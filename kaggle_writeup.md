# MediGuard: An AI Multi-Agent System for Elder Medication Management

**Subtitle:** Using Google ADK, FastMCP, and Antigravity to build a compassionate, always-on medication reminder and inventory tracking system for elderly users

**Track:** Agents for Good

**Author:** Govind | B.Tech AI & Data Science, VJEC

---

## 1. The Problem: A Silent Healthcare Crisis (~300 words)

Medication non-adherence among elderly patients is one of the most underappreciated healthcare crises of our time. Studies consistently show that **more than 50% of elderly patients do not take medications as prescribed**, leading to preventable hospitalizations, disease progression, and billions in avoidable healthcare costs annually.

The challenge is not willpower — it is complexity. An average elderly person manages **5 to 10 medications** simultaneously, each with different dosing schedules, food interaction requirements, and refill timelines. A person managing diabetes, hypertension, and heart disease might need to take medications at 7am, 12pm, 6pm, and 9pm — each from a different bottle, each with a different instruction.

The secondary problem is inventory blindness. Elders often don't realize they're running low on a medication until they reach for the bottle and find it empty. Family caregivers, who may live separately, have no visibility into day-to-day adherence.

Current solutions — pill organizers, phone alarm apps, caregiver phone calls — are fragile. They require the elder to remember to set up the system correctly, and they provide no feedback loop: there is no way to know whether a reminder was acted on.

**MediGuard** addresses this with an AI agent system that is always on, conversational, and genuinely helpful — treating every elder as an individual, not a notification target.

---

## 2. The Solution: MediGuard (~400 words)

MediGuard is a multi-agent AI system that does three things: it **reminds** elders to take their medications in a warm, patient voice; it **tracks** inventory and alerts caregivers when refills are needed; and it **reports** adherence data to family members so they can stay informed without needing to call every day.

The system is designed around three core design principles:

**Accessibility first.** Every interaction is in plain, conversational language. The elder never needs to navigate a menu or learn an app. They can say "did I take my blood pressure pill today?" and get a clear, direct answer.

**Background awareness.** The system doesn't wait to be asked. Powered by Antigravity's scheduling runtime, it proactively sends reminders at the right time, checks inventory after every dose, and sends caregivers a daily summary — without any manual trigger.

**Caregiver visibility.** Family members can query the Caregiver Agent to learn about recent adherence, get low-stock alerts, and understand trends — giving them peace of mind without replacing the elder's independence.

A typical MediGuard interaction looks like this:

- **8:00 AM** → Antigravity triggers the scheduled check. The Orchestrator Agent asks the Reminder Agent to send morning medication reminders.
- **8:05 AM** → The elder receives: *"Good morning! It's time for your Metformin 500mg (1 tablet with breakfast) and Atenolol 50mg. Say 'done' when you've taken them."*
- **8:07 AM** → The elder replies "done." The Reminder Agent calls `confirm_dose_taken`, which decrements inventory. The Inventory Agent sees Atenolol is now at 5 pills — below the 7-pill threshold — and triggers a caregiver alert.
- **8:08 AM** → The elder's daughter receives: *"Low stock alert: Ramesh's Atenolol 50mg has 5 days supply remaining. Please arrange a refill."*
- **8:20 PM** → Antigravity runs the daily summary job. The Caregiver Agent generates: *"Today's adherence for Ramesh: 4/4 doses taken (100%). All evening doses confirmed."*

This entire flow requires zero manual intervention after initial setup. The agents handle scheduling, confirmation, inventory, and communication — all coordinated through the MCP tool layer.

---

## 3. Architecture (~500 words)

MediGuard is built on a four-layer architecture:

```
User / Caregiver
      │
      ▼
Orchestrator Agent  (Google ADK root agent, Antigravity runtime)
      │
      ├── ReminderAgent   (dose schedules, confirmations, follow-ups)
      ├── InventoryAgent  (pill counts, refill thresholds, alerts)
      └── CaregiverAgent  (family notifications, weekly reports)
      │
      ▼
FastMCP Server  (tool layer: 6 tools exposing medication operations)
      │
      ▼
FastAPI Backend + SQLite  (REST API, data persistence)
```

### Layer 1: Google ADK Agents

The **Orchestrator Agent** is the root ADK agent. It receives all input — whether from a scheduled Antigravity trigger or a direct user message — and routes it to the appropriate sub-agent based on intent classification.

Three specialist sub-agents handle specific domains:

- **ReminderAgent**: Manages the reminder workflow. Calls `get_todays_schedule`, sends reminders via `send_reminder`, records confirmations via `confirm_dose_taken`. If a dose is not confirmed within 15 minutes, it escalates to the CaregiverAgent.
- **InventoryAgent**: Monitors stock after each dose using `check_inventory`. Applies a priority system: 0 pills = critical, 1–3 days = high, 4–7 days = medium. Triggers appropriate alerts at each level.
- **CaregiverAgent**: Handles outbound communication to family. Generates adherence summaries using `get_adherence_summary`, sends escalation alerts for missed doses, and answers caregiver queries about the elder's status.

The agent instruction prompts are carefully tuned: the ReminderAgent speaks in warm, plain language for elders; the CaregiverAgent speaks in professional, data-driven language for family members. These are different audiences with different needs.

### Layer 2: FastMCP Server

The MCP Server exposes six tools that agents call to interact with the backend:

| Tool | Purpose |
|---|---|
| `get_todays_schedule` | Fetch all active medications for an elder |
| `confirm_dose_taken` | Record a dose and decrement inventory |
| `check_inventory` | Identify medications below refill threshold |
| `record_refill` | Update inventory after a refill |
| `get_adherence_summary` | Generate adherence statistics for caregivers |
| `send_reminder` | Dispatch SMS or logged reminder to an elder |

This MCP layer is the key architectural decision: agents never touch the database directly. They only call tools. This makes the system modular — you can swap the backend from SQLite to PostgreSQL without changing any agent code.

### Layer 3: FastAPI Backend

A lightweight REST API handles data persistence using SQLite with WAL (Write-Ahead Logging) mode for concurrent access safety. The database schema models Elders, Medications, Schedules, Adherence Logs, and Caregiver Links.

All API inputs are validated via Pydantic schemas. Pill counts use atomic increment/decrement operations to prevent race conditions.

### Layer 4: Antigravity Runtime

Antigravity powers the always-on scheduling layer. The `@antigravity.scheduled` decorator runs the reminder check at 8am, 12pm, 6pm, and 9pm daily — aligned with typical medication schedules. The inventory check runs at 8pm to give caregivers evening notice before the next morning.

Without Antigravity, the system would require a separate cron setup or an external scheduler. Antigravity integrates this into the agent runtime, making deployment to production as simple as a single command.

---

## 4. Key Concepts Demonstrated (~300 words)

This project demonstrates all five required key concepts:

**Multi-agent system (ADK):** MediGuard uses a root Orchestrator Agent that coordinates three specialist sub-agents — ReminderAgent, InventoryAgent, and CaregiverAgent. Each agent has a distinct instruction prompt, tools, and area of responsibility. The Orchestrator routes intent, sub-agents execute. This is visible in `agents/orchestrator.py`.

**MCP Server:** The FastMCP server in `mcp_server/server.py` exposes six typed, documented tools. Each tool is an async function decorated with `@mcp.tool()` and includes complete docstrings explaining parameters and return values. Agents connect to this via `MCPToolset` with `StreamableHTTPConnectionParams`.

**Antigravity:** The `@antigravity.scheduled(cron="...")` decorators in `agents/orchestrator.py` enable proactive, time-based agent execution without manual triggers. This is demonstrated in the video, where the system sends a reminder unprompted at a scheduled time.

**Security features:** API keys are never hardcoded — they are loaded from environment variables via `python-dotenv`. An `.env.example` template is provided with placeholder values. Message content is sanitized (length-capped) before sending. Caregiver endpoints are protected by JWT authentication. Input validation is enforced on all API endpoints via Pydantic.

**Deployability:** The system uses environment-variable-based configuration, making it straightforward to deploy to any cloud provider. Health check endpoints (`/health`) support container orchestrators. SQLite can be swapped for PostgreSQL by changing `DATABASE_URL`. A Docker-ready structure is documented in the README.

---

## 5. What I Learned (~200 words)

Building MediGuard changed how I think about agents. An agent is not just a chatbot with tools — it's a system with a **job to do on behalf of someone who trusts it**. Designing the Orchestrator to properly route intent, and giving each sub-agent a genuinely distinct instruction prompt, was harder than expected. The ReminderAgent that speaks to an elderly person must not sound like the CaregiverAgent that reports to a doctor.

The MCP layer was the most valuable architectural decision I made. By separating tool definitions from agent logic, I could iterate on the API without breaking any agent code. This modularity also made testing dramatically easier — each tool is a pure async function that can be tested with mocked HTTP.

Antigravity's scheduling was a revelation: making agents *proactive* rather than reactive transforms the system from a query-answering tool into a genuine care companion. An elder doesn't need to remember to ask — the system remembers for them.

The hardest part was the tone. Writing instruction prompts that are technically precise but also warm and patient took more iteration than any code. Agents are only as good as the judgment embedded in their instructions.

---

## 6. Project Links

- **GitHub Repository:** [github.com/yourusername/elder-wellness-agent](https://github.com/yourusername/elder-wellness-agent)
- **YouTube Demo:** [youtu.be/your-video-id](https://youtu.be/your-video-id)
- **Live Demo:** [mediguard-demo.yourdomain.com](https://mediguard-demo.yourdomain.com) *(if deployed)*

---

*Word count: ~1,700 words (within 2,500 limit)*
