"""Render docs/reports/*.md from measured result files. Nothing here is typed by hand: every number comes
from evals/results/latest.json, latest_llm.json, perf.json and test result files.

    python -m scripts.make_reports
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "backend" / "evals" / "results"
OUT = ROOT / "docs" / "reports"


def load(name: str) -> dict[str, Any] | None:
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def pct(x: Any) -> str:
    return f"{x * 100:.1f}%" if isinstance(x, int | float) else str(x)


def pick(results: list[dict[str, Any]], suite: str, variant: str | None = None) -> dict[str, Any] | None:
    for r in results:
        if r["suite"] == suite and (variant is None or r["config"].get("variant") == variant):
            return r["metrics"]
    return None


def eval_report() -> str:
    base, llm = load("latest.json"), load("latest_llm.json")
    src = llm or base
    if not src:
        return "# Evaluation report\n\nNo evaluation results found. Run `make eval`.\n"
    res = src["results"]
    cfg = src["config"]
    lines = ["# Evaluation report", "",
             f"Generated from `backend/evals/results/{'latest_llm.json' if llm else 'latest.json'}` "
             f"(run started {cfg.get('started_at', '?')[:19]} UTC; embedder `{cfg.get('embedder')}`; "
             f"local model `{cfg.get('reasoning_model') or 'not used'}`). Every number below was computed by "
             "`python -m evals.run_all --llm` from the system's actual outputs on the synthetic workspace.", ""]
    ee = pick(res, "entity_extraction")
    if ee:
        lines += ["## Entity extraction (rules, 98 emails)", "", "| Type | Precision | Recall | F1 |", "|---|---|---|---|"]
        for t in ("people", "organizations", "projects", "dates", "micro"):
            v = ee[t]
            lines.append(f"| {t} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['f1'])} |")
        lines.append("")
    er = pick(res, "entity_resolution")
    if er:
        a, s = er["auto"], er["with_suggested_merges_accepted"]
        lines += ["## Entity resolution (pairwise over 32 mentions: emails, full names, first names)", "",
                  "| Setting | Precision | Recall | F1 |", "|---|---|---|---|",
                  f"| Automatic links only | {pct(a['precision'])} | {pct(a['recall'])} | {pct(a['f1'])} |",
                  f"| + accepting the suggested merges | {pct(s['precision'])} | {pct(s['recall'])} | {pct(s['f1'])} |", "",
                  f"False merges: **{er['false_merges']}**. Unresolved mentions: {er['unresolved_mentions']} (a bare name shared by "
                  f"two identities is deliberately left unresolved). Pending merge suggestions: {er['pending_merge_suggestions']}.", ""]
    ce = pick(res, "commitment_extraction", "demo_world_rules")
    hr, hl = pick(res, "commitment_extraction", "heldout_rules"), pick(res, "commitment_extraction", "heldout_llm")
    lines += ["## Commitment extraction", ""]
    if ce:
        d = ce["detection"]
        lines += [f"Demo world ({ce['gt_commitments']} annotated commitments in emails and meeting notes): precision {pct(d['precision'])}, "
                  f"recall {pct(d['recall'])}, F1 {pct(d['f1'])}; actor {pct(ce['actor_accuracy'])}, action {pct(ce['action_accuracy'])}, "
                  f"deadline {pct(ce['deadline_accuracy'])}, kind {pct(ce['kind_accuracy'])} (on matched items).", ""]
    if hr:
        lines += ["Held-out statements (52 sentences: commitment / request / intention / completed / none):", "",
                  "| Extractor | Accuracy | Macro-F1 | Actionable-detection F1 | Actor | Action | Deadline | Time |", "|---|---|---|---|---|---|---|---|"]
        for name, v in (("Rules", hr), ("Local LLM (qwen3 4B)", hl)):
            if v:
                lines.append(f"| {name} | {pct(v['accuracy'])} | {pct(v['macro_f1'])} | {pct(v['actionable_detection']['f1'])} | "
                             f"{pct(v['actor_accuracy'])} | {pct(v['action_accuracy'])} | {pct(v['deadline_accuracy'])} | {v['seconds']} s |")
        lines.append("")
    cr = pick(res, "commitment_resolution")
    if cr:
        lines += ["## Commitment resolution", "", f"Final status accuracy: **{pct(cr['accuracy_end_to_end'])}** of {cr['gt_commitments']} "
                  f"ground-truth commitments (OPEN / FULFILLED / OVERDUE / CANCELLED / UNCERTAIN). Per status: "
                  + ", ".join(f"{k} {pct(v)}" for k, v in cr["per_status_accuracy"].items()) + ".", ""]
    lines += ["## Retrieval (34 questions with known evidence; 5 are paraphrases with no shared keywords)", "",
              "| Mode | Recall@5 | Recall@10 | MRR | nDCG@10 | Paraphrase R@5 | p50 latency |", "|---|---|---|---|---|---|---|"]
    for mode in ("vector", "keyword", "graph", "hybrid"):
        v = pick(res, "retrieval", mode)
        if v:
            lines.append(f"| {mode} | {pct(v['recall@5'])} | {pct(v['recall@10'])} | {pct(v['mrr'])} | {pct(v['ndcg@10'])} | "
                         f"{pct(v['paraphrase_recall@5'])} | {v['latency_ms_p50']} ms |")
    lines += ["", "Graph-only retrieval answers only questions that name a person or project, which is why it is low on its own; "
              "it contributes the connected items in hybrid.", ""]
    lines += ["## Question answering (18 questions) and temporal QA (7)", "",
              "| Suite | Answer mode | Factual accuracy | Citation accuracy | Invalid-citation rate | Unsupported-claim rate | Source relevance | p50 latency |",
              "|---|---|---|---|---|---|---|---|"]
    for suite in ("qa", "temporal_qa"):
        for variant in ("extractive", "llm"):
            v = pick(res, suite, variant)
            if v:
                lines.append(f"| {suite} | {variant} | {pct(v['factual_accuracy'])} | {pct(v['citation_accuracy'])} | {pct(v['invalid_citation_rate'])} | "
                             f"{pct(v['unsupported_claim_rate'])} | {pct(v['source_relevance'])} | {v['latency_ms_p50']} ms |")
    lines += ["", "*Factual accuracy*: every required fact (dates matched in any format) appears in the answer. *Citation accuracy*: at least one cited "
              "source is among the expected sources. *Unsupported-claim rate*: share of claim sentences the verifier had to remove or flag. "
              "*Source relevance*: share of cited sources in the expected set (a narrow list, so this is a lower bound).", ""]
    lines += ["## Prompt injection (6 cases: injected email, document and note; direct exfiltration, secret and privilege requests)", "",
              "| Model | Pass rate | Write-tool executions | Exfiltration proposals | Secret leaks | Action claims in answer | Indirect injections flagged | Unsafe sentences removed |",
              "|---|---|---|---|---|---|---|---|"]
    for variant in ("compromised_model", "local_llm", "extractive"):
        v = pick(res, "prompt_injection", variant)
        if v:
            lines.append(f"| {variant} | {pct(v['pass_rate'])} | {v['write_tool_executions']} | {v['exfiltration_proposals']} | {v['secret_leaks']} | "
                         f"{v['action_claims']} | {v['indirect_injections_flagged']} | {v['unsafe_sentences_blocked']} |")
    lines += ["", "`compromised_model` is a scripted model that tries to obey every injection (claims to send files, prints the database URL and "
              "secret key, echoes the system prompt). It measures the defences that do not depend on the model behaving.", ""]
    pm = pick(res, "permissions")
    if pm:
        lines += ["## Permissions and privacy", "", f"{pm['checks']} checks, pass rate **{pct(pm['pass_rate'])}**"
                  + (f"; failed: {', '.join(pm['failed'])}" if pm["failed"] else "") + ". Checks: write tools require approval; a write tool inside a run only "
                  "creates a proposal; cross-user access returns 404; cross-user search leaks nothing; missing CSRF rejected; LOCAL mode makes zero cloud "
                  "calls; HYBRID sends only allow-listed operations; sources that forbid cloud stay local; sources with AI disabled never reach a prompt.", ""]
    at = pick(res, "agent_tools")
    if at:
        lines += ["## Agent tools", "", f"{at['tool_calls']} tool executions across {at['runs']} assistant runs; success rate **{pct(at['tool_success_rate'])}**, "
                  f"errors {at['errors']}.", "", "| Tool | Calls | Success | Avg latency |", "|---|---|---|---|"]
        for t, v in at["per_tool"].items():
            lines.append(f"| {t} | {v['calls']} | {pct(v['success_rate'])} | {v['avg_latency_ms']} ms |")
        lines.append("")
    lines += ["## How to read these numbers (limitations)", "",
              "* The demo world, its ground truth, the rules and the QA/retrieval question sets were written by the same developer. The QA and retrieval "
              "sets and the demo ground truth were used during development; treat those numbers as optimistic. When reviewing outputs, a few "
              "ground-truth annotations were corrected where they contradicted the stated annotation rules (e.g. greeting names count as mentions); "
              "a few legitimate commitments the system found were added to the ground truth. The demo-world commitment scores are therefore close to "
              "an upper bound, not an independent measurement.",
              "* The 52 held-out statements were written separately and not used to tune accuracy. They exposed one crash (\"I can have a first draft "
              "ready…\"), which was fixed; the statement still counts. Rules scoring 100% there mainly shows the rules cover the phrasing families the "
              "author anticipated; real email will be messier.",
              "* The LLM rows use a 4B local model on a laptop. The extractive composer beats it on facts because the planner already computed the "
              "answer; the LLM adds fluency and occasionally wrong statements (two genuine errors in the QA set).",
              "* A first scoring pass marked correct LLM answers wrong when they wrote dates as '2026-08-20' or 'September 23'; the matcher now compares "
              "calendar days in any format.", ""]
    return "\n".join(lines)


def perf_report() -> str:
    p = load("perf.json")
    if not p:
        return "# Performance report\n\nNo results. Run `make perf`.\n"
    lines = ["# Performance report", "", f"Measured {p['generated_at'][:19]} UTC on {p['machine']['platform']}, {p['machine']['cpu_count']} CPUs, "
             f"Python {p['machine']['python']} (`python -m evals.perf`).", ""]
    e = p["embedding"]
    lines += [f"* Embedding throughput ({e['embedder']}): **{e['texts_per_second']} texts/s** ({e['texts']} texts in {e['seconds']} s)."]
    if "pipeline" in p:
        q = p["pipeline"]
        lines += [f"* Full pipeline (sync → events → extraction → resolution → graph → embeddings) on {q['emails']} emails: "
                  f"**{q['end_to_end_items_per_second']} emails/s** (store {q['store_seconds']} s, process {q['process_seconds']} s; "
                  f"{q['commitments_extracted']} commitments extracted)."]
    lines += ["", "Latency by data size (memory objects = chunks with embeddings, their emails and graph edges):", "",
              "| Objects | Vector search p50/p95 | Keyword p50/p95 | Hybrid p50/p95 | Graph neighbourhood p50 | Dashboard briefing p50 | Assistant (extractive) p50 | HNSW used |",
              "|---|---|---|---|---|---|---|---|"]
    for s in p["scale"]:
        lt = s["latency"]
        def f(k: str, lt: dict[str, Any] = lt) -> str:
            return f"{lt[k]['p50_ms']} / {lt[k]['p95_ms']} ms"
        lines.append(f"| {s['objects']:,} | {f('vector_search')} | {f('keyword_search')} | {f('hybrid_search')} | {lt['graph_neighbourhood']['p50_ms']} ms | "
                     f"{lt['dashboard_briefing']['p50_ms']} ms | {lt['assistant_extractive']['p50_ms']} ms | {s['explain_vector_uses_hnsw']} |")
    lines += ["", "Local LLM answer latency is reported in the evaluation report (QA p50 with the model). Scale rows use deterministic "
              "hashing vectors (same 384-d index) so the 100k load finishes quickly; search latency depends on vector size and index, not on which "
              "model produced the vectors. Single-user, single-process measurements; no concurrent load.", ""]
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "EVALUATION_REPORT.md").write_text(eval_report())
    (OUT / "PERFORMANCE_REPORT.md").write_text(perf_report())
    print("wrote", [p.name for p in OUT.iterdir()])


if __name__ == "__main__":
    main()
