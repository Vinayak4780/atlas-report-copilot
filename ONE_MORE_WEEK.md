# What I would do with one more week

**1. Make evaluation drive development (days 1-2).** Grow the test set from 30 to about 150 questions using real
analyst emails (anonymised). Add paraphrases of every trap ("the APAC number for 2030", "is R-101 any good?") and
adversarial variants: injections in other languages, injections split across chunks, Unicode look-alikes, and SQL
requests hidden inside harmless wording. Add an LLM-as-judge pass for answer quality next to the deterministic
checks. Run the suite in CI on every commit, with a regression gate on refusal accuracy and leak checks, which must
stay at 100%.

**2. Real document ingestion (days 2-3).** Use page-aware PDF parsing (pypdf, then a layout model for tables) and a
figure-extraction step that fills `market_metrics` automatically. Every extracted figure would carry its page and
bounding box and need analyst approval before going live. Add chart and table extraction from PDFs (multimodal),
because many market numbers only appear in charts.

**3. Better retrieval (day 3).** Proper hybrid search: Qdrant sparse BM25 vectors plus dense vectors, with
reciprocal rank fusion and a cross-encoder re-ranker. Evaluate recall@k on a labelled set, and calibrate the
relevance floor per embedding model instead of using a fixed 0.58.

**4. Calibrated confidence (day 4).** The confidence score is currently rule-based and transparent, but not
calibrated. Use the thumbs-up/down data and the analysts' corrections on escalated tickets to fit the threshold so
that a stated 0.8 really means about 80% correct. Track the escalation rate per question type.

**5. Production hardening (day 5).** Langfuse tracing (the node and LLM-call data is already logged in a structured
form). Move the cache to Redis with a semantic cache for paraphrases. Stream responses over server-sent events to
the CI3 page. Replace the demo sign-in with the portal's real session and pass a signed client token instead of a
shared API key. Add per-client rate limits and an analyst UI to work through the escalation queue and send the
answer back into the client's chat. Deploy behind TLS on a VPS with backups for MySQL and Qdrant.

**What I would not do:** add more agents. The current graph is small on purpose, and most of the remaining risk is
in data quality and evaluation coverage, not orchestration.
