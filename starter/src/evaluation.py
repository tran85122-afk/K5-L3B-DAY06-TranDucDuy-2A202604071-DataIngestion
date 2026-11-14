import re
from typing import Any

from .ingestion import normalize_text


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text)).strip().lower()


def gold_options(question: dict[str, Any]) -> list[dict[str, Any]]:
    main = {k: question[k] for k in ("gold_source_id", "gold_page", "evidence_quote")}
    return [main, *question.get("alternatives", [])]


def is_hit(hit: dict[str, Any], options: list[dict[str, Any]]) -> bool:
    text = _norm(hit["text"])
    return any(hit["document_id"] == o["gold_source_id"] and int(hit["page"]) == int(o["gold_page"])
               and _norm(o["evidence_quote"]) in text for o in options)


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    options = gold_options(question)
    flags = [is_hit(h, options) for h in hits]
    gold_pages = {(o["gold_source_id"], int(o["gold_page"])) for o in options}
    page_found = any((h["document_id"], int(h["page"])) in gold_pages for h in hits)
    filters = question.get("filter") or {}
    if filters:
        compliant = all(all(str(h["metadata"].get(k)) == str(v) for k, v in filters.items()) for h in hits)
    else:
        compliant = None
    note = ""
    if not any(flags) and page_found:
        note = "gold page retrieved but no single chunk holds the full evidence (split or partial)"
    return {
        "hit_at_1": bool(flags[:1] and flags[0]),
        "hit_at_3": any(flags[:3]),
        "hit_flags": flags,
        "gold_page_in_top3": page_found,
        "filter_compliant": compliant,
        "note": note,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for t in traces:
        bucket = summary.setdefault(t["strategy"], {}).setdefault(t["split"], {
            "n": 0, "hit1": 0, "hit3": 0, "filter_questions": 0, "filter_compliant": 0})
        bucket["n"] += 1
        bucket["hit1"] += t["eval"]["hit_at_1"]
        bucket["hit3"] += t["eval"]["hit_at_3"]
        if t["eval"]["filter_compliant"] is not None:
            bucket["filter_questions"] += 1
            bucket["filter_compliant"] += t["eval"]["filter_compliant"]
    for splits in summary.values():
        for b in splits.values():
            b["hit1_rate"] = round(b["hit1"] / b["n"], 4)
            b["hit3_rate"] = round(b["hit3"] / b["n"], 4)
            b["filter_compliance"] = (f"{b['filter_compliant']}/{b['filter_questions']}"
                                      if b["filter_questions"] else "N/A")
    return summary
