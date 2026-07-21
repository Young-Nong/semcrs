"""
cp_runner.py — Container orchestration for the Mock CP.

The bundled benchmark program ships without a prebuilt image, so this rebuilds it
locally from the bundled source on the public `gcr.io/oss-fuzz-base/base-clang`
base and drives build / run_pov entirely through `docker cp` + `docker exec`
(no bind mounts, so it behaves identically on Windows, WSL, and Linux).

Driving docker from Python (not bash) also avoids MSYS path mangling on Windows.
"""
import subprocess
import time
from pathlib import Path


class CPRunner:
    def __init__(self, mockcp_dir: str, image: str = "mock-cp-local:latest"):
        self.mockcp = Path(mockcp_dir).resolve()
        self.image = image
        self.cid = None
        if not (self.mockcp / "project.yaml").exists():
            raise FileNotFoundError(f"Not a Mock CP dir: {self.mockcp}")

    # -- low level ---------------------------------------------------------
    def _run(self, args, **kw):
        return subprocess.run(args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", **kw)

    def _exec(self, script: str):
        """Run a bash snippet inside the container as root (LOCAL_USER=0:0)."""
        return self._run(
            ["docker", "exec", "-e", "LOCAL_USER=0:0", self.cid, "bash", "-lc", script]
        )

    # -- lifecycle ---------------------------------------------------------
    def build_image(self):
        df = self.mockcp / "Dockerfile.local"
        if not df.exists():
            raise FileNotFoundError(
                f"Missing {df}. Copy the provided Dockerfile.local into the Mock CP dir."
            )
        print(f"[cp] building image {self.image} (first time pulls the ~2GB base)...")
        r = self._run(
            ["docker", "build", "-f", str(df), "-t", self.image, str(self.mockcp)]
        )
        if r.returncode != 0:
            raise RuntimeError("image build failed:\n" + r.stderr[-2000:])
        print("[cp] image ready.")

    def start(self):
        r = self._run(
            ["docker", "run", "-d", "-e", "LOCAL_USER=0:0",
             "--entrypoint", "sleep", self.image, "7200"]
        )
        if r.returncode != 0:
            raise RuntimeError("container start failed:\n" + r.stderr)
        self.cid = r.stdout.strip()
        # ship the CP source into the container's /src
        cp = self._run(["docker", "cp", str(self.mockcp / "src") + "/.", f"{self.cid}:/src/"])
        if cp.returncode != 0:
            raise RuntimeError("copying source failed:\n" + cp.stderr)
        print(f"[cp] container up: {self.cid[:12]}")
        return self.cid

    def build_harness(self):
        r = self._exec("cmd_harness.sh build")
        ok = "/out/filein_harness" not in r.stderr and "Failed" not in (r.stdout + r.stderr)
        # verify artifact really exists
        chk = self._exec("test -x /out/filein_harness && echo OK || echo MISSING")
        if "OK" not in chk.stdout:
            raise RuntimeError("harness build failed:\n" + (r.stdout + r.stderr)[-2000:])
        print("[cp] harness built (clang, ASan+UBSan+libFuzzer).")

    def run_pov(self, blob_path: str, harness: str = "filein_harness") -> str:
        """Copy a PoV blob in, run it, return combined harness output."""
        self._run(["docker", "cp", str(Path(blob_path).resolve()), f"{self.cid}:/work/tmp_blob"])
        r = self._exec(f"cmd_harness.sh pov /work/tmp_blob {harness}")
        return r.stdout + r.stderr

    def run_tests(self):
        """Run the CP's own functional tests (cp_tests). Returns (ok, output).

        For the Mock CP these run the non-sanitized binary on known-good blobs
        and check expected output ('apple'/'bicycle'), i.e. a real functionality
        regression check the patch must not break.
        """
        r = self._exec("cmd_harness.sh tests")
        ok = r.returncode == 0
        # capture concrete evidence: the patched binary's output on each blob
        ev = self._exec(
            "cd /src && for b in test/test1.blob test/test2.blob; do "
            "echo \"--- $b (expect apple/bicycle) ---\"; "
            "./samples/mock_vp < \"$b\"; done 2>&1")
        log = (f"cp_tests exit={r.returncode} -> {'PASS' if ok else 'FAIL'}\n"
               f"{r.stdout}{r.stderr}\n{ev.stdout}")
        return ok, log

    def write_source(self, rel_path: str, content: str):
        """Overwrite a source file inside the container (used for patching)."""
        # write to a temp file then docker cp (handles arbitrary content safely)
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", delete=False, newline="\n",
                                         encoding="utf-8") as f:
            f.write(content)
            tmp = f.name
        self._run(["docker", "cp", tmp, f"{self.cid}:/src/{rel_path}"])
        os.unlink(tmp)

    def read_source(self, rel_path: str) -> str:
        r = self._exec(f"cat /src/{rel_path}")
        return r.stdout

    def diff(self, path: str = "mock_vp.c") -> str:
        # /src/samples is a git repo (bundled .git); show the working diff for
        # just the patched file, ignoring file-mode churn from docker cp.
        r = self._exec(
            f"cd /src/samples && git -c core.fileMode=false diff -- {path} 2>/dev/null || true"
        )
        return r.stdout

    def stop(self):
        if self.cid:
            self._run(["docker", "rm", "-f", self.cid])
            print(f"[cp] container {self.cid[:12]} removed.")
            self.cid = None


SANITIZER = "AddressSanitizer: global-buffer-overflow"


def sanitizer_fired(output: str, sanitizer: str = SANITIZER) -> bool:
    return sanitizer in output


if __name__ == "__main__":
    # Self-test: rebuild CP, run the captured PoV, confirm the sanitizer fires.
    import sys
    mockcp = sys.argv[1] if len(sys.argv) > 1 else \
        "../asc-crs-buffalo/cp_root/mock-cp"
    pov = sys.argv[2] if len(sys.argv) > 2 else "captured_pov_input.bin"
    r = CPRunner(mockcp)
    try:
        r.build_image()
        r.start()
        r.build_harness()
        out = r.run_pov(pov)
        print("--- harness output (tail) ---")
        print("\n".join(out.splitlines()[-6:]))
        print("SANITIZER FIRED:", sanitizer_fired(out))
    finally:
        r.stop()
