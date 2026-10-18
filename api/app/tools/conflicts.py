"""Deterministic conflict detection over structured facts.

Two reports conflict when they give a different value for the same market / metric / region /
year, or a CAGR over a different forecast window. Conflicts are surfaced side by side with their
scope notes; values are never averaged and neither source is silently preferred.
"""
from __future__ import annotations

from collections import defaultdict

from app.domain import METRIC_LABELS, Fact

REL_TOLERANCE = 0.005


def _differs(a: float, b: float) -> bool:
    return abs(a - b) > REL_TOLERANCE * max(abs(a), abs(b), 1e-9)


def _value(f: Fact) -> dict:
    return {
        "report_id": f.report_id,
        "publisher": f.publisher,
        "value": f.value,
        "display": f.display,
        "period": f.period,
        "scope_note": f.scope_note,
        "page": f.page,
        "citation_id": f.fid,
    }


def _note(metric: str, facts: list[Fact]) -> str:
    scopes = "; ".join(f"{f.report_id}: {f.scope_note}" for f in facts)
    if metric == "cagr":
        windows = sorted({f.period for f in facts})
        if len(windows) > 1:
            return (f"Forecast windows differ ({' vs '.join(windows)}), so the growth rates are not like-for-like. "
                    f"Scopes - {scopes}.")
        return f"Growth rates differ for the same window. Scopes - {scopes}."
    if metric == "regional_share":
        return f"The shares are measured against different bases. Scopes - {scopes}."
    return f"The reports measure different scopes, so the figures are not directly comparable. Scopes - {scopes}."


def detect_conflicts(facts: list[Fact], metrics: set[str] | None = None) -> list[dict]:
    groups: dict[tuple, list[Fact]] = defaultdict(list)
    for f in facts:
        if metrics and f.metric not in metrics:
            continue
        # CAGR windows are compared across reports; levels/shares are compared per year.
        year_key = "window" if f.metric == "cagr" else f.period_end
        groups[(f.market, f.metric, f.region, year_key)].append(f)

    conflicts = []
    for (market, metric, region, year_key), fs in groups.items():
        if len({f.report_id for f in fs}) < 2:
            continue
        values_differ = any(_differs(a.value, b.value) for a in fs for b in fs if a is not b)
        windows_differ = metric == "cagr" and len({f.period for f in fs}) > 1
        if not (values_differ or windows_differ):
            continue
        period = " vs ".join(sorted({f.period for f in fs})) if metric == "cagr" else str(year_key)
        conflicts.append({
            "market": market,
            "metric": metric,
            "region": region,
            "period": period,
            "kind": "different_forecast_window" if windows_differ else "value_mismatch",
            "label": f"{market}: {region} {METRIC_LABELS.get(metric, metric)} ({period})",
            "values": [_value(f) for f in sorted(fs, key=lambda x: x.report_id)],
            "note": _note(metric, fs),
            "resolution": "Both values shown; not averaged and neither source silently preferred.",
        })
    return conflicts
