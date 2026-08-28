"""API 级测试（TestClient 会触发 lifespan：建表 + 种子 + recovery）。"""

from starlette.testclient import TestClient

from app.main import create_app


def test_run_endpoint_and_trace():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        assert client.get("/health/ready").json()["status"] == "ready"

        r = client.post("/agents/runs", json={"input": "12 + 30"})
        assert r.status_code == 200
        data = r.json()
        assert data["state"] == "COMPLETED"
        assert "42" in data["answer"]
        assert data["steps"] >= 2
        run_id = data["run_id"]

        trace = client.get(f"/agents/runs/{run_id}").json()
        assert trace["run"]["state"] == "COMPLETED"
        assert len(trace["steps"]) >= 2


def test_async_run_via_queue():
    import time

    app = create_app()
    with TestClient(app) as client:
        r = client.post("/agents/runs", json={"input": "12 + 30", "await_result": False})
        assert r.status_code == 200
        data = r.json()
        assert data["state"] == "QUEUED"  # §9 入队，Worker 异步执行
        run_id = data["run_id"]

        # 轮询直到 Worker 处理完成（最多 ~3s）
        state = None
        deadline = time.time() + 3
        while time.time() < deadline:
            g = client.get(f"/agents/runs/{run_id}")
            if g.status_code == 200:
                state = g.json()["run"]["state"]
                if state == "COMPLETED":
                    break
            time.sleep(0.05)
        assert state == "COMPLETED"

        # 已完成 run 的 cancel 为 no-op
        cancel = client.post(f"/agents/runs/{run_id}/cancel").json()
        assert cancel["cancelled"] is False


def test_run_not_found():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/agents/runs/nope").status_code == 404


def test_tools_list_and_direct_execute():
    app = create_app()
    with TestClient(app) as client:
        tools = client.get("/tools").json()["tools"]
        refs = [t["ref"] for t in tools]
        assert "calc.add" in refs and "http.get" in refs
        assert all(t["risk_level"] for t in tools)

        r = client.post("/tools/calc.add/execute", json={"args": {"a": 2, "b": 5}})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] and body["data"] == 7
        assert body["decision"]  # 决策链（policy_id）可见


def test_tool_permission_denied_via_api():
    app = create_app()
    with TestClient(app) as client:
        # http.get 未在默认租户策略中 => 403（default-deny 生效）
        r = client.post(
            "/tools/http.get/execute",
            json={"args": {"url": "http://example.com/"}},
            headers={"X-Tenant-Id": "tenant-default"},
        )
        assert r.status_code == 403
        assert r.json()["code"] == "TOOL_PERMISSION_DENIED"


def test_compare_replay_with_diff():
    from app.agent.api.runs import _diff_answers

    app = create_app()
    with TestClient(app) as client:
        r = client.post("/agents/runs", json={"input": "12 + 30"})
        orig_id = r.json()["run_id"]
        cmp = client.post(f"/agents/runs/{orig_id}/compare").json()
        # mock 答案含运行时 latency/call_id => 不要求字符串全等；断言语义一致 + diff 结构正确
        assert "42" in (cmp["original_answer"] or "")
        assert "42" in (cmp["replay_answer"] or "")
        assert "same" in cmp["diff"]
        assert cmp["original_run"] == orig_id
        assert cmp["replay_run"] != orig_id
        # 检索参数 diff 展示
        assert cmp["retrieval"]["original_top_k"] is None
        assert cmp["retrieval"]["overridden"] is False

    # §60 换检索：compare 传 top_k 覆盖 => retrieval.overridden True
    with TestClient(app) as client:
        r = client.post("/agents/runs", json={"input": "知识库: 退款"})
        orig_id = r.json()["run_id"]
        cmp = client.post(f"/agents/runs/{orig_id}/compare", json={"top_k": 1}).json()
        assert cmp["retrieval"]["replay_top_k"] == 1
        assert cmp["retrieval"]["overridden"] is True

    # Diff 函数：内容不同时给出 added/removed
    d = _diff_answers("退款 3 个工作日到账", "退款 5 个工作日到账")
    assert d["same"] is False
    assert "3" in d["removed"] and "5" in d["added"]


def test_replay_with_prompt_override():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/agents/runs", json={"input": "hello"})
        orig_id = r.json()["run_id"]
        # 换 system_prompt 重放仍成功
        replay = client.post(
            f"/agents/runs/{orig_id}/replay", json={"system_prompt": "你是一个严格助手。"}
        ).json()
        assert replay["state"] == "COMPLETED"


def test_resume_via_api():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/agents/runs", json={"input": "12 + 30"})
        run_id = r.json()["run_id"]
        # 已完成 run resume 为 no-op
        resume = client.post(f"/agents/runs/{run_id}/resume").json()
        assert resume["state"] == "COMPLETED"
        # 不存在的 run
        assert client.post("/agents/runs/nope/resume").status_code == 404


def test_run_cost_attribution():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/agents/runs", json={"input": "12 + 30"})
        run_id = r.json()["run_id"]
        cost = client.get(f"/agents/runs/{run_id}/cost").json()
        assert cost["run_id"] == run_id
        assert cost["llm_calls"]  # 至少一次 LLM 调用落库
        assert cost["llm_calls"][0]["model"]
        assert cost["llm_calls"][0]["estimated_cost"] >= 0
        assert cost["totals"]["tokens_in"] >= 0
        assert cost["agent_version"] >= 1


def test_cost_overview_and_growth():
    app = create_app()
    with TestClient(app) as client:
        for _ in range(2):
            client.post("/agents/runs", json={"input": "12 + 30"})
        ov = client.get("/cost/overview").json()
        assert ov["rows"]
        row = ov["rows"][0]
        assert row["runs"] >= 2
        assert row["tokens_in"] > 0 and row["cost"] > 0
        g = client.get("/cost/growth").json()
        assert g["rows"]
        assert any(r["current_tokens_per_run"] > 0 for r in g["rows"])


def test_release_metrics_by_status():
    app = create_app()
    with TestClient(app) as client:
        agent_id = client.app.state.agent.seed["agent_id"]
        client.post(f"/agents/{agent_id}/versions/1/publish")
        client.post(f"/agents/{agent_id}/versions/1/gray", json={"percentage": 100})
        client.post("/agents/runs", json={"input": "12 + 30"})
        m = client.get(f"/agents/{agent_id}/release-metrics").json()
        assert m["metrics"]
        # 灰度决策已落 run：GRAY 组有运行量
        assert any(r["release_status"] == "GRAY" and r["runs"] >= 1 for r in m["metrics"])


def test_audit_query_api():
    app = create_app()
    with TestClient(app) as client:
        client.post("/tools/calc.add/execute", json={"args": {"a": 1, "b": 2}})
        r = client.get("/audit").json()
        assert r["rows"]
        r2 = client.get("/audit", params={"action": "tool:execute"}).json()
        assert r2["rows"] and all(x["action"] == "tool:execute" for x in r2["rows"])
        r3 = client.get("/audit", params={"resource": "calc.add"}).json()
        assert any(x["resource"] == "calc.add" for x in r3["rows"])


def test_config_center_versioned():
    app = create_app()
    with TestClient(app) as client:
        v1 = client.post("/config", json={"key": "max_steps", "value": 20}).json()["version"]
        v2 = client.post("/config", json={"key": "max_steps", "value": 30}).json()["version"]
        assert v2 > v1
        cur = client.get("/config", params={"key": "max_steps"}).json()
        assert cur["value"] == 30 and cur["version"] == v2
        old = client.get(f"/config/max_steps/versions/{v1}").json()
        assert old["value"] == 20  # 回滚 = 读旧版本


def test_feature_flag_percentage():
    app = create_app()
    with TestClient(app) as client:
        client.post("/flags", json={"key": "beta", "rules": {"percentage": 100}})
        assert client.get("/flags/beta").json()["enabled"] is True
        client.post("/flags", json={"key": "beta", "rules": {"percentage": 0}})
        assert client.get("/flags/beta").json()["enabled"] is False


def test_bad_case_feedback_into_eval_dataset():
    app = create_app()
    with TestClient(app) as client:
        run_id = client.post("/agents/runs", json={"input": "12 + 30"}).json()["run_id"]
        fb = client.post(
            f"/agents/runs/{run_id}/feedback", json={"feedback": "bad", "reason": "wrong"}
        ).json()
        assert fb["recorded"] is True
        cases = client.get("/evaluations/cases").json()
        assert any(c["run_id"] == run_id for c in cases["rows"])
        good = client.post(f"/agents/runs/{run_id}/feedback", json={"feedback": "good"}).json()
        assert good["recorded"] is False


async def test_payload_recorder_sampling(sessions):
    """§17.3 Trace payload 采样：rate=0 不存、rate=1 全存。"""
    from app.observability.payloads import TracePayloadRecorder

    r0 = TracePayloadRecorder(sessions, rate=0.0)
    await r0.record(trace_id="x", run_id="r-nosample", kind="llm", payload={"a": 1})
    assert await r0.list_for_run("r-nosample") == []

    r1 = TracePayloadRecorder(sessions, rate=1.0)
    await r1.record(
        trace_id="y",
        run_id="r-sample",
        kind="llm",
        payload={"messages": [{"role": "user", "content": "hi"}]},
    )
    rows = await r1.list_for_run("r-sample")
    assert len(rows) == 1 and rows[0]["kind"] == "llm"


def test_trace_payloads_endpoint():
    app = create_app()
    with TestClient(app) as client:
        run_id = client.post("/agents/runs", json={"input": "12 + 30"}).json()["run_id"]
        r = client.get(f"/agents/runs/{run_id}/trace/payloads")
        assert r.status_code == 200
        assert "payloads" in r.json()


def test_ui_run_timeline():
    app = create_app()
    with TestClient(app) as client:
        run_id = client.post("/agents/runs", json={"input": "12 + 30"}).json()["run_id"]
        assert "Run 列表" in client.get("/ui/runs").text
        t = client.get(f"/ui/runs/{run_id}")
        assert t.status_code == 200
        assert run_id in t.text and "Step #1" in t.text


def test_schedule_endpoints():
    app = create_app()
    with TestClient(app) as client:
        run_id = client.post("/agents/runs", json={"input": "12 + 30"}).json()["run_id"]
        s = client.get(f"/agents/runs/{run_id}/schedule").json()
        assert s["run_id"] == run_id and "decisions" in s
        cmp = client.post(f"/agents/runs/{run_id}/schedule/compare").json()
        assert cmp["original_run"] == run_id
        assert "replay_decisions" in cmp and "original_decisions" in cmp


def test_canary_evaluate_endpoint():
    app = create_app()
    with TestClient(app) as client:
        agent_id = client.app.state.agent.seed["agent_id"]
        client.post(f"/agents/{agent_id}/versions/1/publish")
        client.post(f"/agents/{agent_id}/versions/1/gray", json={"percentage": 100})
        r = client.post(f"/agents/{agent_id}/canary/evaluate")
        assert r.status_code == 200
        assert r.json()["action"] == "continue"  # 灰度无运行数据，未达 min_runs


def test_replay_via_api():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/agents/runs", json={"input": "12 + 30"})
        orig_id = r.json()["run_id"]
        assert r.json()["state"] == "COMPLETED"

        replay = client.post(f"/agents/runs/{orig_id}/replay").json()
        assert replay["state"] == "COMPLETED"
        assert replay["run_id"] != orig_id
        assert "42" in (replay["answer"] or "")
        # replay_of 关联到原 run
        detail = client.get(f"/agents/runs/{replay['run_id']}").json()["run"]
        assert detail["replay_of"] == orig_id
        # 不存在的 run
        assert client.post("/agents/runs/nope/replay").status_code == 404


def test_run_trace_redacted():
    app = create_app()
    with TestClient(app) as client:
        # echo 工具会把用户文本原样返回（含敏感串）=> 观测 API 应脱敏
        r = client.post("/agents/runs", json={"input": "hello sk-abcdefghijklmnop123456"})
        assert r.status_code == 200
        trace = client.get(f"/agents/runs/{r.json()['run_id']}").text
        assert "sk-abcdefghijklmnop123456" not in trace
        assert "sk-****" in trace


def test_memory_api_write_recall():
    app = create_app()
    with TestClient(app) as client:
        w = client.post("/memory", json={"content": "用户是 DBA"})
        assert w.status_code == 200 and "memory_id" in w.json()
        r = client.post("/memory/recall", json={"query": "职业"})
        assert r.status_code == 200
        assert any("DBA" in e["content"] for e in r.json()["entries"])


def test_release_api_publish_and_gray():
    app = create_app()
    with TestClient(app) as client:
        state = client.app.state.agent
        agent_id = state.seed["agent_id"]
        p = client.post(f"/agents/{agent_id}/versions/1/publish")
        assert p.status_code == 200 and p.json()["status"] == "ACTIVE"
        g = client.post(f"/agents/{agent_id}/versions/1/gray", json={"percentage": 0})
        assert g.status_code == 200 and g.json()["status"] == "GRAY"


def test_release_create_and_list_version_api():
    """§22 版本只增不改：建 v2 → publish v1 → gray v2 100% → run 落在 v2 灰度。"""
    app = create_app()
    with TestClient(app) as client:
        agent_id = client.app.state.agent.seed["agent_id"]
        c = client.post(
            f"/agents/{agent_id}/versions",
            json={"system_prompt": "v2 prompt", "model": "m2", "config": {"gray_percentage": 100}},
        )
        assert c.status_code == 200 and c.json()["version"] == 2 and c.json()["status"] == "DRAFT"

        versions = client.get(f"/agents/{agent_id}/versions").json()["versions"]
        assert [v["version"] for v in versions] == [2, 1]
        assert versions[0]["system_prompt"] == "v2 prompt"

        client.post(f"/agents/{agent_id}/versions/1/publish")
        client.post(f"/agents/{agent_id}/versions/2/gray", json={"percentage": 100})
        r = client.post("/agents/runs", json={"input": "12 + 30"})
        assert r.status_code == 200
        assert r.json()["agent_version"] == 2  # 灰度命中 v2

        bad = client.post(f"/agents/{agent_id}/versions", json={"system_prompt": ""})
        assert bad.status_code == 422  # system_prompt 必填


def test_contract_check_endpoint():
    """§58 contract-check 返回 10 项报告；seed v1 无 fail（warn 项走人工签核）。"""
    app = create_app()
    with TestClient(app) as client:
        agent_id = client.app.state.agent.seed["agent_id"]
        r = client.post(f"/agents/{agent_id}/versions/1/contract-check")
        assert r.status_code == 200
        body = r.json()
        assert len(body["checks"]) == 10
        assert body["blocked"] is False


def test_publish_gate_blocks_unknown_tool_api():
    """§58 门禁：发布声明未注册工具的版本 => 400；force 可绕过。"""
    app = create_app()
    with TestClient(app) as client:
        agent_id = client.app.state.agent.seed["agent_id"]
        c = client.post(
            f"/agents/{agent_id}/versions",
            json={"system_prompt": "v2", "config": {"tools": ["calc.add", "ghost.tool"]}},
        )
        assert c.status_code == 200
        version = c.json()["version"]  # 共享 DB，版本号不硬编码
        r = client.post(f"/agents/{agent_id}/versions/{version}/publish")
        assert r.status_code == 400
        assert r.json()["code"] == "RELEASE_CONTRACT_FAILED"
        r2 = client.post(f"/agents/{agent_id}/versions/{version}/publish", json={"force": True})
        assert r2.status_code == 200 and r2.json()["status"] == "ACTIVE"


def test_eval_regression_endpoint_and_publish():
    """§20 回归端点 + 发布自动回归：有评测集即自动跑，通过则附报告。"""
    app = create_app()
    with TestClient(app) as client:
        agent_id = client.app.state.agent.seed["agent_id"]
        client.post("/evaluations/bad-cases", json={"query": "12 + 30", "expected": ["42"]})
        version = client.post(f"/agents/{agent_id}/versions", json={"system_prompt": "v2"}).json()["version"]
        r = client.post(f"/agents/{agent_id}/versions/{version}/regression")
        assert r.status_code == 200
        body = r.json()
        assert body["pass_rate"] == 1.0 and body["regressed"] is False
        g = client.get(f"/agents/{agent_id}/versions/{version}/regression")
        assert g.status_code == 200 and g.json()["pass_rate"] == 1.0
        # 不带 evaluate 也自动回归（有 BADCASES）；force 跳过 §58 契约（隔离共享 DB 版本状态）
        p = client.post(f"/agents/{agent_id}/versions/{version}/publish", json={"force": True})
        assert p.status_code == 200 and p.json()["regression"]["pass_rate"] == 1.0


def test_publish_gate_blocks_on_regression_regress():
    """§20 发布自动回归：有评测集且新版本回退 => 自动阻断 400 RELEASE_REGRESSION_FAILED。"""
    from app.agent.model.gateway import MockProvider, ModelResult

    class _Wrong(MockProvider):
        async def complete(self, messages, tools, model, token=None):
            return ModelResult(content="Answer: 99", tokens_in=1, tokens_out=1, cost=0, model=model)

    app = create_app()
    with TestClient(app) as client:
        agent_id = client.app.state.agent.seed["agent_id"]
        client.post("/evaluations/bad-cases", json={"query": "12 + 30", "expected": ["42"]})
        v1 = client.post(f"/agents/{agent_id}/versions", json={"system_prompt": "v1"}).json()["version"]
        client.post(f"/agents/{agent_id}/versions/{v1}/regression")  # v1 回归 pass
        v2 = client.post(f"/agents/{agent_id}/versions", json={"system_prompt": "v2"}).json()["version"]
        client.app.state.agent.gateway.provider = _Wrong()  # v2 答案错误
        reg = client.post(f"/agents/{agent_id}/versions/{v2}/regression").json()
        assert reg["regressed"] is True  # 前置断言：v2 相对 v1 回退
        p = client.post(f"/agents/{agent_id}/versions/{v2}/publish", json={"force": True})
        assert p.status_code == 400
        assert p.json()["code"] == "RELEASE_REGRESSION_FAILED"


def test_health_ha_endpoint():
    """§23 多区域 HA 最小切片：实例身份/就绪/队列排空。"""
    app = create_app()
    with TestClient(app) as client:
        body = client.get("/health/ha").json()
        assert body["ready"] is True
        assert body["role"] == "primary"
        assert body["instance_id"]  # 非空实例身份
        assert "region" in body and "queue_drain_ok" in body


def test_events_and_queue_admin_endpoints():
    """§28.2 事件 Outbox + §9 DLQ 管理端点冒烟。"""
    app = create_app()
    with TestClient(app) as client:
        e1 = client.post(
            "/events/publish",
            json={"event_type": "test.one", "aggregate_id": "a", "dedupe_key": "dup-1", "payload": {"x": 1}},
        )
        assert e1.status_code == 200
        eid = e1.json()["event_id"]
        e2 = client.post(
            "/events/publish", json={"event_type": "test.one", "aggregate_id": "a", "dedupe_key": "dup-1"}
        )
        assert e2.json()["duplicated"] is True and e2.json()["event_id"] == eid
        lst = client.get("/events").json()
        assert any(r["event_type"] == "test.one" for r in lst["rows"])
        replay = client.post("/events/replay/a").json()
        assert replay["total"] >= 1

        jobs = client.get("/queue/jobs").json()
        assert "rows" in jobs and "total" in jobs
        rq = client.post("/queue/jobs/nope/requeue").json()
        assert rq["state"] == "NOT_FOUND"


def test_meta_and_runs_list_endpoints():
    """前端上下文 + JSON run 列表端点。"""
    app = create_app()
    with TestClient(app) as client:
        meta = client.get("/meta").json()
        assert meta["ready"] is True and meta["agent_id"]
        client.post("/agents/runs", json={"input": "12 + 30"})
        runs = client.get("/agents/runs").json()
        assert runs["total"] >= 1 and "runs" in runs
        assert runs["runs"][0]["state"] == "COMPLETED"


def test_approvals_list_endpoint():
    """审批控制台列表端点：{rows, total} 形状（空列表也应 200）。"""
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/approvals")
        assert r.status_code == 200
        body = r.json()
        assert "rows" in body and "total" in body
        assert body["total"] == len(body["rows"])


def test_ha_status_endpoint():
    """多区域 HA 身份切片：region/role/instance/就绪。"""
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/ha/status")
        assert r.status_code == 200
        body = r.json()
        assert body["ready"] is True
        assert body["instance_id"] and body["region"] and body["role"] == "primary"


def test_knowledge_ingest_and_search_via_api():
    app = create_app()
    with TestClient(app) as client:
        text = "# 退货政策\n## 退款到账时间\n退款 3-5 个工作日到账。\n## 退货条件\n30 天内可退货。"
        r = client.post(
            "/knowledge/documents", json={"document_id": "doc-ret", "title": "退货政策", "text": text}
        )
        assert r.status_code == 200
        assert r.json()["chunks"] >= 1
        assert r.json()["status"] == "READY"

        s = client.post("/knowledge/search", json={"query": "退款到账", "rerank_n": 3})
        assert s.status_code == 200
        hits = s.json()["hits"]
        assert hits and hits[0]["document_id"] == "doc-ret"
        assert s.json()["provenance"]

        # 跨租户隔离：别的租户搜不到
        s2 = client.post("/knowledge/search", json={"query": "退款到账"}, headers={"X-Tenant-Id": "nobody"})
        assert s2.status_code == 200
        assert s2.json()["hits"] == []


def test_stream_endpoint_emits_sse_events():
    from starlette.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        r = c.post("/agents/runs/stream", json={"input": "12 + 30"})
        assert r.status_code == 200
        text = r.text
        assert '"type": "tool_call"' in text
        assert '"type": "answer"' in text
        assert '"type": "done"' in text
        assert '"type": "done"' in text and '"state": "COMPLETED"' in text


def test_idempotency_key_dedupes_post():
    """API 级幂等：同 Idempotency-Key 重放返回缓存响应，不重复创建。"""
    from starlette.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        h = {"Idempotency-Key": "req-abc-123"}
        r1 = c.post("/agents/runs", json={"input": "12 + 30"}, headers=h)
        r2 = c.post("/agents/runs", json={"input": "12 + 30"}, headers=h)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["run_id"] == r2.json()["run_id"]
        assert r2.headers.get("Idempotent-Replayed") == "true"
