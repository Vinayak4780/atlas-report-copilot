"""Plain data types shared by the agent, tools and critic (no I/O here)."""
from dataclasses import dataclass, field

METRIC_LABELS = {
    "market_size": "market size",
    "cagr": "CAGR",
    "regional_share": "regional share",
}


@dataclass(frozen=True)
class Fact:
    """One structured figure from market_metrics, already entitlement-filtered."""

    fid: str
    report_id: str
    title: str
    publisher: str
    published: str
    market: str
    metric: str
    region: str
    period_start: int
    period_end: int
    value: float
    unit: str  # USD_B | PCT
    scope_note: str
    page: int

    @property
    def period(self) -> str:
        if self.period_start == self.period_end:
            return str(self.period_start)
        return f"{self.period_start}-{self.period_end}"

    @property
    def display(self) -> str:
        return format_value(self.value, self.unit)


@dataclass
class Chunk:
    cid: str
    report_id: str
    title: str
    publisher: str
    page: int
    text: str
    score: float
    injection_removed: bool = False


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    calls: list = field(default_factory=list)


def format_value(value: float, unit: str) -> str:
    if unit == "USD_B":
        return f"USD {value:g} B"
    if unit == "PCT":
        return f"{value:g}%"
    return f"{value:g}"
