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
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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

# Image model for strong Ghibli-style reference frames
IMAGE_MODEL = os.getenv("SLOP_IMAGE_MODEL", "gemini-2.5-flash-image")

# TTS
TTS_LOCATION = os.getenv("GEMINI_TTS_LOCATION", "global")

# YouTube upload (optional but powerful)
YOUTUBE_CLIENT_SECRETS = os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
YOUTUBE_CREDENTIALS_FILE = os.getenv("YOUTUBE_CREDENTIALS_FILE", "youtube_token.json")

# How many extension steps we are willing to do for a long episode
MAX_EXTENSION_STEPS = int(os.getenv("SLOP_MAX_EXTENSIONS", "35"))

# Default target duration if not specified
DEFAULT_TARGET_SECONDS = 180  # 3 minutes

# Whether to also write local copies (in addition to GCS)
WRITE_LOCAL = os.getenv("SLOP_WRITE_LOCAL", "true").lower() == "true"

# Firestore metadata (re-uses studio if available)
RECORD_TO_FIRESTORE = os.getenv("SLOP_RECORD_TO_FIRESTORE", "true").lower() == "true"
