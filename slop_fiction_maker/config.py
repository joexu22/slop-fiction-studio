"""Runtime configuration for the Slop Fiction Maker.

Most creative decisions live in style_bible.py.
This file handles model choices, paths, GCS, and YouTube credentials.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# Base paths
ROOT = Path(__file__).parent
REPO_ROOT = ROOT.parent
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Drop folder for audio-story source files: put an audio file here and run
# the audio_to_video CLI / MCP tool with no path — the newest file is used.
WORKSPACE_DIR = Path(
    os.getenv("SLOP_WORKSPACE_DIR", str(REPO_ROOT / "slop-video-workspace")),
)

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".flac", ".aiff"}


def find_newest_workspace_audio() -> Path | None:
    """Newest audio file in the drop folder. This is the no-args UX: drop a
    file in the workspace and kick off a build without typing a path.
    """
    if not WORKSPACE_DIR.is_dir():
        return None
    candidates = [
        p
        for p in WORKSPACE_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


# Reuse the parent repo's storage + config where possible
try:
    from config.default import Default as StudioDefault

    STUDIO_CFG = StudioDefault()
    PROJECT_ID = STUDIO_CFG.PROJECT_ID
    LOCATION = STUDIO_CFG.LOCATION
    GENMEDIA_BUCKET = getattr(STUDIO_CFG, "GENMEDIA_BUCKET", None) or os.getenv(
        "GENMEDIA_BUCKET",
    )
    VIDEO_BUCKET = getattr(STUDIO_CFG, "VIDEO_BUCKET", None) or os.getenv(
        "VIDEO_BUCKET",
    )
except Exception:
    STUDIO_CFG = None
    PROJECT_ID = os.getenv("PROJECT_ID")
    LOCATION = os.getenv("LOCATION", "us-central1")
    GENMEDIA_BUCKET = os.getenv("GENMEDIA_BUCKET")
    VIDEO_BUCKET = os.getenv("VIDEO_BUCKET")

# Veo preferences (extension-heavy workflow)
# Use short version_id keys that match config/veo_models.py (e.g. "3.1", "3.1-fast")
# The long names like "veo-3.1-generate-001" are the actual model names passed internally.
VEO_MODEL_ID = os.getenv("SLOP_VEO_MODEL", "3.1")
VEO_FAST_MODEL_ID = os.getenv("SLOP_VEO_FAST_MODEL", "3.1-fast")

# Audio-story mode (audio_to_video.py): clips are comedic background to a
# master audio track, so the cheapest audio-capable model is the default.
AUDIO_STORY_VEO_MODEL_ID = os.getenv("SLOP_AUDIO_STORY_VEO_MODEL", "3.1-lite")

# Image model for strong Ghibli-style reference frames
IMAGE_MODEL = os.getenv("SLOP_IMAGE_MODEL", "gemini-2.5-flash-image")

# TTS
TTS_LOCATION = os.getenv("GEMINI_TTS_LOCATION", "global")


# YouTube upload (optional but powerful)
# Bare filenames resolve against the repo root (not the CWD) so upload works
# no matter where the CLI / MCP server / agent was launched from.
def _repo_path(env_var: str, default_name: str) -> str:
    value = os.getenv(env_var, default_name)
    p = Path(value)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return str(p)


YOUTUBE_CLIENT_SECRETS = _repo_path("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
YOUTUBE_CREDENTIALS_FILE = _repo_path("YOUTUBE_CREDENTIALS_FILE", "youtube_token.json")

# Guard against uploading to the wrong channel: when set, setup and every
# upload verify that the OAuth token acts as a channel whose name contains
# this string (case-insensitive). The Slop Fiction channel is a Brand Account,
# so the right identity must be picked on Google's channel-chooser page during
# the one-time auth — this catches the mistake of picking the personal channel.
YOUTUBE_EXPECTED_CHANNEL = os.getenv("YOUTUBE_EXPECTED_CHANNEL", "")

# How many extension steps we are willing to do for a long episode
MAX_EXTENSION_STEPS = int(os.getenv("SLOP_MAX_EXTENSIONS", "35"))

# Default target duration if not specified
DEFAULT_TARGET_SECONDS = 180  # 3 minutes

# Whether to also write local copies (in addition to GCS)
WRITE_LOCAL = os.getenv("SLOP_WRITE_LOCAL", "true").lower() == "true"

# Firestore metadata (re-uses studio if available)
RECORD_TO_FIRESTORE = os.getenv("SLOP_RECORD_TO_FIRESTORE", "true").lower() == "true"
