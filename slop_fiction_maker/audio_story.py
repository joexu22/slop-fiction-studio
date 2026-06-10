"""Audio-driven storyboard for Slop Fiction "storytime" videos.

The inverse of the normal pipeline: instead of writing a script and letting
the video carry the audio, an existing audio file is the master soundtrack.

1. Transcribe the audio with Gemini (segment-level timestamps).
2. Plan a storyboard: contiguous beats that each own an exact time window
   of the audio. Visuals act out what is being said in the slop fiction
   storytime style; Veo native audio is limited to short exclamations so
   it never competes with the master track.

Timing contract (this is the important part):
- Beats are contiguous and cover [0, audio_duration] exactly.
- Each beat window is <= 8s (the max Veo clip length). Longer windows are
  split into continuation sub-beats in code, never by cutting the audio.
- The Veo clip for a beat is generated at the smallest supported duration
  (4/6/8s) that covers the window, then trimmed to the exact window in
  post-production. The master audio is never cut or re-timed.
"""

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from models.gemini import GeminiModelSetup

from .style_bible import STYLE

# Veo supported clip durations for t2v/i2v
SUPPORTED_CLIP_DURATIONS = (4, 6, 8)
MAX_BEAT_WINDOW = float(SUPPORTED_CLIP_DURATIONS[-1])
MIN_BEAT_WINDOW = 1.0  # beats shorter than this get merged into a neighbor

# Audio formats Gemini accepts directly; anything else is transcoded first.
_DIRECT_AUDIO_MIME = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aiff": "audio/aiff",
    ".m4a": "audio/mp4",
}


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class AudioStoryBeat:
    """One visual beat covering an exact window of the master audio."""

    index: int
    start: float
    end: float
    transcript_text: str  # what is being said during this window (for context only — NOT spoken by Veo)
    visual_description: str
    motion_prompt: str
    exclamation: str = ""  # the ONLY thing Veo characters may say (short, comedic)
    characters: list[str] = field(default_factory=list)

    @property
    def window(self) -> float:
        return self.end - self.start

    @property
    def veo_duration(self) -> int:
        """Smallest supported clip duration that covers the window."""
        for d in SUPPORTED_CLIP_DURATIONS:
            if d >= self.window - 0.01:
                return d
        return SUPPORTED_CLIP_DURATIONS[-1]


@dataclass
class AudioStoryboard:
    audio_path: str
    audio_duration: float
    story_summary: str
    transcript: list[TranscriptSegment]
    beats: list[AudioStoryBeat]
    main_characters: list[dict] = field(default_factory=list)
    raw_transcription_response: str | None = None
    raw_storyboard_response: str | None = None

    def to_dict(self):
        return asdict(self)

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent)


def _audio_part(audio_path: str) -> types.Part:
    """Build a Gemini Part from the audio file, transcoding if the format
    is not in the directly-supported set.
    """
    path = Path(audio_path)
    mime = _DIRECT_AUDIO_MIME.get(path.suffix.lower())
    if mime:
        return types.Part.from_bytes(data=path.read_bytes(), mime_type=mime)

    # Unknown container: transcode to a small mono mp3 for transcription
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-b:a", "96k", tmp_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    data = Path(tmp_path).read_bytes()
    Path(tmp_path).unlink(missing_ok=True)
    return types.Part.from_bytes(data=data, mime_type="audio/mp3")


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=15),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def transcribe_audio(
    audio_path: str,
    audio_duration: float,
    model_name: str = "gemini-2.5-flash",
) -> tuple[list[TranscriptSegment], str]:
    """Transcribe the audio with segment-level timestamps via Gemini."""
    client = GeminiModelSetup.init()

    prompt = f"""
Transcribe this audio file precisely. The total duration is {audio_duration:.1f} seconds.

Break the transcription into natural phrase-level segments (roughly one
breath/phrase each, typically 2-6 seconds). Timestamps must be in seconds,
must not overlap, and must stay within [0, {audio_duration:.1f}].

Return ONLY valid JSON (no markdown):
{{
  "segments": [
    {{"start": 0.0, "end": 3.4, "text": "..."}},
    ...
  ]
}}
""".strip()

    response = client.models.generate_content(
        model=model_name,
        contents=[_audio_part(audio_path), prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,  # transcription should be faithful, not creative
        ),
    )
    raw = response.text
    data = json.loads(raw)

    segments = [
        TranscriptSegment(
            start=float(s.get("start", 0.0)),
            end=float(s.get("end", 0.0)),
            text=s.get("text", "").strip(),
        )
        for s in data.get("segments", [])
        if s.get("text", "").strip()
    ]
    segments.sort(key=lambda s: s.start)
    return segments, raw


def _normalize_beats(
    raw_beats: list[AudioStoryBeat],
    audio_duration: float,
) -> list[AudioStoryBeat]:
    """Enforce the timing contract regardless of what the model returned:
    contiguous beats covering [0, audio_duration], each window in
    [MIN_BEAT_WINDOW, MAX_BEAT_WINDOW]. Oversized windows are split into
    continuation sub-beats (same visuals); undersized ones are merged
    into the previous beat. The audio timeline itself is never altered.
    """
    if not raw_beats:
        raise ValueError("Storyboard has no beats")

    beats = sorted(raw_beats, key=lambda b: b.start)

    # Force contiguity: each beat starts where the previous ended.
    cursor = 0.0
    for b in beats:
        b.start = cursor
        b.end = max(b.end, b.start)  # guard inverted windows
        cursor = b.end
    beats[-1].end = audio_duration

    # Merge too-short beats into their predecessor.
    merged: list[AudioStoryBeat] = []
    for b in beats:
        if merged and b.window < MIN_BEAT_WINDOW:
            merged[-1].end = b.end
            merged[
                -1
            ].transcript_text = (
                f"{merged[-1].transcript_text} {b.transcript_text}".strip()
            )
        else:
            merged.append(b)

    # Split too-long windows into continuation sub-beats.
    final: list[AudioStoryBeat] = []
    for b in merged:
        if b.window <= MAX_BEAT_WINDOW + 0.01:
            final.append(b)
            continue
        n_parts = int(b.window // MAX_BEAT_WINDOW) + 1
        part_len = b.window / n_parts
        for p in range(n_parts):
            final.append(
                AudioStoryBeat(
                    index=0,  # reindexed below
                    start=b.start + p * part_len,
                    end=b.start + (p + 1) * part_len,
                    transcript_text=b.transcript_text,
                    visual_description=b.visual_description,
                    motion_prompt=(
                        b.motion_prompt
                        if p == 0
                        else f"Continuation of the same scene, new camera angle: {b.motion_prompt}"
                    ),
                    exclamation=b.exclamation if p == 0 else "",
                    characters=list(b.characters),
                ),
            )
        final[-1].end = b.end  # absorb float drift

    for i, b in enumerate(final, 1):
        b.index = i
    return final


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=15),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)
def plan_audio_storyboard(
    audio_path: str,
    audio_duration: float,
    transcript: list[TranscriptSegment],
    topic_hint: str | None = None,
    model_name: str = "gemini-2.5-flash",
) -> AudioStoryboard:
    """Turn a timed transcript into a slop-fiction storytime storyboard."""
    client = GeminiModelSetup.init()

    transcript_lines = "\n".join(
        f"[{s.start:.1f}s - {s.end:.1f}s] {s.text}" for s in transcript
    )

    system_instruction = (
        "You are the storyboard artist for 'Slop Fiction', an automated video "
        "series of gloriously campy xianxia cultivation stories in a Studio "
        "Ghibli inspired style that deliberately embraces AI video artifacts.\n\n"
        "You are planning a STORYTIME video: a real pre-recorded audio track is "
        "the master soundtrack, and the generated visuals act out what the "
        "speaker describes — translated into over-the-top cultivation-world "
        "metaphors. The characters on screen must NOT speak the transcript. "
        "At most they may shout one very short comedic exclamation per beat "
        "(e.g. 'Impossible!', 'My spirit stones!'). The comedy comes from the "
        "earnest, slightly unhinged visuals reacting to the mundane audio."
    )

    user_prompt = f"""
Timed transcript of the master audio ({audio_duration:.1f} seconds total):

{transcript_lines}

{f"Topic hint from the creator: {topic_hint}" if topic_hint else ""}

Plan the storyboard:

1. Write a 1-2 sentence "story_summary" of what the audio is about and the
   visual metaphor you chose (e.g. money troubles → the sect treasury of
   spirit stones running dry).
2. Define 1-2 "main_characters" with detailed, consistent visual descriptions
   (reused across every beat for consistency).
3. Break the FULL duration [0, {audio_duration:.1f}] into contiguous "beats".
   - Each beat covers an exact time window of the audio: "start" and "end" in seconds.
   - Windows must be between 3 and 8 seconds and must not overlap or leave gaps.
   - Align beat boundaries with the transcript segment boundaries above wherever possible,
     so visual cuts land on natural phrase breaks.
   - The final beat must end at exactly {audio_duration:.1f}.
4. For each beat provide:
   - "transcript_text": the words spoken during this window (copy from the transcript).
   - "visual_description": rich Ghibli-cultivation visual for this moment, acting out
     the transcript content as cultivation-world metaphor.
   - "motion_prompt": action + camera for this 4-8s clip. Expressive pantomime,
     dramatic gestures, reaction faces. The characters do NOT speak the transcript.
   - "exclamation": OPTIONAL — one short shouted interjection of at most 4 words,
     or "" for silent pantomime. Use sparingly (at most every other beat).
   - "characters": names of main characters in this beat.

Return ONLY valid JSON (no markdown):
{{
  "story_summary": "...",
  "main_characters": [{{"name": "...", "description": "..."}}],
  "beats": [
    {{
      "index": 1,
      "start": 0.0,
      "end": 5.2,
      "transcript_text": "...",
      "visual_description": "...",
      "motion_prompt": "...",
      "exclamation": "My spirit stones!",
      "characters": ["..."]
    }},
    ...
  ]
}}
""".strip()

    response = client.models.generate_content(
        model=model_name,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.9,
        ),
    )
    raw = response.text
    data = json.loads(raw)

    raw_beats = [
        AudioStoryBeat(
            index=b.get("index", i),
            start=float(b.get("start", 0.0)),
            end=float(b.get("end", 0.0)),
            transcript_text=b.get("transcript_text", ""),
            visual_description=b.get("visual_description", ""),
            motion_prompt=b.get("motion_prompt", ""),
            exclamation=(b.get("exclamation") or "").strip(),
            characters=b.get("characters", []),
        )
        for i, b in enumerate(data.get("beats", []), 1)
    ]

    beats = _normalize_beats(raw_beats, audio_duration)

    return AudioStoryboard(
        audio_path=str(audio_path),
        audio_duration=audio_duration,
        story_summary=data.get("story_summary", ""),
        transcript=transcript,
        beats=beats,
        main_characters=data.get("main_characters", []),
        raw_storyboard_response=raw,
    )


def storyboard_from_dict(data: dict) -> AudioStoryboard:
    """Rehydrate a storyboard from a saved storyboard.json.

    Used for resuming a crashed run: the saved beat windows must be reused
    exactly, otherwise newly generated clips would not line up with the
    clips that already exist.
    """
    return AudioStoryboard(
        audio_path=data["audio_path"],
        audio_duration=float(data["audio_duration"]),
        story_summary=data.get("story_summary", ""),
        transcript=[
            TranscriptSegment(
                start=float(s["start"]),
                end=float(s["end"]),
                text=s.get("text", ""),
            )
            for s in data.get("transcript", [])
        ],
        beats=[
            AudioStoryBeat(
                index=int(b["index"]),
                start=float(b["start"]),
                end=float(b["end"]),
                transcript_text=b.get("transcript_text", ""),
                visual_description=b.get("visual_description", ""),
                motion_prompt=b.get("motion_prompt", ""),
                exclamation=b.get("exclamation", ""),
                characters=b.get("characters", []),
            )
            for b in data.get("beats", [])
        ],
        main_characters=data.get("main_characters", []),
    )


def make_audio_story_veo_prompt(
    beat: AudioStoryBeat,
    storyboard: AudioStoryboard,
) -> str:
    """Veo prompt for one storytime beat.

    Unlike the episode pipeline, the transcript is context only — the prompt
    explicitly forbids continuous speech so the native audio never competes
    with the master track. Only the short exclamation (if any) is performed.
    """
    char_desc = ""
    if storyboard.main_characters:
        relevant = []
        for char in storyboard.main_characters:
            if (
                beat.characters and char.get("name") in beat.characters
            ) or not beat.characters:
                relevant.append(f"{char['name']}: {char.get('description', '')}")
        if relevant:
            char_desc = " ".join(relevant) + ". "

    prompt = (
        f"{char_desc}{beat.motion_prompt} "
        f'This moment visually acts out a story being narrated: "{beat.transcript_text}". '
    )

    if beat.exclamation:
        prompt += (
            f'The character briefly shouts only the short exclamation: "{beat.exclamation}" '
            f"— no other talking, no narration. "
        )
    else:
        prompt += (
            "The characters do not speak at all — expressive pantomime, dramatic "
            "gestures and reaction faces only, with ambient sound effects. "
        )

    prompt += (
        f"{STYLE.visual_base}. Storytime animation energy: theatrical, earnest, "
        "comedically over-dramatic. Smooth cinematic camera movement, soft Ghibli "
        "lighting. Accept natural generative motion characteristics."
    )
    return prompt
