from app.agent.runtime.budget import BudgetGuard, BudgetSpent, ExecutionBudget


def test_steps_limit():
    g = BudgetGuard(ExecutionBudget(max_steps=3))
    assert not g.check(BudgetSpent(steps=2)).exceeded
    assert g.check(BudgetSpent(steps=3)).exceeded


def test_cost_limit():
    g = BudgetGuard(ExecutionBudget(max_cost=1.0))
    assert not g.check(BudgetSpent(cost=0.9)).exceeded
    assert g.check(BudgetSpent(cost=1.0)).exceeded


def test_tokens_limit_counts_both_directions():
    g = BudgetGuard(ExecutionBudget(max_tokens=100))
    assert not g.check(BudgetSpent(tokens_in=60, tokens_out=39)).exceeded
    assert g.check(BudgetSpent(tokens_in=60, tokens_out=40)).exceeded


def test_tool_calls_limit():
    g = BudgetGuard(ExecutionBudget(max_tool_calls=2))
    assert not g.check(BudgetSpent(tool_calls=1)).exceeded
    assert g.check(BudgetSpent(tool_calls=2)).exceeded


def test_runtime_limit():
    g = BudgetGuard(ExecutionBudget(max_runtime_s=10))
    assert g.check(BudgetSpent(elapsed_s=10.5)).exceeded
