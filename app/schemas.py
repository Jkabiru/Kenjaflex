from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import (
    AgentVerificationStatus,
    CaptureStatus,
    CommuteMode,
    DisputeResolution,
    DisputeStatus,
    PaymentStatus,
    PropertyStatus,
    PropertyType,
    SearchPaymentStatus,
    UnitType,
    UserRole,
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    phone: str
    name: str | None = None
    role: UserRole = UserRole.hunter


class RegisterResponse(BaseModel):
    message: str
    debug_otp: str | None = None  # only populated when OTP_DEBUG_ECHO=True


class VerifyOTPRequest(BaseModel):
    phone: str
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    role: UserRole


class SocialSignInRequest(BaseModel):
    provider: str  # google | apple
    id_token: str
    phone: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    email: str | None
    name: str | None
    role: UserRole
    is_verified: bool
    id_or_business_number: str | None
    company_name: str | None
    photo_url: str | None
    created_at: datetime


class UserNameUpdate(BaseModel):
    name: str


class UserKycUpdate(BaseModel):
    id_or_business_number: str
    company_name: str | None = None


# ---------------------------------------------------------------------------
# Hunter profile
# ---------------------------------------------------------------------------

class HunterProfileUpdate(BaseModel):
    workplace_name: str | None = None
    workplace_lat: float | None = None
    workplace_lng: float | None = None
    current_city: str | None = None
    current_tenancy_unit_id: int | None = None


class HunterProfileOut(HunterProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    user_id: int


# ---------------------------------------------------------------------------
# Properties / Units / Tenants
# ---------------------------------------------------------------------------

class PropertyCreate(BaseModel):
    name: str
    type: PropertyType
    lat: float
    lng: float
    estate: str | None = None
    sub_county: str | None = None
    county: str | None = None
    address: str | None = None
    amenities: list[str] = []


class PropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    manager_id: int
    name: str
    type: PropertyType
    lat: float
    lng: float
    estate: str | None
    sub_county: str | None
    county: str | None
    address: str | None
    photos: list[str]
    amenities: list[str]
    status: PropertyStatus
    rejection_reason: str | None
    created_at: datetime


class PropertyVerifyRequest(BaseModel):
    approve: bool
    reason: str | None = None


class UnitCreate(BaseModel):
    type: UnitType
    rent: float
    deposit_months: float = 1
    water_deposit: float = 0
    electricity_deposit: float = 0
    agency_fee: float = 0
    notice_period_days: int = 30
    is_vacant: bool = True


class UnitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    property_id: int
    type: UnitType
    rent: float
    deposit_months: float
    water_deposit: float
    electricity_deposit: float
    agency_fee: float
    notice_period_days: int
    is_vacant: bool
    expected_vacancy_date: datetime | None


class UnitVacancyUpdate(BaseModel):
    is_vacant: bool
    expected_vacancy_date: datetime | None = None


class TenantCreate(BaseModel):
    name: str
    phone: str
    move_in_date: datetime
    monthly_rent: float


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    unit_id: int
    name: str
    phone: str
    move_in_date: datetime
    monthly_rent: float
    arrears: float
    is_active: bool
    moved_out_date: datetime | None


class RentReminderRequest(BaseModel):
    tenant_ids: list[int] | None = None  # None = send to all tenants in property


# ---------------------------------------------------------------------------
# Search / AI matching
# ---------------------------------------------------------------------------

class SearchCreate(BaseModel):
    commute_lat: float
    commute_lng: float
    max_commute_minutes: int
    unit_type: UnitType
    max_rent_kes: float
    amenities: list[str] = []
    commute_mode: CommuteMode


class SearchCreateResponse(BaseModel):
    search_id: int
    match_count: int
    unlock_fee_kes: int
    payment_status: SearchPaymentStatus


class SearchUnlockRequest(BaseModel):
    phone: str  # Mpesa phone number to STK push


class SearchUnlockResponse(BaseModel):
    payment_id: int
    status: PaymentStatus
    checkout_request_id: str | None
    message: str


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rank: int
    property_id: int
    property_name: str
    property_lat: float
    property_lng: float
    manager_phone: str
    unit_id: int
    unit_type: UnitType
    rent: float
    commute_time_minutes: float
    commute_cost_kes: float
    food_cost_kes: float
    total_cost_kes: float
    amenity_match_score: float
    overall_score: float
    matched_amenities: list[str]


class FavoriteCreate(BaseModel):
    unit_id: int


# ---------------------------------------------------------------------------
# Field agent
# ---------------------------------------------------------------------------

class FieldAgentProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str
    name: str | None
    student_id_photo_url: str | None
    agent_verification_status: AgentVerificationStatus
    agent_verification_rejection_reason: str | None
    created_at: datetime


class FieldAgentNameUpdate(BaseModel):
    name: str


class AgentKycRejectRequest(BaseModel):
    reason: str


class FieldAgentCaptureCreate(BaseModel):
    property_name: str
    unit_count: int
    estimated_rent_min: float
    estimated_rent_max: float
    manager_contact: str | None = None
    gps_lat: float
    gps_lng: float
    photos: list[str]  # uploaded media URLs (>= 3 required)


class FieldAgentCaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent_id: int
    status: CaptureStatus
    admin_notes: str | None
    reward_amount: float
    created_at: datetime


class FieldAgentEarningsOut(BaseModel):
    total_approved_captures: int
    total_earned_kes: float
    total_paid_out_kes: float
    available_balance_kes: float


class PayoutRequest(BaseModel):
    phone: str


class PayoutOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    amount: float
    status: PaymentStatus


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class ExecutiveDashboardOut(BaseModel):
    total_properties: int
    total_units: int
    occupied_units: int
    vacant_units: int
    occupancy_rate_pct: float
    monthly_revenue_kes: float
    registrations_last_30_days: int


class AnalyticsOut(BaseModel):
    searches_total: int
    paid_searches: int
    search_to_payment_conversion_pct: float
    top_unit_types: list[dict]   # what hunters are searching for
    top_estates: list[dict]      # estates appearing in search results
    searches_by_hour: list[dict]  # [{hour: 0, count: 5}, ...]


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

class DisputeCreate(BaseModel):
    search_id: int
    reason: str


class DisputeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hunter_id: int
    search_id: int
    reason: str
    amount: float
    status: DisputeStatus
    resolution: DisputeResolution | None
    created_at: datetime


class DisputeResolveRequest(BaseModel):
    approve: bool


# ---------------------------------------------------------------------------
# Amenities
# ---------------------------------------------------------------------------

class AmenityCreate(BaseModel):
    name: str


class AmenityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


# ---------------------------------------------------------------------------
# Revenue
# ---------------------------------------------------------------------------

class RevenueOut(BaseModel):
    period_days: int
    search_unlock_revenue_kes: float
    field_agent_payout_outflow_kes: float
    net_kes: float
    failed_transaction_count: int
    transactions: list[dict]


# ---------------------------------------------------------------------------
# Estates
# ---------------------------------------------------------------------------

class EstateCreate(BaseModel):
    name: str
    sub_county: str | None = None
    county: str | None = None
    avg_food_spend_monthly_kes: float = 10000.0


class EstateOut(EstateCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
