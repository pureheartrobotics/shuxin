"""Purpose 注册表：业务用途 -> 对象 key 模板（可扩展，类 AOP 扩展点）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Literal


Who = Literal["admin", "user"]


@dataclass(frozen=True)
class PurposeSpec:
    name: str
    who: Who
    key_template: str
    max_bytes: int = 5 * 1024 * 1024
    allowed_mime: FrozenSet[str] = field(
        default_factory=lambda: frozenset(
            {"image/jpeg", "image/png", "image/webp", "image/gif"}
        )
    )


_PURPOSES: Dict[str, PurposeSpec] = {
    "mall_product_cover": PurposeSpec(
        name="mall_product_cover",
        who="admin",
        key_template="zzx_xcx/mall/products/{entity_id}/cover.webp",
    ),
    "gacha_mbti": PurposeSpec(
        name="gacha_mbti",
        who="admin",
        key_template="zzx_xcx/gacha/mbti/{entity_id}.png",
    ),
    "system_ui": PurposeSpec(
        name="system_ui",
        who="admin",
        key_template="zzx_xcx/system/ui/{entity_id}",
    ),
    "ugc_avatar": PurposeSpec(
        name="ugc_avatar",
        who="user",
        key_template="zzx_xcx/ugc/{user_id}/avatar.webp",
    ),
    "ugc_feedback": PurposeSpec(
        name="ugc_feedback",
        who="user",
        key_template="zzx_xcx/ugc/{user_id}/feedback/{entity_id}.jpg",
    ),
}


def get_purpose(name: str) -> PurposeSpec:
    key = str(name or "").strip()
    spec = _PURPOSES.get(key)
    if spec is None:
        raise ValueError("unknown purpose: %s" % key)
    return spec


def resolve_key(
    purpose: str,
    *,
    entity_id: str = "",
    user_id: str = "",
) -> str:
    """按 purpose 模板生成对象 key；缺占位符所需字段时抛 ValueError。"""
    spec = get_purpose(purpose)
    entity = str(entity_id or "").strip()
    uid = str(user_id or "").strip()
    if spec.name == "gacha_mbti":
        entity = entity.upper()
    tpl = spec.key_template
    if "{entity_id}" in tpl and not entity:
        raise ValueError("entity_id is required for purpose %s" % spec.name)
    if "{user_id}" in tpl and not uid:
        raise ValueError("user_id is required for purpose %s" % spec.name)
    return tpl.format(entity_id=entity, user_id=uid)


def list_purposes(*, who: Who | None = None) -> list[PurposeSpec]:
    items = list(_PURPOSES.values())
    if who is None:
        return items
    return [p for p in items if p.who == who]
