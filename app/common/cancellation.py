"""取消原语（§8 Cancellation Propagation）。

放在 common：Runtime / LLM Gateway / Tool 层共用，避免工具层反向依赖 runtime。
"""

import asyncio

from app.common.errors import RunCancelledError


class CancellationToken:
    """§8 取消令牌：可被 runtime watcher / 下游设置；下游 await wait() 感知取消。"""

    def __init__(self) -> None:
        self._evt = asyncio.Event()

    @property
    def cancelled(self) -> bool:
        return self._evt.is_set()

    def cancel(self) -> None:
        self._evt.set()

    async def wait(self) -> None:
        await self._evt.wait()


async def cancelable_sleep(token: CancellationToken | None, seconds: float, step: float = 0.05) -> None:
    """可中断 sleep：取消即抛 RunCancelledError（在途调用中断，§8.2）。"""
    if token is None:
        await asyncio.sleep(seconds)
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while loop.time() < deadline:
        if token.cancelled:
            raise RunCancelledError("cancelled while in flight")
        await asyncio.sleep(min(step, deadline - loop.time()))
    if token.cancelled:
        raise RunCancelledError("cancelled while in flight")


async def await_cancelable(awaitable, token: CancellationToken | None):
    """运行一个可等待对象；token 触发则取消它（§8.2 在途中断）。"""
    if token is None:
        return await awaitable
    task = asyncio.create_task(awaitable)
    wait_token = asyncio.create_task(token.wait())
    await asyncio.wait({task, wait_token}, return_when=asyncio.FIRST_COMPLETED)
    if token.cancelled:
        task.cancel()
        await asyncio.gather(task, wait_token, return_exceptions=True)
        raise RunCancelledError("cancelled while awaiting downstream")
    wait_token.cancel()
    await asyncio.gather(wait_token, return_exceptions=True)
    return await task
