"""MySQL access. Two users: atlas_app (application) and atlas_ro (SQL tool, catalogue only)."""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

import pymysql
from pymysql.cursors import DictCursor

from app.config import Settings
from app.domain import Fact

logger = logging.getLogger(__name__)

PUBLIC_ACCESS = "public excerpt"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


class Repository:
    def __init__(self, settings: Settings):
        self.s = settings
        self._catalog: dict[str, dict] | None = None
        self._catalog_at = 0.0
        self._lock = threading.Lock()

    # --- connections -----------------------------------------------------
    @contextmanager
    def _conn(self, readonly: bool = False) -> Iterator[pymysql.connections.Connection]:
        user = self.s.mysql_ro_user if readonly else self.s.mysql_app_user
        password = self.s.mysql_ro_password if readonly else self.s.mysql_app_password
        read_timeout = max(2, self.s.sql_timeout_ms // 1000 + 1) if readonly else 10
        conn = pymysql.connect(
            host=self.s.mysql_host,
            port=self.s.mysql_port,
            user=user,
            password=password,
            database=self.s.mysql_database,
            cursorclass=DictCursor,
            autocommit=True,
            connect_timeout=5,
            read_timeout=read_timeout,
            write_timeout=10,
            charset="utf8mb4",
        )
        try:
            yield conn
        finally:
            conn.close()

    def ping(self) -> bool:
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except Exception:  # noqa: BLE001 - health check
            return False

    def wait_until_ready(self, timeout_s: float = 90) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            if self.ping():
                return
            if time.monotonic() > deadline:
                raise RuntimeError("MySQL not reachable")
            time.sleep(2)

    # --- clients and entitlements ---------------------------------------
    def get_client(self, client_id: str) -> dict | None:
        with self._conn() as c, c.cursor() as cur:
            # contact_email is deliberately never selected (and not granted).
            cur.execute("SELECT id, company FROM clients WHERE id = %s", (client_id,))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("SELECT report_id FROM client_purchases WHERE client_id = %s", (client_id,))
            row["purchased"] = sorted(r["report_id"] for r in cur.fetchall())
            return row

    def list_companies(self) -> list[dict]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute("SELECT id, company FROM clients ORDER BY id")
            return list(cur.fetchall())

    def get_catalog(self) -> dict[str, dict]:
        with self._lock:
            if self._catalog is not None and time.monotonic() - self._catalog_at < 60:
                return self._catalog
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT id, title, publisher, published, sector, market, region, access, keywords, summary "
                "FROM reports ORDER BY id"
            )
            rows = {r["id"]: {k: _jsonable(v) for k, v in r.items()} for r in cur.fetchall()}
        for r in rows.values():
            r["keywords"] = [k.strip().lower() for k in r["keywords"].split(",") if k.strip()]
        with self._lock:
            self._catalog, self._catalog_at = rows, time.monotonic()
        return rows

    def entitled_report_ids(self, client: dict) -> list[str]:
        catalog = self.get_catalog()
        public = {rid for rid, r in catalog.items() if r["access"] == PUBLIC_ACCESS}
        return sorted(set(client["purchased"]) | public)

    # --- metrics ---------------------------------------------------------
    def get_facts(self, report_ids: list[str], markets: list[str] | None = None) -> list[Fact]:
        """Figures for the given (already entitled) reports. Never call with locked ids."""
        if not report_ids:
            return []
        catalog = self.get_catalog()
        params: list[Any] = list(report_ids)
        sql = (
            "SELECT report_id, market, metric, region, period_start, period_end, value, unit, scope_note, page "
            f"FROM market_metrics WHERE report_id IN ({', '.join(['%s'] * len(report_ids))})"
        )
        if markets:
            sql += f" AND market IN ({', '.join(['%s'] * len(markets))})"
            params += markets
        sql += " ORDER BY report_id, FIELD(metric, 'market_size', 'cagr', 'regional_share'), region"
        with self._conn() as c, c.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        facts = []
        for i, r in enumerate(rows, start=1):
            rep = catalog.get(r["report_id"], {})
            facts.append(
                Fact(
                    fid=f"F{i}",
                    report_id=r["report_id"],
                    title=rep.get("title", ""),
                    publisher=rep.get("publisher", ""),
                    published=str(rep.get("published", "")),
                    market=r["market"],
                    metric=r["metric"],
                    region=r["region"],
                    period_start=int(r["period_start"]),
                    period_end=int(r["period_end"]),
                    value=float(r["value"]),
                    unit=r["unit"],
                    scope_note=r["scope_note"],
                    page=int(r["page"]),
                )
            )
        return facts

    def get_locked_values(self, report_ids: list[str]) -> list[float]:
        """Numbers from reports the client has NOT bought. Used only by the critic as a leak tripwire;
        these values are never placed in any prompt."""
        if not report_ids:
            return []
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                f"SELECT value FROM market_metrics WHERE report_id IN ({', '.join(['%s'] * len(report_ids))})",
                report_ids,
            )
            return [float(r["value"]) for r in cur.fetchall()]

    # --- read-only SQL tool ---------------------------------------------
    def run_readonly(self, sql: str) -> list[dict]:
        """Executes an already-validated SELECT as the catalogue-only read-only user."""
        with self._conn(readonly=True) as c, c.cursor() as cur:
            cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {int(self.s.sql_timeout_ms)}")
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(sql)
            rows = cur.fetchmany(self.s.sql_row_limit)
        return [{k: _jsonable(v) for k, v in r.items()} for r in rows]

    # --- tickets, logs, security events ---------------------------------
    def create_escalation(self, *, request_id: str, client_id: str, question: str, reason: str,
                          confidence: float | None, draft_answer: str | None) -> int:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO escalations (request_id, client_id, question, reason, confidence, draft_answer) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (request_id, client_id, question, reason[:500], confidence, draft_answer),
            )
            return int(cur.lastrowid)

    def list_escalations(self, status: str | None, limit: int) -> list[dict]:
        sql = ("SELECT id, request_id, client_id, question, reason, confidence, source, status, created_at "
               "FROM escalations")
        params: list[Any] = []
        if status:
            sql += " WHERE status = %s"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT %s"
        params.append(limit)
        with self._conn() as c, c.cursor() as cur:
            cur.execute(sql, params)
            return [{k: _jsonable(v) for k, v in r.items()} for r in cur.fetchall()]

    def log_security_event(self, *, event_type: str, source: str, detail: str,
                           request_id: str | None = None, client_id: str | None = None) -> None:
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO security_events (request_id, client_id, event_type, source, detail) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (request_id, client_id, event_type, source[:120], detail[:1000]),
                )
        except Exception:  # noqa: BLE001 - logging must never break a request
            logger.exception("security_event_log_failed")

    def list_security_events(self, limit: int) -> list[dict]:
        with self._conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT id, request_id, client_id, event_type, source, detail, created_at "
                "FROM security_events ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            return [{k: _jsonable(v) for k, v in r.items()} for r in cur.fetchall()]

    def log_request(self, row: dict) -> None:
        try:
            with self._conn() as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO request_log (request_id, client_id, question, route, confidence, escalated, cached, "
                    "latency_ms, prompt_tokens, completion_tokens, cost_usd, trace_json) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        row["request_id"], row["client_id"], row["question"], row["route"], row["confidence"],
                        int(row["escalated"]), int(row["cached"]), row["latency_ms"], row["prompt_tokens"],
                        row["completion_tokens"], row["cost_usd"], json.dumps(row.get("trace", []), default=str),
                    ),
                )
        except Exception:  # noqa: BLE001
            logger.exception("request_log_failed")
