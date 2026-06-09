# Slop Fiction Maker — Handoff Document

**Project:** `slop-fiction-studio` (personal fork/art project)  
**Core Artifact:** `slop_fiction_maker/` — a one-shot AI skill for generating 2–5 minute "Meme Slop Fiction" cultivation episodes.

## Project Identity (Artistic + Practical Handoff)

This is **not** just another generative media tool. The root README reframes the entire repo as:

- An **art project / meme generator** adapted from Google’s Vertex AI GenMedia Creative Studio.
- Deliberately absurd “Slop Fiction” (over-the-top xianxia cultivation shorts with Ghibli aesthetics) produced end-to-end by models.
- Surface level: pure joke / “the slop is the point.”
- Deeper premise: every media generator (slop or prestige) is an awkward early prototype on the path to the **Holodeck** — instant, personal, responsive, living stories. This fork takes the most ridiculous possible route to explore that future.

**Public face:**
- Featured flagship episode (004): https://www.youtube.com/watch?v=Jp2DN7GAbXw
- Channel: https://www.youtube.com/@slopfictionYT (subscribe for drops)

**Critical for any handoff / fork / clone:**
- `.gitignore` has been hardened (see root `.gitignore` and history). In particular `slop_fiction_maker/output/` is ignored. This prevents leaking:
  - Large generated video files
  - `metadata.json` / `script.json` that contain real GCS bucket paths (e.g. `gen-lang-client-...-assets`)
  - Personal run dates and story content
- Never commit anything under `output/`, `.env`, or stray `.DS_Store` files.
- On a fresh machine: `cp dotenv.template .env`, fill `PROJECT_ID` (and optionally YouTube creds), then run.

The technical details below preserve the original “hands-off one generation, one shot” contract while documenting the evolution (especially the big shift to native in-video dialogue).

---

**Technical Goal (preserved):** Fully automated, hands-off generator of 2–5 minute "Slop Fiction" YouTube episodes. Campy, tropey Chinese cultivation (xianxia) stories with Ghibli-inspired visuals (embracing generative artifacts as part of the charm).

This document captures the major technical work, decisions, trade-offs, current state, and pointers for future work. It was originally written as the explicit handoff at the close of the initial build phase and has been updated with higher-level project context, git hygiene, and the artistic reframing.

The user (channel owner) wants to stay hands-off on implementation details but cares about the final creative output and being able to iterate on audio balance, consistency, and structure. During handoff write we also did a small cleanup of the orchestrator finalization (undefined variables from earlier native-only bypass experiments) so the full described flow actually runs to completion.

## Quick Status at Handoff
- Long-chain extension is the default (consistency wins).
- Hybrid audio (native per-extension Veo audio + full custom narrator + Lyria) is the active path and runs every generation.
- Clean `YYYY-MM-DD/NNN-slug/` + `clips/`, `audio/`, `final/` structure is enforced.
- Volumes default to equal-loudness preference for native vs. custom narrator (0.9 / 0.9).
- `recover_custom_audio.py` successfully used to rescue at least one historical "lost artform" custom narration track from its `script.json`.
- All major early errors (model version_id strings, TTS 403, image 400 fallback, duration clamping, folder hygiene) have been addressed or documented.

## Current High-Level Flow (as of latest run)

1. **Script Generation** (`script_generator.py`)
   - Gemini produces a structured script with per-beat data:
     - `narration_text` (over-the-top lines for the narrator track)
     - `motion_continuation` (prompt for that beat's action/camera)
     - `visual_description` (supporting)
     - `approximate_duration_hint`
   - Also chooses a narrator persona for style prompting in TTS.

2. **Video Generation** (primarily `video_chainer.py` + `models/veo.py`)
   - Per-beat independent generation (extension chaining removed because chains are limited to ~30 s).
   - One short clip per beat (dialogue embedded so native audio has characters speaking).
   - Optional Ghibli-style reference image per beat.
   - All per-beat clips are downloaded, then concatenated with ffmpeg (`assemble_final_video`) into the final episode.
   - This is the reliable long-form path and fixes the previous "only last chain segment kept as final" problem.

3. **Custom Audio Layer** (`audio.py`)
   - Now that the Text-to-Speech API is enabled: full custom over-the-top narrator track is generated from the joined per-beat `narration_text` lines + the chosen persona (via Gemini TTS with strong style prompt, falling back to Chirp 3 HD).
   - Lyria music track.
   - Post-process mix over the chained video using `mix_scene` (ffmpeg filter complex):
     - Voice-first timing with 1.25× tempo guardrail (if custom narration is much longer, keep natural speed and loop/extend the video instead of mangling the voice).
     - Ducking of native Veo audio.
   - Pure `custom_narration.wav` is saved as the standalone "artform piece."

4. **Output & Structure**
   - Clean dated + serialized layout (implemented in `generate_episode.py`):
     ```
     output/
       YYYY-MM-DD/
         NNN-short-slug/
           clips/          # per-step or per-beat clips (native audio)
           audio/          # custom_narration.wav, lyria_music.wav
           final/          # *_native_audio.mp4 and *_custom_audio.mp4
           script.json
           metadata.json
           thumbnail.png
     ```
   - All media also goes to GCS via the studio's `store_to_gcs`.

5. **Recovery of Previous Work**
   - `recover_custom_audio.py` exists to "rescue" custom narrator tracks from old runs whose `script.json` still contains the exact per-beat narration lines + persona from that generation.
   - It re-synthesizes the custom track (now that TTS is on) and produces a mixed version over the existing video without re-doing expensive Veo work.

## Major Technical Decisions & Rationale

### 1. Long Extension Chaining (Primary Video Path) vs. Pure Per-Beat
- **Decision:** Default to the long single-chain extension approach (`video_chainer.py` calling `generate_video` repeatedly with `video_input_gcs`).
- **Why:**
  - This was the user's original preferred technique ("using the veo's ability to extend so we don't quite have to worry about consistency").
  - It delivers pixel-level motion continuity across many beats in one continuous take — exactly the "don't have to worry about consistency" benefit.
  - Per-beat independent generations (the experiment we tried) produced noticeably weaker visual/motion continuity between beats.
- **Trade-off & Compromise:** We still save every intermediate extension step as `clips/step_XX.mp4`. This gives the user the "all the clips downloaded" visibility they asked for, while the final video benefits from the long chain.
- **Per-beat path:** Still present in the codebase (and was used in one major test run). It is useful when you explicitly want many independent short clips (each with its own strong native audio character) + explicit FFmpeg post-stitch. We can flip between the two or build a hybrid (short chains per group of beats + final FFmpeg stitch of the groups).

### 2. Native Veo Audio Per Clip/Segment + Custom Narrator Overlay
- **Decision:** Generate clips/segments with `generate_audio=True` (native Veo ambient/effects per piece) **and** generate a separate custom over-the-top narrator track (TTS + Lyria) that is mixed on top in post.
- **Why:**
  - User explicitly liked "the idea of individual audio native to what veo can do ... as it makes it to be more funny."
  - At the same time they wanted the consistent "gloriously over-the-top" narrator style that defines the channel (the "artform piece").
  - Hybrid gives both: funny per-scene Veo character in the raw clips + a coherent narrator track for the final.
- **Mixing balance:** Originally the mix was very narrator-dominant (heavy ducking of native). User feedback: "the native audio and the sound effects should be just as loud as the narrator."  
  → Updated defaults in `style_bible.py` (and therefore `audio.py`):
    - `NATIVE_BGV_VOLUME = 0.9`
    - `CUSTOM_VOICE_VOLUME = 0.9`
    - `MUSIC_VOLUME = 0.2`
  These are now the single source of truth and easy to tweak for future runs or re-mixes.

### 3. Custom Audio Always Runs (Now That TTS Is Enabled)
- Previously we had various bypasses/guards because the Text-to-Speech API was not enabled.
- Once the user enabled it, we made the custom narrator + music + mix step run as part of the normal flow (after video generation).
- The pure `custom_narration.wav` is always saved so the "lost artform piece" is never lost again.
- Recovery script exists for historical runs whose script.json still contains the narration data.

### 4. Output Organization
- Old runs used flat timestamped folders with ugly truncated names containing colons.
- Changed `generate_episode.py` to produce `output/YYYY-MM-DD/NNN-short-kebab-slug/` with standard subfolders (`clips/`, `audio/`, `final/`).
- This was a direct user request for "dated and serialized in folders" and overall cleanliness.
- The recovery script also adds the missing subfolders to the historical run it was pointed at.

### 5. Veo Practical Limits & Why We Save Steps
- A single continuous extension chain has real limits (roughly 20 extensions of 7s, or ~30s total duration before the API rejects further extensions or quality/consistency drops).
- We saw this in practice ("Video duration 36 seconds exceeds the maximum duration 30 seconds").
- Saving every intermediate step + using the `MAX_EXTENSION_STEPS` guard + planning for future multi-chain + FFmpeg assembly of the chains gives a pragmatic path to longer episodes while still using the extend technique where it helps most.

### 6. Major Philosophy Shift: In-Video Dialogue (Mid-2026)
- **Decision:** By default we no longer generate a separate custom TTS narrator track. Instead the script writer is required to produce explicit `dialogue` per beat. These lines are injected into the Veo motion prompts (`make_veo_motion_prompt`), and Veo generates the characters speaking them as part of its native `generate_audio=True` output.
- **Why:**
  - User feedback repeatedly showed that the custom narrator was overpowering the charming native audio and built-in character sounds.
  - The original manual workflow the user described was feeding scenes to video and letting the model do its thing (including sound).
  - Having the *video model itself* perform the dialogue keeps everything inside one generative pass, reduces post-processing complexity, and leans further into the "slop" aesthetic (whatever weird delivery Veo gives the lines is part of the charm).
- **Implementation:**
  - `SceneBeat` gained a first-class `dialogue` field.
  - The Gemini script prompt was rewritten to prioritize writing speakable, campy in-scene dialogue.
  - `make_veo_motion_prompt` and `make_image_prompt` now embed the dialogue text.
  - In `generate_episode.py` the custom synthesis + mix path is now behind `use_custom_narration=False` (CLI: `--with-custom-narration` to opt back in).
  - `narration_text` is kept (for the opt-in path and old script compat) but is secondary.
- **Trade-offs:** You lose the perfectly consistent "glorious narrator" performance unless you opt in. You gain tighter coupling between visuals and spoken lines and much simpler default pipeline.

### 7. Other Implementation Details & Gotchas Handled
- **Model IDs:** Must use the short `version_id` keys from `config/veo_models.py` ("3.1", "3.1-fast", etc.) when calling `VideoGenerationRequest`, not the long "veo-3.1-generate-001" strings (those are the internal model names). Fixed in `slop_fiction_maker/config.py`.
- **Image references for continuity:** The attempt to generate strong Ghibli-style reference images for i2v (to help continuity) repeatedly hit `400 FAILED_PRECONDITION` because this particular project is on the newer Gemini image path, while the studio's `image_models.py` was still using the old Vertex Predict path for "gemini-*-image". We fall back gracefully ("continuing without") so video generation is not blocked.
- **Service agent provisioning / first-use errors:** Common after enabling Vertex AI + first GCS writes. Usually resolves in a few minutes.
- **Duration handling in per-beat/chain:** Hard-code to supported values (4/6/8) for the chosen model instead of blindly trusting the script's `approximate_duration_hint`.
- **Recovery of "lost" custom tracks:** The `recover_custom_audio.py` script exists precisely because an earlier run produced a great script + video but the custom narration was never generated (TTS was off + we were in native-only mode at the time). It re-uses the exact `script.json` from that run. It still works for re-applying a narrator to a native-dialogue run.

## Current Recommended Workflow (Hands-Off)

1. Throw a premise at the skill (CLI or Python call).
2. By default it produces:
   - A script with explicit `dialogue` per beat.
   - Long chained video via Veo extension where the characters speak the written dialogue using native audio.
   - `clips/step_XX.mp4` (raw extension steps with embedded dialogue audio)
   - `final/sl op_fiction_episode_native_audio.mp4` (the main deliverable)
3. If you want the old glorious external narrator on top of the in-scene dialogue:
   - `python -m slop_fiction_maker.generate_episode "..." --with-custom-narration`
   - This will also populate `audio/custom_narration.wav` and produce a `_custom_audio.mp4`.
4. Re-mixing or recovering custom narration on any native run is still possible with the utilities in `audio.py` / `recover_custom_audio.py`.

## Open / Future Work (Prioritized by User Feedback)

- **Consistency vs. per-scene native audio:** Long chain is better for motion continuity (your original request). Pure per-beat gives stronger per-clip native character but weaker cross-beat continuity. A hybrid (short chains per logical group of beats + final FFmpeg stitch of the groups) is probably the sweet spot for longer episodes.
- **Visual continuity between beats/clips:** Last-frame extraction + use as reference image (or as the starting frame for the next short chain) would help without losing the per-piece native audio.
- **Script quality (dialogue length, naturalism & flow):** Now that dialogue is the primary spoken content fed to Veo, you may want to iterate on the prompt in `script_generator.py` if the generated lines are too short, too narrator-like, or don't feel natural when the model tries to speak them.
- **More audio control:** Option to generate per-beat custom lines instead of (or in addition to) in-video dialogue, better control over when native audio vs custom is used per segment, etc. The `--with-custom-narration` path is the current escape hatch.
- **Longer total duration while using extend:** Implement the "multiple short chains + final stitch" path described above.
- **YouTube automation:** The upload path exists (`youtube_uploader.py`) but needs `client_secrets.json` + OAuth flow (one-time browser auth). See `config.py` and `slop_fiction_maker/README.md`.
- **Scheduling / batching** for daily drops.
- **Public handoff surface:** Keep the root README artistic statement + featured video + channel links fresh. The specific 004 episode (Jp2DN7GAbXw) is currently pinned as the hero. Update when a new “best” episode drops.

## Key Files & Where Things Live

- `generate_episode.py` — main orchestrator (script → video → custom audio → metadata).
- `video_chainer.py` — the long extension logic + saving of step clips.
- `audio.py` — TTS, Lyria, `mix_scene` (the tunable ducking), assemble helpers.
- `script_generator.py` — Gemini prompt that produces the per-beat structure.
- `style_bible.py` — all creative constants + the three audio volume tunables (single source of truth for mixing).
- `config.py` — model IDs (use the short version_ids!), output paths, GCS/YouTube config.
- `recover_custom_audio.py` — recovery of custom narrator from old `script.json`.
- `youtube_uploader.py` — optional direct upload (requires OAuth setup).
- `README.md` and `SKILL.md` — user-facing / agent-facing docs.
- **Root of repo:** `README.md` (artistic framing, featured YouTube video, channel promo, high-level usage) and `.gitignore` (security & hygiene — read this before any `git add`).

**Important repo-level files for handoff:**
- Root `.gitignore` (hardened to protect personal outputs and secrets).
- Root `README.md` (the public artistic statement + Holodeck premise).
- `AGENTS.md` at repo root (AI agent guidelines for the parent studio — we generally avoid touching `experiments/`).

## Quick Commands (for reference)

```bash
# Normal generation (uses current structure + current audio balance)
uv run python -m slop_fiction_maker.generate_episode "your premise" --duration 120

# Re-mix an existing native video with new balance (edit style_bible.py first if desired)
uv run python -c '
from slop_fiction_maker.audio import mix_scene
mix_scene(".../final/slop_fiction_episode_native_audio.mp4",
          ".../audio/custom_narration.wav",
          ".../audio/lyria_music.wav",
          ".../final/slop_fiction_episode_custom_audio_v3.mp4")
'

# Recover custom track from an old run
uv run python -m slop_fiction_maker.recover_custom_audio --run-dir "path/to/old/run/dir"
```

The code is intentionally kept relatively linear and easy to read (per the original "hands-off" spirit). Most creative levers are in `style_bible.py`. The heavy lifting re-uses the excellent primitives already present in the parent studio repo (`models/veo`, storage helpers, patterns from the story-generator skill).

## Fresh Machine / Handoff Setup Checklist

1. Clone the repo.
2. `cp dotenv.template .env` (root) and fill at minimum `PROJECT_ID`. Copy any needed values from the parent studio’s working `.env` (or set via environment).
3. (Optional but powerful) Set up YouTube:
   - Enable YouTube Data API v3.
   - Create OAuth Desktop credentials → `client_secrets.json`.
   - First `--upload` run will trigger browser auth and create `youtube_token.json`.
4. `uv sync` (or pip install -r requirements.txt) — the skill re-uses the parent repo’s Python environment.
5. Test: `python -m slop_fiction_maker.generate_episode --random --duration 120`
6. The first real run will create `slop_fiction_maker/output/YYYY-MM-DD/...` (this folder is gitignored — do not commit it).

**Security note (do not skip):** Before any commit or push, run `git status` and `git ls-files | grep -E 'output/|\.DS_Store|\.env'` to make sure nothing personal leaks. The hardened `.gitignore` + the `bd dolt push + git push` ritual (see AGENTS.md) are mandatory for this repo.

This should give you (or a future agent) enough context to continue iterating without having to reverse-engineer the entire history. The core vision — ridiculous premises turned into one-shot episodes that lean into model weirdness while quietly exploring what “personalized long-form generative media” can actually feel like — is implemented and working.

The main remaining knobs are around visual/motion continuity, script dialogue naturalism, and audio balance between native Veo character and any opt-in narrator.

*Onward toward the Holodeck. One face-slap at a time.*