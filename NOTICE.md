# Notices & provenance

This repository is the demo artifact for the CCS demo paper on **SemCRS**, a system
that streamlines software vulnerability discovery and patching.

## Notes
- **Model:** this demo calls GPT-5 via the current OpenAI SDK. The model is
  configurable through the `LLM_MODEL` environment variable.
- **Submission step:** the scoring server is offline in this standalone artifact,
  so the tool emits the exact schema-conformant VDS/GP JSON payloads instead of
  POSTing them.

## Components & licensing
- The demo kit code (`demo.py`, `cp_runner.py`, `llm.py`, `defs.py`) is authored by
  the paper's authors and released under the MIT `LICENSE` in this repository.
- `mock-cp.tar.gz` bundles a third-party benchmark program (the "Mock CP"). It is
  MIT-licensed and redistributed unmodified; its copyright holder and full license
  text are in the `LICENSE` file inside the archive.
- The demo builds the benchmark on the public base image
  `gcr.io/oss-fuzz-base/base-clang`.

## No secrets
This repository intentionally contains **no** API keys, tokens, or credentials.
