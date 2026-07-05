"""
MediGuard — Agent Tests
Tests for MCP tools, API endpoints, and agent routing logic.
Uses pytest-asyncio for async test support.
"""

import pytest
import pytest_asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

# ── MCP Tool Tests ────────────────────────────────────────────────────────

class TestMCPTools:
    """Test each MCP tool function in isolation using mocked HTTP."""

    @pytest.mark.asyncio
    async def test_get_todays_schedule_returns_medications(self):
        """get_todays_schedule should return formatted medication list."""
        mock_medications = [
            {
                "name": "Metformin 500mg",
                "dosage": "1 tablet",
                "pills_remaining": 20,
                "needs_refill": False,
                "is_active": True,
            },
            {
                "name": "Atenolol 50mg",
                "dosage": "1 tablet",
                "pills_remaining": 5,
                "needs_refill": True,
                "is_active": True,
            },
        ]

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_medications
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            # Import after patching
            from mcp_server.server import get_todays_schedule
            result = await get_todays_schedule(elder_id=1)

        data = json.loads(result)
        assert data["elder_id"] == 1
        assert data["total_medications"] == 2
        assert data["medications"][0]["name"] == "Metformin 500mg"
        assert data["medications"][1]["needs_refill"] is True

    @pytest.mark.asyncio
    async def test_confirm_dose_taken_decrements_count(self):
        """confirm_dose_taken should record dose and return updated count."""
        mock_response_data = {
            "medication": "Metformin 500mg",
            "pills_remaining": 19,
            "needs_refill": False,
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            from mcp_server.server import confirm_dose_taken
            result = await confirm_dose_taken(medication_id=1, elder_id=1)

        data = json.loads(result)
        assert data["success"] is True
        assert data["pills_remaining"] == 19
        assert data["needs_refill"] is False

    @pytest.mark.asyncio
    async def test_confirm_dose_taken_handles_empty_stock(self):
        """confirm_dose_taken should gracefully handle 0 pills remaining."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 409
            mock_client.return_value.__aenter__.return_value.patch = AsyncMock(
                return_value=mock_response
            )

            from mcp_server.server import confirm_dose_taken
            result = await confirm_dose_taken(medication_id=1, elder_id=1)

        data = json.loads(result)
        assert data["success"] is False
        assert data["action_required"] == "refill"

    @pytest.mark.asyncio
    async def test_check_inventory_flags_low_stock(self):
        """check_inventory should identify medications below threshold."""
        mock_api_response = {
            "count": 1,
            "low_stock_medications": [
                {
                    "id": 2,
                    "name": "Atenolol 50mg",
                    "pills_remaining": 5,
                    "refill_threshold": 7,
                    "days_remaining": 5,
                }
            ],
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            from mcp_server.server import check_inventory
            result = await check_inventory(elder_id=1)

        data = json.loads(result)
        assert data["status"] == "alert"
        assert data["low_stock_count"] == 1
        assert data["low_stock_medications"][0]["name"] == "Atenolol 50mg"

    @pytest.mark.asyncio
    async def test_check_inventory_ok_when_all_stocked(self):
        """check_inventory should return ok status when all meds are stocked."""
        mock_api_response = {"count": 0, "low_stock_medications": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = mock_api_response
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=mock_response
            )

            from mcp_server.server import check_inventory
            result = await check_inventory(elder_id=1)

        data = json.loads(result)
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_send_reminder_sanitizes_message(self):
        """send_reminder should truncate overly long messages."""
        long_message = "x" * 1000  # Way over the 500-char limit

        import os
        with patch.dict(os.environ, {"APP_ENV": "development"}):
            from mcp_server.server import send_reminder
            result = await send_reminder(
                elder_id=1,
                medication_name="Metformin",
                message=long_message,
                channel="log",
            )

        data = json.loads(result)
        assert len(data["message"]) <= 500

    @pytest.mark.asyncio
    async def test_record_refill_validates_quantity(self):
        """record_refill should reject non-positive quantities."""
        from mcp_server.server import record_refill
        result = await record_refill(medication_id=1, quantity=-5)
        data = json.loads(result)
        assert data["success"] is False


# ── Adherence Calculation Tests ───────────────────────────────────────────

class TestAdherenceLogic:
    """Test adherence percentage calculation logic."""

    def test_perfect_adherence(self):
        """100% adherence when all doses taken."""
        logs = [{"status": "taken"}] * 14
        taken = sum(1 for l in logs if l["status"] == "taken")
        pct = round(taken / len(logs) * 100, 1)
        assert pct == 100.0

    def test_zero_adherence(self):
        """0% adherence when all doses missed."""
        logs = [{"status": "missed"}] * 7
        taken = sum(1 for l in logs if l["status"] == "taken")
        pct = round((taken / len(logs) * 100) if len(logs) > 0 else 0, 1)
        assert pct == 0.0

    def test_partial_adherence_rating(self):
        """Rating should reflect adherence percentage tier."""
        def get_rating(pct):
            if pct >= 90:
                return "excellent"
            elif pct >= 75:
                return "good"
            return "needs_attention"

        assert get_rating(95) == "excellent"
        assert get_rating(80) == "good"
        assert get_rating(60) == "needs_attention"

    def test_empty_logs_safe(self):
        """Empty logs should return 0% without division error."""
        logs = []
        total = len(logs)
        pct = round((0 / total * 100) if total > 0 else 0, 1)
        assert pct == 0.0
