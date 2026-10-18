"""Calculator tool: projections from quoted figures, with the formula and every assumption shown.

All outputs are labelled as derived estimates. One projection per source report: figures from
different reports are never blended. The base-year ambiguity (2024 base value vs a CAGR window
that starts in 2025) is reported as an explicit alternative, not hidden.
"""
from __future__ import annotations

import re

from app.domain import Fact

REGION_ALIASES = {
    "APAC": ("apac", "asia-pacific", "asia pacific", "asia"),
    "China": ("china",),
    "Global": ("global", "worldwide", "world"),
}


def detect_region(question: str) -> str:
    q = question.lower()
    for region, aliases in REGION_ALIASES.items():
        if region == "Global":
            continue
        if any(re.search(rf"\b{re.escape(a)}\b", q) for a in aliases):
            return region
    return "Global"


def detect_target_year(question: str, min_year: int = 2025) -> int | None:
    years = [int(y) for y in re.findall(r"\b(20[2-9]\d)\b", question)]
    future = [y for y in years if y >= min_year]
    return max(future) if future else None


def project(base: float, rate_pct: float, years: int) -> float:
    """Compound growth: base x (1 + r)^n."""
    return base * (1 + rate_pct / 100) ** years


def implied_cagr(start: float, end: float, years: int) -> float:
    """CAGR in percent between two values n years apart."""
    if start <= 0 or years <= 0:
        raise ValueError("start must be positive and years > 0")
    return ((end / start) ** (1 / years) - 1) * 100


def _pick(facts: list[Fact], metric: str, region: str | None = None) -> Fact | None:
    cands = [f for f in facts if f.metric == metric and (region is None or f.region == region)]
    return max(cands, key=lambda f: f.period_end) if cands else None


def project_for_report(facts: list[Fact], report_id: str, region: str, target_year: int,
                       derived_id: str) -> tuple[dict | None, str | None]:
    """Returns (derived_value, note). derived_value is None when the report lacks the inputs."""
    rf = [f for f in facts if f.report_id == report_id]
    if not rf:
        return None, None
    market = rf[0].market
    cagr = _pick(rf, "cagr", region) or _pick(rf, "cagr", "Global") or _pick(rf, "cagr")
    if cagr is None:
        return None, f"{report_id} states no CAGR, so no projection is possible from it."

    inputs, assumptions = [], []
    direct = _pick(rf, "market_size", region)
    if direct is not None:
        size, share = direct, None
        base_value = direct.value
        base_expr = f"{direct.value:g}"
        symbolic = f"V_{target_year} = V_{direct.period_end} x (1 + CAGR)^n"
    else:
        size = _pick(rf, "market_size", "Global")
        share = _pick(rf, "regional_share", region)
        if size is None or share is None:
            return None, f"{report_id} has no {region} market size or share, so it cannot be projected for {region}."
        base_value = size.value * share.value / 100
        base_expr = f"{size.value:g} x {share.value / 100:g}"
        symbolic = f"V_{target_year} = V_{size.period_end} x share_{region} x (1 + CAGR)^n"
        assumptions.append(
            f"The {region} share stays at its {share.period_end} level ({share.display}) through {target_year}; "
            f"{report_id} does not forecast regional shares."
        )

    base_year = size.period_end
    if target_year <= base_year:
        return None, f"{target_year} is not after the base year {base_year}."

    inputs.append({"name": f"{size.region} market size {size.period}", "value": size.display,
                   "report_id": report_id, "page": size.page, "citation_id": size.fid})
    if share is not None:
        inputs.append({"name": f"{region} share {share.period}", "value": share.display,
                       "report_id": report_id, "page": share.page, "citation_id": share.fid})
    inputs.append({"name": f"CAGR {cagr.period}", "value": cagr.display,
                   "report_id": report_id, "page": cagr.page, "citation_id": cagr.fid})

    n = target_year - base_year
    value = project(base_value, cagr.value, n)
    rate = 1 + cagr.value / 100
    formula = f"{symbolic} = {base_expr} x ({rate:g})^{n} = {value:.2f}"
    assumptions.append(f"Scope follows {report_id}: {size.scope_note}.")

    alternatives = []
    ambiguity = None
    if cagr.period_start > base_year:
        gap = cagr.period_start - base_year
        assumptions.append(
            f"The {cagr.display} CAGR is stated for {cagr.period}; it is also applied to the {base_year}-"
            f"{cagr.period_start} gap ({gap} year) because no growth rate is given for it."
        )
        alt_n = target_year - cagr.period_start
        alt_value = project(base_value, cagr.value, alt_n)
        ambiguity = (
            f"Base-year ambiguity: the market size is for {base_year} but the CAGR window starts in "
            f"{cagr.period_start}. Treating the {base_year} value as the {cagr.period_start} starting point "
            f"({alt_n} years of growth) gives USD {alt_value:.2f} B instead of USD {value:.2f} B."
        )
        alternatives.append({
            "label": f"{alt_n} compounding years ({base_year} value used as {cagr.period_start} base)",
            "value": round(alt_value, 2),
            "display": f"USD {alt_value:.2f} B",
            "formula": f"{base_expr} x ({rate:g})^{alt_n} = {alt_value:.2f}",
        })

    beyond = max(0, target_year - cagr.period_end)
    if beyond:
        assumptions.append(
            f"EXTRAPOLATION: {report_id}'s forecast window ends in {cagr.period_end}; the CAGR is extended "
            f"{beyond} year(s) beyond it."
        )

    return {
        "id": derived_id,
        "kind": "derived_estimate",
        "label": f"{region} {market.lower()} market size, {target_year} (derived from {report_id})",
        "basis_report_id": report_id,
        "value": round(value, 2),
        "unit": "USD B",
        "display": f"USD {value:.2f} B",
        "formula": formula,
        "inputs": inputs,
        "assumptions": assumptions,
        "base_year_ambiguity": ambiguity,
        "alternatives": alternatives,
        "forecast_window": cagr.period,
        "extrapolated_years": beyond,
    }, None
