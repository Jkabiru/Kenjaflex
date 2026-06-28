from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import HunterProfile, User, UserRole
from app.schemas import HunterProfileOut, HunterProfileUpdate

router = APIRouter(prefix="/hunter-profile", tags=["Hunter Profile"])


@router.get("", response_model=HunterProfileOut)
def get_my_profile(
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    profile = db.get(HunterProfile, hunter.id)
    if not profile:
        profile = HunterProfile(user_id=hunter.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.patch("", response_model=HunterProfileOut)
def update_my_profile(
    payload: HunterProfileUpdate,
    hunter: User = Depends(require_roles(UserRole.hunter)),
    db: Session = Depends(get_db),
):
    profile = db.get(HunterProfile, hunter.id)
    if not profile:
        profile = HunterProfile(user_id=hunter.id)
        db.add(profile)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile
