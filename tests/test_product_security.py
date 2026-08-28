"""Phase 0 安全门禁：生产设置强制 JWT、拒绝默认密钥；SPA fallback 不再吞 API 错误。"""

import asyncio
from pathlib import Path

import pytest
from starlette.requests import Request

from app.settings import Settings

DIST_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "dist" / "index.html"


def test_prod_settings_rejects_default_jwt_secret():
    with pytest.raises(ValueError, match="prod"):
        Settings(environment="prod")


def test_prod_settings_forces_jwt_and_accepts_strong_secret():
    s = Settings(environment="prod", auth_jwt_secret="a-strong-random-secret-please-change")
    assert s.auth_require_jwt is True


def test_dev_settings_allows_dev_secret():
    s = Settings(environment="dev")
    assert s.auth_require_jwt is False


def test_get_subject_rejects_no_token_when_jwt_required():
    from app.common.errors import AgentError
    from app.gateway.deps import get_subject

    agent = type("A", (), {"settings": Settings(auth_require_jwt=True), "oidc": None})()
    app_state = type("S", (), {"agent": agent})()
    app = type("App", (), {"state": app_state})()
    scope = {"type": "http", "method": "GET", "path": "/x", "headers": [], "app": app}
    with pytest.raises(AgentError) as ei:
        asyncio.run(get_subject(Request(scope)))
    assert ei.value.code == "AUTH_REQUIRED"


@pytest.mark.skipif(not DIST_INDEX.exists(), reason="frontend/dist 未构建")
def test_spa_fallback_returns_json_404_for_unknown_path():
    from starlette.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        r = c.get("/definitely-not-a-route")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["code"] == "NOT_FOUND"


@pytest.mark.skipif(not DIST_INDEX.exists(), reason="frontend/dist 未构建")
def test_spa_fallback_serves_index_at_root():
    from starlette.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
