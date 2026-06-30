"""Revenue JSON file reader for account commercial data.

Reads pre-aggregated revenue records from JSON files located at:
  {wsr_base_path}/{account_name}/Revenue/*.json

Each file has a `records` array where every record contains month columns
in the form `Mon-YYYY` (e.g. `Jan-2025`) with float revenue values.
"""
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.utils.logger import get_logger
from app.utils.response_cache import ResponseCache

logger = get_logger(__name__, settings.log_level)

_record_cache = ResponseCache("REVENUE_FILE", lambda: settings.revenue_file_cache_days)

_MONTH_COL_RE = re.compile(r"^[A-Za-z]{3}-\d{4}$")

_MONTH_NUM = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_QUARTER_OF = {
    "Jan": "Q1", "Feb": "Q1", "Mar": "Q1",
    "Apr": "Q2", "May": "Q2", "Jun": "Q2",
    "Jul": "Q3", "Aug": "Q3", "Sep": "Q3",
    "Oct": "Q4", "Nov": "Q4", "Dec": "Q4",
}


def _find_revenue_files(account_name: str) -> List[Path]:
    base = Path(settings.wsr_base_path)
    if not base.is_absolute():
        base = Path(__file__).parent.parent.parent / base
    folder = base / account_name / "Revenue"
    if not folder.exists():
        logger.warning(f"Revenue folder not found: {folder}")
        return []
    return sorted(folder.glob("*.json"))


def _col_date(col: str) -> date:
    month_abbr, year_str = col.split("-")
    return date(int(year_str), _MONTH_NUM[month_abbr], 1)


def _format_month(col: str) -> str:
    """'Jan-2025' → 'Jan \\'25'"""
    month, year = col.split("-")
    return f"{month} '{year[2:]}"


def _quarter_label(col: str) -> str:
    """'Jan-2025' → 'Q1 FY25'"""
    month, year = col.split("-")
    return f"{_QUARTER_OF[month]} FY{year[2:]}"


def _month_cols(record: dict) -> List[str]:
    return [k for k in record if _MONTH_COL_RE.match(k)]


def _load_all_records(account_name: str) -> List[dict]:
    """Load and merge all JSON revenue records for an account (cached)."""
    cache_key = f"records:{account_name}"
    cached = _record_cache.get(cache_key)
    if cached is not None:
        return cached

    files = _find_revenue_files(account_name)
    if not files:
        return []

    all_records: List[dict] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            all_records.extend(data.get("records", []))
            logger.info(f"Loaded {len(data.get('records', []))} revenue records from {f.name}")
        except Exception as exc:
            logger.error(f"Error reading revenue file {f}: {exc}")

    _record_cache.set(cache_key, all_records)
    return all_records


def get_monthly_revenue(account_name: str) -> List[Dict[str, Any]]:
    """Aggregate total revenue by calendar month.

    Returns list of {month, revenue, target} sorted chronologically,
    omitting months with zero revenue.
    """
    records = _load_all_records(account_name)
    if not records:
        return []

    cols = sorted(_month_cols(records[0]), key=_col_date)
    totals: Dict[str, float] = defaultdict(float)
    for rec in records:
        for col in cols:
            totals[col] += float(rec.get(col) or 0.0)

    return [
        {"month": _format_month(col), "revenue": round(totals[col], 2), "target": None}
        for col in cols
        if totals[col] != 0.0
    ]


def get_revenue_mix(account_name: str) -> List[Dict[str, Any]]:
    """Revenue broken down by Serviceline Group, then by month.

    Returns list of {service_line, monthly: [{month, revenue}]},
    omitting service lines and months with zero revenue.
    """
    records = _load_all_records(account_name)
    if not records:
        return []

    cols = sorted(_month_cols(records[0]), key=_col_date)
    sl_month: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for rec in records:
        sl = rec.get("Serviceline Group") or "Other"
        for col in cols:
            sl_month[sl][col] += float(rec.get(col) or 0.0)

    result = []
    for sl in sorted(sl_month):
        monthly = [
            {"month": _format_month(col), "revenue": round(sl_month[sl][col], 2)}
            for col in cols
            if sl_month[sl][col] != 0.0
        ]
        if monthly:
            result.append({"service_line": sl, "monthly": monthly})
    return result


def get_quarterly_margin(account_name: str) -> List[Dict[str, Any]]:
    """Quarterly revenue totals.

    Cost and margin_pct are unavailable from the file and returned as None.
    Omits quarters with zero revenue.
    """
    records = _load_all_records(account_name)
    if not records:
        return []

    cols = _month_cols(records[0])
    qtr_totals: Dict[str, float] = defaultdict(float)
    qtr_first_date: Dict[str, date] = {}

    for col in cols:
        label = _quarter_label(col)
        d = _col_date(col)
        if label not in qtr_first_date:
            qtr_first_date[label] = d
        for rec in records:
            qtr_totals[label] += float(rec.get(col) or 0.0)

    sorted_qtrs = sorted(qtr_first_date, key=lambda q: qtr_first_date[q])
    return [
        {"quarter": q, "revenue": round(qtr_totals[q], 2), "cost": None, "margin_pct": None}
        for q in sorted_qtrs
        if qtr_totals[q] != 0.0
    ]


def get_project_revenue(account_name: str) -> Dict[str, float]:
    """Return {project_name: total_revenue} for all projects with non-zero revenue."""
    records = _load_all_records(account_name)
    if not records:
        return {}

    cols = _month_cols(records[0])
    project_totals: Dict[str, float] = defaultdict(float)

    for rec in records:
        proj = rec.get("Project Name") or ""
        for col in cols:
            project_totals[proj] += float(rec.get(col) or 0.0)

    return {k: round(v, 2) for k, v in project_totals.items() if v > 0}


def get_projects_for_analysis(account_name: str) -> List[Dict[str, Any]]:
    """Return one entry per unique project, deduplicated and aggregated across employee categories.

    Fields returned per project:
      project_name, service_line, sub_service_line, fte_count (max headcount
      across rows), ytd_revenue (sum across all rows for that project), year.
    Sorted by project_name for stable ordering.
    """
    records = _load_all_records(account_name)
    if not records:
        return []

    cols = _month_cols(records[0])
    projects: Dict[str, Dict[str, Any]] = {}

    for rec in records:
        name = rec.get("Project Name") or ""
        if not name:
            continue
        ytd = sum(float(rec.get(col) or 0.0) for col in cols)
        if name not in projects:
            projects[name] = {
                "project_name": name,
                "service_line": rec.get("Serviceline Group") or "",
                "sub_service_line": rec.get("Serviceline Subgroup") or "",
                "fte_count": int(rec.get("headcount") or 0),
                "ytd_revenue": 0.0,
                "year": rec.get("source_year") or "",
            }
        projects[name]["ytd_revenue"] += ytd
        projects[name]["fte_count"] = max(
            projects[name]["fte_count"], int(rec.get("headcount") or 0)
        )

    result = sorted(projects.values(), key=lambda p: p["project_name"])
    for p in result:
        p["ytd_revenue"] = round(p["ytd_revenue"], 2)
    return result


def get_revenue_summary(account_name: str) -> Optional[Dict[str, float]]:
    """Compute LTM and YTD revenue totals from the file.

    Returns None when no revenue file exists for the account.
    LTM = last 365 days; YTD = current calendar year up to today.
    """
    records = _load_all_records(account_name)
    if not records:
        return None

    today = date.today()
    ltm_cutoff = date((today - timedelta(days=365)).year, (today - timedelta(days=365)).month, 1)
    current_year = today.year

    cols = _month_cols(records[0])
    ltm_total = 0.0
    ytd_total = 0.0

    for col in cols:
        col_date = _col_date(col)
        if col_date > today:
            continue
        col_rev = sum(float(rec.get(col) or 0.0) for rec in records)
        if col_date >= ltm_cutoff:
            ltm_total += col_rev
        if col_date.year == current_year:
            ytd_total += col_rev

    return {
        "ltm_revenue": round(ltm_total, 2),
        "ytd_revenue": round(ytd_total, 2),
    }
