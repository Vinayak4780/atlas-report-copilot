"""Read-only SQL tool for aggregate questions about the report catalogue."""
from __future__ import annotations

import json
import re

from app.llm import LLMClient, LLMUnavailable, RequestBudget
from app.security.sql_guard import UnsafeSQL, validate_select

SCHEMA = """Table reports (the report catalogue; one row per report):
  id VARCHAR        -- e.g. 'R-101'
  title VARCHAR
  publisher VARCHAR -- e.g. 'CMR', 'Aquila Insights (third party)'
  published DATE
  sector VARCHAR    -- e.g. 'Utilities', 'Consumer Durables', 'Energy'
  market VARCHAR    -- e.g. 'Smart water meters'
  region VARCHAR    -- geographic coverage: 'Global', 'APAC'
  access ENUM('paid','public excerpt')"""

SYSTEM = f"""You translate questions about a market research report library into ONE MySQL SELECT.
{SCHEMA}
Rules: only SELECT on the reports table; no other tables; no comments; no semicolons.
Prefer aggregates (COUNT, GROUP BY) for "how many" / "most" questions and ORDER BY for rankings.
If the question cannot be answered from this table, return null.
Reply as JSON: {{"sql": "<query or null>"}}"""


class SQLToolError(RuntimeError):
    pass


def generate_sql(llm: LLMClient, question: str, budget: RequestBudget) -> str | None:
    raw = llm.complete(system=SYSTEM, user=f"Question: {question}", budget=budget, purpose="sql_generation",
                       max_tokens=200, json_mode=True)
    try:
        sql = json.loads(raw).get("sql")
    except (json.JSONDecodeError, AttributeError):
        m = re.search(r"select\b.*", raw, re.IGNORECASE | re.S)
        sql = m.group(0) if m else None
    return sql.strip() if isinstance(sql, str) and sql.strip() else None


def run_sql_tool(llm: LLMClient, repo, question: str, budget: RequestBudget, row_limit: int) -> dict:
    """Returns {"query", "rows"} or {"error"}; never raises for unsafe SQL."""
    try:
        sql = generate_sql(llm, question, budget)
    except LLMUnavailable as e:
        return {"query": None, "rows": [], "error": f"SQL generation unavailable: {e}"}
    if not sql:
        return {"query": None, "rows": [], "error": "The question cannot be answered from the report catalogue."}
    try:
        safe = validate_select(sql, row_limit)
    except UnsafeSQL as e:
        return {"query": sql, "rows": [], "error": f"Blocked by SQL guard: {e}", "blocked": True}
    try:
        rows = repo.run_readonly(safe)
    except Exception as e:  # noqa: BLE001 - DB-side denial or timeout must fail safely
        return {"query": safe, "rows": [], "error": f"Query failed safely: {type(e).__name__}"}
    return {"query": safe, "rows": rows, "error": None}
