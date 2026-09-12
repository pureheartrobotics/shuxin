from __future__ import annotations

from pathlib import Path

from shuxin.core.plugin import PluginManager


def test_plugin_manager_executes_module_before_register_check(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    plugin_dir = plugin_root / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        "name: demo\nversion: 1.0.0\nhooks:\n  - on_session_start\n",
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(
        "\n".join(
            [
                "def register(ctx):",
                "    ctx.register_hook('on_session_start', lambda **kwargs: 'started')",
            ]
        ),
        encoding="utf-8",
    )

    manager = PluginManager()
    manager.initialize(str(tmp_path / "home"))
    manager._plugin_dirs = [plugin_root]

    manager.discover_and_load(enabled_plugins=["demo"])

    assert manager.invoke_hook("on_session_start") == [("demo", "started")]
