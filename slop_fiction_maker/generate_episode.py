"""Slop Fiction — Fully Automated Episode Generator (one-shot, hands-off)

This is the main entrypoint for the AI skill.

Usage from chat/agent:
    from slop_fiction_maker.generate_episode import generate_slop_episode
    result = generate_slop_episode(topic="your ridiculous premise here")

Or CLI:
    python -m slop_fiction_maker.generate_episode "a young master gets betrayed and starts dual cultivating with a demonic jade beauty"
"""

import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime

from common.storage import store_to_gcs

from .audio import (
    get_duration,
)  # only get_duration is needed in the default (native) path
from .config import (
    OUTPUT_DIR,
    RECORD_TO_FIRESTORE,
    WRITE_LOCAL,
)
from .metadata import generate_thumbnail, generate_title_and_description
from .script_generator import SlopFictionScript, generate_slop_script
from .style_bible import STYLE
from .video_chainer import generate_per_beat_videos

# Lazy import for YouTube uploader (optional feature, not always needed)
# This avoids requiring google-auth-oauthlib unless --upload is used.


@dataclass
class GenerationResult:
    topic: str
    script: dict
    final_video_gcs_uri: str
    thumbnail_gcs: str
    title: str
    description: str
    tags: list
    local_video_path: str | None = None
    youtube_url: str | None = None
    duration_seconds: float = 0.0


def generate_slop_episode(
    topic: str | None = None,
    target_duration_seconds: int = 180,
    upload_to_youtube: bool = False,
    youtube_privacy: str = "private",
    use_custom_narration: bool = False,
    start_beat: int = 1,
) -> GenerationResult:
    """The one function to rule them all.

    Fully hands-off.

    By default (use_custom_narration=False):
    - The script writer produces explicit "dialogue" lines per beat.
    - We generate one independent short video per beat (dialogue is in the
      prompt so native Veo audio contains the characters speaking).
    - All per-beat clips are then concatenated in post-production into the
      final episode video.

    When use_custom_narration=True:
    - Also generates a separate over-the-top narrator track (TTS + Lyria)
      and mixes it over the assembled final video.

    start_beat (1-based):
    - Start video generation from this beat index. Previous beats must already
      have their beat_00X.mp4 files in the clips/ folder (manually download
      the successful ones from the original GCS URIs in the log).
    - After generation, the code will collect *all* beat clips (1..N) and
      stitch them together, so previous successful clips + newly generated
      ones are combined into one final video.
    """
    # Clean dated + serialized output structure
    # output/YYYY-MM-DD/NNN-short-slug/
    date_str = datetime.now().strftime("%Y-%m-%d")
    date_dir = OUTPUT_DIR / date_str
    date_dir.mkdir(parents=True, exist_ok=True)

    # Find next serial number for the day
    existing_serials = []
    for d in date_dir.iterdir():
        if d.is_dir() and len(d.name) >= 3 and d.name[:3].isdigit():
            try:
                existing_serials.append(int(d.name[:3]))
            except ValueError:
                pass
    next_serial = max(existing_serials or [0]) + 1

    safe_slug = (topic or "random-cultivation-slop").lower()
    safe_slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in safe_slug)
    safe_slug = "-".join(safe_slug.split())[:40].strip("-") or "episode"

    run_dir = date_dir / f"{next_serial:03d}-{safe_slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Ensure clean sub-structure
    (run_dir / "clips").mkdir(exist_ok=True)
    (run_dir / "final").mkdir(exist_ok=True)
    # "audio/" subdir is only created when use_custom_narration=True (inside that branch)

    # For GCS filenames and metadata (stable within this run)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = safe_slug

    print(f"\n{'=' * 60}")
    print(" SLOP FICTION EPISODE GENERATOR")
    print(f" Topic: {topic or 'RANDOM'}")
    print(f" Target duration: ~{target_duration_seconds}s")
    print(f" Output: {run_dir}")
    print("  (clips/, audio/, final/ subfolders for clean organization)")
    print(f"{'=' * 60}\n")

    # 1. SCRIPT (the creative heart)
    print(
        "[1/5] Generating campy cultivation script with explicit in-scene dialogue...",
    )
    script: SlopFictionScript = generate_slop_script(
        topic=topic,
        target_duration_seconds=target_duration_seconds,
    )
    print(f"  Narrator persona (for optional custom track): {script.narrator_persona}")
    print(f"  Beats: {len(script.scene_beats)}")
    (run_dir / "script.json").write_text(script.to_json())

    # 2. VIDEO — per-beat independent clips (no more extension chaining)
    # Each beat gets its own short video (dialogue is in the prompt so native
    # audio contains the characters speaking). We then stitch them in post.
    #
    # Resume support: if start_beat > 1, we expect the user to have already
    # placed beat_001.mp4 ... beat_(start_beat-1).mp4 in the clips/ folder
    # (manually gsutil cp them from the original log's GCS URIs).
    print(
        f"\n[2/5] Generating independent per-beat videos (starting from beat {start_beat}) ...",
    )
    beat_video_uris = generate_per_beat_videos(script, start_beat=start_beat)
    print(
        f"  Generated {len(beat_video_uris)} new per-beat videos (from beat {start_beat})",
    )

    final_video_gcs = beat_video_uris[-1] if beat_video_uris else ""

    # Download only the newly generated clips
    clips_dir = run_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    local_beat_clips: list[str] = []

    # Collect any pre-existing clips for beats before start_beat
    for i in range(1, start_beat):
        existing = clips_dir / f"beat_{i:03d}.mp4"
        if existing.exists():
            local_beat_clips.append(str(existing))
        else:
            print(f"  Warning: expected previous clip {existing} not found.")

    # Download the new ones
    for idx, uri in enumerate(beat_video_uris, start_beat):
        local_clip = clips_dir / f"beat_{idx:03d}.mp4"
        subprocess.check_call(["gsutil", "cp", uri, str(local_clip)])
        local_beat_clips.append(str(local_clip))

    print(f"  Now have {len(local_beat_clips)} per-beat clips in clips/")

    # Stitch ALL clips (previous + newly generated) into one final video.
    # This gives you the complete episode even when resuming after a crash.
    final_native = str(run_dir / "final" / "slop_fiction_episode_native_audio.mp4")
    (run_dir / "final").mkdir(exist_ok=True)
    print(f"  Stitching {len(local_beat_clips)} clips into {final_native}...")
    from .audio import assemble_final_video

    assemble_final_video(local_beat_clips, final_native)
    print(f"  Assembled final native video: {final_native}")

    # === AUDIO LAYER ===
    # Default behavior (2026 update): We do NOT generate a separate custom narrator.
    # The script already wrote explicit "dialogue" that was fed into the Veo prompts.
    # Veo therefore produces native audio containing the characters speaking.
    # The final_native from above is the main deliverable.

    if use_custom_narration:
        print(
            "\n[3/6] Custom narration requested — generating over-the-top TTS narrator + music...",
        )
        (run_dir / "audio").mkdir(exist_ok=True)

        # Lazy import so the default path doesn't pull in TTS/Lyria clients
        from .audio import (
            generate_background_music,
            synthesize_narration,
        )
        from .audio import (
            mix_scene as mix_one,
        )

        full_narration = " ".join(b.narration_text for b in script.scene_beats)

        narration_local = str(run_dir / "audio" / "custom_narration.wav")
        synthesize_narration(
            full_narration_text=full_narration,
            persona=script.narrator_persona,
            output_path=narration_local,
        )

        music_local = str(run_dir / "audio" / "lyria_music.wav")
        try:
            generate_background_music(
                prompt=STYLE.music_base,
                output_path=music_local,
            )
        except Exception as e:
            print(f"  Music generation failed (will continue with voice only): {e}")
            music_local = None

        print("[4/6] Mixing custom narrator track over the native video...")
        custom_mixed = str(run_dir / "final" / "slop_fiction_episode_custom_audio.mp4")
        mix_one(
            video_path=final_native,
            voice_path=narration_local,
            music_path=music_local,
            output_path=custom_mixed,
        )

        duration = get_duration(custom_mixed)
        print(f"  Custom mixed version duration: {duration:.1f}s")
        final_mixed = custom_mixed
        audio_mode = "custom-narrated"
    else:
        print(
            "\n[3/5] Using native Veo audio only (dialogue is generated inside the video by the model).",
        )
        duration = get_duration(final_native)
        final_mixed = final_native
        audio_mode = "native-veo-dialogue"

    # 3. METADATA + THUMBNAIL
    print("\n[3/5] Generating title, description, tags, and thumbnail...")
    title, description, tags = generate_title_and_description(script)
    thumbnail_gcs = generate_thumbnail(script, run_dir / "thumbnail.png")

    meta = {
        "title": title,
        "description": description,
        "tags": tags,
        "duration_seconds": duration,
        "topic": script.topic,
        "narrator_persona": script.narrator_persona,
        "audio_mode": audio_mode,
        "video_gcs": final_video_gcs,
        "thumbnail_gcs": thumbnail_gcs,
        "generated_at": timestamp,
    }
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    # 4. STORE FINAL ARTIFACTS TO GCS (via the mandated studio helper)
    print("\n[4/5] Uploading final assets to GCS...")
    final_gcs = store_to_gcs(
        folder="slop_fiction_episodes",
        file_name=f"{timestamp}_{safe_topic}.mp4",
        mime_type="video/mp4",
        contents=final_mixed,
    )
    print(f"  Final episode GCS: {final_gcs}")

    if thumbnail_gcs and os.path.exists(str(run_dir / "thumbnail.png")):
        thumb_gcs = store_to_gcs(
            folder="slop_fiction_thumbnails",
            file_name=f"{timestamp}_{safe_topic}.png",
            mime_type="image/png",
            contents=str(run_dir / "thumbnail.png"),
        )
    else:
        thumb_gcs = thumbnail_gcs

    # 5. OPTIONAL YOUTUBE UPLOAD
    youtube_url = None
    if upload_to_youtube:
        print("\n[5/5] Uploading to YouTube...")
        try:
            from .youtube_uploader import upload_video

            video_id = upload_video(
                video_path=final_mixed,
                title=title,
                description=description,
                tags=tags,
                privacy_status=youtube_privacy,
            )
            if video_id:
                youtube_url = f"https://youtu.be/{video_id}"
        except Exception as e:
            print(f"  YouTube upload failed (you can upload manually): {e}")

    # Record to Firestore (if the studio is configured)
    if RECORD_TO_FIRESTORE:
        try:
            from common.metadata import MediaItem, add_media_item_to_firestore

            item = MediaItem(
                prompt=script.topic,
                model="veo-3.1-per-beat",
                mime_type="video/mp4",
                gcsuri=final_gcs,
                duration=duration,
                comment=f"Slop Fiction — {script.narrator_persona}",
            )
            add_media_item_to_firestore(item)
        except Exception as e:
            print(f"  (Non-fatal) Could not record to Firestore: {e}")

    result = GenerationResult(
        topic=script.topic,
        script=script.to_dict(),
        final_video_gcs_uri=final_gcs,
        thumbnail_gcs=thumb_gcs,
        title=title,
        description=description,
        tags=tags,
        local_video_path=str(final_mixed) if WRITE_LOCAL else None,
        youtube_url=youtube_url,
        duration_seconds=duration,
    )

    print(f"\n{'=' * 60}")
    print(" EPISODE COMPLETE — SLAP IT ON THE INTERNET")
    print(f" Title: {title}")
    print(f" Audio mode: {audio_mode}")
    print(f" Video: {final_gcs}")
    if youtube_url:
        print(f" YouTube: {youtube_url}")
    print(f" Local copy: {final_mixed}")
    print(f"{'=' * 60}\n")

    return result


# ---------------- CLI ----------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate one fully automated Slop Fiction episode.",
    )
    parser.add_argument(
        "topic",
        nargs="?",
        help="Story premise (e.g. 'a young outer disciple finds a talking sword')",
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="Generate a random cultivation trope topic",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=180,
        help="Target duration in seconds (120-300)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload to YouTube after generation",
    )
    parser.add_argument(
        "--privacy",
        default="private",
        choices=["public", "unlisted", "private"],
    )
    parser.add_argument(
        "--with-custom-narration",
        "--custom-narration",
        dest="use_custom_narration",
        action="store_true",
        help="Also generate and mix a separate over-the-top custom narrator track (TTS). "
        "Default is OFF — dialogue is written into the video prompts and spoken by characters via Veo's native audio.",
    )
    parser.add_argument(
        "--start-beat",
        type=int,
        default=1,
        help="1-based beat index to start video generation from. "
        "Useful for resuming after a crash or content filter. "
        "You must manually ensure that beat_001.mp4 .. beat_(N-1).mp4 already exist in the clips/ folder "
        "(download them from GCS using the URIs printed in the original log). "
        "The script will generate from this point onward and then stitch ALL clips (previous + new) together.",
    )

    args = parser.parse_args()

    topic = args.topic
    if args.random or not topic:
        from .style_bible import get_cultivation_topic_seed

        topic = f"A story about {get_cultivation_topic_seed()}"

    result = generate_slop_episode(
        topic=topic,
        target_duration_seconds=args.duration,
        upload_to_youtube=args.upload,
        youtube_privacy=args.privacy,
        use_custom_narration=args.use_custom_narration,
        start_beat=args.start_beat,
    )

    print("\nResult JSON:")
    print(json.dumps(asdict(result), indent=2, default=str))
