"""审批控制台 UI（§19）：渲染 + GET /ui/approvals。"""

from starlette.testclient import TestClient

from app.main import create_app
from app.ui.router import _render_approvals


def test_render_contains_approve_reject_forms():
    html = _render_approvals(
        [{"approval_id": "abc123", "tool_ref": "pay", "risk_level": "CRITICAL", "requester_id": "u"}]
    )
    assert "abc123" in html
    assert "批准" in html and "拒绝" in html
    assert "/approvals/abc123/approve" in html
    assert "/approvals/abc123/reject" in html


def test_approval_console_endpoint():
    with TestClient(create_app()) as c:
        r = c.get("/ui/approvals")
        assert r.status_code == 200
        assert "审批控制台" in r.text
