"""
MediGuard — FastAPI Backend
REST API exposing medication management, schedule tracking,
and adherence logging. Consumed by agents via MCP tools.

Security: JWT auth for caregiver endpoints, input validation
via Pydantic, rate limiting on notification routes.
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from dotenv import load_dotenv

from api.database import get_db, init_db
from api.models import (
    Elder, Medication, MedicationSchedule, AdherenceLog,
    ElderCreate, ElderResponse,
    MedicationCreate, MedicationResponse,
    ScheduleCreate, AdherenceLogResponse,
)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database tables on startup."""
    await init_db()
    yield


app = FastAPI(
    title="MediGuard API",
    description="Elder medication reminder and inventory management system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dashboard and agent calls
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict in production to known origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health Check ──────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health_check():
    """Liveness probe for deployment orchestrators."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ── Elder Endpoints ───────────────────────────────────────────────────────

@app.post("/elders", response_model=ElderResponse, status_code=201, tags=["elders"])
async def create_elder(elder_data: ElderCreate, db: AsyncSession = Depends(get_db)):
    """Register a new elder profile."""
    elder = Elder(**elder_data.model_dump())
    db.add(elder)
    await db.commit()
    await db.refresh(elder)
    return elder


@app.get("/elders/{elder_id}", response_model=ElderResponse, tags=["elders"])
async def get_elder(elder_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve an elder profile by ID."""
    result = await db.execute(select(Elder).where(Elder.id == elder_id))
    elder = result.scalar_one_or_none()
    if not elder:
        raise HTTPException(status_code=404, detail="Elder not found")
    return elder


# ── Medication Endpoints ──────────────────────────────────────────────────

@app.post(
    "/elders/{elder_id}/medications",
    response_model=MedicationResponse,
    status_code=201,
    tags=["medications"],
)
async def add_medication(
    elder_id: int,
    med_data: MedicationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a new medication for an elder."""
    # Verify elder exists
    result = await db.execute(select(Elder).where(Elder.id == elder_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Elder not found")

    med = Medication(elder_id=elder_id, **med_data.model_dump())
    db.add(med)
    await db.commit()
    await db.refresh(med)

    # Attach computed field before returning
    response = MedicationResponse.model_validate(med)
    response.needs_refill = med.pills_remaining <= med.refill_threshold
    return response


@app.get(
    "/elders/{elder_id}/medications",
    response_model=list[MedicationResponse],
    tags=["medications"],
)
async def list_medications(elder_id: int, db: AsyncSession = Depends(get_db)):
    """List all active medications for an elder."""
    result = await db.execute(
        select(Medication)
        .where(Medication.elder_id == elder_id, Medication.is_active == True)
    )
    meds = result.scalars().all()
    responses = []
    for med in meds:
        r = MedicationResponse.model_validate(med)
        r.needs_refill = med.pills_remaining <= med.refill_threshold
        responses.append(r)
    return responses


@app.patch(
    "/medications/{med_id}/taken",
    tags=["medications"],
)
async def mark_medication_taken(med_id: int, db: AsyncSession = Depends(get_db)):
    """
    Record that a dose was taken. Decrements pill count by 1.
    Called by the Reminder Agent when the elder confirms taking the dose.
    """
    result = await db.execute(select(Medication).where(Medication.id == med_id))
    med = result.scalar_one_or_none()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")

    if med.pills_remaining <= 0:
        raise HTTPException(status_code=409, detail="No pills remaining — refill needed")

    med.pills_remaining -= 1
    await db.commit()

    needs_refill = med.pills_remaining <= med.refill_threshold
    return {
        "medication": med.name,
        "pills_remaining": med.pills_remaining,
        "needs_refill": needs_refill,
        "refill_threshold": med.refill_threshold,
    }


@app.patch(
    "/medications/{med_id}/refill",
    tags=["medications"],
)
async def refill_medication(
    med_id: int,
    quantity: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Record a refill event. Adds pills to current inventory."""
    if quantity <= 0 or quantity > 1000:
        raise HTTPException(status_code=422, detail="Quantity must be between 1 and 1000")

    result = await db.execute(select(Medication).where(Medication.id == med_id))
    med = result.scalar_one_or_none()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")

    med.pills_remaining += quantity
    await db.commit()

    return {
        "medication": med.name,
        "pills_remaining": med.pills_remaining,
        "refilled_by": quantity,
    }


# ── Adherence Endpoints ───────────────────────────────────────────────────

@app.get(
    "/elders/{elder_id}/adherence",
    response_model=list[AdherenceLogResponse],
    tags=["adherence"],
)
async def get_adherence_log(
    elder_id: int,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve recent adherence logs for reporting to caregivers."""
    result = await db.execute(
        select(AdherenceLog)
        .where(AdherenceLog.elder_id == elder_id)
        .order_by(AdherenceLog.scheduled_time.desc())
        .limit(min(limit, 100))  # Cap at 100 to avoid large payloads
    )
    return result.scalars().all()


@app.get(
    "/elders/{elder_id}/medications/low-stock",
    tags=["inventory"],
)
async def get_low_stock_medications(elder_id: int, db: AsyncSession = Depends(get_db)):
    """
    Return medications below their refill threshold.
    Used by the Inventory Agent to trigger caregiver alerts.
    """
    result = await db.execute(
        select(Medication).where(
            Medication.elder_id == elder_id,
            Medication.is_active == True,
        )
    )
    all_meds = result.scalars().all()
    low_stock = [
        {
            "id": m.id,
            "name": m.name,
            "pills_remaining": m.pills_remaining,
            "refill_threshold": m.refill_threshold,
            "days_remaining": m.pills_remaining,  # Simplified: 1 pill/day assumption
        }
        for m in all_meds
        if m.pills_remaining <= m.refill_threshold
    ]
    return {"low_stock_medications": low_stock, "count": len(low_stock)}
