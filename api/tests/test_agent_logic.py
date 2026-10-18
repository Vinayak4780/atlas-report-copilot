from app.agent.critic import allowed_numbers, check_draft, extract_numbers, extract_tags, score_confidence
from app.agent.routing import contested_markets, detect_markets, heuristic_route, mentioned_reports, metric_focus


class TestCritic:
    def test_numbers_ignore_tags_and_ids(self):
        assert extract_numbers("R-101 says USD 4.21 B [F1] and 11.2% [F2, F3]") == [4.21, 11.2]

    def test_tags(self):
        assert extract_tags("a [F1] b [C2, D1] c [Q1]") == ["F1", "C2", "D1", "Q1"]

    def test_average_is_caught(self, water_facts):
        allowed = allowed_numbers(question="size in 2024?", history=[], facts=water_facts, chunks=[], derived=[],
                                  sql_rows=[])
        rep = check_draft("The market is about USD 4.04 B [F1].", allowed=allowed, valid_tags={"F1"},
                          locked_values=[])
        assert rep.unsupported_numbers == [4.04]
        assert not rep.ok

    def test_supported_draft_passes(self, water_facts):
        allowed = allowed_numbers(question="", history=[], facts=water_facts, chunks=[], derived=[], sql_rows=[])
        draft = "R-101 reports USD 4.21 B for 2024 [F1]; R-102 reports USD 3.87 B (hardware only) [F4]."
        rep = check_draft(draft, allowed=allowed, valid_tags={"F1", "F4"}, locked_values=[])
        assert rep.ok and rep.uncited_sentences == 0

    def test_leak_tripwire(self, water_facts):
        r102_only = [f for f in water_facts if f.report_id == "R-102"]
        allowed = allowed_numbers(question="", history=[], facts=r102_only, chunks=[], derived=[], sql_rows=[])
        rep = check_draft("R-101 says 4.21 [F4].", allowed=allowed, valid_tags={"F4"}, locked_values=[4.21, 11.2])
        assert rep.leaked_numbers == [4.21]

    def test_invalid_tag(self):
        rep = check_draft("Fine [F9].", allowed=set(), valid_tags={"F1"}, locked_values=[])
        assert rep.invalid_tags == ["F9"]

    def test_confidence_drops_below_threshold_on_unsupported(self, water_facts):
        rep = check_draft("About 4.04 [F1].", allowed={4.21}, valid_tags={"F1"}, locked_values=[])
        score, reasons = score_confidence(route="factual", critic=rep, facts=water_facts, chunks=[], conflicts=[],
                                          derived=[], sql_ok=None, llm_degraded=False, locked_count=0)
        assert score < 0.6 and any("not found" in r for r in reasons)


class TestRouting:
    def test_heuristic_routes(self):
        assert heuristic_route("Which sector has the most reports in your library?", False) == "aggregate"
        assert heuristic_route("What will the APAC smart water meter market be worth in 2030?", True) == "calculation"
        assert heuristic_route("What will the market be worth in 2035?", False) == "calculation"
        assert heuristic_route("Which report should I trust?", False) == "comparison"
        assert heuristic_route("What was the global smart water meter market size in 2024?", True) == "factual"
        assert heuristic_route("What's the weather like in Pune?", False) is None

    def test_markets_and_mentions(self, catalog):
        assert detect_markets("smart water meters in APAC", catalog) == ["Smart water meters"]
        assert detect_markets("water purifiers", catalog) == ["Residential water purifiers"]
        assert mentioned_reports("page 14 of the Aquila Insights report", catalog) == ["R-102"]
        assert mentioned_reports("what does r-101 say", catalog) == ["R-101"]

    def test_contested_markets(self, catalog):
        assert contested_markets(catalog, ["R-102", "R-103"]) == ["Smart water meters"]
        assert contested_markets(catalog, ["R-105"]) == []

    def test_metric_focus(self):
        assert metric_focus("global market size in 2024") == {"market_size"}
        assert metric_focus("What share did Asia-Pacific have?") == {"regional_share"}
