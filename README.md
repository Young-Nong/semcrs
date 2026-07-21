# SemCRS - autonomous vulnerability discovery & patching (CCS demo artifact)

SemCRS is a Cyber Reasoning System for automated software security. Given only a
program and its fuzzing harness, it runs a six-stage pipeline that discovers a
vulnerable function, generates and **validates** a proof-of-vulnerability (PoV)
against AddressSanitizer, generates a patch, and confirms the same PoV no longer
fires while the program's functional tests still pass.

The bundled benchmark program (the "Mock CP") ships without a prebuilt image, so it
is rebuilt locally from source on the public `gcr.io/oss-fuzz-base/base-clang` base.
See [NOTICE.md](NOTICE.md) for provenance and licensing.

## Quick start
```bash
pip install openai pyyaml            # + Docker installed and running

# 1. does it work? (no API key; rebuilds the CP, runs a PoV, checks the sanitizer)
python demo.py --smoke-test          # -> SMOKE TEST: PASS

# 2. reproduce the full pipeline from the recorded run (no API key, deterministic)
python demo.py --replay --cache run1.json

# 3. full live run (needs your key)
export OPENAI_API_KEY=sk-...         # Windows PowerShell: $env:OPENAI_API_KEY="sk-..."
python demo.py
```
The Mock CP is bundled as `mock-cp.tar.gz` and auto-extracted on first run.
Full install/testing tiers and troubleshooting: [SETUP.md](SETUP.md).

## Files
| File | Role |
|---|---|
| `demo.py` | The staged six-stage pipeline driver (this is what the video records). |
| `cp_runner.py` | Container orchestration (build / run_pov / patch / tests) via `docker cp`+`exec` - no bind mounts, so identical on Windows, WSL, Linux. |
| `llm.py` | LLM client (current OpenAI SDK, GPT-5-aware) with record/replay cache. |
| `defs.py` | Function-definition index (prefers `ctags`, regex fallback). |
| `mock-cp.tar.gz` | The bundled benchmark program (the Mock CP; includes its own `Dockerfile.local` and `LICENSE`). |
| `captured_pov_input.bin` | A known-good PoV used by `--smoke-test`. |
| `run1.json` | Recorded GPT-5 responses for `--replay` (commit yours after a live run). |
| `SETUP.md` | Detailed install / test tiers and troubleshooting. |
| `LICENSE`, `NOTICE.md` | MIT license and provenance notes. |

## Notes
- No secrets are included in this repository.
- VDS/GP submissions are printed as exact schema-conformant JSON payloads (the
  scoring server is offline in this standalone artifact), and each run writes an
  inspectable `_work/results/run-*/` record (PoV, before/after sanitizer logs,
  patch, tests).
- Validated on clang 22. On a native amd64 host it runs without emulation warnings.
