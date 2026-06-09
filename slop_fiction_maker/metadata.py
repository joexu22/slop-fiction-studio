"""Metadata, title, description, tags, and thumbnail generation for Slop Fiction episodes.
"""

from dataclasses import dataclass
from pathlib import Path

from models.gemini import generate_image_from_prompt_and_images

from .script_generator import SlopFictionScript
from .style_bible import STYLE


@dataclass
class EpisodeMetadata:
    title: str
    description: str
    tags: list[str]
    thumbnail_gcs: str
    duration_seconds: float


def generate_title_and_description(
    script: SlopFictionScript,
) -> tuple[str, str, list[str]]:
    """Use the model to create deliciously clickbaity but on-brand slop titles."""
    # For true hands-off we can hardcode a strong template + let Gemini refine.
    # Simple but effective for now (we can make this a Gemini call later).
    base_title = script.topic.strip().rstrip(".")
    if len(base_title) > 70:
        base_title = base_title[:67] + "..."

    title = f"{base_title} | Slop Fiction Cultivation"

    description = f"""\
{script.full_story_summary}

A Slop Fiction production — gloriously over-the-top Chinese cultivation slop
told with Studio Ghibli-inspired visuals and the best (worst?) that current
generative video can offer. We asked the silicon dream-engines for epic wuxia
and they delivered... something beautiful and slightly unhinged.

Narrated in the style of: {script.narrator_persona}

#SlopFiction #Cultivation #Xianxia #AIgenerated #Ghibli #Wuxia

More questionable scriptures from the Slop Sect:
https://www.youtube.com/@slopfictionYT
"""

    tags = [
        "cultivation",
        "xianxia",
        "wuxia",
        "slop fiction",
        "ai generated",
        "ghibli style",
        "chinese fantasy",
        "young master",
        "face slap",
        "heavenly tribulation",
        "ai video",
        "generative ai",
        "story",
        "narration",
    ]
    return title, description, tags


def generate_thumbnail(
    script: SlopFictionScript,
    output_path: Path,
) -> str:
    """Generate one beautiful Ghibli-style thumbnail for the episode."""
    prompt = (
        f"Beautiful Studio Ghibli style key art for a cultivation story: "
        f"{script.full_story_summary[:200]}. "
        f"Soft watercolor, emotional lighting, a young cultivator with flowing robes "
        f"standing dramatically on a misty mountain peak at sunrise, sword in hand, "
        f"subtle glowing qi, ancient architecture in the distance. Cinematic composition, "
        f"highly detailed, whimsical yet epic. {STYLE.visual_base}"
    )

    try:
        gcs_uris, _, _, _, _ = generate_image_from_prompt_and_images(
            prompt=prompt,
            images=[],
            aspect_ratio="16:9",
            gcs_folder="slop_fiction_thumbnails",
            file_prefix="thumbnail",
            candidate_count=1,
            model_name="gemini-2.5-flash-image",
        )
        if gcs_uris:
            # Also save a local copy
            # For simplicity we just return the GCS one; the caller can download if needed.
            return gcs_uris[0]
    except Exception as e:
        print(f"[metadata] Thumbnail generation failed: {e}")

    # Fallback: create a very basic placeholder (we can improve this)
    return ""
