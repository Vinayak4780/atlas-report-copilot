"""Evaluation harness. Calls the real running API (nothing mocked) and scores each answer.

Usage (inside the api container):
    docker compose exec api python eval/run_eval.py
or from the host (Python 3.9+, stdlib only):
    ATLAS_API_URL=http://localhost:8000 ATLAS_API_KEY=... python api/eval/run_eval.py

Writes eval/results/results.json and eval/results/report.md.
Metrics
  correctness        - share of questions where every expectation holds
  citation accuracy  - for answered questions with expected sources: cited reports are all expected (precision)
                       and every expected report is cited (recall); forbidden reports never cited
  refusal accuracy   - refused when it should, answered when it should
  conflict detection - precision / recall of conflicts[] against expected conflicts
  leak checks        - must_not_contain strings never appear
"""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = os.environ.get("ATLAS_API_URL", "http://127.0.0.1:8000").rstrip("/")
KEY = os.environ.get("ATLAS_API_KEY", "")
PAUSE_S = float(os.environ.get("EVAL_PAUSE_S", "2"))  # stay under Groq free-tier rate limits
REFUSAL_ROUTES = {"unsafe", "out_of_scope", "entitlement_denied"}


def call(client_id: str, question: str) -> tuple[dict | None, str | None, float]:
    body = json.dumps({"client_id": client_id, "question": question}).encode()
    req = urllib.request.Request(f"{API}/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-API-Key": KEY})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read()), None, time.monotonic() - t0
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read()[:200]!r}", time.monotonic() - t0
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}", time.monotonic() - t0


def score(item: dict, resp: dict | None, error: str | None) -> dict:
    exp = item["expect"]
    checks: dict[str, bool] = {}
    notes: list[str] = []
    if resp is None:
        return {"checks": {"api_ok": False}, "passed": False, "notes": [error or "no response"], "refused": None,
                "cited": [], "conflict": None}

    answer = resp["answer"]
    refused = resp["route"] in REFUSAL_ROUTES
    cited = sorted({c["report_id"] for c in resp["citations"] if c.get("report_id")})
    has_conflict = bool(resp["conflicts"])

    if "refused" in exp:
        checks["refusal"] = refused == exp["refused"]
    if "escalated" in exp:
        checks["escalation"] = resp["escalated"] == exp["escalated"]
    if "route" in exp:
        checks["route"] = resp["route"] == exp["route"]
    if "conflict" in exp:
        checks["conflict"] = has_conflict == exp["conflict"]
    if "derived" in exp:
        checks["derived"] = bool(resp["derived_values"]) == exp["derived"] and all(
            d["kind"] == "derived_estimate" for d in resp["derived_values"])
    if exp.get("sql"):
        checks["sql"] = bool(resp.get("sql_query"))
    if exp.get("injection"):
        checks["injection_logged"] = resp["injection_detected"]
    for s in exp.get("must_contain", []):
        ok = s.lower() in answer.lower()
        checks[f"contains:{s}"] = ok
    for s in exp.get("must_not_contain", []):
        checks[f"absent:{s}"] = s.lower() not in json.dumps(resp).lower()
    if exp.get("forbidden_citations"):
        checks["no_forbidden_citation"] = not set(cited) & set(exp["forbidden_citations"])
    if exp.get("cited_reports") and not refused and not resp["escalated"]:
        expected = set(exp["cited_reports"])
        checks["citations_recall"] = expected <= set(cited)
        checks["citations_precision"] = set(cited) <= expected
        if not checks["citations_precision"]:
            notes.append(f"unexpected citations: {sorted(set(cited) - expected)}")
    failed = [k for k, v in checks.items() if not v]
    if failed:
        notes.append("failed: " + ", ".join(failed))
    return {"checks": checks, "passed": not failed, "notes": notes, "refused": refused, "cited": cited,
            "conflict": has_conflict}


def pct(n: int, d: int) -> str:
    return f"{(100 * n / d):.0f}% ({n}/{d})" if d else "n/a"


def main() -> int:
    if not KEY:
        print("Set ATLAS_API_KEY", file=sys.stderr)
        return 2
    items = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    results = []
    for item in items:
        resp, error, secs = call(item["client_id"], item["question"])
        sc = score(item, resp, error)
        results.append({**item, "response": resp, "error": error, "seconds": round(secs, 2), **sc})
        status = "PASS" if sc["passed"] else "FAIL"
        print(f"{item['id']} {status} {secs:5.1f}s {item['client_id']} {item['question'][:60]}")
        time.sleep(PAUSE_S)

    n = len(results)
    correct = sum(r["passed"] for r in results)
    ref_items = [r for r in results if "refused" in r["expect"] and r["refused"] is not None]
    ref_ok = sum(r["refused"] == r["expect"]["refused"] for r in ref_items)
    conf_items = [r for r in results if "conflict" in r["expect"] and r["response"]]
    tp = sum(r["conflict"] and r["expect"]["conflict"] for r in conf_items)
    fp = sum(r["conflict"] and not r["expect"]["conflict"] for r in conf_items)
    fn = sum((not r["conflict"]) and r["expect"]["conflict"] for r in conf_items)
    cit_items = [r for r in results if "citations_recall" in r["checks"]]
    cit_ok = sum(r["checks"]["citations_recall"] and r["checks"]["citations_precision"] for r in cit_items)
    leak_checks = [(r["id"], k) for r in results for k, v in r["checks"].items() if k.startswith("absent:")]
    leak_fail = [(i, k) for i, k in leak_checks if not next(r for r in results if r["id"] == i)["checks"][k]]
    lat = [r["seconds"] for r in results if r["response"]]
    costs = [r["response"]["cost_usd"] for r in results if r["response"]]
    esc_items = [r for r in results if "escalated" in r["expect"] and r["response"]]
    esc_ok = sum(r["response"]["escalated"] == r["expect"]["escalated"] for r in esc_items)

    summary = {
        "questions": n,
        "correctness": pct(correct, n),
        "citation_accuracy": pct(cit_ok, len(cit_items)),
        "refusal_accuracy": pct(ref_ok, len(ref_items)),
        "conflict_precision": pct(tp, tp + fp),
        "conflict_recall": pct(tp, tp + fn),
        "escalation_accuracy": pct(esc_ok, len(esc_items)),
        "leak_checks_passed": pct(len(leak_checks) - len(leak_fail), len(leak_checks)),
        "latency_p50_s": round(statistics.median(lat), 2) if lat else None,
        "latency_max_s": round(max(lat), 2) if lat else None,
        "total_cost_usd": round(sum(costs), 5),
    }
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps({"summary": summary, "results": results}, indent=2),
                                          encoding="utf-8")

    lines = ["# Evaluation results", "", f"Run at {time.strftime('%Y-%m-%d %H:%M:%S')} against {API}", "",
             "| Metric | Value |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {v} |" for k, v in summary.items()]
    lines += ["", "| # | Client | Category | Question | Route | Conf. | Esc. | Result | Notes |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        resp = r["response"] or {}
        lines.append(
            f"| {r['id']} | {r['client_id']} | {r['category']} | {r['question'].replace('|', '/')} | "
            f"{resp.get('route', '-')} | {resp.get('confidence', '-')} | {resp.get('escalated', '-')} | "
            f"{'PASS' if r['passed'] else 'FAIL'} | {'; '.join(r['notes']).replace('|', '/')} |")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nWrote {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
