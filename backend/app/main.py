"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the database file and schema on startup. SQLite needs no teardown."""
    await db.init_db()
    yield


app = FastAPI(title="PantryPal", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    """Report liveness plus whether the database is currently reachable."""
    return {"status": "ok", "database": await db.healthy()}
