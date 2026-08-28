"""账单 provider 适配器（§50.1 对账上游）：拉取真实账单行 `[{run_id, step_id, cost}]`。"""

from typing import Protocol


class BillProvider(Protocol):
    async def fetch_bill(self, *, tenant_id: str | None = None) -> list[dict]: ...


class StaticBillProvider:
    """静态账单（模拟 provider 拉取），供测试/离线；真实实现对接 provider 用量 API。"""

    def __init__(self, records: list[dict]):
        self.records = records

    async def fetch_bill(self, *, tenant_id: str | None = None) -> list[dict]:
        if tenant_id is None:
            return list(self.records)
        return [r for r in self.records if r.get("tenant_id", "") == tenant_id]
