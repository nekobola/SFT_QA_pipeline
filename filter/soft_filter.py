"""软筛选"""
from typing import Any
from collections import defaultdict
import random
import hashlib
import json


# 模块级倒排索引缓存
_index_cache: dict = {}


def _get_cached_indices(inner_clauses: list[dict]) -> dict:
    """获取或构建缓存的倒排索引（基于 inner_clauses 的前 20 个 uid hash）"""
    sample = tuple(sorted(c.get("uid", "") for c in inner_clauses[:20]))
    h = hashlib.md5(json.dumps(sample, ensure_ascii=False).encode()).hexdigest()

    if h not in _index_cache:
        _index_cache.clear()  # 仅保留当前索引
        _index_cache[h] = {
            "biz_dim": build_inverted_index(inner_clauses, "biz_dims"),
            "subject": build_inverted_index(inner_clauses, "subjects"),
        }
    return _index_cache[h]


def compute_weighted_score(similarity: dict, weights: dict) -> float:
    """
    计算加权综合评分

    Args:
        similarity: 相似度字典
        weights: 各维度权重

    Returns:
        加权综合评分 (0.0 - 1.0)
    """
    total_score = 0.0
    total_weight = 0.0

    for key, weight in weights.items():
        value = similarity.get(key, 0)
        # 直接使用值（匹配数），权重已归一化
        if isinstance(value, int) and key != "text_similarity":
            normalized = min(float(value), 1.0)  # 匹配数归一化：>=1 为 1
        else:
            normalized = float(value)

        total_score += normalized * weight
        total_weight += weight

    return total_score / total_weight if total_weight > 0 else 0.0


def build_inverted_index(clauses: list[dict], field: str) -> dict[str, set]:
    """
    构建倒排索引

    Args:
        clauses: 条款列表
        field: 要索引的字段名 (如 "biz_dims", "subjects")

    Returns:
        倒排索引: {value: set(clause_indices)}
    """
    index = defaultdict(set)
    for idx, clause in enumerate(clauses):
        values = clause.get(field, [])
        if isinstance(values, list):
            for v in values:
                if v:
                    index[v].add(idx)
    return index


# 行为模态相反映射
OPPOSITE_ACTION_MAP = {
    "应当": ["禁止", "不得"],
    "禁止": ["应当", "可以"],
    "不得": ["应当", "可以"],
    "可以": ["禁止", "不得"],
}


def _check_action_opposite(outer_action: str, inner_action: str) -> bool:
    """检查两个行为模态是否相反"""
    if outer_action in OPPOSITE_ACTION_MAP:
        return inner_action in OPPOSITE_ACTION_MAP[outer_action]
    return False


def stratified_filter_candidates(
    outer_clauses: list[dict],
    inner_clauses: list[dict],
    config: dict,
    layer_ratios: dict[str, float] = None,
    random_seed: int = 42,
    total_target: int = None,
) -> list[dict]:
    """
    分层筛选候选配对

    按匹配特征分层采样，以获得更平衡的标签分布

    Args:
        outer_clauses: 外规条款列表
        inner_clauses: 内规条款列表
        config: 筛选配置
        layer_ratios: 各层采样比例
        random_seed: 随机种子

    Returns:
        候选配对列表
    """
    from .similarity import compute_similarity

    if layer_ratios is None:
        # 从配置读取分层比例
        layer_ratios = config.get("layer_ratios", {
            "L1_strong": 0.45,      # 强匹配 → 完全符合/基本一致
            "L2_moderate": 0.25,    # 中等匹配 → 部分冲突
            "L3_weak": 0.15,        # 弱匹配 → 无关
            "L4_opposite": 0.15,    # 反向匹配 → 直接冲突
        })

    random.seed(random_seed)

    # 构建倒排索引（优先使用缓存）
    print("[StratifiedFilter] 构建倒排索引...")
    cached = _get_cached_indices(inner_clauses)
    inner_biz_dim_index = cached["biz_dim"]
    inner_subject_index = cached["subject"]

    # 分层候选池
    layers = {
        "L1_strong": [],      # 强匹配 → 完全符合/基本一致
        "L2_moderate": [],    # 中等匹配 → 部分冲突/基本一致
        "L3_weak": [],        # 弱匹配 → 剔除
        "L4_opposite": [],    # 反向匹配 → 剔除
    }

    processed_pairs = set()

    print("[StratifiedFilter] 分层筛选候选对...")

    for outer_idx, outer in enumerate(outer_clauses):
        outer_biz_dims = set(outer.get("biz_dims", []))
        outer_subjects = set(outer.get("subjects", []))
        outer_objects = set(outer.get("objects", []))
        outer_action = outer.get("action", "")

        # 收集候选内规索引
        candidate_inner_indices = set()
        for biz in outer_biz_dims:
            candidate_inner_indices.update(inner_biz_dim_index.get(biz, set()))
        for subj in outer_subjects:
            candidate_inner_indices.update(inner_subject_index.get(subj, set()))

        for inner_idx in candidate_inner_indices:
            pair_key = (outer_idx, inner_idx)
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            inner = inner_clauses[inner_idx]

            # 计算匹配特征
            inner_biz_dims = set(inner.get("biz_dims", []))
            inner_subjects = set(inner.get("subjects", []))
            inner_objects = set(inner.get("objects", []))
            inner_action = inner.get("action", "")

            biz_match = len(outer_biz_dims & inner_biz_dims)
            subj_match = len(outer_subjects & inner_subjects)
            obj_match = len(outer_objects & inner_objects)
            action_match = 1 if outer_action and inner_action and outer_action == inner_action else 0
            is_opposite = _check_action_opposite(outer_action, inner_action)

            # 硬筛选：biz_dim 和 subject 必须各至少有一个匹配（AND 逻辑）
            # 配合关键词过滤后，AND 可确保候选对质量
            # 如果两者都为空，则放宽到 action 匹配 或 obj 匹配
            if len(outer_biz_dims) == 0 and len(outer_subjects) == 0:
                if not (action_match == 1 or obj_match >= 1):
                    continue
            elif biz_match < 1 or subj_match < 1:
                continue

            # 计算完整相似度（用于排序）
            similarity = {
                "biz_dim_match": biz_match,
                "subject_match": subj_match,
                "object_match": obj_match,
                "action_match": action_match,
                "text_similarity": 0.0,
            }

            weights = config.get("soft_filter", {}).get("score_weights", {})
            score = compute_weighted_score(similarity, weights)

            candidate = {
                "pair_id": f"{outer.get('uid', '')}_{inner.get('uid', '')}",
                "outer_clause": outer,
                "inner_clause": inner,
                "similarity_score": score,
                "confidence_level": "high",
                "match_details": similarity,
            }

                        # 分层归类（放宽条件以产生更多候选对）
            # 排序从最强匹配到最弱匹配

            if is_opposite:
                candidate["layer"] = "L4_opposite"
                layers["L4_opposite"].append(candidate)
            elif obj_match >= 1 and action_match == 1:
                # L1_strong: 客体匹配>=1 + action匹配 (强匹配)
                candidate["layer"] = "L1_strong"
                layers["L1_strong"].append(candidate)
            elif biz_match >= 2 and subj_match >= 1:
                # L1_strong: 业务维度匹配>=2 + 主体匹配>=1 (强匹配)
                candidate["layer"] = "L1_strong"
                layers["L1_strong"].append(candidate)
            elif subj_match >= 2 and biz_match >= 1:
                # L1_strong: 主体匹配>=2 + 业务维度匹配>=1 (强匹配)
                candidate["layer"] = "L1_strong"
                layers["L1_strong"].append(candidate)
            elif subj_match >= 1 and biz_match >= 1 and obj_match >= 1:
                # L1_strong: 三维都有匹配 (强匹配)
                candidate["layer"] = "L1_strong"
                layers["L1_strong"].append(candidate)
            elif obj_match >= 1:
                # L2_moderate: 客体匹配>=1 (中等匹配)
                candidate["layer"] = "L2_moderate"
                layers["L2_moderate"].append(candidate)
            elif subj_match >= 1 and biz_match >= 1:
                # L2_moderate: 主体+业务维度匹配 (中等匹配)
                candidate["layer"] = "L2_moderate"
                layers["L2_moderate"].append(candidate)
            elif subj_match >= 2:
                # L2_moderate: 主体匹配>=2 (中等匹配)
                candidate["layer"] = "L2_moderate"
                layers["L2_moderate"].append(candidate)
            elif biz_match >= 1 or subj_match >= 1:
                # L3_weak: 仅单维度匹配 (弱匹配)
                candidate["layer"] = "L3_weak"
                layers["L3_weak"].append(candidate)
            else:
                candidate["layer"] = "L3_weak"
                layers["L3_weak"].append(candidate)

    # 打印各层统计
    print("[StratifiedFilter] 各层候选数量:")
    for layer_name, candidates in layers.items():
        print(f"  {layer_name}: {len(candidates)}")

    # 按比例从各层采样
    # total_target 由调用方显式传入；未传入时从 config 读取，回退到 10000
    if total_target is None:
        total_target = config.get("target", {}).get("max_candidates_to_process", 10000)
    sampled = []

    for layer_name, ratio in layer_ratios.items():
        layer_candidates = layers[layer_name]
        n_samples = int(total_target * ratio)

        if len(layer_candidates) <= n_samples:
            sampled.extend(layer_candidates)
        else:
            sampled.extend(random.sample(layer_candidates, n_samples))

    print(f"[StratifiedFilter] 总计采样: {len(sampled)}")

    # 不要按相似度排序，保持分层结构
    # 打乱顺序以避免批次偏差
    random.shuffle(sampled)

    return sampled


def filter_candidates(
    outer_clauses: list[dict],
    inner_clauses: list[dict],
    config: dict,
) -> list[dict]:
    """
    筛选候选配对 - 使用倒排索引优化

    Args:
        outer_clauses: 外规条款列表
        inner_clauses: 内规条款列表
        config: 筛选配置

    Returns:
        候选配对列表
    """
    from .similarity import compute_similarity
    from .hard_filter import check_hard_filter

    hard_config = config.get("hard_filter", {})
    soft_config = config.get("soft_filter", {})
    weights = soft_config.get("score_weights", {})
    min_score = soft_config.get("min_score", 0.3)

    # 检查是否启用分层筛选
    use_stratified = config.get("use_stratified", False)

    if use_stratified:
        return stratified_filter_candidates(outer_clauses, inner_clauses, config)

    # 构建内规的倒排索引（优先使用缓存）
    print(f"[Filter] 构建倒排索引...")
    cached = _get_cached_indices(inner_clauses)
    inner_biz_dim_index = cached["biz_dim"]
    inner_subject_index = cached["subject"]

    # 确定使用哪个索引（优先 biz_dim，其次 subject）
    use_biz_dim = "biz_dim_match" in hard_config
    use_subject = "subject_match" in hard_config

    candidates = []
    processed_pairs = set()  # 避免重复

    print(f"[Filter] 使用倒排索引快速匹配...")

    for outer_idx, outer in enumerate(outer_clauses):
        # 收集可能与此外规匹配的内规索引
        candidate_inner_indices = set()

        if use_biz_dim:
            # 基于 biz_dims 快速匹配
            outer_biz_dims = outer.get("biz_dims", [])
            for biz_dim in outer_biz_dims:
                if biz_dim in inner_biz_dim_index:
                    candidate_inner_indices.update(inner_biz_dim_index[biz_dim])

        if use_subject:
            # 基于 subjects 快速匹配
            outer_subjects = outer.get("subjects", [])
            for subject in outer_subjects:
                if subject in inner_subject_index:
                    candidate_inner_indices.update(inner_subject_index[subject])

        # 如果没有配置硬筛选，则使用全部内规（不推荐）
        if not use_biz_dim and not use_subject:
            candidate_inner_indices = set(range(len(inner_clauses)))

        # 只对候选内规计算相似度
        for inner_idx in candidate_inner_indices:
            pair_key = (outer_idx, inner_idx)
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            inner = inner_clauses[inner_idx]

            # 计算相似度
            similarity = compute_similarity(outer, inner)

            # 硬筛选
            if not check_hard_filter(similarity, hard_config):
                continue

            # 软筛选
            score = compute_weighted_score(similarity, weights)
            if score < min_score:
                continue

            # 确定置信级别
            confidence_level = "high" if score >= 0.6 else "medium"

            candidates.append({
                "pair_id": f"{outer.get('uid', '')}_{inner.get('uid', '')}",
                "outer_clause": outer,
                "inner_clause": inner,
                "similarity_score": score,
                "confidence_level": confidence_level,
                "match_details": similarity,
            })

    print(f"[Filter] 候选对: {len(candidates)} 条 (检查了 {len(processed_pairs)} 对)")

    # 按相似度排序
    candidates.sort(key=lambda x: x["similarity_score"], reverse=True)

    return candidates
