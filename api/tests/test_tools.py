import pytest

from app.tools.calculator import detect_region, detect_target_year, implied_cagr, project, project_for_report
from app.tools.conflicts import detect_conflicts


class TestCalculator:
    def test_project(self):
        assert project(100, 10, 2) == pytest.approx(121.0)

    def test_implied_cagr_roundtrip(self):
        assert implied_cagr(100, project(100, 7.5, 6), 6) == pytest.approx(7.5)

    def test_apac_2030_from_r101(self, water_facts):
        d, note = project_for_report(water_facts, "R-101", "APAC", 2030, "D1")
        assert note is None
        # 4.21 x 0.38 x 1.112^6
        assert d["value"] == pytest.approx(4.21 * 0.38 * 1.112 ** 6, abs=0.01)
        assert d["value"] == pytest.approx(3.02, abs=0.01)
        assert d["kind"] == "derived_estimate"
        assert d["extrapolated_years"] == 0
        # base-year ambiguity surfaced with the 5-year alternative
        assert d["base_year_ambiguity"] and "2025" in d["base_year_ambiguity"]
        assert d["alternatives"][0]["value"] == pytest.approx(4.21 * 0.38 * 1.112 ** 5, abs=0.01)
        assert {i["citation_id"] for i in d["inputs"]} == {"F1", "F2", "F3"}
        assert any("share stays" in a for a in d["assumptions"])

    def test_r102_2030_is_flagged_as_extrapolation(self, water_facts):
        d, _ = project_for_report(water_facts, "R-102", "APAC", 2030, "D2")
        assert d["extrapolated_years"] == 1
        assert d["base_year_ambiguity"] is None  # window starts in the base year
        assert any("EXTRAPOLATION" in a for a in d["assumptions"])

    def test_never_mixes_reports(self, water_facts):
        d, _ = project_for_report(water_facts, "R-101", "APAC", 2030, "D1")
        assert all(i["report_id"] == "R-101" for i in d["inputs"])

    def test_detectors(self):
        assert detect_target_year("worth in 2030?") == 2030
        assert detect_target_year("size in 2024") is None
        assert detect_region("the APAC market") == "APAC"
        assert detect_region("Asia-Pacific share") == "APAC"
        assert detect_region("the global market") == "Global"


class TestConflicts:
    def test_market_size_conflict_shows_both_scopes(self, water_facts):
        conflicts = detect_conflicts(water_facts, {"market_size"})
        assert len(conflicts) == 1
        c = conflicts[0]
        assert {v["report_id"] for v in c["values"]} == {"R-101", "R-102"}
        assert {v["value"] for v in c["values"]} == {4.21, 3.87}
        assert "hardware only" in c["note"] and "not averaged" in c["resolution"]

    def test_all_three_conflicts(self, water_facts):
        kinds = {(c["metric"], c["kind"]) for c in detect_conflicts(water_facts)}
        assert kinds == {("market_size", "value_mismatch"), ("cagr", "different_forecast_window"),
                         ("regional_share", "value_mismatch")}

    def test_single_report_has_no_conflict(self, water_facts):
        assert detect_conflicts([f for f in water_facts if f.report_id == "R-102"]) == []
