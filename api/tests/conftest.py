import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import Fact  # noqa: E402


def _fact(fid, rid, metric, region, start, end, value, unit, scope, page, market="Smart water meters"):
    return Fact(fid=fid, report_id=rid, title=rid, publisher="CMR" if rid == "R-101" else "Aquila",
                published="2025-03-10", market=market, metric=metric, region=region, period_start=start,
                period_end=end, value=value, unit=unit, scope_note=scope, page=page)


@pytest.fixture
def water_facts():
    """Exactly the Appendix A rows."""
    return [
        _fact("F1", "R-101", "market_size", "Global", 2024, 2024, 4.21, "USD_B",
              "Includes hardware, software and services", 8),
        _fact("F2", "R-101", "cagr", "Global", 2025, 2030, 11.2, "PCT", "Forecast period stated as 2025-2030", 8),
        _fact("F3", "R-101", "regional_share", "APAC", 2024, 2024, 38.0, "PCT", "Share of global market size", 8),
        _fact("F4", "R-102", "market_size", "Global", 2024, 2024, 3.87, "USD_B", "AMR / AMI hardware only", 14),
        _fact("F5", "R-102", "cagr", "Global", 2024, 2029, 9.8, "PCT", "Different forecast window from R-101", 14),
        _fact("F6", "R-102", "regional_share", "APAC", 2024, 2024, 41.0, "PCT", "Share of hardware market", 14),
    ]


@pytest.fixture
def catalog():
    def rep(title, publisher, market, access, keywords):
        return {"title": title, "publisher": publisher, "market": market, "access": access,
                "keywords": keywords, "summary": "", "published": "2025-01-01"}
    water = ["water meter", "water metering", "smart water"]
    return {
        "R-101": rep("Global Smart Water Meter Market 2025", "CMR", "Smart water meters", "paid", water),
        "R-102": rep("Smart Water Metering: Industry Outlook 2024", "Aquila Insights (third party)",
                     "Smart water meters", "public excerpt", water),
        "R-103": rep("Residential Water Purifier Market 2025", "CMR", "Residential water purifiers", "paid",
                     ["water purifier", "purifier"]),
        "R-105": rep("Global EV Charging Infrastructure Market 2025", "CMR", "EV charging infrastructure", "paid",
                     ["ev charging", "charging infrastructure"]),
    }
