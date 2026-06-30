"""Orchestrator for the business line coverage analysis workflow.

Two sequential phases:
  Phase 1 — Business_Line_Mapper_Agent: web-searches the client's business lines
  Phase 2 — Coverage_Analyzer_Agent:    compares findings against internal DB data
                                         and outputs structured gap-analysis JSON
"""
import json
import logging
from datetime import date
from typing import Any, Dict, List

from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console

from app.agents import revenue_json_reader
from app.agents.business_line_agent import create_business_line_agents
from app.config import settings
from app.utils.logger import get_logger
from app.utils.response_cache import ResponseCache

logger = get_logger(__name__, settings.log_level)

_response_cache = ResponseCache("BL-COVERAGE", lambda: settings.business_line_cache_days)


async def _run_agent(agent, task: str) -> str:
    """Run a single agent in its own RoundRobinGroupChat team and return its response."""
    try:
        termination = MaxMessageTermination(max_messages=2)
        team = RoundRobinGroupChat([agent], termination_condition=termination)
        result = await Console(team.run_stream(task=task))
        messages = result.messages if hasattr(result, "messages") else []
        for msg in reversed(messages):
            if hasattr(msg, "source") and msg.source == agent.name:
                return msg.content if hasattr(msg, "content") else ""
        return ""
    except Exception as e:
        logger.error(f"Error running agent {agent.name}: {str(e)}", exc_info=True)
        return f"ERROR: {str(e)}"


def _format_active_projects(rows: List[Dict[str, Any]]) -> str:
    """Format active project rows for the analyzer prompt.

    Handles delivery-DAO rows (rag_status, start_date/end_date, project_manager)
    and revenue-file rows (service_line, ytd_revenue, year). All fields are optional.
    """
    if not rows:
        return "  (No active projects found for this account)"
    lines = []
    for r in rows:
        parts = [f"  - Project: \"{r.get('project_name', 'Unknown')}\""]
        parts.append(f"FTEs: {r.get('fte_count', 0)}")
        if r.get("rag_status") and r["rag_status"] != "Grey":
            parts.append(f"RAG: {r['rag_status']}")
        if r.get("service_line"):
            sl = r["service_line"]
            if r.get("sub_service_line"):
                sl += f" / {r['sub_service_line']}"
            parts.append(f"Service Line: {sl}")
        if r.get("ytd_revenue") is not None:
            parts.append(f"YTD Revenue: ${r['ytd_revenue']:,.0f}")
        if r.get("start_date") or r.get("end_date"):
            parts.append(f"Period: {r.get('start_date', 'N/A')} → {r.get('end_date', 'N/A')}")
        elif r.get("year"):
            parts.append(f"Year: {r['year']}")
        if r.get("project_manager"):
            parts.append(f"PM: {r['project_manager']}")
        # network-sourced projects carry opportunity fields instead of delivery fields
        if r.get("stage_name"):
            parts.append(f"Stage: {r['stage_name']}")
        if r.get("amount"):
            parts.append(f"Value: ${float(r['amount']):,.0f}")
        if r.get("probability") is not None:
            parts.append(f"Prob: {r['probability']}%")
        if r.get("owner"):
            parts.append(f"Owner: {r['owner']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _format_opportunities(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "  (No open pipeline opportunities found for this account)"
    lines = []
    for r in rows:
        parts = [f"  - \"{r.get('opportunity_name', 'Unknown')}\""]
        parts.append(f"Service Line: {r.get('service_line', 'Unknown')}")
        parts.append(f"Amount: ${float(r.get('amount') or 0):,.0f}")
        if r.get("probability") is not None:
            parts.append(f"Prob: {r['probability']}%")
        parts.append(f"Stage: {r.get('stage_name', 'Unknown')}")
        parts.append(f"Close: {r.get('close_date', 'N/A')}")
        if r.get("revenue_type"):
            parts.append(f"Type: {r['revenue_type']}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _extract_json(text: str) -> Dict[str, Any] | None:
    """Pull the first JSON object out of an agent response."""
    json_str = None
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        json_str = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        json_str = text[start:end].strip()
    else:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            json_str = text[start:end]

    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error in coverage analysis output: {e}")
        return None


async def run_business_line_coverage_workflow(
    account_id: str,
    account_name: str,
    vertical: str,
    location: str,
    active_projects: List[Dict[str, Any]],
    pipeline_opportunities: List[Dict[str, Any]],
    refresh: bool = False,
) -> Dict[str, Any]:
    """Run the two-phase business line coverage workflow.

    Phase 1: Business_Line_Mapper_Agent discovers the client's business lines via web search.
    Phase 2: Coverage_Analyzer_Agent receives Phase 1 output + internal Apexon data,
             then classifies each client business line as covered / in-pipeline / gap.

    Args:
        account_id: Salesforce account SF ID.
        account_name: Client company name.
        vertical: Industry vertical (e.g. "BFSI").
        location: Client geographic location.
        active_projects: Rows from BusinessLineCoverageDAO.get_active_projects.
        pipeline_opportunities: Rows from BusinessLineCoverageDAO.get_pipeline_opportunities.

    Returns:
        Coverage analysis dict keyed by client business lines.
    """
    if refresh:
        _response_cache.invalidate(account_id)
    cached = _response_cache.get(account_id)
    if cached is not None:
        return cached

    today = date.today().strftime("%Y-%m-%d")

    # Revenue-file projects take priority; fall back to DB active_projects if file is absent
    file_projects = revenue_json_reader.get_projects_for_analysis(account_name)
    effective_projects: List[Dict[str, Any]] = file_projects if file_projects else active_projects
    if file_projects:
        logger.info(
            f"Using {len(file_projects)} revenue-file projects for BL analysis of '{account_name}'"
        )

    mapper_agent, analyzer_agent = create_business_line_agents()

    # ── Phase 1: discover client business lines ────────────────────────────
    mapper_task = (
        f"CLIENT: {account_name}\n"
        f"VERTICAL: {vertical}\n"
        f"LOCATION: {location}\n"
        f"TODAY: {today}\n\n"
        f"Discover all business lines, divisions, and service areas for {account_name}. "
        f"Run the four web searches described in your instructions and compile a complete list."
    )
    mapper_output = await _run_agent(mapper_agent, mapper_task)

    # ── Phase 2: gap analysis against internal data ────────────────────────
    analyzer_task = (
        f"CLIENT: {account_name}\n"
        f"VERTICAL: {vertical}\n"
        f"LOCATION: {location}\n"
        f"TODAY: {today}\n\n"
        f"{'=' * 70}\n"
        f"CLIENT'S BUSINESS LINES (discovered via web research):\n"
        f"{'=' * 70}\n"
        f"{mapper_output}\n\n"
        f"{'=' * 70}\n"
        f"APEXON INTERNAL DATA — map these TO the client's business lines above:\n"
        f"{'=' * 70}\n"
        f"NOTE: The projects below come from two sources:\n"
        f"  1. Delivery project register (active projects with RAG status, FTE count, dates)\n"
        f"  2. Relationship network (CRM-linked opportunity/project names visible in the network graph,\n"
        f"     shown with stage, value, and probability where available)\n"
        f"Use the project name to map each entry to the correct client business line.\n\n"
        f"ACTIVE PROJECTS (Apexon is actively delivering these for the client right now):\n"
        f"{_format_active_projects(effective_projects)}\n\n"
        f"OPEN PIPELINE OPPORTUNITIES (deals Apexon is pursuing with this client):\n"
        f"{_format_opportunities(pipeline_opportunities)}\n\n"
        f"For each client business line: list which active projects and pipeline opportunities\n"
        f"fall within it, then identify gaps where Apexon has nothing. Output the complete JSON."
    )
    analyzer_output = await _run_agent(analyzer_agent, analyzer_task)

    # ── Extract and enrich the JSON ────────────────────────────────────────
    parsed = _extract_json(analyzer_output)
    if parsed:
        parsed.update(
            account_id=account_id,
            account_name=account_name,
            vertical=vertical,
            generated_at=today,
        )
        _response_cache.set(account_id, parsed)
        return parsed

    logger.warning(f"No valid JSON in Coverage_Analyzer_Agent output for {account_name}")
    return {
        "account_id": account_id,
        "account_name": account_name,
        "vertical": vertical,
        "generated_at": today,
        "client_business_lines": [],
        "coverage_stats": {"total_business_lines": 0, "covered": 0, "in_pipeline": 0, "gaps": 0},
        "summary": "Coverage analysis could not be completed. Please retry.",
        "error": "JSON extraction failed from analyzer output",
    }
