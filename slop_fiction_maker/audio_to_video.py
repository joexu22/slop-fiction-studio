"""Slop Fiction — Audio-Story Video Generator (storytime mode).

The inverse of generate_episode: a user-provided audio file is the master
soundtrack, and we generate slop-fiction visuals that act it out.

Pipeline:
1. Transcribe the audio with Gemini (segment timestamps).
2. Plan a storyboard of contiguous beats, each owning an exact time window
   of the audio (see audio_story.py for the timing contract).
3. Generate one Veo clip per beat (default: the cheapest audio-capable
   model). Native audio is limited to short comedic exclamations.
4. Post: trim each clip to its exact window, concatenate, then lay the
   original audio on top at full volume with the Veo audio ducked low.

The master audio is never cut, stretched, or re-timed. Video bends to fit
the audio, not the other way around.

Usage from chat/agent:
    from slop_fiction_maker.audio_to_video import generate_audio_story_video
    result = generate_audio_story_video("slop-video-workspace/Kennewick Rd.m4a")

Or CLI:
    python -m slop_fiction_maker.audio_to_video "slop-video-workspace/Kennewick Rd.m4a"

    # Upload only the video track (no master audio mix):
    python -m slop_fiction_maker.audio_to_video "slop-video-workspace/Kennewick Rd.m4a" \
        --upload-variants video-track
"""

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from common.storage import store_to_gcs
from config.veo_models import get_veo_model_config
from models.veo import VideoGenerationRequest, generate_video

from .audio import (
    assemble_final_video,
    get_duration,
    mix_master_audio,
    normalize_and_trim_clip,
)
from .audio_story import (
    AudioStoryboard,
    make_audio_story_veo_prompt,
    plan_audio_storyboard,
    storyboard_from_dict,
    transcribe_audio,
)
from .config import (
    AUDIO_STORY_VEO_MODEL_ID,
    OUTPUT_DIR,
    RECORD_TO_FIRESTORE,
    VEO_FAST_MODEL_ID,
    WORKSPACE_DIR,
    find_newest_workspace_audio,
)


@dataclass
class AudioStoryResult:
    audio_path: str
    storyboard: dict
    final_video_gcs_uri: str
    title: str
    description: str
    tags: list
    local_video_path: str | None = None
    youtube_url: str | None = None  # kept for backward compat (points to mixed)
    youtube_url_mixed: str | None = None
    youtube_url_video_track: str | None = None
    duration_seconds: float = 0.0


def _make_run_dir(slug_source: str) -> Path:
    """Same dated + serialized layout as generate_episode:
    output/YYYY-MM-DD/NNN-short-slug/ with clips/ and final/ subfolders.
    """
    date_dir = OUTPUT_DIR / datetime.now().strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    existing_serials = []
    for d in date_dir.iterdir():
        if d.is_dir() and len(d.name) >= 3 and d.name[:3].isdigit():
            try:
                existing_serials.append(int(d.name[:3]))
            except ValueError:
                pass
    next_serial = max(existing_serials or [0]) + 1

    safe_slug = slug_source.lower()
    safe_slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in safe_slug)
    safe_slug = "-".join(safe_slug.split())[:40].strip("-") or "audio-story"

    run_dir = date_dir / f"{next_serial:03d}-{safe_slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "clips").mkdir(exist_ok=True)
    (run_dir / "final").mkdir(exist_ok=True)
    return run_dir


def _pick_model(aspect_ratio: str) -> str:
    """Validate the configured audio-story model against the registry,
    falling back to the fast tier if it is unknown or can't do the
    requested aspect ratio.
    """
    cfg = get_veo_model_config(AUDIO_STORY_VEO_MODEL_ID)
    if cfg and aspect_ratio in cfg.supported_aspect_ratios:
        return AUDIO_STORY_VEO_MODEL_ID
    print(
        f"[audio_to_video] Model '{AUDIO_STORY_VEO_MODEL_ID}' unavailable or "
        f"doesn't support {aspect_ratio}; falling back to '{VEO_FAST_MODEL_ID}'.",
    )
    return VEO_FAST_MODEL_ID


def _generate_beat_clips(
    storyboard: AudioStoryboard,
    model_id: str,
    aspect_ratio: str,
    resolution: str,
    start_beat: int = 1,
) -> list[str]:
    """Generate one independent Veo clip per beat. Returns GCS URIs in
    story order, starting from start_beat.
    """
    beat_uris: list[str] = []
    beats = storyboard.beats

    for beat in beats[start_beat - 1 :]:
        print(f"\n=== Generating beat {beat.index}/{len(beats)} ===")
        print(f"  Window: {beat.start:.1f}s - {beat.end:.1f}s ({beat.window:.1f}s)")
        print(f"  Clip duration: {beat.veo_duration}s (trimmed to window in post)")
        print(f"  Transcript: {beat.transcript_text[:70]}...")
        if beat.exclamation:
            print(f'  Exclamation: "{beat.exclamation}"')

        request = VideoGenerationRequest(
            prompt=make_audio_story_veo_prompt(beat, storyboard),
            duration_seconds=beat.veo_duration,
            video_count=1,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            enhance_prompt=True,
            generate_audio=True,
            model_version_id=model_id,
            person_generation="Allow (Adults only)",
            negative_prompt=(
                "continuous talking, narration, voiceover, singing, "
                "text, subtitles, watermark, logo, deformed, blurry motion, "
                "bad anatomy, violence, blood, dark, despair"
            ),
        )

        try:
            video_uris, _ = generate_video(request)
            beat_uris.append(video_uris[0])
            print(f"  Beat {beat.index} generated: {video_uris[0]}")
        except Exception as e:
            print(f"  Beat {beat.index} generation failed: {e}")
            print(
                f"  To resume: --resume-dir <run dir> --start-beat {beat.index} "
                f"(clips for earlier beats must exist in clips/)",
            )
            raise

    return beat_uris


def generate_audio_story_video(
    audio_path: str | None = None,
    topic_hint: str | None = None,
    aspect_ratio: str = "9:16",
    resolution: str = "720p",
    upload_to_youtube: bool = True,
    youtube_privacy: str = "unlisted",
    native_volume: float | None = None,
    resume_dir: str | None = None,
    start_beat: int = 1,
    upload_variants: str = "both",
) -> AudioStoryResult:
    """One-shot: audio file in, finished storytime video out.

    audio_path=None: use the newest audio file in the workspace drop folder
    (slop-video-workspace/ — see WORKSPACE_DIR in config.py).

    Upload defaults to YouTube as *unlisted*: review via the link, then flip
    to public in YouTube Studio. Requires the one-time OAuth setup
    (python -m slop_fiction_maker.youtube_uploader --setup); until then the
    upload step is skipped with a pointer to setup (non-fatal).

    upload_variants: "both" (default), "mixed", or "video-track".
    - "both": upload both the final mixed video (with master audio) and the
      raw video track.
    - "mixed": only the final mixed version (slop_audio_story.mp4).
    - "video-track": only the concatenated Veo video track (video_track.mp4).

    resume_dir + start_beat: point at an existing run directory to reuse its
    storyboard.json (the beat windows must match the already-generated clips)
    and continue generation from start_beat. Clips for beats before
    start_beat must already exist as clips/beat_NNN.mp4.
    """
    if audio_path is None:
        newest = find_newest_workspace_audio()
        if newest is None:
            raise FileNotFoundError(
                f"No audio path given and no audio files found in {WORKSPACE_DIR}. "
                f"Drop an audio file there or pass a path explicitly.",
            )
        print(f"[audio_to_video] Using newest workspace audio: {newest.name}")
        audio_path = str(newest)

    audio_file = Path(audio_path).expanduser().resolve()
    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    audio_duration = get_duration(str(audio_file))
    if audio_duration <= 0:
        raise ValueError(f"Could not read duration of {audio_file}")

    print(f"\n{'=' * 60}")
    print(" SLOP FICTION AUDIO-STORY GENERATOR")
    print(f" Audio: {audio_file.name} ({audio_duration:.1f}s)")
    print(f" Aspect: {aspect_ratio} @ {resolution}")
    print(f"{'=' * 60}\n")

    # 0. Run directory (new or resumed)
    if resume_dir:
        run_dir = Path(resume_dir).expanduser().resolve()
        storyboard_path = run_dir / "storyboard.json"
        if not storyboard_path.exists():
            raise FileNotFoundError(f"No storyboard.json in {run_dir} to resume from")
        print(f"[resume] Reusing storyboard from {storyboard_path}")
        storyboard = storyboard_from_dict(json.loads(storyboard_path.read_text()))
    else:
        run_dir = _make_run_dir(audio_file.stem)
        print(f" Output: {run_dir}\n")

        # 1. TRANSCRIBE (timestamps drive everything downstream)
        print("[1/5] Transcribing audio with timestamps...")
        transcript, _ = transcribe_audio(str(audio_file), audio_duration)
        (run_dir / "transcript.json").write_text(
            json.dumps([asdict(s) for s in transcript], indent=2),
        )
        for seg in transcript:
            print(f"  [{seg.start:5.1f}s - {seg.end:5.1f}s] {seg.text}")

        # 2. STORYBOARD (beats own exact audio windows)
        print("\n[2/5] Planning slop-fiction storyboard against the timeline...")
        storyboard = plan_audio_storyboard(
            audio_path=str(audio_file),
            audio_duration=audio_duration,
            transcript=transcript,
            topic_hint=topic_hint,
        )
        (run_dir / "storyboard.json").write_text(storyboard.to_json())
        print(f"  Story: {storyboard.story_summary}")
        print(f"  Beats: {len(storyboard.beats)}")
        total_clip_seconds = sum(b.veo_duration for b in storyboard.beats)
        print(f"  Total clip seconds to generate: {total_clip_seconds}s")

    # 3. VIDEO — one clip per beat
    model_id = _pick_model(aspect_ratio)
    print(f"\n[3/5] Generating per-beat clips with Veo '{model_id}'...")
    beat_uris = _generate_beat_clips(
        storyboard,
        model_id=model_id,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        start_beat=start_beat,
    )

    clips_dir = run_dir / "clips"
    clips_dir.mkdir(exist_ok=True)

    # Download newly generated clips (pre-existing ones stay in place on resume)
    for beat, uri in zip(storyboard.beats[start_beat - 1 :], beat_uris):
        local_clip = clips_dir / f"beat_{beat.index:03d}.mp4"
        subprocess.check_call(["gsutil", "cp", uri, str(local_clip)])

    # 4. POST — trim each clip to its exact audio window, concat, master mix
    print("\n[4/5] Post-production: trimming clips to audio windows + mixing...")
    trimmed_paths: list[str] = []
    for beat in storyboard.beats:
        raw_clip = clips_dir / f"beat_{beat.index:03d}.mp4"
        if not raw_clip.exists():
            raise FileNotFoundError(
                f"Missing clip {raw_clip} (beat {beat.index}). "
                f"On resume, download earlier clips from their GCS URIs first.",
            )
        trimmed = clips_dir / f"beat_{beat.index:03d}_trimmed.mp4"
        normalize_and_trim_clip(str(raw_clip), str(trimmed), beat.window)
        trimmed_paths.append(str(trimmed))
        print(f"  Beat {beat.index}: trimmed to {beat.window:.2f}s")

    silent_concat = str(run_dir / "final" / "video_track.mp4")
    assemble_final_video(trimmed_paths, silent_concat)

    final_video = str(run_dir / "final" / "slop_audio_story.mp4")
    mix_master_audio(
        video_path=silent_concat,
        master_audio_path=str(audio_file),
        output_path=final_video,
        native_volume=native_volume,
    )
    duration = get_duration(final_video)
    print(
        f"  Final video: {final_video} ({duration:.1f}s vs audio {audio_duration:.1f}s)",
    )

    # 5. METADATA + GCS + optional YouTube
    print("\n[5/5] Metadata + upload...")
    is_short = duration <= 60 and aspect_ratio == "9:16"
    base_title = (topic_hint or storyboard.story_summary or audio_file.stem).strip()
    if len(base_title) > 70:
        base_title = base_title[:67] + "..."
    title = f"{base_title} | Slop Fiction Storytime"
    if is_short:
        title += " #Shorts"

    description = f"""\
{storyboard.story_summary}

A Slop Fiction STORYTIME production — a real audio story acted out by the
silicon dream-engines in gloriously over-the-top cultivation-world metaphor.
The visuals are deliberately unhinged. The audio is real. The slop is the point.

#SlopFiction #Storytime #Cultivation #Xianxia #AIgenerated

More questionable scriptures from the Slop Sect:
https://www.youtube.com/@slopfictionYT
"""
    tags = [
        "slop fiction",
        "storytime",
        "cultivation",
        "xianxia",
        "ai generated",
        "ghibli style",
        "ai video",
        "shorts" if is_short else "story",
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_gcs = store_to_gcs(
        folder="slop_fiction_audio_stories",
        file_name=f"{timestamp}_{run_dir.name}.mp4",
        mime_type="video/mp4",
        contents=final_video,
    )
    print(f"  Final GCS: {final_gcs}")

    meta = {
        "title": title,
        "description": description,
        "tags": tags,
        "duration_seconds": duration,
        "audio_source": str(audio_file),
        "audio_mode": "master-audio-story",
        "aspect_ratio": aspect_ratio,
        "veo_model": model_id,
        "video_gcs": final_gcs,
        "generated_at": timestamp,
    }
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=2))

    youtube_url_mixed = None
    youtube_url_video_track = None

    if upload_to_youtube:
        try:
            from .youtube_uploader import is_upload_ready, upload_video

            if not is_upload_ready():
                print(
                    "  YouTube upload skipped: no credentials yet. One-time setup:\n"
                    "    python -m slop_fiction_maker.youtube_uploader --setup",
                )
            else:
                video_track_path = str(run_dir / "final" / "video_track.mp4")

                if upload_variants in ("both", "mixed"):
                    print(
                        f"  Uploading mixed version to YouTube ({youtube_privacy})...",
                    )
                    video_id = upload_video(
                        video_path=final_video,
                        title=title,
                        description=description,
                        tags=tags,
                        privacy_status=youtube_privacy,
                    )
                    if video_id:
                        youtube_url_mixed = f"https://youtu.be/{video_id}"

                if upload_variants in ("both", "video-track"):
                    if Path(video_track_path).exists():
                        vt_title = title.replace(
                            " | Slop Fiction Storytime",
                            " | Slop Fiction Storytime (Video Track)",
                        )
                        print(
                            f"  Uploading video track to YouTube ({youtube_privacy})...",
                        )
                        vt_video_id = upload_video(
                            video_path=video_track_path,
                            title=vt_title,
                            description=description,
                            tags=tags + ["video track"],
                            privacy_status=youtube_privacy,
                        )
                        if vt_video_id:
                            youtube_url_video_track = f"https://youtu.be/{vt_video_id}"
                    else:
                        print("  Video track not found, skipping video-track upload.")

        except Exception as e:
            print(
                f"  YouTube upload failed (video is safe locally + in GCS): {e}\n"
                f"  If this is an auth problem, re-run: "
                f"python -m slop_fiction_maker.youtube_uploader --setup",
            )

    if RECORD_TO_FIRESTORE:
        try:
            from common.metadata import MediaItem, add_media_item_to_firestore

            add_media_item_to_firestore(
                MediaItem(
                    prompt=storyboard.story_summary,
                    model=f"veo-{model_id}-audio-story",
                    mime_type="video/mp4",
                    gcsuri=final_gcs,
                    duration=duration,
                    comment=f"Slop Fiction audio story — {audio_file.name}",
                ),
            )
        except Exception as e:
            print(f"  (Non-fatal) Could not record to Firestore: {e}")

    # Backward compat: youtube_url points to the mixed version when available
    youtube_url = youtube_url_mixed

    result = AudioStoryResult(
        audio_path=str(audio_file),
        storyboard=storyboard.to_dict(),
        final_video_gcs_uri=final_gcs,
        title=title,
        description=description,
        tags=tags,
        local_video_path=final_video,
        youtube_url=youtube_url,
        youtube_url_mixed=youtube_url_mixed,
        youtube_url_video_track=youtube_url_video_track,
        duration_seconds=duration,
    )

    print(f"\n{'=' * 60}")
    print(" AUDIO STORY COMPLETE — SLAP IT ON THE INTERNET")
    print(f" Title: {title}")
    print(f" Video: {final_gcs}")
    if youtube_url_mixed:
        print(f" YouTube (mixed): {youtube_url_mixed}")
    if youtube_url_video_track:
        print(f" YouTube (video track): {youtube_url_video_track}")
    print(f" Local copy: {final_video}")
    print(f"{'=' * 60}\n")

    return result


# ---------------- CLI ----------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Turn an audio file into a Slop Fiction storytime video "
        "(the audio is the master soundtrack; visuals act it out).",
    )
    parser.add_argument(
        "audio",
        nargs="?",
        default=None,
        help="Path to the audio file (m4a/mp3/wav/...). Omit to use the newest "
        "audio file in slop-video-workspace/",
    )
    parser.add_argument(
        "--topic-hint",
        help="Optional hint about what the audio is about, to steer the visual metaphor "
        "(e.g. 'running out of budget')",
    )
    parser.add_argument(
        "--aspect-ratio",
        default="9:16",
        choices=["9:16", "16:9"],
        help="9:16 (Shorts, default) or 16:9",
    )
    parser.add_argument("--resolution", default="720p", choices=["720p", "1080p"])
    parser.add_argument(
        "--native-volume",
        type=float,
        default=None,
        help="Volume of the Veo native audio under the master track "
        "(default from style_bible: 0.25)",
    )
    parser.add_argument(
        "--no-upload",
        dest="upload",
        action="store_false",
        help="Skip the YouTube upload (default is auto-upload as unlisted)",
    )
    parser.add_argument(
        "--privacy",
        default="unlisted",
        choices=["public", "unlisted", "private"],
        help="YouTube privacy for the auto-upload (default: unlisted)",
    )
    parser.add_argument(
        "--upload-variants",
        default="both",
        choices=["both", "mixed", "video-track"],
        help="Which versions to upload to YouTube. "
        "'both' (default) uploads the final mixed video (with master audio) "
        "and the raw video track. 'mixed' uploads only the mixed version. "
        "'video-track' uploads only the concatenated Veo video track.",
    )
    parser.add_argument(
        "--resume-dir",
        help="Existing run directory to resume (reuses its storyboard.json so "
        "beat windows match the already-generated clips)",
    )
    parser.add_argument(
        "--start-beat",
        type=int,
        default=1,
        help="1-based beat index to start generation from (use with --resume-dir). "
        "Clips for earlier beats must already exist as clips/beat_NNN.mp4.",
    )

    args = parser.parse_args()

    result = generate_audio_story_video(
        audio_path=args.audio,
        topic_hint=args.topic_hint,
        aspect_ratio=args.aspect_ratio,
        resolution=args.resolution,
        upload_to_youtube=args.upload,
        youtube_privacy=args.privacy,
        native_volume=args.native_volume,
        resume_dir=args.resume_dir,
        start_beat=args.start_beat,
        upload_variants=args.upload_variants,
    )

    print("\nResult JSON:")
    print(json.dumps(asdict(result), indent=2, default=str))
