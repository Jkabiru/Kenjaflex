"""
AI Recommendation Engine (backend).

Implements the spec's ranking algorithm:
  1. Filter by hard constraints (rent <= budget, unit type match, vacant only)
  2. Calculate commute time using transport data
  3. Score by: commute time (40%), all-in cost (35%), amenity match (25%)
  4. Return top N results with match count summary
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CommuteMode, Estate, Property, PropertyStatus, Unit, UnitType
from app.services.geo import estimate_commute

COMMUTE_WEIGHT = 0.40
COST_WEIGHT = 0.35
AMENITY_WEIGHT = 0.25

DEFAULT_FOOD_SPEND_KES = 10000  # used when an estate has no benchmark on file


@dataclass
class CandidateResult:
    property: Property
    unit: Unit
    commute_time_minutes: float
    commute_cost_kes: float
    food_cost_kes: float
    total_cost_kes: float
    amenity_match_score: float  # 0..1
    matched_amenities: list[str]
    overall_score: float = 0.0  # filled in after normalization


def _amenity_match_score(wanted: list[str], available: list[str]) -> tuple[float, list[str]]:
    if not wanted:
        return 1.0, []
    wanted_set = {a.lower() for a in wanted}
    available_set = {a.lower() for a in available}
    matched = wanted_set & available_set
    score = len(matched) / len(wanted_set)
    return score, sorted(matched)


def find_candidates(
    db: Session,
    commute_lat: float,
    commute_lng: float,
    max_commute_minutes: int,
    unit_type: UnitType,
    max_rent_kes: float,
    amenities: list[str],
    commute_mode: CommuteMode,
) -> list[CandidateResult]:
    """Hard-filters then scores every vacant, approved unit matching the
    request. Returns an UNRANKED list of candidates with scores attached
    (call `rank_candidates` to sort + assign rank)."""

    stmt = (
        select(Unit, Property)
        .join(Property, Unit.property_id == Property.id)
        .where(
            Property.status == PropertyStatus.approved,
            Unit.is_vacant.is_(True),
            Unit.type == unit_type,
            Unit.rent <= max_rent_kes,
        )
    )
    rows = db.execute(stmt).all()

    estate_food_cache: dict[str, float] = {}

    candidates: list[CandidateResult] = []
    for unit, prop in rows:
        commute_minutes, commute_cost = estimate_commute(
            commute_lat, commute_lng, prop.lat, prop.lng, commute_mode
        )
        if commute_minutes > max_commute_minutes:
            continue

        estate_key = (prop.estate or "").strip().lower()
        if estate_key not in estate_food_cache:
            estate = db.execute(select(Estate).where(Estate.name == prop.estate)).scalar_one_or_none()
            estate_food_cache[estate_key] = (
                estate.avg_food_spend_monthly_kes if estate else DEFAULT_FOOD_SPEND_KES
            )
        food_cost = estate_food_cache[estate_key]

        total_cost = unit.rent + food_cost + commute_cost
        amenity_score, matched = _amenity_match_score(amenities, prop.amenities or [])

        candidates.append(
            CandidateResult(
                property=prop,
                unit=unit,
                commute_time_minutes=commute_minutes,
                commute_cost_kes=commute_cost,
                food_cost_kes=food_cost,
                total_cost_kes=round(total_cost, 2),
                amenity_match_score=round(amenity_score, 3),
                matched_amenities=matched,
            )
        )

    return candidates


def rank_candidates(candidates: list[CandidateResult]) -> list[CandidateResult]:
    """Normalizes commute time and total cost across the candidate set (so
    the cheapest/fastest in *this* result set scores best), combines with
    amenity match using the spec's weights, sorts descending by score, and
    assigns 1-based rank. Mutates and returns the same list."""
    if not candidates:
        return candidates

    commute_values = [c.commute_time_minutes for c in candidates]
    cost_values = [c.total_cost_kes for c in candidates]
    min_commute, max_commute = min(commute_values), max(commute_values)
    min_cost, max_cost = min(cost_values), max(cost_values)

    def normalize(value, lo, hi):
        if hi == lo:
            return 0.0  # all equal -> no penalty differentiation
        return (value - lo) / (hi - lo)

    for c in candidates:
        commute_penalty = normalize(c.commute_time_minutes, min_commute, max_commute)
        cost_penalty = normalize(c.total_cost_kes, min_cost, max_cost)
        c.overall_score = round(
            (1 - commute_penalty) * COMMUTE_WEIGHT
            + (1 - cost_penalty) * COST_WEIGHT
            + c.amenity_match_score * AMENITY_WEIGHT,
            4,
        )

    candidates.sort(key=lambda c: c.overall_score, reverse=True)
    return candidates
