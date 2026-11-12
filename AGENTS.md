# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A research project (ADS 5984) auditing bias in LLM-based resume screening. LLMs (VT ARC hosted models, and possibly Anthropic and Grok models) score candidate resumes 0–100 against one fixed job posting. Each resume is scored with no names attached and again in versions that carry demographic cues for race, gender, and age.

## Files

- `prompt.md`: the original study prompt.
- `improved_prompt.md`: the original methodology write-up. It covers fit tiers, a name-free baseline and manipulation check, the scoring protocol, and the analysis plan. **Where it disagrees with the "Current study design" section below, the section below wins.** The variant design changed from one controlled signal per variant to holistic, full-factorial cues.
- `cto_job_listing.qmd`: the fixed job posting. It is the **control document for the whole study**. Do not change its wording unless asked, because any change invalidates comparisons across runs.
- `cto_job_listing.html` / `.pdf` / `cto_job_listing_files/`: rendered output, committed to the repo.
- `prompt_resume.md`: the prompt used to generate the name-free base resumes.
- `prompt_evaluation.md`: the original evaluation prompt. Its one-dimension-at-a-time design is superseded by the full factorial below.
- `scoring_system_prompt.md`: the fixed system prompt for scoring. `run_evaluation.py` extracts the text block under `## System Prompt`.
- `cv/<tier>/NN_resume_<tier>.md`: the base resumes. These are name-free, with 10 per tier for `high`, `medium`, and `low`. They use placeholders such as `<name>`, `<city>`, `<company_N>`, `<university_N>`, and `<year>`.
- `cv/<tier>/race-<race>_gender-<gender>_age-<band>/NN_resume_<tier>.md`: the demographic variants, with 27 folders per tier. They are **generated, so never edit them by hand**. Change the base resume or the cue table and rebuild.
- `demographic_cues.json`: the cue table. It holds names by race × gender × age band, home and employer cities, schools, community lines, interests, the reference year, each resume's career length, and degree-year overrides.
- `make_variants.py`: builds every variant from the base resumes and the cue table. It also writes `cv/variants_manifest.json`, which records each file's name, age, degree years, and earlier-career span.
- `score_resumes.py`: the scoring harness. It scores every base resume (as the baseline) and all variants through the Anthropic-compatible endpoint in `.env` (`ANTHROPIC_ENDPOINT`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`).
  - It uses only the system prompt and user template from `scoring_system_prompt.md`, with nothing added.
  - Only one `ANTHROPIC_ENDPOINT` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` combination is uncommented in `.env` at a time (see `.env.sample`). All of the endpoints (ARC, Ollama on ads1/ads2, Anthropic) speak the Anthropic Messages API.
  - Each run gets its own folder, `results/<source>/<model>_<YYYY-MM-DD>/`. The source (`ARC`, `anthropic`, or `ollama`) is inferred from the endpoint and can be overridden with `--source`. Characters in the model name that are unsafe in a folder name become `-` (for example `qwen3.8:27b` becomes `qwen3.8-27b`). The date is the date the run started.
  - The run folder holds `scores.jsonl`, `scores.json`, `isolation.json`, and `run.log`. `scores.jsonl` is the per-call checkpoint, so an interrupted run resumes where it stopped: a rerun on the same day reuses that day's folder, and `--run-dir` resumes an older one. `scores.json` is the combined input for the dashboard: run metadata (including `source` and `run_dir`), `summary` aggregates, and one row per resume with cohort fields, per-sample scores, rationale, model reasoning, and `diff_from_baseline`.
- `analyze_significance.py`: runs the significance tests on a run folder's `scores.json` and writes `significance.md` and `significance.json` to the same folder.
- `results/ARC/vt-arc-llm_2026-11-11/`: the DeepSeek 4.1 Flash run (served by ARC as `vt-arc-llm`), with the findings report.
- `run_evaluation.py`: an older scorer that calls `opencode run` (tool-less `scorer` agent, `--pure`, empty scratch cwd; model arg `provider/model`, default `vt-arc/vt-arc-llm`) and adds a deductions addendum to the prompt. It is superseded by `score_resumes.py`.
- `run_evaluation_claude.py`: the same older scorer, but it calls `claude -p` (Claude Code CLI, tool-less, no session persistence; model arg is a Claude alias or ID, default `sonnet`) and writes `evaluation_claude.json`.
- `backup/`: earlier prompt and listing drafts. These are superseded and kept only for reference.

## Commands

```bash
python3 make_variants.py               # rebuild all 810 variants + manifest (deletes old variant folders)
python3 score_resumes.py               # score baselines + variants -> results/<source>/<model>_<date>/scores.json (resumable)
python3 score_resumes.py --limit 5 --samples 1 --run-dir results/smoke   # quick smoke test
python3 score_resumes.py --run-dir results/ARC/<model>_<date>           # resume an older run
python3 score_resumes.py --combine-only                          # rebuild scores.json (latest run for the .env model)
python3 analyze_significance.py --run-dir results/ARC/vt-arc-llm_2026-11-11   # significance tests (default: latest run)
quarto render cto_job_listing.qmd      # render posting to html + pdf (Quarto at /opt/quarto/bin/quarto)
```

A full evaluation run makes 840 resumes × 3 samples = 2,520 model calls. Confirm before launching one.

## Current study design

**Base resumes (name-free)**
- The tiers are defined against the posting's required qualifications:
  - high: meets all required qualifications and most preferred ones.
  - medium: clearly short on one or two required qualifications.
  - low: misses several required qualifications.
- Every base resume keeps a "**Work Authorization:** U.S. Citizen" line and a Security Clearance line.
- Do not state gaps outright (for example "has not…", "never…", or "budget owned by…"). A gap should show only through what the resume leaves out.
- Do not include demographic cues: no names, pronouns, real dates, military-service framing, or identity-linked affiliations.
- The Education section must carry a `<year>` slot on degree lines, because the generator fills these to set age.
- Medium-tier gaps are spread across requirements on purpose:
  - leadership years: 01, 04, 07, 08, 09, 10
  - industry years: 06, 09
  - degree field: 03
  - customer relationships: 02, 04, 05, 08

**Demographic variants (full factorial, holistic cues)**
- There are 3 races (White, African American, Middle Eastern), 3 genders (male, female, non-binary), and 3 age bands (37–40, 41–55, 56–80). That makes 27 cells per base resume and 810 files in total.
- Job content (titles, bullets, years of experience, degrees, certifications) must stay identical to the base resume. Cues go only in these slots:
  - name and pronouns in the heading
  - email and LinkedIn, derived from the name
  - home city and employer cities
  - race-linked schools of comparable standing
  - degree years
  - an "Earlier Career" line when the gap from schooling to the first listed role is at least 4 years
  - a closing "Community and Interests" section with one race line, one gender line, and interests. The White and male cells get neutral community lines of similar length.
- Ages use a reference year of 2026: 38 (raised to as much as 40 so that careers of up to 19 years fit), 48, and 65. B.S. graduation is at age 22, or 21 if the timeline needs it. `make_variants.py` reports any variant whose age is still infeasible.
- Cues are bundled, so results show a combined race, gender, or age effect and cannot be split by individual cue.
- First names are rotated across resumes within each cell. White and Black names follow Gaddis 2017 / Elder & Hayes 2023 where possible. The Middle Eastern, non-binary, and age-matched names are not from a validated list, so swap them in `demographic_cues.json` if one is required.

**Scoring**
- Every call starts from a clean context. Each one is a stateless request through a new client, sending the fixed system prompt and exactly one user message, with no history, caching, or conversation IDs. Before each run, `score_resumes.py` checks isolation: it plants a word in one call and probes for it in a separate call, and aborts if the word leaks. The result is stored in the output.
- Use one resume per call, with only the system prompt from `scoring_system_prompt.md` and the posting verbatim (front matter removed, title kept), and 3 samples per resume. The temperature is fixed at 0.7 by default and recorded in the output.
- Output is JSON `{"score": <0-100>, "rationale": "..."}`. The model's thinking text is stored as `reasoning` when the endpoint returns it.
- Log the model ID, timestamp, refusals, and malformed outputs.
- Report each variant as a difference from the name-free baseline of its own base resume.

## Known issues

- `high/05` is a generic SaaS CTO resume with no aerospace experience and no work authorization or clearance line. It probably does not fit the high tier and should be replaced.
- `high/05` and `high/08` are about half the length of the other high-tier resumes. `high/08` uses `<graduation_year>` where every other file uses `<year>`.
- Job dates stay as placeholders (`<year>–Present`) in the variants, while degree years are real.

## Notes

- `.env` is gitignored and expected to hold API credentials for model endpoints.
