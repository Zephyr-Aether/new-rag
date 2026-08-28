"""auth_require_jwt=true 端到端烟测（§16/§27 生产认证）。

用法：make smoke-auth 或 python scripts/smoke_auth.py
在独立进程中设置 APP_AUTH_REQUIRE_JWT=true，验证：
- 无 token -> 401
- 无效 token -> 401
- 有效 token（/auth/token 签发）-> 200
退出码：全部通过=0，否则=1（可作 CI 门禁）。
"""

import os
import tempfile

os.environ["APP_DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/smoke_auth.db"
os.environ["APP_LLM_PROVIDER"] = "mock"
os.environ["APP_AUTH_REQUIRE_JWT"] = "true"

from starlette.testclient import TestClient  # noqa: E402

from app.gateway.passwords import client_sha256  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> int:
    failures = 0
    with TestClient(create_app()) as c:
        # 1) 无 token -> 401
        r = c.post("/tools/echo/execute", json={"args": {"text": "x"}})
        ok = r.status_code == 401
        print(f"[{'PASS' if ok else 'FAIL'}] 无 token -> {r.status_code}（期望 401）")
        failures += not ok

        # 2) 无效 token -> 401
        r = c.post(
            "/tools/echo/execute", json={"args": {"text": "x"}}, headers={"Authorization": "Bearer not-a-jwt"}
        )
        ok = r.status_code == 401
        print(f"[{'PASS' if ok else 'FAIL'}] 无效 token -> {r.status_code}（期望 401）")
        failures += not ok

        # 3) /auth/token 签发后用 Bearer -> 200
        login = c.post(
            "/auth/token",
            json={
                "tenant_id": "tenant-default",
                "user_id": "user-default",
                "password": client_sha256("admin123"),
            },
        )
        ok_login = login.status_code == 200
        print(f"[{'PASS' if ok_login else 'FAIL'}] 种子用户登录 -> {login.status_code}")
        failures += not ok_login
        if not ok_login:
            return 1
        t = login.json()["access_token"]
        r = c.post(
            "/tools/calc.add/execute",
            json={"args": {"a": 1, "b": 2}},
            headers={"Authorization": f"Bearer {t}"},
        )
        ok = r.status_code == 200 and r.json()["data"] == 3
        body = r.json() if r.status_code == 200 else "-"
        print(f"[{'PASS' if ok else 'FAIL'}] 有效 token -> {r.status_code} data={body}")
        failures += not ok

    print("== auth_require_jwt 烟测：" + ("PASS" if failures == 0 else f"{failures} FAILED") + " ==")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
