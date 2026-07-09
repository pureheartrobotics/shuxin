from __future__ import annotations

from unittest.mock import MagicMock
from fastapi import FastAPI, Depends, Request
from fastapi.testclient import TestClient
from shuxin.voice.api.routers.deps import get_repo, get_billing, require_admin
from shuxin.voice.api.routers.exception_handlers import register_exception_handlers


def test_deps_and_exception_handlers() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    # Setup app state Mock
    mock_repo = MagicMock()
    mock_billing = MagicMock()
    app.state.repo = mock_repo
    app.state.billing = mock_billing
    app.state.admin_token = "admin-secret-token"

    @app.get("/test-repo")
    def route_repo(repo=Depends(get_repo)):
        return {"repo": "ok" if repo is mock_repo else "fail"}

    @app.get("/test-billing")
    def route_billing(billing=Depends(get_billing)):
        return {"billing": "ok" if billing is mock_billing else "fail"}

    @app.get("/test-admin", dependencies=[Depends(require_admin)])
    def route_admin():
        return {"admin": "ok"}

    @app.get("/test-value-error")
    def route_value_error():
        raise ValueError("invalid parameter value")

    @app.get("/test-permission-error")
    def route_permission_error():
        raise PermissionError("not allowed")

    @app.get("/test-generic-error")
    def route_generic_error():
        raise RuntimeError("system crashed")

    client = TestClient(app, raise_server_exceptions=False)

    # 1. Test get_repo dependency
    response = client.get("/test-repo")
    assert response.status_code == 200
    assert response.json() == {"repo": "ok"}

    # 2. Test get_billing dependency
    response = client.get("/test-billing")
    assert response.status_code == 200
    assert response.json() == {"billing": "ok"}

    # 3. Test require_admin without token -> 403
    response = client.get("/test-admin")
    assert response.status_code == 403
    assert "error" in response.json()

    # 4. Test require_admin with invalid token -> 403
    response = client.get("/test-admin", headers={"X-Admin-Token": "wrong-token"})
    assert response.status_code == 403
    assert response.json() == {"error": "invalid admin token"}

    # 5. Test require_admin with valid token -> 200
    response = client.get("/test-admin", headers={"X-Admin-Token": "admin-secret-token"})
    assert response.status_code == 200
    assert response.json() == {"admin": "ok"}

    # 6. Test ValueError exception handler -> 400
    response = client.get("/test-value-error")
    assert response.status_code == 400
    assert response.json() == {"error": "invalid parameter value"}

    # 7. Test PermissionError exception handler -> 403
    response = client.get("/test-permission-error")
    assert response.status_code == 403
    assert response.json() == {"error": "not allowed"}

    # 8. Test generic exception handler -> 400
    response = client.get("/test-generic-error")
    assert response.status_code == 400
    assert response.json() == {"error": "system crashed"}
