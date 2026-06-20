from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_assets_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_device_prompt_assets.py"
    spec = importlib.util.spec_from_file_location("generate_device_prompt_assets", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merge_manifest_entries_keeps_untouched_keys_in_string_order() -> None:
    module = _load_assets_module()
    strings = {
        "WARNING": "警告",
        "FACTORY_VERIFY_SUCCESS": "验证成功",
        "FACTORY_VERIFY_FAILED": "验证失败",
    }
    existing_manifest = {
        "entries": [
            {"key": "WARNING", "text": "警告", "files": {"ogg": "WARNING.ogg"}},
            {
                "key": "FACTORY_VERIFY_SUCCESS",
                "text": "旧文案",
                "files": {"ogg": "old.ogg"},
            },
        ],
    }
    new_manifest = {
        "profile": "flash",
        "entries": [
            {
                "key": "FACTORY_VERIFY_SUCCESS",
                "text": "验证成功",
                "files": {"ogg": "FACTORY_VERIFY_SUCCESS.ogg"},
            },
            {
                "key": "FACTORY_VERIFY_FAILED",
                "text": "验证失败",
                "files": {"ogg": "FACTORY_VERIFY_FAILED.ogg"},
            },
        ],
    }

    merged = module._merge_manifest_entries(new_manifest, existing_manifest, strings)

    assert [entry["key"] for entry in merged["entries"]] == [
        "WARNING",
        "FACTORY_VERIFY_SUCCESS",
        "FACTORY_VERIFY_FAILED",
    ]
    assert merged["entries"][0]["files"]["ogg"] == "WARNING.ogg"
    assert merged["entries"][1]["text"] == "验证成功"
