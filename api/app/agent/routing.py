"""Deterministic helpers for routing and scoping (no I/O, unit-tested)."""
from __future__ import annotations

import re

from app.tools.calculator import detect_target_year

AGG_RE = re.compile(
    r"\b(how many|number of|count of|which sector|which publisher|most reports|fewest reports|"
    r"list (all |the |your )?reports|reports? (do you have|are there|are in|are available)|"
    r"in (your|the) (library|catalog(ue)?)|newest report|latest report|oldest report|published (in|after|before|by))\b",
    re.IGNORECASE,
)
CALC_VERBS_RE = re.compile(r"\b(will|worth|reach|be|projection|project|projected|forecast|estimate|value|size)\b",
                           re.IGNORECASE)
CALC_EXPLICIT_RE = re.compile(r"\b(calculate|compute|projection|project(ed)? (to|for|the)|implied)\b", re.IGNORECASE)
COMPARE_RE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|differ|difference|disagree|conflict(ing)?|trust|reliable|reliability|"
    r"which report|which source|better source|recommend)\b",
    re.IGNORECASE,
)
FACT_RE = re.compile(r"\b(market size|size|worth|valued?|revenue|cagr|growth|share|forecast|figure|say)\b",
                     re.IGNORECASE)
REPORT_ID_RE = re.compile(r"\bR-\d{3}\b", re.IGNORECASE)
VALID_ROUTES = {"factual", "comparison", "calculation", "aggregate", "out_of_scope", "unsafe"}


def heuristic_route(question: str, has_market: bool) -> str | None:
    if AGG_RE.search(question):
        return "aggregate"
    if detect_target_year(question, min_year=2026) and CALC_VERBS_RE.search(question):
        return "calculation"
    if CALC_EXPLICIT_RE.search(question):
        return "calculation"
    if COMPARE_RE.search(question):
        return "comparison"
    if has_market or REPORT_ID_RE.search(question) or FACT_RE.search(question):
        return "factual"
    return None


def detect_markets(text: str, catalog: dict[str, dict]) -> list[str]:
    t = text.lower()
    found = set()
    for r in catalog.values():
        if any(re.search(rf"\b{re.escape(k)}", t) for k in r["keywords"]):
            found.add(r["market"])
    return sorted(found)


def mentioned_reports(question: str, catalog: dict[str, dict]) -> list[str]:
    ids = {m.upper() for m in REPORT_ID_RE.findall(question)}
    q = question.lower()
    for rid, r in catalog.items():
        publisher_word = r["publisher"].split()[0].lower()
        if publisher_word != "cmr" and len(publisher_word) > 3 and re.search(rf"\b{re.escape(publisher_word)}\b", q):
            ids.add(rid)
        if r["title"].lower() in q:
            ids.add(rid)
    return sorted(i for i in ids if i in catalog)


def contested_markets(catalog: dict[str, dict], entitled: list[str]) -> list[str]:
    """Markets covered by 2+ reports where the client can see at least one ("which report should I trust?")."""
    by_market: dict[str, list[str]] = {}
    for rid, r in catalog.items():
        by_market.setdefault(r["market"], []).append(rid)
    return sorted(m for m, ids in by_market.items() if len(ids) > 1 and any(i in entitled for i in ids))


def metric_focus(question: str) -> set[str] | None:
    q = question.lower()
    focus = set()
    if re.search(r"\b(size|worth|valued?|revenue|market value)\b", q):
        focus.add("market_size")
    if re.search(r"\b(cagr|growth|grow|growing)\b", q):
        focus.add("cagr")
    if re.search(r"\b(share|apac|asia|asia-pacific|regional|region)\b", q):
        focus.add("regional_share")
    return focus or None


def page_reference(question: str) -> int | None:
    m = re.search(r"\bpage\s+(\d{1,3})\b", question, re.IGNORECASE)
    return int(m.group(1)) if m else None
