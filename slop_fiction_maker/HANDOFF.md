# Slop Fiction Maker — Handoff Document

**Project:** `slop-fiction-studio` (personal fork/art project)  
**Core Artifact:** `slop_fiction_maker/` — a one-shot AI skill for generating "Meme Slop Fiction" cultivation videos in three forms: 2–5 minute episodes (16:9), vertical Shorts (9:16, ≤60s target), and "audio-story" storytime videos built around a user-provided audio recording.

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

## Quick Status at Handoff (updated 2026-06-10)
- **Per-beat independent generation + ffmpeg post-stitch is the default video path** (extension chains are capped at ~30s; the long-chain notes below in Decision 1/5 are historical).
- **Native in-video dialogue is the default audio** (Decision 6); the custom TTS narrator is opt-in via `--with-custom-narration`.
- **Three working pipelines:** episodes (`generate_episode.py`), Shorts (same CLI with `--aspect-ratio 9:16` + short `--duration`, see Decision 10), and audio-story storytime videos (`audio_to_video.py`, see Decision 8). Proven runs: 006 (audio story from a voice memo), 007 (Slop Dao short, 9:16, 66s).
- **MCP server live** (`mcp_server.py`, registered in root `.mcp.json`) — any agent can generate/poll/upload via 5 tools with a detached-job pattern (Decision 9).
- **YouTube upload fully configured** (2026-06-09): OAuth done, token bound to the Slop Fiction Brand Account, wrong-channel guard active (`YOUTUBE_EXPECTED_CHANNEL` in `.env`), consent screen "In production" so the token doesn't expire weekly. Audio-story builds auto-upload unlisted; episodes are opt-in. First upload verified live: https://youtu.be/yyShW0TuyeA (007, unlisted).
- **Firestore + YouTube Data APIs enabled** in the owner's GCP project (ID lives in the local `.env`, redacted here per repo convention); run records write successfully.
- Clean `YYYY-MM-DD/NNN-slug/` + `clips/`, `audio/`, `final/` structure is enforced; job logs live under `output/.jobs/`.
- All major early errors (model version_id strings, TTS 403, image 400 fallback, duration clamping, folder hygiene) have been addressed or documented.
- **Default cost posture:** audio-story and Shorts run on `3.1-lite` (~$0.05/s, the jank is on-brand); episodes default to `3.1` unless `SLOP_VEO_MODEL` overrides.

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

3. **Custom Audio Layer** (`audio.py`) — **opt-in only** (`--with-custom-narration`; see Decision 6)
   - When enabled: full custom over-the-top narrator track is generated from the joined per-beat `narration_text` lines + the chosen persona (via Gemini TTS with strong style prompt, falling back to Chirp 3 HD).
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

### 3. Custom Audio Always Runs (Now That TTS Is Enabled) — *historical; superseded by Decision 6 (custom narration is opt-in now)*
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

### 8. Audio-Story Mode (June 2026)
- **What:** `audio_to_video.py` + `audio_story.py` — the inverse pipeline. A user-provided
  audio file is the master soundtrack; Gemini transcribes it with timestamps, plans beats
  that each own an exact audio window, Veo generates per-beat clips (silent pantomime +
  at most one short exclamation), and post trims each clip to its exact window before
  laying the original audio on top (Veo audio ducked to `AUDIO_STORY_NATIVE_VOLUME`).
- **Why:** The user wanted to make videos *about* existing audio recordings (storytime
  style) and was explicitly worried about clip durations (4/6/8s) not lining up with the
  voice. The solution: clips are generated at the next supported duration ≥ the beat's
  window and trimmed to the exact window in post — the master audio is never altered.
- **Model:** defaults to `3.1-lite` (cheapest audio-capable tier) since the clips are
  deliberately comedic background; `SLOP_AUDIO_STORY_VEO_MODEL` overrides.
- **Resume:** `--resume-dir` + `--start-beat` reuses the saved `storyboard.json` so beat
  windows stay consistent with already-generated clips (unlike the episode pipeline,
  regenerating the plan on resume would break timing).
- **Not built yet (by choice):** overlay/PiP compositing over a background slop video,
  and any logic that re-times or cuts the source audio.
- **Proven:** run 006 (2026-06-09, "Kennewick Rd" voice memo about running out of budget,
  28s, 5 beats, ~$1.70).

### 9. MCP Server + Auto-Upload + Firestore (June 2026)
- **MCP server** (`mcp_server.py` + `jobs.py`, registered via root `.mcp.json`): the
  general agent interface. Tools return a `job_id` immediately and the generation runs
  as a detached subprocess (runner pattern in `jobs.py` — the runner waits on the real
  command and records the exit code in `output/.jobs/<id>.json`, because a directly
  detached child becomes a zombie that still looks alive to `os.kill`). Stdout is the
  MCP protocol channel, so all package imports in `mcp_server.py` are wrapped in
  `redirect_stdout(stderr)` — the studio modules print at import time.
- **Auto-upload unlisted:** audio-story builds now default to
  `upload_to_youtube=True, privacy="unlisted"` (`--no-upload` to skip). Episode pipeline
  stays opt-in. `client_secrets.json`/`youtube_token.json` are gitignored.
- **Workspace drop folder:** `slop-video-workspace/` at the repo root
  (`SLOP_WORKSPACE_DIR` to override). CLI/MCP with no audio path = newest audio file there.
- **Firestore enabled** in the project (June 9, 2026: API + `(default)` database in
  us-central1), so `RECORD_TO_FIRESTORE` works now. YouTube Data API v3 also enabled.
- **YouTube OAuth COMPLETED (2026-06-09)** and verified end-to-end: token bound to the
  **Slop Fiction Brand Account** (the channel-chooser step during the browser auth decides
  this), consent screen set to "In production" (testing-status tokens expire every 7
  days), and the first upload is live unlisted: https://youtu.be/yyShW0TuyeA (run 007).
- **Wrong-channel guard:** `YOUTUBE_EXPECTED_CHANNEL=Slop Fiction` in `.env`. Setup
  refuses a token for any other channel, and every upload re-verifies identity before
  sending bytes (`WrongChannelError` in `youtube_uploader.py`). To redo the binding:
  delete `youtube_token.json`, re-run `--setup`, pick the brand channel.
- **Token scope is deliberately minimal** (upload + readonly): it cannot delete videos
  or change channel settings. Side effect: a stray private "guard test" video uploaded
  during verification on 2026-06-09 must be deleted manually in YouTube Studio.
- **Caveat to watch:** unverified API projects can have uploads locked private by
  YouTube until passing their API audit. Run 007 was NOT locked (verified in Studio),
  so this hasn't bitten — but check new uploads occasionally.

### 10. Shorts Mode (June 2026)
- **What:** the episode pipeline now does vertical Shorts. `--aspect-ratio 9:16` on
  `generate_episode.py` (threaded through `video_chainer.py` including reference-image
  aspect), and the script generator's beat-count floor dropped from 12 to 4
  (`script_generator.py`) so short targets get proportionally few beats. Classic episode
  durations (120s+) are completely unaffected by the floor change.
- **Model for Shorts:** run with `SLOP_VEO_MODEL=3.1-lite` — ~8× cheaper than `3.1`
  and the Lite jank suits the format (user-approved aesthetic).
- **Proven:** run 007 (2026-06-09, "Slop Dao" agentic-programming meta-joke, 9 beats,
  9:16, ~$3.30, live unlisted at https://youtu.be/yyShW0TuyeA).
- **Known calibration gap:** 007 targeted 54s but came out 66s — Gemini's per-beat
  `approximate_duration_hint` leans toward 8s. Still fine (YouTube Shorts allows up to
  3 min vertical), but cap the hints or lower `--duration` if tighter cuts matter.

## Current Recommended Workflow (Hands-Off)

Three entry points, all one-shot:

1. **Episode from a premise** — `python -m slop_fiction_maker.generate_episode "..." --duration 180`.
   Produces a script with explicit per-beat `dialogue`, one independent Veo clip per beat
   (characters speak via native audio), ffmpeg-stitched into
   `final/slop_fiction_episode_native_audio.mp4`. Add `--with-custom-narration` for the
   old external narrator on top; `--upload` to publish.
2. **Short from a premise** — same CLI with `--aspect-ratio 9:16 --duration 54` and
   `SLOP_VEO_MODEL=3.1-lite` in the environment (see Decision 10).
3. **Storytime video from a recording** — drop the audio file in `slop-video-workspace/`
   and run `python -m slop_fiction_maker.audio_to_video --topic-hint "..."` (no path
   needed; newest file wins). Auto-uploads unlisted to the Slop Fiction channel.

Agents do the same through the MCP tools (`generate_episode`, `generate_audio_story`,
`check_job`, `list_runs`, `upload_run_to_youtube`) — see `SKILL.md`.

Re-mixing or recovering custom narration on any native run is still possible with the
utilities in `audio.py` / `recover_custom_audio.py`.

## Open / Future Work (Prioritized by User Feedback)

Done since the original list: ~~YouTube automation~~ (Decision 9), ~~Shorts adaptation~~
(Decision 10), ~~MCP tool wrapper~~ (Decision 9), ~~audio-driven generation~~ (Decision 8).

Still open, roughly in priority order:

- **Visual continuity between beats/clips** — the biggest quality lever. Last-frame
  extraction → reference image for the next beat would help a lot. Blocked partly by the
  image-helper 400 (Decision 7 / next bullet); character consistency currently rests on
  text descriptions alone.
- **Fix the reference-image 400** (`FAILED_PRECONDITION`): `models/image_models.py` still
  uses the old Vertex Predict path for `gemini-*-image` models. Every per-beat reference
  image silently fails and the pipeline continues without. Fixing this unlocks the
  continuity work above.
- **Shorts duration calibration:** per-beat duration hints lean 8s, so targets overshoot
  (54s → 66s on run 007). Cap hints for short targets in `script_generator.py` if needed.
- **Audio-story overlay mode:** composite beat clips picture-in-picture over a background
  slop video instead of full-screen cuts. The timed-beat structure supports it; it's one
  more ffmpeg pass (deliberately deferred).
- **Script quality (dialogue length, naturalism & flow):** iterate the prompt in
  `script_generator.py` if Veo-spoken lines feel too short or narrator-like.
- **More audio control:** per-beat custom lines, per-segment native-vs-custom choices.
  `--with-custom-narration` is the current escape hatch.
- **Scheduling / batching** for daily drops (the MCP job pattern is the natural substrate).
- **Publish flow:** uploads land unlisted by design; flipping to public is manual in
  YouTube Studio. Could add a `publish_run` tool if the manual step gets old.
- **YouTube API verification:** if uploads ever start getting locked private (unverified
  project caveat, Decision 9), file YouTube's API audit form.
- **Public handoff surface:** Keep the root README artistic statement + featured video +
  channel links fresh. Episode 004 (Jp2DN7GAbXw) is the pinned hero; the Slop Dao short
  (yyShW0TuyeA) is a candidate once public. Update when a new "best" drops.

## Key Files & Where Things Live

- `generate_episode.py` — main orchestrator (script → video → custom audio → metadata).
- `audio_to_video.py` — audio-story orchestrator (transcribe → storyboard → per-beat video → trim/concat/master-mix).
- `audio_story.py` — transcription, timed storyboard planning + normalization, storytime Veo prompts.
- `video_chainer.py` — the long extension logic + saving of step clips.
- `audio.py` — TTS, Lyria, `mix_scene` (the tunable ducking), assemble helpers.
- `script_generator.py` — Gemini prompt that produces the per-beat structure.
- `style_bible.py` — all creative constants + the three audio volume tunables (single source of truth for mixing).
- `config.py` — model IDs (use the short version_ids!), output paths, GCS/YouTube config.
- `recover_custom_audio.py` — recovery of custom narrator from old `script.json`.
- `youtube_uploader.py` — upload + `--setup` OAuth flow + wrong-channel guard (configured and working as of 2026-06-09).
- `jobs.py` — detached background jobs (runner pattern, registry in `output/.jobs/`).
- `mcp_server.py` — the agent interface (5 MCP tools over stdio; registered in root `.mcp.json`).
- `README.md` and `SKILL.md` — user-facing / agent-facing docs.
- `MANUAL_SETUP.md` — human-first setup + audit guide (no agent required): what each
  cloud service is for, where secrets live, costs, and per-claim verification commands.
- **Root of repo:** `README.md` (artistic framing, featured YouTube video, channel promo, high-level usage) and `.gitignore` (security & hygiene — read this before any `git add`).

**Important repo-level files for handoff:**
- Root `.gitignore` (hardened to protect personal outputs and secrets).
- Root `README.md` (the public artistic statement + Holodeck premise).
- `AGENTS.md` at repo root (AI agent guidelines for the parent studio — we generally avoid touching `experiments/`).

## Quick Commands (for reference)

```bash
# Normal generation (uses current structure + current audio balance)
uv run python -m slop_fiction_maker.generate_episode "your premise" --duration 120

# Vertical Short on the cheap model
SLOP_VEO_MODEL=3.1-lite uv run python -m slop_fiction_maker.generate_episode \
  "your premise" --duration 54 --aspect-ratio 9:16

# Storytime video from the newest recording in slop-video-workspace/
# (auto-uploads unlisted to the Slop Fiction channel)
uv run python -m slop_fiction_maker.audio_to_video --topic-hint "what it's about"

# Check a detached MCP-started job by hand
cat slop_fiction_maker/output/.jobs/<job_id>.json
tail -f slop_fiction_maker/output/.jobs/<job_id>.log

# Re-verify / redo the YouTube channel binding
uv run python -m slop_fiction_maker.youtube_uploader --setup

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

**Full human-readable version of this checklist (with per-step verification): `MANUAL_SETUP.md`.**

1. Clone the repo.
2. `cp dotenv.template .env` (root) and fill at minimum `PROJECT_ID`. Recommended:
   also `YOUTUBE_EXPECTED_CHANNEL=Slop Fiction` (the wrong-channel upload guard).
3. `uv sync` — the skill re-uses the parent repo's Python environment.
4. Enable the cloud APIs (one-time per project): `aiplatform`, `texttospeech`,
   `firestore` (+ create the `(default)` database), `youtube` — commands in
   `MANUAL_SETUP.md` §4–5.
5. (Optional but powerful) Set up YouTube: create an OAuth **Desktop** client in the
   console → save as `client_secrets.json` at repo root → set the consent screen to
   **"In production"** (avoids 7-day token expiry) →
   `uv run python -m slop_fiction_maker.youtube_uploader --setup` → **pick the Slop
   Fiction Brand Account on the channel chooser**. Details + pitfalls: `MANUAL_SETUP.md` §6.
6. Agents: `.mcp.json` at the repo root registers the MCP server automatically for
   Claude Code; other agents can use the same command (see `SKILL.md`).
7. Test cheap: `uv run python -m slop_fiction_maker.audio_to_video --no-upload` with any
   short audio file in `slop-video-workspace/` (~$1.50), or a Short per the Quick
   Commands above.
8. The first real run will create `slop_fiction_maker/output/YYYY-MM-DD/...` (this folder is gitignored — do not commit it).

**Security note (do not skip):** Before any commit or push, run `git status` and `git ls-files | grep -E 'output/|\.DS_Store|\.env'` to make sure nothing personal leaks. The hardened `.gitignore` + the `bd dolt push + git push` ritual (see AGENTS.md) are mandatory for this repo.

This should give you (or a future agent) enough context to continue iterating without having to reverse-engineer the entire history. The core vision — ridiculous premises (or a voice memo) turned into one-shot videos that lean into model weirdness while quietly exploring what "personalized generative media" can actually feel like — is implemented and working end-to-end: premise/audio in → unlisted YouTube video on the Slop Fiction channel out, drivable by hand, by CLI, or by any MCP-capable agent.

The main remaining quality lever is visual continuity between beats (blocked partly on the reference-image 400 fix); after that, script naturalism and the publish/scheduling conveniences in the Open Work list.

*Onward toward the Holodeck. One face-slap at a time.*