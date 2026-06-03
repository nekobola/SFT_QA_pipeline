"""工作流状态定义"""
from typing import TypedDict, Annotated
import operator


class WorkflowState(TypedDict):
    """工作流状态"""

    # ===== 条款数据 =====
    outer_clauses: list[dict]
    inner_clauses: list[dict]
    clauses_loaded: bool

    # ===== 候选配对 =====
    candidate_pairs: list[dict]
    candidate_idx: int

    # ===== LLM 判定 =====
    current_pair: dict
    judgment_result: dict
    review_result: dict
    retry_count: int
    need_retry: bool  # 是否需要重试

    # ===== 结果收集 =====
    qa_pairs: Annotated[list[dict], operator.add]
    failed_pairs: Annotated[list[dict], operator.add]

    # ===== 数据集划分 =====
    train_set: list[dict]
    val_set: list[dict]

    # ===== 统计信息 =====
    stats: dict

    # ===== 返工模式 =====
    rework_mode: bool
    rework_data: list[dict]

    # ===== 配置 =====
    config: dict


def init_state(config: dict) -> WorkflowState:
    """初始化工作流状态"""
    return WorkflowState(
        outer_clauses=[],
        inner_clauses=[],
        clauses_loaded=False,
        candidate_pairs=[],
        candidate_idx=0,
        current_pair={},
        judgment_result={},
        review_result={},
        retry_count=0,
        need_retry=False,
        qa_pairs=[],
        failed_pairs=[],
        train_set=[],
        val_set=[],
        stats={},
        rework_mode=False,
        rework_data=[],
        config=config,
    )
