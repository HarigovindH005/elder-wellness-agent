# 💊 MediGuard — Elder Medication Reminder & Inventory Agent

> An AI-powered multi-agent system built with Google ADK, FastMCP, and FastAPI that helps elderly users manage medications, track inventory, and get timely reminders — powered by Antigravity.

---

## 🎯 Problem Statement

Over **50% of elderly patients** do not take medications as prescribed. Missed doses lead to hospitalizations, complications, and unnecessary healthcare costs. Elderly individuals often manage 5–10+ medications with complex schedules, and caregivers cannot always be present.

**MediGuard** solves this with a compassionate AI agent system that:
- Reminds elders to take medications at the right time
- Tracks inventory levels and alerts when refills are needed
- Enables caregivers to monitor adherence remotely
- Uses natural language for accessible, friendly interaction

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User / Caregiver                      │
│              (Web UI / Voice / SMS / WhatsApp)           │
└──────────────────────┬──────────────────────────────────┘
                       │
              ┌────────▼────────┐
              │  Orchestrator   │  ← Google ADK Root Agent
              │     Agent       │    (Antigravity runtime)
              └────────┬────────┘
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼──────┐ ┌─────▼──────┐ ┌────▼────────┐
│  Reminder    │ │ Inventory  │ │  Caregiver  │
│   Agent      │ │   Agent    │ │    Agent    │
│ (schedules,  │ │ (stock,    │ │ (alerts,    │
│  alarms)     │ │  refills)  │ │  reports)   │
└───────┬──────┘ └─────┬──────┘ └────┬────────┘
        │              │              │
        └──────────────▼──────────────┘
                       │
              ┌────────▼────────┐
              │   FastMCP       │  ← MCP Server (tool layer)
              │   Server        │    medication_tools
              └────────┬────────┘
                       │
              ┌────────▼────────┐
              │   FastAPI       │  ← REST API + SQLite DB
              │   Backend       │
              └─────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- pip

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/elder-wellness-agent
cd elder-wellness-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your API keys
# GOOGLE_API_KEY=your_google_api_key_here
# (Never commit real API keys!)
```

### Run the System

```bash
# Terminal 1: Start FastAPI backend
uvicorn api.main:app --reload --port 8000

# Terminal 2: Start MCP Server
python mcp_server/server.py

# Terminal 3: Start the agent system
python agents/orchestrator.py
```

### Run Tests

```bash
pytest tests/ -v
```

---

## 📁 Project Structure

```
elder-wellness-agent/
├── agents/
│   ├── orchestrator.py      # Root ADK agent — coordinates all sub-agents
│   ├── reminder_agent.py    # Schedules and fires medication reminders
│   ├── inventory_agent.py   # Tracks pill counts and refill thresholds
│   └── caregiver_agent.py   # Sends alerts/summaries to caregivers
├── mcp_server/
│   ├── server.py            # FastMCP server exposing medication tools
│   └── tools/
│       ├── medication_tools.py   # CRUD for medications
│       ├── schedule_tools.py     # Schedule management
│       └── notification_tools.py # SMS/email notifications
├── api/
│   ├── main.py              # FastAPI application entry point
│   ├── models.py            # Pydantic + SQLAlchemy models
│   ├── routes/
│   │   ├── medications.py   # Medication CRUD endpoints
│   │   ├── schedules.py     # Schedule endpoints
│   │   └── adherence.py     # Adherence tracking endpoints
│   └── database.py          # SQLite database setup
├── frontend/
│   └── index.html           # Simple caregiver dashboard
├── tests/
│   ├── test_agents.py       # Agent unit tests
│   ├── test_mcp.py          # MCP server tests
│   └── test_api.py          # API integration tests
├── docs/
│   └── architecture.md      # Detailed architecture docs
├── requirements.txt
├── .env.example
└── README.md
```

---

## 🔑 Key Concepts Demonstrated

| Concept | Where |
|---|---|
| Multi-agent system (ADK) | `agents/orchestrator.py`, `agents/*.py` |
| MCP Server | `mcp_server/server.py` |
| Antigravity | Agent deployment runtime (video demo) |
| Security features | `.env` secrets management, input validation, rate limiting |
| Deployability | Docker-ready, env-based config, health endpoints |
| Agent skills (CLI) | `agents/orchestrator.py` — ADK skill registration |

---

## 🛡 Security

- API keys loaded from environment variables only — never hardcoded
- Input validation on all endpoints via Pydantic
- Rate limiting on notification endpoints
- Caregiver access protected by token-based auth
- Medication data encrypted at rest (SQLite WAL mode)

---

## 📄 License

MIT License — see LICENSE file.
