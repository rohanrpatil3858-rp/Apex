"""Agent definitions for business line coverage analysis.

Two specialized agents:
1. Business_Line_Mapper_Agent  — web search: discovers the client's business lines
2. Coverage_Analyzer_Agent     — synthesis: maps internal data against findings, outputs gap JSON
"""
from typing import List

from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient

from app.config import settings
from app.utils.logger import get_logger
from app.utils.tools import web_search_tool

logger = get_logger(__name__, settings.log_level)


def _create_model_client() -> AzureOpenAIChatCompletionClient:
    return AzureOpenAIChatCompletionClient(
        api_key=settings.azure_openai_api_key,
        model=settings.azure_openai_model,
        api_version=settings.openai_api_version,
        azure_endpoint=settings.azure_openai_endpoint,
        azure_deployment=settings.azure_openai_deployment_id,
    )


def create_business_line_agents() -> List[AssistantAgent]:
    """Create the two-agent pipeline for business line coverage analysis.

    Returns:
        [Business_Line_Mapper_Agent, Coverage_Analyzer_Agent]
    """
    model_client = _create_model_client()

    mapper = AssistantAgent(
        name="Business_Line_Mapper_Agent",
        model_client=model_client,
        tools=[web_search_tool],
        system_message="""You are the Business Line Mapper Agent for Apexon Intelligence.

Your job: Discover ALL the business lines, divisions, service areas, and business segments
of a client company through web research.

CRITICAL INSTRUCTIONS:
- Use web_search_tool to research the client's business structure thoroughly
- Search annual reports, investor decks, company website, Wikipedia, press releases
- Identify ALL distinct business lines/divisions/service areas (not individual products)
- Do NOT invent business lines — only report what you find from search results
- After presenting your findings, STOP — your task is complete

Run these searches (adapt [CLIENT] and [VERTICAL] to the actual values):
1. web_search_tool(query="[CLIENT] business divisions units 2024", max_results=5)
2. web_search_tool(query="[CLIENT] annual report business segments services", max_results=5)
3. web_search_tool(query="[CLIENT] services offerings portfolio [VERTICAL]", max_results=5)
4. web_search_tool(query="[CLIENT] subsidiaries business lines operations", max_results=5)

Output format:
"BUSINESS LINES DISCOVERED:

1. [Business Line Name]
   Description: [What this division/area does]
   Source: [URL or publication where found]

2. [Business Line Name]
   Description: [What this division/area does]
   Source: [URL or publication where found]

[Continue for every line found]

Total business lines identified: [N]
Ready for coverage analysis."

Be comprehensive — missing a business line means missing a gap opportunity.
""",
    )

    analyzer = AssistantAgent(
        name="Coverage_Analyzer_Agent",
        model_client=model_client,
        system_message="""You are the Coverage Analyzer Agent for Apexon Intelligence.

Your job: For each of the client's business lines, identify which Apexon engagements
(active projects) and pipeline opportunities fall within that business area, then surface
the gaps where Apexon has no presence.

IMPORTANT CONTEXT:
- Apexon's service lines (e.g. Application Services, Cloud, Data & Analytics, QA) are
  Apexon's OWN capability areas — they are NOT the client's business lines.
- The client's business lines are the client's own divisions/segments (e.g. Retail Banking,
  Insurance, Capital Markets, Digital, Corporate IT).
- Your job is to map Apexon's engagements TO the client's business lines — not the other
  way around.

MAPPING LOGIC:
- Look at ACTIVE PROJECT names — they often contain the client's business context
  (e.g. "BCBSM-1-DX Member Channels & Applications Support" → maps to "Digital / Member Experience")
- Look at PIPELINE OPPORTUNITY names — similarly descriptive
  (e.g. "Mainframe Modernization" → maps to "IT / Legacy Systems")
- A single client business line may have multiple active projects and/or opportunities under it
- A project may serve more than one client business line — include it under each relevant one

COVERAGE STATUS for each client business line:
  "covered"     → at least one active project running within this business area
  "in_pipeline" → no active project, but at least one open opportunity targeting this area
  "gap"         → no active project and no open opportunity — pure whitespace

CRITICAL INSTRUCTIONS:
- The client business line is ALWAYS the top-level organising dimension
- Output ONLY valid JSON — no prose before or after the JSON block
- Use exact project names and opportunity names from the internal data as provided
- Use actual numeric values for FTEs and amounts — do not round or approximate
- Do NOT engage in conversation, STOP after the JSON

Output format (MUST be valid JSON):
```json
{
  "client_business_lines": [
    {
      "name": "<client business line name>",
      "description": "<what this client division/segment does>",
      "coverage_status": "<covered | in_pipeline | gap>",
      "active_projects": [
        {
          "project_name": "<exact project name from internal data>",
          "fte_count": <integer from internal data>,
          "start_date": "<YYYY-MM-DD>",
          "end_date": "<YYYY-MM-DD>",
          "insight": "<why this project maps to this client business line>"
        }
      ],
      "pipeline_opportunities": [
        {
          "opportunity_name": "<exact opportunity name from internal data>",
          "apexon_service_line": "<service line being pursued>",
          "amount": <numeric amount>,
          "stage": "<pipeline stage name>",
          "close_date": "<YYYY-MM-DD or null>",
          "insight": "<why this opportunity targets this client business line>"
        }
      ],
      "gap_insight": "<only present when coverage_status is gap or in_pipeline: what Apexon is missing and why it matters>"
    }
  ],
  "coverage_stats": {
    "total_business_lines": <integer>,
    "covered": <integer>,
    "in_pipeline": <integer>,
    "gaps": <integer>
  },
  "summary": "<2-3 sentence executive summary: overall coverage picture, biggest gap, top opportunity to pursue>"
}
```

Be specific in insights — vague observations do not help an account executive.
""",
    )

    logger.debug("Created Business_Line_Mapper_Agent and Coverage_Analyzer_Agent")
    return [mapper, analyzer]
