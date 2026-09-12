from __future__ import annotations

import logging
from typing import Optional, Any
from fastapi import Request

logger = logging.getLogger("shuxin.voice.deps")


def get_repo(request: Request) -> Any:
    """获取数据仓储服务。"""
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise RuntimeError("voice repository is not initialized")
    return repo


def get_billing(request: Request) -> Any:
    """获取计费服务。"""
    billing = getattr(request.app.state, "billing", None)
    if billing is None:
        raise RuntimeError("billing service is not initialized")
    return billing


def require_admin(request: Request) -> None:
    """管理员鉴权门控，若无权限抛出 PermissionError。"""
    admin_token = getattr(request.app.state, "admin_token", "")
    provided = request.headers.get("X-Admin-Token") or request.cookies.get("shuxin_admin")
    if not admin_token:
        raise PermissionError("SHUXIN_ADMIN_TOKEN is required for admin access")
    if provided != admin_token:
        raise PermissionError("invalid admin token")
