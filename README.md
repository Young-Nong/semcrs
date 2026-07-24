# SemCRS - streamlining vulnerability discovery \& patching (CCS demo artifact)

SemCRS is a Semantics-guided Cyber Reasoning System for automated software security.
Given a program, its fuzzing harness, and the target sanitizer classes, it streamlines
discovery and patching in a single six-stage pipeline: it discovers a vulnerable
function, generates and **validates** a proof-of-vulnerability (PoV) against
AddressSanitizer, and then generates a patch that blocks the same PoV while the
program's functional tests still pass.

The bundled benchmark program (the "Mock CP") ships without a prebuilt image, so it
is rebuilt locally from source on the public `gcr.io/oss-fuzz-base/base-clang` base.
See [NOTICE.md](NOTICE.md) for provenance and licensing.

## Demo video

[**`demo.mp4`**](demo.mp4) **is a narrated walkthrough of the whole artifact** - the fastest
way to see what SemCRS does without installing anything. Starting from a clean checkout,
it covers the setup, then follows one live GPT-5 run of the full pipeline on the Mock CP:
seed-input generation, reachability analysis, vulnerability detection (which flags two
candidate functions), PoV generation, validation under AddressSanitizer, and patch
generation with the post-patch PoV re-run and functional tests. The run ends with a
sanitizer-validated PoV and a patch that blocks it while the functional tests still pass.


## Quick start

```bash
pip install openai pyyaml            # + Docker installed and running

# 1. does it work? (no API key; rebuilds the CP, runs a PoV, checks the sanitizer)
python demo.py --smoke-test          # -> SMOKE TEST: PASS

# 2. reproduce the full pipeline from the recorded run (no API key, deterministic)
python demo.py --replay --cache run1.json

# 3. full live run (needs your key)
export OPENAI\_API\_KEY=sk-...         # Windows PowerShell: $env:OPENAI\_API\_KEY="sk-..."
python demo.py
```

The Mock CP is bundled as `mock-cp.tar.gz` and auto-extracted on first run.
Full install/testing tiers and troubleshooting: [SETUP.md](SETUP.md).

## Files

|File|Role|
|-|-|
|`demo.py`|The staged six-stage pipeline driver (this is what the video records).|
|`cp\_runner.py`|Container orchestration (build / run\_pov / patch / tests) via `docker cp`+`exec` - no bind mounts, so identical on Windows, WSL, Linux.|
|`llm.py`|LLM client (current OpenAI SDK, GPT-5-aware) with record/replay cache.|
|`defs.py`|Function-definition index (prefers `ctags`, regex fallback).|
|`mock-cp.tar.gz`|The bundled benchmark program (the Mock CP; includes its own `Dockerfile.local` and `LICENSE`).|
|`captured\_pov\_input.bin`|A known-good PoV used by `--smoke-test`.|
|`run1.json`|Recorded GPT-5 responses for `--replay` (commit yours after a live run).|
|`demo.mp4`|Narrated walkthrough of a full live run (see [Demo video](#demo-video)).|
|`SETUP.md`|Detailed install / test tiers and troubleshooting.|
|`LICENSE`, `NOTICE.md`|MIT license and provenance notes.|

## Notes

* No secrets are included in this repository.
* VDS/GP submissions are printed as exact schema-conformant JSON payloads (the
scoring server is offline in this standalone artifact), and each run writes an
inspectable `\_work/results/run-\*/` record (PoV, before/after sanitizer logs,
patch, tests).
* Validated on clang 22. On a native amd64 host it runs without emulation warnings.

