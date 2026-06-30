"""Orchestrator for WSR (Weekly/Biweekly Status Report) analysis workflow.

For each .md file found in WSRs/{account_name}/, the WSR_Analyzer_Agent extracts:
  - RAG status (Green / Amber / Red) with reasoning
  - Upcoming milestones and release schedule
  - Open risks & issues
  - Open defects (In Progress / Open)
  - Delivery flags (spills, metric thresholds, trends)

Results are aggregated into an account-level rollup with overall RAG derived from
the worst individual team status.
"""
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console

from app.agents.wsr_agent import create_wsr_analyzer_agent
from app.config import settings
from app.utils.logger import get_logger
from app.utils.response_cache import ResponseCache

logger = get_logger(__name__, settings.log_level)

_response_cache = ResponseCache("WSR", lambda: settings.wsr_cache_days)

_RAG_PRIORITY = {"red": 3, "amber": 2, "green": 1}


async def _run_agent(agent, task: str) -> str:
    """Run a single agent in its own team and return the agent's last message."""
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
        logger.error(f"JSON parse error in WSR analyzer output: {e}")
        return None


def _find_wsr_files(account_name: str) -> List[Path]:
    """Locate all .md WSR files under {wsr_base_path}/{account_name}/WSRs/."""
    base_path = Path(settings.wsr_base_path)
    if not base_path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        base_path = project_root / base_path

    wsr_folder = base_path / account_name / "WSRs"
    if not wsr_folder.exists():
        logger.warning(f"WSR folder not found: {wsr_folder}")
        return []

    files = sorted(wsr_folder.glob("*.md"))
    logger.info(
        f"Found {len(files)} WSR file(s) for '{account_name}': {[f.name for f in files]}"
    )
    return files


def get_cached_wsr_insights(account_id: str) -> Dict[str, Any] | None:
    """Synchronous cache read — returns the last WSR result or None if not cached."""
    return _response_cache.get(account_id)


async def run_wsr_analysis_workflow(
    account_id: str,
    account_name: str,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Parse and analyze all WSR files for an account.

    Reads every .md file in WSRs/{account_name}/, sends each to WSR_Analyzer_Agent,
    then rolls up individual team results into an account-level summary.

    Args:
        account_id: Salesforce account SF ID.
        account_name: Client company name — used to locate the WSR subfolder.
        refresh: When True, bypasses the cache and re-processes all files.

    Returns:
        Dict with keys:
          account_id, account_name, generated_at, overall_rag,
          wsr_files_processed, teams (list of per-team analysis dicts)
    """
    if refresh:
        _response_cache.invalidate(account_id)
    cached = _response_cache.get(account_id)
    if cached is not None:
        return cached

    wsr_files = _find_wsr_files(account_name)
    if not wsr_files:
        return {
            "account_id": account_id,
            "account_name": account_name,
            "generated_at": date.today().strftime("%Y-%m-%d"),
            "teams": [],
            "overall_rag": None,
            "wsr_files_processed": [],
            "error": (
                f"No WSR files found for '{account_name}'. "
                f"Expected location: {settings.wsr_base_path}/{account_name}/WSRs/*.md"
            ),
        }

    today = date.today().strftime("%Y-%m-%d")
    team_results: List[Dict[str, Any]] = []

    for wsr_file in wsr_files:
        logger.info(f"Analyzing WSR: {wsr_file.name}")
        content = wsr_file.read_text(encoding="utf-8")
        agent = create_wsr_analyzer_agent()

        task = (
            f"FILE: {wsr_file.name}\n"
            f"TODAY: {today}\n\n"
            f"Analyze the following WSR document and extract structured delivery intelligence.\n\n"
            f"{'=' * 70}\n"
            f"{content}\n"
            f"{'=' * 70}\n\n"
            f"Extract RAG status, milestones, open risks, open defects, and delivery flags. "
            f"Output the complete JSON."
        )

        agent_output = await _run_agent(agent, task)
        parsed = _extract_json(agent_output)

        if parsed:
            parsed["source_file"] = wsr_file.name
            team_results.append(parsed)
            logger.info(
                f"WSR parsed: team={parsed.get('team_name', wsr_file.stem)} "
                f"rag={parsed.get('rag_status')} "
                f"open_defects={len(parsed.get('open_defects', []))}"
            )
        else:
            logger.warning(f"Could not extract JSON from WSR analysis for {wsr_file.name}")
            team_results.append({
                "source_file": wsr_file.name,
                "team_name": wsr_file.stem,
                "rag_status": None,
                "error": "Analysis output could not be parsed",
            })

    # Overall RAG = worst individual team RAG
    overall_rag = "green"
    for team in team_results:
        team_rag = (team.get("rag_status") or "green").lower()
        if _RAG_PRIORITY.get(team_rag, 0) > _RAG_PRIORITY.get(overall_rag, 0):
            overall_rag = team_rag

    result = {
        "account_id": account_id,
        "account_name": account_name,
        "generated_at": today,
        "overall_rag": overall_rag,
        "wsr_files_processed": [f.name for f in wsr_files],
        "teams": team_results,
    }

    _response_cache.set(account_id, result)
    return result
