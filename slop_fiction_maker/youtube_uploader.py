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

from .config import YOUTUBE_CLIENT_SECRETS, YOUTUBE_CREDENTIALS_FILE

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


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
                YOUTUBE_CLIENT_SECRETS, SCOPES,
            )
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


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
