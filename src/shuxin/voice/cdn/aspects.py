"""横切校验辅助（MIME / 大小等），供上传凭证路由使用。"""

from __future__ import annotations

from shuxin.voice.cdn.purposes import PurposeSpec


def assert_mime_allowed(spec: PurposeSpec, content_type: str) -> None:
    mime = str(content_type or "").split(";")[0].strip().lower()
    if not mime:
        return
    if mime not in spec.allowed_mime:
        raise ValueError(
            "content_type %s not allowed for purpose %s" % (mime, spec.name)
        )


def assert_size_allowed(spec: PurposeSpec, size_bytes: int) -> None:
    if size_bytes is None:
        return
    n = int(size_bytes)
    if n < 0:
        raise ValueError("size_bytes must be >= 0")
    if n > int(spec.max_bytes):
        raise ValueError(
            "file too large for purpose %s (max %s bytes)" % (spec.name, spec.max_bytes)
        )
