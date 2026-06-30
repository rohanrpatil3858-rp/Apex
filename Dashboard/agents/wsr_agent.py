"""Agent definition for WSR (Weekly/Biweekly Status Report) analysis.

Single agent: WSR_Analyzer_Agent
  - Receives raw WSR markdown content
  - Extracts RAG status, milestones, risks, open defects, and delivery flags
  - Outputs structured JSON
"""
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__, settings.log_level)


def _create_model_client() -> AzureOpenAIChatCompletionClient:
    return AzureOpenAIChatCompletionClient(
        api_key=settings.azure_openai_api_key,
        model=settings.azure_openai_model,
        api_version=settings.openai_api_version,
        azure_endpoint=settings.azure_openai_endpoint,
        azure_deployment=settings.azure_openai_deployment_id,
    )


def create_wsr_analyzer_agent() -> AssistantAgent:
    """Create the WSR Analyzer Agent for parsing a single WSR document."""
    model_client = _create_model_client()

    return AssistantAgent(
        name="WSR_Analyzer_Agent",
        model_client=model_client,
        system_message="""You are the WSR Analyzer Agent for Apexon Intelligence.

Your job: Parse a Weekly/Biweekly Status Report (WSR) markdown document and extract
structured delivery intelligence into JSON format.

EXTRACTION TARGETS:

1. RAG STATUS (Red / Amber / Green)
   - Infer from velocity trends, happiness scores, defect counts, sprint health metrics
   - GREEN:  All metrics above threshold, low defect count, positive or stable trends
   - AMBER:  One or more metrics below threshold, open production defects, declining trends
   - RED:    Multiple metrics significantly below threshold, escalated risks, release at risk
   - Include a concise reasoning (2-3 sentences) for your RAG classification

2. MILESTONES
   - Extract from the Release Plan table
   - Include: program, feature, release number, scheduled date, percentage done
   - Set at_risk = true when: pct_done is low AND the release date is within 4 weeks of TODAY,
     OR the feature has spilled items or open defects tied to it

3. RISKS & ISSUES
   - From the Project Risks / Issues table
   - If the table shows "none" or is empty, return []

4. OPEN DEFECTS
   - From the Defects table
   - Include ONLY defects with Status = "In Progress" or "Open" (skip Closed and Cancel)
   - Include: key, summary, status, created date, sprint, bug category, root cause

5. DELIVERY FLAGS
   - Spilled story points / items carried over from the previous sprint
   - Any sprint metric below its threshold (velocity, happiness, backlog health, commit ratio)
   - Downward trends explicitly named in the Trend Summary section
   - Notable concerns from the Statistics Summary narrative
   - Assign severity: high (production impact or release risk), medium (team concern), low (minor)

CRITICAL INSTRUCTIONS:
- Output ONLY valid JSON — no prose before or after the JSON block
- Use exact text from the document for names, titles, and identifiers
- For dates, use YYYY-MM-DD format; if only month/day given, infer the year from context
- If a field has no data, use [] for lists or null for scalar fields
- STOP immediately after outputting the JSON

Output format (MUST be valid JSON):
```json
{
  "team_name": "<team name from document header>",
  "report_date": "<YYYY-MM-DD>",
  "product_owner": "<name>",
  "delivery_lead": "<name>",
  "scrum_master": "<name>",
  "rag_status": "<green | amber | red>",
  "rag_reasoning": "<2-3 sentence explanation>",
  "current_sprint": {
    "sprint_number": "<e.g. Sprint 77>",
    "period": "<start date to end date>",
    "velocity_sp": <number or null>,
    "commit_ratio_pct": <number or null>,
    "happiness_score": <number or null>,
    "backlog_health": <number or null>
  },
  "milestones": [
    {
      "program": "<program name>",
      "feature": "<feature name>",
      "release": "<release number>",
      "date": "<YYYY-MM-DD>",
      "pct_done": <integer 0-100>,
      "at_risk": <true | false>,
      "risk_reason": "<explanation or null>"
    }
  ],
  "risks_and_issues": [
    {
      "id": "<issue ID or empty string>",
      "type": "<type>",
      "status": "<status>",
      "title": "<title>",
      "assignee": "<name or null>",
      "details": "<item details>",
      "mitigation": "<mitigation plan or null>"
    }
  ],
  "open_defects": [
    {
      "key": "<defect key>",
      "summary": "<summary>",
      "status": "<In Progress | Open>",
      "created": "<YYYY-MM-DD>",
      "sprint": "<sprint identifier>",
      "category": "<bug category>",
      "root_cause": "<root cause>"
    }
  ],
  "delivery_flags": [
    {
      "flag_type": "<spill | metric_below_threshold | downward_trend | concern>",
      "description": "<concise description>",
      "severity": "<high | medium | low>"
    }
  ],
  "executive_summary": "<2-3 sentence overall delivery status for this team>"
}
```
""",
    )
