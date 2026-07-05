"""
MediGuard — Data Models
ORM models (SQLAlchemy) and validation schemas (Pydantic) for:
  - Elder profiles
  - Medications
  - Schedules
  - Adherence logs
  - Caregiver relationships
"""

from datetime import datetime, time
from typing import Optional, List
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Time, ForeignKey, Text, Enum
)
from sqlalchemy.orm import relationship
from pydantic import BaseModel, Field, validator

from api.database import Base


# ── SQLAlchemy ORM Models ──────────────────────────────────────────────────

class Elder(Base):
    """An elderly user whose medications are being managed."""
    __tablename__ = "elders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)   # For SMS reminders
    email = Column(String(200), nullable=True)  # For email reminders
    timezone = Column(String(50), default="Asia/Kolkata")
    created_at = Column(DateTime, default=datetime.utcnow)

    medications = relationship("Medication", back_populates="elder")
    caregivers = relationship("CaregiverLink", back_populates="elder")
    adherence_logs = relationship("AdherenceLog", back_populates="elder")


class Medication(Base):
    """A medication belonging to an elder, with inventory tracking."""
    __tablename__ = "medications"

    id = Column(Integer, primary_key=True, index=True)
    elder_id = Column(Integer, ForeignKey("elders.id"), nullable=False)
    name = Column(String(200), nullable=False)          # e.g. "Metformin 500mg"
    dosage = Column(String(100), nullable=False)         # e.g. "1 tablet"
    pills_remaining = Column(Integer, default=30)        # Current pill count
    refill_threshold = Column(Integer, default=7)        # Alert when <= this many pills
    total_supply = Column(Integer, default=30)           # Pills per bottle/pack
    notes = Column(Text, nullable=True)                  # Special instructions
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    elder = relationship("Elder", back_populates="medications")
    schedules = relationship("MedicationSchedule", back_populates="medication")


class MedicationSchedule(Base):
    """A specific time at which a medication must be taken."""
    __tablename__ = "medication_schedules"

    id = Column(Integer, primary_key=True, index=True)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False)
    scheduled_time = Column(String(8), nullable=False)  # "HH:MM:SS" string
    label = Column(String(50), default="dose")          # "morning", "evening", etc.
    days_of_week = Column(String(20), default="1234567") # "1234567" = every day

    medication = relationship("Medication", back_populates="schedules")


class AdherenceLog(Base):
    """Records whether a scheduled dose was taken, skipped, or missed."""
    __tablename__ = "adherence_logs"

    id = Column(Integer, primary_key=True, index=True)
    elder_id = Column(Integer, ForeignKey("elders.id"), nullable=False)
    medication_id = Column(Integer, ForeignKey("medications.id"), nullable=False)
    scheduled_time = Column(DateTime, nullable=False)
    taken_at = Column(DateTime, nullable=True)           # None = not yet taken
    status = Column(
        Enum("taken", "missed", "skipped", "pending", name="adherence_status"),
        default="pending"
    )
    notes = Column(Text, nullable=True)

    elder = relationship("Elder", back_populates="adherence_logs")


class CaregiverLink(Base):
    """Links a caregiver to an elder with notification preferences."""
    __tablename__ = "caregiver_links"

    id = Column(Integer, primary_key=True, index=True)
    elder_id = Column(Integer, ForeignKey("elders.id"), nullable=False)
    caregiver_name = Column(String(100), nullable=False)
    caregiver_phone = Column(String(20), nullable=True)
    caregiver_email = Column(String(200), nullable=True)
    notify_missed = Column(Boolean, default=True)       # Alert on missed dose
    notify_refill = Column(Boolean, default=True)       # Alert on low inventory
    notify_daily_summary = Column(Boolean, default=True)

    elder = relationship("Elder", back_populates="caregivers")


# ── Pydantic Schemas (API validation) ─────────────────────────────────────

class MedicationCreate(BaseModel):
    """Schema for creating a new medication."""
    name: str = Field(..., min_length=1, max_length=200, example="Metformin 500mg")
    dosage: str = Field(..., example="1 tablet")
    pills_remaining: int = Field(default=30, ge=0, le=10000)
    refill_threshold: int = Field(default=7, ge=1)
    notes: Optional[str] = None

    @validator("pills_remaining")
    def pills_must_be_positive(cls, v):
        if v < 0:
            raise ValueError("Pills remaining cannot be negative")
        return v


class MedicationResponse(BaseModel):
    id: int
    elder_id: int
    name: str
    dosage: str
    pills_remaining: int
    refill_threshold: int
    needs_refill: bool = False  # Computed field
    notes: Optional[str]
    is_active: bool

    class Config:
        from_attributes = True


class ScheduleCreate(BaseModel):
    """Schema for scheduling a medication dose time."""
    medication_id: int
    scheduled_time: str = Field(..., example="08:00", pattern=r"^\d{2}:\d{2}$")
    label: str = Field(default="dose", example="morning")
    days_of_week: str = Field(default="1234567")


class AdherenceLogResponse(BaseModel):
    id: int
    medication_id: int
    scheduled_time: datetime
    taken_at: Optional[datetime]
    status: str

    class Config:
        from_attributes = True


class ElderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    phone: Optional[str] = None
    email: Optional[str] = None
    timezone: str = Field(default="Asia/Kolkata")


class ElderResponse(BaseModel):
    id: int
    name: str
    phone: Optional[str]
    email: Optional[str]
    timezone: str

    class Config:
        from_attributes = True
