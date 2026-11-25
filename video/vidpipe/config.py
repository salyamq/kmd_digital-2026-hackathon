"""Output formats and pipeline-wide defaults. Nothing topic-specific lives here."""

FORMATS = {
    # 9:16 short: 30-60 s. Russian/English narration runs at ~2 words/s (measured on RHVoice and SpeechKit
    # at speed 1.0), so the word budget is ~2x the target seconds.
    "short": {"w": 720, "h": 1280, "fps": 30, "orientation": "portrait",
              "target_s": [30, 60], "words": [60, 115]},
    # 16:9 explainer: 2-4 min
    "explainer": {"w": 1920, "h": 1080, "fps": 30, "orientation": "landscape",
                  "target_s": [120, 240], "words": [240, 470]},
}

# Order in which stages run. Each stage reads files written by earlier stages only,
# so any stage can be re-run alone (see cli.py).
STAGES = ["brief", "script", "shotlist", "specs", "models", "audio",
          "layout", "render", "overlays", "compose", "qa", "passport"]
# audio runs after planning (it does not change the plan) and before layout (the voice drives the edit),
# so 'rebuild --from audio' re-voices and re-times a video without re-planning it.

# Stage I/O contract. REQUIRES: files a stage reads ({shot} = every shot in 02_shotlist.json,
# {model_shot} = every shot whose spec has a state model, {video_id} from the brief).
# PRODUCES: which stage writes each of them (used to say "run --from <stage>" when something is missing).
# DIRS: folders a stage writes into; created before the stage runs.
STAGE_REQUIRES = {
    "script": ["00_brief.json"],
    "shotlist": ["00_brief.json", "01_script.json"],
    "specs": ["01_script.json", "02_shotlist.json", "03_scene_specs/{shot}.json"],
    "models": ["02_shotlist.json", "03_scene_specs/{shot}.json"],
    "audio": ["00_brief.json", "01_script.json"],
    # layout re-evaluates a state model whose output is missing (04_models is a cache), so it is not required
    "layout": ["01_script.json", "02_shotlist.json", "03_scene_specs/{shot}.json", "06_audio/audio.json"],
    "render": ["02_shotlist.json", "timeline.json", "05_renders/{shot}.layout.json"],
    "overlays": ["01_script.json", "02_shotlist.json", "timeline.json", "05_renders/{shot}.layout.json",
                 "03_scene_specs/{shot}.json"],
    "compose": ["timeline.json", "07_overlays/overlays.json", "05_renders/{shot}.mp4", "06_audio/audio.json"],
    "qa": ["01_script.json", "02_shotlist.json", "timeline.json", "07_overlays/overlays.json",
           "06_audio/audio.json", "08_final/{video_id}.mp4"],
    "passport": ["qa.json", "08_final/{video_id}.mp4"],
}
STAGE_PRODUCES = {
    "00_brief.json": "brief", "01_script.json": "script", "02_shotlist.json": "shotlist",
    "03_scene_specs/{shot}.json": "shotlist",
    "06_audio/audio.json": "audio", "timeline.json": "layout", "05_renders/{shot}.layout.json": "layout",
    "05_renders/{shot}.mp4": "render", "07_overlays/overlays.json": "overlays",
    "08_final/{video_id}.mp4": "compose", "qa.json": "qa",
}
STAGE_DIRS = {
    "script": ["llm"], "shotlist": ["03_scene_specs", "llm"], "specs": ["03_scene_specs"], "models": ["04_models"],
    "audio": ["06_audio"], "layout": ["05_renders", "04_models"], "render": ["05_renders/frames", "05_renders/qa"],
    "overlays": ["07_overlays"], "compose": ["08_final"], "qa": ["05_renders/qa"], "passport": [],
}

# Shot timing
SHOT_PAD_HEAD = 0.25      # silence before first line of a shot (s)
SHOT_PAD_TAIL = 0.35      # hold after the last line of a shot (s)
LINE_GAP = 0.22           # pause between two lines inside one shot (s)
MIN_SHOT_S = 2.0
TARGET_SHOT_MAX_S = 6.0   # brief: shots of 2-6 s (A/B continuous scenes may run longer, QA notes it)
XFADE_FRAMES = 8          # cross-fade between shots

LOUDNESS_LUFS = -16.0

# Classes and what provenance label each implies (label keys, localized in i18n.json)
CLASS_LABEL = {
    "A": "data",          # rendered from real data
    "B": "simulation",    # computed process; "schematic" when no numeric model drives it
    "C": "photo",         # real photo -> label is not in the organizers' set: flagged for the team
    "D": "schematic",     # atmosphere; label outside set must be flagged, never invented
    "T": "schematic",     # full-screen text card (question, myth/fact, equation, list): a separate class in QA
}

# Shares the brief asks for
MIN_AB_SHARE = 0.70
MAX_D_CLIPS = 2
MAX_CARD_SHARE = 0.25          # class T screen time
VISUAL_ROLES = ("mechanism", "data")   # these lines must be shown on a visual shot (class A/B/C)
