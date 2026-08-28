import pytest

from app.agent.runtime.state import AgentState, StateMachine
from app.common.errors import InvalidStateTransition


def test_happy_path_transitions():
    sm = StateMachine()
    assert sm.state == AgentState.REQUESTED
    sm.transition(AgentState.PLANNING)
    sm.transition(AgentState.RUNNING)
    sm.transition(AgentState.WAITING_TOOL)
    sm.transition(AgentState.OBSERVING)
    sm.transition(AgentState.REFLECTING)
    sm.transition(AgentState.COMPLETED)
    assert sm.is_terminal()


def test_invalid_transition_rejected():
    sm = StateMachine()
    with pytest.raises(InvalidStateTransition):
        sm.transition(AgentState.COMPLETED)


def test_guard_failure_rejected():
    sm = StateMachine()
    with pytest.raises(InvalidStateTransition):
        sm.transition(AgentState.PLANNING, guard=lambda: False)


def test_terminal_has_no_out_edges():
    sm = StateMachine(AgentState.FAILED)
    with pytest.raises(InvalidStateTransition):
        sm.transition(AgentState.RUNNING)


def test_cancel_and_timeout_are_terminal():
    for initial in (AgentState.CANCELLED, AgentState.TIMEOUT):
        assert StateMachine(initial).is_terminal()


def test_history_records_reason():
    sm = StateMachine()
    sm.transition(AgentState.PLANNING, reason="acquired lock")
    assert sm.history[-1] == (AgentState.REQUESTED, AgentState.PLANNING, "acquired lock")
