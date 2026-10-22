"""
AI Faceless Video Generator
Pipeline:
  1. Script -> N scenes (word-split)
  2. Each scene -> 9:16 background image (Kie.ai gpt-image-2-text-to-image)
  3. Each image -> 5s animated clip with dynamic motion (Kie.ai wan/2-6-flash-video-to-video)
  4. Each clip -> trimmed to ~3.5s + burned-in caption (FFmpeg drawtext)
  5. Full script -> voiceover MP3 (ElevenLabs)
  6. Captioned clips + voiceover + optional music bed -> final MP4 (FFmpeg)
"""
from __future__ import annotations

import json
import logging
import subprocess
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_KIE_CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
_KIE_RECORD = "https://api.kie.ai/api/v1/jobs/recordInfo"
_KIE_IMAGE_MODEL = "gpt-image-2-text-to-image"
_KIE_VIDEO_MODEL = "wan/2-6-flash-video-to-video"
_EL_BASE = "https://api.elevenlabs.io/v1"

VOICES: dict[str, str] = {
    "Rachel – Female, Calm": "21m00Tcm4TlvDq8ikWAM",
    "Adam – Male, Deep": "pNInz6obpgDQGcFmaJgB",
    "Josh – Male, Energetic": "TxGEqnHWrfWFTfGW9XjX",
    "Antoni – Male, Smooth": "ErXwobaYiN019PkySvjV",
    "Bella – Female, Warm": "EXAVITQu4vr4xnSDxMaL",
}

# Kie.ai only supports 5s or 10s clips. We generate 5s and trim each to TRIM_TO
# seconds in FFmpeg — faster cuts = better retention.
# scenes × TRIM_TO ≈ target duration.
DURATION_CONFIG: dict[int, dict] = {
    30: {"scenes": 9,  "clip_seconds": 5, "trim_to": 3.5},
    60: {"scenes": 18, "clip_seconds": 5, "trim_to": 3.5},
}

# Rotating motion styles — applied round-robin across scenes for variety
_MOTION_STYLES = [
    "dramatic slow push-in zoom, camera slowly moving toward subject, cinematic",
    "fast whip pan left revealing new scene, dynamic motion blur, energetic",
    "upward tilt reveal, camera panning upward slowly, epic establishing shot",
    "parallax drift, subtle sideways camera slide, atmospheric depth",
    "slow pull-back zoom out reveal, expansive cinematic feel",
    "fast zoom-in punch, sudden dramatic scale change, high-impact",
    "smooth orbit around subject, subtle rotation, immersive",
    "handheld subtle shake, documentary realism, grounded feel",
    "diagonal wipe reveal, camera rolling slightly, dynamic angle change",
]


# ── Kie.ai helpers ─────────────────────────────────────────────────────────────

def _kie_headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _kie_poll(key: str, task_id: str, timeout: int = 480) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = httpx.get(f"{_KIE_RECORD}?taskId={task_id}", headers=_kie_headers(key), timeout=15)
        r.raise_for_status()
        data = r.json().get("data", {})
        status = (data.get("status") or "").lower()
        if status in ("succeed", "success", "completed", "finished"):
            return data
        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Kie task {task_id} failed: {data}")
        time.sleep(6)
    raise TimeoutError(f"Kie task {task_id} timed out after {timeout}s")


def _extract_image_url(data: dict) -> str:
    for work in (data.get("works") or []):
        for key in ("coverUrl", "imageUrl", "url", "outputUrl"):
            if work.get(key):
                return work[key]
    raise RuntimeError(f"No image URL in Kie response: {json.dumps(data)[:300]}")


def _extract_video_url(data: dict) -> str:
    for work in (data.get("works") or []):
        for key in ("url", "videoUrl", "outputUrl", "coverUrl"):
            v = work.get(key, "")
            if v and (v.endswith(".mp4") or "mp4" in v or "video" in key.lower()):
                return v
        for key in ("url", "videoUrl", "outputUrl"):
            if work.get(key):
                return work[key]
    raise RuntimeError(f"No video URL in Kie response: {json.dumps(data)[:300]}")


def _kie_generate_image(kie_key: str, prompt: str) -> str:
    body = {
        "model": _KIE_IMAGE_MODEL,
        "input": {"prompt": prompt, "aspect_ratio": "9:16", "resolution": "1K"},
    }
    r = httpx.post(_KIE_CREATE, headers=_kie_headers(kie_key), json=body, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"Kie image: code={payload.get('code')} {payload.get('msg')}")
    return _extract_image_url(_kie_poll(kie_key, payload["data"]["taskId"], timeout=480))


def _kie_animate_image(kie_key: str, image_url: str, motion_prompt: str, clip_seconds: int = 5) -> str:
    body = {
        "model": _KIE_VIDEO_MODEL,
        "input": {
            "video_urls": [image_url],
            "prompt": motion_prompt,
            "duration": clip_seconds,
            "resolution": "720p",
            "audio": False,
            "multi_shots": False,
        },
    }
    r = httpx.post(_KIE_CREATE, headers=_kie_headers(kie_key), json=body, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"Kie video: code={payload.get('code')} {payload.get('msg')}")
    return _extract_video_url(_kie_poll(kie_key, payload["data"]["taskId"], timeout=600))


# ── ElevenLabs TTS + Sound Effects ─────────────────────────────────────────────

def _elevenlabs_tts(el_key: str, text: str, voice_id: str, out_path: str) -> None:
    r = httpx.post(
        f"{_EL_BASE}/text-to-speech/{voice_id}",
        headers={"xi-api-key": el_key, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
    )
    r.raise_for_status()
    Path(out_path).write_bytes(r.content)


def _elevenlabs_sound_effect(el_key: str, prompt: str, duration: float, out_path: str) -> None:
    """Generate background music/sound via ElevenLabs Sound Generation API."""
    r = httpx.post(
        f"{_EL_BASE}/sound-generation",
        headers={"xi-api-key": el_key, "Content-Type": "application/json"},
        json={
            "text": prompt,
            "duration_seconds": min(duration, 22.0),  # ElevenLabs max is 22s
            "prompt_influence": 0.3,
        },
        timeout=120,
    )
    r.raise_for_status()
    Path(out_path).write_bytes(r.content)


# ── FFmpeg helpers ─────────────────────────────────────────────────────────────

def _download(url: str, out_path: str) -> None:
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    Path(out_path).write_bytes(r.content)


def _ffmpeg_trim_and_caption(
    input_path: str,
    caption_text: str,
    trim_to: float,
    output_path: str,
    font_path: str | None = None,
) -> None:
    """Trim clip to trim_to seconds and burn in bold caption at lower center."""
    # Wrap long captions at ~30 chars for vertical video
    wrapped = "\n".join(textwrap.wrap(caption_text, width=28))
    # Write to temp file to avoid shell escaping issues
    txt_file = input_path + ".txt"
    Path(txt_file).write_text(wrapped, encoding="utf-8")

    font_args = f":fontfile='{font_path}'" if font_path else ""

    # Bold white text, black semi-transparent box, lower third
    drawtext = (
        f"drawtext=textfile='{txt_file}'"
        f"{font_args}"
        ":fontsize=52"
        ":fontcolor=white"
        ":x=(w-tw)/2"
        ":y=h*0.72"
        ":box=1"
        ":boxcolor=black@0.55"
        ":boxborderw=18"
        ":line_spacing=10"
        ":expansion=none"
    )

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", input_path,
            "-t", str(trim_to),
            "-vf", drawtext,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-an",  # drop original (silent) audio
            output_path,
        ],
        check=True, capture_output=True,
    )


def _find_font() -> str | None:
    """Return path to a bold font available on Render/Linux, or None for default."""
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def _ffmpeg_compile(
    captioned_clip_paths: list[str],
    audio_path: str,
    out_path: str,
    music_path: str | None = None,
) -> None:
    """Concatenate captioned clips, mix voiceover + optional music bed."""
    tmp_dir = Path(out_path).parent

    # Concat silent captioned clips
    concat_file = str(tmp_dir / "concat.txt")
    with open(concat_file, "w") as f:
        for p in captioned_clip_paths:
            f.write(f"file '{p}'\n")

    silent_mp4 = str(tmp_dir / "silent.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
         "-c:v", "copy", silent_mp4],
        check=True, capture_output=True,
    )

    if music_path and Path(music_path).exists():
        # Mix voiceover (full vol) + music bed (-18dB)
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", silent_mp4,
                "-i", audio_path,
                "-i", music_path,
                "-filter_complex",
                "[2:a]volume=0.12,aloop=loop=-1:size=2e+09[music];"
                "[1:a][music]amix=inputs=2:duration=first:dropout_transition=2[audio]",
                "-map", "0:v",
                "-map", "[audio]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                out_path,
            ],
            check=True, capture_output=True,
        )
    else:
        subprocess.run(
            ["ffmpeg", "-y",
             "-i", silent_mp4, "-i", audio_path,
             "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
             out_path],
            check=True, capture_output=True,
        )


# ── Scene splitting ─────────────────────────────────────────────────────────────

def _split_scenes(script: str, num_scenes: int) -> list[dict]:
    words = script.split()
    n = len(words)
    size = max(1, n // num_scenes)
    scenes = []
    for i in range(num_scenes):
        start = i * size
        end = (start + size) if i < num_scenes - 1 else n
        chunk = " ".join(words[start:end])
        motion_style = _MOTION_STYLES[i % len(_MOTION_STYLES)]
        visual = (
            "Cinematic vertical 9:16 background scene, photorealistic, "
            "no visible text, no logos, no watermarks, "
            f"dramatic professional lighting, subject: {chunk[:100]}. "
            "Rich color grading, high production quality, vertical portrait orientation."
        )
        motion = (
            f"{motion_style}, "
            f"scene context: {chunk[:60]}. "
            "High production quality, smooth motion, vertical 9:16 format."
        )
        scenes.append({"narration": chunk, "visual_prompt": visual, "motion_prompt": motion})
    return scenes


# ── Main pipeline ──────────────────────────────────────────────────────────────

def generate_faceless_video(
    script: str,
    duration: int,
    voice_id: str,
    kie_key: str,
    el_key: str,
    job_id: str,
    music_url: str = "",
    music_prompt: str = "",
    progress_callback=None,
) -> str:
    cfg = DURATION_CONFIG.get(duration, DURATION_CONFIG[30])
    num_scenes = cfg["scenes"]
    clip_sec = cfg["clip_seconds"]
    trim_to = cfg["trim_to"]

    job_dir = Path(f"/tmp/faceless_video/{job_id}")
    job_dir.mkdir(parents=True, exist_ok=True)
    font_path = _find_font()

    def _prog(msg: str, pct: int):
        logger.info("[faceless %s] %d%% %s", job_id, pct, msg)
        if progress_callback:
            try:
                progress_callback(msg, pct)
            except Exception:
                pass

    _prog("Splitting script into scenes", 3)
    scenes = _split_scenes(script, num_scenes)

    # Step 1: generate all background images in parallel
    _prog(f"Generating {num_scenes} background images (parallel)", 5)

    def _gen_image(args):
        idx, scene = args
        return idx, _kie_generate_image(kie_key, scene["visual_prompt"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_gen_image, (i, s)): i for i, s in enumerate(scenes)}
        done = 0
        for fut in as_completed(futures):
            idx, img_url = fut.result()
            scenes[idx]["image_url"] = img_url
            done += 1
            _prog(f"Images: {done}/{num_scenes} ready", 5 + done * 30 // num_scenes)

    # Step 2: animate each image → 5s clip (sequential; Kie rate-limits concurrent video)
    raw_clip_paths = []
    for i, scene in enumerate(scenes):
        _prog(f"Animating clip {i+1}/{num_scenes}", 37 + i * 28 // num_scenes)
        vid_url = _kie_animate_image(kie_key, scene["image_url"], scene["motion_prompt"], clip_sec)
        scene["video_url"] = vid_url
        raw_path = str(job_dir / f"raw_{i:02d}.mp4")
        _download(vid_url, raw_path)
        raw_clip_paths.append(raw_path)

    # Step 3: trim each clip to trim_to seconds + burn in caption
    _prog("Burning captions & trimming clips", 67)
    captioned_paths = []
    for i, (raw_path, scene) in enumerate(zip(raw_clip_paths, scenes)):
        cap_path = str(job_dir / f"cap_{i:02d}.mp4")
        _ffmpeg_trim_and_caption(raw_path, scene["narration"], trim_to, cap_path, font_path)
        captioned_paths.append(cap_path)

    # Step 4: voiceover
    _prog("Generating voiceover", 80)
    audio_path = str(job_dir / "voiceover.mp3")
    _elevenlabs_tts(el_key, script, voice_id, audio_path)

    # Step 5: optional music/sound bed
    music_path: str | None = None
    if music_prompt and el_key:
        _prog("Generating background music (ElevenLabs Sound Effects)", 86)
        try:
            music_path = str(job_dir / "music.mp3")
            _elevenlabs_sound_effect(el_key, music_prompt, float(duration), music_path)
        except Exception as exc:
            logger.warning("ElevenLabs sound effect failed, skipping: %s", exc)
            music_path = None
    elif music_url:
        _prog("Downloading music track", 86)
        try:
            music_path = str(job_dir / "music.mp3")
            _download(music_url, music_path)
        except Exception as exc:
            logger.warning("Music download failed, skipping: %s", exc)
            music_path = None

    # Step 6: compile
    _prog("Compiling final video", 90)
    final_path = str(job_dir / "final.mp4")
    _ffmpeg_compile(captioned_paths, audio_path, final_path, music_path)

    (job_dir / "metadata.json").write_text(
        json.dumps({"job_id": job_id, "duration": duration, "trim_to": trim_to, "scenes": scenes}, indent=2)
    )

    _prog("Complete", 100)
    return final_path
