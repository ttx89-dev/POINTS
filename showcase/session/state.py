"""Multi-process session state helpers (tmpfs-backed)."""
from __future__ import annotations
import os
import json
import fcntl
from pathlib import Path
from typing import Any, Optional

SESSION_DIR = Path("/tmp/opencode/points")
SESSION_DIR.mkdir(parents=True, exist_ok=True)

PLAN_FILE = SESSION_DIR / "master_plan.bin"
RESULTS_DIR = SESSION_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

SUBAGENT_MAP = {
    "math": "subagent_math.py",
    "fib": "subagent_math.py",
    "logic": "subagent_logic.py",
    "code": "subagent_code.py",
}

def load_plan() -> bytes:
    with open(PLAN_FILE, "rb") as f:
        return f.read()

def save_plan(raw: bytes) -> None:
    with open(PLAN_FILE, "wb") as f:
        f.write(raw)

def result_path(task_name: str) -> Path:
    return RESULTS_DIR / f"{task_name}.bin"

def save_result(task_name: str, raw: bytes) -> None:
    path = result_path(task_name)
    with open(path, "wb") as f:
        f.write(fcntl.flock(f, fcntl.LOCK_EX) or f.write(raw))

def load_result(task_name: str) -> Optional[bytes]:
    path = result_path(task_name)
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return f.read()

def subagent_script(task_type: str) -> str:
    return f"/var/home/ryan/Documents/projects/POINTS/showcase/{SUBAGENT_MAP[task_type]}"

def task_list() -> list[str]:
    return [p.stem for p in RESULTS_DIR.glob("*.bin")]