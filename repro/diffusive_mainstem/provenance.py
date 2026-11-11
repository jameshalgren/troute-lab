"""Write results/provenance.json describing how and where a run happened.

Identical copies live in every repro/ experiment so each directory stays self-contained.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def _cmd(args: list[str]) -> str | None:
    if shutil.which(args[0]) is None:
        return None
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None
    except Exception as e:  # pragma: no cover - diagnostic only
        return f"error: {e}"


def _git_state(repo_dir: Path) -> dict:
    head = _cmd(["git", "-C", str(repo_dir), "rev-parse", "HEAD"])
    dirty = None
    if head and not head.startswith("error"):
        st = subprocess.run(["git", "-C", str(repo_dir), "status", "--porcelain", "--", "."],
                            capture_output=True, text=True)
        dirty = bool(st.stdout.strip())
    return {"commit": head, "experiment_dir_has_uncommitted_changes": dirty}


def collect(exp_dir: Path, inputs: dict[str, Path] | None = None,
            sources: dict | None = None, compilers: list[list[str]] | None = None,
            extra: dict | None = None) -> dict:
    pkgs = {d.metadata["Name"]: d.version for d in metadata.distributions()}
    prov = {
        "timestamp_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "python": {"version": sys.version, "implementation": platform.python_implementation()},
        "uv": _cmd(["uv", "--version"]),
        "packages": dict(sorted(pkgs.items(), key=lambda kv: kv[0].lower())),
        "paper_repo": _git_state(exp_dir),
        "inputs": {k: {"path": str(Path(p).relative_to(exp_dir)) if Path(p).is_relative_to(exp_dir) else Path(p).name,
                       "sha256": sha256(Path(p))}
                   for k, p in (inputs or {}).items()},
        "sources": sources or {},
        "compilers": {" ".join(c): _cmd(c) for c in (compilers or [])},
    }
    if extra:
        prov.update(extra)
    return prov


def write(exp_dir: Path, results_dir: Path, **kw) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / "provenance.json"
    out.write_text(json.dumps(collect(exp_dir, **kw), indent=2) + "\n")
    return out
