"""
AI Faceless Video Generator
Pipeline:
  1. Script -> N scenes (word-split)
  2. Each scene -> 9:16 background image (Kie.ai gpt-image-2-text-to-image)
  3. Each image -> animated clip with Ken Burns motion (FFmpeg zoompan/crop, no API wait)
  4. Each clip -> burned-in caption (FFmpeg drawtext)
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


class CancelledError(Exception):
    """Raised inside the pipeline when the operator cancels the job."""


_KIE_CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
_KIE_RECORD = "https://api.kie.ai/api/v1/jobs/recordInfo"
_KIE_IMAGE_MODEL = "gpt-image-2-text-to-image"
_EL_BASE = "https://api.elevenlabs.io/v1"

VOICES: dict[str, str] = {
    "Rachel – Female, Calm": "21m00Tcm4TlvDq8ikWAM",
    "Adam – Male, Deep": "pNInz6obpgDQGcFmaJgB",
    "Josh – Male, Energetic": "TxGEqnHWrfWFTfGW9XjX",
    "Antoni – Male, Smooth": "ErXwobaYiN019PkySvjV",
    "Bella – Female, Warm": "EXAVITQu4vr4xnSDxMaL",
}

# Each clip is CLIP_DURATION seconds. scenes × CLIP_DURATION ≈ target video duration.
DURATION_CONFIG: dict[int, dict] = {
    30: {"scenes": 9,  "clip_duration": 3.5},
    60: {"scenes": 18, "clip_duration": 3.5},
}

# Ken Burns motion presets — FFmpeg zoompan filter expressions.
# Each entry is (zoom_expr, x_expr, y_expr) for a 1080x1920 (9:16) clip.
# zoompan input is assumed to be 1080x1920; output locked to 1080x1920.
# z goes from 1.0 (full frame) to ~1.06 (slight crop = motion).
_MOTION_PRESETS = [
    # Slow push-in zoom toward center
    ("1.0+0.012*on/25", "(iw-ow)/2", "(ih-oh)/2"),
    # Slow pull-back zoom out
    ("1.06-0.012*on/25", "(iw-ow)/2", "(ih-oh)/2"),
    # Pan right while slightly zoomed
    ("1.05", "min(iw-ow, 0.6*on/25*(iw-ow))", "(ih-oh)/2"),
    # Pan left while slightly zoomed
    ("1.05", "max(0, (iw-ow)-0.6*on/25*(iw-ow))", "(ih-oh)/2"),
    # Pan upward
    ("1.05", "(iw-ow)/2", "min(ih-oh, 0.6*on/25*(ih-oh))"),
    # Pan downward
    ("1.05", "(iw-ow)/2", "max(0, (ih-oh)-0.6*on/25*(ih-oh))"),
    # Zoom-in punch from left side
    ("1.0+0.012*on/25", "0", "(ih-oh)/2"),
    # Zoom-in pull from right side
    ("1.0+0.012*on/25", "iw-ow", "(ih-oh)/2"),
    # Gentle diagonal drift
    ("1.05", "0.4*on/25*(iw-ow)", "0.4*on/25*(ih-oh)"),
]


# ── Kie.ai helpers ─────────────────────────────────────────────────────────────

def _kie_headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _kie_poll(key: str, task_id: str, timeout: int = 480, cancel_check=None) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cancel_check and cancel_check():
            raise CancelledError("Job cancelled during Kie poll")
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


def _kie_generate_image(kie_key: str, prompt: str, cancel_check=None) -> str:
    body = {
        "model": _KIE_IMAGE_MODEL,
        "input": {"prompt": prompt, "aspect_ratio": "9:16", "resolution": "1K"},
    }
    r = httpx.post(_KIE_CREATE, headers=_kie_headers(kie_key), json=body, timeout=30)
    r.raise_for_status()
    payload = r.json()
    if payload.get("code") != 200:
        raise RuntimeError(f"Kie image: code={payload.get('code')} {payload.get('msg')}")
    return _extract_image_url(_kie_poll(kie_key, payload["data"]["taskId"], timeout=480, cancel_check=cancel_check))


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


def _ffmpeg_ken_burns_and_caption(
    image_path: str,
    caption_text: str,
    clip_duration: float,
    output_path: str,
    motion_preset: tuple,
    font_path: str | None = None,
) -> None:
    """
    Animate a still image with a Ken Burns zoompan effect and burn in caption.
    Output: H.264 MP4, 9:16, 30fps, ~clip_duration seconds.
    """
    fps = 30
    num_frames = int(clip_duration * fps)
    w, h = 1080, 1920

    z_expr, x_expr, y_expr = motion_preset

    # zoompan: input image is looped, output is w×h at fps
    zoompan = (
        f"scale={w*2}:{h*2},"   # upscale so zoompan has room to crop
        f"zoompan="
        f"z='{z_expr}':"
        f"x='{x_expr}':"
        f"y='{y_expr}':"
        f"d={num_frames}:"
        f"s={w}x{h}:"
        f"fps={fps}"
    )

    # Wrap caption for vertical video (~28 chars per line)
    wrapped = "\n".join(textwrap.wrap(caption_text, width=28))
    txt_file = image_path + ".cap.txt"
    Path(txt_file).write_text(wrapped, encoding="utf-8")

    font_args = f":fontfile='{font_path}'" if font_path else ""
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

    vf = f"{zoompan},{drawtext}"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-t", str(clip_duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-an",
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
        motion_preset = _MOTION_PRESETS[i % len(_MOTION_PRESETS)]
        visual = (
            "Cinematic vertical 9:16 background scene, photorealistic, "
            "no visible text, no logos, no watermarks, "
            f"dramatic professional lighting, subject: {chunk[:100]}. "
            "Rich color grading, high production quality, vertical portrait orientation."
        )
        scenes.append({
            "narration": chunk,
            "visual_prompt": visual,
            "motion_preset": motion_preset,
        })
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
    cancel_check=None,
) -> str:
    cfg = DURATION_CONFIG.get(duration, DURATION_CONFIG[30])
    num_scenes = cfg["scenes"]
    clip_duration = cfg["clip_duration"]

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

    def _check_cancel():
        if cancel_check and cancel_check():
            raise CancelledError("Job cancelled by operator")

    _prog("Splitting script into scenes", 3)
    scenes = _split_scenes(script, num_scenes)

    # Step 1: generate all background images in parallel
    _prog(f"Generating {num_scenes} background images (parallel, ~5-10 min)", 5)

    def _gen_image(args):
        idx, scene = args
        _check_cancel()
        img_path = str(job_dir / f"img_{idx:02d}.jpg")
        img_url = _kie_generate_image(kie_key, scene["visual_prompt"], cancel_check=cancel_check)
        _download(img_url, img_path)
        return idx, img_path

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_gen_image, (i, s)): i for i, s in enumerate(scenes)}
        done = 0
        for fut in as_completed(futures):
            idx, img_path = fut.result()
            scenes[idx]["image_path"] = img_path
            done += 1
            _prog(f"Images: {done}/{num_scenes} ready", 5 + done * 55 // num_scenes)

    # Step 2: Ken Burns animate each image + burn caption (FFmpeg, no API wait)
    _check_cancel()
    _prog("Animating clips with Ken Burns motion + captions (FFmpeg)", 62)
    captioned_paths = []
    for i, scene in enumerate(scenes):
        _check_cancel()
        cap_path = str(job_dir / f"cap_{i:02d}.mp4")
        _ffmpeg_ken_burns_and_caption(
            scene["image_path"],
            scene["narration"],
            clip_duration,
            cap_path,
            scene["motion_preset"],
            font_path,
        )
        captioned_paths.append(cap_path)
        _prog(f"Clips: {i+1}/{num_scenes} rendered", 62 + (i + 1) * 15 // num_scenes)

    # Step 3: voiceover
    _check_cancel()
    _prog("Generating voiceover (ElevenLabs)", 80)
    audio_path = str(job_dir / "voiceover.mp3")
    _elevenlabs_tts(el_key, script, voice_id, audio_path)

    # Step 4: optional music/sound bed
    music_path: str | None = None
    if music_prompt and el_key:
        _prog("Generating background music (ElevenLabs Sound Effects)", 88)
        try:
            music_path = str(job_dir / "music.mp3")
            _elevenlabs_sound_effect(el_key, music_prompt, float(duration), music_path)
        except Exception as exc:
            logger.warning("ElevenLabs sound effect failed, skipping: %s", exc)
            music_path = None
    elif music_url:
        _prog("Downloading music track", 88)
        try:
            music_path = str(job_dir / "music.mp3")
            _download(music_url, music_path)
        except Exception as exc:
            logger.warning("Music download failed, skipping: %s", exc)
            music_path = None

    # Step 5: compile final video
    _prog("Compiling final video", 92)
    final_path = str(job_dir / "final.mp4")
    _ffmpeg_compile(captioned_paths, audio_path, final_path, music_path)

    (job_dir / "metadata.json").write_text(
        json.dumps({"job_id": job_id, "duration": duration, "clip_duration": clip_duration, "scenes": [
            {k: v for k, v in s.items() if k != "motion_preset"} for s in scenes
        ]}, indent=2)
    )

    _prog("Complete", 100)
    return final_path
