"""Hardware camera stills: look-intent matching and OpenAI-compatible vision caption."""

from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger("shuxin.voice.vision")

LOOK_RE = re.compile(
    r"(摄像头|镜头|你能看见|你能看到|看得见|看得到|看见什么|看到什么|看见吗|看到吗|"
    r"你看看|帮我看|你看这|看看这|看看那|看看前面|看看我|看一看|看一下|^看看$|"
    r"这是什么|那是什么|前面有什么|眼前有什么|拍一张|拍张照)"
)

_MAX_JPEG_BYTES = 400_000


def is_look_intent(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    if re.search(r"天气|气温", compact) and "这是什么" not in compact:
        return False
    return LOOK_RE.search(compact) is not None


def attach_scene(text: str, scene: str) -> str:
    scene = (scene or "").strip()
    if not scene:
        return text
    return f"{text}\n\n[摄像头看到：{scene}]"


def camera_present_note() -> str:
    return (
        "这台车上有 MIPI 摄像头，已经接上。"
        "这一眼的照片还没传到。不要说自己没有眼睛、没有摄像头，或摄像头没接进来。"
    )


def decode_jpeg_base64(raw: str) -> Optional[bytes]:
    text = str(raw or "").strip()
    if not text:
        return None
    if "," in text and text.lower().startswith("data:"):
        text = text.split(",", 1)[1]
    try:
        data = base64.b64decode(text, validate=False)
    except Exception:
        return None
    if len(data) < 32 or len(data) > _MAX_JPEG_BYTES:
        return None
    if data[:2] != b"\xff\xd8":
        return None
    return data


async def caption_jpeg(jpeg: bytes, question: str, llm: Any = None) -> str:
    """Describe a still using the session LLM if it is OpenAI-compatible."""
    api_key, base_url, model = _llm_creds(llm)
    model = os.environ.get("SHUXIN_VISION_MODEL", "").strip() or model
    if not api_key or not model:
        return "拍到画面了，但当前模型不能看图。"
    import httpx

    url = _chat_url(base_url)
    b64 = base64.b64encode(jpeg).decode("ascii")
    payload = {
        "model": model,
        "max_tokens": 180,
        "temperature": 0.2,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "这是陪伴机器人眼前摄像头拍到的一张照片。"
                            "用一两句中文说出你看见的主要内容，不要开场白。"
                            f"用户说：{question or '看看前面'}"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=4.5) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            choice = (response.json().get("choices") or [{}])[0]
            content = ((choice.get("message") or {}).get("content")) or ""
            text = str(content).strip()
            return text or "看见了画面，但说不清细节。"
    except Exception as exc:
        logger.warning("vision caption failed: %s", exc)
        return "拍到画面了，但认图暂时失败。"


def _llm_creds(llm: Any) -> tuple[str, str, str]:
    if llm is None:
        return "", "", ""
    provider = getattr(llm, "provider", llm)
    try:
        provider = llm.provider
    except Exception:
        provider = llm
    return (
        str(getattr(provider, "api_key", "") or ""),
        str(getattr(provider, "base_url", "") or ""),
        str(getattr(provider, "model", "") or ""),
    )


def _chat_url(base_url: str) -> str:
    url = (base_url or "").rstrip("/")
    if not url:
        return "https://api.openai.com/v1/chat/completions"
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/chat/completions"
