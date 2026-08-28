"""ExecutionBudget 执行预算（§3.7，防死循环 + 成本闸）。

每次循环结束快照 spent 并 check；超出任一维度即触发超时/中断。
"""

from dataclasses import dataclass

from pydantic import BaseModel


class ExecutionBudget(BaseModel):
    max_steps: int = 30
    max_tokens: int = 200_000
    max_cost: float = 10.0
    max_tool_calls: int = 50
    max_runtime_s: int = 600
    max_retries: int = 3
    step_timeout_s: float | None = None  # §9.1 分层超时：单步（LLM+工具）上限

    def to_dict(self) -> dict:
        return self.model_dump()


@dataclass
class BudgetSpent:
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    tool_calls: int = 0
    elapsed_s: float = 0.0
    retries: int = 0

    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass
class BudgetCheck:
    exceeded: bool
    reason: str | None = None


class BudgetGuard:
    """按 budget 对 spent 做检查；超限即报告 reason。"""

    def __init__(self, budget: ExecutionBudget):
        self.budget = budget

    def check(self, spent: BudgetSpent) -> BudgetCheck:
        b = self.budget
        if spent.steps >= b.max_steps:
            return BudgetCheck(True, f"max_steps={b.max_steps}")
        if spent.tokens_total() >= b.max_tokens:
            return BudgetCheck(True, f"max_tokens={b.max_tokens}")
        if spent.cost >= b.max_cost:
            return BudgetCheck(True, f"max_cost={b.max_cost}")
        if spent.tool_calls >= b.max_tool_calls:
            return BudgetCheck(True, f"max_tool_calls={b.max_tool_calls}")
        if spent.elapsed_s >= b.max_runtime_s:
            return BudgetCheck(True, f"max_runtime_s={b.max_runtime_s}")
        return BudgetCheck(False)


def default_budget_from_settings(settings) -> ExecutionBudget:
    return ExecutionBudget(
        max_steps=settings.budget_max_steps,
        max_tokens=settings.budget_max_tokens,
        max_cost=settings.budget_max_cost,
        max_tool_calls=settings.budget_max_tool_calls,
        max_runtime_s=settings.budget_max_runtime_s,
        max_retries=settings.budget_max_retries,
        step_timeout_s=getattr(settings, "budget_max_step_s", None),
    )
