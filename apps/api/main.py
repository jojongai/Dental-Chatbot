from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import get_settings
from database import check_database_connection, init_db


class HealthResponse(BaseModel):
    status: str
    service: str
    database: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Dental Chatbot API", version="0.1.0", lifespan=lifespan)

_settings = get_settings()
allow_origins = [o.strip() for o in _settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> HealthResponse:
    check_database_connection()
    db_kind = "sqlite" if _settings.database_url.startswith("sqlite") else "postgres"
    return HealthResponse(status="ok", service="api", database=db_kind)
