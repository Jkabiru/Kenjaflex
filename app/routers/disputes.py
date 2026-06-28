from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import (
    Dispute,
    DisputeStatus,
    Payment,
    PaymentStatus,
    Search,
    SearchPaymentStatus,
    User,
    UserRole,
)
from app.schemas import DisputeCreate, DisputeOut

router = APIRouter(prefix="/hunter", tags=["Disputes"])


@router.post("/disputes", response_model=DisputeOut, status_code=201)
def file_dispute(
    payload: DisputeCreate,
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    search = db.get(Search, payload.search_id)
    if not search or search.hunter_id != hunter.id:
        raise HTTPException(status_code=404, detail="Search not found")
    if search.payment_status != SearchPaymentStatus.paid:
        raise HTTPException(status_code=400, detail="Only paid searches can be disputed")

    if db.query(Dispute).filter(Dispute.search_id == payload.search_id).one_or_none():
        raise HTTPException(status_code=409, detail="A dispute has already been filed for this search")

    payment = (
        db.query(Payment)
        .filter(
            Payment.search_id == payload.search_id,
            Payment.purpose == "search_unlock",
            Payment.status == PaymentStatus.success,
        )
        .first()
    )
    if not payment:
        raise HTTPException(status_code=400, detail="No successful payment found for this search")

    dispute = Dispute(
        hunter_id=hunter.id,
        search_id=payload.search_id,
        reason=payload.reason,
        amount=payment.amount,
    )
    db.add(dispute)
    db.commit()
    db.refresh(dispute)
    return dispute


@router.get("/disputes", response_model=list[DisputeOut])
def list_my_disputes(
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    return (
        db.query(Dispute)
        .filter(Dispute.hunter_id == hunter.id)
        .order_by(Dispute.created_at.desc())
        .all()
    )
