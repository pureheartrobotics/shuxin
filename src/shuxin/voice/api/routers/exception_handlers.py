from __future__ import annotations

import logging
from typing import Any
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("shuxin.voice.api")


async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
    if "SHUXIN_DEVICE_SECRET_ENCRYPTION_KEY" in str(exc):
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"error": str(exc)}, status_code=403)


async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse({"error": str(exc)}, status_code=400)


def register_exception_handlers(app: Any) -> None:
    app.add_exception_handler(PermissionError, permission_error_handler)
    app.add_exception_handler(ValueError, value_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_error_handler)
