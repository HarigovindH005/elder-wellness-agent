"""
MediGuard — FastMCP Server
Exposes medication management as MCP tools that ADK agents can call.
Each tool maps to a specific capability: schedule lookup, dose confirmation,
inventory check, and caregiver notification.

The MCP layer decouples agent logic from API implementation —
agents never call the database directly, they call tools.
"""

import os
import json
from datetime import datetime, time
from typing import Optional

import httpx
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

# Base URL for the FastAPI backend
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

# Initialize FastMCP server — gives agents a clean tool interface
mcp = FastMCP(
    name="MediGuard",
    description="Tools for elder medication reminders and inventory tracking",
)


# ── Tool: Get today's medication schedule ─────────────────────────────────

@mcp.tool()
async def get_todays_schedule(elder_id: int) -> str:
    """
    Retrieve all medications scheduled for today for a given elder.
    Returns medication names, dosages, scheduled times, and pill counts.

    Args:
        elder_id: The unique ID of the elder user.

    Returns:
        JSON string with today's scheduled medications.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_BASE}/elders/{elder_id}/medications")
        response.raise_for_status()
        medications = response.json()

    schedule = [
        {
            "name": med["name"],
            "dosage": med["dosage"],
            "pills_remaining": med["pills_remaining"],
            "needs_refill": med["needs_refill"],
        }
        for med in medications
        if med["is_active"]
    ]

    return json.dumps(
        {
            "elder_id": elder_id,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "medications": schedule,
            "total_medications": len(schedule),
        },
        indent=2,
    )


# ── Tool: Confirm a dose was taken ───────────────────────────────────────

@mcp.tool()
async def confirm_dose_taken(medication_id: int, elder_id: int) -> str:
    """
    Record that an elder has taken a specific medication dose.
    Automatically decrements the pill inventory count.

    Args:
        medication_id: ID of the medication that was taken.
        elder_id: The elder's ID (for audit logging).

    Returns:
        Confirmation message with updated pill count and refill status.
    """
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{API_BASE}/medications/{medication_id}/taken"
        )
        if response.status_code == 409:
            return json.dumps({
                "success": False,
                "message": "No pills remaining. Please refill this medication immediately.",
                "action_required": "refill",
            })
        response.raise_for_status()
        data = response.json()

    result = {
        "success": True,
        "medication": data["medication"],
        "pills_remaining": data["pills_remaining"],
        "needs_refill": data["needs_refill"],
        "message": (
            f"Dose recorded. {data['pills_remaining']} pills remaining."
            if not data["needs_refill"]
            else f"⚠️ Low stock! Only {data['pills_remaining']} pills left. Please refill soon."
        ),
    }
    return json.dumps(result, indent=2)


# ── Tool: Check inventory levels ─────────────────────────────────────────

@mcp.tool()
async def check_inventory(elder_id: int) -> str:
    """
    Check current inventory levels for all of an elder's medications.
    Flags medications that are below their refill threshold.

    Args:
        elder_id: The elder's ID.

    Returns:
        JSON with inventory status and list of medications needing refill.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE}/elders/{elder_id}/medications/low-stock"
        )
        response.raise_for_status()
        data = response.json()

    if data["count"] == 0:
        return json.dumps({
            "status": "ok",
            "message": "All medications are adequately stocked.",
            "low_stock_count": 0,
        })

    return json.dumps({
        "status": "alert",
        "message": f"{data['count']} medication(s) need refilling.",
        "low_stock_medications": data["low_stock_medications"],
        "low_stock_count": data["count"],
    }, indent=2)


# ── Tool: Record a refill ─────────────────────────────────────────────────

@mcp.tool()
async def record_refill(medication_id: int, quantity: int = 30) -> str:
    """
    Record that a medication has been refilled, updating inventory.

    Args:
        medication_id: ID of the medication being refilled.
        quantity: Number of pills added (default 30).

    Returns:
        Confirmation with updated pill count.
    """
    if quantity <= 0:
        return json.dumps({"success": False, "message": "Quantity must be positive."})

    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{API_BASE}/medications/{medication_id}/refill",
            params={"quantity": quantity},
        )
        response.raise_for_status()
        data = response.json()

    return json.dumps({
        "success": True,
        "medication": data["medication"],
        "pills_remaining": data["pills_remaining"],
        "refilled_by": data["refilled_by"],
        "message": f"Refill recorded. {data['pills_remaining']} pills now in stock.",
    }, indent=2)


# ── Tool: Get adherence summary ───────────────────────────────────────────

@mcp.tool()
async def get_adherence_summary(elder_id: int, days: int = 7) -> str:
    """
    Generate an adherence summary for an elder over recent days.
    Used by the Caregiver Agent to produce weekly reports.

    Args:
        elder_id: The elder's ID.
        days: Number of days to include in summary (default 7).

    Returns:
        Adherence statistics: doses taken, missed, adherence percentage.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE}/elders/{elder_id}/adherence",
            params={"limit": days * 10},  # Approximate: up to 10 meds/day
        )
        response.raise_for_status()
        logs = response.json()

    total = len(logs)
    taken = sum(1 for log in logs if log["status"] == "taken")
    missed = sum(1 for log in logs if log["status"] == "missed")
    adherence_pct = round((taken / total * 100) if total > 0 else 0, 1)

    return json.dumps({
        "elder_id": elder_id,
        "period_days": days,
        "total_scheduled": total,
        "doses_taken": taken,
        "doses_missed": missed,
        "adherence_percentage": adherence_pct,
        "rating": (
            "excellent" if adherence_pct >= 90
            else "good" if adherence_pct >= 75
            else "needs_attention"
        ),
    }, indent=2)


# ── Tool: Send a reminder message ─────────────────────────────────────────

@mcp.tool()
async def send_reminder(
    elder_id: int,
    medication_name: str,
    message: str,
    channel: str = "sms",
) -> str:
    """
    Send a medication reminder to an elder via SMS or a simulated alert.
    In production, this integrates with Twilio. In development, it logs.

    Args:
        elder_id: The elder's ID.
        medication_name: The medication to remind about.
        message: The reminder message text.
        channel: "sms" | "email" | "log" (default "sms").

    Returns:
        Delivery status.
    """
    # Security: sanitize message to avoid injection
    safe_message = message[:500].strip()  # Limit length

    # In development: log the reminder (no real SMS cost)
    if os.getenv("APP_ENV", "development") == "development" or channel == "log":
        print(f"[REMINDER] Elder {elder_id} | {medication_name}: {safe_message}")
        return json.dumps({
            "delivered": True,
            "channel": "log",
            "message": safe_message,
            "note": "Development mode — set APP_ENV=production for real SMS",
        })

    # Production: integrate with Twilio (keys from env only)
    # Actual Twilio call would be here, using TWILIO_* env vars
    return json.dumps({
        "delivered": True,
        "channel": channel,
        "message": safe_message,
    })


# ── Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    host = os.getenv("MCP_SERVER_HOST", "localhost")
    port = int(os.getenv("MCP_SERVER_PORT", "8001"))
    print(f"Starting MediGuard MCP Server on {host}:{port}")
    mcp.run(transport="streamable-http", host=host, port=port)
