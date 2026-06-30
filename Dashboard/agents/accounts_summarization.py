"""Business logic for multi-account intelligence summarization.

This module contains the business logic for running portfolio-wide intelligence
analysis. It coordinates fetching accounts and orchestrating the multi-account workflow.
"""
from datetime import datetime
from typing import Any, Dict
from app.agents.orchestrator import run_intelligence_workflow
from app.utils.logger import get_logger
from app.utils.response_cache import ResponseCache
from app.config import settings

logger = get_logger(__name__, settings.log_level)

_summary_cache = ResponseCache("SUMMARY", lambda: settings.intelligence_cache_days)


async def get_accounts_summary(
    intelligence_service,
    page: int = 1,
    page_size: int = 15,
    tier: str | None = None,
    vertical: str | None = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Execute multi-account intelligence workflow for portfolio summary.
    
    Business logic layer for portfolio intelligence analysis.
    Cost-optimized approach: Runs ONE intelligence workflow for ALL accounts
    instead of running separate workflows for each account.
    
    This reduces API calls from ~450 (15 accounts x 30 calls each) to ~30 calls
    total, achieving ~90% cost reduction.
    
    Args:
        intelligence_service: IntelligenceService instance for DB access
        page: Page number for pagination (default: 1)
        page_size: Number of accounts to analyze (default: 15)
        tier: Optional tier filter (e.g., "Strategic")
        vertical: Optional vertical filter (e.g., "BFSI")
        
    Returns:
        Dictionary containing:
            - generated_at: Timestamp
            - total_accounts: Number of accounts analyzed
            - accounts: List of account summaries with intelligence per account
            
    Raises:
        Exception: For workflow execution errors.
    """
    cache_key = f"p{page}|ps{page_size}|t{tier or ''}|v{vertical or ''}"
    if refresh:
        _summary_cache.invalidate(cache_key)
    cached = _summary_cache.get(cache_key)
    if cached is not None:
        return cached

    logger.info(f"Starting multi-account intelligence summary for page {page}, page_size {page_size}")

    try:
        # Fetch top accounts from database via service layer
        paged_data = intelligence_service.account_svc.list_accounts(
            page=page,
            page_size=page_size,
            tier=tier,
            vertical=vertical,
            sort_by="total_acv",
            sort_order="desc"
        )
        
        if not paged_data.data:
            logger.warning("No accounts found for multi-account summary")
            return {
                "generated_at": datetime.now().strftime("%Y-%m-%d"),
                "total_accounts": 0,
                "accounts": []
            }
        
        # Convert Pydantic models to dictionaries for orchestrator
        accounts = []
        for account in paged_data.data:
            accounts.append({
                "id": account.id,
                "name": account.name,
                "vertical": account.vertical,
                "location": account.location,
                "total_acv": account.total_acv,
                "tier": account.tier
            })
        
        logger.info(f"Fetched {len(accounts)} accounts for multi-account analysis")
        
        # Run SINGLE intelligence workflow for ALL accounts
        # This is the key cost optimization - one workflow instead of N workflows
        # The orchestrator will use multi-account agents and prompts
        result = await run_intelligence_workflow(accounts=accounts)
        
        logger.info(
            f"Multi-account intelligence summary completed - "
            f"{result.get('total_accounts', 0)} accounts analyzed"
        )

        _summary_cache.set(cache_key, result)
        return result
        
    except Exception as e:
        logger.error(
            f"Multi-account intelligence summary failed: {str(e)}",
            exc_info=True
        )
        raise
