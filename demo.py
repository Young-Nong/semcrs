"""
demo.py - staged, narratable re-run of the SemCRS on the Mock CP.

Reproduces the pipeline the original `detect.py` implemented, but as clean,
sectioned stages suitable for a screen recording:

  1. Seed-input generation          (LLM writes a generator from the harness)
  2. Reachable-function analysis    (defs/ctags + LLM call-graph broadening)
  3. Vulnerability detection        (LLM yes/no per function x sanitizer)
  4. Vulnerable-path + PoV gen      (LLM writes a PoV generator)
  5. Validation + VDS submission    (rebuild CP, run PoV, ASan check; payload)
  6. Patch generation + GP submit   (LLM fixes the function; confirm PoV dies)

Modes:
  live     (default) - calls GPT-5 via llm.py; needs OPENAI_API_KEY.
  --offline          - replays captured LLM outputs + a known-good patch.
                       Runs the full pipeline (incl. container + patching) with
                       no API key. Use as the recording fallback.

The competition API (cAPI) is gone, so VDS/GP submissions are printed as the
exact JSON payloads that would have been POSTed, clearly labelled as stubs.
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time

import yaml

import cp_runner
from defs import index_functions

# ---- captured LLM outputs (from the original run in crs_scratch/project) ----
CAPTURED_SEED = '''\
import struct
def generate_test_input():
    data = b''
    data += struct.pack('I', 0xdeadbeef)
    data += b'ABCD' * 10
    data += struct.pack('f', 3.14159)
    data += b'\\x00\\x01\\x02\\x03' * 10
    with open('test_input.bin', 'wb') as f:
        f.write(data)
generate_test_input()
'''

CAPTURED_POV = '''\
# Overflow items[3][10]: fgets(buff,40,..) reads 39 bytes/row across >3 rows.
input_data = b"\\n".join([b"A" * 39 for _ in range(15)]) + b"\\n"
with open("pov_input.bin", "wb") as f:
    f.write(input_data)
'''

# known-good patch for func_a (offline mode): bound the row index and the read
OFFLINE_PATCH_FUNC_A = '''\
void func_a(){
    char* buff;
    int i = 0;
    do{
        if (i >= 3) break;                 /* fix: never index past items[3] */
        printf("input item:");
        buff = &items[i][0];
        i++;
        fgets(buff, sizeof(items[0]), stdin); /* fix: read at most row size */
        buff[strcspn(buff, "\\n")] = 0;
    }while(strlen(buff)!=0);
    i--;
}'''

BAR = "=" * 74
_PAUSE = False


def pause():
    """Wait for Enter between stages (narration mode). No-op otherwise."""
    if _PAUSE:
        try:
            input("\n  [enter to continue] ")
        except EOFError:
            pass


def banner(n, title):
    print(f"\n{BAR}\n  STAGE {n}: {title}\n{BAR}")


def show(label, text, limit=1200):
    t = text if len(text) <= limit else text[:limit] + "\n  ... (truncated)"
    print(f"\n[{label}]\n" + "\n".join("  " + ln for ln in t.splitlines()))


def run_local(code, out_name, workdir):
    """Write an LLM-produced generator script and execute it in `workdir`."""
    script = os.path.join(workdir, "_gen.py")
    open(script, "w", encoding="utf-8", newline="\n").write(code)
    # ensure the child also treats source/IO as utf-8 on Windows
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    subprocess.run([sys.executable, "_gen.py"], cwd=workdir, check=True, env=env)
    return os.path.join(workdir, out_name)


def resolve_mockcp(explicit):
    """Find the Mock CP dir. Works both in the dev tree and in a standalone
    clone that ships the CP as `mock-cp.tar.gz` next to this script."""
    here = os.path.dirname(os.path.abspath(__file__))
    if explicit:
        cands = [explicit]
    else:
        cands = [os.path.join(here, "mock-cp"),
                 os.path.join(here, "..", "asc-crs-buffalo", "cp_root", "mock-cp")]
    for c in cands:
        if os.path.isdir(c):
            return os.path.abspath(c)
    tar = os.path.join(here, "mock-cp.tar.gz")
    if os.path.exists(tar):
        import tarfile
        print("[setup] extracting bundled mock-cp.tar.gz ...")
        with tarfile.open(tar) as t:
            t.extractall(here)
        d = os.path.join(here, "mock-cp")
        if os.path.isdir(d):
            return d
    raise SystemExit("Mock CP not found (expected ./mock-cp or ./mock-cp.tar.gz).")


def smoke_test(mockcp):
    """Verify the environment + container pipeline end-to-end, no API key.

    Builds/starts the CP, runs the captured PoV, checks the sanitizer fires,
    and runs the CP's functional tests. This is the artifact's 'does it work?'
    check reviewers can run for free.
    """
    print(f"{BAR}\n  SMOKE TEST - environment + pipeline plumbing (no API key)\n{BAR}")
    cp = cp_runner.CPRunner(mockcp)
    ok = False
    try:
        cp.build_image()
        cp.start()
        cp.build_harness()
        pov = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "captured_pov_input.bin")
        fired = cp_runner.sanitizer_fired(cp.run_pov(pov, "filein_harness"))
        tests_ok, _ = cp.run_tests()
        ok = fired and tests_ok
        print(f"  docker build + harness build : OK")
        print(f"  captured PoV triggers ASan   : {fired}")
        print(f"  CP functional tests pass     : {tests_ok}")
        print(f"\n  SMOKE TEST: {'PASS' if ok else 'FAIL'}\n{BAR}")
    finally:
        cp.stop()
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mockcp", default=None,
                    help="Mock CP dir (default: ./mock-cp or bundled tarball)")
    ap.add_argument("--smoke-test", action="store_true",
                    help="verify env + container pipeline (no LLM, no key)")
    ap.add_argument("--offline", action="store_true",
                    help="replay captured LLM outputs (heuristic); no API key")
    ap.add_argument("--cache", metavar="PATH",
                    help="record/replay LLM responses to this JSON file")
    ap.add_argument("--replay", action="store_true",
                    help="replay from --cache only; never call the API (for recording)")
    ap.add_argument("--pause", action="store_true",
                    help="wait for Enter between stages (narration)")
    ap.add_argument("--workdir", default="_work")
    args = ap.parse_args()

    if args.smoke_test:
        sys.exit(smoke_test(resolve_mockcp(args.mockcp)))

    global _PAUSE
    _PAUSE = args.pause
    if args.cache:
        os.environ["LLM_CACHE"] = os.path.abspath(args.cache)
    if args.replay:
        if not args.cache:
            ap.error("--replay requires --cache PATH (the recorded run)")
        os.environ["LLM_CACHE_STRICT"] = "1"

    # force UTF-8 on the console so printing LLM output can't crash on Windows
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    offline = args.offline
    t0 = time.time()
    os.makedirs(args.workdir, exist_ok=True)
    mockcp = resolve_mockcp(args.mockcp)
    src_root = os.path.join(mockcp, "src")

    project = yaml.safe_load(open(os.path.join(mockcp, "project.yaml"), encoding="utf-8"))
    cp_name = project["cp_name"]
    sanitizers = project["sanitizers"]            # id -> string
    harnesses = project["harnesses"]              # id -> {name, source}
    h_id = list(harnesses)[0]
    harness = harnesses[h_id]
    harness_code = open(os.path.join(mockcp, harness["source"]), encoding="utf-8").read()

    if not offline:
        import llm

    model = os.environ.get("LLM_MODEL", "gpt-5")
    if offline:
        mode = "OFFLINE (captured replay, heuristic)"
    elif args.replay:
        mode = f"REPLAY ({model}, cached)"
    else:
        mode = f"LIVE ({model})"
    print(f"{BAR}\n  SemCRS - autonomous vulnerability discovery & patching\n"
          f"  Pipeline: AIxCC 2024 (DARPA AI Cyber Challenge)  |  standalone reconstruction\n"
          f"  LLM: {mode}   (the 2024 competition run used GPT-4-turbo / GPT-3.5)\n"
          f"  target CP: '{cp_name}'  |  scored sanitizers: {list(sanitizers.values())}\n{BAR}")
    pause()

    # ---- STAGE 1: seed-input generation ------------------------------------
    banner(1, "Seed-input generation from the harness")
    if offline:
        seed_code = CAPTURED_SEED
    else:
        prompt = ("Given the harness, write a python script that saves a test "
                  "input as `test_input.bin` to exercise as much code as "
                  "possible. Output only code.\n" + harness_code)
        reply, _ = llm.chat([{"role": "user", "content": prompt}])
        seed_code = llm.extract_code(reply)
    show("LLM-generated seed generator (excerpt)", seed_code, limit=340)
    print(f"  (full generator: {len(seed_code.splitlines())} lines; saved to artifacts)")
    run_local(seed_code, "test_input.bin", args.workdir)
    tin = os.path.join(args.workdir, "test_input.bin")
    print(f"  -> wrote test_input.bin ({os.path.getsize(tin)} bytes)")

    pause()
    # ---- STAGE 2: reachable-function analysis ------------------------------
    banner(2, "Reachable-function analysis (defs + call-graph broadening)")
    idx = index_functions(src_root)
    entry = [f for f in ("LLVMFuzzerTestOneInput", "main") if f in idx]
    print(f"  entry functions: {entry}")
    reachable = set(entry)
    if offline:
        reachable |= {"setup_pipe_data", "func_a", "func_b"}
    else:
        for fn in list(entry):
            prompt = ("List the user-defined functions called in this function, "
                      "one name per line, no prose:\n" + idx[fn]["code"])
            reply, _ = llm.chat_fast([{"role": "user", "content": prompt}])
            for cand in reply.split("\n"):
                cand = cand.strip().split("(")[0].split(".")[-1]
                if cand in idx:
                    reachable.add(cand)
    print(f"  reachable set: {sorted(reachable)}")

    pause()
    # ---- STAGE 3: vulnerability detection ----------------------------------
    banner(3, "Vulnerability detection (per function x sanitizer)")
    flagged = []
    for fn in sorted(reachable):
        for sid, sname in sanitizers.items():
            if offline:
                verdict = "yes" if fn == "func_a" and "overflow" in sname else "no"
            else:
                prompt = (f"Does this function have an exploitable "
                          f"`{sname}` vulnerability triggerable via its inputs? "
                          f"Answer only yes or no.\n" + idx[fn]["code"])
                reply, _ = llm.chat([{"role": "user", "content": prompt}])
                verdict = "yes" if "yes" in reply.lower() else "no"
            mark = "  <== FLAGGED" if verdict == "yes" else ""
            print(f"  {fn:22s} {sid} ({sname}): {verdict}{mark}")
            if verdict == "yes":
                flagged.append((fn, sid, sname))
    if not flagged:
        print("  no vulnerabilities flagged; stopping.")
        return

    # candidate queue (each is validated before any submission; no confidence
    # scores are shown because the detector emits a yes/no decision, not a score)
    print("\n  candidate queue (validated in Stage 5 before submission):")
    for k, (cfn, csid, csn) in enumerate(flagged):
        status = "selected" if k == 0 else "queued  "
        print(f"    [{status}] {cfn:8s} {csn}")

    pause()
    # ---- STAGE 4: vulnerable-path analysis + PoV generation ----------------
    banner(4, "Vulnerable-path analysis + PoV generation")
    fn, sid, sname = flagged[0]
    print(f"  target: {fn}  sanitizer: {sname}")
    path_analysis = "(offline replay)"
    if offline:
        pov_code = CAPTURED_POV
    else:
        ctx = "\n".join(idx[f]["code"] for f in ("LLVMFuzzerTestOneInput",
                                                 "setup_pipe_data", fn) if f in idx)
        msgs = [{"role": "user", "content":
                 f"Here is a call path to `{fn}` and the harness:\n{ctx}\n\n"
                 f"{harness_code}\n\nExplain how to trigger `{sname}`, then write "
                 f"a python script saving a PoV as `pov_input.bin`. Output the "
                 f"analysis, then a python code block."}]
        reply, _ = llm.chat(msgs)
        path_analysis = reply
        show("LLM path analysis + PoV", reply, 900)
        pov_code = llm.extract_code(reply)
    show("PoV generator", pov_code)
    run_local(pov_code, "pov_input.bin", args.workdir)
    pov_path = os.path.join(args.workdir, "pov_input.bin")
    print(f"  -> wrote pov_input.bin ({os.path.getsize(pov_path)} bytes)")

    pause()
    # ---- STAGE 5: validation + VDS submission ------------------------------
    banner(5, "Validation in rebuilt CP + VDS submission")
    cp = cp_runner.CPRunner(mockcp)
    try:
        cp.build_image()
        cp.start()
        cp.build_harness()
        out = cp.run_pov(pov_path, harness["name"])
        fired = cp_runner.sanitizer_fired(out, sname)
        for l in out.splitlines():
            if "AddressSanitizer:" in l or "SUMMARY:" in l:
                print("  " + l)
        print(f"\n  sanitizer fired: {fired}")
        if not fired:
            print("  PoV did not trigger; a full run would retry / try next path.")
            return

        commit = subprocess.run(
            ["docker", "exec", cp.cid, "bash", "-lc",
             "cd /src/samples && git rev-parse HEAD"],
            capture_output=True, text=True).stdout.strip()
        pov_b64 = base64.b64encode(open(pov_path, "rb").read()).decode()
        vds = {"cp_name": cp_name,
               "pou": {"commit_sha1": commit, "sanitizer": sid},
               "pov": {"harness": h_id, "data": pov_b64[:44] + "..."}}
        print("\n  [SUBMISSION STUB - cAPI offline] POST /submission/vds/")
        print("  " + json.dumps(vds))

        pause()
        # ---- STAGE 6: patch generation + GP submission ---------------------
        banner(6, "Patch generation + GP submission")
        orig = idx[fn]["code"]
        if offline:
            patched = OFFLINE_PATCH_FUNC_A
        else:
            import llm
            reply, _ = llm.chat([{"role": "user", "content":
                f"Rewrite this function to fix the `{sname}` vulnerability. Keep "
                f"it compilable and preserve functionality. Output only the "
                f"function code.\n" + orig}])
            patched = llm.extract_code(reply)
        show("patched function", patched)

        # apply inside the container, rebuild, re-run the SAME PoV
        cur = cp.read_source("samples/mock_vp.c")
        cp.write_source("samples/mock_vp.c", cur.replace(orig, patched))
        cp.build_harness()
        out2 = cp.run_pov(pov_path, harness["name"])
        still_fires = cp_runner.sanitizer_fired(out2, sname)
        print(f"\n  PoV re-run after patch - sanitizer fired: {still_fires}"
              f"  (blocked: {not still_fires})")

        # functionality regression: run the CP's own tests on the patched build
        tests_ok, tests_out = cp.run_tests()
        print(f"  functional regression (cp_tests on test1/test2 blobs): "
              f"{'PASS' if tests_ok else 'FAIL'}")

        diff = cp.diff()
        show("git diff", diff, 800)
        gp_full = {"cpv_uuid": "<from accepted VDS>",
                   "data": base64.b64encode(diff.encode()).decode()}
        print("\n  [SUBMISSION STUB - cAPI offline] POST /submission/gp/")
        print("  " + json.dumps({**gp_full, "data": gp_full["data"][:44] + "..."}))

        # ---- persist artifacts + honest run summary ------------------------
        run_dir = os.path.join(args.workdir, "results",
                               "run-" + time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(run_dir, exist_ok=True)
        vds_full = {"cp_name": cp_name,
                    "pou": {"commit_sha1": commit, "sanitizer": sid},
                    "pov": {"harness": h_id, "data": pov_b64}}
        w = lambda n, s: open(os.path.join(run_dir, n), "w", encoding="utf-8",
                              newline="\n").write(s)
        w("seed_generator.py", seed_code)
        w("path_analysis.txt", path_analysis)
        shutil.copy(pov_path, os.path.join(run_dir, "pov_input.bin"))
        w("sanitizer_before.log", out)
        w("sanitizer_after.log", out2)
        w("functional_tests.log", tests_out)
        w("patch.diff", diff)
        w("vds_request.json", json.dumps(vds_full, indent=2))
        w("gp_request.json", json.dumps(gp_full, indent=2))
        calls = llm.CALLS if not offline else 0
        summary = (
            f"Target CP        : {cp_name}\n"
            f"Vulnerability    : {sname} in {fn}\n"
            f"PoV validated    : {'yes' if fired else 'no'} (sanitizer fired live)\n"
            f"Patch blocks PoV : {'yes' if not still_fires else 'no'}\n"
            f"Functional tests : {'pass' if tests_ok else 'fail'}\n"
            f"LLM queries      : {calls if not offline else 'n/a (offline replay)'}\n"
            f"Runtime          : {time.time() - t0:.0f}s\n"
            f"Artifacts        : {run_dir}\n")
        w("summary.txt", summary)
        print(f"\n{BAR}\n  RESULT\n{BAR}")
        print("  " + summary.replace("\n", "\n  ").rstrip())
        verdict = ("patch blocks the validated PoV and functional tests pass"
                   if (not still_fires and tests_ok)
                   else "see summary above")
        print(f"\n  DONE - vulnerability discovered & reproduced; {verdict}.\n{BAR}")
    finally:
        cp.stop()


if __name__ == "__main__":
    main()
