"""§28.2 事件 Outbox：幂等发布 / 查询 / 重放。"""

from app.events.service import EventOutbox


async def test_event_publish_idempotent_and_list(sessions):
    svc = EventOutbox(sessions)
    r1 = await svc.publish(
        event_type="feedback.bad",
        tenant_id="t",
        aggregate_id="run1",
        payload={"q": "x"},
        dedupe_key="fb:run1",
    )
    r2 = await svc.publish(
        event_type="feedback.bad",
        tenant_id="t",
        aggregate_id="run1",
        payload={"q": "y"},
        dedupe_key="fb:run1",
    )
    assert r1["duplicated"] is False and r2["duplicated"] is True
    assert r1["event_id"] == r2["event_id"]  # 幂等：同 dedupe_key 返回既有事件
    rows = await svc.list_events(tenant_id="t")
    assert len(rows) == 1 and rows[0]["payload"] == {"q": "x"}  # 保留首次 payload
    # 不同类型隔离
    await svc.publish(event_type="run.completed", tenant_id="t", aggregate_id="run1", dedupe_key="rc:run1")
    assert len(await svc.list_events(tenant_id="t", event_type="feedback.bad")) == 1


async def test_event_replay_by_aggregate(sessions):
    svc = EventOutbox(sessions)
    await svc.publish(event_type="run.completed", tenant_id="t", aggregate_id="agg-1", dedupe_key="rc:a1")
    await svc.publish(event_type="feedback.bad", tenant_id="t", aggregate_id="agg-1", dedupe_key="fb:a1")
    await svc.publish(event_type="run.completed", tenant_id="t", aggregate_id="agg-2", dedupe_key="rc:a2")
    rows = await svc.replay(tenant_id="t", aggregate_id="agg-1")
    assert len(rows) == 2  # 可重放：按 aggregate 取回全部事件
    assert {r["event_type"] for r in rows} == {"run.completed", "feedback.bad"}
