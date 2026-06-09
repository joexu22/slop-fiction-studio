"""Per-beat video generation for Slop Fiction episodes.

Since Veo extension chains are limited to roughly 30 seconds total,
we no longer rely on indefinite extension chaining for long episodes.

Instead we generate one short independent clip per scene beat (using the
dialogue lines written by the script generator so native audio includes
the characters speaking). All the per-beat clips are then concatenated
in post-production (see generate_episode.py) to produce the final video.

This matches the original manual workflow: generate per beat/scene,
then stitch.
"""

from config.veo_models import get_veo_model_config
from models.image_models import generate_images_from_prompt
from models.veo import VideoGenerationRequest, generate_video

from .config import (
    IMAGE_MODEL,
    VEO_FAST_MODEL_ID,
    VEO_MODEL_ID,
)
from .script_generator import (
    SceneBeat,
    SlopFictionScript,
    make_image_prompt,
    make_veo_motion_prompt,
)


def _get_best_veo_model() -> str:
    """Return a strong model for independent per-beat generation."""
    cfg = get_veo_model_config("3.1")
    if cfg:
        return VEO_MODEL_ID
    return VEO_FAST_MODEL_ID


def _create_strong_reference_image(
    beat: SceneBeat,
    script: SlopFictionScript | None = None,
    narrator_persona: str = "",
) -> str | None:
    """Generate one high-quality Ghibli-style image for the beat.
    Used as an image reference (i2v) for that beat's video.
    Returns a GCS URI or None.
    """
    try:
        prompt = make_image_prompt(beat, script=script)
        uris = generate_images_from_prompt(
            input_txt=prompt,
            current_model_name=IMAGE_MODEL,
            image_count=1,
            negative_prompt="blurry, deformed faces, bad anatomy, text, watermark, low quality",
            prompt_modifiers_segment="highly detailed, beautiful lighting, Studio Ghibli aesthetic",
            aspect_ratio="16:9",
        )
        if uris:
            return uris[0]
    except Exception as e:
        print(
            f"[video_chainer] Reference image generation failed (continuing without): {e}",
        )
    return None


def generate_per_beat_videos(
    script: SlopFictionScript,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    start_beat: int = 1,
) -> list[str]:
    """Generate one independent short video per scene beat.

    Each beat uses its own dialogue + motion prompt (so Veo native audio
    contains the characters speaking the lines). Duration comes from the
    script's approximate_duration_hint (clamped to supported values).

    No extension chaining is used.

    start_beat: 1-based index to start from (useful for resuming after a
    crash or content filter). The caller is responsible for ensuring that
    beat clips for 1..(start_beat-1) already exist locally in the clips/
    folder (they can be manually downloaded from GCS using URIs from the
    original log).

    Returns:
        List of GCS URIs for the beats that were actually generated
        (starting from start_beat), in story order.

    """
    model_id = _get_best_veo_model()
    print(f"[video_chainer] Using Veo model: {model_id} (per-beat independent clips)")

    beat_uris: list[str] = []
    beats = script.scene_beats
    if not beats:
        raise ValueError("Script has no scene beats")

    beats_to_generate = beats[start_beat - 1 :]
    for i, beat in enumerate(beats_to_generate, start_beat):
        print(f"\n=== Generating beat {i}/{len(beats)} ===")
        dialogue_preview = (beat.dialogue or beat.narration_text or "")[:80]
        print(f"  Dialogue: {dialogue_preview}...")

        # Use the beat's own duration hint (or sensible default).
        # The model only supports 4/6/8s for text_to_video / image_to_video.
        dur = beat.approximate_duration_hint or 6
        if dur not in (4, 6, 8):
            dur = 6 if dur < 7 else 8

        ref_image_uri = _create_strong_reference_image(
            beat,
            script=script,
            narrator_persona=script.narrator_persona,
        )

        prompt = make_veo_motion_prompt(beat, script=script)
        if ref_image_uri:
            prompt = f"{prompt} Strong visual reference to the provided image."

        request = VideoGenerationRequest(
            prompt=prompt,
            duration_seconds=dur,
            video_count=1,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            enhance_prompt=True,
            generate_audio=True,
            model_version_id=model_id,
            person_generation="Allow (Adults only)",
            negative_prompt="text, watermark, logo, deformed, blurry motion, bad anatomy, violence, blood, dark, despair, broken, shattered, doomed, wrath, wretch",
            reference_image_gcs=ref_image_uri,
            reference_image_mime_type="image/png" if ref_image_uri else None,
        )

        try:
            video_uris, _ = generate_video(request)
            uri = video_uris[0]
            beat_uris.append(uri)
            print(f"  Beat {i} generated: {uri}")
        except Exception as e:
            print(f"  Beat {i} generation failed: {e}")
            raise

    print(
        f"\n[video_chainer] Generated {len(beat_uris)} independent per-beat videos (starting from beat {start_beat}).",
    )
    return beat_uris
