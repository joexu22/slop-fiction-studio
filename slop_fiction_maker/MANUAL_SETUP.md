# Manual Setup & Engineering Audit Guide

**Audience:** a human. No AI agent required, no prior knowledge of this repo
assumed. Read this if you want to set the system up from scratch by hand, or
if an agent did the setup and you want to verify ("audit") what it actually
did to your machine and your Google Cloud project.

Every section has a **"Verify it yourself"** part — a command or console page
that proves the claim without trusting this document.

---

## 1. What this system is, in one paragraph

You give it an audio recording (or a story idea). It uses Google Cloud's
generative models — Gemini for writing/transcription, Veo for video — to
produce a finished video: scripted, generated clip-by-clip, stitched together
with ffmpeg, and optionally uploaded to YouTube. Everything runs from your
machine; Google Cloud does the model inference and stores copies of the media.
**Generation costs real money** (roughly $0.05–$0.40 per second of video
depending on model — see §8).

## 2. What's installed on your machine (and why)

| Tool | Why it's needed | Verify it yourself |
|---|---|---|
| `uv` | Python package manager; creates `.venv/` and installs everything in `pyproject.toml` | `uv --version` |
| `gcloud` | Google Cloud CLI: authentication + enabling APIs | `gcloud --version` |
| `gsutil` | Downloads generated clips from Google Cloud Storage | `which gsutil` |
| `ffmpeg` / `ffprobe` | All local video work: trimming clips, stitching, mixing audio | `ffmpeg -version` |

Python dependencies live in `pyproject.toml` (repo root). The ones added for
this skill specifically: `google-api-python-client` + `google-auth-oauthlib`
(YouTube upload), `mcp` (the agent interface, §7). Install/update everything
with `uv sync`.

## 3. Local configuration files

| File | Contains | Committed to git? |
|---|---|---|
| `.env` (repo root) | `PROJECT_ID=<your GCP project>` — the only required setting | **No** (gitignored) |
| `client_secrets.json` | YouTube OAuth app identity (created in §6) | **No** (gitignored) |
| `youtube_token.json` | Your YouTube authorization token (created in §6) | **No** (gitignored) |
| `slop-video-workspace/` | Drop folder for your audio recordings | **No** (gitignored) |
| `slop_fiction_maker/output/` | All generated videos, scripts, logs | **No** (gitignored) |

**Verify it yourself** (this is the most important security check in the repo —
run it before every push):

```bash
git ls-files | grep -E 'output/|\.DS_Store|^\.env$|client_secret|youtube_token|workspace'
# Must print nothing.
```

To recreate `.env` by hand:

```bash
echo "PROJECT_ID=$(gcloud config get-value project)" > .env
```

All other settings have sensible defaults (see `slop_fiction_maker/config.py` —
it's 100 lines and readable). Notable optional ones:
`SLOP_AUDIO_STORY_VEO_MODEL` (default `3.1-lite`, the cheap tier),
`SLOP_WORKSPACE_DIR` (default `slop-video-workspace/`),
`SLOP_RECORD_TO_FIRESTORE` (default `true`).

## 4. Google Cloud project setup

Everything below happens inside one GCP project (this repo currently uses
the ID in your local `.env`; redacted here). Manual from-scratch steps:

```bash
gcloud auth login                      # browser sign-in
gcloud config set project <PROJECT_ID>
gcloud auth application-default login  # lets the Python code use your auth
```

**APIs that must be enabled** (each is a one-line command; all free to enable):

```bash
gcloud services enable aiplatform.googleapis.com   # Vertex AI: Gemini + Veo
gcloud services enable texttospeech.googleapis.com # optional narrator voice
gcloud services enable firestore.googleapis.com    # run history (see §5)
gcloud services enable youtube.googleapis.com      # YouTube upload (see §6)
```

**Storage bucket** — generated media is uploaded to
`gs://<PROJECT_ID>-assets/` (the code derives this name automatically from
`config/default.py`):

```bash
gcloud storage buckets create gs://<PROJECT_ID>-assets --location=us-central1
```

**Verify it yourself:**

```bash
gcloud services list --enabled | grep -E "aiplatform|firestore|youtube|texttospeech"
gcloud storage ls          # bucket exists
gcloud storage ls gs://<PROJECT_ID>-assets/slop_fiction_audio_stories/  # your videos
```

## 5. Firestore (run history — optional but enabled)

**What it is:** a small Google database. After each generation, one record
(title, GCS path, duration) is written so the studio web UI's "Library" page
can list your runs. **Cost: $0** at this usage — the free tier allows 20,000
writes/day; this writes one per video.

Manual setup (done on 2026-06-09 for this project):

```bash
gcloud services enable firestore.googleapis.com
gcloud firestore databases create --location=us-central1
```

To opt out instead: put `SLOP_RECORD_TO_FIRESTORE=false` in `.env`. Generation
works fine either way — a Firestore failure is deliberately non-fatal (see the
`try/except` at the bottom of `slop_fiction_maker/audio_to_video.py`).

**Verify it yourself:** [Firestore console](https://console.cloud.google.com/firestore)
→ database `(default)` → collection `genmedia` fills up as you generate.

## 6. YouTube upload (one-time OAuth setup)

**What OAuth is doing here:** YouTube uploads act *as your channel*, which
Google only allows through a browser consent flow — no API key shortcut.
Two files result: `client_secrets.json` (identifies "this app may ask for
permission") and `youtube_token.json` (your actual granted permission).
Both are gitignored; whoever holds `youtube_token.json` can upload to your
channel, so treat it like a password.

Steps (only #2–4 are manual; Google doesn't allow automating them):

1. API is already enabled (§4).
2. [Console → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent):
   External, fill the minimum, **add your own Google account as a test user**.
3. **Set the app's Publishing status to "In production"** (same consent-screen
   page). It will say "unverified" — that's fine, you click through a warning
   once during auth. Why this matters: in "Testing" status Google expires the
   token every **7 days**, silently breaking upload weekly.
4. [Console → Credentials](https://console.cloud.google.com/apis/credentials):
   Create Credentials → OAuth client ID → type **Desktop app** → download the
   JSON → save as `client_secrets.json` in the repo root.
5. ```bash
   uv run python -m slop_fiction_maker.youtube_uploader --setup
   ```
   A browser opens. Sign in with the account, and — **this is the step that
   decides where videos land** — on Google's channel-chooser page pick the
   **brand channel** (e.g. "Slop Fiction"), not your personal channel. The
   token permanently acts as whichever identity you pick. On success the
   helper prints the channel name it will upload to.

**Wrong-channel protection:** set `YOUTUBE_EXPECTED_CHANNEL=Slop Fiction` in
`.env`. Setup then refuses a token for any other channel, and every upload
re-verifies the channel before sending bytes (see `_check_expected_channel`
in `youtube_uploader.py`). Picked wrong? Delete `youtube_token.json` and
re-run `--setup`.

**Known caveat:** YouTube sometimes locks videos uploaded by *unverified* API
projects to private until the project passes YouTube's API audit. If your
unlisted uploads show "locked private" in YouTube Studio, that's what
happened — the fix is YouTube's API verification form, not anything in this
repo.

**Default upload behavior** (decided 2026-06-09): audio-story builds upload
automatically as **unlisted** — you review via the link and click "public" in
YouTube Studio. `--no-upload` skips it; `--privacy public|private` changes it.
Episode builds remain opt-in (`--upload`).

**Verify it yourself:** the requested permissions are in
`slop_fiction_maker/youtube_uploader.py` → `SCOPES` (upload + read-only; it
cannot delete videos or change channel settings). Revoke access anytime at
[myaccount.google.com/permissions](https://myaccount.google.com/permissions),
then delete `youtube_token.json`.

## 7. The MCP server (the "agents can drive this" part)

**What MCP is:** a standard protocol that lets AI agents (Claude Code, Gemini
CLI, …) call tools in external programs. `.mcp.json` at the repo root tells
agents: "run `uv run python -m slop_fiction_maker.mcp_server` and talk to it".
The server is `slop_fiction_maker/mcp_server.py` (~250 lines) and exposes five
tools — generate audio-story, generate episode, check job, list runs, upload
run. **It only runs while an agent session has it open; nothing is installed
system-wide and no network port is opened** (it talks over stdin/stdout).

**The job trick to be aware of:** generations take 5–20+ minutes, so the
generate tools don't wait. They start the normal CLI as a detached background
process and return a `job_id`. The bookkeeping lives in
`slop_fiction_maker/output/.jobs/`:

- `<job_id>.log` — full output, identical to running the CLI yourself
- `<job_id>.json` — command, process ID, exit code

This means **a generation may still be running (and spending money) after an
agent conversation ends.** To audit or stop one by hand:

```bash
cat slop_fiction_maker/output/.jobs/<job_id>.json   # command + pid + exit_code
tail -f slop_fiction_maker/output/.jobs/<job_id>.log
kill <pid>                                          # stop it; resume later (§9)
```

You never need MCP — every tool is a thin wrapper over a CLI you can run
yourself (§9).

## 8. Costs (the part worth auditing most)

Veo video generation is billed per second of *generated* video:

| Model (`config/veo_models.py` id) | $/sec (720p, with audio) | A 30s audio story | A 3-min episode |
|---|---|---|---|
| `3.1-lite` (audio-story default) | $0.05 | ~$1.70–2.40 | — |
| `3.1-fast` (episode default) | $0.10 | ~$3.40–4.80 | ~$18–25 |
| `3.1` | $0.40 | — | ~$72–100 |

Failed/filtered generations aren't billed, but clips already generated before
a mid-run crash are. That's what the resume flags are for (§9). Gemini
(transcription/scripts) and storage costs are pennies by comparison.

**Verify it yourself:**
[Console → Billing → Reports](https://console.cloud.google.com/billing),
filter by service "Vertex AI".

## 9. Running it by hand (no agent anywhere)

```bash
# Storytime video from your newest recording in slop-video-workspace/
uv run python -m slop_fiction_maker.audio_to_video --topic-hint "running out of budget"

# Explicit file, no YouTube upload
uv run python -m slop_fiction_maker.audio_to_video path/to/audio.m4a --no-upload

# Full episode from a premise
uv run python -m slop_fiction_maker.generate_episode "a talking sword joins a sect" --duration 180

# Resume an audio-story run that died at beat 3 (reuses paid-for clips)
uv run python -m slop_fiction_maker.audio_to_video \
  --resume-dir slop_fiction_maker/output/<date>/<run>/ --start-beat 3
```

Each run creates `slop_fiction_maker/output/YYYY-MM-DD/NNN-slug/` containing
every intermediate artifact, so the whole generation is inspectable after the
fact: `transcript.json` (what Gemini heard, with timestamps),
`storyboard.json` (the visual plan + exact timing windows), `clips/` (raw Veo
output before and after trimming), `final/` (the deliverable), and
`metadata.json` (title/description/tags + GCS/YouTube URLs).

## 10. How the audio-story pipeline actually works (plain language)

1. **Transcribe** (`audio_story.py: transcribe_audio`) — Gemini listens to
   your audio and returns phrases with start/end times.
2. **Storyboard** (`audio_story.py: plan_audio_storyboard`) — Gemini plans
   "beats". Each beat owns an exact slice of your audio timeline and
   describes a cultivation-fantasy visual for what's being said. Code in
   `_normalize_beats` then enforces the rules no matter what the model
   returned: no gaps, no overlaps, no beat longer than 8s (Veo's max).
3. **Generate** (`audio_to_video.py: _generate_beat_clips`) — one Veo clip
   per beat. Veo only makes 4/6/8-second clips, so each clip is ordered at
   the *next size up* from its beat (a 5.3s beat gets a 6s clip). Characters
   pantomime; at most one short shouted exclamation per beat.
4. **Post-production** (`audio.py`) — each clip is *trimmed down* to its
   beat's exact duration (this is how video cuts land precisely on your
   phrases — the surplus is discarded, your audio is never altered), clips
   are concatenated, then your original audio is laid on top at full volume
   with the Veo sound ducked to 25%.
5. **Publish** — upload to GCS, write `metadata.json`, optionally YouTube
   (unlisted), optionally a Firestore record.

The key engineering promise to audit: **the source audio is never cut,
stretched, or re-timed — the video is always bent to fit the audio.**
Check it: `ffprobe` the final video and the source audio; durations match
within one video frame (~0.04s).

## 11. Change log of the agent-driven setup (2026-06-09)

So the trail is explicit, this is everything that session changed:

**On Google Cloud** (the owner's project — ID redacted, see local `.env`):
- Enabled `firestore.googleapis.com` and `youtube.googleapis.com`
- Created Firestore database `(default)` in `us-central1`
- (Bucket `gs://<PROJECT_ID>-assets` already existed)

**In the repo:**
- New: `audio_story.py`, `audio_to_video.py` (the audio-story pipeline),
  `jobs.py`, `mcp_server.py` (agent interface), `.mcp.json`, this file
- Modified: `audio.py` (trim/mix helpers), `config.py` (workspace dir,
  YouTube paths, lite model default), `style_bible.py` (volume knobs),
  `youtube_uploader.py` (`--setup` flow), `pyproject.toml` (3 deps),
  `.gitignore` (OAuth secrets + workspace), docs (`README.md`, `SKILL.md`,
  `HANDOFF.md`, root `AGENTS.md`)

**On this machine:**
- Created `.env` containing only `PROJECT_ID=<the GCP project ID>`
- `uv sync` (installed the new Python deps into `.venv/`)

**Later the same evening (2026-06-09, continued):**
- YouTube OAuth completed by the owner: consent screen created and set to
  **"In production"**, Desktop OAuth client created, browser auth done with the
  **Slop Fiction Brand Account** selected. `client_secrets.json` and
  `youtube_token.json` now exist at the repo root (both gitignored).
- Wrong-channel guard added: `YOUTUBE_EXPECTED_CHANNEL=Slop Fiction` in `.env`;
  `youtube_uploader.py` refuses tokens/uploads for any other channel.
- Shorts mode added to the episode pipeline: `--aspect-ratio 9:16` flag
  (`generate_episode.py`, `video_chainer.py`) and the script beat-count floor
  lowered 12 → 4 (`script_generator.py`).
- First two YouTube uploads from the pipeline: a stray private "guard test"
  video (delete it manually in Studio — the upload-only token can't) and the
  real one, run 007 "Slop Dao" unlisted: https://youtu.be/yyShW0TuyeA
- `slop-video-workspace/` added to `.gitignore` (personal recordings).

**Verify it yourself:** `git log --stat` and `git diff` show every repo
change; the GCP console's [Activity log](https://console.cloud.google.com/home/activity)
shows the cloud-side actions.

---

*Deep technical rationale and decision history: [HANDOFF.md](HANDOFF.md).
Agent-facing tool reference: [SKILL.md](SKILL.md).*
