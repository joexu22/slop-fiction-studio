"""Slop Fiction Production Bible
=============================

This file encodes the "house style" for fully automated, hands-off
Slop Fiction long-form episodes (2-5 minutes, extendable to Shorts).

Core Philosophy
- Lean hard into the "slop" aesthetic as a deliberate artistic choice.
- "Poor video quality is a feature, not a bug" — we prompt for the best
  possible Ghibli-inspired cultivation visuals, but we embrace Veo artifacts,
  motion weirdness, and uncanny elements.
- Campy, tropey Chinese cultivation (xianxia) stories: young masters,
  face-slapping, heavenly tribulations, jade beauties, forbidden techniques,
  arrogant elders, destiny, etc. — played straight but with loving over-the-top
  delivery.
- Narration: Over-the-top, bombastic, dramatic, sometimes smug or ironic.
  Vary the persona per generation for freshness.
- Length target: 2-5 minutes of final video. Achieved primarily via
  per-beat independent generation + ffmpeg post-stitch (extension chains
  are limited to ~30 s, so we generate short clips per beat and assemble).

Visual Style Prompts (base)
- Primary: "Studio Ghibli inspired, soft watercolor backgrounds, detailed
  nature, emotional character expressions, beautiful lighting, flying swords
  through misty mountain peaks, ancient Chinese architecture, lush forests"
- Slop flavor (deliberately added): "in the style of Studio Ghibli but with
  current generative video model characteristics, slight motion artifacts,
  painterly dreamlike quality, acceptable uncanny elements"
- Cultivation flavor: sword flight, qi auras (soft glowing energy), robes,
  spiritual beasts, tribulation lightning, pagodas, etc.

Narration Tone
- Over-the-top epic storyteller / dramatic cultivator soap opera narrator.
- Examples of variation (chosen by Gemini at generation time):
  - "Bombastic ancient immortal storyteller with booming voice"
  - "Smug young master recounting his own legend"
  - "Dramatic tragedy narrator from a 90s wuxia drama"
  - "Enthusiastic hype-man for the Heavenly Dao"

Veo Strategy
- Because extension chains are practically limited to ~30 s total, we generate
  one short independent clip per beat (4-8 s).
- The beat's dialogue is embedded in the prompt so Veo native audio includes
  the characters speaking the lines.
- All per-beat clips are concatenated with ffmpeg at the end to produce the
  final 2-5 minute episode.
- Optional Ghibli-style reference image per beat for visual flavor.

Audio (default)
- Dialogue is the primary spoken content. The script writer produces explicit
  "dialogue" lines per beat. These are embedded in the Veo video prompts so
  the model generates characters speaking them using native audio
  (`generate_audio=True`).
- The external over-the-top narrator (TTS + Lyria) is now opt-in only via
  `--with-custom-narration`.
- When the custom path is used: Gemini TTS (or Chirp 3 HD fallback) for the
  narrator + Lyria for music. Mix volumes are tunable in `SlopFictionStyle`.
- Music base prompt always includes "strictly instrumental, no vocals...".

Automation Contract
- One-shot, fully hands-off from a single topic string.
- No human review gates.
- Initiated from chat / agent by calling the skill entrypoint with a topic
  (or "random cultivation slop" for surprise episodes).
"""

from dataclasses import dataclass

CULTIVATION_TROPES = [
    "young master with heaven-defying talent",
    "jade beauty with mysterious background",
    "arrogant young master from powerful clan gets face-slapped",
    "forbidden ancient technique discovered in a cave",
    "heavenly tribulation lightning striking during breakthrough",
    "spiritual beast companion that evolves",
    "rivalry between sects at a grand tournament",
    "betrayal by a trusted brother / sister disciple",
    "mortal who ascends after eating a 10,000 year old herb",
    "ancient ancestor wakes up inside a ring",
]

GHIBLI_BASE_VISUAL = (
    "Studio Ghibli inspired, soft watercolor and hand-painted aesthetic, "
    "lush detailed nature, emotional character expressions, beautiful "
    "atmospheric lighting, gentle wind and floating particles, "
    "dreamlike yet grounded fantasy"
)

GHIBLI_CULTIVATION_VISUAL = (
    GHIBLI_BASE_VISUAL
    + ", ancient Chinese-inspired architecture, flying swords, soft glowing "
    "qi energy auras, misty mountain peaks, flowing robes, spiritual beasts, "
    "pagodas and floating islands, in the style of Spirited Away and Princess "
    "Mononoke meeting wuxia xianxia"
)

SLOP_ACCEPTANCE = (
    ", rendered with current generative video model strengths and "
    "characteristic motion artifacts, painterly and slightly uncanny in "
    "places — these imperfections are intentional and part of the charm"
)

OVER_THE_TOP_NARRATION_STYLES = [
    "bombastic ancient immortal storyteller with a booming, theatrical voice full of gravitas",
    "smug and arrogant young master narrating his own legendary rise with dramatic flair",
    "overly dramatic 90s wuxia soap opera narrator who takes everything extremely seriously",
    "enthusiastic hype-man cultivator who gets way too excited about every technique and tribulation",
    "wise but slightly unhinged old hermit who has seen too many heavenly tribulations",
    "elegant and condescending female elder who looks down on all juniors while telling the tale",
]

# Preferred models for quality + extension support
PREFERRED_VEO_MODEL = "veo-3.1-generate-001"  # Best quality when available
PREFERRED_FAST_VEO = (
    "veo-3.1-fast-generate-001"  # Good for rapid iteration / many extensions
)
FALLBACK_VEO = "veo-3.1-lite-generate-001"

# For images (Ghibli-style stills used as strong image references for i2v or R2V)
PREFERRED_IMAGE_MODEL = (
    "gemini-2.5-flash-image"  # or "gemini-3-pro-image" / imagen-4 when configured
)

# Narration / TTS
PREFERRED_TTS_MODEL = "gemini-tts"  # Allows strong style prompting
FALLBACK_TTS_VOICES = ["Callirrhoe", "Fenrir", "Kore", "Orus"]  # From Chirp/Gemini TTS

# Music
LYRIA_PROMPT_BASE = "epic wuxia cultivation fantasy, sweeping orchestral with traditional Chinese instruments, misty mountains and soaring flight, emotional and grand, Ghibli-inspired wonder"

# Target final durations (seconds)
MIN_EPISODE_DURATION = 120  # 2 minutes
MAX_EPISODE_DURATION = 300  # 5 minutes
TARGET_EXTENSION_SECONDS = 7  # Common supported extension length

# Scene / beat guidance (we still break the story into beats even when chaining extensions)
MIN_SCENES = 12
MAX_SCENES = 35


@dataclass
class SlopFictionStyle:
    visual_base: str = GHIBLI_CULTIVATION_VISUAL + SLOP_ACCEPTANCE
    narration_styles: list[str] = None
    cultivation_tropes: list[str] = None
    music_base: str = LYRIA_PROMPT_BASE

    # Audio mixing balances (used in audio.py mix_scene for custom narrator over native Veo audio)
    # Current preference: native audio and sound effects should be just as loud as the narrator.
    # Set them roughly equal (e.g. both ~0.9). Music a bit lower as a supporting bed.
    NATIVE_BGV_VOLUME: float = 0.9  # native Veo audio (built-in per-clip dialogue/ambient) — matched to narrator level
    CUSTOM_VOICE_VOLUME: float = (
        0.9  # custom over-the-top narrator — matched to native level
    )
    MUSIC_VOLUME: float = 0.2  # supporting music bed

    def __post_init__(self):
        if self.narration_styles is None:
            self.narration_styles = OVER_THE_TOP_NARRATION_STYLES
        if self.cultivation_tropes is None:
            self.cultivation_tropes = CULTIVATION_TROPES


STYLE = SlopFictionStyle()


def get_random_narration_style() -> str:
    import random

    return random.choice(STYLE.narration_styles)


def get_cultivation_topic_seed() -> str:
    import random

    return random.choice(STYLE.cultivation_tropes)
