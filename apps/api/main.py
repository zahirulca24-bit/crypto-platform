import os

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from routers.auth import router as auth_router
from routers.market_data import router as market_data_router
from routers.demo_exchange import router as demo_exchange_router
from routers.symbol_selection import router as symbol_selection_router
from routers.strategies import router as strategies_router
from routers.phase2 import router as phase2_router

app = FastAPI(
    title="Adaptive Crypto Trading Platform API",
    description="Stateless API Service for Adaptive Crypto Trading Platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",") if origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(auth_router)
app.include_router(market_data_router)
app.include_router(demo_exchange_router)
app.include_router(symbol_selection_router)
app.include_router(strategies_router)
app.include_router(phase2_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/db")
def health_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "error", "database": "disconnected", "error": str(e)},
        )
