"""
AI Faceless Video Generator
Pipeline:
  1. Script -> N scenes (simple word-split)
  2. Each scene -> background image (Kie.ai gpt-image-2-text-to-image)
  3. Each image -> 5s animated clip (Kie.ai wan/2-6-flash-video-to-video)
  4. Full script -> voiceover MP3 (ElevenLabs)
  5. Clips + audio -> final MP4 (FFmpeg)
  6. Final MP4 stored in /tmp/faceless_video/<job_id>/ for one-time download
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_KIE_CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
_KIE_RECORD = "https://api.kie.ai/api/v1/jobs/recordInfo"
_KIE_IMAGE_MODEL = "gpt-image-2-text-to-image"
_KIE_VIDEO_MODEL = "wan/2-6-flash-video-to-video"
_EL_BASE = "https://api.elevenlabs.io/v1"

# Preset voices available to operator
VOICES: dict[str, str] = {
    "Rachel – Female, Calm": "21m00Tcm4TlvDq8ikWAM",
    "Adam – Male, Deep": "pNInz6obpgDQGcFmaJgB",
    "Josh – Male, Energetic": "TxGEqnHWrfWFTfGW9XjX",
    "Antoni – Male, Smooth": "ErXwobaYiN019PkySvjV",
    "Bella – Female, Warm": "EXAVITQu4vr4xnSDxMaL",
}

# 30s = 6 clips × 5s, 60s = 12 clips × 5s
DURATION_CONFIG: dict[int, dict] = {
    30: {"scenes": 6, "clip_seconds": 5},
    60: {"scenes": 12, "clip_seconds": 5},
}


# ── Kie.ai helpers ─────────────────────────────────────────────────────────────

def _kie_headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _kie_poll(key: str, task_id: str, timeout: int = 360) -> dict:
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
        # fall back to any non-empty URL
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
        raise RuntimeError(f"Kie image create: code={payload.get('code')} {payload.get('msg')}")
    task_id = payload["data"]["taskId"]
    return _extract_image_url(_kie_poll(kie_key, task_id, timeout=480))


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
        raise RuntimeError(f"Kie video create: code={payload.get('code')} {payload.get('msg')}")
    task_id = payload["data"]["taskId"]
    return _extract_video_url(_kie_poll(kie_key, task_id, timeout=600))


# ── ElevenLabs TTS ─────────────────────────────────────────────────────────────

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


# ── FFmpeg compilation ─────────────────────────────────────────────────────────

def _download(url: str, out_path: str) -> None:
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    Path(out_path).write_bytes(r.content)


def _ffmpeg_compile(clip_paths: list[str], audio_path: str, out_path: str) -> None:
    tmp_dir = Path(out_path).parent
    concat_file = str(tmp_dir / "concat.txt")
    with open(concat_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")

    silent_mp4 = str(tmp_dir / "silent.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
         "-c:v", "libx264", "-preset", "fast", "-crf", "23", silent_mp4],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", silent_mp4, "-i", audio_path,
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", out_path],
        check=True, capture_output=True,
    )


# ── Scene splitting ─────────────────────────────────────────────────────────────

def _split_scenes(script: str, num_scenes: int) -> list[dict]:
    """Even word-split. Each scene gets a narration chunk and a derived visual prompt."""
    words = script.split()
    n = len(words)
    size = max(1, n // num_scenes)
    scenes = []
    for i in range(num_scenes):
        start = i * size
        end = (start + size) if i < num_scenes - 1 else n
        chunk = " ".join(words[start:end])
        visual = (
            f"Cinematic vertical background scene, photorealistic, no visible text or logos, "
            f"no people in foreground, dramatic lighting, related to: {chunk[:120]}. "
            "9:16 vertical portrait format, professional documentary style."
        )
        motion = (
            f"Slow cinematic camera movement, subtle zoom or pan, atmospheric, "
            f"natural lighting changes, related to: {chunk[:60]}."
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
    progress_callback=None,
) -> str:
    """Run the full pipeline. Returns absolute path to final MP4 in /tmp."""
    cfg = DURATION_CONFIG.get(duration, DURATION_CONFIG[30])
    num_scenes = cfg["scenes"]
    clip_sec = cfg["clip_seconds"]

    job_dir = Path(f"/tmp/faceless_video/{job_id}")
    job_dir.mkdir(parents=True, exist_ok=True)

    def _prog(msg: str, pct: int):
        logger.info("[faceless %s] %d%% %s", job_id, pct, msg)
        if progress_callback:
            try:
                progress_callback(msg, pct)
            except Exception:
                pass

    _prog("Splitting script into scenes", 3)
    scenes = _split_scenes(script, num_scenes)

    # Step 1: generate all images in parallel
    _prog(f"Generating {num_scenes} background images (parallel)", 5)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    def _gen_image(args):
        idx, scene = args
        return idx, _kie_generate_image(kie_key, scene["visual_prompt"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_gen_image, (i, scene)): i for i, scene in enumerate(scenes)}
        done_count = 0
        for fut in as_completed(futures):
            idx, img_url = fut.result()
            scenes[idx]["image_url"] = img_url
            done_count += 1
            _prog(f"Images: {done_count}/{num_scenes} done", 5 + done_count * 35 // num_scenes)

    # Step 2: animate each image (sequential — Kie.ai rate limits concurrent video jobs)
    clip_paths = []
    for i, scene in enumerate(scenes):
        _prog(f"Animating clip {i+1}/{num_scenes}", 42 + i * 35 // num_scenes)
        vid_url = _kie_animate_image(kie_key, scene["image_url"], scene["motion_prompt"], clip_sec)
        scene["video_url"] = vid_url
        clip_path = str(job_dir / f"clip_{i:02d}.mp4")
        _download(vid_url, clip_path)
        clip_paths.append(clip_path)

    # Step 3: voiceover
    _prog("Generating voiceover", 80)
    audio_path = str(job_dir / "voiceover.mp3")
    _elevenlabs_tts(el_key, script, voice_id, audio_path)

    # Step 4: compile
    _prog("Compiling final video", 90)
    final_path = str(job_dir / "final.mp4")
    _ffmpeg_compile(clip_paths, audio_path, final_path)

    # Save metadata (Kie URLs) for reconstructability
    (job_dir / "metadata.json").write_text(
        json.dumps({"job_id": job_id, "duration": duration, "scenes": scenes}, indent=2)
    )

    _prog("Complete", 100)
    return final_path
