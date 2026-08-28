"""Knowledge Graph（§16）：事实写入 / provenance / 消歧 / 冲突 / 隔离 / graph.query 工具。"""

import json

from starlette.testclient import TestClient

from app.common.contracts import ToolCallRequest
from app.graph.extract import GraphExtractor
from app.graph.service import GraphService
from app.graph.store import GraphStore
from app.main import create_app


async def test_add_fact_and_retrieve(sessions):
    svc = GraphService(GraphStore(sessions))
    await svc.add_fact(
        tenant_id="t",
        subject="Tesla",
        predicate="CEO",
        object="Elon Musk",
        aliases=["特斯拉"],
        source_doc="doc-1",
        source_version="v7",
        confidence=0.92,
    )
    facts = await svc.retrieve(query="Tesla 的 CEO", tenant_id="t", k=5)
    assert any(
        f["subject"] == "Tesla" and f["predicate"] == "CEO" and f["object"] == "Elon Musk" for f in facts
    )
    assert facts[0]["source_doc"] == "doc-1"  # provenance 可回源


async def test_alias_detection(sessions):
    svc = GraphService(GraphStore(sessions))
    await svc.add_fact(
        tenant_id="t", subject="Tesla", predicate="CEO", object="Elon Musk", aliases=["特斯拉"]
    )
    facts = await svc.retrieve(query="特斯拉 CEO 是谁", tenant_id="t", k=5)
    assert any(f["subject"] == "Tesla" for f in facts)


async def test_conflict_supersedes_old(sessions):
    svc = GraphService(GraphStore(sessions))
    await svc.add_fact(tenant_id="t", subject="Tesla", predicate="CEO", object="Elon Musk", confidence=0.9)
    await svc.add_fact(tenant_id="t", subject="Tesla", predicate="CEO", object="New CEO", confidence=0.95)
    facts = await svc.retrieve(query="Tesla", tenant_id="t", k=10)
    objects = [f["object"] for f in facts]
    assert "New CEO" in objects
    assert "Elon Musk" not in objects  # 旧值 SUPERSEDED，但仍保留供审计


async def test_tenant_isolation(sessions):
    svc = GraphService(GraphStore(sessions))
    await svc.add_fact(tenant_id="tA", subject="Tesla", predicate="CEO", object="Secret")
    assert await svc.retrieve(query="Tesla", tenant_id="tB", k=5) == []


async def test_graph_query_tool(tool_runtime, graph_service):
    await graph_service.add_fact(tenant_id="t", subject="Acme", predicate="CEO", object="Alice")
    call = ToolCallRequest(
        call_id="g1",
        tenant_id="t",
        user_id="u",
        tool_ref="graph.query",
        args={"query": "Acme 的 CEO", "k": 5},
    )
    res = await tool_runtime.execute(call)
    assert res.ok
    assert any(f["subject"] == "Acme" and f["object"] == "Alice" for f in res.data)


async def test_entity_merge_across_docs(sessions):
    """§16 实体消歧：跨文档别名合并后，事实统一到规范化实体。"""
    svc = GraphService(GraphStore(sessions))
    await svc.add_fact(tenant_id="t", subject="特斯拉", predicate="CEO", object="张三", source_doc="doc-1")
    await svc.add_fact(tenant_id="t", subject="Tesla", predicate="CTO", object="李四", source_doc="doc-2")
    before = await svc.retrieve(query="特斯拉", tenant_id="t", k=10)
    assert {f["predicate"] for f in before} == {"CEO"}  # 合并前只看到自身事实
    await svc.merge_entity(tenant_id="t", from_name="特斯拉", to_name="Tesla")
    after = await svc.retrieve(query="特斯拉", tenant_id="t", k=10)
    assert {"CEO", "CTO"} <= {f["predicate"] for f in after}  # 两来源事实统一到 Tesla
    assert all(f["subject"] == "Tesla" for f in after)


async def test_extract_rule_fallback():
    ex = GraphExtractor()
    facts = await ex.extract("特斯拉的 CEO 是 Elon Musk。另一段无关内容。")
    assert any(
        f["subject"] == "特斯拉" and f["predicate"] == "CEO" and f["object"] == "Elon Musk" for f in facts
    )
    assert facts[0]["extracted_by"] == "rule"


async def test_extract_llm_path():
    async def fake_llm(text):
        return json.dumps([{"subject": "Acme", "predicate": "CEO", "object": "Alice", "confidence": 0.9}])

    ex = GraphExtractor(llm=fake_llm)
    facts = await ex.extract("some text")
    assert facts[0]["object"] == "Alice"
    assert facts[0]["extracted_by"] == "llm"


def test_extract_facts_api():
    with TestClient(create_app()) as c:
        r = c.post("/graph/extract", json={"document_id": "doc-org", "text": "特斯拉的 CEO 是 Elon Musk。"})
        assert r.status_code == 200
        body = r.json()
        assert body["added"] >= 1
        # 抽取入库后可查询
        q = c.post("/graph/query", json={"query": "特斯拉 CEO"})
        assert any(f["object"] == "Elon Musk" for f in q.json()["facts"])


async def test_add_facts_merged_dedup_and_conflict(sessions):
    """§16 跨文档去重/合并：同 (subject,predicate,object) 去重；不同 object 冲突新值胜出。"""
    svc = GraphService(GraphStore(sessions))
    facts1 = [
        {
            "subject": "Acme",
            "predicate": "CEO",
            "object": "Alice",
            "source_doc": "doc-1",
            "extracted_by": "llm",
        }
    ]
    r1 = await svc.add_facts_merged(tenant_id="t", facts=facts1)
    assert r1 == {"added": 1, "deduped": 0}
    # 同事实从 doc-2 再来 => 去重，不重复建链
    facts2 = [
        {
            "subject": "Acme",
            "predicate": "CEO",
            "object": "Alice",
            "source_doc": "doc-2",
            "extracted_by": "llm",
        }
    ]
    r2 = await svc.add_facts_merged(tenant_id="t", facts=facts2)
    assert r2 == {"added": 0, "deduped": 1}
    # §16 多源保留：去重但来源合并（doc-1 + doc-2）
    existing = await svc.store.find_active_fact(tenant_id="t", subject="Acme", predicate="CEO")
    assert existing and sorted(existing["sources"]) == ["doc-1", "doc-2"]
    # 不同 object（CEO 换届）=> 冲突，新值胜出
    facts3 = [
        {"subject": "Acme", "predicate": "CEO", "object": "Bob", "source_doc": "doc-3", "extracted_by": "llm"}
    ]
    r3 = await svc.add_facts_merged(tenant_id="t", facts=facts3)
    assert r3 == {"added": 1, "deduped": 0}
    facts = await svc.retrieve(query="Acme", tenant_id="t", k=10)
    objects = [f["object"] for f in facts]
    assert "Bob" in objects and "Alice" not in objects


async def test_make_graph_extractor_uses_gateway_llm():
    """§16 接真 LLM：gateway(openai) 抽取，返回 JSON 事实。"""
    import httpx

    from app.agent.model.gateway import ModelGateway, OpenAIProvider
    from app.graph.extract import make_graph_extractor
    from app.settings import Settings

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                [
                                    {
                                        "subject": "Acme",
                                        "predicate": "CEO",
                                        "object": "Alice",
                                        "confidence": 0.9,
                                    }
                                ]
                            ),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    settings = Settings(
        database_url="sqlite+aiosqlite://", llm_provider="openai", llm_base_url="http://fake", llm_api_key="x"
    )
    gw = ModelGateway(settings)
    gw.provider = OpenAIProvider(settings, transport=httpx.MockTransport(handler))
    ex = make_graph_extractor(gw)
    facts = await ex.extract("Acme 的 CEO 是 Alice。")
    assert facts[0]["subject"] == "Acme" and facts[0]["object"] == "Alice"
    assert facts[0]["extracted_by"] == "llm"
