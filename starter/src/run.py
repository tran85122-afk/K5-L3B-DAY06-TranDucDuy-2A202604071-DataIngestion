import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from importlib import metadata as pkg_meta
from pathlib import Path

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import make_embedder
from .evaluation import _norm, evaluate_query, summarize
from .ingestion import load_pdf
from .models import Chunk, DocumentPage
from .store import PgVectorStore, content_hash

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
MANIFEST = ROOT / "data" / "manifest.json"
BENCHMARK = ROOT / "benchmark" / "questions.json"
RESULTS = STARTER / "results"
TOP_K = 3
INGEST_BATCH = 100
MIN_CONTENT_PAGES = 30

INDEXES = {
    "A": {"chunking": "fixed", "size": 500, "overlap": 50},
    "B": {"chunking": "paragraph", "max_size": 800},
}
STRATEGIES = {
    "A": {"index": "A", "use_filter": False},
    "B": {"index": "B", "use_filter": False},
    "C": {"index": "B", "use_filter": True},
}


def load_corpus() -> tuple[list[dict], list[DocumentPage], list[dict]]:
    if not MANIFEST.exists():
        raise SystemExit(f"Missing {MANIFEST}. Create it as described in starter/README.md.")
    documents = json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]
    required = ("source_id", "title", "source_path_or_url", "license_or_permission", "accessed_at", "local_path")
    missing_fields = [f"{d.get('source_id', '?')}: {k}" for d in documents for k in required if not d.get(k)]
    if missing_fields:
        raise SystemExit("Manifest is missing required fields (GUIDE §1):\n  " + "\n  ".join(missing_fields))
    pages, log = [], []
    for doc in documents:
        path = ROOT / doc["local_path"]
        if not path.exists():
            raise SystemExit(f"File not found for {doc['source_id']}: {path}")
        meta = {"title": doc["title"], **doc.get("metadata", {})}
        doc_pages, doc_log = load_pdf(path, doc["source_id"], doc["local_path"], meta, doc.get("header_regex"))
        ranges = doc.get("page_ranges")
        if ranges is not None:
            range_meta = {page: r.get("metadata", {}) for r in ranges for page in range(r["first"], r["last"] + 1)}
            for page in sorted(set(range_meta) - {p.page for p in doc_pages}):
                log.append({"document_id": doc["source_id"], "page": page, "status": "listed_but_empty",
                            "detail": "content page has no extractable text (see error/empty entry)"})
            doc_pages = [p for p in doc_pages if p.page in range_meta]
            for p in doc_pages:
                p.metadata.update(range_meta[p.page])
        pages.extend(doc_pages)
        log.extend(doc_log)
    if len(pages) < MIN_CONTENT_PAGES:
        raise SystemExit(f"Only {len(pages)} content pages with text; need >= {MIN_CONTENT_PAGES}.")
    return documents, pages, log


def load_questions(pages: list[DocumentPage]) -> list[dict]:
    if not BENCHMARK.exists():
        raise SystemExit(f"Missing {BENCHMARK}. See starter/README.md for the format.")
    questions = json.loads(BENCHMARK.read_text(encoding="utf-8"))
    page_text = {(p.document_id, p.page): _norm(p.text) for p in pages}
    ids = [q["id"] for q in questions]
    problems = [f"duplicate id {i}" for i in set(ids) if ids.count(i) > 1]
    for q in questions:
        if q.get("split") not in ("dev", "test"):
            problems.append(f"{q['id']}: split must be dev or test")
        golds = [q, *q.get("alternatives", [])]
        if not any(_norm(g["evidence_quote"]) in page_text.get((g["gold_source_id"], int(g["gold_page"])), "")
                   for g in golds):
            problems.append(f"{q['id']}: evidence_quote not found on its gold page after normalization")
    dev = [q for q in questions if q.get("split") == "dev"]
    test = [q for q in questions if q.get("split") == "test"]
    with_filter = [q for q in questions if q.get("filter")]
    if len(dev) < 15 or len(test) < 5:
        problems.append(f"need >= 15 dev / 5 test, got {len(dev)} / {len(test)}")
    if len(with_filter) < 3 or not any(q["split"] == "test" for q in with_filter):
        problems.append("need >= 3 questions with a filter, at least 1 in test")
    if problems:
        raise SystemExit("Benchmark problems:\n  " + "\n  ".join(problems))
    return questions


def build_chunks(pages: list[DocumentPage], cfg: dict) -> list[Chunk]:
    chunks = []
    for page in pages:
        if cfg["chunking"] == "fixed":
            chunks += fixed_size(page, cfg["size"], cfg["overlap"])
        else:
            chunks += by_paragraph(page, cfg["max_size"])
    return [c for c in chunks if c.text]


def ingest(store: PgVectorStore, embedder, name: str, chunks: list[Chunk]) -> dict:
    started = time.perf_counter()
    known = store.existing_hashes(name, embedder.model_name)
    todo = [c for c in chunks if known.get(c.chunk_id) != content_hash(c.text)]
    tokens_before = getattr(embedder, "total_tokens", 0)
    keep_ids = {c.chunk_id for c in chunks}
    embed_seconds, deleted = 0.0, 0
    for i in range(0, max(len(todo), 1), INGEST_BATCH):
        batch = todo[i:i + INGEST_BATCH]
        embed_start = time.perf_counter()
        vectors = embedder.embed_documents([c.text for c in batch]) if batch else []
        embed_seconds += time.perf_counter() - embed_start
        deleted += store.upsert(name, batch, vectors, embedder.model_name, keep_ids=keep_ids)
        if batch:
            print(f"  index {name}: {i + len(batch)}/{len(todo)} chunks embedded", flush=True)
    tokens = getattr(embedder, "total_tokens", 0) - tokens_before
    rows, distinct = store.count(name)
    if rows != len(chunks) or distinct != rows:
        raise RuntimeError(f"Index {name}: {rows} rows / {distinct} distinct, expected {len(chunks)}")
    lengths = [len(c.text) for c in chunks]
    return {
        "chunks": len(chunks), "embedded_this_run": len(todo), "unchanged_skipped": len(chunks) - len(todo),
        "deleted_obsolete": deleted, "rows_in_store": rows,
        "len_min": min(lengths), "len_mean": round(statistics.mean(lengths), 1),
        "len_median": statistics.median(lengths), "len_max": max(lengths), "total_chars": sum(lengths),
        "embed_seconds": round(embed_seconds, 2), "ingest_seconds": round(time.perf_counter() - started, 2),
        "embedding_tokens_this_run": tokens, "cost_usd_this_run": cost_usd(embedder, tokens),
    }


def cost_usd(embedder, tokens: int):
    if type(embedder).__name__ == "LocalEmbedder":
        return 0.0
    if not hasattr(embedder, "total_tokens"):
        return "API reports no token usage; check provider billing (free tier = 0)"
    price = os.getenv("EMBEDDING_PRICE_PER_1M_TOKENS", "").strip()
    return round(tokens * float(price) / 1_000_000, 6) if price else "set EMBEDDING_PRICE_PER_1M_TOKENS"


def run_benchmark(store: PgVectorStore, embedder, questions: list[dict]) -> list[dict]:
    traces = []
    for q in questions:
        qvec = embedder.embed_query(q["question"])
        for name, cfg in STRATEGIES.items():
            applied = q.get("filter") if cfg["use_filter"] else None
            hits = store.search(cfg["index"], qvec, TOP_K, applied)
            traces.append({
                "strategy": name, "index": cfg["index"], "split": q["split"], "question_id": q["id"],
                "question": q["question"], "type": q.get("type"), "filter_requested": q.get("filter"),
                "filter_applied": applied, "expected_answer": q["expected_answer"],
                "gold_source_id": q["gold_source_id"], "gold_page": q["gold_page"],
                "evidence_quote": q["evidence_quote"], "alternatives": q.get("alternatives", []),
                "hits": hits, "eval": evaluate_query(q, hits),
            })
    return traces


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def write_audit_sheets(traces: list[dict], pages: list[DocumentPage], chunks_by_index: dict) -> None:
    test = [t for t in traces if t["split"] == "test"]
    write_csv(RESULTS / "audit_grounding.csv",
              ["strategy", "question_id", "question", "expected_answer", "top3_chunk_ids", "top3_text",
               "evidence_hit_at_3_auto", "grounding_score_0_2", "reason"],
              [[t["strategy"], t["question_id"], t["question"], t["expected_answer"],
                " | ".join(h["chunk_id"] for h in t["hits"]),
                "\n---\n".join(h["text"] for h in t["hits"]), t["eval"]["hit_at_3"], "", ""] for t in test])
    write_csv(RESULTS / "audit_metadata.csv",
              ["strategy", "question_id", "rank", "chunk_id", "source", "page", "metadata",
               "filter_requested", "source_ok", "page_ok", "filter_field_ok", "error_note"],
              [[t["strategy"], t["question_id"], rank, h["chunk_id"], h["source"], h["page"],
                json.dumps(h["metadata"], ensure_ascii=False), json.dumps(t["filter_requested"] or {}), "", "", "", ""]
               for t in test for rank, h in enumerate(t["hits"], start=1)])
    sample = sorted(pages, key=lambda p: (p.document_id, p.page))[:10]
    rows = []
    for page in sample:
        pos = len(page.text) // 2
        for index, chunks in chunks_by_index.items():
            on_page = [c for c in chunks if c.document_id == page.document_id and c.page == page.page]
            chunk = max((c for c in on_page if c.metadata["char_start"] <= pos),
                        key=lambda c: c.metadata["char_start"], default=on_page[0])
            strategies = "+".join(s for s, cfg in STRATEGIES.items() if cfg["index"] == index)
            rows.append([f"{page.document_id}:p{page.page}@{pos}", strategies, chunk.chunk_id, chunk.text, "", ""])
    write_csv(RESULTS / "audit_coherence.csv",
              ["position", "strategies", "chunk_id", "chunk_text", "coherence_score_0_2", "reason"], rows)


def versions() -> dict:
    out = {}
    for pkg in ("psycopg", "pypdf", "python-dotenv", "sentence-transformers"):
        try:
            out[pkg] = pkg_meta.version(pkg)
        except pkg_meta.PackageNotFoundError:
            pass
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(STARTER / ".env", override=True)
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL missing: copy .env.example to .env")
    RESULTS.mkdir(exist_ok=True)

    documents, pages, page_log = load_corpus()
    print(f"Corpus: {len(documents)} documents, {len(pages)} content pages, {len(page_log)} page issues")
    questions = load_questions(pages) if BENCHMARK.exists() else None
    if questions:
        print(f"Benchmark: {len(questions)} questions verified")
    write_csv(RESULTS / "corpus_pages.csv", ["document_id", "page", "chars"],
              [[p.document_id, p.page, len(p.text)] for p in pages])
    (RESULTS / "ingest_log.json").write_text(json.dumps(page_log, ensure_ascii=False, indent=2), encoding="utf-8")

    embedder = make_embedder()
    print(f"Embedder: {embedder.model_name} ({embedder.dimensions} dims)")
    store = PgVectorStore(url, embedder.dimensions)
    store.create_schema()

    chunks_by_index, stats = {}, {}
    for name, cfg in INDEXES.items():
        chunks_by_index[name] = build_chunks(pages, cfg)
        stats[name] = ingest(store, embedder, name, chunks_by_index[name])
        print(f"Index {name}: {stats[name]}")
    (RESULTS / "chunk_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    if questions is None:
        write_config(embedder)
        print(f"\nIngest done. Add {BENCHMARK} and run again to benchmark (unchanged chunks are not re-embedded).")
        return

    traces = run_benchmark(store, embedder, questions)
    summary = summarize(traces)
    write_config(embedder)
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (RESULTS / "traces.jsonl").open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    write_audit_sheets(traces, pages, chunks_by_index)

    print("\nStrategy  Split  Hit@1      Hit@3      Filter compliance")
    for name, splits in summary.items():
        for split in ("dev", "test"):
            b = splits.get(split)
            if b:
                print(f"{name:<9} {split:<6} {b['hit1']:>2}/{b['n']:<2} ({b['hit1_rate']:.2f})  "
                      f"{b['hit3']:>2}/{b['n']:<2} ({b['hit3_rate']:.2f})  {b['filter_compliance']}")
    print(f"\nResults written to {RESULTS}. Fill in the manual audit CSVs by hand.")


def write_config(embedder) -> None:
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (RESULTS / "config.json").write_text(json.dumps({
        "run_at_utc": run_at, "embedding_provider": os.getenv("EMBEDDING_PROVIDER", "gemini"),
        "embedding_tokens_total_incl_queries": getattr(embedder, "total_tokens", 0),
        "cost_usd_total_incl_queries": cost_usd(embedder, getattr(embedder, "total_tokens", 0)),
        "embedding_model": embedder.model_name, "dimensions": embedder.dimensions,
        "vector_store": "PostgreSQL + pgvector, cosine distance (<=>), exact search (no ANN index)",
        "top_k": TOP_K, "indexes": INDEXES, "strategies": STRATEGIES, "versions": versions(),
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
