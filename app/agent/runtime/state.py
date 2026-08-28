"""AgentState 状态机（§3.3）。

实现要点：
- 状态转换只允许走 StateMachine.transition()，带守卫 + 审计 history；
- 业务代码禁止直接改 state 字段；
- 非法转换抛 InvalidStateTransition。
"""

from collections.abc import Callable
from enum import StrEnum

from app.common.errors import InvalidStateTransition


class AgentState(StrEnum):
    REQUESTED = "REQUESTED"
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    OBSERVING = "OBSERVING"
    REFLECTING = "REFLECTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    UNKNOWN = "UNKNOWN"  # §3.4 工具超时结果未知，待 reconcile
    PAUSED = "PAUSED"  # §10.3 用户暂停（非终态，可 resume 续跑）


TERMINAL_STATES = {
    AgentState.COMPLETED,
    AgentState.FAILED,
    AgentState.CANCELLED,
    AgentState.TIMEOUT,
    AgentState.UNKNOWN,
}

# 相邻状态表（对应 §3.3 转换表；终态无出边）
_ALLOWED: dict[AgentState, set[AgentState]] = {
    AgentState.REQUESTED: {AgentState.PLANNING, AgentState.CANCELLED, AgentState.FAILED},
    AgentState.PLANNING: {
        AgentState.RUNNING,
        AgentState.RETRYING,
        AgentState.FAILED,
        AgentState.CANCELLED,
        AgentState.TIMEOUT,
    },
    AgentState.RUNNING: {
        AgentState.WAITING_TOOL,
        AgentState.REFLECTING,
        AgentState.WAITING_APPROVAL,
        AgentState.TIMEOUT,
        AgentState.CANCELLED,
        AgentState.FAILED,
        AgentState.UNKNOWN,
        AgentState.PAUSED,
    },
    AgentState.WAITING_TOOL: {
        AgentState.OBSERVING,
        AgentState.WAITING_APPROVAL,
        AgentState.CANCELLED,
        AgentState.TIMEOUT,
        AgentState.FAILED,
        AgentState.UNKNOWN,
        AgentState.PAUSED,
    },
    AgentState.WAITING_APPROVAL: {
        AgentState.RUNNING,
        AgentState.CANCELLED,
        AgentState.TIMEOUT,
        AgentState.FAILED,
    },
    AgentState.OBSERVING: {
        AgentState.REFLECTING,
        AgentState.FAILED,
        AgentState.CANCELLED,
        AgentState.TIMEOUT,
        AgentState.UNKNOWN,
        AgentState.PAUSED,
    },
    AgentState.REFLECTING: {
        AgentState.RUNNING,
        AgentState.COMPLETED,
        AgentState.CANCELLED,
        AgentState.FAILED,
        AgentState.TIMEOUT,
        AgentState.PAUSED,
    },
    AgentState.RETRYING: {
        AgentState.PLANNING,
        AgentState.RUNNING,
        AgentState.WAITING_TOOL,
        AgentState.FAILED,
        AgentState.CANCELLED,
        AgentState.TIMEOUT,
    },
    AgentState.COMPLETED: set(),
    AgentState.FAILED: set(),
    AgentState.CANCELLED: set(),
    AgentState.TIMEOUT: set(),
    AgentState.UNKNOWN: set(),
    AgentState.PAUSED: {AgentState.RUNNING},
}


class StateMachine:
    """相邻状态机 + 守卫 + 历史审计。"""

    def __init__(self, initial: AgentState = AgentState.REQUESTED):
        self._state = initial
        self._history: list[tuple[AgentState, AgentState, str]] = []

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def history(self) -> list[tuple[AgentState, AgentState, str]]:
        return list(self._history)

    def can(self, target: AgentState) -> bool:
        return target in _ALLOWED[self._state]

    def transition(
        self, target: AgentState, *, guard: Callable[[], bool] | None = None, reason: str = ""
    ) -> AgentState:
        if not self.can(target):
            raise InvalidStateTransition(f"{self._state.value} -> {target.value} not allowed")
        if guard is not None and not guard():
            raise InvalidStateTransition(f"{self._state.value} -> {target.value} guard failed")
        self._history.append((self._state, target, reason))
        self._state = target
        return self._state

    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES
