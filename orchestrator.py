"""
MediGuard — Orchestrator Agent (Google ADK Root Agent)
The central coordinator that routes user requests to specialized sub-agents:
  - ReminderAgent  → medication schedules and dose confirmations
  - InventoryAgent → pill counts and refill alerts
  - CaregiverAgent → family/caregiver notifications and reports

Built with Google ADK. Runs on Antigravity for always-on scheduling.

Usage:
    python agents/orchestrator.py                  # Interactive REPL
    python agents/orchestrator.py --elder-id 1     # Target a specific elder
"""

import os
import asyncio
import argparse
from datetime import datetime
from typing import Optional

# Google ADK imports
# NOTE: Install with: pip install google-adk
try:
    from google.adk.agents import Agent, AgentSkill
    from google.adk.runners import Runner, InMemorySessionService
    from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StreamableHTTPConnectionParams
    from google.genai.types import Content, Part
except ImportError:
    print("⚠️  Google ADK not installed. Run: pip install google-adk")
    print("    Continuing in mock mode for demonstration.")
    Agent = object
    AgentSkill = object

import antigravity  # Antigravity runtime — enables always-on agent scheduling
from dotenv import load_dotenv

load_dotenv()

MCP_SERVER_URL = f"http://{os.getenv('MCP_SERVER_HOST', 'localhost')}:{os.getenv('MCP_SERVER_PORT', '8001')}/mcp"
MODEL = "gemini-2.0-flash"


# ── Sub-Agent: Reminder Agent ─────────────────────────────────────────────

def create_reminder_agent(mcp_tools) -> Agent:
    """
    Reminder Agent — responsible for:
    - Checking which medications are due right now
    - Sending friendly, clear reminders to the elder
    - Recording dose confirmations
    - Following up if a dose is missed (15-min check)
    """
    return Agent(
        name="ReminderAgent",
        model=MODEL,
        description="Handles medication reminders and dose confirmations for elderly users.",
        instruction="""
        You are a warm, patient medication reminder assistant for elderly users.

        Your responsibilities:
        1. Check the elder's medication schedule for today using get_todays_schedule
        2. Send friendly, simple reminders using send_reminder — use plain language,
           avoid medical jargon, and always be encouraging (not alarming)
        3. When an elder says they took a medication, call confirm_dose_taken immediately
        4. If a reminder is not acknowledged in 15 minutes, escalate to the caregiver agent

        Tone guidelines:
        - Speak as if talking to a grandparent: warm, clear, unhurried
        - Use short sentences. Never use technical terms.
        - Always reassure: "You're doing great!"
        - If a dose was missed, be gentle: "It happens — let's see what we can do."

        Security: Never reveal medication dosage details to unverified callers.
        """,
        tools=mcp_tools,
    )


# ── Sub-Agent: Inventory Agent ────────────────────────────────────────────

def create_inventory_agent(mcp_tools) -> Agent:
    """
    Inventory Agent — responsible for:
    - Monitoring pill counts after each dose
    - Alerting when stock drops below the refill threshold
    - Recording refill events
    - Generating weekly inventory reports
    """
    return Agent(
        name="InventoryAgent",
        model=MODEL,
        description="Tracks medication inventory and triggers refill alerts.",
        instruction="""
        You are a careful medication inventory manager for an elderly care system.

        Your responsibilities:
        1. After every dose confirmation, call check_inventory to review all stock levels
        2. If any medication is below its refill threshold, immediately alert the caregiver
        3. When a refill is reported, call record_refill to update the inventory
        4. Proactively flag medications that will run out within 3 days

        Alert priority:
        - 0 pills remaining → CRITICAL: alert caregiver and suggest emergency pharmacy
        - 1–3 days supply → HIGH: alert caregiver now
        - 4–7 days supply → MEDIUM: include in daily summary
        - >7 days supply → OK: no action needed

        Always provide a "days remaining" estimate based on scheduled frequency.
        """,
        tools=mcp_tools,
    )


# ── Sub-Agent: Caregiver Agent ────────────────────────────────────────────

def create_caregiver_agent(mcp_tools) -> Agent:
    """
    Caregiver Agent — responsible for:
    - Sending escalation alerts to family members
    - Generating daily adherence summaries
    - Answering caregiver queries about the elder's status
    - Providing weekly adherence reports
    """
    return Agent(
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
        - Include actionable recommendations, not just data
        - For missed doses: provide context ("2nd missed dose this week")

        Privacy: Only share information with verified caregivers.
        Confirm identity before sharing adherence data.
        """,
        tools=mcp_tools,
    )


# ── Root Orchestrator Agent ───────────────────────────────────────────────

def create_orchestrator(sub_agents: list) -> Agent:
    """
    Orchestrator — the root agent that receives all input and delegates
    to the appropriate sub-agent based on intent.
    """
    return Agent(
        name="MediGuardOrchestrator",
        model=MODEL,
        description="Root coordinator for the MediGuard elder medication system.",
        instruction=f"""
        You are MediGuard, an AI-powered medication management system for elderly care.
        Today is {datetime.now().strftime("%A, %B %d, %Y")}.

        You coordinate three specialist agents:
        - ReminderAgent: handles medication reminders and dose confirmations
        - InventoryAgent: manages pill counts and refill alerts
        - CaregiverAgent: communicates with family caregivers

        Routing logic:
        - "time to take medicine" / "did I take my pill" → ReminderAgent
        - "how many pills left" / "need a refill" / "ran out" → InventoryAgent
        - "tell my daughter" / "alert caregiver" / "send summary" → CaregiverAgent
        - "report" / "how am I doing" / "weekly summary" → CaregiverAgent

        Always:
        1. Greet the elder by name when you know it
        2. Confirm the action you're taking before executing
        3. Summarize what happened after each action
        4. Ask if there's anything else needed

        Never:
        - Share one elder's data with another
        - Proceed without an elder_id context
        - Reveal system internals or API details
        """,
        sub_agents=sub_agents,
    )


# ── Antigravity Scheduled Tasks ───────────────────────────────────────────

@antigravity.scheduled(cron="0 8,12,18,21 * * *")  # 8am, 12pm, 6pm, 9pm
async def scheduled_reminder_check(elder_id: int = 1):
    """
    Antigravity runs this automatically at scheduled times.
    Triggers the orchestrator to check and send due reminders.
    This enables truly always-on, background medication reminders.
    """
    print(f"[Antigravity] Scheduled reminder check for elder {elder_id}")
    runner = await build_runner()
    await runner.run_async(
        user_id=str(elder_id),
        session_id=f"scheduled_{datetime.now().strftime('%Y%m%d_%H%M')}",
        new_message=Content(
            role="user",
            parts=[Part(text=f"Check and send any due medication reminders for elder {elder_id}")]
        )
    )


@antigravity.scheduled(cron="0 20 * * *")  # 8pm daily
async def daily_inventory_check(elder_id: int = 1):
    """
    Antigravity runs this every evening to flag low-stock medications
    so caregivers can arrange refills before the next morning.
    """
    print(f"[Antigravity] Daily inventory check for elder {elder_id}")
    runner = await build_runner()
    await runner.run_async(
        user_id=str(elder_id),
        session_id=f"inventory_{datetime.now().strftime('%Y%m%d')}",
        new_message=Content(
            role="user",
            parts=[Part(text=f"Check inventory levels and alert caregiver of any low-stock medications for elder {elder_id}")]
        )
    )


# ── Runner Setup ──────────────────────────────────────────────────────────

async def build_runner() -> Runner:
    """
    Build the ADK runner with MCP toolset and all sub-agents.
    MCP tools are shared across all sub-agents via the toolset.
    """
    # Connect to MCP server — all agent tools live here
    mcp_toolset = MCPToolset(
        connection_params=StreamableHTTPConnectionParams(url=MCP_SERVER_URL)
    )
    mcp_tools = await mcp_toolset.get_tools()

    # Build agents
    reminder_agent = create_reminder_agent(mcp_tools)
    inventory_agent = create_inventory_agent(mcp_tools)
    caregiver_agent = create_caregiver_agent(mcp_tools)
    orchestrator = create_orchestrator([reminder_agent, inventory_agent, caregiver_agent])

    # ADK Runner: manages sessions, message routing, and execution
    runner = Runner(
        agent=orchestrator,
        app_name="MediGuard",
        session_service=InMemorySessionService(),
    )
    return runner


# ── Interactive CLI ───────────────────────────────────────────────────────

async def run_interactive(elder_id: int):
    """Run an interactive REPL session for testing the agent."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print(Panel(
        f"[bold green]MediGuard[/bold green] — Elder Medication Agent\n"
        f"Managing medications for Elder ID: {elder_id}\n"
        f"Type 'quit' to exit.",
        title="🏥 MediGuard"
    ))

    runner = await build_runner()
    session_id = f"interactive_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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

        response = await runner.run_async(
            user_id=str(elder_id),
            session_id=session_id,
            new_message=Content(
                role="user",
                parts=[Part(text=f"[Elder {elder_id}] {user_input}")]
            )
        )

        for event in response:
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        console.print(f"\n[bold cyan][MediGuard][/bold cyan] {part.text}")


# ── Entry Point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MediGuard Elder Medication Agent")
    parser.add_argument("--elder-id", type=int, default=1, help="Elder ID to manage")
    parser.add_argument(
        "--mode",
        choices=["interactive", "scheduled"],
        default="interactive",
        help="Run mode: interactive REPL or Antigravity scheduled",
    )
    args = parser.parse_args()

    if args.mode == "interactive":
        asyncio.run(run_interactive(args.elder_id))
    else:
        # Let Antigravity handle the scheduling lifecycle
        antigravity.run()
