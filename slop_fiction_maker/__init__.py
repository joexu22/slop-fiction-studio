"""Slop Fiction Maker

An AI skill for fully automated, hands-off generation of 2-5 minute
cultivation slop fiction episodes using per-beat Veo generation + post-production stitching.

Invoke via:
    from slop_fiction_maker.generate_episode import generate_slop_episode

Audio-story (storytime) mode — an existing audio file becomes the master
soundtrack and the visuals act it out:
    from slop_fiction_maker.audio_to_video import generate_audio_story_video
"""

from .generate_episode import GenerationResult, generate_slop_episode
from .style_bible import STYLE

__all__ = ["STYLE", "GenerationResult", "generate_slop_episode"]
