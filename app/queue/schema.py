"""§57 队列消息 schema 演进：向后兼容（新旧 Worker 共存）。

payload 携带 schema_version；消费端 migrate 到当前结构（补默认字段）。
发布期间旧 Worker 产出的旧 payload 仍能被新 Worker 正确处理。
"""

AGENT_RUN_SCHEMA = 1


def migrate_agent_run_payload(payload: dict) -> dict:
    """老版本 agent_run payload -> 当前结构（缺字段补默认，保证 RunInput 可解析）。"""
    p = dict(payload)
    p.setdefault("schema_version", AGENT_RUN_SCHEMA)
    p.setdefault("release_status", "ACTIVE")  # §21 灰度状态（新字段向后兼容）
    p.setdefault("frozen_versions", {})  # §22.1 版本冻结（新字段向后兼容）
    run_input = dict(p.get("run_input") or {})
    run_input.setdefault("model", None)
    run_input.setdefault("retrieval_top_k", None)
    p["run_input"] = run_input
    return p
