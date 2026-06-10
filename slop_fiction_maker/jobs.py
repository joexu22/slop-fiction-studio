"""Detached background jobs for long-running generations.

Generations take 5-20 minutes, which is far too long for a blocking MCP tool
call. Instead, tools spawn the normal CLI as a detached subprocess (so the
job log is identical to a manual run) and return a job_id immediately. The
caller polls job_status() until the job reaches a terminal state.

Registry layout (under the gitignored output/ tree):
    output/.jobs/<job_id>.json   # args, label, pid, started_at, exit_code
    output/.jobs/<job_id>.log    # the run's full stdout+stderr

Process model: start_job() spawns `python -m slop_fiction_maker.jobs <job_id>`
(the runner, see __main__ below) in a new session. The runner executes the
real command, waits for it (so it is properly reaped — a directly-detached
child would linger as a zombie and look alive to os.kill), and writes the
exit code back into the registry entry. The exit code in the JSON is the
authoritative terminal-state signal; the pid check only distinguishes
"still running" from "runner crashed before recording an exit code".
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import shortuuid

from .config import OUTPUT_DIR, REPO_ROOT

JOBS_DIR = OUTPUT_DIR / ".jobs"
LOG_TAIL_LINES = 30


def start_job(args: list[str], label: str) -> dict:
    """Start `python <args>` as a detached, logged background job.

    args: arguments after the interpreter, e.g.
        ["-m", "slop_fiction_maker.audio_to_video", "--topic-hint", "..."]
    Returns the registry entry (including job_id).
    """
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{shortuuid.uuid()[:6]}"
    entry_path = JOBS_DIR / f"{job_id}.json"

    entry = {
        "job_id": job_id,
        "label": label,
        "args": args,
        "pid": None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "log": str(JOBS_DIR / f"{job_id}.log"),
        "exit_code": None,
    }
    # The runner reads this entry, so it must exist before the spawn.
    entry_path.write_text(json.dumps(entry, indent=2))

    proc = subprocess.Popen(
        [sys.executable, "-m", "slop_fiction_maker.jobs", job_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(REPO_ROOT),
        start_new_session=True,  # survives the MCP server / agent exiting
    )

    entry["pid"] = proc.pid
    entry_path.write_text(json.dumps(entry, indent=2))
    return entry


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    # Reap if it's our own finished child (otherwise a zombie reads as alive).
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def job_status(job_id: str) -> dict:
    """Status + progress for a job: running/succeeded/failed, parsed
    artifacts (run dir, final video, YouTube URL), and the log tail.
    """
    entry_path = JOBS_DIR / f"{job_id}.json"
    if not entry_path.exists():
        known = sorted(p.stem for p in JOBS_DIR.glob("*.json"))
        return {
            "job_id": job_id,
            "state": "unknown",
            "error": f"No such job. Known jobs: {known[-10:]}",
        }
    entry = json.loads(entry_path.read_text())

    if entry["exit_code"] is not None:
        state = "succeeded" if entry["exit_code"] == 0 else "failed"
    elif _pid_alive(entry["pid"]):
        state = "running"
    else:
        state = "failed"  # runner died before recording an exit code

    log_path = Path(entry["log"])
    log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
    lines = log_text.splitlines()

    # Parse artifacts from well-known log lines
    run_dir = None
    final_video = None
    youtube_url = None
    resume_hint = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Output: "):
            run_dir = stripped.removeprefix("Output: ").strip()
        elif stripped.startswith("Local copy: "):
            final_video = stripped.removeprefix("Local copy: ").strip()
        elif stripped.startswith("YouTube: "):
            youtube_url = stripped.removeprefix("YouTube: ").strip()
        elif stripped.startswith("To resume: "):
            resume_hint = stripped.removeprefix("To resume: ").strip()

    beats_done = sum(1 for ln in lines if "generated: gs://" in ln)

    return {
        "job_id": job_id,
        "label": entry["label"],
        "state": state,
        "started_at": entry["started_at"],
        "beats_generated": beats_done,
        "run_dir": run_dir,
        "final_video": final_video,
        "youtube_url": youtube_url,
        "resume_hint": resume_hint if state == "failed" else None,
        "log_tail": lines[-LOG_TAIL_LINES:],
    }


def _run_job(job_id: str) -> int:
    """Runner entrypoint: execute the job's command, wait for it, and record
    the exit code in the registry. Runs detached from the spawning process.
    """
    entry_path = JOBS_DIR / f"{job_id}.json"
    entry = json.loads(entry_path.read_text())

    with Path(entry["log"]).open("ab") as log_file:
        result = subprocess.run(
            [sys.executable, *entry["args"]],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
            check=False,
        )

    # Re-read so we don't clobber fields written after the spawn (e.g. pid).
    entry = json.loads(entry_path.read_text())
    entry["exit_code"] = result.returncode
    entry["finished_at"] = datetime.now().isoformat(timespec="seconds")
    entry_path.write_text(json.dumps(entry, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(_run_job(sys.argv[1]))
