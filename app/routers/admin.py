from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.services.mpesa import initiate_b2c_payout
from app.models import (
    AgentVerificationStatus,
    Amenity,
    CaptureStatus,
    Dispute,
    DisputeResolution,
    DisputeStatus,
    Estate,
    FieldAgentCapture,
    FieldAgentPayout,
    Payment,
    PaymentStatus,
    Property,
    PropertyStatus,
    Search,
    SearchPaymentStatus,
    Unit,
    User,
    UserRole,
)
from app.schemas import (
    AgentKycRejectRequest,
    AmenityCreate,
    AmenityOut,
    AnalyticsOut,
    DisputeOut,
    DisputeResolveRequest,
    EstateCreate,
    EstateOut,
    ExecutiveDashboardOut,
    FieldAgentProfileOut,
    PropertyOut,
    PropertyVerifyRequest,
    RevenueOut,
    UserOut,
)
from app.config import get_settings
from app.utils import utcnow

router = APIRouter(prefix="/admin", tags=["Admin"])
settings = get_settings()


# ---------------------------------------------------------------------------
# Property Verification Queue
# ---------------------------------------------------------------------------

@router.get("/properties/pending", response_model=list[PropertyOut])
def verification_queue(
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    return db.query(Property).filter(Property.status == PropertyStatus.pending).all()


@router.post("/properties/{property_id}/verify", response_model=PropertyOut)
def verify_property(
    property_id: int,
    payload: PropertyVerifyRequest,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    prop.status = PropertyStatus.approved if payload.approve else PropertyStatus.rejected
    prop.rejection_reason = None if payload.approve else payload.reason
    db.commit()
    db.refresh(prop)
    return prop


# ---------------------------------------------------------------------------
# Field Agent Capture Review (-> approve triggers the KES 500 reward credit)
# ---------------------------------------------------------------------------

@router.get("/field-agent/captures/pending")
def pending_captures(
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    captures = (
        db.query(FieldAgentCapture).filter(FieldAgentCapture.status == CaptureStatus.under_review).all()
    )
    return [
        {
            "id": c.id,
            "agent_id": c.agent_id,
            "property_data": c.property_data_json,
            "gps_lat": c.gps_lat,
            "gps_lng": c.gps_lng,
            "photos": c.photos,
            "created_at": c.created_at,
        }
        for c in captures
    ]


@router.post("/field-agent/captures/{capture_id}/review")
def review_capture(
    capture_id: int,
    approve: bool,
    notes: str | None = None,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    capture = db.get(FieldAgentCapture, capture_id)
    if not capture:
        raise HTTPException(status_code=404, detail="Capture not found")

    capture.status = CaptureStatus.approved if approve else CaptureStatus.rejected
    capture.admin_notes = notes
    if approve:
        capture.reward_amount = settings.FIELD_AGENT_REWARD_KES
    db.commit()
    return {"id": capture.id, "status": capture.status, "reward_amount": capture.reward_amount}


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@router.get("/users", response_model=list[UserOut])
def search_users(
    role: UserRole | None = None,
    q: str | None = None,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if role:
        query = query.filter(User.role == role)
    if q:
        query = query.filter((User.name.ilike(f"%{q}%")) | (User.phone.ilike(f"%{q}%")))
    return query.all()


# ---------------------------------------------------------------------------
# Executive Dashboard & Analytics
# ---------------------------------------------------------------------------

@router.get("/dashboard", response_model=ExecutiveDashboardOut)
def executive_dashboard(
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    total_properties = db.query(func.count(Property.id)).filter(
        Property.status == PropertyStatus.approved
    ).scalar()
    total_units = db.query(func.count(Unit.id)).scalar() or 0
    occupied_units = db.query(func.count(Unit.id)).filter(Unit.is_vacant.is_(False)).scalar() or 0
    vacant_units = total_units - occupied_units

    monthly_revenue = (
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.status == PaymentStatus.success)
        .scalar()
    )

    thirty_days_ago = utcnow() - timedelta(days=30)
    registrations = db.query(func.count(User.id)).filter(User.created_at >= thirty_days_ago).scalar()

    return ExecutiveDashboardOut(
        total_properties=total_properties or 0,
        total_units=total_units,
        occupied_units=occupied_units,
        vacant_units=vacant_units,
        occupancy_rate_pct=round((occupied_units / total_units * 100), 1) if total_units else 0.0,
        monthly_revenue_kes=float(monthly_revenue or 0),
        registrations_last_30_days=registrations or 0,
    )


@router.get("/analytics", response_model=AnalyticsOut)
def analytics(
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    searches_total = db.query(func.count(Search.id)).scalar() or 0
    paid_searches = (
        db.query(func.count(Search.id))
        .filter(Search.payment_status == SearchPaymentStatus.paid)
        .scalar() or 0
    )
    conversion = round((paid_searches / searches_total * 100), 1) if searches_total else 0.0

    # Unit-type popularity from search events (what hunters are actually looking for)
    top_unit_types = (
        db.query(Search.unit_type, func.count(Search.id).label("count"))
        .filter(Search.unit_type.isnot(None))
        .group_by(Search.unit_type)
        .order_by(func.count(Search.id).desc())
        .limit(5)
        .all()
    )

    # Top estates from search results (where hunters are finding matches)
    top_estates = (
        db.query(Search.estate, func.count(Search.id).label("count"))
        .filter(Search.estate.isnot(None))
        .group_by(Search.estate)
        .order_by(func.count(Search.id).desc())
        .limit(5)
        .all()
    )

    # Searches by hour-of-day (extract works on both SQLite and PostgreSQL)
    hour_rows = (
        db.query(
            extract("hour", Search.created_at).label("hour"),
            func.count(Search.id).label("count"),
        )
        .group_by("hour")
        .order_by("hour")
        .all()
    )

    return AnalyticsOut(
        searches_total=searches_total,
        paid_searches=paid_searches,
        search_to_payment_conversion_pct=conversion,
        top_unit_types=[{"unit_type": t.value, "count": c} for t, c in top_unit_types],
        top_estates=[{"estate": e, "count": c} for e, c in top_estates],
        searches_by_hour=[{"hour": int(h), "count": c} for h, c in hour_rows],
    )


# ---------------------------------------------------------------------------
# Disputes (Decision 2)
# ---------------------------------------------------------------------------

@router.get("/disputes", response_model=list[DisputeOut])
def list_disputes(
    status: DisputeStatus | None = None,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    query = db.query(Dispute)
    if status:
        query = query.filter(Dispute.status == status)
    return query.order_by(Dispute.created_at).all()


@router.post("/disputes/{dispute_id}/resolve", response_model=DisputeOut)
def resolve_dispute(
    dispute_id: int,
    payload: DisputeResolveRequest,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    dispute = db.get(Dispute, dispute_id)
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    if dispute.status == DisputeStatus.resolved:
        raise HTTPException(status_code=409, detail="Dispute is already resolved")

    if payload.approve:
        hunter = db.get(User, dispute.hunter_id)
        initiate_b2c_payout(
            phone=hunter.phone,
            amount=int(dispute.amount),
            remarks=f"Kejaflix search refund for dispute #{dispute.id}",
        )
        dispute.resolution = DisputeResolution.refunded
        search = db.get(Search, dispute.search_id)
        search.payment_status = SearchPaymentStatus.refunded
    else:
        dispute.resolution = DisputeResolution.denied

    dispute.status = DisputeStatus.resolved
    db.commit()
    db.refresh(dispute)
    return dispute


# ---------------------------------------------------------------------------
# Field Agent KYC Queue (Decision 1)
# ---------------------------------------------------------------------------

@router.get("/field-agents", response_model=list[FieldAgentProfileOut])
def list_field_agents(
    status: AgentVerificationStatus | None = None,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    query = db.query(User).filter(User.role == UserRole.field_agent)
    if status:
        query = query.filter(User.agent_verification_status == status)
    return query.order_by(User.created_at).all()


@router.post("/field-agents/{user_id}/verify", response_model=FieldAgentProfileOut)
def verify_field_agent(
    user_id: int,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    agent = db.get(User, user_id)
    if not agent or agent.role != UserRole.field_agent:
        raise HTTPException(status_code=404, detail="Field agent not found")
    agent.agent_verification_status = AgentVerificationStatus.verified
    agent.agent_verification_rejection_reason = None
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/field-agents/{user_id}/reject", response_model=FieldAgentProfileOut)
def reject_field_agent(
    user_id: int,
    payload: AgentKycRejectRequest,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    agent = db.get(User, user_id)
    if not agent or agent.role != UserRole.field_agent:
        raise HTTPException(status_code=404, detail="Field agent not found")
    agent.agent_verification_status = AgentVerificationStatus.rejected
    agent.agent_verification_rejection_reason = payload.reason
    db.commit()
    db.refresh(agent)
    return agent


# ---------------------------------------------------------------------------
# Content management — Estates
# ---------------------------------------------------------------------------

@router.get("/estates", response_model=list[EstateOut])
def list_estates(
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    return db.query(Estate).order_by(Estate.name).all()


@router.post("/estates", response_model=EstateOut, status_code=201)
def create_estate(
    payload: EstateCreate,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    if db.query(Estate).filter(Estate.name == payload.name).one_or_none():
        raise HTTPException(status_code=409, detail=f"Estate '{payload.name}' already exists")
    estate = Estate(**payload.model_dump())
    db.add(estate)
    db.commit()
    db.refresh(estate)
    return estate


@router.delete("/estates/{estate_id}", status_code=204)
def delete_estate(
    estate_id: int,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    estate = db.get(Estate, estate_id)
    if not estate:
        raise HTTPException(status_code=404, detail="Estate not found")
    db.delete(estate)
    db.commit()


# ---------------------------------------------------------------------------
# Content management — Amenities
# ---------------------------------------------------------------------------

@router.get("/amenities", response_model=list[AmenityOut])
def list_amenities(
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    return db.query(Amenity).order_by(Amenity.name).all()


@router.post("/amenities", response_model=AmenityOut, status_code=201)
def create_amenity(
    payload: AmenityCreate,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    if db.query(Amenity).filter(Amenity.name == payload.name).one_or_none():
        raise HTTPException(status_code=409, detail=f"Amenity '{payload.name}' already exists")
    amenity = Amenity(name=payload.name)
    db.add(amenity)
    db.commit()
    db.refresh(amenity)
    return amenity


@router.delete("/amenities/{amenity_id}", status_code=204)
def delete_amenity(
    amenity_id: int,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    amenity = db.get(Amenity, amenity_id)
    if not amenity:
        raise HTTPException(status_code=404, detail="Amenity not found")
    db.delete(amenity)
    db.commit()


# ---------------------------------------------------------------------------
# Capture review — status-filtered list (adds resolved view to existing endpoint)
# ---------------------------------------------------------------------------

@router.get("/field-agent/captures")
def list_captures(
    status: CaptureStatus | None = None,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    query = db.query(FieldAgentCapture)
    if status:
        query = query.filter(FieldAgentCapture.status == status)
    captures = query.order_by(FieldAgentCapture.created_at).all()
    return [
        {
            "id": c.id,
            "agent_id": c.agent_id,
            "property_data": c.property_data_json,
            "gps_lat": c.gps_lat,
            "gps_lng": c.gps_lng,
            "photos": c.photos,
            "status": c.status,
            "admin_notes": c.admin_notes,
            "reward_amount": c.reward_amount,
            "created_at": c.created_at,
        }
        for c in captures
    ]


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------

@router.get("/revenue", response_model=RevenueOut)
def revenue(
    range: int = 30,
    admin: User = Depends(require_roles(UserRole.admin)),
    db: Session = Depends(get_db),
):
    if range not in (7, 30, 90):
        raise HTTPException(status_code=400, detail="range must be 7, 30, or 90")

    cutoff = utcnow() - timedelta(days=range)

    payments = (
        db.query(Payment)
        .filter(Payment.created_at >= cutoff, Payment.purpose == "search_unlock")
        .all()
    )
    payouts = (
        db.query(FieldAgentPayout)
        .filter(FieldAgentPayout.created_at >= cutoff)
        .all()
    )

    unlock_revenue = sum(p.amount for p in payments if p.status == PaymentStatus.success)
    payout_outflow = sum(p.amount for p in payouts if p.status == PaymentStatus.success)
    failed_count = (
        sum(1 for p in payments if p.status == PaymentStatus.failed)
        + sum(1 for p in payouts if p.status == PaymentStatus.failed)
    )

    transactions = sorted(
        [
            {
                "id": f"pay_{p.id}",
                "type": "search_unlock",
                "user_id": p.user_id,
                "amount": p.amount,
                "mpesa_receipt": p.mpesa_receipt,
                "status": p.status.value,
                "created_at": p.created_at.isoformat(),
            }
            for p in payments
        ] + [
            {
                "id": f"payout_{p.id}",
                "type": "field_agent_payout",
                "user_id": p.agent_id,
                "amount": p.amount,
                "mpesa_receipt": p.mpesa_receipt,
                "status": p.status.value,
                "created_at": p.created_at.isoformat(),
            }
            for p in payouts
        ],
        key=lambda t: t["created_at"],
        reverse=True,
    )

    return RevenueOut(
        period_days=range,
        search_unlock_revenue_kes=unlock_revenue,
        field_agent_payout_outflow_kes=payout_outflow,
        net_kes=unlock_revenue - payout_outflow,
        failed_transaction_count=failed_count,
        transactions=transactions,
    )
