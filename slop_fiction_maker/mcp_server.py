"""Slop Fiction MCP server — the general agent interface to this repo.

Exposes the generation pipelines as MCP tools over stdio so Claude Code,
Gemini CLI, or any other MCP-capable agent can drive them. Registered for
Claude Code via .mcp.json at the repo root.

Generations take 5-20 minutes, so the generate_* tools do NOT block: they
spawn the normal CLI as a detached job (see jobs.py) and return a job_id.
Poll check_job(job_id) every minute or two until it reaches a terminal state.

Run manually for debugging:
    uv run python -m slop_fiction_maker.mcp_server
"""

import contextlib
import json
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# The package __init__ (pulled in by any relative import) initializes Gemini
# clients that print to stdout. Stdout is the MCP protocol channel — divert
# import-time noise to stderr or the client's JSON-RPC framing breaks.
with contextlib.redirect_stdout(sys.stderr):
    from .config import (
        AUDIO_STORY_VEO_MODEL_ID,
        OUTPUT_DIR,
        WORKSPACE_DIR,
        find_newest_workspace_audio,
    )
    from .jobs import job_status, start_job

mcp = FastMCP("slop-fiction")

# Veo pricing per generated second (720p, with audio) for cost estimates
_PRICE_PER_SECOND = {"3.1-lite": 0.05, "3.1-fast": 0.10, "3.1": 0.40}


def _ffprobe_duration(path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


@mcp.tool()
def generate_audio_story(
    audio_path: str | None = None,
    topic_hint: str | None = None,
    aspect_ratio: str = "9:16",
    upload: bool = True,
    privacy: str = "unlisted",
) -> dict:
    """Turn an audio file into a Slop Fiction storytime video.

    The audio becomes the master soundtrack; generated visuals act it out in
    over-the-top cultivation-world metaphor. The audio is never cut or
    re-timed. Output is 9:16 by default (a YouTube Short if under 60s) and
    auto-uploads as unlisted unless upload=False.

    audio_path: omit to use the newest audio file dropped into
    slop-video-workspace/. topic_hint steers the visual metaphor
    (e.g. "running out of budget").

    Returns a job_id immediately — generation takes ~1-2 min per 10s of
    audio. Poll check_job(job_id) until state is "succeeded" or "failed".
    """
    if audio_path is None:
        newest = find_newest_workspace_audio()
        if newest is None:
            return {
                "error": f"No audio files in {WORKSPACE_DIR}. Drop one there "
                f"or pass audio_path explicitly.",
            }
        audio_path = str(newest)
    audio_file = Path(audio_path).expanduser().resolve()
    if not audio_file.exists():
        return {"error": f"Audio file not found: {audio_file}"}

    duration = _ffprobe_duration(str(audio_file))
    rate = _PRICE_PER_SECOND.get(AUDIO_STORY_VEO_MODEL_ID, 0.10)
    # Clips are generated at the next supported duration above each beat
    # window, so total generated seconds run ~25% over the audio length.
    estimated_cost = round(duration * 1.25 * rate, 2)

    args = [
        "-m",
        "slop_fiction_maker.audio_to_video",
        str(audio_file),
        "--aspect-ratio",
        aspect_ratio,
        "--privacy",
        privacy,
    ]
    if topic_hint:
        args += ["--topic-hint", topic_hint]
    if not upload:
        args.append("--no-upload")

    entry = start_job(args, label=f"audio-story: {audio_file.name}")
    return {
        "job_id": entry["job_id"],
        "audio": str(audio_file),
        "audio_duration_seconds": round(duration, 1),
        "veo_model": AUDIO_STORY_VEO_MODEL_ID,
        "estimated_cost_usd": estimated_cost,
        "next_step": "Poll check_job(job_id) every ~60s until terminal state.",
    }


@mcp.tool()
def generate_episode(
    topic: str | None = None,
    duration_seconds: int = 180,
    upload: bool = False,
) -> dict:
    """Generate a full 2-5 minute Slop Fiction episode from a story premise.

    Gemini writes a campy xianxia script with per-beat dialogue, Veo generates
    each beat with the characters speaking (native audio), and the clips are
    stitched into one episode. topic=None picks a random cultivation trope.

    Returns a job_id immediately — a 3-minute episode takes 15-30 minutes and
    costs real money (~$0.10/s of video on the default fast model). Poll
    check_job(job_id) until terminal state.
    """
    args = ["-m", "slop_fiction_maker.generate_episode"]
    args += [topic] if topic else ["--random"]
    args += ["--duration", str(duration_seconds)]
    if upload:
        args.append("--upload")

    entry = start_job(args, label=f"episode: {topic or 'random'}")
    return {
        "job_id": entry["job_id"],
        "topic": topic or "random cultivation trope",
        "target_duration_seconds": duration_seconds,
        "next_step": "Poll check_job(job_id) every ~120s until terminal state.",
    }


@mcp.tool()
def check_job(job_id: str) -> dict:
    """Check a generation job started by generate_audio_story/generate_episode.

    Returns state (running/succeeded/failed), beats generated so far, the run
    directory, final video path, YouTube URL (when uploaded), the log tail,
    and — on failure — the exact resume command so already-paid-for clips are
    not regenerated.
    """
    return job_status(job_id)


@mcp.tool()
def list_runs(limit: int = 10) -> list[dict]:
    """List recent generation runs (newest first) with their metadata:
    title, duration, audio mode, local/GCS video paths, and YouTube URL.
    Run directories look like output/YYYY-MM-DD/NNN-slug/.
    """
    metas = sorted(
        OUTPUT_DIR.glob("*/*/metadata.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    runs = []
    for meta_path in metas[:limit]:
        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        run_dir = meta_path.parent
        finals = sorted(str(p) for p in (run_dir / "final").glob("*.mp4"))
        runs.append(
            {
                "run_dir": str(run_dir),
                "title": meta.get("title"),
                "duration_seconds": meta.get("duration_seconds"),
                "audio_mode": meta.get("audio_mode"),
                "video_gcs": meta.get("video_gcs"),
                "youtube_url": meta.get("youtube_url"),
                "final_videos": finals,
            },
        )
    return runs


@mcp.tool()
def upload_run_to_youtube(run_dir: str, privacy: str = "unlisted") -> dict:
    """Upload an existing run's final video to YouTube using the title,
    description, and tags from its metadata.json. Use this to publish a run
    that was generated with upload=False, or to retry a failed upload.

    Requires one-time OAuth setup:
    python -m slop_fiction_maker.youtube_uploader --setup
    """
    run_path = Path(run_dir).expanduser().resolve()
    meta_path = run_path / "metadata.json"
    if not meta_path.exists():
        return {"error": f"No metadata.json in {run_path}"}
    meta = json.loads(meta_path.read_text())

    # Prefer the canonical deliverables, fall back to any final mp4
    candidates = [
        run_path / "final" / "slop_audio_story.mp4",
        run_path / "final" / "slop_fiction_episode_custom_audio.mp4",
        run_path / "final" / "slop_fiction_episode_native_audio.mp4",
    ]
    video = next((c for c in candidates if c.exists()), None)
    if video is None:
        finals = sorted((run_path / "final").glob("*.mp4"))
        video = finals[0] if finals else None
    if video is None:
        return {"error": f"No final video found under {run_path}/final/"}

    with contextlib.redirect_stdout(sys.stderr):
        from .youtube_uploader import is_upload_ready, upload_video

        if not is_upload_ready():
            return {
                "error": "YouTube credentials not set up. Run: "
                "python -m slop_fiction_maker.youtube_uploader --setup",
            }
        video_id = upload_video(
            video_path=str(video),
            title=meta.get("title", video.stem),
            description=meta.get("description", ""),
            tags=meta.get("tags", []),
            privacy_status=privacy,
        )

    youtube_url = f"https://youtu.be/{video_id}"
    meta["youtube_url"] = youtube_url
    meta_path.write_text(json.dumps(meta, indent=2))
    return {"youtube_url": youtube_url, "privacy": privacy, "video": str(video)}


if __name__ == "__main__":
    mcp.run()
