"""PurposeRegistry 单元测试。"""

from __future__ import annotations

import pytest

from shuxin.voice.cdn.purposes import get_purpose, resolve_key


def test_mall_cover_key():
    assert resolve_key("mall_product_cover", entity_id="prod_1").startswith(
        "zzx_xcx/mall/products/prod_1/cover"
    )


def test_gacha_mbti_key():
    assert resolve_key("gacha_mbti", entity_id="ENFP") == "zzx_xcx/gacha/mbti/ENFP.png"
    assert resolve_key("gacha_mbti", entity_id="enfp") == "zzx_xcx/gacha/mbti/ENFP.png"


def test_unknown_purpose_raises():
    with pytest.raises(ValueError):
        get_purpose("nope")


def test_missing_entity_id_raises():
    with pytest.raises(ValueError):
        resolve_key("mall_product_cover", entity_id="")


def test_ugc_avatar_requires_user_id():
    with pytest.raises(ValueError):
        resolve_key("ugc_avatar", user_id="")
    assert resolve_key("ugc_avatar", user_id="u1") == "zzx_xcx/ugc/u1/avatar.webp"
