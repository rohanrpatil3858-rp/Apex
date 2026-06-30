"""Orchestrator for multi-agent intelligence workflow with parallel execution.

This module coordinates the execution of multiple specialized agents using a
phased parallel approach for optimal performance.

PARALLEL EXECUTION: Search agents (2-7) run concurrently using asyncio.gather()
for 3-5x performance improvement while maintaining data quality.
"""
import asyncio
import json
import warnings
from datetime import datetime, date
from typing import Dict, Any, List

# Suppress AutoGen model mismatch warnings to keep terminal clean
warnings.filterwarnings('ignore', message='.*Resolved model mismatch.*')
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination
from app.config import settings
from app.agents.agent_definitions import create_single_account_agents, create_multi_account_agents, create_market_performance_agents
from app.utils.logger import get_logger

logger = get_logger(__name__, settings.log_level)


async def run_phase(agents: List, task: str, max_messages: int = 2) -> List[str]:
    """Run multiple agents in parallel, each in its own RoundRobinGroupChat team.
    
    This helper function creates a separate team for each agent and runs them
    concurrently using asyncio.gather(). Each agent gets proper team context
    even though it's the only agent in its team.
    
    Args:
        agents: List of agents to run in parallel
        task: Task message to send to each agent
        max_messages: Maximum messages for termination (default 2 for non-tool agents)
        
    Returns:
        List of response strings from each agent
    """
    async def run_single(agent):
        """Run a single agent in its own team."""
        try:
            # Create single-agent team with configurable max messages
            termination = MaxMessageTermination(max_messages=max_messages)
            team = RoundRobinGroupChat([agent], termination_condition=termination)
            
            # Run the team silently (no Console wrapper to avoid terminal flooding)
            result = await team.run(task=task)
            
            # Extract agent's response from messages
            messages = result.messages if hasattr(result, 'messages') else []
            for msg in reversed(messages):
                if hasattr(msg, 'source') and msg.source == agent.name:
                    return msg.content if hasattr(msg, 'content') else ""
            
            return ""
            
        except Exception as e:
            # Suppress error logging to keep terminal clean
            return f"ERROR from {agent.name}: {str(e)}"
    
    # Run all agents in parallel
    return await asyncio.gather(*[run_single(a) for a in agents])


async def run_intelligence_workflow(
    client_name: str = "",
    vertical: str = "",
    location: str = "",
    deal_size: str = "",
    area_of_work: str = "",
    description: str = "",
    accounts: list[Dict[str, Any]] | None = None
) -> Dict[str, Any]:
    """Main orchestrator for the intelligence workflow with parallel execution.
    
    Supports TWO modes:
    1. Single-account mode: Analyzes one client
    2. Multi-account mode: Analyzes multiple clients in ONE workflow run
    
    PARALLEL EXECUTION: Search agents (2-7) run concurrently using asyncio.gather()
    for 3-5x performance improvement while maintaining data quality.
    
    Workflow phases:
    1. Industry_Mapper: Sequential (creates search strategy)
    2. Search Agents (6): PARALLEL (execute searches concurrently)
    3. Impact_Analyzer: Sequential (filters and analyzes)
    4. Categorizer: Sequential (groups and categorizes)
    5. Portfolio_Summary (multi-account only): Sequential
    
    Args:
        client_name: Name of the client company (single-account mode).
        vertical: Industry vertical (single-account mode).
        location: Client's geographic location (single-account mode).
        deal_size: Current deal size (single-account mode).
        area_of_work: Area of work/SOW (single-account mode).
        description: Brief business description (single-account mode).
        accounts: List of account dictionaries for multi-account mode.
        
    Returns:
        Dictionary containing intelligence results structured per mode.
    """
    start_time = datetime.now()
    is_multi_account = accounts is not None and len(accounts) > 0
    
    if is_multi_account:
        logger.info(f"[WORKFLOW] Intelligence analysis started for {len(accounts)} accounts")
    else:
        logger.info(f"[WORKFLOW] Intelligence analysis started for {client_name} ({vertical})")
    
    # Create agents
    if is_multi_account:
        agents = create_multi_account_agents()
    else:
        agents = create_single_account_agents()
    
    # Build initial context
    today = date.today().strftime("%Y-%m-%d")
    
    if is_multi_account:
        initial_message = build_multi_account_prompt(accounts, today)
    else:
        initial_message = build_single_account_prompt(
            client_name, vertical, location, deal_size, area_of_work, description, today
        )
    
    try:
        # PHASE 1: Industry Mapper (Sequential)
        phase1_start = datetime.now()
        
        mapper_results = await run_phase([agents[0]], initial_message)
        search_strategy = mapper_results[0]
        
        phase1_duration = (datetime.now() - phase1_start).total_seconds()
        # logger.info(f"[WORKFLOW] Phase 1/5: Mapper completed")
        
        # PHASE 2: Search Agents (PARALLEL)
        phase2_start = datetime.now()
        
        # Build task for search agents
        parallel_task = f"{initial_message}\n\n{'='*80}\nSEARCH STRATEGY FROM INDUSTRY MAPPER:\n{'='*80}\n{search_strategy}\n\nExecute your assigned search queries now using the above strategy."
        
        # Run all 6 search agents in parallel
        search_agents = agents[1:7]
        news_results = await run_phase(search_agents, parallel_task)
        
        phase2_duration = (datetime.now() - phase2_start).total_seconds()
        # logger.info(f"[WORKFLOW] Phase 2/5: Search completed (6 agents in {phase2_duration:.1f}s)")
        
        # Combine all news results
        all_news = "\n\n".join([f"=== {search_agents[i].name} ===\n{result}" 
                                 for i, result in enumerate(news_results)])
        
        # PHASE 3: Impact Analyzer (Sequential)
        phase3_start = datetime.now()
        
        analysis_task = f"Client: {client_name}\nVertical: {vertical}\n\n=== NEWS FROM ALL SEARCH AGENTS ===\n{all_news}\n\nAnalyze impact on client and Apexon's engagement. Filter irrelevant items."
        analyzer_results = await run_phase([agents[7]], analysis_task)
        
        phase3_duration = (datetime.now() - phase3_start).total_seconds()
        # logger.info(f"[WORKFLOW] Phase 3/5: Analyzer completed")
        
        analyzer_content = analyzer_results[0]
        
        # PHASE 4: Categorizer (Sequential)
        phase4_start = datetime.now()
        
        categorization_task = f"Client: {client_name}\n\n=== ANALYZED INTELLIGENCE ===\n{analyzer_content}\n\nCategorize into JSON: {{'intelligence': [...]}}"
        categorizer_results = await run_phase([agents[8]], categorization_task)
        
        phase4_duration = (datetime.now() - phase4_start).total_seconds()
        # logger.info(f"[WORKFLOW] Phase 4/5: Categorizer completed")
        
        categorizer_content = categorizer_results[0]
        
        # PHASE 5: Portfolio Summary (Multi-account only)
        portfolio_summary = None
        phase5_duration = 0
        if is_multi_account and len(agents) > 9:
            phase5_start = datetime.now()
            
            summary_task = f"Portfolio: {len(accounts)} accounts\n\n=== CATEGORIZED INTELLIGENCE ===\n{categorizer_content}\n\nCreate executive portfolio summary: health, themes, opportunities, risks, recommendations."
            summary_results = await run_phase([agents[9]], summary_task)
            portfolio_summary = summary_results[0]
            
            phase5_duration = (datetime.now() - phase5_start).total_seconds()
            # logger.info(f"[WORKFLOW] Phase 5/5: Portfolio summary completed")
        
        # Extract final JSON from categorizer output
        categorizer_output = categorizer_results[0]
        # logger.debug(f"[PARALLEL] Categorizer output (first 500 chars): {categorizer_output[:500]}")
        
        # Try to extract JSON from the output
        final_response = None
        
        # Look for JSON in markdown code blocks
        if "```json" in categorizer_output:
            json_start = categorizer_output.find("```json") + 7
            json_end = categorizer_output.find("```", json_start)
            json_str = categorizer_output[json_start:json_end].strip()
        elif "```" in categorizer_output:
            json_start = categorizer_output.find("```") + 3
            json_end = categorizer_output.find("```", json_start)
            json_str = categorizer_output[json_start:json_end].strip()
        else:
            # Try to find JSON object directly
            json_start = categorizer_output.find("{")
            json_end = categorizer_output.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = categorizer_output[json_start:json_end]
            else:
                json_str = None
        
        if json_str:
            try:
                parsed = json.loads(json_str)
                
                if is_multi_account:
                    # Multi-account response
                    if portfolio_summary:
                        final_response = {
                            "generated_at": today,
                            "total_accounts_analyzed": len(accounts),
                            "portfolio_summary": portfolio_summary
                        }
                    else:
                        final_response = parsed
                        final_response["generated_at"] = today
                else:
                    # Single-account response
                    final_response = {
                        "account": client_name,
                        "vertical": vertical,
                        "generated_at": today,
                        "intelligence": parsed.get("intelligence", [])
                    }
                
            except json.JSONDecodeError as e:
                # Suppress JSON parse error logging
                final_response = {
                    "account": client_name,
                    "vertical": vertical,
                    "generated_at": today,
                    "intelligence": [],
                    "error": "Failed to parse categorizer output"
                }
        else:
            # logger.warning("[WORKFLOW] No JSON found in categorizer output")
            final_response = {
                "account": client_name,
                "vertical": vertical,
                "generated_at": today,
                "intelligence": [],
                "error": "No JSON found in output"
            }
        
        total_duration = (datetime.now() - start_time).total_seconds()
        intelligence_count = len(final_response.get('intelligence', []))
        # logger.info(f"[WORKFLOW] Completed in {total_duration:.1f}s | Intelligence: {intelligence_count} items")
        
        return final_response
        
    except Exception as e:
        # Re-raise without logging to keep terminal clean
        raise




def build_single_account_prompt(
    client_name: str,
    vertical: str,
    location: str,
    deal_size: str,
    area_of_work: str,
    description: str,
    today: str
) -> str:
    """Build prompt for single-account mode (backward compatible)."""
    
    client_profile = f"""
CLIENT PROFILE:
- Client Name: {client_name}
- Vertical: {vertical}
- Location: {location}
- Deal Size: {deal_size}
- Area of Work: {area_of_work}
- Description: {description}
"""
    
    return f"""
=== APEXON INTELLIGENCE WORKFLOW ===

CLIENT: {client_name}
VERTICAL: {vertical}
TODAY'S DATE: {today}

{client_profile}

OBJECTIVE: Gather and analyze the latest world news to identify events that may impact this client's business and Apexon's engagement with them.

WORKFLOW EXECUTION PLAN:

STEP 1 - Industry_Mapper_Agent:
→ Read the client profile above
→ Based on industry and business, create targeted search queries for:
  - Direct news about the client
  - Industry trends and developments (LOCAL and GLOBAL)
  - Regulatory/political events (LOCAL and GLOBAL)
  - Climate and weather events (LOCAL and GLOBAL)
  - Geopolitical events (ANY region of the world)
  - Competitor activities (LOCAL and GLOBAL)
→ Output: Organized search strategy with specific queries

STEP 2 - General_News_Agent:
→ Execute "General News Queries" from Step 1 using web_search_tool
→ Search for direct news about {client_name}
→ Output: All search results

STEP 3 - Industry_Trends_Agent:
→ Execute "Industry Trend Queries" from Step 1 using web_search_tool
→ Search for {vertical} industry trends both LOCAL and GLOBAL
→ Output: All search results

STEP 4 - Regulatory_Political_Agent:
→ Execute "Regulatory & Political Queries" from Step 1 using web_search_tool
→ Search for regulatory, legal, and political news both LOCAL and GLOBAL affecting {vertical}
→ Output: All search results

STEP 5 - Climate_Weather_Agent:
→ Execute "Climate & Weather Queries" from Step 1 using web_search_tool
→ Search for climate, weather, and environmental events both LOCAL and GLOBAL affecting {vertical}
→ Output: All search results

STEP 6 - Geopolitical_Agent:
→ Execute "Geopolitical Queries" from Step 1 using web_search_tool
→ Search for geopolitical events and international relations from ANY region of the world affecting {vertical}
→ Output: All search results

STEP 7 - Competitor_Intel_Agent:
→ Execute "Competitor Queries" from Step 1 using web_search_tool
→ Search for competitor news and activities both LOCAL and GLOBAL
→ Output: All search results (this is the last news gathering step)

STEP 8 - Impact_Analyzer_Agent:
→ Read ALL news from Steps 2-7
→ Filter out irrelevant items
→ For each relevant item, analyze:
  - How does this impact {client_name}'s business?
  - What does this mean for Apexon's engagement?
→ Output: Analyzed and filtered news items with impact assessment

STEP 9 - Categorizer_Agent:
→ Read analyzed items from Step 8
→ Create dynamic categories based on content (e.g., Trigger, Risk, Opportunity, Regulatory, Competitor)
→ Group items into categories
→ Output: Final JSON with categorized intelligence
→ End message with: WORKFLOW_COMPLETE

IMPORTANT RULES:
- Each agent executes ONLY their step, then stops
- Do NOT engage in conversations between agents
- Do NOT respond to thank you messages
- Do not make up news - only use the search tool results
- Follow the sequence strictly: 1→2→3→4→5→6→7→8→9
- The workflow is complete when Categorizer_Agent outputs WORKFLOW_COMPLETE

BEGIN EXECUTION NOW.
Industry_Mapper_Agent: Start by analyzing the client profile above and creating the search strategy.
"""


def build_multi_account_prompt(accounts: list[Dict[str, Any]], today: str) -> str:
    """Build prompt for multi-account mode (cost-optimized)."""
    
    # Build portfolio context with all accounts
    accounts_list = "\n".join([
        f"""
ACCOUNT {i+1}:
- ID: {acc.get('id', 'N/A')}
- Name: {acc.get('name', 'N/A')}
- Vertical: {acc.get('vertical', 'N/A')}
- Location: {acc.get('location', 'N/A')}
- ACV: ${acc.get('total_acv', 0):,.0f}
- Industry Details: {acc.get('vertical_industry', acc.get('vertical', 'N/A'))}
"""
        for i, acc in enumerate(accounts)
    ])
    
    return f"""
=== APEXON PORTFOLIO INTELLIGENCE WORKFLOW ===

TODAY'S DATE: {today}
MODE: MULTI-ACCOUNT ANALYSIS

PORTFOLIO CONTEXT:
You are analyzing intelligence for {len(accounts)} client accounts simultaneously. This is more cost-efficient than running separate workflows.

{accounts_list}

OBJECTIVE: Gather and analyze the latest world news to identify events that may impact ANY of these clients' businesses and Apexon's engagements with them.

WORKFLOW EXECUTION PLAN:

STEP 1 - Industry_Mapper_Agent:
→ Read ALL account profiles above
→ Identify common industry verticals and unique verticals
→ Create consolidated search queries covering ALL accounts:
  - Direct news about each specific client (by name)
  - Industry trends for each vertical represented (LOCAL and GLOBAL)
  - Regulatory/political events for each vertical (LOCAL and GLOBAL)
  - Climate/weather events for each location (LOCAL and GLOBAL)
  - Geopolitical events globally
  - Competitor activities in each industry (LOCAL and GLOBAL)
→ Output: Consolidated search strategy covering all {len(accounts)} accounts

STEP 2 - General_News_Agent:
→ Execute "General News Queries" from Step 1 using web_search_tool
→ Search for direct news about EACH client by name
→ Output: All search results

STEP 3 - Industry_Trends_Agent:
→ Execute "Industry Trend Queries" from Step 1 using web_search_tool
→ Search for ALL industry verticals represented in the portfolio (LOCAL and GLOBAL)
→ Output: All search results

STEP 4 - Regulatory_Political_Agent:
→ Execute "Regulatory & Political Queries" from Step 1 using web_search_tool
→ Search for regulatory/legal/political news for ALL verticals (LOCAL and GLOBAL)
→ Output: All search results

STEP 5 - Climate_Weather_Agent:
→ Execute "Climate & Weather Queries" from Step 1 using web_search_tool
→ Search for climate/weather events for ALL locations (LOCAL and GLOBAL)
→ Output: All search results

STEP 6 - Geopolitical_Agent:
→ Execute "Geopolitical Queries" from Step 1 using web_search_tool
→ Search for geopolitical events globally
→ Output: All search results

STEP 7 - Competitor_Intel_Agent:
→ Execute "Competitor Queries" from Step 1 using web_search_tool
→ Search for competitor news in ALL industries
→ Output: All search results (this is the last news gathering step)

STEP 8 - Impact_Analyzer_Agent:
→ Read ALL news from Steps 2-7
→ For EACH news item, analyze which account(s) it impacts
→ Filter out items that don't impact any account
→ For each relevant item, analyze:
  - Which specific account(s) does this impact?
  - How does this impact each account's business?
  - What does this mean for Apexon's engagement with each account?
→ Output: Analyzed news items with PER-ACCOUNT impact assessment

STEP 9 - Categorizer_Agent:
→ Read analyzed items from Step 8
→ Group intelligence BY ACCOUNT
→ For each account, create categories (Trigger, Risk, Opportunity, Regulatory, Competitor)
→ Output: Final JSON with PER-ACCOUNT intelligence structure:
```json
{{
  "accounts": [
    {{
      "account_id": "...",
      "account_name": "...",
      "vertical": "...",
      "intelligence": [
        {{"category": "...", "headline": "...", "summary": "...", "impact": "...", "published_date": "...", "source": "..."}},
        ...
      ]
    }},
    ...
  ]
}}
```
→ End message with: WORKFLOW_COMPLETE

STEP 10 - Portfolio_Summary_Agent:
→ Read the categorized intelligence from Step 9
→ Analyze the overall portfolio impact across all accounts
→ Create an executive summary covering:
  - Overall portfolio health
  - Key themes across multiple accounts
  - Top opportunities and risks
  - Accounts requiring immediate attention
  - Strategic recommendations
→ Output: Portfolio intelligence summary for leadership review

IMPORTANT RULES:
- Each agent executes ONLY their step, then stops
- Do NOT engage in conversations between agents
- Do NOT respond to thank you messages
- Do not make up news - only use the search tool results
- When analyzing impact, clearly identify which account(s) each news item affects
- The Categorizer MUST output per-account intelligence structure
- Follow the sequence strictly: 1→2→3→4→5→6→7→8→9→10
- The workflow is complete when Portfolio_Summary_Agent outputs the summary

BEGIN EXECUTION NOW.
Industry_Mapper_Agent: Start by analyzing all {len(accounts)} account profiles above and creating the consolidated search strategy.
"""


def extract_multi_account_json(result: Any, accounts: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract multi-account JSON from Categorizer Agent's output and portfolio summary."""
    try:
        messages = result.messages if hasattr(result, 'messages') else []
        # logger.debug(f"Extracting multi-account JSON from {len(messages)} messages")
        
        parsed_accounts = None
        portfolio_summary = None
        
        # Look for JSON in the last messages from Categorizer Agent
        for message in reversed(messages):
            if hasattr(message, 'source') and message.source == "Categorizer_Agent":
                content = message.content if hasattr(message, 'content') else str(message)
                
                # Extract JSON from markdown code blocks if present
                json_str = ""
                if "```json" in content:
                    json_start = content.find("```json") + 7
                    json_end = content.find("```", json_start)
                    json_str = content[json_start:json_end].strip()
                elif "```" in content:
                    json_start = content.find("```") + 3
                    json_end = content.find("```", json_start)
                    json_str = content[json_start:json_end].strip()
                else:
                    json_start = content.find("{")
                    json_end = content.rfind("}") + 1
                    if json_start != -1 and json_end > json_start:
                        json_str = content[json_start:json_end]
                
                if not json_str:
                    continue
                
                try:
                    parsed = json.loads(json_str)
                    
                    # Validate structure
                    if "accounts" in parsed and isinstance(parsed["accounts"], list):
                        parsed_accounts = parsed["accounts"]
                        # logger.info(f"Successfully parsed multi-account JSON with {len(parsed_accounts)} accounts")
                        break
                        
                except json.JSONDecodeError as e:
                    # logger.warning(f"JSON decode error: {str(e)}")
                    continue
        
        # Look for portfolio summary from Portfolio_Summary_Agent
        for message in reversed(messages):
            if hasattr(message, 'source') and message.source == "Portfolio_Summary_Agent":
                content = message.content if hasattr(message, 'content') else str(message)
                
                # Extract the summary text (everything between "PORTFOLIO INTELLIGENCE SUMMARY:" and end)
                if "PORTFOLIO INTELLIGENCE SUMMARY:" in content:
                    summary_start = content.find("PORTFOLIO INTELLIGENCE SUMMARY:")
                    portfolio_summary = content[summary_start:].strip()
                    # logger.info("Successfully extracted portfolio summary")
                    break
        
        # Build final response - ONLY return portfolio summary, not detailed accounts
        if portfolio_summary:
            # Count accounts from parsed data
            total_accounts_analyzed = len(parsed_accounts) if parsed_accounts else len(accounts)
            
            final_response = {
                "generated_at": datetime.now().strftime("%Y-%m-%d"),
                "total_accounts_analyzed": total_accounts_analyzed,
                "portfolio_summary": portfolio_summary
            }
            # logger.info(f"Returning portfolio summary for {total_accounts_analyzed} accounts")
            
            return final_response
        
        # Fallback if no summary found - still return summary-only structure
        # logger.warning("No portfolio summary found, returning minimal structure")
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d"),
            "total_accounts_analyzed": len(accounts),
            "portfolio_summary": "Portfolio analysis completed but summary generation failed. Please retry."
        }
        
    except Exception as e:
        logger.error(f"Error extracting multi-account JSON: {str(e)}", exc_info=True)
        return {
            "generated_at": datetime.now().strftime("%Y-%m-%d"),
            "total_accounts": len(accounts),
            "accounts": [],
            "error": str(e)
        }


def extract_final_json(result: Any, client_name: str, vertical: str) -> Dict[str, Any]:
    """Extract final JSON from the Categorizer Agent's output.
    
    Parses the agent chat result to find and extract the final JSON response
    from the Categorizer Agent, which contains all categorized intelligence items.
    
    Args:
        result: Chat result from team execution.
        client_name: Client name to include in response.
        vertical: Industry vertical to include in response.
        
    Returns:
        Dictionary containing final formatted intelligence response with:
            - account: Client name
            - vertical: Industry vertical
            - generated_at: Date in YYYY-MM-DD format
            - intelligence: List of intelligence items (may be empty on failure)
            
    Note:
        Returns empty intelligence list if JSON parsing fails or no valid
        output is found from Categorizer Agent.
    """
    try:
        # Get messages from result
        messages = result.messages if hasattr(result, 'messages') else []
        # logger.debug(f"Extracting multi-account JSON from {len(messages)} messages")
        
        # Look for JSON in the last messages from Categorizer Agent
        for message in reversed(messages):
            source = getattr(message, 'source', 'N/A')
            # logger.debug(f"Checking message from: {source}")
            
            if hasattr(message, 'source') and message.source == "Categorizer_Agent":
                content = message.content if hasattr(message, 'content') else str(message)
                # logger.debug(f"Found Categorizer message, length: {len(content)}")
                
                # Extract JSON from markdown code blocks if present
                json_str = ""
                if "```json" in content:
                    json_start = content.find("```json") + 7
                    json_end = content.find("```", json_start)
                    json_str = content[json_start:json_end].strip()
                elif "```" in content:
                    json_start = content.find("```") + 3
                    json_end = content.find("```", json_start)
                    json_str = content[json_start:json_end].strip()
                else:
                    # Try to find JSON object directly
                    json_start = content.find("{")
                    json_end = content.rfind("}") + 1
                    if json_start != -1 and json_end > json_start:
                        json_str = content[json_start:json_end]
                
                if not json_str:
                    # logger.warning("No JSON string found in Categorizer output")
                    continue
                
                # logger.debug(f"Extracted JSON string, length: {len(json_str)}")
                
                try:
                    parsed = json.loads(json_str)
                    
                    # Add account, vertical, and generated_at fields
                    final_response = {
                        "account": client_name,
                        "vertical": vertical,
                        "generated_at": datetime.now().strftime("%Y-%m-%d"),
                        "intelligence": parsed.get("intelligence", [])
                    }
                    
                    # logger.info(f"Successfully parsed JSON with {len(final_response['intelligence'])} intelligence items")
                    # logger.info("="*80)
                    # logger.info("✓ SEQUENTIAL WORKFLOW COMPLETED (Non-Parallel)")
                    # logger.info(f"✓ Workflow Type: SEQUENTIAL")
                    # logger.info(f"✓ Total intelligence items: {len(final_response['intelligence'])}")
                    # logger.info("="*80)
                    return final_response
                    
                except json.JSONDecodeError as e:
                    # logger.warning(f"JSON decode error: {str(e)}")
                    continue
        
        # Fallback if no valid JSON found
        # logger.warning("No valid JSON found in agent responses, returning empty intelligence")
        # logger.info("="*80)
        # logger.info("✓ SEQUENTIAL WORKFLOW COMPLETED (Non-Parallel) - FALLBACK")
        # logger.info(f"✓ Workflow Type: SEQUENTIAL")
        # logger.info(f"✓ Total intelligence items: 0 (fallback)")
        # logger.info("="*80)
        return {
            "account": client_name,
            "vertical": vertical,
            "generated_at": datetime.now().strftime("%Y-%m-%d"),
            "intelligence": []
        }
        
    except Exception as e:
        logger.error(f"Error extracting final JSON: {str(e)}", exc_info=True)
        return {
            "account": client_name,
            "vertical": vertical,
            "generated_at": datetime.now().strftime("%Y-%m-%d"),
            "intelligence": [],
            "error": str(e)
        }


async def run_market_performance_workflow(
    company_name: str,
    ticker: str | None = None
) -> Dict[str, Any]:
    """Orchestrate market performance analysis workflow with parallel execution.
    
    Analyzes market data, executive insights, and sentiment for a company.
    Conditionally includes stock data based on ticker availability.
    
    PARALLEL EXECUTION: Market Data, Executive, and Sentiment agents run
    concurrently when ticker is provided. Executive and Sentiment run in
    parallel when ticker is absent.
    
    Args:
        company_name: Full company name (e.g., "Goldman Sachs", "Apple")
        ticker: Optional stock ticker symbol (e.g., "GS", "AAPL")
        
    Returns:
        Dict with keys: stock_data, executive_insights, sentiment, synthesis
        
    Raises:
        ValueError: If company_name is empty or invalid
        Exception: For workflow execution errors
    """
    try:
        if not company_name or not company_name.strip():
            raise ValueError("Company name is required for market performance analysis")
        
        logger.info(f"[WORKFLOW] Market performance analysis started for {company_name}" + 
                   (f" (ticker: {ticker})" if ticker else " (no ticker)"))
        
        # Create all 5 market performance agents (including ticker resolver)
        agents = create_market_performance_agents()
        ticker_resolver_agent = agents[0]
        market_data_agent = agents[1]
        executive_agent = agents[2]
        sentiment_agent = agents[3]
        synthesizer_agent = agents[4]
        
        # Phase 0: Ticker Resolution (if ticker not provided)
        resolved_ticker = ticker
        if not ticker or not ticker.strip():
            try:
                # Smart preprocessing: Try to extract parent company name if subsidiary
                search_company_name = company_name
                country_suffixes = [" India", " UK", " United Kingdom", " Japan", " China", " Singapore", 
                                   " Hong Kong", " Australia", " Canada", " Germany", " France"]
                
                for suffix in country_suffixes:
                    if company_name.endswith(suffix):
                        search_company_name = company_name[:-len(suffix)].strip()
                        break
                
                resolver_task = f"Find the stock ticker symbol for {search_company_name}. Search for '{search_company_name} stock ticker symbol' and determine if it's publicly traded."
                # Ticker resolver needs more messages: task->tool_call->tool_result->final_response = 4 messages
                resolver_results = await run_phase([ticker_resolver_agent], resolver_task, max_messages=6)
                resolver_output = resolver_results[0] if resolver_results else ""
                
                # Parse resolver output to extract ticker
                if "Status: PUBLIC" in resolver_output and "Ticker:" in resolver_output:
                    # Extract ticker from output
                    lines = resolver_output.split('\n')
                    for line in lines:
                        if line.strip().startswith("Ticker:"):
                            resolved_ticker = line.split(":", 1)[1].strip()
                            if resolved_ticker and resolved_ticker != "NONE":
                                break
                    else:
                        resolved_ticker = None
                elif "Status: PRIVATE" in resolver_output:
                    resolved_ticker = None
                    
            except Exception as e:
                # If ticker resolution fails, proceed without ticker
                resolved_ticker = None
        
        # Phase 1-3: Run data collection agents in parallel
        # Conditionally include market data agent only if ticker is available
        parallel_agents = []
        parallel_tasks = []
        
        # Always include executive and sentiment agents
        parallel_agents.extend([executive_agent, sentiment_agent])
        parallel_tasks.extend([
            f"Analyze executive insights for {company_name}. Call executive_insights_tool with company_name='{company_name}' and limit=5.",
            f"Analyze news sentiment for {company_name}. Call sentiment_analysis_tool with company_name='{company_name}'."
        ])
        
        # Conditionally include market data agent if ticker is available (provided or resolved)
        if resolved_ticker and resolved_ticker.strip():
            parallel_agents.insert(0, market_data_agent)
            parallel_tasks.insert(0, 
                f"Gather market data for ticker {resolved_ticker}. Call stock_quote_tool with ticker='{resolved_ticker}' AND company_news_tool with ticker='{resolved_ticker}' and limit=5."
            )
        
        # Run all data collection agents in parallel
        try:
            parallel_results = await asyncio.gather(*[
                run_phase([agent], task) 
                for agent, task in zip(parallel_agents, parallel_tasks)
            ])
            
            # Build combined context from parallel results
            combined_context = "MARKET PERFORMANCE DATA COLLECTION:\n\n"
            
            if resolved_ticker:
                combined_context += f"Market Data Results:\n{parallel_results[0][0]}\n\n"
                combined_context += f"Executive Intelligence Results:\n{parallel_results[1][0]}\n\n"
                combined_context += f"Sentiment Analysis Results:\n{parallel_results[2][0]}\n\n"
            else:
                combined_context += "Market Data Results:\nNo ticker provided - stock data not available.\n\n"
                combined_context += f"Executive Intelligence Results:\n{parallel_results[0][0]}\n\n"
                combined_context += f"Sentiment Analysis Results:\n{parallel_results[1][0]}\n\n"
            
        except Exception as e:
            # Re-raise without logging
            raise
        
        # Phase 4: Synthesizer combines all results into structured JSON
        synthesis_task = f"""Synthesize the market performance data for {company_name} into structured JSON.

Company: {company_name}
Ticker: {resolved_ticker if resolved_ticker else "Not available - private company or not found"}

{combined_context}

Output the JSON in the exact format specified in your system message.
Include all four sections: stock_data, executive_insights, sentiment, and synthesis.
If no ticker was available, set stock_data to null.
"""
        
        try:
            synthesizer_results = await run_phase([synthesizer_agent], synthesis_task)
            synthesizer_output = synthesizer_results[0] if synthesizer_results else ""
            
        except Exception as e:
            # Re-raise without logging
            raise
        
        # Extract JSON from synthesizer output
        try:
            # Look for JSON in the output
            json_start = synthesizer_output.find('{')
            json_end = synthesizer_output.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = synthesizer_output[json_start:json_end]
                parsed = json.loads(json_str)
                
                # Add metadata
                final_response = {
                    "company": company_name,
                    "ticker": resolved_ticker,  # Use resolved ticker (may be None for private companies)
                    "ticker_source": "provided" if ticker else ("resolved" if resolved_ticker else "unavailable"),
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "stock_data": parsed.get("stock_data"),
                    "executive_insights": parsed.get("executive_insights", {}),
                    "sentiment": parsed.get("sentiment", {}),
                    "synthesis": parsed.get("synthesis", "")
                }
                
                return final_response
                
            else:
                raise ValueError("Synthesizer did not produce valid JSON output")
                
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse synthesizer output as JSON: {str(e)}")
        
    except ValueError as e:
        # Re-raise validation errors without logging
        raise
        
    except Exception as e:
        raise Exception(f"Market performance workflow failed: {str(e)}")


async def run_priority_alignment_workflow(
    priorities: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    opportunities: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Orchestrator for priority alignment workflow.
    
    Takes strategic priorities from knowledge base and maps them to
    active projects and pipeline opportunities using Priority_Mapper_Agent.
    
    Args:
        priorities: List of strategic priorities from KB (each has heading, description)
        projects: List of active delivery projects
        opportunities: List of pipeline opportunities
        
    Returns:
        Dictionary containing:
        - priorities: Array of priorities with coverage % and mapped items
        - unaligned_items: Projects/opportunities not mapped to any priority
        - summary: Overall alignment statistics
        
    Raises:
        Exception: If workflow execution fails.
    """
    from app.agents.agent_definitions import create_priority_mapper_agent
    
    logger.info(
        f"Starting priority alignment workflow: "
        f"{len(priorities)} priorities, {len(projects)} projects, {len(opportunities)} opportunities"
    )
    
    try:
        # Create the Priority Mapper Agent
        agent = create_priority_mapper_agent()
        
        # Convert date objects to strings for JSON serialization
        def convert_dates(obj):
            """Recursively convert date/datetime objects to ISO format strings."""
            if isinstance(obj, dict):
                return {k: convert_dates(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_dates(item) for item in obj]
            elif isinstance(obj, (date, datetime)):
                return obj.isoformat()
            else:
                return obj
        
        # Convert all dates in the data
        priorities_json = convert_dates(priorities)
        projects_json = convert_dates(projects)
        opportunities_json = convert_dates(opportunities)
        
        # Build the task prompt with all data
        task = f"""Analyze the following data and map projects/opportunities to strategic priorities.

PRIORITIES (from Knowledge Base):
{json.dumps(priorities_json, indent=2)}

PROJECTS (Active Delivery):
{json.dumps(projects_json, indent=2)}

OPPORTUNITIES (Pipeline):
{json.dumps(opportunities_json, indent=2)}

Analyze each priority and determine which projects and opportunities align with it.
Calculate coverage percentage and identify gaps.
Output the complete JSON response."""

        # Run the agent
        termination = MaxMessageTermination(max_messages=2)
        team = RoundRobinGroupChat([agent], termination_condition=termination)
        result = await team.run(task=task)
        
        # Extract agent's response
        agent_output = ""
        messages = result.messages if hasattr(result, 'messages') else []
        for msg in reversed(messages):
            if hasattr(msg, 'source') and msg.source == agent.name:
                agent_output = msg.content if hasattr(msg, 'content') else ""
                break
        
        if not agent_output:
            raise ValueError("Priority Mapper Agent did not produce output")
        
        # Parse JSON from agent output
        try:
            # Find JSON block in output
            json_start = agent_output.find('{')
            json_end = agent_output.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                json_str = agent_output[json_start:json_end]
                parsed = json.loads(json_str)
                
                logger.info(
                    f"Priority alignment completed: "
                    f"{len(parsed.get('priorities', []))} priorities analyzed, "
                    f"overall score: {parsed.get('summary', {}).get('overall_alignment_score', 'N/A')}%"
                )
                
                return parsed
            else:
                raise ValueError("Agent output does not contain valid JSON")
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Priority Mapper output: {str(e)}")
            raise ValueError(f"Failed to parse agent output as JSON: {str(e)}")
            
    except ValueError as e:
        raise
        
    except Exception as e:
        logger.error(f"Priority alignment workflow failed: {str(e)}", exc_info=True)
        raise Exception(f"Priority alignment workflow failed: {str(e)}")
