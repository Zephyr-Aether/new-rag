"""自定义沙箱代码工具（页面录入 Python 代码，子进程隔离执行）。

用户写 `def run(args) -> JSON 可序列化` 的函数体，服务端在子进程沙箱内执行：
- 超时强杀 + 内存/CPU rlimit；
- 禁网络（monkeypatch socket）+ 文件访问限制到 scratch 目录；
- `-I -S` 隔离模式、独立临时工作目录、输出 JSON 化。
诚实标注：MVP 沙箱非真正容器隔离，生产需更强沙箱宿主。
"""

import asyncio
import json
import sys
import tempfile
import uuid

from sqlalchemy import select

from app.common.errors import ToolExecutionFailedError
from app.storage.models import PolicyRow
from app.tool.registry import ToolDefinition, ToolRegistry

_RUNNER = r"""
import builtins, json, os, resource, socket, sys, subprocess

def _deny(*a, **k):
    raise RuntimeError("network disabled in sandbox")
socket.socket = _deny
socket.create_connection = _deny

# 禁止命令执行 / 子进程（否则可用 os.system / subprocess 读宿主机文件，绕过 open 限制）
def _deny_cmd(*a, **k):
    raise RuntimeError("command execution disabled in sandbox")
os.system = _deny_cmd
os.popen = _deny_cmd
for _f in ("execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
           "posix_spawn", "posix_spawnp", "spawnl", "spawnle", "spawnlp", "spawnlpe",
           "spawnv", "spawnve", "spawnvp", "spawnvpe"):
    if hasattr(os, _f):
        setattr(os, _f, _deny_cmd)
for _f in ("Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"):
    setattr(subprocess, _f, _deny_cmd)
# 绕过 builtins.open 限制的原始 fd 入口
for _f in ("open", "fdopen", "posix_openpt"):
    if hasattr(os, _f):
        setattr(os, _f, _deny_cmd)

# 禁用高风险模块 import（subprocess/ctypes/multiprocessing/importlib 都是绕过点）
_ORIG_IMPORT = builtins.__import__
_BLOCKED = {"subprocess", "ctypes", "multiprocessing", "importlib", "pty"}
def _import(name, *a, **k):
    if name.split(".")[0] in _BLOCKED:
        raise RuntimeError(f"import forbidden in sandbox: {name}")
    return _ORIG_IMPORT(name, *a, **k)
builtins.__import__ = _import

SCRATCH = os.environ.get("SCRATCH", os.getcwd())
_real_open = builtins.open
def _open(path, *a, **k):
    if not os.path.abspath(path).startswith(os.path.abspath(SCRATCH)):
        raise PermissionError("file access restricted to scratch dir")
    return _real_open(path, *a, **k)
builtins.open = _open

try:
    resource.setrlimit(resource.RLIMIT_AS, (MEM_BYTES, MEM_BYTES))
except (ValueError, OSError):
    pass
try:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_S, CPU_S))
except (ValueError, OSError):
    pass

args = json.load(sys.stdin)

USER_CODE

try:
    out = run(args)
    print(json.dumps({"ok": True, "data": out}))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}))
"""


class CustomToolSandbox:
    def __init__(
        self,
        max_memory_mb: int = 256,
        max_output_chars: int = 100_000,
        use_docker: bool = False,
        docker_runtime: str = "",
    ):
        self.max_memory_mb = max_memory_mb
        self.max_output_chars = max_output_chars
        self.use_docker = (
            use_docker  # True=容器隔离（需 docker CLI + python:3.12-slim 镜像）；False=子进程沙箱
        )
        self.docker_runtime = docker_runtime  # ""=默认 runtime；"runsc"=gVisor（需安装 runsc + daemon 注册）

    def validate(self, code: str) -> None:
        compile(code, "<custom-tool>", "exec")

    async def _run_process(self, cmd: list[str], args: dict, timeout_s: float, *, cwd=None, env=None) -> dict:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(json.dumps(args).encode()), timeout=timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"custom tool timed out after {timeout_s}s") from None
        if proc.returncode != 0:
            raise ToolExecutionFailedError(f"custom tool crashed: {err.decode()[:500]}")
        text = out.decode()
        if len(text) > self.max_output_chars:
            text = text[: self.max_output_chars] + "\n…[output truncated]"
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            raise ToolExecutionFailedError(f"custom tool 未返回合法 JSON：{text[:300]}") from None
        if not result.get("ok"):
            raise ToolExecutionFailedError(result.get("error", "custom tool failed"))
        return result["data"]

    async def run(self, *, code: str, args: dict, timeout_s: float = 5.0) -> dict:
        self.validate(code)
        runner = (
            _RUNNER.replace("USER_CODE", code)
            .replace("MEM_BYTES", str(self.max_memory_mb * 1024 * 1024))
            .replace("CPU_S", str(max(1, int(timeout_s))))
        )
        if self.use_docker:
            # 容器隔离：--network none + 内存/CPU 限制；镜像内只需 python -I -S 解释器
            cmd = [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--memory",
                f"{self.max_memory_mb}m",
                "--cpus",
                "1",
            ]
            if self.docker_runtime:
                cmd += ["--runtime", self.docker_runtime]  # gVisor：runsc
            cmd += ["-i", "python:3.12-slim", "python", "-I", "-S", "-c", runner]
            return await self._run_process(cmd, args, timeout_s)
        with tempfile.TemporaryDirectory(prefix="custom-tool-") as scratch:
            return await self._run_process(
                [sys.executable, "-I", "-S", "-c", runner],
                args,
                timeout_s,
                cwd=scratch,
                env={"SCRATCH": scratch},
            )


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class CustomToolManager:
    """配置中心里的自定义工具定义 ↔ 注册表 热同步；注册后给默认租户加 ALLOW 策略。"""

    def __init__(
        self,
        registry: ToolRegistry,
        sessions,
        seed_tenant: str,
        sandbox: CustomToolSandbox | None = None,
    ):
        self.registry = registry
        self.sessions = sessions
        self.seed_tenant = seed_tenant
        self.sandbox = sandbox or CustomToolSandbox()
        self.registered: dict[str, str] = {}  # ref -> code（用于检测变更）

    async def reconcile(self, defs: list[dict]) -> dict:
        results: dict[str, str] = {}
        current = {d.get("ref") for d in defs if d.get("ref")}
        for ref in list(self.registered):
            if ref not in current:
                await self.unregister(ref)
                results[ref] = "removed"
        for d in defs:
            ref = d.get("ref")
            if not ref:
                continue
            code = d.get("code") or ""
            if ref in self.registered and self.registered[ref] == code:
                results[ref] = "unchanged"
                continue
            if ref in self.registered:
                await self.unregister(ref)
            try:
                await self.register(d)
                results[ref] = "registered"
            except Exception as exc:  # noqa: BLE001 单个失败不阻断其它
                results[ref] = f"failed: {exc}"
        return results

    async def register(self, d: dict) -> None:
        ref = d["ref"]
        code = d["code"]
        self.sandbox.validate(code)
        timeout_s = float(d.get("timeout_s") or 5)
        tool = ToolDefinition(
            ref=ref,
            description=d.get("description") or "",
            input_schema=d.get("input_schema") or {"type": "object", "properties": {}},
            fn=self._make_fn(code, timeout_s),
            permission=f"custom:{ref}",
            risk_level=d.get("risk_level") or "LOW_RISK_WRITE",
            timeout_s=timeout_s,
        )
        self.registry.register(tool)
        self.registered[ref] = code
        await self._ensure_allow_policy(ref)

    async def unregister(self, ref: str) -> None:
        self.registered.pop(ref, None)
        try:
            self.registry.unregister(ref)
        except Exception:  # noqa: BLE001
            pass

    def _make_fn(self, code: str, timeout_s: float):
        sandbox = self.sandbox

        async def _fn(**args):
            return await sandbox.run(code=code, args=args, timeout_s=timeout_s)

        return _fn

    async def _ensure_allow_policy(self, ref: str) -> None:
        """给默认租户加 ALLOW：`tool:execute -> {ref}`（default-deny 下才能执行）。"""
        async with self.sessions() as s:
            existing = await s.scalar(
                select(PolicyRow)
                .where(
                    PolicyRow.tenant_id == self.seed_tenant,
                    PolicyRow.effect == "ALLOW",
                    PolicyRow.action == "tool:execute",
                    PolicyRow.resource == ref,
                )
                .limit(1)
            )
            if existing is not None:
                return
            s.add(
                PolicyRow(
                    id=_uid("pol"),
                    tenant_id=self.seed_tenant,
                    name=f"custom-allow-{ref}",
                    effect="ALLOW",
                    action="tool:execute",
                    resource=ref,
                )
            )
            await s.commit()

    def list(self, defs: list[dict]) -> dict:
        """返回完整定义（含 code/input_schema，供页面编辑回填）+ 注册状态。"""
        return {
            "tools": [
                {
                    "ref": d.get("ref", ""),
                    "description": d.get("description") or "",
                    "input_schema": d.get("input_schema") or {"type": "object", "properties": {}},
                    "code": d.get("code", ""),
                    "timeout_s": d.get("timeout_s") or 5,
                    "risk_level": d.get("risk_level") or "LOW_RISK_WRITE",
                    "registered": d.get("ref") in self.registered,
                }
                for d in defs
            ]
        }
