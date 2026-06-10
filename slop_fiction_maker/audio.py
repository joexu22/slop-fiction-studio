"""Audio layer for Slop Fiction episodes.

- Over-the-top narration via Gemini TTS (preferred for style prompting) or Chirp.
- Epic cultivation / Ghibli-style music via Lyria.
- Voice-first timing + speed-fitting logic adapted from the excellent
  story-generator skill (with the same 1.25x guardrail philosophy).
- Per-beat mixing + final assembly helpers.

This module is intentionally self-contained so the skill can run hands-off.
"""

import os
import subprocess
from dataclasses import dataclass

from google.cloud import texttospeech

from models.lyria import generate_music_with_lyria

from .config import TTS_LOCATION
from .style_bible import STYLE


@dataclass
class AudioAssets:
    narration_path: str  # local wav of the full narration (or per-beat)
    music_path: str | None
    mixed_video_path: str | None = None


def synthesize_narration(
    full_narration_text: str,
    persona: str,
    output_path: str,
    voice_name: str = "Callirrhoe",
) -> str:
    """Generate the over-the-top narration audio.

    We prefer Gemini TTS when available because the prompt can strongly
    influence the delivery style ("bombastic", "smug young master", etc.).
    Falls back to standard Chirp 3 HD voices.
    """
    client_options = {}
    if TTS_LOCATION and TTS_LOCATION != "global":
        client_options["api_endpoint"] = f"{TTS_LOCATION}-texttospeech.googleapis.com"

    client = texttospeech.TextToSpeechClient(client_options=client_options)

    # Build a strong style prompt for Gemini TTS
    style_prompt = (
        f"Deliver this cultivation slop narration in an extremely over-the-top, "
        f"campy, theatrical style. Persona: {persona}. "
        f"Be dramatic, bombastic, slightly unhinged, perfect for a wuxia drama "
        f"voice actor who takes every line completely seriously. "
        f"Emphasize key cultivation terms with weight and flair."
    )

    try:
        # Gemini TTS path (newer, promptable)
        response = client.synthesize_speech(
            input=texttospeech.SynthesisInput(
                text=full_narration_text,
                prompt=style_prompt,
            ),
            voice=texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name=voice_name,
                model_name="gemini-tts",  # will gracefully fall back if not available
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
            ),
        )
    except Exception:
        # Fallback to classic Chirp 3 HD
        response = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=full_narration_text),
            voice=texttospeech.VoiceSelectionParams(
                language_code="en-US",
                name=f"en-US-Chirp3-HD-{voice_name}",
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            ),
        )

    with open(output_path, "wb") as f:
        f.write(response.audio_content)

    return output_path


def generate_background_music(
    prompt: str,
    output_path: str,
    sample_count: int = 1,
) -> str:
    """Generate Lyria music. We always append the "strictly instrumental" guardrail.
    """
    safe_prompt = f"{prompt}, {STYLE.music_base}, strictly instrumental, no vocals, no voice, no singing, ambient background score"
    uris, _, _ = generate_music_with_lyria(
        prompt=safe_prompt,
        sample_count=sample_count,
    )
    # The studio function stores to GCS. For local mixing we download.
    gcs_uri = uris[0]
    # Simple download
    subprocess.run(
        ["gcloud", "storage", "cp", gcs_uri, output_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return output_path


def get_duration(path: str) -> float:
    cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{path}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def has_audio_stream(path: str) -> bool:
    cmd = f'ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0 "{path}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return len(result.stdout.strip()) > 0


def mix_scene(
    video_path: str,
    voice_path: str,
    music_path: str | None,
    output_path: str,
    auto_speed_fit: bool = True,
) -> str:
    """Mix one video segment with voice + music.

    Voice-first philosophy (taken from the story-generator skill):
    - Measure voice duration.
    - Choose video clip length that roughly matches.
    - If voice is longer, apply atempo (capped at 1.25x). If it would exceed
      1.25x we keep voice at 1.0x and loop the video instead.
    - Duck music and any native video audio appropriately.
    """
    voice_dur = get_duration(voice_path)
    video_dur = get_duration(video_path)

    tempo = 1.0
    target_out_dur = max(voice_dur, video_dur)

    if auto_speed_fit and voice_dur > video_dur:
        target = video_dur - 0.4
        if target < 1.0:
            target = video_dur
        tempo = voice_dur / target
        if tempo > 1.25:
            print(
                f"  [audio] Required tempo {tempo:.2f}x > 1.25x guardrail. "
                "Keeping voice natural and looping video.",
            )
            tempo = 1.0
            target_out_dur = voice_dur  # we will loop video to fit voice

    # Build filter complex
    filters = []

    # Video side (loop if needed)
    if tempo == 1.0 and voice_dur > video_dur:
        # We will use -stream_loop -1 on the video input
        pass

    # Audio processing - uses balances from style_bible.py for native Veo audio vs custom narrator.
    # If narrator overpowers built-in dialogue/ambient, increase STYLE.NATIVE_BGV_VOLUME
    # or decrease STYLE.CUSTOM_VOICE_VOLUME.
    if has_audio_stream(video_path):
        filters.append(
            f"[0:a]volume={STYLE.NATIVE_BGV_VOLUME}[bgv]",
        )  # duck native video audio
    else:
        filters.append("anullsrc=cl=stereo:r=44100[bgv]")

    # Voice
    if tempo != 1.0:
        filters.append(
            f"[1:a]atempo={tempo:.3f},volume={STYLE.CUSTOM_VOICE_VOLUME}[vo]",
        )
    else:
        filters.append(f"[1:a]volume={STYLE.CUSTOM_VOICE_VOLUME}[vo]")

    # Music
    if music_path:
        filters.append(f"[2:a]volume={STYLE.MUSIC_VOLUME}[bgm]")
        mix_inputs = "[vo][bgv][bgm]"
    else:
        mix_inputs = "[vo][bgv]"
        filters.append("anullsrc=cl=stereo:r=44100[bgm]")

    filters.append(
        f"{mix_inputs}amix=inputs={3 if music_path else 2}:duration=first:dropout_transition=0[aout]",
    )

    filter_complex = ";".join(filters)

    cmd = [
        "ffmpeg",
        "-y",
    ]
    if tempo == 1.0 and voice_dur > video_dur:
        cmd += ["-stream_loop", "-1"]

    cmd += ["-i", video_path, "-i", voice_path]

    if music_path:
        cmd += ["-i", music_path]

    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-t",
        str(target_out_dur),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "44100",
        output_path,
    ]

    print(f"  [audio] Mixing scene (tempo={tempo:.2f}x, out_dur≈{target_out_dur:.1f}s)")
    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return output_path


def normalize_and_trim_clip(
    input_path: str,
    output_path: str,
    target_duration: float,
    fps: int = 24,
) -> str:
    """Trim a generated clip to an exact duration and normalize its codec
    parameters so all clips can be losslessly concatenated.

    Used by the audio-story pipeline: clips are generated at the next
    supported Veo duration (4/6/8s) >= the beat's audio window, then trimmed
    here to the exact window so cuts land precisely on the master audio
    timeline. If the clip is somehow shorter than the window, the last frame
    is held (tpad) and the audio padded with silence — the master audio
    timing is never compromised.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
    ]
    if not has_audio_stream(input_path):
        cmd += ["-f", "lavfi", "-i", "anullsrc=cl=stereo:r=44100"]

    cmd += [
        "-vf",
        f"tpad=stop_mode=clone:stop_duration={target_duration},fps={fps}",
        "-af",
        "apad",
        "-t",
        f"{target_duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "44100",
        "-ac",
        "2",
        output_path,
    ]
    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return output_path


def mix_master_audio(
    video_path: str,
    master_audio_path: str,
    output_path: str,
    native_volume: float | None = None,
    master_volume: float | None = None,
) -> str:
    """Lay a master audio track (e.g. a user-provided recording) over a video.

    The inverse philosophy of mix_scene: here the external audio is the star
    and the native Veo audio (short exclamations, ambient SFX) is ducked low
    underneath it. The video stream is passed through untouched, so the
    timing established by normalize_and_trim_clip is preserved exactly.
    """
    native_vol = (
        native_volume
        if native_volume is not None
        else STYLE.AUDIO_STORY_NATIVE_VOLUME
    )
    master_vol = (
        master_volume
        if master_volume is not None
        else STYLE.AUDIO_STORY_MASTER_VOLUME
    )

    filters = []
    if has_audio_stream(video_path):
        filters.append(f"[0:a]volume={native_vol}[bgv]")
    else:
        filters.append("anullsrc=cl=stereo:r=44100[bgv]")
    filters.append(f"[1:a]volume={master_vol}[master]")
    # normalize=0 so amix doesn't halve both inputs — the volume filters
    # above are the single source of truth for the balance.
    filters.append(
        "[master][bgv]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]",
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-i",
        master_audio_path,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-ar",
        "44100",
        output_path,
    ]
    print(
        f"  [audio] Mixing master audio over video (master={master_vol}, native={native_vol})",
    )
    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return output_path


def assemble_final_video(
    mixed_scene_paths: list[str],
    output_path: str,
) -> str:
    """Lossless concat of already-normalized mixed scenes.
    All scenes should already have identical codec parameters.
    """
    list_file = output_path + ".concat.txt"
    with open(list_file, "w") as f:
        for p in mixed_scene_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_file,
        "-c",
        "copy",
        output_path,
    ]
    subprocess.run(
        cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    os.remove(list_file)
    return output_path
