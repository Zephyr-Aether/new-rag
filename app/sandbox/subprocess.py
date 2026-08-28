"""子进程隔离（§23.4 最小版）：超时强杀 + 内存/CPU rlimit。

fn_spec = "module:function"；在子进程内导入执行并做资源限额。
诚实标注：无网络隔离（macOS 无 seccomp/network namespace），生产需容器/沙箱宿主。
"""

import asyncio
import json
import sys

_RUNNER = r"""
import json, resource, sys
args = json.loads(sys.argv[1])
try:
    resource.setrlimit(resource.RLIMIT_AS, (args["mem_bytes"], args["mem_bytes"]))
except (ValueError, OSError):
    pass  # macOS 虚拟内存基线较高，内存限额尽力而为
try:
    resource.setrlimit(resource.RLIMIT_CPU, (args["cpu_s"], args["cpu_s"]))
except (ValueError, OSError):
    pass
mod_name, fn_name = args["fn_spec"].split(":")
mod = __import__(mod_name, fromlist=[fn_name])
out = getattr(mod, fn_name)(*args["call_args"])  # call_args 为位置参数列表
print(json.dumps({"ok": True, "data": out}))
"""


async def run_isolated(
    *,
    fn_spec: str,
    args: list,
    timeout_s: float = 5.0,
    max_memory_mb: int = 256,
) -> dict:
    """子进程执行 `fn_spec(*args)`：超时强杀 + 内存/CPU 限额。返回 {ok, data}。"""
    payload = {
        "fn_spec": fn_spec,
        "call_args": args,
        "mem_bytes": max_memory_mb * 1024 * 1024,
        "cpu_s": max(1, int(timeout_s)),
    }
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _RUNNER,
        json.dumps(payload),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"subprocess timed out after {timeout_s}s") from None
    if proc.returncode != 0:
        raise RuntimeError(f"subprocess failed ({proc.returncode}): {err.decode()[:500]}")
    return json.loads(out.decode())
