from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Payment, PaymentStatus, Search, SearchPaymentStatus
from app.routers.search import _record_lead_views

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/mpesa/callback")
async def mpesa_stk_callback(payload: dict, db: Session = Depends(get_db)):
    """Safaricom Daraja STK Push result callback.

    Expected (real) Daraja shape:
    {
      "Body": {"stkCallback": {
        "CheckoutRequestID": "...",
        "ResultCode": 0,
        "ResultDesc": "...",
        "CallbackMetadata": {"Item": [{"Name": "MpesaReceiptNumber", "Value": "..."}]}
      }}
    }
    In MPESA_MOCK_MODE this endpoint is never actually hit -- the unlock
    endpoint marks payment success synchronously -- but it's implemented and
    tested here so flipping MPESA_MOCK_MODE off in production needs no
    further code changes.
    """
    stk = payload.get("Body", {}).get("stkCallback", {})
    checkout_id = stk.get("CheckoutRequestID")
    result_code = stk.get("ResultCode")

    payment = (
        db.query(Payment).filter(Payment.mpesa_checkout_request_id == checkout_id).one_or_none()
    )
    if not payment:
        return {"ResultCode": 0, "ResultDesc": "Accepted (no matching payment found)"}

    if result_code == 0:
        receipt = next(
            (
                item["Value"]
                for item in stk.get("CallbackMetadata", {}).get("Item", [])
                if item.get("Name") == "MpesaReceiptNumber"
            ),
            None,
        )
        payment.status = PaymentStatus.success
        payment.mpesa_receipt = receipt

        if payment.search_id:
            search = db.get(Search, payment.search_id)
            search.payment_status = SearchPaymentStatus.paid
            _record_lead_views(db, search)
    else:
        payment.status = PaymentStatus.failed

    db.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
