"""
Seed script -- populates a small but realistic dataset for local
development and demos.

Usage:
    python seed.py
"""
from app.auth import hash_value
from app.database import Base, SessionLocal, engine
from app.models import (
    Estate,
    HunterProfile,
    Property,
    PropertyStatus,
    PropertyType,
    Tenant,
    Unit,
    UnitType,
    User,
    UserRole,
)

Base.metadata.create_all(bind=engine)

ESTATES = [
    ("Kilimani", "Dagoretti", "Nairobi", 12000),
    ("Lavington", "Dagoretti", "Nairobi", 14000),
    ("Kasarani", "Kasarani", "Nairobi", 8000),
    ("South B", "Makadara", "Nairobi", 9000),
    ("Westlands", "Westlands", "Nairobi", 15000),
    ("Roysambu", "Kasarani", "Nairobi", 8500),
]

PROPERTIES = [
    # name, estate, lat, lng, type, units: [(type, rent), ...], amenities
    (
        "Kilimani Heights",
        "Kilimani",
        -1.2906,
        36.7873,
        PropertyType.apartment_block,
        [(UnitType.bedsitter, 9000), (UnitType.one_br, 18000), (UnitType.two_br, 28000)],
        ["wifi", "parking", "cctv", "borehole_water"],
    ),
    (
        "Lavington Court",
        "Lavington",
        -1.2792,
        36.7689,
        PropertyType.gated_community,
        [(UnitType.two_br, 45000), (UnitType.three_br, 65000)],
        ["parking", "gym", "security_guard", "electric_fence"],
    ),
    (
        "Kasarani Bedsitters",
        "Kasarani",
        -1.2231,
        36.8983,
        PropertyType.bedsitter_block,
        [(UnitType.bedsitter, 6000), (UnitType.bedsitter, 6500)],
        ["parking", "wifi"],
    ),
    (
        "South B Maisonettes",
        "South B",
        -1.3097,
        36.8345,
        PropertyType.maisonette_complex,
        [(UnitType.three_br, 38000)],
        ["parking", "generator_or_solar", "cctv"],
    ),
    (
        "Westlands Studios",
        "Westlands",
        -1.2655,
        36.8027,
        PropertyType.self_contained_units,
        [(UnitType.studio, 22000), (UnitType.one_br, 32000)],
        ["wifi", "gym", "security_guard", "parking"],
    ),
    (
        "Roysambu Hostel",
        "Roysambu",
        -1.2197,
        36.9226,
        PropertyType.hostel,
        [(UnitType.hostel_room, 5000), (UnitType.hostel_room, 5000), (UnitType.hostel_room, 5500)],
        ["wifi", "security_guard"],
    ),
]


def run():
    db = SessionLocal()
    try:
        if db.query(Estate).count() > 0:
            print("Database already seeded -- skipping. Delete kejaflix.db to reseed.")
            return

        for name, sub_county, county, food in ESTATES:
            db.add(Estate(name=name, sub_county=sub_county, county=county, avg_food_spend_monthly_kes=food))

        manager = User(
            phone="+254700100100",
            name="Demo Manager",
            role=UserRole.manager,
            is_verified=True,
            company_name="Kejaflix Demo Properties Ltd",
        )
        admin = User(phone="+254700100200", name="Demo Admin", role=UserRole.admin, is_verified=True)
        hunter = User(phone="+254700100300", name="Demo Hunter", role=UserRole.hunter, is_verified=True)
        db.add_all([manager, admin, hunter])
        db.flush()

        db.add(
            HunterProfile(
                user_id=hunter.id,
                workplace_name="CBD Office",
                workplace_lat=-1.2864,
                workplace_lng=36.8172,
                current_city="Nairobi",
            )
        )

        for name, estate, lat, lng, ptype, units, amenities in PROPERTIES:
            prop = Property(
                manager_id=manager.id,
                name=name,
                type=ptype,
                lat=lat,
                lng=lng,
                estate=estate,
                sub_county=dict((e[0], e[1]) for e in ESTATES)[estate],
                county="Nairobi",
                amenities=amenities,
                status=PropertyStatus.approved,
            )
            db.add(prop)
            db.flush()

            for unit_type, rent in units:
                db.add(Unit(property_id=prop.id, type=unit_type, rent=rent))

        db.commit()
        print("Seeded:")
        print(f"  {len(ESTATES)} estates")
        print(f"  3 demo users -- manager: +254700100100, admin: +254700100200, hunter: +254700100300")
        print(f"  {len(PROPERTIES)} approved properties with units")
        print()
        print("Demo login: POST /auth/register with one of the phone numbers above,")
        print("then POST /auth/verify-otp using the debug_otp returned (OTP_DEBUG_ECHO=true).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
