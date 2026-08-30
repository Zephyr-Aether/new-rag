"""子进程沙箱（§23.4 最小版）：隔离执行 + 超时强杀 + 资源限额 + 命令执行禁用。"""

import pytest

from app.common.errors import ToolExecutionFailedError
from app.sandbox.subprocess import run_isolated
from app.tool.custom import CustomToolSandbox


async def test_run_isolated_ok():
    res = await run_isolated(fn_spec="math:sqrt", args=[16])
    assert res["ok"] and res["data"] == 4.0


async def test_run_isolated_timeout():
    with pytest.raises(TimeoutError):
        await run_isolated(fn_spec="time:sleep", args=[10], timeout_s=0.2)


async def test_custom_sandbox_runs_normal_code():
    sb = CustomToolSandbox()
    res = await sb.run(code='def run(args):\n    return {"echo": args.get("x")}', args={"x": 1})
    assert res == {"echo": 1}


async def test_custom_sandbox_blocks_command_execution():
    sb = CustomToolSandbox()
    for code in (
        'def run(args):\n    import os\n    return os.system("cat /etc/passwd")',
        'def run(args):\n    import subprocess\n    return subprocess.run(["cat", "/etc/passwd"])',
    ):
        with pytest.raises(ToolExecutionFailedError, match="sandbox"):
            await sb.run(code=code, args={})
