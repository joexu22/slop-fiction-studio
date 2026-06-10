"""Script + Scene + Narration generator for Slop Fiction.

Fully hands-off. Takes a topic (or generates one) and returns a rich
structured script optimized for per-beat Veo generation + post-stitch (with explicit dialogue per beat)
cultivation narration.
"""

import json
from dataclasses import asdict, dataclass, field

from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Reuse the studio's Gemini tooling (best patterns already exist here)
from models.gemini import GeminiModelSetup

from .config import DEFAULT_TARGET_SECONDS
from .style_bible import (
    STYLE,
    get_cultivation_topic_seed,
    get_random_narration_style,
)


@dataclass
class SceneBeat:
    """One narrative beat / logical unit for the story.

    Default audio model (2026 update):
    - "dialogue" = the actual spoken lines by characters in the scene.
      These strings are embedded into the Veo video generation prompts.
      Veo will then generate the characters speaking those lines as part
      of its native audio track.
    - "narration_text" is now opt-in only (for the separate custom narrator).
    """

    index: int
    dialogue: str  # Exact dialogue lines spoken by characters (fed into video model for native speech audio).
    visual_description: (
        str  # High-level visual description for image/reference prompts.
    )
    motion_continuation: str  # Action + camera for the 7-8s extension. Must describe the character(s) speaking the dialogue.
    approximate_duration_hint: int  # seconds we think this beat should feel like (4-8)

    characters: list[str] = field(
        default_factory=list,
    )  # names of main characters appearing in this beat (for injecting consistent descriptions into prompts)

    # Legacy / optional external narrator track (only used when custom narration is explicitly enabled)
    narration_text: str = ""  # Over-the-top narrator voiceover text (secondary)


@dataclass
class SlopFictionScript:
    topic: str
    full_story_summary: str
    narrator_persona: str
    scene_beats: list[SceneBeat]
    target_total_duration: int
    main_characters: list[dict] = field(
        default_factory=list,
    )  # [{"name": "Ling Jun", "description": "detailed consistent visual description for video prompts..."}]
    raw_gemini_response: str | None = None

    def to_dict(self):
        return asdict(self)

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent)


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=15),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def generate_slop_script(
    topic: str | None = None,
    target_duration_seconds: int = DEFAULT_TARGET_SECONDS,
    model_name: str = None,
) -> SlopFictionScript:
    """One-shot generation of a complete campy cultivation slop script.

    The model is instructed to:
    - Write in gloriously over-the-top, tropey xianxia style.
    - Produce narration lines that sound amazing when read dramatically.
    - Break the story into beats suitable for 7-8s Veo extension steps.
    - Suggest visual language that works with Ghibli + cultivation + slop acceptance.
    - Choose (or we pick) a narrator persona.
    """
    if not topic:
        topic = f"A story about {get_cultivation_topic_seed()}"

    client = GeminiModelSetup.init()

    narrator_persona = get_random_narration_style()

    # Number of beats we want (roughly one beat per 6-8 seconds of final video).
    # Floor of 4 so short durations (Shorts mode, <= 60s) get a proportionally
    # small beat count; classic episode durations (120s+) are unaffected.
    num_beats = max(4, min(35, target_duration_seconds // 6))

    system_instruction = (
        "You are a legendary (and slightly unhinged) cultivation novel ghostwriter "
        "who specializes in gloriously campy, tropey, over-the-top xianxia slop. "
        "You love young masters, face-slapping, heavenly tribulations, jade beauties, "
        "forbidden techniques, and dramatic monologues. Your narration is always "
        "theatrical, bombastic, and perfect for a dramatic voice actor.\n\n"
        "You are helping create an automated video series called 'Slop Fiction' that "
        "deliberately embraces the charming imperfections of current AI video generation. "
        "Visuals should be described in a beautiful Studio Ghibli + wuxia fusion style, "
        "but you understand that the final video will have some motion artifacts and "
        "uncanny moments — those are part of the aesthetic."
    )

    user_prompt = f"""
Topic / Premise: {topic}

Target final video length: approximately {target_duration_seconds} seconds
(roughly {num_beats} beats of 6-8 seconds each; we generate one short clip per beat and stitch in post-production).

Narrator persona for this episode: "{narrator_persona}"

Requirements:
1. Write a short but complete story focused on motivation, perseverance, and pushing through challenges (can blend cultivation tropes with space mecha elements). Keep it campy and fun.
2. Identify 1-3 main recurring characters for the episode. For each, write a detailed, consistent visual description (age appearance, hair, build, signature clothing/accessories, colors, demeanor, perhaps mecha pilot elements) that will be reused across beats to help the video model maintain character consistency.
3. Break it into exactly {num_beats} scene beats.
4. For each beat provide **dialogue-first** content so that the video model itself can generate the characters speaking. Use positive, empowering, motivational language focused on inner strength, perseverance, rising to challenges, and forward momentum. Avoid words like "shattered", "broken", "doomed", "wrath", "wretch", "blasphemy", "dust", "end", "failure" etc. that may trigger content filters.

   - "dialogue": The exact lines the characters speak in this beat. Write them as full spoken sentences the characters would say out loud. Make them campy, dramatic, quotable, motivational slop dialogue focused on perseverance and pushing forward (e.g. "With the Motivation Scripture burning in my veins, I will pilot this mecha to victory!", "No matter the tribulation, I keep moving forward!"). These lines will be injected directly into the Veo video prompt so the generated video contains the characters speaking them with lip movement and voice.
   - "characters": List of main character names appearing in this beat (e.g. ["Ling Jun"]).
   - "visual_description": A rich visual description suitable for a Ghibli-inspired image prompt.
   - "motion_continuation": What happens in this 7-8 second segment. Explicitly describe the character(s) speaking the dialogue above (mouth movements, gestures while talking, emotional delivery, camera push-in on the speaker, etc.). Emphasize determination and forward motion.
   - "approximate_duration_hint": Suggested seconds for this beat (usually 5-8).
   - "narration_text": (optional) A short over-the-top narrator line if you really want one. This is only used when the user explicitly enables the separate custom narrator track. Prefer putting story delivery into the in-scene "dialogue" instead.

5. Also give a 2-3 sentence "full_story_summary" of the whole episode.

Return ONLY valid JSON with this exact structure (no markdown, no extra text):

{{
  "full_story_summary": "...",
  "main_characters": [
    {{
      "name": "Ling Jun",
      "description": "Young man in his early 20s with long black hair in a messy topknot, sharp determined eyes, wearing faded blue cultivator robes with a torn left sleeve and a cracked jade pendant around his neck, often seen with a focused, resilient expression as he pilots his mecha."
    }}
  ],
  "scene_beats": [
    {{
      "index": 1,
      "dialogue": "With the Motivation Scripture burning in my veins, I will pilot this mecha to new heights!",
      "characters": ["Ling Jun"],
      "visual_description": "...",
      "motion_continuation": "The young cultivator stands tall in his cockpit, eyes burning with resolve, and shouts the line while gripping the controls. The massive space mecha begins to rise, camera pushing in on his determined face as energy surges.",
      "approximate_duration_hint": 7,
      "narration_text": "With renewed inner fire, the cultivator took the first step toward his destiny..."
    }},
    ...
  ]
}}

Prioritize writing excellent, speakable, motivational dialogue that will sound great when Veo generates the audio for the characters. Focus on themes of perseverance and forward momentum. Lean hard into the slop. The dialogue is now the primary way the story is told on-screen.
Make the main character descriptions detailed and consistent so the video model can maintain visual consistency across independent clips.
""".strip()

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        temperature=0.9,  # We want creative slop, not safe boring output
    )

    response = client.models.generate_content(
        model=model_name or "gemini-2.5-flash",
        contents=user_prompt,
        config=config,
    )

    raw_text = response.text
    data = json.loads(raw_text)

    beats = []
    for b in data.get("scene_beats", []):
        beats.append(
            SceneBeat(
                index=b.get("index"),
                dialogue=b.get(
                    "dialogue",
                    b.get("narration_text", ""),
                ),  # support old scripts that only had narration_text
                visual_description=b.get("visual_description", ""),
                motion_continuation=b.get("motion_continuation", ""),
                approximate_duration_hint=b.get("approximate_duration_hint", 7),
                characters=b.get("characters", []),
                narration_text=b.get("narration_text", ""),
            ),
        )

    script = SlopFictionScript(
        topic=topic,
        full_story_summary=data.get("full_story_summary", ""),
        narrator_persona=narrator_persona,
        main_characters=data.get("main_characters", []),
        scene_beats=beats,
        target_total_duration=target_duration_seconds,
        raw_gemini_response=raw_text,
    )

    return script


def make_image_prompt(
    beat: SceneBeat,
    script: SlopFictionScript | None = None,
) -> str:
    """Turn a beat's visual_description into a strong prompt for the image model.
    Used both for reference images and as strong conditioning for video.

    If script is provided and has main_characters, injects consistent character
    descriptions for any characters listed in the beat.
    """
    base = STYLE.visual_base
    dialogue_part = (
        f' The character is speaking: "{beat.dialogue}".' if beat.dialogue else ""
    )

    char_desc = ""
    if script and getattr(script, "main_characters", None):
        relevant = []
        for char in script.main_characters:
            if (
                beat.characters and char.get("name") in beat.characters
            ) or not beat.characters:
                relevant.append(f"{char['name']}: {char.get('description', '')}")
        if relevant:
            char_desc = " ".join(relevant) + ". "

    return (
        f"{char_desc}{beat.visual_description}{dialogue_part} {base}. "
        f"Cultivation xianxia scene, dramatic and epic yet whimsical. "
        f"High detail, beautiful composition, cinematic Ghibli lighting."
    )


def make_veo_motion_prompt(
    beat: SceneBeat,
    script: SlopFictionScript | None = None,
    previous_context: str = "",
) -> str:
    """The motion prompt we will feed to Veo for per-beat video generation.

    Injects consistent main character descriptions (when provided via the script)
    so the video model has a better chance of maintaining visual consistency
    across independent per-beat clips.

    Also embeds the "dialogue" field so Veo generates the
    characters speaking those lines as part of the native video audio.
    """
    char_desc = ""
    if script and getattr(script, "main_characters", None):
        relevant = []
        for char in script.main_characters:
            if (
                beat.characters and char.get("name") in beat.characters
            ) or not beat.characters:
                relevant.append(f"{char['name']}: {char.get('description', '')}")
        if relevant:
            char_desc = " ".join(relevant) + ". "

    prompt = char_desc + beat.motion_continuation

    if beat.dialogue:
        prompt = (
            f"{prompt} During this segment the character clearly speaks the line: "
            f'"{beat.dialogue}" with visible mouth movements, emotional facial expression, '
            f"and appropriate gestures."
        )

    if previous_context:
        prompt = f"{previous_context}. Continuing: {prompt}"

    # Add gentle guardrails that still allow slop
    prompt += (
        " Smooth cinematic camera movement, beautiful Ghibli-inspired animation style, "
        "soft lighting, emotional weight. The spoken dialogue must be clearly audible and "
        "lip-synced. Accept natural generative motion characteristics and audio artifacts."
    )
    return prompt
