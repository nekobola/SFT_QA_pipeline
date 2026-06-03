"""工作流状态测试"""
import pytest
from workflow.state import WorkflowState, init_state


def test_init_state():
    """测试初始化状态"""
    config = {"data": {"output_dir": "output"}}
    state = init_state(config)

    assert state["outer_clauses"] == []
    assert state["inner_clauses"] == []
    assert state["candidate_pairs"] == []
    assert state["qa_pairs"] == []
    assert state["failed_pairs"] == []
    assert state["retry_count"] == 0
    assert state["clauses_loaded"] is False
    assert state["candidate_idx"] == 0
    assert state["config"] == config


def test_state_is_typed_dict():
    """测试状态是 TypedDict"""
    from typing import get_type_hints
    from workflow.state import WorkflowState

    hints = get_type_hints(WorkflowState)
    assert "outer_clauses" in hints
    assert "qa_pairs" in hints
    assert "config" in hints


def test_init_state_with_full_config():
    """测试完整配置初始化"""
    config = {
        "data": {
            "output_dir": "test_output",
            "outer_dir": "data/outer",
            "inner_dir": "data/inner",
        },
        "filter": {
            "similarity_threshold": 0.3,
        },
        "llm": {
            "judgment_model": "qwen-plus",
            "review_model": "qwen-plus",
        },
        "review": {
            "pass_threshold": 70,
            "max_retries": 2,
        },
        "split": {
            "val_clause_ratio": 0.05,
            "random_seed": 42,
        },
    }
    state = init_state(config)

    assert state["config"] == config
    assert state["stats"] == {}
    assert state["train_set"] == []
    assert state["val_set"] == []
    assert state["rework_mode"] is False
    assert state["rework_data"] == []


def test_state_field_types():
    """测试状态字段类型"""
    from typing import get_type_hints, Annotated
    import operator
    from workflow.state import WorkflowState

    hints = get_type_hints(WorkflowState)

    # qa_pairs 和 failed_pairs 应该是 Annotated 类型，使用 operator.add
    qa_pairs_hint = hints.get("qa_pairs")
    failed_pairs_hint = hints.get("failed_pairs")

    # 检查是否为 Annotated 类型
    assert hasattr(qa_pairs_hint, "__origin__") or str(qa_pairs_hint).startswith("typing.Annotated")
    assert hasattr(failed_pairs_hint, "__origin__") or str(failed_pairs_hint).startswith("typing.Annotated")
