# Ingest runs (2026-11-14)

Embedding: Gemini `gemini-embedding-001`, 768 dims, free tier. The free tier allows 100 embed requests per minute and 1,000 per day per project, and each text in a batch counts as one request. Ingest was therefore spread over several runs, using API keys from several of the student's Google projects. Every run resumed from the chunks already stored (content-hash check), so nothing was embedded twice into the store.

| Run log | Index A stored | Index B stored | Notes |
|---|---|---|---|
| ingest_run1.txt (2nd key) | 0 → 800 | – | stopped at the daily quota; an earlier attempt with the 1st key had stored nothing |
| ingest_run2.txt (3rd key) | 800 → 1700 | – | stopped at the daily quota |
| ingest_run3.txt (4th key) | 1700 → 2001 (301 in 241.7 s) | 0 → 600 | stopped at the daily quota |
| ingest_run4.txt (5th key) | skipped 2001 | – | key's project had no quota left |
| ingest_run5.txt (6th key) | skipped 2001 | 600 → 1495 (895 in 544.5 s) | ingest complete |
| run_benchmark.txt | skipped 2001 (0 embedded) | skipped 1495 (0 embedded) | re-run check: rows = chunks, no duplicates |

- Throughput was set by the quota throttle (about 100 chunks/min), not by compute, so wall-clock embedding time is not comparable between A and B. The fair resource comparison is chunk count: A 2001 vs B 1495 embedding calls, about 25% fewer for B.
- Cost: USD 0 (free tier; the API reports no token usage).
- About 100 chunks were embedded but not stored when a 200-chunk batch hit the quota mid-way. The batch size was then reduced to 100.
