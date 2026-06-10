"""Optional YouTube upload automation for Slop Fiction episodes.

Setup (one time):
1. Go to Google Cloud Console → APIs & Services → Library → enable "YouTube Data API v3".
2. Create OAuth 2.0 Client ID (Desktop app) → download client_secrets.json.
3. Place it where config.YOUTUBE_CLIENT_SECRETS points (or set the env var).
4. First run will open a browser for you to authorize the channel.
   Token is saved locally (youtube_token.json by default).

The code requests the minimal scopes needed for video upload + metadata.
"""

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import (
    YOUTUBE_CLIENT_SECRETS,
    YOUTUBE_CREDENTIALS_FILE,
    YOUTUBE_EXPECTED_CHANNEL,
)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",  # for the setup channel check
]


def _get_youtube_service():
    creds = None
    token_path = Path(YOUTUBE_CREDENTIALS_FILE)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                YOUTUBE_CLIENT_SECRETS,
                SCOPES,
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def get_authorized_channel(youtube) -> str | None:
    """Title of the channel this token acts as (None if no channel)."""
    response = (
        youtube.channels().list(part="snippet", mine=True, maxResults=1).execute()
    )
    items = response.get("items", [])
    return items[0]["snippet"]["title"] if items else None


class WrongChannelError(RuntimeError):
    """The OAuth token acts as a different channel than YOUTUBE_EXPECTED_CHANNEL."""


def _check_expected_channel(channel: str | None) -> None:
    """Raise WrongChannelError if the authorized channel doesn't match the
    configured expectation. The fix is always the same: redo the auth and
    pick the right identity on Google's channel-chooser page.
    """
    if not YOUTUBE_EXPECTED_CHANNEL:
        return
    if channel and YOUTUBE_EXPECTED_CHANNEL.lower() in channel.lower():
        return
    raise WrongChannelError(
        f"This token uploads to channel '{channel}', but "
        f"YOUTUBE_EXPECTED_CHANNEL is '{YOUTUBE_EXPECTED_CHANNEL}'. "
        f"To fix: delete {YOUTUBE_CREDENTIALS_FILE}, re-run "
        f"'python -m slop_fiction_maker.youtube_uploader --setup', and pick "
        f"the '{YOUTUBE_EXPECTED_CHANNEL}' Brand Account on the channel-chooser "
        f"page during the browser sign-in (not the personal channel).",
    )


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "24",  # Entertainment
    privacy_status: str = "private",  # "public", "unlisted", or "private"
) -> str | None:
    """Upload a video to YouTube.

    Returns the video ID (you can construct https://youtu.be/{id}).
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    youtube = _get_youtube_service()

    # Never upload to the wrong channel (e.g. personal instead of the brand
    # channel) — verify the token's identity before sending any bytes.
    _check_expected_channel(get_authorized_channel(youtube))

    body = {
        "snippet": {
            "title": title[:100],  # YouTube limit
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path,
        chunksize=-1,
        resumable=True,
        mimetype="video/mp4",
    )

    print(f"[youtube] Uploading '{title}' (privacy={privacy_status}) ...")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Uploaded {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"[youtube] Upload complete! https://youtu.be/{video_id}")
    return video_id


SETUP_INSTRUCTIONS = f"""
[youtube setup] No OAuth client found at:
    {YOUTUBE_CLIENT_SECRETS}

One-time manual step (cannot be automated via gcloud):
  1. Open https://console.cloud.google.com/apis/credentials/consent
     and configure the OAuth consent screen (External, add yourself as a test user).
  2. Open https://console.cloud.google.com/apis/credentials
     -> Create Credentials -> OAuth client ID -> Application type: "Desktop app".
  3. Download the JSON and save it as:  {YOUTUBE_CLIENT_SECRETS}
     (this path is gitignored — it will never be committed)
  4. Re-run:  python -m slop_fiction_maker.youtube_uploader --setup
     A browser will open for you to authorize the Slop Fiction channel.
     The token is saved to {YOUTUBE_CREDENTIALS_FILE} (also gitignored).

Note: the YouTube Data API v3 is already enabled for this project.
"""


def run_setup() -> bool:
    """Interactive one-time setup: triggers the OAuth browser flow and
    verifies the authorized channel. Returns True when upload is ready.
    """
    if not Path(YOUTUBE_CLIENT_SECRETS).exists():
        print(SETUP_INSTRUCTIONS)
        return False

    print(f"[youtube setup] Using OAuth client: {YOUTUBE_CLIENT_SECRETS}")
    print("[youtube setup] Authorizing (a browser window may open)...")
    if YOUTUBE_EXPECTED_CHANNEL:
        print(
            f"[youtube setup] IMPORTANT: on Google's channel-chooser page, pick "
            f"the '{YOUTUBE_EXPECTED_CHANNEL}' Brand Account, not your personal "
            f"channel.",
        )
    youtube = _get_youtube_service()

    channel = get_authorized_channel(youtube)
    if not channel:
        print(
            "[youtube setup] Authorized, but no channel found on this account. "
            "Make sure you picked the Google account that owns the Slop Fiction channel.",
        )
        return False

    try:
        _check_expected_channel(channel)
    except WrongChannelError as e:
        print(f"[youtube setup] WRONG CHANNEL — refusing this token.\n  {e}")
        return False

    print(f"[youtube setup] Success! Uploads will go to channel: {channel}")
    print(f"[youtube setup] Token saved at {YOUTUBE_CREDENTIALS_FILE}")
    return True


def is_upload_ready() -> bool:
    """Cheap check (no network): are credentials in place for upload?"""
    return (
        Path(YOUTUBE_CREDENTIALS_FILE).exists()
        or Path(
            YOUTUBE_CLIENT_SECRETS,
        ).exists()
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="YouTube upload setup/check")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run the one-time OAuth setup (browser flow) and verify the channel",
    )
    args = parser.parse_args()
    if args.setup:
        ok = run_setup()
        raise SystemExit(0 if ok else 1)
    parser.print_help()
