from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.config import get_settings
from app.database import get_db
from app.models import (
    AgentVerificationStatus,
    CaptureStatus,
    FieldAgentCapture,
    FieldAgentPayout,
    PaymentStatus,
    Property,
    User,
    UserRole,
)
from app.schemas import (
    FieldAgentCaptureCreate,
    FieldAgentCaptureOut,
    FieldAgentEarningsOut,
    FieldAgentNameUpdate,
    FieldAgentProfileOut,
    PayoutOut,
    PayoutRequest,
)
from app.services.geo import haversine_distance_km
from app.services.mpesa import initiate_b2c_payout
from app.services.storage import save_file

router = APIRouter(prefix="/field-agent", tags=["Field Agent"])
settings = get_settings()


# ---------------------------------------------------------------------------
# Profile & KYC
# ---------------------------------------------------------------------------

@router.get("/profile", response_model=FieldAgentProfileOut)
def get_profile(agent: User = Depends(require_roles(UserRole.field_agent))):
    return agent


@router.patch("/profile", response_model=FieldAgentProfileOut)
def update_profile(
    payload: FieldAgentNameUpdate,
    agent: User = Depends(require_roles(UserRole.field_agent)),
    db: Session = Depends(get_db),
):
    agent.name = payload.name
    if agent.agent_verification_status == AgentVerificationStatus.rejected:
        agent.agent_verification_status = AgentVerificationStatus.pending
        agent.agent_verification_rejection_reason = None
    db.commit()
    db.refresh(agent)
    return agent


@router.post("/student-id-photo", response_model=FieldAgentProfileOut)
def upload_student_id_photo(
    file: UploadFile = File(...),
    agent: User = Depends(require_roles(UserRole.field_agent)),
    db: Session = Depends(get_db),
):
    agent.student_id_photo_url = save_file(file, f"student-id-photos/{agent.id}")
    if agent.agent_verification_status == AgentVerificationStatus.rejected:
        agent.agent_verification_status = AgentVerificationStatus.pending
        agent.agent_verification_rejection_reason = None
    db.commit()
    db.refresh(agent)
    return agent


def _is_duplicate(db: Session, lat: float, lng: float) -> bool:
    """Auto-reject if within FIELD_AGENT_DUPLICATE_RADIUS_M of an existing
    *approved* property."""
    radius_km = settings.FIELD_AGENT_DUPLICATE_RADIUS_M / 1000
    approved = db.query(Property).filter(Property.status == "approved").all()
    for prop in approved:
        if haversine_distance_km(lat, lng, prop.lat, prop.lng) <= radius_km:
            return True
    return False


@router.post("/capture", response_model=FieldAgentCaptureOut)
def submit_capture(
    payload: FieldAgentCaptureCreate,
    agent: User = Depends(require_roles(UserRole.field_agent)),
    db: Session = Depends(get_db),
):
    if agent.agent_verification_status != AgentVerificationStatus.verified:
        raise HTTPException(status_code=403, detail="Student status not yet verified")
    if len(payload.photos) < 3:
        raise HTTPException(status_code=400, detail="Minimum 3 photographs required")

    if _is_duplicate(db, payload.gps_lat, payload.gps_lng):
        capture = FieldAgentCapture(
            agent_id=agent.id,
            property_data_json=payload.model_dump(exclude={"photos"}, mode="json"),
            gps_lat=payload.gps_lat,
            gps_lng=payload.gps_lng,
            photos=payload.photos,
            status=CaptureStatus.rejected,
            admin_notes=(
                f"Auto-rejected: within {settings.FIELD_AGENT_DUPLICATE_RADIUS_M}m "
                "of an existing approved property"
            ),
        )
        db.add(capture)
        db.commit()
        db.refresh(capture)
        return capture

    capture = FieldAgentCapture(
        agent_id=agent.id,
        property_data_json=payload.model_dump(exclude={"photos"}, mode="json"),
        gps_lat=payload.gps_lat,
        gps_lng=payload.gps_lng,
        photos=payload.photos,
        status=CaptureStatus.under_review,
    )
    db.add(capture)
    db.commit()
    db.refresh(capture)
    return capture


@router.get("/captures", response_model=list[FieldAgentCaptureOut])
def list_my_captures(
    agent: User = Depends(require_roles(UserRole.field_agent)),
    db: Session = Depends(get_db),
):
    return db.query(FieldAgentCapture).filter(FieldAgentCapture.agent_id == agent.id).all()


@router.get("/captures/{capture_id}", response_model=FieldAgentCaptureOut)
def get_capture(
    capture_id: int,
    agent: User = Depends(require_roles(UserRole.field_agent)),
    db: Session = Depends(get_db),
):
    capture = db.get(FieldAgentCapture, capture_id)
    if not capture or capture.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Capture not found")
    return capture


@router.get("/payouts", response_model=list[PayoutOut])
def list_my_payouts(
    agent: User = Depends(require_roles(UserRole.field_agent)),
    db: Session = Depends(get_db),
):
    return (
        db.query(FieldAgentPayout)
        .filter(FieldAgentPayout.agent_id == agent.id)
        .order_by(FieldAgentPayout.created_at.desc())
        .all()
    )


@router.get("/earnings", response_model=FieldAgentEarningsOut)
def get_earnings(
    agent: User = Depends(require_roles(UserRole.field_agent)),
    db: Session = Depends(get_db),
):
    captures = (
        db.query(FieldAgentCapture)
        .filter(FieldAgentCapture.agent_id == agent.id, FieldAgentCapture.status == CaptureStatus.approved)
        .all()
    )
    total_earned = sum(c.reward_amount for c in captures)

    payouts = (
        db.query(FieldAgentPayout)
        .filter(FieldAgentPayout.agent_id == agent.id, FieldAgentPayout.status == PaymentStatus.success)
        .all()
    )
    total_paid_out = sum(p.amount for p in payouts)

    return FieldAgentEarningsOut(
        total_approved_captures=len(captures),
        total_earned_kes=total_earned,
        total_paid_out_kes=total_paid_out,
        available_balance_kes=total_earned - total_paid_out,
    )


@router.post("/payout", response_model=PayoutOut)
def request_payout(
    payload: PayoutRequest,
    agent: User = Depends(require_roles(UserRole.field_agent)),
    db: Session = Depends(get_db),
):
    earnings = get_earnings(agent, db)
    if earnings.available_balance_kes < settings.FIELD_AGENT_MIN_PAYOUT_KES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Minimum payout threshold is KES {settings.FIELD_AGENT_MIN_PAYOUT_KES}. "
                f"Available balance: KES {earnings.available_balance_kes:.0f}"
            ),
        )

    result = initiate_b2c_payout(
        phone=payload.phone,
        amount=int(earnings.available_balance_kes),
        remarks="Kejaflix field agent reward payout",
    )

    payout = FieldAgentPayout(
        agent_id=agent.id,
        amount=earnings.available_balance_kes,
        mpesa_receipt=result.get("mpesa_receipt"),
        status=PaymentStatus.success if result["status"] == "success" else PaymentStatus.initiated,
    )
    db.add(payout)
    db.commit()
    db.refresh(payout)
    return payout
