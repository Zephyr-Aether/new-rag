"""账单 Provider（§50.1 对账上游）：从真实/静态来源拉账单记录。

BillProvider 协议返回 `[{run_id, step_id, cost, model, tokens_in, tokens_out}]`（与 reconcile 的
run_id:step_id 匹配键一致）。
- StaticBillProvider：显式喂记录（测试/离线）。
- OpenAIUsageBillProvider：调 OpenAI usage API（需 key，网络依赖——脚手架）。
"""

from datetime import datetime
from typing import Protocol

import httpx


class BillProvider(Protocol):
    async def fetch_bill(self, tenant_id: str | None = None, since: datetime | None = None) -> list[dict]: ...


class StaticBillProvider:
    """静态账单：直接喂记录（[{run_id, step_id, cost, ...}]）。"""

    def __init__(self, records: list[dict]):
        self.records = records

    async def fetch_bill(self, tenant_id: str | None = None, since: datetime | None = None) -> list[dict]:
        return self.records


class OpenAIUsageBillProvider:
    """调 OpenAI usage API 拉账单（需 APP_LLM_API_KEY；网络依赖）。

    MVP 脚手架：usage 端点返回按天聚合，映射到 {run_id, step_id, cost} 需对账映射层。
    """

    def __init__(self, *, api_key: str, base_url: str = "https://api.openai.com"):
        self._key = api_key
        self._base = base_url.rstrip("/")

    async def fetch_bill(self, tenant_id: str | None = None, since: datetime | None = None) -> list[dict]:
        headers = {"Authorization": f"Bearer {self._key}"}
        params = {}
        if since:
            params["start_time"] = int(since.timestamp())
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base}/v1/usage?granularity=daily", headers=headers, params=params
            )
            resp.raise_for_status()
            resp.json()
        # 脚手架：usage API 按天聚合；此处返回空（真实映射需对账层 + 逐请求标识）
        return []
