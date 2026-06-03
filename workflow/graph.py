"""工作流图构建"""
from langgraph.graph import StateGraph, END

from .state import WorkflowState
from .nodes import (
    node_parse_clauses,
    node_filter_candidates,
    node_judge,
    node_review,
    node_process_result,
    node_split_dataset,
    node_persist,
)
from .conditions import should_retry, should_continue


def should_start_judging(state: dict) -> str:
    """
    判断是否有候选对需要处理

    Returns:
        "judge" - 有候选对，开始判定
        "split" - 无候选对，跳转到数据集划分
    """
    candidate_pairs = state.get("candidate_pairs", [])
    if len(candidate_pairs) == 0:
        return "split"
    return "judge"


def build_workflow() -> StateGraph:
    """
    构建 LangGraph 工作流

    工作流结构：
    parse → filter → judge ↔ review → process_result → split → persist

    条件边：
    - review 后：retry / next
    - process_result 后：judge / split
    """
    workflow = StateGraph(WorkflowState)

    # 1. 添加节点
    workflow.add_node("parse", node_parse_clauses)
    workflow.add_node("filter", node_filter_candidates)
    workflow.add_node("judge", node_judge)
    workflow.add_node("review", node_review)
    workflow.add_node("process_result", node_process_result)
    workflow.add_node("split", node_split_dataset)
    workflow.add_node("persist", node_persist)

    # 2. 添加固定边
    workflow.add_edge("parse", "filter")
    workflow.add_edge("judge", "review")
    workflow.add_edge("split", "persist")
    workflow.add_edge("persist", END)

    # 3. 添加条件边：filter 后判断是否有候选对
    workflow.add_conditional_edges(
        "filter",
        should_start_judging,
        {
            "judge": "judge",
            "split": "split",
        }
    )

    # 4. review 后固定进入 process_result
    # process_result 会根据评审结果决定是重试还是继续下一个
    workflow.add_edge("review", "process_result")

    # 5. 添加条件边：处理结果后决定下一步
    workflow.add_conditional_edges(
        "process_result",
        should_continue,
        {
            "judge": "judge",   # 处理下一个候选对
            "split": "split",   # 进入数据集划分
        }
    )

    # 6. 设置入口
    workflow.set_entry_point("parse")

    return workflow
