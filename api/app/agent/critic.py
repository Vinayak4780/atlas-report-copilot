"""Critic / fact-checker. Pure functions, no I/O.

* Every number in the LLM draft must match a number the writer was given (facts, excerpts,
  derived values, SQL rows, the question). Unmatched numbers => rewrite, then escalate.
* Citation tags must refer to sources that were actually provided.
* Leak tripwire: a number that matches a figure from a locked (unpurchased) report and is not
  otherwise supported blocks the answer.
* Confidence is a transparent, rule-based score with human-readable reasons.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain import Chunk, Fact

TAG_GROUP_RE = re.compile(r"\[((?:[FCDQ]\d+)(?:\s*[,;]\s*[FCDQ]\d+)*)\]")
TAG_RE = re.compile(r"[FCDQ]\d+")
ID_RE = re.compile(r"\b[RC]-\d+\b")
NUM_RE = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])\d+(?:\.\d+)?")
SMALL_INT_MAX = 12


def strip_refs(text: str) -> str:
    return ID_RE.sub(" ", TAG_GROUP_RE.sub(" ", text))


def extract_numbers(text: str) -> list[float]:
    out = []
    for tok in NUM_RE.findall(strip_refs(text)):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            continue
    return out


def extract_tags(text: str) -> list[str]:
    tags: list[str] = []
    for group in TAG_GROUP_RE.findall(text):
        for t in TAG_RE.findall(group):
            if t not in tags:
                tags.append(t)
    return tags


def _variants(v: float) -> set[float]:
    return {v, round(v, 2), round(v, 1), round(v, 0)}


def allowed_numbers(*, question: str, history: list[str], facts: list[Fact], chunks: list[Chunk],
                    derived: list[dict], sql_rows: list[dict], extra_texts: list[str] | None = None) -> set[float]:
    """Every number the writer was legitimately shown. `extra_texts` = catalogue metadata in the prompt."""
    allowed: set[float] = set()
    for text in [question, *history, *(c.text for c in chunks), *(extra_texts or [])]:
        allowed.update(extract_numbers(text))
    allowed.update(float(c.page) for c in chunks)
    for f in facts:
        allowed.update(_variants(f.value))
        allowed.update({float(f.period_start), float(f.period_end), float(f.page)})
        if f.unit == "PCT":
            allowed.update(_variants(f.value / 100))
            allowed.add(round(1 + f.value / 100, 4))
    for d in derived:
        allowed.update(_variants(d["value"]))
        for alt in d.get("alternatives", []):
            allowed.update(_variants(alt["value"]))
        for text in [d["formula"], d["label"], *d.get("assumptions", []), d.get("base_year_ambiguity") or ""]:
            allowed.update(extract_numbers(text))
    for row in sql_rows:
        for v in row.values():
            if isinstance(v, (int, float)):
                allowed.update(_variants(float(v)))
            elif isinstance(v, str):
                allowed.update(extract_numbers(v))
    return allowed


def _supported(n: float, allowed: set[float]) -> bool:
    if n.is_integer() and 0 <= n <= SMALL_INT_MAX:
        return True
    return any(abs(n - a) <= max(0.006, 0.002 * abs(a)) for a in allowed)


@dataclass
class CriticReport:
    unsupported_numbers: list[float] = field(default_factory=list)
    leaked_numbers: list[float] = field(default_factory=list)
    invalid_tags: list[str] = field(default_factory=list)
    tags_used: list[str] = field(default_factory=list)
    uncited_sentences: int = 0
    insufficient: bool = False

    @property
    def ok(self) -> bool:
        return not (self.unsupported_numbers or self.leaked_numbers or self.invalid_tags)

    def as_dict(self) -> dict:
        return {
            "unsupported_numbers": self.unsupported_numbers,
            "leaked_numbers": self.leaked_numbers,
            "invalid_tags": self.invalid_tags,
            "tags_used": self.tags_used,
            "uncited_sentences": self.uncited_sentences,
            "insufficient": self.insufficient,
        }


def check_draft(draft: str, *, allowed: set[float], valid_tags: set[str], locked_values: list[float]) -> CriticReport:
    rep = CriticReport()
    rep.insufficient = draft.strip().upper().startswith("INSUFFICIENT_EVIDENCE")
    rep.tags_used = extract_tags(draft)
    rep.invalid_tags = [t for t in rep.tags_used if t not in valid_tags]
    for n in extract_numbers(draft):
        if _supported(n, allowed):
            continue
        if any(abs(n - lv) <= max(0.006, 0.002 * abs(lv)) for lv in locked_values):
            rep.leaked_numbers.append(n)
        else:
            rep.unsupported_numbers.append(n)
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", draft):
        nums = [n for n in extract_numbers(sentence) if not (n.is_integer() and (n <= SMALL_INT_MAX or 1990 <= n <= 2100))]
        if nums and not TAG_GROUP_RE.search(sentence):
            rep.uncited_sentences += 1
    return rep


def score_confidence(*, route: str, critic: CriticReport | None, facts: list[Fact], chunks: list[Chunk],
                     conflicts: list[dict], derived: list[dict], sql_ok: bool | None,
                     llm_degraded: bool, locked_count: int) -> tuple[float, list[str]]:
    score, reasons = 0.9, []
    if route == "aggregate":
        if not sql_ok:
            score, reasons = 0.3, ["SQL tool returned no usable result"]
        else:
            reasons.append("Answer computed by a validated read-only SQL query")
    else:
        if not facts and not chunks:
            score = 0.2
            reasons.append("No relevant material in the client's entitled reports")
        elif not facts:
            best = max((c.score for c in chunks), default=0)
            if best < 0.55:
                score -= 0.3
                reasons.append(f"Weak retrieval match (best similarity {best:.2f})")
            else:
                reasons.append("Answer based on report excerpts (no structured figures)")
        else:
            reasons.append("Figures come from structured report data with page citations")
    if conflicts:
        score -= 0.1
        reasons.append("Sources disagree; both values shown with scope")
    if derived:
        score -= 0.1
        reasons.append("Includes a derived estimate (calculated, not quoted)")
        if all(d.get("extrapolated_years", 0) > 0 for d in derived):
            score -= 0.3
            reasons.append("Projection extends beyond every source's forecast window")
    if locked_count:
        score -= 0.05
        reasons.append("Relevant reports exist outside the client's subscription")
    if llm_degraded:
        score -= 0.1
        reasons.append("LLM unavailable; answer assembled from templates")
    if critic is not None:
        if critic.insufficient:
            score = min(score, 0.3)
            reasons.append("Writer found the material insufficient to answer")
        if critic.unsupported_numbers:
            score = min(score, 0.3)
            reasons.append(f"Draft contained numbers not found in sources: {critic.unsupported_numbers}")
        if critic.leaked_numbers:
            score = 0.0
            reasons.append("Draft matched figures from unpurchased reports - blocked")
        if critic.invalid_tags:
            score -= 0.15
            reasons.append(f"Invalid citation tags: {critic.invalid_tags}")
        if critic.uncited_sentences:
            score -= 0.05 * min(critic.uncited_sentences, 3)
            reasons.append(f"{critic.uncited_sentences} sentence(s) with numbers lack a citation tag")
    return round(max(0.0, min(1.0, score)), 2), reasons
