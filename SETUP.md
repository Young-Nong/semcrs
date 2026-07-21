# SETUP - installing, testing, and running the artifact

This artifact reconstructs the Buffalo CRS pipeline (AIxCC 2024) as a standalone
demo on the public **Mock CP** challenge project. The original competition images
(`ghcr.io/aixcc-sc/*`) are gone - the `aixcc-sc` org was deleted - so the CP is
rebuilt locally from bundled source on the still-public `gcr.io/oss-fuzz-base/base-clang`.

## Requirements
- **Docker** (Desktop on Windows/macOS, or Docker Engine on Linux). First run pulls
  a ~2 GB base image. Needs ~4 GB free disk.
- **Python 3.9+** with `pip install openai pyyaml`.
- For the **live** tier only: an OpenAI API key with access to `gpt-5`.

Tested on Windows 11 (Docker Desktop) and Linux. On Windows, run from PowerShell.

## Three ways to run (pick your tier)

### 1. Smoke test - free, no API key (~1 min after image build)
Verifies the whole environment: rebuilds the CP in Docker, runs a known PoV,
confirms AddressSanitizer fires, and runs the CP's functional tests.
```bash
python demo.py --smoke-test
# expect: SMOKE TEST: PASS
```

### 2. Replay the recorded run - free, no API key, deterministic
Runs the complete six-stage pipeline using cached GPT-5 responses from our recorded
run, but still performs the *real* CP rebuild, PoV execution, patch, and validation.
This reproduces exactly what the demo video shows.
```bash
python demo.py --replay --cache run1.json
# add --pause to step through stages
```

### 3. Full live run - needs your OpenAI key
Calls GPT-5 for every stage. Non-deterministic; results may differ slightly.
```bash
# Linux/macOS:
export OPENAI_API_KEY=sk-...
# Windows PowerShell:
$env:OPENAI_API_KEY="sk-..."

python demo.py                       # defaults to gpt-5
# optional: LLM_MODEL, LLM_MODEL_FAST, LLM_EFFORT (see README.md)
```
Approx. cost: a few GPT-5 calls per run (single-digit dollars, model-dependent).
Runtime: ~2-4 min plus the one-time image build.

## Expected output
Each run prints six labeled stages and a final `RESULT` block, and writes an
inspectable record to `_work/results/run-<timestamp>/`:
```
seed_generator.py      path_analysis.txt      pov_input.bin
sanitizer_before.log   sanitizer_after.log    functional_tests.log
patch.diff             vds_request.json       gp_request.json      summary.txt
```
A successful run ends with: PoV validated (sanitizer fired), patch blocks the PoV,
and functional tests pass.

## What is original vs. reconstructed
- **Pipeline design & prompts:** from the 2024 AIxCC submission.
- **Model:** GPT-5 here (the 2024 run used GPT-4-turbo / GPT-3.5). Ported from the
  legacy `openai.ChatCompletion` SDK to the current SDK.
- **Submission step:** the competition cAPI is offline; the tool emits the exact
  schema-conformant VDS/GP JSON payloads instead of POSTing them.

## Troubleshooting
- **`OPENAI_API_KEY is not set`** - only the live tier needs it; use `--smoke-test`
  or `--replay` otherwise.
- **Docker build fails on the clang runtime path** - the base image ships a moving
  clang version; `Dockerfile.local` globs it. Re-pull `gcr.io/oss-fuzz-base/base-clang`.
- **Windows path / encoding errors** - run from PowerShell; the tool forces UTF-8.
- **`replay mode: prompt not found in cache`** - the cache doesn't match; record a
  fresh live run with `--cache run1.json` first, then replay it.
