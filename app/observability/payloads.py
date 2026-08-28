"""§17.3 Trace payload 采样存储：属性全量、payload 按采样率（默认 10%）。"""

import hashlib
import json
import uuid

from sqlalchemy import select

from app.storage.models import TracePayloadRow


class TracePayloadRecorder:
    def __init__(self, sessions, *, rate: float = 0.1):
        self.sessions = sessions
        self.rate = rate

    def should_sample(self, trace_id: str) -> bool:
        if self.rate >= 1.0:
            return True
        if self.rate <= 0.0:
            return False
        return int(hashlib.md5(trace_id.encode()).hexdigest(), 16) % 100 < self.rate * 100

    async def record(
        self, *, trace_id: str, run_id: str, span_name: str = "", kind: str = "llm", payload
    ) -> None:
        if not self.should_sample(trace_id):
            return
        async with self.sessions() as s:
            s.add(
                TracePayloadRow(
                    id=uuid.uuid4().hex,
                    trace_id=trace_id,
                    run_id=run_id,
                    span_name=span_name,
                    kind=kind,
                    payload_json=json.dumps(payload, ensure_ascii=False, default=str),
                )
            )
            await s.commit()

    async def list_for_run(self, run_id: str) -> list[dict]:
        async with self.sessions() as s:
            rows = await s.scalars(select(TracePayloadRow).where(TracePayloadRow.run_id == run_id))
            return [
                {
                    "id": r.id,
                    "span_name": r.span_name,
                    "kind": r.kind,
                    "payload": json.loads(r.payload_json),
                }
                for r in rows
            ]
