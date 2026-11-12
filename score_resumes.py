"""Score every base resume and demographic variant against the CTO posting.

Uses the Anthropic-compatible endpoint in .env (ANTHROPIC_ENDPOINT, ANTHROPIC_API_KEY,
ANTHROPIC_MODEL). The system prompt and user-message template are taken verbatim
from scoring_system_prompt.md; nothing else is added. One resume per call, fresh
context, fixed temperature, N samples per resume.

Each run writes to its own folder, named by source and model + start date:
  results/<source>/<model>_<YYYY-MM-DD>/   e.g. results/ARC/gpt-oss-120b_2026-11-12/
The source (ARC, anthropic, ollama) is inferred from ANTHROPIC_ENDPOINT; override with
--source. The folder holds scores.jsonl (checkpoint), scores.json (combined output),
isolation.json and run.log.

Every call is appended to the JSONL checkpoint, so an interrupted run resumes where it
stopped: rerunning on the same day reuses today's folder; on a later day pass
--run-dir to resume an older one.

Usage:
  python3 score_resumes.py                       # full run: 30 baselines + 810 variants x 3 samples
  python3 score_resumes.py --limit 5 --samples 1 --run-dir results/smoke   # smoke test
  python3 score_resumes.py --tier low --samples 1
  python3 score_resumes.py --run-dir results/ARC/gpt-oss-120b_2026-11-12   # resume a run
  python3 score_resumes.py --combine-only        # rebuild scores.json (latest run for this model)
"""

import argparse
import json
import os
import random
import re
import string
import sys
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
CV = ROOT / "cv"
POSTING = ROOT / "cto_job_listing.qmd"
PROMPT_MD = ROOT / "scoring_system_prompt.md"
MANIFEST = CV / "variants_manifest.json"
RESULTS = ROOT / "results"
TIERS = ["high", "medium", "low"]


# ---------- inputs ----------

def load_prompt():
    text = PROMPT_MD.read_text()
    system = re.search(r"## System Prompt\s*```text\n(.*?)```", text, re.S).group(1).strip()
    template = re.search(r"## User Message Template\s*```text\n(.*?)```", text, re.S).group(1).strip()
    return system, template


def load_posting():
    text = POSTING.read_text()
    fm = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    body = text[fm.end():].strip() if fm else text.strip()
    title = re.search(r'^title:\s*"?(.*?)"?\s*$', fm.group(1), re.M).group(1) if fm else ""
    sub = re.search(r'^subtitle:\s*"?(.*?)"?\s*$', fm.group(1), re.M) if fm else None
    head = f"# {title}\n{sub.group(1)}\n\n" if sub else (f"# {title}\n\n" if title else "")
    return head + body


def build_items():
    """One item per resume to score: the name-free baseline and each variant."""
    manifest = json.loads(MANIFEST.read_text())
    by_base = {}
    for m in manifest:
        by_base.setdefault(m["base"], []).append(m)
    items = []
    for tier in TIERS:
        for base in sorted((CV / tier).glob("*.md")):
            bkey = str(base.relative_to(ROOT))
            rid = f"{tier}/{base.name[:2]}"
            items.append({
                "item_id": f"{rid}|baseline", "file": bkey, "base_file": bkey, "resume_id": rid,
                "tier": tier, "cohort": "baseline", "is_baseline": True,
                "race": None, "gender": None, "age_band": None, "age": None,
                "name": None, "pronouns": None, "home": None, "bs_year": None, "earlier_career": None,
            })
            for m in by_base.get(bkey, []):
                cohort = f"race={m['race']}|gender={m['gender']}|age={m['age_band']}"
                items.append({
                    "item_id": f"{rid}|{cohort}", "file": m["file"], "base_file": bkey, "resume_id": rid,
                    "tier": tier, "cohort": cohort, "is_baseline": False,
                    "race": m["race"], "gender": m["gender"], "age_band": m["age_band"], "age": m["age"],
                    "name": m["name"], "pronouns": m["pronouns"], "home": m["home"],
                    "bs_year": m["bs_year"], "earlier_career": m["earlier_career"],
                })
    return items


# ---------- model call ----------

def endpoint_config():
    load_dotenv(ROOT / ".env")
    ep = os.environ["ANTHROPIC_ENDPOINT"].strip().rstrip("/")
    base = ep
    for suffix in ("/messages", "/v1"):  # the SDK appends /v1/messages itself
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    # Ollama needs no key, but the SDK refuses to send a request without one.
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or "no-key"
    return {"base_url": base, "api_key": key}, os.environ["ANTHROPIC_MODEL"].strip(), ep


ARC_MAX_WORKERS = 3


def infer_source(endpoint):
    e = endpoint.lower()
    if "arc.vt.edu" in e:
        return "ARC"
    if "anthropic.com" in e:
        return "anthropic"
    if ":11434" in e or "ollama" in e:
        return "ollama"
    raise SystemExit(f"Cannot infer the source from ANTHROPIC_ENDPOINT={endpoint!r}; pass --source.")


def slug(model):
    """Folder-safe model name: 'qwen3.8:27b' -> 'qwen3.8-27b'."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")


def resolve_run_dir(args, model, endpoint, for_combine=False):
    if args.run_dir:
        d = Path(args.run_dir)
        return d if d.is_absolute() else (Path.cwd() / d).resolve()
    source = args.source or infer_source(endpoint)
    parent = RESULTS / source
    prefix = f"{slug(model)}_"
    if for_combine:  # latest existing run for this model
        runs = sorted(p for p in parent.glob(f"{prefix}*") if (p / "scores.jsonl").exists())
        if not runs:
            raise SystemExit(f"No runs for {model} under {parent}; pass --run-dir.")
        return runs[-1]
    today = datetime.now().strftime("%Y-%m-%d")
    d = parent / f"{prefix}{today}"
    older = [p for p in sorted(parent.glob(f"{prefix}*")) if p != d and (p / "scores.jsonl").exists()]
    if older and not d.exists():
        print(f"note: earlier run(s) for this model exist ({', '.join(p.name for p in older)}). "
              f"Starting a new run in {d.name}; use --run-dir to resume one instead.", flush=True)
    return d


class Tee:
    """Mirror stdout into run.log."""
    def __init__(self, path):
        self.f = path.open("a")
        self.out = sys.stdout

    def write(self, s):
        self.out.write(s)
        self.f.write(s)
        self.f.flush()

    def flush(self):
        self.out.flush()


def call_clean(cfg, model, system, user_msg, temperature, max_tokens):
    """One stateless request: a brand-new client (no reused HTTP connection or session),
    the fixed system prompt, and exactly one user message. No history, no caching,
    no metadata or conversation IDs are sent."""
    messages = [{"role": "user", "content": user_msg}]
    assert len(messages) == 1 and messages[0]["role"] == "user"
    with anthropic.Anthropic(**cfg, timeout=180, max_retries=0) as client:
        return client.messages.create(model=model, system=system, max_tokens=max_tokens,
                                      temperature=temperature, messages=messages)


def check_isolation(cfg, model):
    """Plant a random word in one call, then ask for it in a separate call. If the second
    call can recall it, the endpoint is carrying state between requests."""
    word = "".join(random.choice(string.ascii_uppercase) for _ in range(10))
    call_clean(cfg, model, "You are a helpful assistant.",
               f"Remember this code word for later: {word}. Reply only with OK.", 0, 1000)
    r = call_clean(cfg, model, "You are a helpful assistant.",
                   "What code word did I ask you to remember earlier? If you were not given one "
                   "in this conversation, reply only with NONE.", 0, 1000)
    text = "".join(b.text for b in r.content if b.type == "text")
    leaked = word in text or word in "".join(getattr(b, "thinking", "") or "" for b in r.content)
    return {"passed": not leaked, "planted_word": word, "probe_reply": text.strip()[:200],
            "checked_at": datetime.now(timezone.utc).isoformat()}


def parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        score = int(obj["score"])
        if not 0 <= score <= 100:
            return None
        return score, str(obj.get("rationale", "")).strip()
    except (ValueError, KeyError, TypeError):
        return None


REFUSAL = re.compile(r"\b(I can(?:not|'t)|I'm unable|I am unable|I won't|cannot assist)\b", re.I)


def score_once(cfg, model, system, user_msg, temperature, max_tokens, attempts=5):
    rec = {"timestamp": datetime.now(timezone.utc).isoformat()}
    for a in range(attempts):
        t0 = time.time()
        try:
            r = call_clean(cfg, model, system, user_msg, temperature, max_tokens)
        except (anthropic.RateLimitError, anthropic.APIConnectionError,
                anthropic.APITimeoutError, anthropic.InternalServerError) as e:
            rec["last_error"] = f"{type(e).__name__}: {str(e)[:300]}"
            time.sleep(min(60, 2 ** a * 3))
            continue
        except anthropic.APIStatusError as e:
            rec.update(status="error", error=f"{e.status_code}: {str(e)[:300]}", attempts=a + 1)
            return rec
        text = "".join(b.text for b in r.content if b.type == "text")
        thinking = "".join(getattr(b, "thinking", "") or "" for b in r.content if b.type == "thinking")
        rec.update(model_id=r.model, stop_reason=r.stop_reason, latency_s=round(time.time() - t0, 2),
                   input_tokens=r.usage.input_tokens, output_tokens=r.usage.output_tokens,
                   raw_output=text, reasoning=thinking or None, attempts=a + 1)
        p = parse(text)
        if p:
            rec.update(status="ok", score=p[0], rationale=p[1])
        else:
            rec["status"] = "refusal" if REFUSAL.search(text) else "malformed"
        return rec
    rec.update(status="error", attempts=attempts)
    return rec


# ---------- run ----------

def run(args):
    system, template = load_prompt()
    posting = load_posting()
    cfg, model, endpoint = endpoint_config()
    run_dir = resolve_run_dir(args, model, endpoint)
    run_dir.mkdir(parents=True, exist_ok=True)
    if "arc.vt.edu" in (endpoint or "") and args.workers > ARC_MAX_WORKERS:
        args.workers = ARC_MAX_WORKERS  # ARC allows at most 3 concurrent requests
    sys.stdout = Tee(run_dir / "run.log")
    print(f"=== {datetime.now(timezone.utc).isoformat()}  model={model}  endpoint={endpoint}\n"
          f"run dir: {run_dir.relative_to(ROOT) if run_dir.is_relative_to(ROOT) else run_dir}", flush=True)
    iso = check_isolation(cfg, model)
    print(f"isolation check: {'PASSED' if iso['passed'] else 'FAILED'} (probe reply: {iso['probe_reply']!r})",
          flush=True)
    if not iso["passed"] and not args.ignore_isolation:
        raise SystemExit("Endpoint recalled a word from a previous call; contexts are not clean. "
                         "Aborting (use --ignore-isolation to override).")
    (run_dir / "isolation.json").write_text(json.dumps(iso, indent=2))
    items = build_items()
    if args.tier:
        items = [i for i in items if i["tier"] == args.tier]
    if args.limit:
        items = items[:args.limit]

    ckpt = run_dir / "scores.jsonl"
    done = set()
    if ckpt.exists():
        for line in ckpt.read_text().splitlines():
            r = json.loads(line)
            if r.get("status") in ("ok", "refusal", "malformed"):  # errors get retried
                done.add((r["item_id"], r["sample"]))
    jobs = [(it, s) for it in items for s in range(args.samples) if (it["item_id"], s) not in done]
    print(f"{len(items)} resumes x {args.samples} samples; {len(done)} already done; {len(jobs)} to run "
          f"(model={model}, temperature={args.temperature}, workers={args.workers})", flush=True)

    texts = {}
    lock = threading.Lock()
    counts = {"ok": 0, "other": 0}

    def work(job):
        it, s = job
        if it["file"] not in texts:
            texts[it["file"]] = (ROOT / it["file"]).read_text()
        msg = template.replace("<job_posting>", posting).replace("<resume>", texts[it["file"]])
        rec = score_once(cfg, model, system, msg, args.temperature, args.max_tokens)
        rec.update(item_id=it["item_id"], sample=s, file=it["file"])
        if not args.keep_reasoning:
            rec.pop("reasoning", None)
        with lock:
            with ckpt.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            counts["ok" if rec["status"] == "ok" else "other"] += 1
            n = counts["ok"] + counts["other"]
            if n % 25 == 0 or n == len(jobs):
                print(f"  {n}/{len(jobs)} done ({counts['other']} not ok)", flush=True)
        return rec

    with ThreadPoolExecutor(args.workers) as ex:
        for f in as_completed([ex.submit(work, j) for j in jobs]):
            f.result()

    combine(args, run_dir, items, system, template, model, endpoint)


# ---------- combine ----------

def stats(scores):
    if not scores:
        return {"mean_score": None, "sd_score": None, "min_score": None, "max_score": None}
    return {"mean_score": round(statistics.mean(scores), 2),
            "sd_score": round(statistics.stdev(scores), 2) if len(scores) > 1 else 0.0,
            "min_score": min(scores), "max_score": max(scores)}


def combine(args, run_dir, items=None, system=None, template=None, model=None, endpoint=None):
    ckpt = run_dir / "scores.jsonl"
    prev = run_dir / "scores.json"
    prev_run = json.loads(prev.read_text())["run"] if prev.exists() else {}
    if items is None:
        items = build_items()
        system, template = load_prompt()
        if prev_run.get("model"):  # rebuilding an existing run: keep its own model/endpoint
            model, endpoint = prev_run["model"], prev_run.get("endpoint")
        else:
            _, model, endpoint = endpoint_config()
    recs = {}
    for line in ckpt.read_text().splitlines():
        r = json.loads(line)
        key = (r["item_id"], r["sample"])
        if key not in recs or recs[key].get("status") == "error":  # keep the latest non-error
            recs[key] = r
    by_item = {}
    for (iid, _), r in sorted(recs.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        by_item.setdefault(iid, []).append(r)

    rows = []
    for it in items:
        samples = by_item.get(it["item_id"])
        if not samples:
            continue
        ok = [s["score"] for s in samples if s.get("status") == "ok"]
        row = {**it, **stats(ok), "n_samples": len(samples), "n_ok": len(ok),
               "n_refusal": sum(s["status"] == "refusal" for s in samples),
               "n_malformed": sum(s["status"] == "malformed" for s in samples),
               "n_error": sum(s["status"] == "error" for s in samples),
               "samples": [{k: s.get(k) for k in ("sample", "status", "score", "rationale", "reasoning",
                                                   "raw_output", "model_id", "timestamp", "latency_s",
                                                   "input_tokens", "output_tokens", "stop_reason", "error")
                            if k in s} for s in samples]}
        rows.append(row)

    base_mean = {r["resume_id"]: r["mean_score"] for r in rows if r["is_baseline"]}
    for r in rows:
        b = base_mean.get(r["resume_id"])
        r["baseline_mean_score"] = b
        r["diff_from_baseline"] = (round(r["mean_score"] - b, 2)
                                   if r["mean_score"] is not None and b is not None else None)

    def group(keys):
        out = {}
        for r in rows:
            if r["is_baseline"] or r["diff_from_baseline"] is None:
                continue
            k = "|".join(f"{kk}={r[kk]}" for kk in keys)
            out.setdefault(k, {**{kk: r[kk] for kk in keys}, "diffs": [], "scores": []})
            out[k]["diffs"].append(r["diff_from_baseline"])
            out[k]["scores"].append(r["mean_score"])
        return [{**{kk: v[kk] for kk in keys}, "n_resumes": len(v["diffs"]),
                 "mean_score": round(statistics.mean(v["scores"]), 2),
                 "mean_diff_from_baseline": round(statistics.mean(v["diffs"]), 2)}
                for v in out.values()]

    out = {
        "run": {
            "run_name": run_dir.name,
            "run_dir": str(run_dir.relative_to(ROOT)) if run_dir.is_relative_to(ROOT) else str(run_dir),
            "source": (run_dir.parent.name if run_dir.parent.parent == RESULTS
                       else args.source or prev_run.get("source")),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "endpoint": endpoint,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "samples_per_resume": args.samples,
            "system_prompt_source": str(PROMPT_MD.relative_to(ROOT)),
            "system_prompt": system,
            "user_message_template": template,
            "job_posting_source": str(POSTING.relative_to(ROOT)),
            "variant_manifest": str(MANIFEST.relative_to(ROOT)),
            "context_policy": "one stateless request per call: new client, fixed system prompt, "
                              "exactly one user message, no history or caching",
            "isolation_check": (json.loads(p.read_text())
                                if (p := run_dir / "isolation.json").exists() else None),
            "n_resumes": len(rows),
            "n_calls": sum(r["n_samples"] for r in rows),
            "n_ok": sum(r["n_ok"] for r in rows),
            "n_refusal": sum(r["n_refusal"] for r in rows),
            "n_malformed": sum(r["n_malformed"] for r in rows),
            "n_error": sum(r["n_error"] for r in rows),
        },
        "summary": {
            "by_tier": group(["tier"]),
            "by_race": group(["race"]),
            "by_gender": group(["gender"]),
            "by_age_band": group(["age_band"]),
            "by_tier_race": group(["tier", "race"]),
            "by_tier_gender": group(["tier", "gender"]),
            "by_tier_age_band": group(["tier", "age_band"]),
            "by_cell": group(["race", "gender", "age_band"]),
            "baseline_by_tier": [
                {"tier": t, "n_resumes": len(v), "mean_score": round(statistics.mean(v), 2)}
                for t in TIERS
                if (v := [r["mean_score"] for r in rows
                          if r["is_baseline"] and r["tier"] == t and r["mean_score"] is not None])]
        },
        "results": rows,
    }
    path = run_dir / "scores.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"wrote {path} ({len(rows)} resumes, {out['run']['n_ok']}/{out['run']['n_calls']} calls ok)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", help="output folder (default: results/<source>/<model>_<today>); "
                                     "pass an existing folder to resume or re-combine it")
    ap.add_argument("--source", choices=["ARC", "anthropic", "ollama"],
                    help="override the source inferred from ANTHROPIC_ENDPOINT")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=4000, help="includes the model's thinking tokens")
    ap.add_argument("--workers", type=int, default=8,
                    help=f"concurrent calls (default 8; capped at {ARC_MAX_WORKERS} for the ARC endpoint)")
    ap.add_argument("--tier", choices=TIERS)
    ap.add_argument("--limit", type=int, help="score only the first N resumes (smoke test)")
    ap.add_argument("--keep-reasoning", action=argparse.BooleanOptionalAction, default=True,
                    help="store the model's thinking text as 'reasoning' (default: on)")
    ap.add_argument("--combine-only", action="store_true")
    ap.add_argument("--ignore-isolation", action="store_true",
                    help="continue even if the pre-run context-isolation check fails")
    args = ap.parse_args()
    if args.combine_only:
        _, model, endpoint = endpoint_config()
        run_dir = resolve_run_dir(args, model, endpoint, for_combine=True)
        combine(args, run_dir)
    else:
        run(args)


if __name__ == "__main__":
    main()
