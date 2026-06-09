# Slop Fiction Studio

> **Meme Slop Fiction Generator** — an art project / automated video & shorts experiment  
> Adapted from Google’s Vertex AI GenMedia Creative Studio (original GenMedia Creative Studio for Veo, Imagen, Lyria, etc.)

> ###### _This is not an officially supported Google product. This project is not eligible for the [Google Open Source Software Vulnerability Rewards Program](https://bughunters.google.com/open-source-security). This project is intended for demonstration and artistic purposes only._

---

## The Premise (the joke and the point)

**This is a joke.** 

We took a powerful Google Cloud generative media stack (Veo video, Gemini, Lyria, image models, chaining, native audio, post-production) and pointed it at the most unhinged possible use case: fully automated, one-shot "Slop Fiction" — gloriously over-the-top Chinese cultivation xianxia short films and 2–5 minute episodes. Badass young masters, face-slapping, forbidden techniques, Studio Ghibli aesthetics, and zero restraint.

The `slop_fiction_maker/` skill is the heart of this fork. Give it a ridiculous premise and it writes the script (with in-scene dialogue), generates chained video beats with native audio, stitches everything, makes thumbnails, titles, descriptions, tags, and can even push to YouTube.

**But the joke has a real core.**

This project is an exploration of **personalized, automated, long-form story generation**. What happens when you can summon a complete, weird little film from a single sentence in seconds?

The deeper, non-joke premise:

We are standing on the steps to the **Holodeck**.

Every media generation system — whether it’s producing prestige cinematic work, careful indie experiments, or magnificent trash like this — is reaching toward the same thing: instant, personal, responsive, living media. Stories that react to you. Worlds you can step inside. The Holodeck was never just about perfect pixels; it was about *agency and immediacy* in storytelling.

The current wave of generators, slop or sublime, are the awkward, charming, sometimes unhinged early prototypes of that future. This project deliberately takes one of the silliest possible paths and sees how far the tools can actually carry it.

If you’re here for the slop: welcome, the slop is the point.  
If you’re here for the technique: the pipelines, prompting strategies, chaining, audio handling, and post-production tricks are real and reusable.  
If you’re here for the Holodeck thought: you’re in the right place.

---

## What’s in this repo

- **`slop_fiction_maker/`** — The main artifact: a self-contained, one-shot episode generator you can call from the command line, from agents, or as an MCP skill.
- The full underlying **GenMedia Creative Studio** stack (the original web app, models, workflows, components) — this is a personal adaptation/fork focused on the slop fiction experiment.
- Lots of experiments, MCP servers, and generative techniques inherited from the original Google Cloud platform project.

See [slop_fiction_maker/README.md](slop_fiction_maker/README.md) for how to actually run the meme machine.

The original studio documentation and capabilities are still here if you want to use the serious tools for less ridiculous things.

---

## Original GenMedia Creative Studio (for reference)

The code and architecture in this repository are adapted from the Vertex AI GenMedia Creative Studio — a web application showcasing Google Cloud’s generative media capabilities (Veo, Lyria, Gemini Image Generation, Chirp, custom workflows like character consistency, shop-the-look, interior design, etc.).

It is built with [Mesop](https://mesop-dev.github.io/mesop/).

For the original project’s full documentation, deployment guides, and experiments, see the upstream at:
https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio (or the docs site linked in the original README below).

Current inherited feature set (the powerful substrate we’re abusing for slop):

- **Image:** Gemini Flash Image, Gemini 3 Pro Image, Virtual Try-On, Imagen models
- **Video:** Veo 3.1, Veo 3, Veo 2 + extension chaining
- **Music:** Lyria
- **Speech:** Chirp 3 HD + Gemini TTS
- **Workflows & Library** for media management

---

## Quick Start (Slop Mode)

```bash
# One random episode
python -m slop_fiction_maker.generate_episode --random --duration 180

# Or feed it your worst idea
python -m slop_fiction_maker.generate_episode \
  "a fallen genius re-cultivates using a forbidden bloodline technique that slowly turns him into a demon" \
  --duration 240
```

See the full [slop_fiction_maker/README.md](slop_fiction_maker/README.md) for agent/MCP usage, custom narration, YouTube upload, etc.

---

## Contributing / Forking

This is primarily a personal art/experiment repo. PRs that improve the generation pipelines, prompting, or Holodeck-adjacent ideas are welcome. Pure slop improvements are also welcome.

The original project’s contributing guidelines still apply for the shared studio code.

## Licensing

Code is licensed under Apache 2.0 (inherited). See [LICENSE](LICENSE).

## Disclaimer

> [!CAUTION]
> This is **not** an officially supported Google product.
> This fork is an unofficial, artistic, and highly unserious adaptation for exploration and meme purposes.

---

*Onward toward the Holodeck. One face-slap at a time.*

## 📖 Documentation Hub

**For comprehensive guides, deployment instructions, architecture details, and developer workflows, please visit our [Documentation Hub](https://googlecloudplatform.github.io/vertex-ai-creative-studio/).**

Stay up-to-date with upcoming breaking changes and releases on our **[Changelog & Notices](https://googlecloudplatform.github.io/vertex-ai-creative-studio/core/changelog/)** page.

---

### Quick Start

If you want to quickly run the UI without having to set up a local development environment, use Cloud Shell and follow the tutorial instructions:

[![Open in Cloud Shell](https://gstatic.com/cloudssh/images/open-btn.svg)](https://shell.cloud.google.com/cloudshell/editor?cloudshell_git_repo=https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio.git&cloudshell_tutorial=tutorial.md)

### Deploying to Google Cloud

The application is designed to be deployed using Terraform and Cloud Run. You have the flexibility to deploy using a custom domain (with Identity Aware Proxy and a Load Balancer) or using the autogenerated Cloud Run domain. 

For detailed, step-by-step instructions on setting up your environment, configuring custom domains, and managing Identity Aware Proxy (IAP), please see the [Deployment Guide on our Documentation Hub](https://googlecloudplatform.github.io/vertex-ai-creative-studio/core/installation/deploy/).

## Experiments & MCP Tools

The `experiments/` folder contains a variety of stand-alone applications, new workflows, and Model Context Protocol (MCP) servers that showcase cutting-edge capabilities with generative AI. This includes combined workflows for video generation, advanced prompting techniques, image recontextualization, and audio exploration.

To explore the available experiments, view architecture diagrams, and find installation instructions for our MCP tools, head over to the [Experiments Section of our Documentation Hub](https://googlecloudplatform.github.io/vertex-ai-creative-studio/experiments/overview/).

## Contributing changes

Interested in contributing? Please open an issue describing the intended change. Additionally, bug fixes are welcome, either as pull requests or as GitHub issues.

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to contribute.

## Licensing

Code in this repository is licensed under the Apache 2.0. See [LICENSE](LICENSE).

## Disclaimer

> [!CAUTION]
> This is **not** an officially supported Google product.
> This project is not eligible for the [Google Open Source Software Vulnerability Rewards Program](https://bughunters.google.com/open-source-security).