"""LangGraph agent.

guard -> router -> entitlement -> retrieve -> evidence -> [calculator] -> writer -> critic -> finalize
                                \-> sql ------------------------------------^          |
  guard/router/entitlement can short-circuit to `refuse`; calculator/critic can go to `escalate`;
  critic can send the draft back to the writer once.
"""
import json
import logging
import re
import time
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from app.agent import render
from app.agent.critic import CriticReport, allowed_numbers, check_draft, extract_tags, score_confidence
from app.agent.prompts import ROUTER_SYSTEM, WRITER_SYSTEM, build_writer_prompt
from app.agent.routing import (
    VALID_ROUTES, contested_markets, detect_markets, heuristic_route, mentioned_reports, metric_focus,
    page_reference,
)
from app.config import Settings
from app.domain import METRIC_LABELS, Chunk, Fact
from app.llm import LLMClient, LLMUnavailable
from app.logging_setup import log_event
from app.security.guard import check_question
from app.security.injection import sanitize_document_text
from app.tools.calculator import detect_region, detect_target_year, project_for_report
from app.tools.conflicts import detect_conflicts
from app.tools.sql_tool import run_sql_tool

logger = logging.getLogger(__name__)
POSITIVE_REASONS = ("Figures come from", "Answer computed", "Answer based on")


class AgentState(TypedDict, total=False):
    # input
    request_id: str
    client_id: str
    company: str
    question: str
    history: list
    entitled: list
    catalog: dict
    other_companies: list
    budget: Any
    # routing / scoping
    route: str
    route_source: str
    refusal_kind: str
    guard_reason: str
    markets: list
    markets_explicit: bool
    mentioned: list
    scope_ids: list
    entitlement_alternatives: list
    # evidence
    chunks: list
    injection_events: list
    facts: list
    conflicts: list
    locked_reports: list
    derived: list
    calc_notes: list
    calc_status: str
    fixed_answer: str
    sql_result: dict
    # writing / checking
    draft: str
    writer_attempts: int
    writer_feedback: str
    retry_writer: bool
    llm_degraded: bool
    critic_report: dict
    confidence: float
    confidence_reasons: list
    escalation_kind: str
    escalation_detail: str
    # output
    escalated: bool
    escalation_id: int
    answer: str
    citations: list
    trace: list


def _report_info(rid: str, catalog: dict) -> dict:
    r = catalog[rid]
    return {"report_id": rid, "title": r["title"], "publisher": r["publisher"], "published": r["published"],
            "access": r["access"], "summary": r["summary"], "upgrade_hint": render.UPGRADE_HINT}


class AtlasAgent:
    def __init__(self, settings: Settings, repo, store, llm: LLMClient):
        self.s = settings
        self.repo = repo
        self.store = store
        self.llm = llm
        self.graph = self._build()

    def run(self, state: AgentState) -> AgentState:
        return self.graph.invoke(state, {"recursion_limit": 30})

    # ------------------------------------------------------------------ graph
    def _build(self):
        g = StateGraph(AgentState)
        for name in ("guard", "router", "entitlement", "retrieve", "evidence", "calculator", "sql",
                     "writer", "critic", "escalate", "refuse", "finalize"):
            g.add_node(name, self._timed(name, getattr(self, f"node_{name}")))
        g.set_entry_point("guard")
        g.add_conditional_edges("guard", self._after_guard,
                                {"refuse": "refuse", "escalate": "escalate", "router": "router"})
        g.add_conditional_edges("router", self._after_router, {"refuse": "refuse", "entitlement": "entitlement"})
        g.add_conditional_edges("entitlement", self._after_entitlement,
                                {"refuse": "refuse", "sql": "sql", "retrieve": "retrieve"})
        g.add_conditional_edges("retrieve", lambda s: "refuse" if s["route"] == "out_of_scope" else "evidence",
                                {"refuse": "refuse", "evidence": "evidence"})
        g.add_conditional_edges("evidence", self._after_evidence, {"calculator": "calculator", "writer": "writer"})
        g.add_conditional_edges("calculator", self._after_calculator,
                                {"writer": "writer", "escalate": "escalate", "finalize": "finalize"})
        g.add_edge("sql", "writer")
        g.add_edge("writer", "critic")
        g.add_conditional_edges("critic", self._after_critic,
                                {"writer": "writer", "escalate": "escalate", "finalize": "finalize"})
        for terminal in ("escalate", "refuse", "finalize"):
            g.add_edge(terminal, END)
        return g.compile()

    def _timed(self, name: str, fn: Callable[[AgentState], dict]) -> Callable[[AgentState], dict]:
        def wrapper(state: AgentState) -> dict:
            t0 = time.monotonic()
            out = fn(state) or {}
            ms = int((time.monotonic() - t0) * 1000)
            out["trace"] = list(state.get("trace", [])) + [{"node": name, "ms": ms}]
            log_event(logger, "node_done", node=name, ms=ms, request_id=state.get("request_id"))
            return out
        return wrapper

    # ---------------------------------------------------------- conditionals
    @staticmethod
    def _after_guard(s: AgentState) -> str:
        route = s.get("route")
        if route in ("unsafe", "out_of_scope"):
            return "refuse"
        if route == "escalation_request":
            return "escalate"
        return "router"

    @staticmethod
    def _after_router(s: AgentState) -> str:
        return "refuse" if s["route"] in ("unsafe", "out_of_scope") else "entitlement"

    @staticmethod
    def _after_entitlement(s: AgentState) -> str:
        if s["route"] == "entitlement_denied":
            return "refuse"
        return "sql" if s["route"] == "aggregate" else "retrieve"

    @staticmethod
    def _after_evidence(s: AgentState) -> str:
        return "calculator" if s["route"] == "calculation" else "writer"

    @staticmethod
    def _after_calculator(s: AgentState) -> str:
        status = s.get("calc_status")
        if status in ("beyond_window", "insufficient"):
            return "escalate"
        if status == "clarify":
            return "finalize"
        return "writer"

    def _after_critic(self, s: AgentState) -> str:
        if s.get("retry_writer"):
            return "writer"
        if s["confidence"] < self.s.confidence_threshold:
            return "escalate"
        return "finalize"

    # ----------------------------------------------------------------- nodes
    def node_guard(self, s: AgentState) -> dict:
        verdict = check_question(s["question"], s["company"], s["other_companies"])
        if verdict is None:
            return {}
        if verdict.security_event:
            self.repo.log_security_event(
                event_type=f"unsafe_request:{verdict.kind}", source="user_question",
                detail=f"{verdict.reason} | question: {s['question'][:300]}",
                request_id=s["request_id"], client_id=s["client_id"])
        log_event(logger, "guard_blocked", request_id=s["request_id"], kind=verdict.kind, route=verdict.route)
        return {"route": verdict.route, "refusal_kind": verdict.kind, "route_source": "guard",
                "guard_reason": verdict.reason}

    def node_router(self, s: AgentState) -> dict:
        q, catalog = s["question"], s["catalog"]
        markets = detect_markets(q, catalog)
        if not markets and s.get("history"):
            markets = detect_markets(" ".join(s["history"][-3:]), catalog)
        route, source = heuristic_route(q, bool(markets)), "heuristic"
        if route is None:
            source = "llm"
            try:
                raw = self.llm.complete(system=ROUTER_SYSTEM, user=q, budget=s["budget"], purpose="router",
                                        model=self.s.llm_router_model, max_tokens=30, json_mode=True)
                route = json.loads(raw).get("route")
            except (LLMUnavailable, json.JSONDecodeError, AttributeError):
                route, source = None, "default"
            if route not in VALID_ROUTES:
                route, source = "factual", "default"
        out = {"route": route, "route_source": source, "markets": markets, "markets_explicit": bool(markets)}
        if route == "unsafe":
            out["refusal_kind"] = "unsafe"
            self.repo.log_security_event(event_type="unsafe_request:llm_router", source="user_question",
                                         detail=f"Router classified as unsafe | question: {q[:300]}",
                                         request_id=s["request_id"], client_id=s["client_id"])
        elif route == "out_of_scope":
            out["refusal_kind"] = "out_of_scope"
        return out

    def node_entitlement(self, s: AgentState) -> dict:
        catalog, entitled = s["catalog"], s["entitled"]
        mentioned = mentioned_reports(s["question"], catalog)
        locked_mentioned = [r for r in mentioned if r not in entitled]
        entitled_mentioned = [r for r in mentioned if r in entitled]
        markets = list(s.get("markets") or [])

        if locked_mentioned and not entitled_mentioned:
            locked_markets = {catalog[r]["market"] for r in locked_mentioned}
            alternatives = [_report_info(r, catalog) for r in entitled if catalog[r]["market"] in locked_markets]
            self._log_entitlement(s, locked_mentioned)
            return {"route": "entitlement_denied", "refusal_kind": "entitlement", "mentioned": mentioned,
                    "locked_reports": [_report_info(r, catalog) for r in locked_mentioned],
                    "entitlement_alternatives": alternatives, "markets": sorted(locked_markets)}

        if s["route"] == "comparison" and not markets and not mentioned:
            markets = contested_markets(catalog, entitled)

        if markets and s["route"] != "aggregate":
            covered = [r for r in entitled if catalog[r]["market"] in markets]
            if not covered:
                locked = [r for r, rep in catalog.items() if rep["market"] in markets and r not in entitled]
                self._log_entitlement(s, locked)
                return {"route": "entitlement_denied", "refusal_kind": "entitlement", "mentioned": mentioned,
                        "locked_reports": [_report_info(r, catalog) for r in locked],
                        "entitlement_alternatives": [], "markets": markets}

        scope = entitled_mentioned or [r for r in entitled if not markets or catalog[r]["market"] in markets]
        return {"mentioned": mentioned, "markets": markets, "scope_ids": scope}

    def _log_entitlement(self, s: AgentState, locked: list[str]) -> None:
        log_event(logger, "entitlement_denied", request_id=s["request_id"], client_id=s["client_id"], locked=locked)

    def node_retrieve(self, s: AgentState) -> dict:
        q = s["question"]
        query = q if s.get("markets_explicit") or not s.get("history") else f"{s['history'][-1]} {q}"
        page = page_reference(q) if s.get("mentioned") else None
        chunks: list[Chunk] = self.store.search(query, s["scope_ids"], self.s.retrieval_top_k, page=page)
        anchored = s.get("markets") or s.get("mentioned")
        if not anchored and (not chunks or chunks[0].score < self.s.min_relevance):
            best = chunks[0].score if chunks else 0.0
            log_event(logger, "retrieval_below_floor", request_id=s["request_id"], best=best)
            if s.get("route_source") == "default":
                # Neither the heuristics nor the LLM could classify it and nothing in the library matches.
                return {"chunks": [], "route": "out_of_scope", "refusal_kind": "out_of_scope"}
            return {"chunks": []}
        events = []
        for i, c in enumerate(chunks, start=1):
            c.cid = f"C{i}"
            clean, hits = sanitize_document_text(c.text)
            if hits:
                c.text, c.injection_removed = clean, True
                events.append({"report_id": c.report_id, "page": c.page, "fragment": hits[0][:200]})
                self.repo.log_security_event(
                    event_type="injection_in_document", source=f"{c.report_id} p.{c.page}",
                    detail=f"Instruction-like text removed from retrieved chunk before the LLM call: '{hits[0][:200]}'",
                    request_id=s["request_id"], client_id=s["client_id"])
        return {"chunks": chunks, "injection_events": events}

    def node_evidence(self, s: AgentState) -> dict:
        catalog, entitled, chunks = s["catalog"], s["entitled"], s.get("chunks", [])
        markets = list(s.get("markets") or [])
        if not markets:
            if s["route"] == "calculation" or s.get("mentioned"):
                markets = sorted({catalog[r]["market"] for r in s["scope_ids"]})
            elif chunks:
                best = chunks[0].score
                markets = sorted({catalog[c.report_id]["market"] for c in chunks[:3] if c.score >= 0.85 * best})
        fact_ids = [r for r in s["scope_ids"] if catalog[r]["market"] in markets] if markets else []
        facts: list[Fact] = self.repo.get_facts(fact_ids, markets) if fact_ids else []
        focus = None if s["route"] in ("calculation", "comparison") else metric_focus(s["question"])
        conflicts = detect_conflicts(facts, focus)
        locked = [_report_info(r, catalog) for r, rep in catalog.items() if rep["market"] in markets and r not in entitled]
        return {"facts": facts, "conflicts": conflicts, "locked_reports": locked, "markets": markets}

    def node_calculator(self, s: AgentState) -> dict:
        q, facts, catalog = s["question"], s.get("facts", []), s["catalog"]
        target = detect_target_year(q, min_year=2025)
        if target is None:
            return {"calc_status": "no_target", "calc_notes": ["No target year found, so no projection was made."]}

        cagr_end = {f.report_id: f.period_end for f in facts if f.metric == "cagr"}
        if cagr_end and target > max(cagr_end.values()):
            windows = ", ".join(f"{f.report_id} {f.period}" for f in facts if f.metric == "cagr")
            return {"calc_status": "beyond_window", "escalation_kind": "beyond_window", "escalation_detail": (
                f"The forecast windows in your reports end by {max(cagr_end.values())} ({windows}). A {target} "
                f"figure would mean extrapolating beyond every report's forecast.")}

        markets = s.get("markets", [])
        if not s.get("markets_explicit") and len(markets) > 1:
            by_market = {m: [r for r in s["scope_ids"] if catalog[r]["market"] == m] for m in markets}
            return {"calc_status": "clarify", "fixed_answer": render.clarify_message(by_market)}

        region = detect_region(q)
        derived, notes = [], []
        for rid in sorted({f.report_id for f in facts}):
            d, note = project_for_report(facts, rid, region, target, f"D{len(derived) + 1}")
            if d:
                derived.append(d)
            elif note:
                notes.append(note)
        within = [d for d in derived if d["extrapolated_years"] == 0]
        if within:
            for d in derived:
                if d["extrapolated_years"]:
                    notes.append(f"{d['basis_report_id']}'s forecast window is {d['forecast_window']}, so it was not "
                                 f"projected to {target} (that would be an extrapolation).")
            derived = [dict(d, id=f"D{i}") for i, d in enumerate(within, start=1)]
        elif derived:
            windows = ", ".join(f"{d['basis_report_id']} {d['forecast_window']}" for d in derived)
            return {"calc_status": "beyond_window", "escalation_kind": "beyond_window", "escalation_detail": (
                f"The forecast windows in your reports ({windows}) end before {target}, so a {target} figure "
                f"would be an extrapolation.")}
        if not derived:
            return {"calc_status": "insufficient", "escalation_kind": "insufficient", "escalation_detail": (
                "Your reports don't contain the inputs needed to compute this. " + " ".join(notes)).strip()}
        return {"calc_status": "ok", "derived": derived, "calc_notes": notes}

    def node_sql(self, s: AgentState) -> dict:
        result = run_sql_tool(self.llm, self.repo, s["question"], s["budget"], self.s.sql_row_limit)
        if result.get("blocked"):
            self.repo.log_security_event(event_type="sql_blocked", source="sql_tool",
                                         detail=f"{result['error']} | sql: {(result.get('query') or '')[:400]}",
                                         request_id=s["request_id"], client_id=s["client_id"])
        return {"sql_result": result}

    def node_writer(self, s: AgentState) -> dict:
        attempts = s.get("writer_attempts", 0) + 1
        facts, chunks, derived = s.get("facts", []), s.get("chunks", []), s.get("derived", [])
        sql = s.get("sql_result")
        if s["route"] == "aggregate" and (not sql or sql.get("error")):
            reason = (sql or {}).get("error") or "no query result"
            return {"draft": f"INSUFFICIENT_EVIDENCE: {reason}", "writer_attempts": attempts}
        if s["route"] != "aggregate" and not facts and not chunks:
            return {"draft": "INSUFFICIENT_EVIDENCE: none of the reports in your subscription contain material "
                             "on this question.", "writer_attempts": attempts}
        budget = s["budget"]
        char_budget = int(min(9000, max(2000, (budget.remaining_tokens - self.s.max_output_tokens - 600) * 4)))
        prompt = build_writer_prompt(
            question=s["question"], history=s.get("history", []), route=s["route"], catalog=s["catalog"],
            facts=facts, chunks=chunks, derived=derived, conflicts=s.get("conflicts", []),
            locked=s.get("locked_reports", []), sql=sql, feedback=s.get("writer_feedback"), char_budget=char_budget)
        try:
            draft = self.llm.complete(system=WRITER_SYSTEM, user=prompt, budget=budget,
                                      purpose=f"writer_attempt_{attempts}")
            return {"draft": draft, "writer_attempts": attempts, "llm_degraded": False}
        except LLMUnavailable as e:
            log_event(logger, "writer_degraded", logging.WARNING, request_id=s["request_id"], error=str(e))
            return {"draft": render.fallback_answer(s["question"], facts, derived, sql),
                    "writer_attempts": attempts, "llm_degraded": True}

    def node_critic(self, s: AgentState) -> dict:
        facts, chunks, derived = s.get("facts", []), s.get("chunks", []), s.get("derived", [])
        sql = s.get("sql_result") or {}
        shown = {f.report_id for f in facts} | {c.report_id for c in chunks}
        meta = [f"{s['catalog'][r]['title']} {s['catalog'][r]['published']}" for r in shown]
        meta += [f"{l['title']} {l['published']}" for l in s.get("locked_reports", [])]
        allowed = allowed_numbers(question=s["question"], history=s.get("history", []), facts=facts, chunks=chunks,
                                  derived=derived, sql_rows=sql.get("rows") or [], extra_texts=meta)
        valid = {f.fid for f in facts} | {c.cid for c in chunks} | {d["id"] for d in derived}
        if sql.get("rows"):
            valid.add("Q1")
        locked_ids = [r for r in s["catalog"] if r not in s["entitled"]]
        report: CriticReport = check_draft(s["draft"], allowed=allowed, valid_tags=valid,
                                           locked_values=self.repo.get_locked_values(locked_ids))
        degraded = s.get("llm_degraded", False)
        if not report.ok and s.get("writer_attempts", 1) < 2 and not degraded:
            problems = []
            if report.unsupported_numbers or report.leaked_numbers:
                problems.append("these numbers do not appear in the material and must be removed or replaced "
                                f"with exact source values: {report.unsupported_numbers + report.leaked_numbers}")
            if report.invalid_tags:
                problems.append(f"these citation tags do not exist: {report.invalid_tags}")
            log_event(logger, "critic_retry", request_id=s["request_id"], **report.as_dict())
            return {"critic_report": report.as_dict(), "retry_writer": True, "writer_feedback": "; ".join(problems)}

        sql_ok = bool(sql.get("rows")) if s["route"] == "aggregate" else None
        confidence, reasons = score_confidence(
            route=s["route"], critic=report, facts=facts, chunks=chunks, conflicts=s.get("conflicts", []),
            derived=derived, sql_ok=sql_ok, llm_degraded=degraded, locked_count=len(s.get("locked_reports", [])))
        out = {"critic_report": report.as_dict(), "retry_writer": False, "confidence": confidence,
               "confidence_reasons": reasons}
        if confidence < self.s.confidence_threshold:
            if report.insufficient:
                out["escalation_kind"] = "insufficient"
                out["escalation_detail"] = ("I couldn't find enough in the reports in your subscription to answer "
                                            "this reliably.")
            else:
                out["escalation_kind"] = "low_confidence"
                out["escalation_detail"] = "; ".join(r for r in reasons if not r.startswith(POSITIVE_REASONS))
        return out

    def node_escalate(self, s: AgentState) -> dict:
        kind = s.get("escalation_kind") or ("client_request" if s.get("route") == "escalation_request"
                                            else "low_confidence")
        detail = s.get("escalation_detail", "")
        confidence = float(s.get("confidence", 0.3 if kind != "client_request" else 0.0))
        internal = json.dumps({
            "draft": s.get("draft"),
            "derived": s.get("derived", []),
            "conflicts": s.get("conflicts", []),
            "confidence_reasons": s.get("confidence_reasons", []),
        }, default=str)[:60000]
        ticket = self.repo.create_escalation(request_id=s["request_id"], client_id=s["client_id"],
                                             question=s["question"], reason=f"{kind}: {detail}"[:500],
                                             confidence=confidence, draft_answer=internal)
        log_event(logger, "escalated", request_id=s["request_id"], ticket=ticket, kind=kind)
        answer = render.escalation_message(ticket, kind, detail)
        locked = render.locked_section(s.get("locked_reports", []))
        if locked:
            answer += "\n\n" + locked
        reasons = s.get("confidence_reasons") or [f"Escalated: {kind}"]
        return {"answer": answer, "escalated": True, "escalation_id": ticket, "confidence": confidence,
                "confidence_reasons": reasons, "citations": [], "derived": [], "conflicts": []}

    def node_refuse(self, s: AgentState) -> dict:
        kind = s.get("refusal_kind") or "out_of_scope"
        if kind == "entitlement":
            answer = render.entitlement_message(s.get("locked_reports", []), s.get("entitlement_alternatives", []),
                                                s.get("markets", []))
            reason = "Entitlement check: requested figures are in reports the client has not purchased"
        else:
            answer = render.REFUSALS.get(kind, render.REFUSALS["out_of_scope"])
            reason = f"Policy refusal ({kind}): {s.get('guard_reason') or 'classified by router'}"
        return {"answer": answer, "escalated": False, "confidence": 1.0 if s.get("route_source") == "guard" else 0.9,
                "confidence_reasons": [reason], "citations": [], "derived": [], "conflicts": []}

    def node_finalize(self, s: AgentState) -> dict:
        if s.get("fixed_answer"):
            return {"answer": s["fixed_answer"], "escalated": False, "confidence": 0.9,
                    "confidence_reasons": ["Clarification needed: more than one market matches"], "citations": []}
        parts = [s["draft"].strip()]
        parts.append(render.conflicts_section(s.get("conflicts", [])))
        parts.append(render.derived_section(s.get("derived", [])))
        if s.get("calc_notes"):
            parts.append("Notes: " + " ".join(s["calc_notes"]))
        parts.append(render.locked_section(s.get("locked_reports", [])))
        if s["route"] == "aggregate":
            parts.append(render.sql_section((s.get("sql_result") or {}).get("query")))
        if s["route"] == "comparison" and re.search(r"\b(trust|reliable|recommend|should|better)\b",
                                                     s["question"], re.IGNORECASE):
            parts.append("If you'd like a CMR analyst to review this recommendation, reply \"escalate\" and I'll "
                         "open a ticket.")
        answer = "\n\n".join(p for p in parts if p)
        return {"answer": answer, "escalated": False, "citations": build_citations(answer, s)}


def build_citations(answer: str, s: AgentState) -> list[dict]:
    facts = {f.fid: f for f in s.get("facts", [])}
    chunks = {c.cid: c for c in s.get("chunks", [])}
    derived = {d["id"]: d for d in s.get("derived", [])}
    sql = s.get("sql_result") or {}
    out = []
    for tag in extract_tags(answer):
        if tag in facts:
            f = facts[tag]
            out.append({"id": tag, "kind": "metric", "report_id": f.report_id, "title": f.title,
                        "publisher": f.publisher, "page": f.page,
                        "snippet": f"{f.region} {METRIC_LABELS.get(f.metric, f.metric)} {f.period}: {f.display} "
                                   f"({f.scope_note})"})
        elif tag in chunks:
            c = chunks[tag]
            out.append({"id": tag, "kind": "excerpt", "report_id": c.report_id, "title": c.title,
                        "publisher": c.publisher, "page": c.page, "snippet": c.text[:280]})
        elif tag in derived:
            d = derived[tag]
            out.append({"id": tag, "kind": "derived", "report_id": d["basis_report_id"], "title": d["label"],
                        "publisher": "Atlas calculator", "page": None, "snippet": d["formula"]})
        elif tag == "Q1" and sql.get("query"):
            out.append({"id": tag, "kind": "sql", "report_id": None, "title": "Report catalogue query",
                        "publisher": "CMR library database", "page": None, "snippet": sql["query"]})
    return out
