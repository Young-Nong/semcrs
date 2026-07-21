# Notices & provenance

This repository is the demo artifact for the CCS demo paper on the **Buffalo CRS**,
a standalone reconstruction of a system entered in the 2024 DARPA AI Cyber Challenge
Semifinal Competition (AIxCC ASC).

## What is original vs. reconstructed
- **Pipeline design and prompts** derive from the 2024 AIxCC submission.
- **Model:** this demo calls GPT-5 (the 2024 run used GPT-4-turbo / GPT-3.5), via
  the current OpenAI SDK (the original used the now-removed `openai.ChatCompletion`).
- **Submission:** the competition cAPI is offline; the tool emits the exact
  schema-conformant VDS/GP JSON payloads instead of POSTing them.

## Components & licensing
- The demo kit code (`demo.py`, `cp_runner.py`, `llm.py`, `defs.py`) is authored by
  the paper's authors and released under the MIT `LICENSE` in this repository.
- `mock-cp.tar.gz` bundles the **AIxCC Mock CP** challenge project (a public AIxCC
  exemplar), which is itself MIT-licensed (Copyright (c) 2024 Artificial
  Intelligence Cyber Challenge). Its `LICENSE` is included inside the archive; it is
  redistributed here under that license for reproducibility.
- The demo builds the CP on the public base image `gcr.io/oss-fuzz-base/base-clang`.

## No secrets
This repository intentionally contains **no** API keys, tokens, or credentials.
The original competition repository's secret files are deliberately excluded.
