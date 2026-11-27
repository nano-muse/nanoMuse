"""Translate the relay's media contracts to Baidu Qianfan's native endpoints."""

from __future__ import annotations

import math
import re
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import QIANFAN_IMAGE, QIANFAN_VIDEO
from .service import CloudError

VIDEO_INPUT_HELP = (
    "This video model needs a portrait, a storyboard image (short side at least 720 pixels), "
    "and 10 to 60 seconds of WAV reference speech that you have permission to use. "
    "Add your materials at /app/?video=wizshot."
)
VIDEO_STATES = {"pending": "PENDING", "processing": "RUNNING", "succeeded": "SUCCEEDED", "failed": "FAILED"}
MAX_IMAGE_BYTES = 32 * 1024 * 1024


def _result_url(value: object, bucket: str) -> str:
    # Some BOS signed URLs arrive as http; the signature also works over TLS.
    try:
        parts = urlsplit(value if isinstance(value, str) else "")
        if (
            parts.scheme in {"http", "https"}
            and re.fullmatch(re.escape(bucket) + r"\.[a-z0-9-]+\.bcebos\.com", parts.hostname or "")
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
        ):
            return urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))
    except ValueError:
        pass
    raise CloudError(502, "upstream", "The media provider sent an unexpected result URL")


def _material_url(value: object) -> str:
    try:
        if isinstance(value, str):
            url = urlsplit(value)
            if url.scheme == "https" and url.hostname and url.username is None and url.password is None:
                return value
    except ValueError:
        pass
    raise CloudError(400, "wizshot_materials_required", VIDEO_INPUT_HELP, {"open": "/app/?video=wizshot"})


def _upstream_data(r: httpx.Response, *, task_query: bool = False) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = None
    if r.status_code == 429:
        raise CloudError(429, "provider_busy", "The media provider is busy; try again later")
    if r.status_code in (400, 403, 422):
        info = data.get("error", data) if isinstance(data, dict) else {}
        code = info.get("code") if isinstance(info, dict) else None
        if isinstance(code, str) and ("unsafe" in code.lower() or "content_filter" in code.lower()):
            raise CloudError(400, "content_rejected", "The media provider declined this content")
        if r.status_code != 403:
            # Upstream error messages can echo input text and signed URLs.
            extra = {"provider_code": code} if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code) else {}
            raise CloudError(400, "invalid_media_input", "The media provider could not use these materials or parameters", extra)
    if not r.is_success or not isinstance(data, dict) or (data.get("error") and not (task_query and data.get("status") == "failed")):
        raise CloudError(502, "upstream", "The media provider did not return a usable response")
    return data


async def image(http: httpx.AsyncClient, base: str, headers: dict, prompt: str, size: str) -> bytes:
    payload = {"model": QIANFAN_IMAGE, "prompt": prompt, "size": size.replace("*", "x"), "prompt_extend": False, "response_format": "url"}
    try:
        data = _upstream_data(await http.post(base + "/musesteamer/images/generations", headers=headers, json=payload))
        try:
            url = _result_url(data["data"][0]["url"], "qianfan-modelbuilder-img-gen")
        except (KeyError, TypeError, IndexError) as e:
            raise CloudError(502, "upstream", "The image provider sent no picture") from e
        # Only the API call carries the key. Signed result URLs authorize their own read.
        async with http.stream("GET", url, follow_redirects=False) as r:
            if not r.is_success:
                raise CloudError(502, "upstream", "Could not download the generated picture")
            result = bytearray()
            async for chunk in r.aiter_bytes():
                if len(result) + len(chunk) > MAX_IMAGE_BYTES:
                    raise CloudError(502, "upstream", "The generated picture is too large")
                result.extend(chunk)
    except httpx.HTTPError as e:
        raise CloudError(502, "upstream", "The image provider did not answer") from e
    if not (result.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or (result.startswith(b"RIFF") and result[8:12] == b"WEBP")):
        raise CloudError(502, "upstream", "The image provider sent an unreadable picture")
    return bytes(result)


def video_payload(body: dict) -> tuple[dict, float]:
    """Validate the source material before reserving an allowance or submitting a task."""
    inp = body.get("input", body)
    if not isinstance(inp, dict):
        raise CloudError(400, "bad_request", "Video input must be an object")
    if "personas" in inp or "fragments" in inp:
        payload = {k: inp.get(k) for k in ("scene_type", "personas", "fragments")}
    else:
        avatar = _material_url(inp.get("avatar_url"))
        shot = _material_url(inp.get("shot_image", avatar))
        audio = _material_url(inp.get("reference_audio_url"))
        performance = inp.get("prompt")
        dialog = inp.get("dialog", "")
        if not isinstance(performance, str) or not performance.strip() or not isinstance(dialog, str):
            raise CloudError(400, "bad_request", "A performance prompt and optional dialogue text are required")
        elements = {"dialog": dialog, "performance": performance, "emotion": "自然"}
        if not dialog:
            elements["silence_duration"] = inp.get("duration", 4)
        elif "duration" in inp:
            raise CloudError(400, "bad_request", "For spoken dialogue, omit duration")
        speaker = "Speaker"
        payload = {
            "scene_type": "podcast",
            "personas": {speaker: {"name": speaker, "identity": "Speaker", "temperament": "自然", "avatar_url": avatar, "mid": audio}},
            "fragments": [
                {
                    "shots": [
                        {
                            "camera_settings": {"camera_movement": "固定机位", "shot_image": shot},
                            "characters": [speaker],
                            "segments": [{"character_speaker": speaker, "production_elements": elements}],
                        }
                    ],
                }
            ],
        }
    personas, fragments = payload["personas"], payload["fragments"]
    if not isinstance(personas, dict) or not personas or not isinstance(fragments, list) or len(fragments) != 1:
        raise CloudError(400, "wizshot_materials_required", VIDEO_INPUT_HELP, {"open": "/app/?video=wizshot"})
    for person in personas.values():
        if not isinstance(person, dict):
            raise CloudError(400, "bad_request", "Each persona must be an object")
        _material_url(person.get("avatar_url"))
        _material_url(person.get("mid"))
    shots = fragments[0].get("shots") if isinstance(fragments[0], dict) else None
    if not isinstance(shots, list) or not shots:
        raise CloudError(400, "bad_request", "Include the storyboard shots")
    silence = 0.0
    spoken = False
    for shot in shots:
        camera = shot.get("camera_settings") if isinstance(shot, dict) else None
        _material_url(camera.get("shot_image") if isinstance(camera, dict) else None)
        segments = shot.get("segments")
        if not isinstance(segments, list) or not segments:
            raise CloudError(400, "bad_request", "Each shot needs performance segments")
        for segment in segments:
            el = segment.get("production_elements") if isinstance(segment, dict) else None
            if not isinstance(el, dict) or not isinstance(el.get("dialog"), str):
                raise CloudError(400, "bad_request", "Each segment needs dialogue or silence")
            if el["dialog"]:
                if "silence_duration" in el:
                    raise CloudError(400, "bad_request", "For spoken dialogue, omit silence_duration")
                spoken = True
            else:
                duration = el.get("silence_duration")
                if type(duration) not in (int, float) or not 0 < duration <= 16:
                    raise CloudError(400, "bad_request", "Each silent segment needs a duration of up to 16 seconds")
                silence += duration
    if silence > 16 or (not spoken and silence < 4):
        raise CloudError(400, "bad_request", "Wizshot clips must be 4 to 16 seconds long")
    payload["model"] = QIANFAN_VIDEO
    # Speech duration is measured by the provider. Silent video may have padding.
    return payload, 16.0 if spoken else min(16.0, silence + 1.0)


async def create_video(http: httpx.AsyncClient, base: str, headers: dict, payload: dict) -> str:
    try:
        data = _upstream_data(await http.post(base + "/mm/ernie/ernie-wizshot-me", headers=headers, json=payload))
    except httpx.HTTPError as e:
        raise CloudError(502, "submission_unknown", "The video request may have reached the provider; do not resubmit automatically") from e
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,200}", task_id):
        raise CloudError(502, "submission_unknown", "The video provider did not return a usable task ID")
    return task_id


async def video_status(http: httpx.AsyncClient, base: str, headers: dict, task_id: str) -> tuple[dict, float | None, str]:
    try:
        r = await http.get(base + "/mm/ernie/tasks", headers=headers, params={"task_id": task_id})
    except httpx.HTTPError as e:
        raise CloudError(502, "upstream", "The video provider did not answer the status check") from e
    if r.status_code == 404:
        raise CloudError(404, "no_task", "The video provider no longer has this task")
    data = _upstream_data(r, task_query=True)
    state = data.get("status")
    if data.get("task_id", task_id) != task_id or not isinstance(state, str) or state not in VIDEO_STATES:
        raise CloudError(502, "upstream", "The video provider sent an unknown task status")
    output = {"task_id": task_id, "task_status": VIDEO_STATES[state]}
    duration = None
    resolution = ""
    if state == "succeeded":
        content = data.get("content")
        output["video_url"] = _result_url(content.get("video_url") if isinstance(content, dict) else None, "qianfan-mm-router")
        usage = data.get("usage")
        if isinstance(usage, dict):
            try:
                value = float(usage["duration"])
                if math.isfinite(value) and value > 0:
                    duration = value
            except (KeyError, ValueError, TypeError, OverflowError):
                pass
            resolution = str(usage.get("resolution") or "")
    elif state == "failed":
        output["message"] = "The video provider could not generate this clip"
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", code):
            output["code"] = code
            output["message"] += " (" + code + ")"
    return output, duration, resolution
