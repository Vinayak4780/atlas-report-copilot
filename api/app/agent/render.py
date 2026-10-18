"""Deterministic text: refusals, escalation notices, and the appended answer sections.

Conflicts, derived-value formulas and locked-report notices are rendered from structured data
rather than left to the LLM, so they are always present and always exact.
"""
from __future__ import annotations

from app.domain import METRIC_LABELS, Fact

UPGRADE_HINT = "Ask your CMR account manager for an upgrade quote, or request access from the portal's Reports page."

REFUSALS = {
    "prompt_injection": (
        "I can't do that. I don't change how I operate based on instructions in a question, and I never share "
        "client records or contact details. This request has been logged for review. I'm happy to help with "
        "questions about the market reports in your subscription."
    ),
    "data_modification": (
        "I can't modify or delete data. The Report Copilot has read-only access to the report catalogue, and "
        "requests to change data are blocked and logged. If a report record needs correcting, please contact "
        "your account manager."
    ),
    "personal_data": (
        "I can't share contact details, personal data or other confidential information. This request has been "
        "logged. I can help with market sizes, forecasts and report comparisons from your subscription."
    ),
    "other_clients": (
        "I can't share information about other clients or what they have purchased; that is confidential. "
        "I can tell you which reports exist in our library and which ones are in your subscription."
    ),
    "politics": (
        "That's outside what I can help with. I answer questions about CMR market research reports, such as market "
        "sizes, growth forecasts, regional splits and how different reports compare. Is there a market you'd "
        "like me to look at?"
    ),
    "out_of_scope": (
        "That's outside what I can help with. I answer questions about the market research reports in your "
        "subscription, such as market sizes, growth forecasts, regional splits and how reports compare."
    ),
    "unsafe": (
        "I can't help with that request. It has been logged for review. I'm happy to answer questions about the "
        "market reports in your subscription."
    ),
}


def entitlement_message(locked: list[dict], alternatives: list[dict], markets: list[str]) -> str:
    names = "; ".join(f"{l['report_id']} \"{l['title']}\" ({l['publisher']})" for l in locked)
    if alternatives:
        alt = "; ".join(f"{a['report_id']} \"{a['title']}\" ({a['publisher']}, {a['access']})" for a in alternatives)
        tail = f" Reports in your subscription that cover the same market: {alt}. I can answer from those if useful."
    else:
        scope = ", ".join(markets) if markets else "this topic"
        tail = f" No report in your current subscription covers {scope.lower()}."
    return (f"{names} {'is' if len(locked) == 1 else 'are'} in our library but not part of your subscription, so I "
            f"can't share any of {'its' if len(locked) == 1 else 'their'} figures. {UPGRADE_HINT}{tail}")


def clarify_message(markets: dict[str, list[str]]) -> str:
    lines = "; ".join(f"{m.lower()} ({', '.join(ids)})" for m, ids in markets.items())
    return (f"Which market do you mean? Your subscription covers: {lines}. Please name the market and I'll "
            "calculate the projection with its formula and assumptions.")


def escalation_message(ticket_id: int, reason_kind: str, detail: str) -> str:
    lead = {
        "beyond_window": f"{detail} I won't extrapolate silently, because an unsupported number is worse than no answer.",
        "client_request": "I've passed your question to a human analyst.",
        "insufficient": f"{detail}",
        "low_confidence": ("I'm not confident enough in this answer to send it without review. "
                           f"Main concerns: {detail}."),
    }.get(reason_kind, detail)
    return (f"{lead} I've opened ticket #{ticket_id} and a CMR analyst will reply, typically within one business day.")


def conflicts_section(conflicts: list[dict]) -> str:
    if not conflicts:
        return ""
    lines = ["Sources disagree (shown side by side, not averaged):"]
    for c in conflicts:
        vals = "; ".join(f"{v['report_id']} {v['display']} for {v['period']} ({v['scope_note']}, p.{v['page']}) "
                         f"[{v['citation_id']}]" for v in c["values"])
        lines.append(f"- {c['label']}: {vals}. {c['note'].split(' Scopes - ')[0]}")
    return "\n".join(lines)


def derived_section(derived: list[dict]) -> str:
    if not derived:
        return ""
    lines = ["Derived estimates (calculated by the copilot, not quoted from any report):"]
    for d in derived:
        lines.append(f"- [{d['id']}] {d['label']}: {d['display']} (derived estimate)")
        lines.append(f"  Formula: {d['formula']}")
        lines.append("  Inputs: " + "; ".join(
            f"{i['name']} = {i['value']} ({i['report_id']} p.{i['page']}) [{i['citation_id']}]" for i in d["inputs"]))
        for a in d["assumptions"]:
            lines.append(f"  Assumption: {a}")
        if d.get("base_year_ambiguity"):
            lines.append(f"  {d['base_year_ambiguity']}")
    return "\n".join(lines)


def locked_section(locked: list[dict]) -> str:
    if not locked:
        return ""
    names = "; ".join(f"{l['report_id']} \"{l['title']}\" ({l['publisher']})" for l in locked)
    return f"Not in your subscription: {names} also cover{'s' if len(locked) == 1 else ''} this market. {UPGRADE_HINT}"


def sql_section(query: str | None) -> str:
    return f"Query used (read-only, catalogue table only):\n{query}" if query else ""


def fallback_answer(question: str, facts: list[Fact], derived: list[dict], sql: dict | None) -> str:
    """Used when the LLM is unavailable: a templated answer that only restates structured data."""
    if sql and sql.get("rows"):
        return f"Result of the catalogue query [Q1]: {sql['rows']}"
    if derived:
        return " ".join(f"{d['label']}: {d['display']} (derived estimate) [{d['id']}]." for d in derived)
    if facts:
        return "Figures from your reports: " + " ".join(
            f"{f.report_id} {f.region} {METRIC_LABELS.get(f.metric, f.metric)} {f.period}: {f.display} "
            f"({f.scope_note}) [{f.fid}]." for f in facts)
    return "INSUFFICIENT_EVIDENCE: no structured figures available and the language model is unavailable."
