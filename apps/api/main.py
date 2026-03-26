from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import get_settings
from database import check_database_connection, init_db
from routers import appointments, chat, clinic, patients


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Dental Chatbot API",
    version="0.1.0",
    description=(
        "Backend for the Bright Smile Dental chatbot. "
        "Handles new/existing patient flows, scheduling, family booking, "
        "emergency triage, and general inquiries."
    ),
    lifespan=lifespan,
)

_settings = get_settings()
allow_origins = [o.strip() for o in _settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(chat.router)
app.include_router(patients.router)
app.include_router(appointments.router)
app.include_router(clinic.router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"])
async def health() -> HealthResponse:
    check_database_connection()
    db_kind = "sqlite" if _settings.database_url.startswith("sqlite") else "postgres"
    return HealthResponse(status="ok", service="api", database=db_kind)
