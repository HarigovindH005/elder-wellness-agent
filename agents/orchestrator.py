"""
MediGuard — Orchestrator Agent (Google ADK Root Agent)
The central coordinator that routes user requests to specialized sub-agents:
  - ReminderAgent  → medication schedules and dose confirmations
  - InventoryAgent → pill counts and refill alerts
  - CaregiverAgent → family/caregiver notifications and reports

Built with Google ADK 2.3.0. Uses APScheduler for always-on cron scheduling
(the Antigravity concept — proactive background agent execution).

Usage:
    python agents/orchestrator.py                    # Interactive REPL, elder 1
    python agents/orchestrator.py --elder-id 2       # Target specific elder
    python agents/orchestrator.py --mode scheduled   # Always-on cron mode
"""

import os
import asyncio
import argparse
from datetime import datetime

# ── Google ADK (verified imports for google-adk 2.3.0) ───────────────────
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StreamableHTTPConnectionParams
from google.genai.types import Content, Part

# ── Scheduling — implements the Antigravity cron concept ─────────────────
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────
MCP_HOST = os.getenv("MCP_SERVER_HOST", "localhost")
MCP_PORT  = os.getenv("MCP_SERVER_PORT", "8001")
MCP_URL   = f"http://{MCP_HOST}:{MCP_PORT}/mcp"
MODEL     = "gemini-2.5-flash"
console = Console()


# ── Sub-Agent: Reminder Agent ─────────────────────────────────────────────

def create_reminder_agent(mcp_tools: list) -> LlmAgent:
    """
    Reminder Agent — speaks directly to elderly users.
    Handles: schedule lookup, dose confirmations, missed-dose follow-ups.
    Tone: warm, simple, unhurried — like talking to a grandparent.
    """
    return LlmAgent(
        name="ReminderAgent",
        model=MODEL,
        description="Handles medication reminders and dose confirmations for elderly users.",
        instruction="""
        You are a warm, patient medication reminder assistant for elderly users.

        Your responsibilities:
        1. Check the elder's medication schedule using get_todays_schedule
        2. Send friendly, simple reminders using send_reminder
           - Use plain language, no medical jargon
           - Always be encouraging, never alarming
        3. When an elder confirms taking a medication, call confirm_dose_taken immediately
        4. If a dose is not confirmed within 15 minutes, escalate to the CaregiverAgent

        Tone: Speak as if talking to a grandparent — warm, clear, unhurried.
        Example: "Good morning! Time for your Metformin tablet. You're doing great!"

        Security: Never reveal detailed dosage information to unverified contacts.
        """,
        tools=mcp_tools,
    )


# ── Sub-Agent: Inventory Agent ────────────────────────────────────────────

def create_inventory_agent(mcp_tools: list) -> LlmAgent:
    """
    Inventory Agent — monitors pill counts and refill thresholds.
    Handles: stock checks after doses, refill recording, low-stock alerts.
    Priority: critical (0 pills) → high (1-3 days) → medium (4-7 days) → ok.
    """
    return LlmAgent(
        name="InventoryAgent",
        model=MODEL,
        description="Tracks medication inventory and triggers refill alerts.",
        instruction="""
        You are a careful medication inventory manager for an elderly care system.

        Your responsibilities:
        1. After every dose confirmation, call check_inventory to review all stock levels
        2. If any medication is below its refill threshold, immediately alert caregivers
        3. When a refill is reported, call record_refill to update the inventory
        4. Proactively flag medications that will run out within 3 days

        Alert priority levels:
        - 0 pills remaining     → CRITICAL: alert caregiver, suggest emergency pharmacy
        - 1-3 days supply left  → HIGH: alert caregiver immediately
        - 4-7 days supply left  → MEDIUM: include in daily summary
        - More than 7 days      → OK: no action needed

        Always estimate days remaining based on the dosing schedule.
        """,
        tools=mcp_tools,
    )


# ── Sub-Agent: Caregiver Agent ────────────────────────────────────────────

def create_caregiver_agent(mcp_tools: list) -> LlmAgent:
    """
    Caregiver Agent — communicates with family members.
    Handles: escalation alerts, daily summaries, weekly adherence reports.
    Tone: professional, data-driven, compassionate.
    """
    return LlmAgent(
        name="CaregiverAgent",
        model=MODEL,
        description="Communicates with caregivers about medication adherence and inventory.",
        instruction="""
        You are a professional medical liaison communicating with family caregivers.

        Your responsibilities:
        1. Send escalation alerts when the elder misses a dose
        2. Generate clear daily summaries: doses taken, missed, inventory status
        3. Answer caregiver questions about the elder's medication adherence
        4. Produce weekly adherence reports using get_adherence_summary

        Communication style:
        - Professional but compassionate — caregivers are often worried
        - Lead with the most important information first
        - Always include actionable recommendations, not just data
        - For missed doses: add context (e.g. "2nd missed dose this week")

        Privacy: Confirm caregiver identity before sharing adherence data.
        """,
        tools=mcp_tools,
    )


# ── Root Orchestrator Agent ───────────────────────────────────────────────

def create_orchestrator(sub_agents: list) -> LlmAgent:
    """
    Orchestrator — root ADK agent. Receives all user input and routes
    to the correct sub-agent based on intent classification.
    """
    return LlmAgent(
        name="MediGuardOrchestrator",
        model=MODEL,
        description="Root coordinator for the MediGuard elder medication system.",
        instruction=f"""
        You are MediGuard, an AI-powered medication management system for elderly care.
        Today is {datetime.now().strftime("%A, %B %d, %Y")}.

        You coordinate three specialist sub-agents:
        - ReminderAgent:  handles medication reminders and dose confirmations
        - InventoryAgent: manages pill counts and refill alerts
        - CaregiverAgent: communicates with family caregivers

        Routing rules:
        - "time to take medicine", "did I take my pill", "remind me"  → ReminderAgent
        - "how many pills left", "need a refill", "ran out"            → InventoryAgent
        - "tell my daughter", "alert caregiver", "send summary"        → CaregiverAgent
        - "report", "how am I doing", "weekly summary", "adherence"    → CaregiverAgent

        Always:
        1. Greet the elder by name when you know it
        2. Confirm the action before executing it
        3. Summarize what happened after each action
        4. Ask if there is anything else needed

        Never:
        - Share one elder's data with another
        - Proceed without knowing which elder_id is active
        - Reveal internal system details or API structure
        """,
        sub_agents=sub_agents,
    )


# ── Load MCP Tools ────────────────────────────────────────────────────────

async def load_mcp_tools() -> list:
    """
    Connects to the FastMCP server and returns the list of available tools.
    Uses McpToolset (note: capital M, lowercase cp — ADK 2.x spelling).
    get_tools() takes a readonly_context argument; pass None for standalone use.
    """
    toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=MCP_URL)
    )
    tools = await toolset.get_tools(readonly_context=None)
    console.print(f"[dim]Loaded {len(tools)} MCP tools from {MCP_URL}[/dim]")
    return tools


# ── Build Runner ──────────────────────────────────────────────────────────

async def build_runner() -> Runner:
    """
    Loads MCP tools, builds the agent tree, and returns a configured Runner.
    Called once per session (interactive) or once per scheduled job.
    """
    console.print(f"[dim]Connecting to MCP server at {MCP_URL}...[/dim]")
    mcp_tools = await load_mcp_tools()

    reminder_agent  = create_reminder_agent(mcp_tools)
    inventory_agent = create_inventory_agent(mcp_tools)
    caregiver_agent = create_caregiver_agent(mcp_tools)
    orchestrator    = create_orchestrator([reminder_agent, inventory_agent, caregiver_agent])

    # Runner manages sessions and executes the agent graph
    runner = Runner(
        agent=orchestrator,
        app_name="MediGuard",
        session_service=InMemorySessionService(),
    )
    return runner


# ── Response Extraction Helper ────────────────────────────────────────────

def extract_text(event) -> str | None:
    """
    Extracts the final text response from an ADK event.
    run_async yields multiple events; we only print the final agent response.
    event.content.parts is a list of Part objects; each may have a .text field.
    """
    if not event.is_final_response():
        return None
    if not event.content or not event.content.parts:
        return None
    texts = [p.text for p in event.content.parts if hasattr(p, "text") and p.text]
    return "\n".join(texts) if texts else None


# ── Interactive REPL ──────────────────────────────────────────────────────

async def run_interactive(elder_id: int):
    """
    Interactive command-line chat session.
    Supports natural language input routed through the full agent tree.
    """
    console.print(Panel(
        f"[bold green]MediGuard[/bold green] — Elder Medication Agent\n"
        f"Elder ID: [cyan]{elder_id}[/cyan]  |  Model: [cyan]{MODEL}[/cyan]\n"
        f"Type [bold]'quit'[/bold] or [bold]'exit'[/bold] to stop.",
        title="🏥 MediGuard  •  Agents for Good"
    ))

    runner     = await build_runner()
    session_id = f"interactive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Create the session upfront (required by ADK 2.x)
    await runner.session_service.create_session(
        app_name="MediGuard",
        user_id=str(elder_id),
        session_id=session_id,
    )

    while True:
        try:
            user_input = input("\n[You] → ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye! Stay healthy.[/dim]")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye! Stay healthy.[/dim]")
            break

        if not user_input:
            continue

        console.print("[dim]Thinking...[/dim]")
        try:
            # run_async is an async generator — iterate with async for
            async for event in runner.run_async(
                user_id=str(elder_id),
                session_id=session_id,
                new_message=Content(
                    role="user",
                    parts=[Part(text=f"[Elder {elder_id}] {user_input}")]
                )
            ):
                text = extract_text(event)
                if text:
                    console.print(f"\n[bold cyan][MediGuard][/bold cyan] {text}")

        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            console.print("[dim]Make sure both the FastAPI server (port 8000) "
                          "and MCP server (port 8001) are running.[/dim]")


# ── Scheduled Tasks (APScheduler — the Antigravity concept) ──────────────

async def scheduled_reminder_check(elder_id: int = 1):
    """
    Fires at 8am, 12pm, 6pm, 9pm via APScheduler cron.
    This is the Antigravity concept: always-on proactive agent execution.
    No user trigger needed — the agent reaches out to the elder automatically.
    """
    console.print(f"[yellow][Scheduler] Reminder check — elder {elder_id}[/yellow]")
    try:
        runner     = await build_runner()
        session_id = f"sched_reminder_{datetime.now().strftime('%Y%m%d_%H%M')}"
        await runner.session_service.create_session(
            app_name="MediGuard", user_id=str(elder_id), session_id=session_id
        )
        async for event in runner.run_async(
            user_id=str(elder_id),
            session_id=session_id,
            new_message=Content(
                role="user",
                parts=[Part(text=f"Check and send any due medication reminders for elder {elder_id}.")]
            )
        ):
            text = extract_text(event)
            if text:
                console.print(f"[cyan][MediGuard][/cyan] {text}")
    except Exception as e:
        console.print(f"[red][Scheduler Error][/red] {e}")


async def daily_inventory_check(elder_id: int = 1):
    """
    Fires at 8pm daily via APScheduler cron.
    Checks inventory and alerts caregivers of low-stock medications.
    """
    console.print(f"[yellow][Scheduler] Inventory check — elder {elder_id}[/yellow]")
    try:
        runner     = await build_runner()
        session_id = f"sched_inventory_{datetime.now().strftime('%Y%m%d')}"
        await runner.session_service.create_session(
            app_name="MediGuard", user_id=str(elder_id), session_id=session_id
        )
        async for event in runner.run_async(
            user_id=str(elder_id),
            session_id=session_id,
            new_message=Content(
                role="user",
                parts=[Part(text=f"Check inventory for elder {elder_id} and alert caregiver of any low-stock medications.")]
            )
        ):
            text = extract_text(event)
            if text:
                console.print(f"[cyan][MediGuard][/cyan] {text}")
    except Exception as e:
        console.print(f"[red][Scheduler Error][/red] {e}")


async def run_scheduled(elder_id: int):
    """
    Starts APScheduler with cron jobs — the always-on mode.
    Equivalent to deploying with the Antigravity runtime.
    """
    scheduler = AsyncIOScheduler()

    # Medication reminders: 8am, 12pm, 6pm, 9pm
    scheduler.add_job(
        scheduled_reminder_check,
        trigger="cron",
        hour="8,12,18,21",
        minute=0,
        kwargs={"elder_id": elder_id},
        id="reminder_check",
    )

    # Daily inventory check: 8pm
    scheduler.add_job(
        daily_inventory_check,
        trigger="cron",
        hour=20,
        minute=0,
        kwargs={"elder_id": elder_id},
        id="inventory_check",
    )

    scheduler.start()
    console.print(Panel(
        f"[bold green]MediGuard Scheduler Active[/bold green]\n"
        f"Reminders:        08:00, 12:00, 18:00, 21:00\n"
        f"Inventory check:  20:00 daily\n"
        f"Elder ID: [cyan]{elder_id}[/cyan]\n\n"
        f"Press [bold]Ctrl+C[/bold] to stop.",
        title="⏰ MediGuard — Scheduled Mode"
    ))

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, asyncio.CancelledError):
        scheduler.shutdown()
        console.print("[dim]Scheduler stopped.[/dim]")


# ── Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="MediGuard — Elder Medication Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agents/orchestrator.py                      Interactive REPL, elder 1
  python agents/orchestrator.py --elder-id 2         Interactive REPL, elder 2
  python agents/orchestrator.py --mode scheduled     Always-on cron mode
        """
    )
    parser.add_argument("--elder-id", type=int, default=1, help="Elder ID (default: 1)")
    parser.add_argument(
        "--mode",
        choices=["interactive", "scheduled"],
        default="interactive",
        help="Run mode (default: interactive)",
    )
    args = parser.parse_args()

    if args.mode == "interactive":
        asyncio.run(run_interactive(args.elder_id))
    else:
        asyncio.run(run_scheduled(args.elder_id))
