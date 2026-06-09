# Slop Fiction Maker

Fully automated, one-shot generator of 2–5 minute "Slop Fiction" cultivation episodes using Veo extension chaining.

This is an **AI skill** designed to be called from chat, agents, Gemini CLI, Claude, or future MCP tools.

## Philosophy
> The slop is the point.

We ask the models for beautiful Studio Ghibli + wuxia visuals and gloriously over-the-top narration, then we embrace whatever charming imperfections, motion artifacts, and uncanny moments come out. That is the aesthetic.

## Quick Start (inside this repo)

```bash
# One random episode
python -m slop_fiction_maker.generate_episode --random --duration 180

# Specific premise (the way you already work)
python -m slop_fiction_maker.generate_episode \
  "a fallen genius re-cultivates using a forbidden bloodline technique that slowly turns him into a demon" \
  --duration 240
```

From Python (perfect for agents/chat):

```python
from slop_fiction_maker.generate_episode import generate_slop_episode

result = generate_slop_episode(
    topic="a young outer sect disciple accidentally bonds with a sentient ancient sword that only speaks in poetry",
    target_duration_seconds=200,
    upload_to_youtube=False,   # flip to True after you set up credentials
)

print(result.final_video_gcs_uri)
print(result.title)
if result.youtube_url:
    print(result.youtube_url)
```

## How it works (per-beat + post-stitch)

1. Gemini writes a campy, tropey xianxia script with explicit in-scene **dialogue** per beat (plus motion/visual descriptions).
2. For each beat we generate an **independent short video clip** (typically 4-8s).
   - The beat's dialogue is embedded in the prompt so Veo's native audio contains the characters speaking the lines.
   - Optional Ghibli-style reference image per beat for visual flavor.
3. All the per-beat clips are **concatenated** in post-production (ffmpeg) into one final episode video. This is the reliable way to get long-form now that extension chains are limited to ~30s.
4. The final video carries the native per-clip audio (with dialogue). No external narrator by default.
5. One final beautiful thumbnail + clickbaity-but-on-brand title/description/tags.
6. (Optional) Direct YouTube upload.

## Audio — Default is Native Veo Dialogue (no separate TTS)

**Default behavior (use_custom_narration=False):**

- The script explicitly writes "dialogue" for each beat (the lines characters actually say).
- These lines are embedded into the Veo prompts (see `script_generator.py:make_veo_motion_prompt`).
- Veo runs with `generate_audio=True`. The characters speak the written dialogue inside the generated video using the model's native audio capabilities.
- The output video (`final/sl op_fiction_episode_native_audio.mp4` or the main episode file) already contains the spoken lines. This is now the one-shot default.

This was the desired direction: the video model itself performs the dialogue instead of us always layering a separate narrator.

**Opt-in external narrator:**

```bash
python -m slop_fiction_maker.generate_episode "..." --with-custom-narration
```

When enabled:
- A full custom over-the-top narrator track is still generated (Gemini TTS + persona) + Lyria music.
- It is mixed on top of the native dialogue video.
- The pure `custom_narration.wav` is saved.

See `HANDOFF.md` for the history of this change and `recover_custom_audio.py` for re-applying custom narration to old native runs.

## Output & Folder Structure (clean, dated, serialized)
New runs use a clean structure:

```
slop_fiction_maker/output/
  YYYY-MM-DD/
    NNN-short-slug/
      clips/          # extension step clips (native Veo audio + dialogue)
      audio/          # only present when --with-custom-narration was used
      final/          # slop_fiction_episode_native_audio.mp4   (default — contains in-video dialogue)
                      # slop_fiction_episode_custom_audio.mp4 (only when custom narration was mixed)
      script.json
      metadata.json
      thumbnail.png
```

- Dated by creation day.
- Serialized with incrementing NNN per day + short kebab-case slug from the topic.
- Standard subfolders for easy navigation.

Historical runs (the old top-level timestamp folders) are left as-is for now. You can manually move them under their date folder if you want everything consolidated.

See `recover_custom_audio.py` (below) for reorganizing + recovering assets from a specific old run.

## YouTube Upload (highly recommended for true automation)

1. Enable the YouTube Data API v3 in your Google Cloud project.
2. Create an OAuth 2.0 Desktop client → download `client_secrets.json`.
3. Set the env var or put the file where `config.py` expects it.
4. First run will pop a browser for authorization (one-time).

Then just pass `--upload` (or `upload_to_youtube=True`).

## Extending the Skill

- Tweak the house style in `style_bible.py` (visual prompts, tropes, narration flavors, Veo model preferences).
- The `generate_episode.py` orchestrator is deliberately linear and easy to read.
- Future ideas (add as you need them):
  - Shorts mode (vertical + tighter cuts)
  - Scheduled drops / queue
  - Loose series bible (recurring characters via reference images)
  - MCP tool wrapper so the existing `mcp-genmedia` servers can call it natively

## Relationship to the rest of the repo

This skill lives at the root as a first-class citizen of the "slop-fiction-studio" workspace.

It **reuses** (does not duplicate) the excellent primitives from the main app:
- `models.veo` + `VideoGenerationRequest` (especially the `video_input_gcs` extension path)
- `models.gemini` and image generation helpers
- `common.storage.store_to_gcs`
- FFmpeg timing/mixing patterns adapted from the story-generator skill (with credit in comments)

It deliberately does **not** touch `experiments/` so we stay compliant with project guidelines.

## One generation. One shot. No review gates.

That's the contract. The automation exists so you can throw ridiculous premises at it from chat and go do something else while the silicon dream-engines forge another scripture for the Slop Sect.
