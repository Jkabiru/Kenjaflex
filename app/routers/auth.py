import random
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_value, verify_value
from app.config import get_settings
from app.database import get_db
from app.models import HunterProfile, OTPVerification, User, UserRole
from app.schemas import (
    RegisterRequest,
    RegisterResponse,
    SocialSignInRequest,
    TokenResponse,
    UserKycUpdate,
    UserNameUpdate,
    UserOut,
    VerifyOTPRequest,
)
from app.services.sms import send_sms
from app.services.storage import save_file
from app.utils import utcnow

router = APIRouter(prefix="/auth", tags=["Authentication"])
settings = get_settings()


def _generate_otp() -> str:
    return "".join(random.choices("0123456789", k=settings.OTP_LENGTH))


@router.post("/register", response_model=RegisterResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Mobile OTP registration. Creates the user record (if new) and sends
    (or, in OTP_DEBUG_ECHO mode, returns) a one-time code to verify the
    phone number."""
    user = db.query(User).filter(User.phone == payload.phone).one_or_none()
    if not user:
        user = User(phone=payload.phone, name=payload.name, role=payload.role)
        db.add(user)
        db.flush()
        if payload.role == UserRole.hunter:
            db.add(HunterProfile(user_id=user.id))
    elif payload.name:
        user.name = payload.name

    code = _generate_otp()
    otp = OTPVerification(
        phone=payload.phone,
        code_hash=hash_value(code),
        expires_at=utcnow() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
    )
    db.add(otp)
    db.commit()

    send_sms(payload.phone, f"Your Kejaflix verification code is {code}")

    return RegisterResponse(
        message="OTP sent",
        debug_otp=code if settings.OTP_DEBUG_ECHO else None,
    )


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    otp = (
        db.query(OTPVerification)
        .filter(OTPVerification.phone == payload.phone, OTPVerification.verified.is_(False))
        .order_by(OTPVerification.created_at.desc())
        .first()
    )
    if not otp:
        raise HTTPException(status_code=400, detail="No pending OTP for this phone number")
    if otp.expires_at < utcnow():
        raise HTTPException(status_code=400, detail="OTP expired, please request a new one")
    if otp.attempts >= 5:
        raise HTTPException(status_code=429, detail="Too many attempts, request a new OTP")

    if not verify_value(payload.code, otp.code_hash):
        otp.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Incorrect code")

    otp.verified = True
    user = db.query(User).filter(User.phone == payload.phone).one()
    user.is_verified = True
    db.commit()

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user_id=user.id, role=user.role)


@router.post("/social", response_model=TokenResponse)
def social_sign_in(payload: SocialSignInRequest, db: Session = Depends(get_db)):
    """Google/Apple sign-in.

    Production implementation: verify `id_token` against the provider
    (Firebase Admin SDK `auth.verify_id_token`, or Apple's public JWKS) to
    recover a verified phone/email + provider user id. Stubbed here to
    trust the caller-supplied phone so the rest of the auth flow (account
    creation, JWT issuance) can be built/tested without provider keys.
    """
    if payload.provider not in ("google", "apple"):
        raise HTTPException(status_code=400, detail="provider must be 'google' or 'apple'")
    if not payload.phone:
        raise HTTPException(status_code=400, detail="phone is required (post provider verification)")

    user = db.query(User).filter(User.phone == payload.phone).one_or_none()
    if not user:
        user = User(phone=payload.phone, role=UserRole.hunter, is_verified=True)
        db.add(user)
        db.flush()
        db.add(HunterProfile(user_id=user.id))
        db.commit()

    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token, user_id=user.id, role=user.role)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UserNameUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.name = payload.name
    db.commit()
    db.refresh(user)
    return user


@router.patch("/me/kyc", response_model=UserOut)
def update_kyc(
    payload: UserKycUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Property Manager / Field Agent identity verification. Real
    implementation would flag is_verified pending an admin/automated check
    against the ID/business registry; stubbed here as self-attested so the
    rest of the onboarding flow can be built without that integration."""
    user.id_or_business_number = payload.id_or_business_number
    if payload.company_name is not None:
        user.company_name = payload.company_name
    db.commit()
    db.refresh(user)
    return user


@router.post("/me/photo", response_model=UserOut)
def upload_profile_photo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.photo_url = save_file(file, f"profile-photos/{user.id}")
    db.commit()
    db.refresh(user)
    return user
