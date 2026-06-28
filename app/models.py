"""
SQLAlchemy models.

These extend the "Database Schema (Core Tables)" section of the spec with
the supporting tables needed to actually run the product (OTP codes,
estates/food-spend benchmarks, vacancy signals, field-agent payouts).

Notes on portability:
- lat/lng are stored as plain Float columns (not PostGIS geometry) so this
  schema runs unmodified on SQLite (dev/tests) and PostgreSQL (prod). In
  production, add a PostGIS `geography` column + GiST index alongside these
  for fast radius queries at scale; see migration notes in README.
- JSON columns (photos, amenities, params_json) use SQLAlchemy's generic
  JSON type, which is supported on both SQLite and PostgreSQL (as JSONB).
"""
import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils import utcnow


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    hunter = "hunter"
    manager = "manager"
    admin = "admin"
    field_agent = "field_agent"


class PropertyType(str, enum.Enum):
    apartment_block = "apartment_block"
    maisonette_complex = "maisonette_complex"
    hostel = "hostel"
    bedsitter_block = "bedsitter_block"
    gated_community = "gated_community"
    self_contained_units = "self_contained_units"


class PropertyStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class UnitType(str, enum.Enum):
    bedsitter = "bedsitter"
    studio = "studio"
    one_br = "1br"
    two_br = "2br"
    three_br = "3br"
    hostel_room = "hostel_room"


class CommuteMode(str, enum.Enum):
    walking = "walking"
    matatu = "matatu"
    bus = "bus"
    sgr = "sgr"
    boda_boda = "boda_boda"
    personal_vehicle = "personal_vehicle"


class AgentVerificationStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    rejected = "rejected"


class DisputeStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"


class DisputeResolution(str, enum.Enum):
    refunded = "refunded"
    denied = "denied"


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    initiated = "initiated"
    success = "success"
    failed = "failed"


class SearchPaymentStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    refunded = "refunded"


class CaptureStatus(str, enum.Enum):
    under_review = "under_review"
    approved = "approved"
    rejected = "rejected"


class VacancySignalStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    dismissed = "dismissed"


# ---------------------------------------------------------------------------
# Core tables (per spec)
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.hunter)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # KYC (Property Manager registration)
    id_or_business_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Field agent verification
    student_id_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    agent_verification_status: Mapped[AgentVerificationStatus] = mapped_column(
        Enum(AgentVerificationStatus), default=AgentVerificationStatus.pending
    )
    agent_verification_rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    hunter_profile: Mapped["HunterProfile"] = relationship(back_populates="user", uselist=False)
    properties: Mapped[list["Property"]] = relationship(back_populates="manager")


class OTPVerification(Base):
    __tablename__ = "otp_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HunterProfile(Base):
    __tablename__ = "hunter_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    workplace_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workplace_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    workplace_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_tenancy_unit_id: Mapped[int | None] = mapped_column(ForeignKey("units.id"), nullable=True)

    user: Mapped["User"] = relationship(back_populates="hunter_profile")


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[PropertyType] = mapped_column(Enum(PropertyType))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    estate: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sub_county: Mapped[str | None] = mapped_column(String(255), nullable=True)
    county: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    photos: Mapped[list] = mapped_column(JSON, default=list)
    amenities: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[PropertyStatus] = mapped_column(Enum(PropertyStatus), default=PropertyStatus.pending)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    manager: Mapped["User"] = relationship(back_populates="properties")
    units: Mapped[list["Unit"]] = relationship(back_populates="property", cascade="all, delete-orphan")


class Unit(Base):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    type: Mapped[UnitType] = mapped_column(Enum(UnitType))
    rent: Mapped[float] = mapped_column(Float)
    deposit_months: Mapped[float] = mapped_column(Float, default=1)
    water_deposit: Mapped[float] = mapped_column(Float, default=0)
    electricity_deposit: Mapped[float] = mapped_column(Float, default=0)
    agency_fee: Mapped[float] = mapped_column(Float, default=0)
    notice_period_days: Mapped[int] = mapped_column(Integer, default=30)
    is_vacant: Mapped[bool] = mapped_column(Boolean, default=True)
    expected_vacancy_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    property: Mapped["Property"] = relationship(back_populates="units")
    tenants: Mapped[list["Tenant"]] = relationship(back_populates="unit")


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(20))
    move_in_date: Mapped[datetime] = mapped_column(DateTime)
    monthly_rent: Mapped[float] = mapped_column(Float)
    arrears: Mapped[float] = mapped_column(Float, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    moved_out_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    unit: Mapped["Unit"] = relationship(back_populates="tenants")


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[int] = mapped_column(primary_key=True)
    hunter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    params_json: Mapped[dict] = mapped_column(JSON)
    match_count: Mapped[int] = mapped_column(Integer, default=0)
    payment_status: Mapped[SearchPaymentStatus] = mapped_column(
        Enum(SearchPaymentStatus), default=SearchPaymentStatus.pending
    )
    # Decision 3: denormalized for analytics queries
    unit_type: Mapped["UnitType | None"] = mapped_column(Enum(UnitType), nullable=True)
    estate: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    results: Mapped[list["SearchResult"]] = relationship(back_populates="search", cascade="all, delete-orphan")


class SearchResult(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id"))
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    commute_time_minutes: Mapped[float] = mapped_column(Float)
    commute_cost_kes: Mapped[float] = mapped_column(Float)
    food_cost_kes: Mapped[float] = mapped_column(Float)
    total_cost_kes: Mapped[float] = mapped_column(Float)
    amenity_match_score: Mapped[float] = mapped_column(Float)
    overall_score: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)

    search: Mapped["Search"] = relationship(back_populates="results")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    search_id: Mapped[int | None] = mapped_column(ForeignKey("searches.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Float)
    purpose: Mapped[str] = mapped_column(String(50), default="search_unlock")  # search_unlock | field_agent_payout
    phone: Mapped[str] = mapped_column(String(20))
    mpesa_checkout_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mpesa_receipt: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FieldAgentCapture(Base):
    __tablename__ = "field_agent_captures"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    property_data_json: Mapped[dict] = mapped_column(JSON)
    gps_lat: Mapped[float] = mapped_column(Float)
    gps_lng: Mapped[float] = mapped_column(Float)
    photos: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[CaptureStatus] = mapped_column(Enum(CaptureStatus), default=CaptureStatus.under_review)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reward_amount: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FieldAgentPayout(Base):
    __tablename__ = "field_agent_payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float)
    mpesa_receipt: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Supporting tables (not in spec's core list, needed to make the product work)
# ---------------------------------------------------------------------------

class Estate(Base):
    """Benchmark / crowd-sourced average food spend by estate, used in the
    'all-in monthly cost' budget breakdown shown to hunters."""

    __tablename__ = "estates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    sub_county: Mapped[str | None] = mapped_column(String(255), nullable=True)
    county: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avg_food_spend_monthly_kes: Mapped[float] = mapped_column(Float, default=10000)


class VacancySignal(Base):
    """Created when a hunter who has a linked current tenancy runs a search;
    notifies their current landlord that the tenant may be moving out."""

    __tablename__ = "vacancy_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    hunter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[VacancySignalStatus] = mapped_column(Enum(VacancySignalStatus), default=VacancySignalStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("unit_id", "hunter_id", "created_at", name="uq_vacancy_signal"),)


class Amenity(Base):
    """Global list of amenity strings available for property tagging."""

    __tablename__ = "amenities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(primary_key=True)
    hunter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("units.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("hunter_id", "unit_id", name="uq_favorite"),)


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(primary_key=True)
    hunter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id"), unique=True)
    reason: Mapped[str] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Float)  # snapshotted from payment at filing time
    status: Mapped[DisputeStatus] = mapped_column(Enum(DisputeStatus), default=DisputeStatus.pending)
    resolution: Mapped["DisputeResolution | None"] = mapped_column(Enum(DisputeResolution), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PropertyLeadView(Base):
    """Powers the Property Manager App's '30-day dashboard: hunters who
    received contact details per property' requirement."""

    __tablename__ = "property_lead_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    hunter_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
