"""
Geospatial helpers.

`estimate_commute` is a deliberately simple placeholder: it estimates travel
time from straight-line (haversine) distance and a per-mode average speed,
then adds a fixed boarding/waiting overhead for public transport modes.

Swap-in point for production: replace the body of `estimate_commute` with a
call to Google Maps Platform Directions/Distance Matrix API (using
`commute_mode` -> Google travel mode) and/or integrated matatu/SGR
route+fare data, as described in the spec's "Data Integration" section.
Everything downstream (ranking.py, search router) only depends on this
function's (minutes, cost_kes) return signature, so the swap is isolated.
"""
import math

from app.models import CommuteMode

EARTH_RADIUS_KM = 6371.0

# Average effective speed in km/h, accounting for typical Nairobi traffic.
MODE_SPEED_KMH = {
    CommuteMode.walking: 4.5,
    CommuteMode.matatu: 18.0,
    CommuteMode.bus: 16.0,
    CommuteMode.sgr: 60.0,
    CommuteMode.boda_boda: 22.0,
    CommuteMode.personal_vehicle: 25.0,
}

# Fixed boarding/waiting overhead in minutes.
MODE_OVERHEAD_MIN = {
    CommuteMode.walking: 0,
    CommuteMode.matatu: 8,
    CommuteMode.bus: 10,
    CommuteMode.sgr: 15,
    CommuteMode.boda_boda: 3,
    CommuteMode.personal_vehicle: 5,
}

# Approximate one-way fare in KES per km, for monthly cost estimation
# (used both ways, ~22 working days/month).
MODE_FARE_KES_PER_KM = {
    CommuteMode.walking: 0,
    CommuteMode.matatu: 12,
    CommuteMode.bus: 9,
    CommuteMode.sgr: 6,
    CommuteMode.boda_boda: 25,
    CommuteMode.personal_vehicle: 18,  # fuel-equivalent cost
}

WORKING_DAYS_PER_MONTH = 22


def haversine_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_commute(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    mode: CommuteMode,
) -> tuple[float, float]:
    """Returns (one_way_minutes, monthly_cost_kes)."""
    distance_km = haversine_distance_km(origin_lat, origin_lng, dest_lat, dest_lng)
    # Straight-line distance underestimates real road/route distance; apply a
    # routing factor as a rough correction until real route data is wired in.
    routing_factor = 1.3
    effective_km = distance_km * routing_factor

    speed = MODE_SPEED_KMH[mode]
    minutes = (effective_km / speed) * 60 + MODE_OVERHEAD_MIN[mode]

    one_way_fare = effective_km * MODE_FARE_KES_PER_KM[mode]
    monthly_cost = one_way_fare * 2 * WORKING_DAYS_PER_MONTH

    return round(minutes, 1), round(monthly_cost, 2)
