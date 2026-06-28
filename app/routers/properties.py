from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.auth import require_roles
from app.database import get_db
from app.models import Property, PropertyLeadView, PropertyStatus, Tenant, Unit, User, UserRole, VacancySignal
from app.schemas import (
    PropertyCreate,
    PropertyOut,
    RentReminderRequest,
    TenantCreate,
    TenantOut,
    UnitCreate,
    UnitOut,
    UnitVacancyUpdate,
)
from app.services.sms import send_sms
from app.services.storage import save_file
from app.utils import utcnow

router = APIRouter(tags=["Properties"])

MAX_PHOTOS_PER_PROPERTY = 6


def _get_owned_property(db: Session, property_id: int, manager: User) -> Property:
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.manager_id != manager.id:
        raise HTTPException(status_code=403, detail="Not your property")
    return prop


# ---------------------------------------------------------------------------
# Property Onboarding Wizard (steps 1-5 collapsed into one create call;
# step 6 occupancy is handled via the tenant endpoints below; step 7 photos
# via /properties/{id}/photos; step 8 review is a client-side concern that
# simply calls this same endpoint once confirmed).
# ---------------------------------------------------------------------------

@router.post("/properties", response_model=PropertyOut)
def create_property(
    payload: PropertyCreate,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    prop = Property(manager_id=manager.id, **payload.model_dump())
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


@router.get("/properties/{property_id}", response_model=PropertyOut)
def get_property(property_id: int, db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


@router.get("/properties", response_model=list[PropertyOut])
def list_my_properties(
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    return db.query(Property).filter(Property.manager_id == manager.id).all()


@router.post("/properties/{property_id}/photos", response_model=PropertyOut)
def upload_property_photos(
    property_id: int,
    files: list[UploadFile] = File(...),
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    prop = _get_owned_property(db, property_id, manager)
    if len(prop.photos) + len(files) > MAX_PHOTOS_PER_PROPERTY:
        raise HTTPException(
            status_code=400,
            detail=f"Max {MAX_PHOTOS_PER_PROPERTY} photos per property",
        )
    urls = [save_file(f, f"properties/{property_id}") for f in files]
    prop.photos = [*prop.photos, *urls]
    db.commit()
    db.refresh(prop)
    return prop


@router.post("/properties/{property_id}/submit", response_model=PropertyOut)
def submit_property_for_review(
    property_id: int,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    """Step 8 -- Review & Submit. Moves the property into the admin
    verification queue."""
    prop = _get_owned_property(db, property_id, manager)
    prop.status = PropertyStatus.pending
    db.commit()
    db.refresh(prop)
    return prop


# ---------------------------------------------------------------------------
# Units (Step 3 -- Unit Configuration, plus ongoing vacancy management)
# ---------------------------------------------------------------------------

@router.post("/properties/{property_id}/units", response_model=UnitOut)
def add_unit(
    property_id: int,
    payload: UnitCreate,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    _get_owned_property(db, property_id, manager)
    unit = Unit(property_id=property_id, **payload.model_dump())
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit


@router.get("/properties/{property_id}/units", response_model=list[UnitOut])
def list_units(property_id: int, db: Session = Depends(get_db)):
    return db.query(Unit).filter(Unit.property_id == property_id).all()


@router.patch("/units/{unit_id}/vacancy", response_model=UnitOut)
def set_unit_vacancy(
    unit_id: int,
    payload: UnitVacancyUpdate,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    """Toggling occupancy here is what makes a unit immediately appear (or
    disappear) from hunter search results -- find_candidates() in
    services/ranking.py filters on `Unit.is_vacant`."""
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    _get_owned_property(db, unit.property_id, manager)
    unit.is_vacant = payload.is_vacant
    unit.expected_vacancy_date = payload.expected_vacancy_date
    db.commit()
    db.refresh(unit)
    return unit


# ---------------------------------------------------------------------------
# Tenants (Step 6 -- Occupancy / ongoing Tenant Management)
# ---------------------------------------------------------------------------

@router.post("/units/{unit_id}/tenants", response_model=TenantOut)
def add_tenant(
    unit_id: int,
    payload: TenantCreate,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    unit = db.get(Unit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    _get_owned_property(db, unit.property_id, manager)

    tenant = Tenant(unit_id=unit_id, **payload.model_dump())
    unit.is_vacant = False
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/properties/{property_id}/tenants", response_model=list[TenantOut])
def list_tenants(
    property_id: int,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    _get_owned_property(db, property_id, manager)
    return (
        db.query(Tenant)
        .join(Unit, Tenant.unit_id == Unit.id)
        .filter(Unit.property_id == property_id)
        .all()
    )


@router.post("/tenants/{tenant_id}/archive", response_model=TenantOut)
def archive_departed_tenant(
    tenant_id: int,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    """Archives a departed tenant and auto-marks their unit vacant."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    unit = db.get(Unit, tenant.unit_id)
    _get_owned_property(db, unit.property_id, manager)

    tenant.is_active = False
    tenant.moved_out_date = utcnow()
    unit.is_vacant = True
    db.commit()
    db.refresh(tenant)
    return tenant


@router.post("/properties/{property_id}/tenants/rent-reminders")
def send_rent_reminders(
    property_id: int,
    payload: RentReminderRequest,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    _get_owned_property(db, property_id, manager)
    query = (
        db.query(Tenant)
        .join(Unit, Tenant.unit_id == Unit.id)
        .filter(Unit.property_id == property_id, Tenant.is_active.is_(True))
    )
    if payload.tenant_ids:
        query = query.filter(Tenant.id.in_(payload.tenant_ids))
    tenants = query.all()

    for tenant in tenants:
        send_sms(
            tenant.phone,
            f"Hi {tenant.name}, this is a reminder that your rent of KES "
            f"{tenant.monthly_rent:,.0f} is due. Outstanding arrears: "
            f"KES {tenant.arrears:,.0f}.",
        )
    return {"sent_count": len(tenants)}


@router.get("/properties/{property_id}/rent-arrears")
def rent_arrears_dashboard(
    property_id: int,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    _get_owned_property(db, property_id, manager)
    tenants = (
        db.query(Tenant)
        .join(Unit, Tenant.unit_id == Unit.id)
        .filter(Unit.property_id == property_id, Tenant.is_active.is_(True), Tenant.arrears > 0)
        .all()
    )
    total = sum(t.arrears for t in tenants)
    return {
        "total_arrears_kes": total,
        "tenants": [
            {"tenant_id": t.id, "name": t.name, "unit_id": t.unit_id, "arrears_kes": t.arrears}
            for t in tenants
        ],
    }


# ---------------------------------------------------------------------------
# Vacancy & Lead Visibility
# ---------------------------------------------------------------------------

@router.get("/properties/{property_id}/vacancy-signals")
def list_vacancy_signals(
    property_id: int,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    """'Your tenant [Name] in Unit [X] appears to be searching for a new
    house' notifications -- created by the search router when a hunter with
    a linked tenancy runs a search."""
    _get_owned_property(db, property_id, manager)
    signals = (
        db.query(VacancySignal)
        .join(Unit, VacancySignal.unit_id == Unit.id)
        .filter(Unit.property_id == property_id)
        .all()
    )
    return [
        {
            "id": s.id,
            "unit_id": s.unit_id,
            "hunter_id": s.hunter_id,
            "status": s.status,
            "created_at": s.created_at,
        }
        for s in signals
    ]


@router.post("/vacancy-signals/{signal_id}/respond")
def respond_to_vacancy_signal(
    signal_id: int,
    confirm: bool,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    signal = db.get(VacancySignal, signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    unit = db.get(Unit, signal.unit_id)
    _get_owned_property(db, unit.property_id, manager)

    from app.models import VacancySignalStatus

    signal.status = VacancySignalStatus.confirmed if confirm else VacancySignalStatus.dismissed
    if confirm:
        unit.is_vacant = True
        unit.expected_vacancy_date = utcnow() + timedelta(days=30)
    db.commit()
    return {"status": signal.status}


# ---------------------------------------------------------------------------
# Rent payments & lead visibility
# ---------------------------------------------------------------------------

@router.post("/tenants/{tenant_id}/record-payment", response_model=TenantOut)
def record_tenant_payment(
    tenant_id: int,
    amount: float | None = None,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    """Records a rent payment against a tenant's arrears. Omit `amount` (or
    pass a value >= current arrears) to clear the balance entirely; pass a
    smaller amount to record a partial payment."""
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    unit = db.get(Unit, tenant.unit_id)
    _get_owned_property(db, unit.property_id, manager)

    if amount is None or amount >= tenant.arrears:
        tenant.arrears = 0
    else:
        tenant.arrears -= amount
    db.commit()
    db.refresh(tenant)
    return tenant


@router.get("/properties/{property_id}/leads")
def property_leads(
    property_id: int,
    manager: User = Depends(require_roles(UserRole.manager)),
    db: Session = Depends(get_db),
):
    """Powers the Property Manager App's '30-day dashboard: hunters who
    received contact details per property' requirement."""
    _get_owned_property(db, property_id, manager)
    cutoff = utcnow() - timedelta(days=30)
    leads = (
        db.query(PropertyLeadView)
        .filter(PropertyLeadView.property_id == property_id, PropertyLeadView.created_at >= cutoff)
        .all()
    )
    by_day: dict[str, int] = {}
    for lead in leads:
        day_key = lead.created_at.date().isoformat()
        by_day[day_key] = by_day.get(day_key, 0) + 1
    return {"leads_30d": len(leads), "by_day": by_day}
