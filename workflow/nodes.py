"""工作流节点函数"""
import json
import sys
from pathlib import Path
from typing import Any

from parser import parse_inner_docx, parse_outer_docx, parse_outer_json
from filter import filter_candidates
from llm import (
    call_llm_with_retries,
    build_judgment_prompt,
    build_review_prompt,
    build_retry_prompt,
    parse_judgment_response,
    parse_review_response,
    GlobalRateLimiter,
    get_client_from_config,
)


def node_parse_clauses(state: dict) -> dict:
    """节点：解析条款"""
    config = state["config"]
    data_config = config.get("data", {})
    output_dir = Path(data_config.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 缓存文件路径
    outer_cache_path = output_dir / "outer_clauses_with_semantics.json"
    inner_cache_path = output_dir / "inner_clauses_with_semantics.json"
    parser_config = config.get("parser", {})
    use_cache = parser_config.get("use_semantics_cache", True)

    # 1. 尝试读取缓存 — 仅检查内规缓存；外规每次从 JSON 重新解析 + 关键词匹配
    if use_cache and inner_cache_path.exists():
        print(f"[Parse] 加载缓存的内规语义数据...", flush=True)
        inner_clauses = json.loads(inner_cache_path.read_text(encoding="utf-8"))
        outer_dir = Path(data_config.get("outer_dir", "data/outer"))
        outer_json_path = outer_dir / "full_outer_data.json"
        outer_clauses = parse_outer_json(outer_json_path) if outer_json_path.exists() else []

        print(f"[Parse] 外规: {len(outer_clauses)} 条, 从内规构建关键词表...", flush=True)
        biz_dim_keys = sorted(set(k for c in inner_clauses for k in c.get("biz_dims", []) if k), key=len, reverse=True)
        subject_keys = sorted(set(k for c in inner_clauses for k in c.get("subjects", []) if k), key=len, reverse=True)
        object_keys = sorted(set(k for c in inner_clauses for k in c.get("objects", []) if k), key=len, reverse=True)
        print(f"  关键词: {len(biz_dim_keys)} biz_dims, {len(subject_keys)} subjects, {len(object_keys)} objects", flush=True)

        from parser import extract_action_from_text
        for clause in outer_clauses:
            ct = clause.get("clause_text", "")
            if not ct:
                clause["subjects"] = []; clause["objects"] = []; clause["biz_dims"] = []; clause["action"] = None
                continue
            clause["biz_dims"] = list(set(k for k in biz_dim_keys if k in ct))
            clause["subjects"] = list(set(k for k in subject_keys if k in ct))
            clause["objects"] = list(set(k for k in object_keys if k in ct))
            clause["action"] = extract_action_from_text(ct)

        print(f"  完成: {sum(1 for c in outer_clauses if c['biz_dims'])} 条有 biz_dims, "
              f"{sum(1 for c in outer_clauses if c['subjects'])} 条有 subjects", flush=True)
        return {
            "outer_clauses": outer_clauses,
            "inner_clauses": inner_clauses,
            "clauses_loaded": True,
        }

    # 2. 尝试读取现成的条款 JSON
    clauses_path = data_config.get("clauses_json_path", "")
    if clauses_path and Path(clauses_path).exists():
        clauses = json.loads(Path(clauses_path).read_text(encoding="utf-8"))
        outer_clauses = [c for c in clauses if c.get("source") == "外规"]
        inner_clauses = [c for c in clauses if c.get("source") == "内规"]
        return {
            "outer_clauses": outer_clauses,
            "inner_clauses": inner_clauses,
            "clauses_loaded": True,
        }

    # 3. 回退：调用独立解析器
    outer_dir = Path(data_config.get("outer_dir", "data/outer"))
    inner_dir = Path(data_config.get("inner_dir", "data/inner"))

    outer_clauses = []
    inner_clauses = []

    # 解析外规 — 优先使用 JSON 格式，回退到 DOCX
    outer_json_path = outer_dir / "full_outer_data.json"
    if outer_json_path.exists():
        print(f"[Parse] 使用 JSON 格式外规数据: {outer_json_path}", flush=True)
        outer_clauses = parse_outer_json(outer_json_path)
    else:
        for f in sorted(outer_dir.glob("*.docx")):
            try:
                result = parse_outer_docx(f)
                for clause in result["clauses"]:
                    clause["doc_title"] = result["regulation"]["title"]
                    clause["statute_id"] = result["regulation"]["statute_id"]
                outer_clauses.extend(result["clauses"])
            except Exception as e:
                print(f"  外规解析失败: {f.name} → {e}")

    # 解析内规
    for f in sorted(inner_dir.glob("*.docx")):
        try:
            clauses = parse_inner_docx(f)
            inner_clauses.extend(clauses)
        except Exception as e:
            print(f"  内规解析失败: {f.name} → {e}")

    print(f"[Parse] 外规: {len(outer_clauses)} 条, 内规: {len(inner_clauses)} 条")

    # 4. 提取语义要素（如果配置启用）
    if parser_config.get("extract_semantics", False):
        print("[Parse] 提取语义要素...")
        from parser import batch_extract_semantics, SynonymNormalizer
        from llm import get_client_from_config, GlobalRateLimiter

        llm_config = config.get("llm", {})
        model = llm_config.get("judgment_model", "qwen-plus")
        client = get_client_from_config(config)
        rate_limiter = GlobalRateLimiter(min_interval=1.0 / llm_config.get("rate_limit_per_second", 2.0))

        # 加载同义词归一化器
        normalizer = None
        if parser_config.get("use_synonym_dict", False):
            synonym_dict_path = parser_config.get("synonym_dict_path", "")
            if not synonym_dict_path:
                # 尝试默认路径
                default_path = Path(__file__).parent.parent.parent / "output" / "synonym_dictionary.json"
                if default_path.exists():
                    synonym_dict_path = str(default_path)
            if synonym_dict_path:
                normalizer = SynonymNormalizer(synonym_dict_path)

        # 语义提取策略：
        #   - 内规（7k条）走 LLM 提取 — 用于构造候选对
        #   - 外规（134k条）走关键词匹配 — 基于内规已提取的实体关键词
        llm_concurrency = parser_config.get("llm_concurrency", 3)
        from parser import extract_action_from_text
        import re

        print("[Parse] 内规: LLM 语义提取...", flush=True)
        inner_clauses = batch_extract_semantics(
            inner_clauses,
            model=model,
            client=client,
            rate_limiter=rate_limiter,
            concurrency=llm_concurrency,
            normalizer=normalizer,
        )

        # 从内规语义中收集关键词表
        print("[Parse] 从内规语义构建关键词表...", flush=True)
        biz_dim_keywords = sorted(set(k for c in inner_clauses for k in c.get("biz_dims", []) if k), key=len, reverse=True)
        subject_keywords = sorted(set(k for c in inner_clauses for k in c.get("subjects", []) if k), key=len, reverse=True)
        print(f"  收集到 {len(biz_dim_keywords)} 个业务维度关键词, {len(subject_keywords)} 个主体关键词", flush=True)

        print("[Parse] 外规: 关键词匹配提取语义...", flush=True)
        for clause in outer_clauses:
            ct = clause.get("clause_text", "")
            if not ct:
                clause["subjects"] = []; clause["objects"] = []; clause["biz_dims"] = []; clause["action"] = None
                continue
            clause["biz_dims"] = list(set(k for k in biz_dim_keywords if k in ct))
            clause["subjects"] = list(set(k for k in subject_keywords if k in ct))
            clause["objects"] = []
            clause["action"] = extract_action_from_text(ct)

        print(f"[Parse] 语义提取完成")

        # 保存到缓存文件 — 仅缓存内规（外规只有规则提取）
        if use_cache:
            inner_cache_path.write_text(json.dumps(inner_clauses, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[Parse] 内规语义数据已缓存到 {inner_cache_path}", flush=True)

    return {
        "outer_clauses": outer_clauses,
        "inner_clauses": inner_clauses,
        "clauses_loaded": True,
    }


def node_filter_candidates(state: dict) -> dict:
    """节点：语义要素预筛选"""
    outer_clauses = state["outer_clauses"]
    inner_clauses = state["inner_clauses"]
    config = state["config"]

    filter_config = config.get("filter", {})
    data_config = config.get("data", {})
    output_dir = Path(data_config.get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 候选对缓存文件路径（轻量级，只存索引）
    candidates_cache_path = output_dir / "candidate_pairs_index.json"
    target_config = config.get("target", {})
    max_candidates = target_config.get("max_candidates_to_process", 0)

    # 尝试从缓存加载
    parser_config = config.get("parser", {})
    use_cache = parser_config.get("use_semantics_cache", True)

    if use_cache and candidates_cache_path.exists():
        print(f"[Filter] 加载缓存的候选对索引...", flush=True)
        cached_data = json.loads(candidates_cache_path.read_text(encoding="utf-8"))
        # 从索引重建候选对（关联完整条款数据）
        candidates = []
        for item in cached_data.get("pairs", []):
            outer_idx = item["outer_idx"]
            inner_idx = item["inner_idx"]
            if outer_idx < len(outer_clauses) and inner_idx < len(inner_clauses):
                candidates.append({
                    "pair_id": item["pair_id"],
                    "outer_clause": outer_clauses[outer_idx],
                    "inner_clause": inner_clauses[inner_idx],
                    "similarity_score": item["score"],
                    "confidence_level": item["confidence"],
                    "match_details": item["match_details"],
                })
        print(f"[Filter] 从缓存加载 {len(candidates)} 条候选对", flush=True)
    else:
        # 执行筛选
        candidates = filter_candidates(outer_clauses, inner_clauses, filter_config)

        # 保存到缓存（轻量级，只存索引和分数）
        # 构建条款 UID 到索引的映射
        outer_uid_to_idx = {c.get("uid", ""): i for i, c in enumerate(outer_clauses)}
        inner_uid_to_idx = {c.get("uid", ""): i for i, c in enumerate(inner_clauses)}

        lightweight_pairs = []
        for c in candidates:
            outer_uid = c["outer_clause"].get("uid", "")
            inner_uid = c["inner_clause"].get("uid", "")
            outer_idx = outer_uid_to_idx.get(outer_uid, -1)
            inner_idx = inner_uid_to_idx.get(inner_uid, -1)
            lightweight_pairs.append({
                "pair_id": c["pair_id"],
                "outer_idx": outer_idx,
                "inner_idx": inner_idx,
                "score": c["similarity_score"],
                "confidence": c["confidence_level"],
                "match_details": c["match_details"],
            })

        cache_data = {
            "total_count": len(candidates),
            "pairs": lightweight_pairs,
        }
        candidates_cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")
        print(f"[Filter] 候选对索引已缓存到 {candidates_cache_path}", flush=True)

    # 限制候选对数量（用于测试或控制处理时间）
    if max_candidates > 0 and len(candidates) > max_candidates:
        print(f"[Filter] 限制候选对数量: {len(candidates)} → {max_candidates}", flush=True)
        candidates = candidates[:max_candidates]

    # 更新统计
    stats = state.get("stats", {})
    stats["candidate_generation"] = {
        "total_combinations": len(outer_clauses) * len(inner_clauses),
        "after_filter": len(candidates),
        "high_confidence": sum(1 for c in candidates if c["confidence_level"] == "high"),
        "medium_confidence": sum(1 for c in candidates if c["confidence_level"] == "medium"),
    }

    print(f"[Filter] 候选对: {len(candidates)} 条", flush=True)
    sys.stdout.flush()

    return {
        "candidate_pairs": candidates,
        "candidate_idx": 0,
        "stats": stats,
    }


# 全局限流器（跨节点共享）
_rate_limiter = None


def _get_rate_limiter(config: dict) -> GlobalRateLimiter:
    """获取或创建限流器"""
    global _rate_limiter
    if _rate_limiter is None:
        llm_config = config.get("llm", {})
        rate = llm_config.get("rate_limit_per_second", 2.0)
        _rate_limiter = GlobalRateLimiter(min_interval=1.0 / rate)
    return _rate_limiter


def node_judge(state: dict) -> dict:
    """节点：LLM 生成判定"""
    candidate_pairs = state["candidate_pairs"]
    candidate_idx = state["candidate_idx"]
    retry_count = state.get("retry_count", 0)
    config = state["config"]

    # 输出进度
    total = len(candidate_pairs)
    print(f"[Judge] 处理 {candidate_idx + 1}/{total} (重试: {retry_count})", flush=True)

    current_pair = candidate_pairs[candidate_idx]
    outer = current_pair["outer_clause"]
    inner = current_pair["inner_clause"]

    # 构建 Prompt
    if retry_count > 0 and state.get("judgment_result") and state.get("review_result"):
        # 重试模式：附带评审反馈
        original_prompt = build_judgment_prompt(
            outer_doc_title=outer.get("doc_title", ""),
            outer_article_no=outer.get("article_no", ""),
            outer_content=outer.get("clause_text", ""),
            outer_subjects=outer.get("subjects", []),
            outer_objects=outer.get("objects", []),
            outer_biz_dims=outer.get("biz_dims", []),
            outer_action=outer.get("action", ""),
            outer_threshold="",
            inner_doc_title=inner.get("doc_title", ""),
            inner_article_no=inner.get("article_no", ""),
            inner_content=inner.get("clause_text", ""),
            inner_subjects=inner.get("subjects", []),
            inner_objects=inner.get("objects", []),
            inner_biz_dims=inner.get("biz_dims", []),
            inner_action=inner.get("action", ""),
        )
        prompt = build_retry_prompt(
            original_prompt,
            state["judgment_result"],
            state["review_result"],
        )
    else:
        prompt = build_judgment_prompt(
            outer_doc_title=outer.get("doc_title", ""),
            outer_article_no=outer.get("article_no", ""),
            outer_content=outer.get("clause_text", ""),
            outer_subjects=outer.get("subjects", []),
            outer_objects=outer.get("objects", []),
            outer_biz_dims=outer.get("biz_dims", []),
            outer_action=outer.get("action", ""),
            outer_threshold="",
            inner_doc_title=inner.get("doc_title", ""),
            inner_article_no=inner.get("article_no", ""),
            inner_content=inner.get("clause_text", ""),
            inner_subjects=inner.get("subjects", []),
            inner_objects=inner.get("objects", []),
            inner_biz_dims=inner.get("biz_dims", []),
            inner_action=inner.get("action", ""),
        )

    # 调用 LLM
    llm_config = config.get("llm", {})
    model = llm_config.get("judgment_model", "qwen-plus")
    rate_limiter = _get_rate_limiter(config)
    client = get_client_from_config(config)

    response = call_llm_with_retries(prompt, rate_limiter, model=model, client=client)
    judgment_result = parse_judgment_response(response)
    judgment_result["pair_id"] = current_pair["pair_id"]

    return {
        "current_pair": current_pair,
        "judgment_result": judgment_result,
        "retry_count": retry_count,
    }


def node_review(state: dict) -> dict:
    """节点：LLM 评审校验"""
    current_pair = state["current_pair"]
    judgment_result = state["judgment_result"]
    config = state["config"]

    print(f"[Review] 开始评审...", flush=True)

    # 构建 Prompt
    prompt = build_review_prompt(
        judgment_result=json.dumps(judgment_result, ensure_ascii=False),
        outer_content=current_pair["outer_clause"].get("clause_text", ""),
        inner_content=current_pair["inner_clause"].get("clause_text", ""),
    )

    # 调用 LLM
    llm_config = config.get("llm", {})
    model = llm_config.get("review_model", "qwen-plus")
    rate_limiter = _get_rate_limiter(config)
    client = get_client_from_config(config)

    response = call_llm_with_retries(prompt, rate_limiter, model=model, client=client)
    review_result = parse_review_response(response)
    review_result["pair_id"] = current_pair["pair_id"]

    print(f"[Review] 完成: passed={review_result.get('passed')}, score={review_result.get('score')}", flush=True)

    return {
        "review_result": review_result,
    }


def node_process_result(state: dict) -> dict:
    """节点：处理判定结果"""
    judgment_result = state["judgment_result"]
    review_result = state["review_result"]
    retry_count = state["retry_count"]
    current_pair = state["current_pair"]
    config = state["config"]

    review_config = config.get("review", {})
    max_retries = review_config.get("max_retries", 2)
    pass_threshold = review_config.get("pass_threshold", 70)

    # 调试输出
    print(f"[Process] review_passed={review_result.get('passed')}, score={review_result.get('score')}, retry={retry_count}", flush=True)

    # 1. 评审通过
    if review_result.get("passed") and review_result.get("score", 0) >= pass_threshold:
        qa_pair = _build_qa_pair(current_pair, judgment_result, review_result)
        print(f"[Process] → PASSED, moving to next candidate", flush=True)
        return {
            "qa_pairs": [qa_pair],
            "retry_count": 0,
            "candidate_idx": state["candidate_idx"] + 1,
            "need_retry": False,  # 标记不需要重试
        }

    # 2. 评审未通过，但还可重试
    if retry_count < max_retries:
        new_retry = retry_count + 1
        print(f"[Process] → RETRY ({new_retry}/{max_retries})", flush=True)
        return {
            "retry_count": new_retry,
            "need_retry": True,  # 标记需要重试
        }

    # 3. 重试耗尽，标记为失败
    failed_pair = _build_failed_pair(current_pair, judgment_result, review_result, retry_count)
    print(f"[Process] → FAILED, moving to next candidate", flush=True)
    return {
        "failed_pairs": [failed_pair],
        "retry_count": 0,
        "candidate_idx": state["candidate_idx"] + 1,
        "need_retry": False,  # 标记不需要重试
    }


def _build_qa_pair(current_pair: dict, judgment: dict, review: dict) -> dict:
    """构建 QA 对"""
    return {
        "id": f"qa_{current_pair['pair_id']}",
        "outer_clause": current_pair["outer_clause"],
        "inner_clause": current_pair["inner_clause"],
        "label": judgment.get("label", ""),
        "confidence": judgment.get("confidence", 0.0),
        "reasoning": judgment.get("reasoning", ""),
        "key_evidence": judgment.get("key_evidence", []),
        "conflict_details": judgment.get("conflict_details", {}),
        "quality_score": review.get("score", 0),
        "retry_count": 0,
        "is_low_quality": False,
    }


def _build_failed_pair(
    current_pair: dict,
    judgment: dict,
    review: dict,
    retry_count: int
) -> dict:
    """构建失败记录"""
    from datetime import datetime
    return {
        "pair_id": current_pair["pair_id"],
        "outer_clause": current_pair["outer_clause"],
        "inner_clause": current_pair["inner_clause"],
        "judgment": judgment,
        "review_score": review.get("score", 0),
        "review_feedback": review.get("feedback", ""),
        "retry_count": retry_count,
        "failed_at": datetime.now().isoformat(),
    }


def node_split_dataset(state: dict) -> dict:
    """节点：划分训练集/验证集"""
    import random

    qa_pairs = state["qa_pairs"]
    config = state["config"]

    split_config = config.get("split", {})
    val_ratio = split_config.get("val_clause_ratio", 0.05)
    random_seed = split_config.get("random_seed", 42)

    random.seed(random_seed)

    # 收集所有条款 ID
    outer_ids = set(qa["outer_clause"].get("uid", "") for qa in qa_pairs)
    inner_ids = set(qa["inner_clause"].get("uid", "") for qa in qa_pairs)

    # 随机划分
    outer_ids_list = list(outer_ids)
    inner_ids_list = list(inner_ids)
    random.shuffle(outer_ids_list)
    random.shuffle(inner_ids_list)

    val_outer_ids = set(outer_ids_list[:int(len(outer_ids_list) * val_ratio)])
    val_inner_ids = set(inner_ids_list[:int(len(inner_ids_list) * val_ratio)])

    # 划分 QA 对
    train_set = []
    val_set = []

    for qa in qa_pairs:
        outer_in_val = qa["outer_clause"].get("uid", "") in val_outer_ids
        inner_in_val = qa["inner_clause"].get("uid", "") in val_inner_ids

        if outer_in_val and inner_in_val:
            val_set.append(qa)
        elif not outer_in_val and not inner_in_val:
            train_set.append(qa)
        else:
            train_set.append(qa)

    print(f"[Split] 训练集: {len(train_set)}, 验证集: {len(val_set)}")

    return {
        "train_set": train_set,
        "val_set": val_set,
    }


def node_persist(state: dict) -> dict:
    """节点：持久化存储"""
    import json
    from pathlib import Path

    config = state["config"]
    output_dir = Path(config.get("data", {}).get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存训练集
    train_path = output_dir / "train.jsonl"
    with open(train_path, "w", encoding="utf-8") as f:
        for qa in state["train_set"]:
            f.write(json.dumps(qa, ensure_ascii=False) + "\n")

    # 保存验证集
    val_path = output_dir / "val.jsonl"
    with open(val_path, "w", encoding="utf-8") as f:
        for qa in state["val_set"]:
            f.write(json.dumps(qa, ensure_ascii=False) + "\n")

    # 保存失败数据
    if state["failed_pairs"]:
        failed_path = output_dir / "failed_pairs.jsonl"
        with open(failed_path, "w", encoding="utf-8") as f:
            for fp in state["failed_pairs"]:
                f.write(json.dumps(fp, ensure_ascii=False) + "\n")

    # 保存统计
    stats_path = output_dir / "stats.json"
    stats_path.write_text(
        json.dumps(state["stats"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[Persist] 已保存到 {output_dir}")

    return {}
