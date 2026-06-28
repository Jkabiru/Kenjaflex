# Kejaflix Backend

Backend API for **Kejaflix** — a dual-sided rental marketplace for Kenya,
connecting house hunters with property managers via AI-powered search,
Mpesa payments, and a free property management tool.

This is the backend slice of the full Kejaflix spec (4 apps: Hunter,
Property Manager, Admin Portal, Field Agent). It's a real, runnable,
tested FastAPI service — not a mockup — built so a frontend (mobile or
web) can be wired straight into it.

## Stack

| Layer | Choice | Why |
|---|---|---|
| API framework | FastAPI | Async, auto-generates OpenAPI/Swagger docs (a spec deliverable) |
| ORM | SQLAlchemy 2.0 | Works unmodified on SQLite (dev) and PostgreSQL (prod) |
| DB (dev) | SQLite | Zero setup, used in `docker-compose` is Postgres+PostGIS |
| DB (prod) | PostgreSQL + PostGIS | Per spec; geospatial extension ready for real radius queries at scale |
| Migrations | Alembic | `alembic/versions/` has the initial schema migration |
| Auth | JWT (python-jose) + OTP | Mobile OTP registration per spec |
| Payments | Safaricom Daraja (mocked by default) | STK Push (C2B) + B2C payouts |
| SMS | Africa's Talking (mocked by default) | OTP delivery, rent reminders |

## Quick start (local, zero external dependencies)

```bash
python3 -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate

pip install -r requirements.txt
python seed.py          # populates demo estates/properties/users
uvicorn app.main:app --reload
```

> **Hit `error: externally-managed-environment`?** Modern Debian/Ubuntu block
> `pip install` outside a virtual environment (PEP 668). The `venv` steps
> above are the fix — just make sure you've run `source venv/bin/activate`
> before `pip install`. Re-run that `source` line in any new terminal you
> open for this project.

- API: http://localhost:8000
- Interactive Swagger docs: **http://localhost:8000/docs**
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

By default the app runs against a local SQLite file with `MPESA_MOCK_MODE=true`
and `OTP_DEBUG_ECHO=true`, so you can exercise every flow — registration,
property onboarding, search, payment unlock, field agent payouts — with
**no real Mpesa, Africa's Talking, or Google Maps credentials**.

Demo accounts after `python seed.py` (use `/auth/register` then
`/auth/verify-otp` with the `debug_otp` returned):
- Manager: `+254700100100`
- Admin: `+254700100200`
- Hunter: `+254700100300`

## Running with Docker (production-shaped stack)

```bash
cp .env.example .env   # edit as needed
docker compose up --build
```

This runs the API against real **PostgreSQL + PostGIS** and **Redis**
containers, and runs Alembic migrations automatically on startup.

## Running tests

```bash
pytest tests/ -v
```

24 tests cover the critical flows called out in the spec's MVP success
criteria: search match-counting, payment-gated results, the ranking
algorithm's weighting, field-agent duplicate detection, payout thresholds,
and role-based access control.

## Architecture

```
app/
  main.py            FastAPI app, router wiring, CORS, static file mount
  config.py          All settings, env-driven (see .env.example)
  database.py        SQLAlchemy engine/session
  models.py          ORM models (see Database Schema below)
  schemas.py         Pydantic request/response models
  auth.py            JWT issuance/verification, role-based dependencies
  routers/
    auth.py          OTP registration/verification, social sign-in
    properties.py    Property onboarding wizard, units, tenants, vacancy
    search.py        AI search wizard, payment unlock, results, favorites
    payments.py      Mpesa Daraja STK Push callback webhook
    field_agent.py   Property capture, duplicate detection, earnings, payout
    admin.py         Verification queue, dashboard, analytics
  services/
    geo.py           Haversine distance + commute time/cost estimation
    ranking.py       AI Recommendation Engine (the weighted scoring algorithm)
    mpesa.py         Daraja STK Push (C2B) + B2C payout integration
    sms.py           Africa's Talking integration
    storage.py        File upload abstraction (local disk / S3 swap-in)
alembic/             Database migrations
tests/               24 pytest tests across auth, properties, search, field agent, admin
seed.py              Demo data generator
docker-compose.yml   API + PostgreSQL+PostGIS + Redis
```

## What's mocked, and how to go live

Everything below runs end-to-end in mock mode so you can build/test the
full product immediately. Each has one clearly marked swap-in point:

| Integration | Mock behavior | File | To go live |
|---|---|---|---|
| Mpesa Daraja | STK Push / B2C instantly "succeed" | `app/services/mpesa.py` | Set `MPESA_MOCK_MODE=false`, fill `DARAJA_*` env vars |
| Africa's Talking SMS | Logs message instead of sending | `app/services/sms.py` | Fill `AT_USERNAME`/`AT_API_KEY` |
| Google/Apple Sign-In | Trusts caller-supplied phone | `app/routers/auth.py: social_sign_in` | Verify `id_token` via Firebase Admin SDK / Apple JWKS |
| Commute time/cost | Haversine distance × per-mode avg speed | `app/services/geo.py` | Call Google Maps Directions/Distance Matrix API |
| File storage | Local disk under `static/` | `app/services/storage.py` | Swap in S3/GCS upload |

## AI Recommendation Engine

Implements the spec's algorithm exactly:
1. Hard filter: `rent <= budget`, unit type match, vacant + approved only
2. Commute time from the chosen transport mode
3. Score = commute time (**40%**) + all-in cost (**35%**) + amenity match (**25%**),
   each normalized against the candidate set before weighting
4. Sorted descending, ranked, returned with a match-count summary

See `app/services/ranking.py`.

## Database Schema

The spec's core tables (`users`, `properties`, `units`, `tenants`,
`hunter_profiles`, `searches`, `results`, `payments`,
`field_agent_captures`) are implemented as specified, extended with the
supporting tables needed to actually run the product:

- `otp_verifications` — hashed OTP codes with expiry/attempt tracking
- `estates` — crowd-sourced/benchmark average food spend by estate, used
  in the all-in cost calculation
- `vacancy_signals` — the "your tenant appears to be searching" feature
- `favorites`, `property_lead_views`, `field_agent_payouts`

Geospatial note: `lat`/`lng` are plain `Float` columns so the schema runs
identically on SQLite and PostgreSQL. In production, add a PostGIS
`geography` column + GiST index alongside them for fast radius queries at
scale (the spec calls for PostGIS specifically) — see the Alembic
migration as the place to add it.

## API Endpoints

All endpoints from the spec's table are implemented, plus the supporting
ones needed to make each feature actually work end-to-end (full list with
request/response schemas is always up to date at `/docs`):

**Auth** — `POST /auth/register`, `/auth/verify-otp`, `/auth/social`, `GET /auth/me`

**Properties** (Property Manager) — `POST /properties`, `GET /properties/{id}`,
`POST /properties/{id}/photos`, `POST /properties/{id}/submit`,
`POST/GET /properties/{id}/units`, `PATCH /units/{id}/vacancy`,
`POST /units/{id}/tenants`, `GET /properties/{id}/tenants`,
`POST /tenants/{id}/archive`, `POST /properties/{id}/tenants/rent-reminders`,
`GET /properties/{id}/rent-arrears`, `GET /properties/{id}/vacancy-signals`,
`POST /vacancy-signals/{id}/respond`

**Search** (Hunter) — `POST /search`, `POST /search/{id}/unlock`,
`GET /search/{id}/results`, `POST/GET /favorites`

**Payments** — `POST /payments/mpesa/callback` (Daraja webhook)

**Field Agent** — `POST /field-agent/capture`, `GET /field-agent/captures`,
`GET /field-agent/earnings`, `POST /field-agent/payout`

**Admin** — `GET /admin/properties/pending`, `POST /admin/properties/{id}/verify`,
`GET/POST /admin/field-agent/captures/...`, `GET /admin/users`,
`GET /admin/dashboard`, `GET /admin/analytics`

## Notes on MVP success criteria (from spec)

- **Property onboarding < 5 min** — the wizard is a single `POST /properties`
  + unit calls + photo upload; no server-side bottleneck.
- **Search-to-payment conversion** — tracked via `Search.payment_status`;
  surfaced in `GET /admin/analytics`.
- **AI search < 3 seconds** — ranking runs in-process over an indexed query
  (`Unit.is_vacant`, `Unit.type`, `Property.status` should be indexed in
  production at scale; add via a follow-up migration once query patterns
  are known).
- **Mpesa STK success > 95%** — handled by the real Daraja integration once
  `MPESA_MOCK_MODE=false`; failures surface as `PaymentStatus.failed` for
  retry.
- **Field agent workflow functional** — capture → duplicate check → admin
  review → reward credit → B2C payout, all implemented and tested.
- **Admin verification within 48h** — process/SLA concern, not code; the
  queue (`GET /admin/properties/pending`) and timestamps are in place to
  measure it.

## Remaining deliverables (per spec) not in this slice

This PR is the backend/API + DB slice. Still outstanding from the full
spec's deliverables list:
- Mobile apps (Hunter + Property Manager) — React Native/Flutter
- Admin web portal frontend
- Published app store listings
- Full PostGIS geospatial indexing for production-scale radius queries
