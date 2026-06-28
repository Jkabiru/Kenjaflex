from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import Base, engine
from app.routers import admin, auth, disputes, field_agent, hunter_profile, payments, properties, search

settings = get_settings()

# In production, use Alembic migrations instead of create_all (see
# alembic/ directory). create_all is convenient for local dev/tests against
# a throwaway SQLite file.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "Kejaflix backend API -- dual-sided rental marketplace for Kenya. "
        "Covers hunter search/payment, property manager onboarding & tenant "
        "management, admin verification/analytics, and the field agent "
        "capture program."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=settings.MEDIA_ROOT), name="static")

app.include_router(auth.router)
app.include_router(hunter_profile.router)
app.include_router(properties.router)
app.include_router(search.router)
app.include_router(payments.router)
app.include_router(field_agent.router)
app.include_router(disputes.router)
app.include_router(admin.router)


@app.get("/health", tags=["Meta"])
def health_check():
    return {"status": "ok"}
