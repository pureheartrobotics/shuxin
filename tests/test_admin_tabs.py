"""Admin inline UI tab wiring — prevent showTab referencing removed DOM ids."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from shuxin.voice.server import _admin_html, create_app

TAB_PANELS = ["devices", "users", "agents", "bindings", "adapters", "billing"]
TAB_BUTTONS = [
    "tabDevices",
    "tabUsers",
    "tabAgents",
    "tabBindings",
    "tabAdapters",
    "tabBilling",
]


def test_admin_html_includes_tab_panels_and_buttons() -> None:
    html = _admin_html(authenticated=False)
    for panel_id in TAB_PANELS:
        assert f'id="{panel_id}"' in html, f"missing panel #{panel_id}"
    for button_id in TAB_BUTTONS:
        assert f'id="{button_id}"' in html, f"missing tab button #{button_id}"


def test_admin_showtab_does_not_reference_removed_payment_plans_tab() -> None:
    html = _admin_html(authenticated=False)
    showtab_block = html.split("function showTab(name)", 1)[1].split("function listUrl", 1)[0]
    assert "paymentPlans" not in showtab_block
    assert "tabPaymentPlans" not in showtab_block
    assert "TAB_PANELS" in showtab_block
    assert "TAB_BUTTON_BY_PANEL" in showtab_block


def test_admin_tab_buttons_call_showtab_for_each_panel() -> None:
    html = _admin_html(authenticated=False)
    for panel in TAB_PANELS:
        assert re.search(
            rf'onclick="showTab\(\'{panel}\'\)"',
            html,
        ), f"missing showTab('{panel}') button"


def test_admin_route_returns_html() -> None:
    app = create_app()
    with TestClient(app) as client:
        res = client.get("/admin")
    assert res.status_code == 200
    assert "function showTab(name)" in res.text
    assert 'id="bindings"' in res.text
