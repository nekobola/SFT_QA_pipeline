"""冲突候选对筛选模块 - 识别可能产生冲突的候选对"""
import json
from pathlib import Path
from collections import defaultdict
from typing import Any


# 行为模态相反映射
OPPOSITE_ACTION_MAP = {
    "应当": ["禁止", "不得", "不得"],
    "禁止": ["应当", "可以", "必须"],
    "不得": ["应当", "可以", "必须"],
    "可以": ["禁止", "不得", "不得"],
    "必须": ["可以", "禁止", "不得"],
}


def build_biz_dim_index(clauses: list[dict]) -> dict[str, list[int]]:
    """构建业务维度倒排索引"""
    index = defaultdict(list)
    for idx, clause in enumerate(clauses):
        for biz in clause.get("biz_dims", []):
            if biz:
                index[biz].append(idx)
    return index


def identify_action_opposite_candidates(
    outer_clauses: list[dict],
    inner_clauses: list[dict],
) -> list[dict]:
    """
    识别行为模态相反的候选对（直接冲突候选）

    当外规要求"应当"而内规规定"禁止"时，可能产生直接冲突
    """
    inner_biz_index = build_biz_dim_index(inner_clauses)

    candidates = []

    for outer_idx, outer in enumerate(outer_clauses):
        outer_action = outer.get("action", "")
        target_actions = OPPOSITE_ACTION_MAP.get(outer_action, [])

        if not target_actions:
            continue

        outer_biz_dims = set(outer.get("biz_dims", []))

        # 找相同业务维度但行为相反的内规
        candidate_inner_indices = set()
        for biz in outer_biz_dims:
            candidate_inner_indices.update(inner_biz_index.get(biz, []))

        for inner_idx in candidate_inner_indices:
            inner = inner_clauses[inner_idx]
            inner_action = inner.get("action", "")

            if inner_action in target_actions:
                # 检查主体是否有重叠
                outer_subjects = set(outer.get("subjects", []))
                inner_subjects = set(inner.get("subjects", []))

                if outer_subjects & inner_subjects:  # 有主体重叠
                    candidates.append({
                        "pair_id": f"{outer.get('uid', '')}_{inner.get('uid', '')}",
                        "outer_clause": outer,
                        "inner_clause": inner,
                        "conflict_type": "action_opposite",
                        "match_details": {
                            "outer_action": outer_action,
                            "inner_action": inner_action,
                            "biz_dim_overlap": list(outer_biz_dims & set(inner.get("biz_dims", []))),
                            "subject_overlap": list(outer_subjects & inner_subjects),
                        },
                    })

    return candidates


def identify_subject_mismatch_candidates(
    outer_clauses: list[dict],
    inner_clauses: list[dict],
) -> list[dict]:
    """
    识别主体错位的候选对（部分冲突候选）

    当外规针对"银行"而内规针对"个人"时，可能产生主体错位
    """
    inner_biz_index = build_biz_dim_index(inner_clauses)

    # 主体层级关系（高层 → 低层）
    subject_hierarchy = {
        "商业银行": ["个人", "客户", "借款人"],
        "金融机构": ["个人", "客户", "借款人"],
        "银行": ["个人", "客户", "借款人"],
    }

    candidates = []

    for outer_idx, outer in enumerate(outer_clauses):
        outer_subjects = set(outer.get("subjects", []))
        outer_biz_dims = set(outer.get("biz_dims", []))

        # 找相同业务维度的内规
        candidate_inner_indices = set()
        for biz in outer_biz_dims:
            candidate_inner_indices.update(inner_biz_index.get(biz, []))

        for inner_idx in candidate_inner_indices:
            inner = inner_clauses[inner_idx]
            inner_subjects = set(inner.get("subjects", []))

            # 检查是否有层级关系
            for high_subject, low_subjects in subject_hierarchy.items():
                if high_subject in outer_subjects:
                    for low in low_subjects:
                        if low in inner_subjects and high not in inner_subjects:
                            candidates.append({
                                "pair_id": f"{outer.get('uid', '')}_{inner.get('uid', '')}",
                                "outer_clause": outer,
                                "inner_clause": inner,
                                "conflict_type": "subject_mismatch",
                                "match_details": {
                                    "outer_subjects": list(outer_subjects),
                                    "inner_subjects": list(inner_subjects),
                                    "hierarchy": f"{high_subject} → {low}",
                                },
                            })

    return candidates


def identify_object_mismatch_candidates(
    outer_clauses: list[dict],
    inner_clauses: list[dict],
) -> list[dict]:
    """
    识别客体不符的候选对（部分冲突候选）

    当外规和内规的客体不完全匹配时，可能产生客体不符
    """
    inner_biz_index = build_biz_dim_index(inner_clauses)

    candidates = []

    for outer_idx, outer in enumerate(outer_clauses):
        outer_biz_dims = set(outer.get("biz_dims", []))
        outer_subjects = set(outer.get("subjects", []))
        outer_objects = set(outer.get("objects", []))

        if not outer_objects:
            continue

        # 找相同业务维度和主体的内规
        candidate_inner_indices = set()
        for biz in outer_biz_dims:
            candidate_inner_indices.update(inner_biz_index.get(biz, []))

        for inner_idx in candidate_inner_indices:
            inner = inner_clauses[inner_idx]
            inner_subjects = set(inner.get("subjects", []))
            inner_objects = set(inner.get("objects", []))

            # 必须有主体匹配
            if not (outer_subjects & inner_subjects):
                continue

            if not inner_objects:
                continue

            # 检查客体重叠
            obj_overlap = outer_objects & inner_objects
            obj_diff = (outer_objects | inner_objects) - obj_overlap

            # 有部分重叠但不完全匹配
            if obj_overlap and obj_diff:
                candidates.append({
                    "pair_id": f"{outer.get('uid', '')}_{inner.get('uid', '')}",
                    "outer_clause": outer,
                    "inner_clause": inner,
                    "conflict_type": "object_mismatch",
                    "match_details": {
                        "outer_objects": list(outer_objects),
                        "inner_objects": list(inner_objects),
                        "overlap": list(obj_overlap),
                        "diff": list(obj_diff),
                    },
                })

    return candidates


def filter_conflict_candidates(
    outer_clauses: list[dict],
    inner_clauses: list[dict],
    conflict_types: list[str] = None,
) -> list[dict]:
    """
    综合筛选冲突候选对

    Args:
        outer_clauses: 外规条款列表
        inner_clauses: 内规条款列表
        conflict_types: 要识别的冲突类型列表

    Returns:
        冲突候选对列表
    """
    if conflict_types is None:
        conflict_types = ["action_opposite", "subject_mismatch", "object_mismatch"]

    all_candidates = []
    seen_pairs = set()

    # 1. 行为模态相反
    if "action_opposite" in conflict_types:
        print("[ConflictFilter] 识别行为模态相反候选...")
        candidates = identify_action_opposite_candidates(outer_clauses, inner_clauses)
        print(f"  找到 {len(candidates)} 条")
        for c in candidates:
            pair_id = c["pair_id"]
            if pair_id not in seen_pairs:
                all_candidates.append(c)
                seen_pairs.add(pair_id)

    # 2. 主体错位
    if "subject_mismatch" in conflict_types:
        print("[ConflictFilter] 识别主体错位候选...")
        candidates = identify_subject_mismatch_candidates(outer_clauses, inner_clauses)
        print(f"  找到 {len(candidates)} 条")
        for c in candidates:
            pair_id = c["pair_id"]
            if pair_id not in seen_pairs:
                all_candidates.append(c)
                seen_pairs.add(pair_id)

    # 3. 客体不符
    if "object_mismatch" in conflict_types:
        print("[ConflictFilter] 识别客体不符候选...")
        candidates = identify_object_mismatch_candidates(outer_clauses, inner_clauses)
        print(f"  找到 {len(candidates)} 条")
        for c in candidates:
            pair_id = c["pair_id"]
            if pair_id not in seen_pairs:
                all_candidates.append(c)
                seen_pairs.add(pair_id)

    print(f"[ConflictFilter] 总计 {len(all_candidates)} 条冲突候选对")

    return all_candidates


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="冲突候选对筛选")
    parser.add_argument("--outer", type=str, default="output/outer_clauses_with_semantics.json",
                        help="外规条款文件")
    parser.add_argument("--inner", type=str, default="output/inner_clauses_with_semantics.json",
                        help="内规条款文件")
    parser.add_argument("--output", type=str, default="output/conflict_candidates.json",
                        help="输出文件")
    args = parser.parse_args()

    # 加载条款
    print(f"[加载] {args.outer}")
    outer_clauses = json.loads(Path(args.outer).read_text(encoding='utf-8'))
    print(f"  外规条款: {len(outer_clauses)} 条")

    print(f"[加载] {args.inner}")
    inner_clauses = json.loads(Path(args.inner).read_text(encoding='utf-8'))
    print(f"  内规条款: {len(inner_clauses)} 条")

    # 筛选冲突候选
    candidates = filter_conflict_candidates(outer_clauses, inner_clauses)

    # 保存结果
    Path(args.output).write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    print(f"\n[保存] {args.output}")
    print(f"  共 {len(candidates)} 条冲突候选对")


if __name__ == "__main__":
    main()
