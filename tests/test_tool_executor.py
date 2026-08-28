import pytest

from app.agent.runtime.runtime import call_id_for
from app.common.contracts import Subject
from app.common.errors import ToolInvalidArgumentError, ToolPermissionDeniedError
from app.tool.registry import default_registry, execute_tool


async def test_calc_add(store):
    tool = default_registry().resolve("calc.add")
    r = await execute_tool(
        tool, {"a": 2, "b": 3}, call_id="c1", subject=Subject(tenant_id="t", user_id="u"), idem=store
    )
    assert r.ok and r.data == 5


async def test_invalid_args_rejected(store):
    tool = default_registry().resolve("calc.add")
    with pytest.raises(ToolInvalidArgumentError):
        await execute_tool(
            tool, {"a": "x", "b": 1}, call_id="c2", subject=Subject(tenant_id="t", user_id="u"), idem=store
        )


async def test_missing_required_rejected(store):
    tool = default_registry().resolve("calc.add")
    with pytest.raises(ToolInvalidArgumentError):
        await execute_tool(
            tool, {"a": 1}, call_id="c2b", subject=Subject(tenant_id="t", user_id="u"), idem=store
        )


async def test_permission_denied(store):
    tool = default_registry().resolve("calc.add")
    with pytest.raises(ToolPermissionDeniedError):
        await execute_tool(
            tool,
            {"a": 1, "b": 2},
            call_id="c3",
            subject=Subject(tenant_id="t", user_id="u"),
            idem=store,
            is_allowed=lambda s, p: False,
        )


async def test_idempotent_replay_returns_cached(store):
    tool = default_registry().resolve("calc.add")
    call_id = call_id_for("run1", "calc.add", '{"a": 1, "b": 2}')
    r1 = await execute_tool(
        tool, {"a": 1, "b": 2}, call_id=call_id, subject=Subject(tenant_id="t", user_id="u"), idem=store
    )
    r2 = await execute_tool(
        tool, {"a": 1, "b": 2}, call_id=call_id, subject=Subject(tenant_id="t", user_id="u"), idem=store
    )
    assert r1.data == r2.data == 3
    cached = await store.get(call_id)
    assert cached is not None and cached.data == 3
