#!/usr/bin/env python3
"""Recovery script for custom narrator audio track ("lost artform piece").

Usage (after TTS API is enabled on the project):

python -m slop_fiction_maker.recover_custom_audio \
  --run-dir "slop_fiction_maker/output/2026-06-09_064650_the-slop-master-cultivator-has-cultivated-a-new-technique:-t"

It will:
- Load the script.json from that run (which has the exact per-beat narration texts and persona from the "lost" generation).
- Synthesize the full custom over-the-top narration.wav (the pure art piece you wanted).
- Generate a Lyria music track.
- Produce a mixed video version using the existing stitched episode as base, with the custom track mixed in (ducking the native audio from the per-beat clips).
- Also keep a copy of the original native-audio video.
- Place assets cleanly under audio/ and final/ subdirs inside the run dir.

This recovers the custom narrator track without re-generating the video clips.
"""

import argparse
import json
import subprocess
from pathlib import Path

from .audio import (
    generate_background_music,
    get_duration,
    mix_scene,
    synthesize_narration,
)
from .style_bible import STYLE


def main():
    parser = argparse.ArgumentParser(
        description="Recover custom narrator audio from a previous run's script.json",
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Path to the previous output directory that contains script.json and the stitched episode.mp4 (e.g. the 2026-06-09_064650... one with 15 clips)",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        print(f"ERROR: Run dir does not exist: {run_dir}")
        return

    script_path = run_dir / "script.json"
    if not script_path.exists():
        print(f"ERROR: No script.json found in {run_dir}")
        return

    with open(script_path) as f:
        script_data = json.load(f)

    persona = script_data.get(
        "narrator_persona",
        "bombastic ancient immortal storyteller with a booming, theatrical voice full of gravitas",
    )
    beats = script_data.get("scene_beats", [])
    if not beats:
        print("ERROR: No beats in script.json")
        return

    full_narration = " ".join(b.get("narration_text", "") for b in beats).strip()
    if not full_narration:
        print("ERROR: No narration text found in script.json")
        return

    print(f"Recovering custom audio for run: {run_dir}")
    print(f"  Persona: {persona}")
    print(f"  Total narration length: {len(full_narration)} chars / {len(beats)} beats")

    # Ensure clean subdirs
    audio_dir = run_dir / "audio"
    final_dir = run_dir / "final"
    audio_dir.mkdir(exist_ok=True)
    final_dir.mkdir(exist_ok=True)

    # 1. The pure custom narrator track (the "artform piece")
    narration_wav = audio_dir / "custom_narration.wav"
    print(f"\n[1/3] Synthesizing custom narrator track -> {narration_wav}")
    synthesize_narration(
        full_narration_text=full_narration,
        persona=persona,
        output_path=str(narration_wav),
    )
    print(
        f"  Recovered narrator track: {narration_wav} (duration ~{get_duration(str(narration_wav)):.1f}s)",
    )

    # 2. Music
    music_wav = audio_dir / "lyria_music.wav"
    print(f"\n[2/3] Generating Lyria music -> {music_wav}")
    try:
        generate_background_music(
            prompt=STYLE.music_base,
            output_path=str(music_wav),
        )
    except Exception as e:
        print(f"  Music generation failed: {e}")
        music_wav = None

    # 3. Find the existing stitched video (native audio version)
    native_video = run_dir / "slop_fiction_episode.mp4"
    if not native_video.exists():
        # Try in final/ or other common locations from previous runs
        candidates = [
            run_dir / "final" / "slop_fiction_episode_native_audio.mp4",
            run_dir / "slop_fiction_episode.mp4",
        ]
        for c in candidates:
            if c.exists():
                native_video = c
                break

    if not native_video.exists():
        print(f"\nWARNING: Could not find the stitched episode.mp4 in {run_dir}")
        print("  You can manually mix the custom_narration.wav over your video later.")
        print(f"  Pure narrator track saved to: {narration_wav}")
        return

    print(f"\n[3/3] Mixing custom narrator + music over existing video: {native_video}")

    # Produce a version with custom audio (primary)
    custom_mixed = final_dir / "slop_fiction_episode_custom_audio.mp4"
    mix_scene(
        video_path=str(native_video),
        voice_path=str(narration_wav),
        music_path=str(music_wav) if music_wav else None,
        output_path=str(custom_mixed),
        auto_speed_fit=True,
    )

    # Keep a clear copy of the original native version (if not already in final/)
    native_copy = final_dir / "slop_fiction_episode_native_audio.mp4"
    if str(native_video) != str(native_copy):
        subprocess.check_call(["cp", str(native_video), str(native_copy)])

    print("\n=== Recovery complete ===")
    print(f"Pure custom narrator track (the art piece): {narration_wav}")
    print(f"Video with custom audio mixed in: {custom_mixed}")
    print(f"Original native-audio video copy: {native_copy}")
    print(
        "\nYou now have the 'lost' custom over-the-top narrator track from that exact script generation.",
    )


if __name__ == "__main__":
    main()
