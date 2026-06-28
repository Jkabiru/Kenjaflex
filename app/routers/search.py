from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.config import get_settings
from app.database import get_db
from app.models import (
    Favorite,
    HunterProfile,
    Payment,
    PaymentStatus,
    Property,
    PropertyLeadView,
    Search,
    SearchPaymentStatus,
    SearchResult,
    Unit,
    User,
    UserRole,
    VacancySignal,
)
from app.schemas import (
    FavoriteCreate,
    ResultOut,
    SearchCreate,
    SearchCreateResponse,
    SearchUnlockRequest,
    SearchUnlockResponse,
)
from app.services.mpesa import initiate_stk_push
from app.services.ranking import find_candidates, rank_candidates

router = APIRouter(tags=["Search"])
settings = get_settings()


@router.post("/search", response_model=SearchCreateResponse)
def run_search(
    payload: SearchCreate,
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    """AI-Powered House Search Wizard step. Runs the full matching +
    ranking pipeline immediately so `match_count` is accurate, but only
    persists results and reveals them after payment (see /search/{id}/unlock
    and /search/{id}/results)."""
    candidates = find_candidates(
        db,
        commute_lat=payload.commute_lat,
        commute_lng=payload.commute_lng,
        max_commute_minutes=payload.max_commute_minutes,
        unit_type=payload.unit_type,
        max_rent_kes=payload.max_rent_kes,
        amenities=payload.amenities,
        commute_mode=payload.commute_mode,
    )
    ranked = rank_candidates(candidates)

    search = Search(
        hunter_id=hunter.id,
        params_json=payload.model_dump(mode="json"),
        match_count=len(ranked),
        payment_status=SearchPaymentStatus.pending,
        unit_type=payload.unit_type,
        estate=ranked[0].property.estate if ranked else None,
    )
    db.add(search)
    db.flush()

    # Persist ranked results now (so unlocking is instant) but they remain
    # invisible to the hunter via the API until payment_status == paid;
    # /search/{id}/results enforces that gate.
    for i, c in enumerate(ranked, start=1):
        db.add(
            SearchResult(
                search_id=search.id,
                property_id=c.property.id,
                unit_id=c.unit.id,
                commute_time_minutes=c.commute_time_minutes,
                commute_cost_kes=c.commute_cost_kes,
                food_cost_kes=c.food_cost_kes,
                total_cost_kes=c.total_cost_kes,
                amenity_match_score=c.amenity_match_score,
                overall_score=c.overall_score,
                rank=i,
            )
        )

    _maybe_create_vacancy_signal(db, hunter)

    db.commit()

    return SearchCreateResponse(
        search_id=search.id,
        match_count=search.match_count,
        unlock_fee_kes=settings.SEARCH_UNLOCK_FEE_KES,
        payment_status=search.payment_status,
    )


def _maybe_create_vacancy_signal(db: Session, hunter: User) -> None:
    """Vacancy Signal feature: if the hunter has a linked current tenancy,
    notify their current landlord that they appear to be searching."""
    profile = db.get(HunterProfile, hunter.id)
    if profile and profile.current_tenancy_unit_id:
        db.add(VacancySignal(unit_id=profile.current_tenancy_unit_id, hunter_id=hunter.id))


@router.post("/search/{search_id}/unlock", response_model=SearchUnlockResponse)
def unlock_search_results(
    search_id: int,
    payload: SearchUnlockRequest,
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    search = db.get(Search, search_id)
    if not search or search.hunter_id != hunter.id:
        raise HTTPException(status_code=404, detail="Search not found")
    if search.match_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No matching results -- nothing to unlock. See support for zero-result refund policy.",
        )
    if search.payment_status == SearchPaymentStatus.paid:
        return SearchUnlockResponse(
            payment_id=0, status=PaymentStatus.success, checkout_request_id=None,
            message="Already unlocked",
        )

    stk = initiate_stk_push(
        phone=payload.phone,
        amount=settings.SEARCH_UNLOCK_FEE_KES,
        account_reference=f"SEARCH-{search.id}",
        description="Kejaflix search unlock fee",
    )

    payment = Payment(
        user_id=hunter.id,
        search_id=search.id,
        amount=settings.SEARCH_UNLOCK_FEE_KES,
        purpose="search_unlock",
        phone=payload.phone,
        mpesa_checkout_request_id=stk.get("checkout_request_id"),
        status=PaymentStatus.initiated if stk["status"] == "initiated" else PaymentStatus.failed,
    )
    db.add(payment)

    # In MPESA_MOCK_MODE the STK push is simulated successful immediately;
    # in production this transition instead happens in the Daraja callback
    # webhook (see routers/payments.py: POST /payments/mpesa/callback).
    if stk.get("mock") and payment.status == PaymentStatus.initiated:
        payment.status = PaymentStatus.success
        payment.mpesa_receipt = f"MOCKRCPT-{payment.mpesa_checkout_request_id[-8:]}"
        search.payment_status = SearchPaymentStatus.paid
        _record_lead_views(db, search)

    db.commit()
    db.refresh(payment)

    return SearchUnlockResponse(
        payment_id=payment.id,
        status=payment.status,
        checkout_request_id=payment.mpesa_checkout_request_id,
        message="Payment successful, results unlocked" if payment.status == PaymentStatus.success
        else "STK push sent -- approve on your phone to unlock results",
    )


def _record_lead_views(db: Session, search: Search) -> None:
    """Powers the manager-side '30-day dashboard: hunters who received
    contact details per property' requirement."""
    for result in search.results:
        db.add(
            PropertyLeadView(
                property_id=result.property_id,
                hunter_id=search.hunter_id,
                search_id=search.id,
            )
        )


@router.get("/search/{search_id}/results", response_model=list[ResultOut])
def get_search_results(
    search_id: int,
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    search = db.get(Search, search_id)
    if not search or search.hunter_id != hunter.id:
        raise HTTPException(status_code=404, detail="Search not found")
    if search.payment_status != SearchPaymentStatus.paid:
        raise HTTPException(status_code=402, detail="Payment required to view full results")

    out = []
    for r in sorted(search.results, key=lambda x: x.rank):
        unit = db.get(Unit, r.unit_id)
        prop = db.get(Property, r.property_id)
        manager = db.get(User, prop.manager_id)
        wanted = set(a.lower() for a in (search.params_json or {}).get("amenities", []))
        matched = [a for a in (prop.amenities or []) if a.lower() in wanted]
        out.append(
            ResultOut(
                rank=r.rank,
                property_id=prop.id,
                property_name=prop.name,
                property_lat=prop.lat,
                property_lng=prop.lng,
                manager_phone=manager.phone,
                unit_id=unit.id,
                unit_type=unit.type,
                rent=unit.rent,
                commute_time_minutes=r.commute_time_minutes,
                commute_cost_kes=r.commute_cost_kes,
                food_cost_kes=r.food_cost_kes,
                total_cost_kes=r.total_cost_kes,
                amenity_match_score=r.amenity_match_score,
                overall_score=r.overall_score,
                matched_amenities=matched,
            )
        )
    return out


@router.post("/favorites")
def add_favorite(
    payload: FavoriteCreate,
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(Favorite)
        .filter(Favorite.hunter_id == hunter.id, Favorite.unit_id == payload.unit_id)
        .one_or_none()
    )
    if existing:
        return {"message": "Already favorited"}
    db.add(Favorite(hunter_id=hunter.id, unit_id=payload.unit_id))
    db.commit()
    return {"message": "Saved to favorites"}


@router.delete("/favorites/{unit_id}")
def remove_favorite(
    unit_id: int,
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    fav = (
        db.query(Favorite)
        .filter(Favorite.hunter_id == hunter.id, Favorite.unit_id == unit_id)
        .one_or_none()
    )
    if not fav:
        return {"message": "Not favorited"}
    db.delete(fav)
    db.commit()
    return {"message": "Removed from favorites"}


@router.get("/favorites")
def list_favorites(
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    favorites = db.query(Favorite).filter(Favorite.hunter_id == hunter.id).all()
    out = []
    for fav in favorites:
        unit = db.get(Unit, fav.unit_id)
        prop = db.get(Property, unit.property_id) if unit else None
        manager = db.get(User, prop.manager_id) if prop else None
        out.append(
            {
                "favorite_id": fav.id,
                "unit_id": fav.unit_id,
                "property_id": prop.id if prop else None,
                "property_name": prop.name if prop else None,
                "unit_type": unit.type if unit else None,
                "rent": unit.rent if unit else None,
                "manager_phone": manager.phone if manager else None,
            }
        )
    return out
