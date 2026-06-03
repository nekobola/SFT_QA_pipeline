"""相似度计算，复用自图数据库 stage3_5_tag.py"""
from typing import Any


def compute_set_overlap(set_a: list, set_b: list) -> int:
    """计算两个集合的重叠数量"""
    return len(set(set_a) & set(set_b))


def compute_similarity(
    outer_clause: dict,
    inner_clause: dict,
) -> dict[str, Any]:
    """
    计算内外规条款的多维度相似度

    返回：
    {
        "biz_dim_match": int,
        "subject_match": int,
        "object_match": int,
        "action_match": int (0 or 1),
        "text_similarity": float (占位，暂返回 0)
    }
    """
    return {
        "biz_dim_match": compute_set_overlap(
            outer_clause.get("biz_dims", []),
            inner_clause.get("biz_dims", [])
        ),
        "subject_match": compute_set_overlap(
            outer_clause.get("subjects", []),
            inner_clause.get("subjects", [])
        ),
        "object_match": compute_set_overlap(
            outer_clause.get("objects", []),
            inner_clause.get("objects", [])
        ),
        "action_match": 1 if (
            outer_clause.get("action") and
            inner_clause.get("action") and
            outer_clause.get("action") == inner_clause.get("action")
        ) else 0,
        "text_similarity": 0.0,  # 可选：后续添加 embedding 相似度
    }
