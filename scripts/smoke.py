"""离线烟测：SQLite + mock provider 跑通 对话→工具调用→收敛→Trace。

用法：make smoke  （无需 Docker / 无需 LLM key）
"""

import os
import tempfile

os.environ.setdefault("APP_DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/smoke.db")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")

from starlette.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


def main() -> None:
    app = create_app()
    with TestClient(app) as client:
        print("[1] health/ready:", client.get("/health/ready").json())
        r = client.post("/agents/runs", json={"input": "12 + 30"})
        data = r.json()
        print(
            "[2] run:", {k: data[k] for k in ("run_id", "state", "steps", "tokens_in", "tokens_out", "cost")}
        )
        print("    answer:", data["answer"])
        trace = client.get(f"/agents/runs/{data['run_id']}").json()
        print(f"[3] trace steps: {len(trace['steps'])}")
        for step in trace["steps"]:
            tools = [o["tool_ref"] for o in step["tool_calls"]]
            print(
                f"    step#{step['seq']} state={step['state']} decision={step['decision']} "
                f"tokens={step['tokens_used']} tools={tools}"
            )
        print("[4] done: 端到端对话 + 工具调用 + 持久化 + Trace 可用")


if __name__ == "__main__":
    main()
