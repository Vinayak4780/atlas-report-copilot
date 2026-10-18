"""Validation for LLM-generated SQL. Layered with the database-side controls:

  this validator  -> single SELECT, allow-listed tables, no comments/dangerous functions, LIMIT enforced
  atlas_ro user   -> SELECT on `reports` only (no metrics, no clients) - see db/init/03_users.sh
  session         -> MAX_EXECUTION_TIME + READ ONLY transaction (see Repository.run_readonly)
"""
import re

import sqlglot
from sqlglot import exp

ALLOWED_TABLES = {"reports"}
FORBIDDEN_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|rename|merge|call|load|"
    r"handler|lock|unlock|set|use|show|describe|explain|into|outfile|dumpfile|sleep|benchmark|"
    r"information_schema|performance_schema|mysql|sys|load_file|get_lock)\b",
    re.IGNORECASE,
)


class UnsafeSQL(ValueError):
    pass


def validate_select(sql: str, row_limit: int) -> str:
    """Returns a normalised, LIMIT-bounded SELECT or raises UnsafeSQL."""
    if not sql or not sql.strip():
        raise UnsafeSQL("empty query")
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise UnsafeSQL("multiple statements are not allowed")
    if "--" in s or "/*" in s or "#" in s:
        raise UnsafeSQL("comments are not allowed")
    m = FORBIDDEN_RE.search(s)
    if m:
        raise UnsafeSQL(f"forbidden keyword: {m.group(0)}")
    try:
        parsed = sqlglot.parse(s, read="mysql")
    except sqlglot.errors.ParseError as e:
        raise UnsafeSQL(f"could not parse query: {e}") from e
    if len(parsed) != 1 or parsed[0] is None:
        raise UnsafeSQL("exactly one statement is required")
    stmt = parsed[0]
    if not isinstance(stmt, exp.Select):
        raise UnsafeSQL("only SELECT statements are allowed")
    tables = {t.name.lower() for t in stmt.find_all(exp.Table)}
    if not tables:
        raise UnsafeSQL("query must read from the reports table")
    if not tables <= ALLOWED_TABLES:
        raise UnsafeSQL(f"table not allowed: {', '.join(sorted(tables - ALLOWED_TABLES))}")

    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(row_limit)
    else:
        try:
            current = int(limit.expression.name)
        except (AttributeError, ValueError) as e:
            raise UnsafeSQL("LIMIT must be a number") from e
        if current > row_limit:
            stmt = stmt.limit(row_limit)
    return stmt.sql(dialect="mysql")
