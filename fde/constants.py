from __future__ import annotations

STAGE_DIRECTORIES = [
    "00_input",
    "01_research",
    "02_structure",
    "03_narration",
    "04_voice/chapters",
    "05_timing",
    "05_master_assets/prompts",
    "05_master_assets/history",
    "06_shots/overlays",
    "07_images",
    "08_animatic/sfx",
    "09_videos",
    "10_final_preview",
    "12_timeline/overlays",
    "_history",
    "_jobs",
    "_requests",
    # Compatibility directories for projects created before the audio-first two-pass flow.
    "03_script",
    "04_shot_plan",
    "06_contact_sheet",
    "07_review",
    "08_generated_images/inbox",
    "08_generated_images/approved",
    "08_generated_images/rejected",
    "08_generated_images/thumbnails",
    "09_video_jobs/prompts",
    "10_generated_videos/inbox",
    "10_generated_videos/approved",
    "10_generated_videos/rejected",
    "10_generated_videos/variants",
    "11_narration",
    "13_preview",
    "14_final",
]

DEFAULT_GLOBAL_STYLE = (
    "High-end failure-investigation documentary reconstruction; photorealistic and technically "
    "credible; dark navy, charcoal and steel-blue palette; restrained teal instrumentation; "
    "subtle amber practical highlights; realistic scale and movement; cinematic 16:9 composition; "
    "clear negative space for technical overlays; no embedded text, subtitles, watermark, fantasy "
    "lighting, sensational explosion, or gratuitous suffering."
)

DOCUMENTARY_PERFORMANCE_TAGS = (
    "quietly investigative",
    "curious",
    "clear and measured",
    "gentle emphasis",
    "thinking pause",
    "serious",
    "with restrained urgency",
    "somber",
    "reflective",
)
