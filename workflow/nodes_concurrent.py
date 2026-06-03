"""并发工作流节点 - 批量处理候选对以提高效率"""
import json
import sys
import asyncio
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from parser import parse_inner_docx, parse_outer_docx, parse_outer_json
from filter import filter_candidates
from llm import (
    call_llm_with_retries,
    build_judgment_prompt,
    build_review_prompt,
    parse_judgment_response,
    parse_review_response,
    GlobalRateLimiter,
    get_client_from_config,
    generate_conflict_qa,  # 新增：冲突场景生成
)

# 关键词过滤：短词和泛化词黑名单，这些词在外规中命中率太高导致候选对质量差
_KEYWORD_MIN_LEN = 3  # 最短关键词长度（字符数）
_KEYWORD_BLACKLIST = {
    # 泛化主体/实体词，命中太宽泛
    "银行", "业务", "人员", "管理", "部门", "机构", "单位",
    "企业", "公司", "客户", "员工", "股东", "用户", "会员",
    "董事", "监事", "高管", "经理", "行长", "主任", "负责人",
    "信息", "数据", "资料", "文件", "记录", "报告",
    "资金", "资产", "现金", "存款", "贷款", "合同", "账户",
    "系统", "技术", "网络", "设备", "项目", "产品", "服务",
    "风险", "制度", "规定", "办法", "流程", "标准",
    "本行", "我方", "对方", "第三方", "相关方",
    "上级", "下级", "相关", "有关",
}


def _filter_keywords(keywords: set) -> list:
    """过滤关键词：排除短词和泛化黑名单词，按长度降序排列"""
    return sorted(
        [k for k in keywords if k and len(k) >= _KEYWORD_MIN_LEN and k not in _KEYWORD_BLACKLIST],
        key=len, reverse=True
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

        # 外规从 JSON 重新解析
        outer_dir = Path(data_config.get("outer_dir", "data/outer"))
        outer_json_path = outer_dir / "full_outer_data.json"
        outer_clauses = parse_outer_json(outer_json_path) if outer_json_path.exists() else []

        # 从内规语义收集关键词表，对外规做关键词匹配
        print(f"[Parse] 外规: {len(outer_clauses)} 条, 从内规构建关键词表...", flush=True)
        biz_dim_keywords = _filter_keywords(set(k for c in inner_clauses for k in c.get("biz_dims", []) if k))
        subject_keywords = _filter_keywords(set(k for c in inner_clauses for k in c.get("subjects", []) if k))
        object_keywords = _filter_keywords(set(k for c in inner_clauses for k in c.get("objects", []) if k))
        print(f"  内规关键词(过滤后): {len(biz_dim_keywords)} biz_dims, {len(subject_keywords)} subjects, {len(object_keywords)} objects", flush=True)

        from parser import extract_action_from_text
        for clause in outer_clauses:
            ct = clause.get("clause_text", "")
            if not ct:
                clause["subjects"] = []; clause["objects"] = []; clause["biz_dims"] = []; clause["action"] = None
                continue
            clause["biz_dims"] = list(set(k for k in biz_dim_keywords if k in ct))
            clause["subjects"] = list(set(k for k in subject_keywords if k in ct))
            clause["objects"] = list(set(k for k in object_keywords if k in ct))
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
        #   - 内规（7k条）走 LLM 提取 — 结果精确，用于构造候选对
        #   - 外规（134k条）走关键词匹配 — 基于内规已提取的实体关键词做文本匹配
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

        # 从内规语义中收集所有出现的 biz_dims / subjects 作为关键词表
        print("[Parse] 从内规语义构建关键词表...", flush=True)
        biz_dim_keywords = set()
        subject_keywords = set()
        for clause in inner_clauses:
            biz_dim_keywords.update(clause.get("biz_dims", []))
            subject_keywords.update(clause.get("subjects", []))
        biz_dim_keywords = _filter_keywords(biz_dim_keywords)
        subject_keywords = _filter_keywords(subject_keywords)
        print(f"  收集到(过滤后) {len(biz_dim_keywords)} 个业务维度关键词, {len(subject_keywords)} 个主体关键词", flush=True)

        print("[Parse] 外规: 关键词匹配提取语义...", flush=True)
        for clause in outer_clauses:
            clause_text = clause.get("clause_text", "")
            if not clause_text:
                clause["subjects"] = []
                clause["objects"] = []
                clause["biz_dims"] = []
                clause["action"] = None
                continue

            # 关键词匹配 biz_dims
            matched_biz = set()
            for kw in biz_dim_keywords:
                if kw in clause_text:
                    matched_biz.add(kw)
            clause["biz_dims"] = list(matched_biz)

            # 关键词匹配 subjects
            matched_subj = set()
            for kw in subject_keywords:
                if kw in clause_text:
                    matched_subj.add(kw)
            clause["subjects"] = list(matched_subj)

            clause["objects"] = []
            clause["action"] = extract_action_from_text(clause_text)

        print(f"[Parse] 语义提取完成")

        # 保存到缓存文件 — 仅缓存内规（外规只有规则提取，下次重新解析更快）
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

    # 将 max_candidates 注入 filter_config 以便 stratified_filter_candidates 读取
    filter_config = dict(filter_config)
    if "target" not in filter_config:
        filter_config["target"] = {}
    filter_config["target"]["max_candidates_to_process"] = max_candidates

    # 检查是否启用分层筛选
    use_stratified = filter_config.get("use_stratified", False)

    # 尝试从缓存加载（分层筛选不使用缓存）
    parser_config = config.get("parser", {})
    use_cache = parser_config.get("use_semantics_cache", True) and not use_stratified

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
                    "layer": item.get("layer", "unknown"),  # 读取分层信息
                })
        print(f"[Filter] 从缓存加载 {len(candidates)} 条候选对", flush=True)
    else:
        # 执行筛选
        if use_stratified:
            print(f"[Filter] 使用分层筛选模式...", flush=True)
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
                "layer": c.get("layer", "unknown"),  # 保存分层信息
            })

        cache_data = {
            "total_count": len(candidates),
            "pairs": lightweight_pairs,
        }
        candidates_cache_path.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")
        print(f"[Filter] 候选对索引已缓存到 {candidates_cache_path}", flush=True)

    # 限制候选对数量（分层截断，保持各层比例）
    if max_candidates > 0 and len(candidates) > max_candidates:
        print(f"[Filter] 分层截断候选对数量: {len(candidates)} → {max_candidates}", flush=True)
        # 按层分组
        by_layer = {}
        for c in candidates:
            layer = c.get("layer", "unknown")
            if layer not in by_layer:
                by_layer[layer] = []
            by_layer[layer].append(c)

        # 按比例从各层采样
        import random
        random.seed(42)
        layer_ratios = filter_config.get("layer_ratios", {
            "L1_strong": 0.45,
            "L2_moderate": 0.25,
            "L3_weak": 0.15,
            "L4_opposite": 0.15,
        })
        truncated = []
        for layer_name, ratio in layer_ratios.items():
            layer_candidates = by_layer.get(layer_name, [])
            n_samples = int(max_candidates * ratio)
            if len(layer_candidates) <= n_samples:
                truncated.extend(layer_candidates)
            else:
                truncated.extend(random.sample(layer_candidates, n_samples))
        candidates = truncated
        print(f"[Filter] 截断后各层数量: {dict((k, len(v)) for k, v in by_layer.items())}", flush=True)

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


def _process_single_candidate(
    candidate: dict,
    config: dict,
    rate_limiter: GlobalRateLimiter,
    client: Any,
) -> dict:
    """
    处理单个候选对（判断 + 评审）

    Returns:
        成功: {"status": "success", "qa_pair": {...}}
        失败: {"status": "failed", "failed_pair": {...}}
    """
    llm_config = config.get("llm", {})
    model = llm_config.get("judgment_model", "qwen-plus")
    review_config = config.get("review", {})
    max_retries = review_config.get("max_retries", 2)
    pass_threshold = review_config.get("pass_threshold", 70)

    outer = candidate["outer_clause"]
    inner = candidate["inner_clause"]

    retry_count = 0
    last_judgment = None
    last_review = None

    for attempt in range(max_retries + 1):
        # 构建判断 Prompt
        if retry_count > 0 and last_judgment and last_review:
            # 重试模式：附带评审反馈
            from llm import build_retry_prompt
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
            prompt = build_retry_prompt(original_prompt, last_judgment, last_review)
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

        # 调用判断 LLM
        try:
            response = call_llm_with_retries(prompt, rate_limiter, model=model, client=client)
            judgment = parse_judgment_response(response)
            judgment["pair_id"] = candidate["pair_id"]
            last_judgment = judgment

            # JSON 完整性校验：如果有 parse_error，重试而非直接失败
            if judgment.get("parse_error"):
                missing = judgment.get("missing_fields", [])
                if attempt < max_retries:
                    print(f"  [Judgment] JSON 不完整 ({', '.join(missing)})，重试 attempt={attempt+1}", flush=True)
                    retry_count += 1
                    continue
                else:
                    return {
                        "status": "failed",
                        "failed_pair": {
                            "pair_id": candidate["pair_id"],
                            "outer_clause": outer,
                            "inner_clause": inner,
                            "judgment": judgment,
                            "review_score": 0,
                            "review_feedback": f"JSON 不完整(重试{max_retries}次后): {', '.join(missing)}",
                            "retry_count": retry_count,
                        }
                    }

        except Exception as e:
            if attempt < max_retries:
                retry_count += 1
                continue
            return {
                "status": "failed",
                "failed_pair": {
                    "pair_id": candidate["pair_id"],
                    "outer_clause": outer,
                    "inner_clause": inner,
                    "judgment": None,
                    "review_score": 0,
                    "review_feedback": f"判断调用失败: {e}",
                    "retry_count": retry_count,
                }
            }

        # 构建评审 Prompt
        review_prompt = build_review_prompt(
            judgment_result=json.dumps(judgment, ensure_ascii=False),
            outer_content=outer.get("clause_text", ""),
            inner_content=inner.get("clause_text", ""),
        )

        # 调用评审 LLM
        try:
            review_response = call_llm_with_retries(review_prompt, rate_limiter, model=model, client=client)
            review = parse_review_response(review_response)
            review["pair_id"] = candidate["pair_id"]
            last_review = review
        except Exception as e:
            if attempt < max_retries:
                retry_count += 1
                continue
            return {
                "status": "failed",
                "failed_pair": {
                    "pair_id": candidate["pair_id"],
                    "outer_clause": outer,
                    "inner_clause": inner,
                    "judgment": judgment,
                    "review_score": 0,
                    "review_feedback": f"评审调用失败: {e}",
                    "retry_count": retry_count,
                }
            }

        # 检查评审结果
        if review.get("passed") and review.get("score", 0) >= pass_threshold:
            # 通过
            qa_pair = {
                "id": f"qa_{candidate['pair_id']}",
                "outer_clause": outer,
                "inner_clause": inner,
                "label": judgment.get("label", ""),
                "confidence": judgment.get("confidence", 0.0),
                "reasoning": judgment.get("reasoning", ""),
                "key_evidence": judgment.get("key_evidence", []),
                "conflict_details": judgment.get("conflict_details", {}),
                "quality_score": review.get("score", 0),
                "retry_count": retry_count,
                "is_low_quality": False,
            }

            # 新增：如果标签是"完全符合"或"基本一致"，额外生成冲突QA
            result = {"status": "success", "qa_pair": qa_pair}
            if judgment.get("label") in ["完全符合", "基本一致"]:
                conflict_qa = generate_conflict_qa(
                    outer_clause=outer,
                    inner_clause=inner,
                    original_label=judgment.get("label", ""),
                    reasoning=judgment.get("reasoning", ""),
                    client=client,
                    rate_limiter=rate_limiter,
                    model=model,
                )
                if conflict_qa:
                    result["conflict_qa"] = conflict_qa

            return result

        # 未通过，检查是否可重试
        if retry_count < max_retries:
            retry_count += 1
            continue
        else:
            # 重试耗尽
            from datetime import datetime
            return {
                "status": "failed",
                "failed_pair": {
                    "pair_id": candidate["pair_id"],
                    "outer_clause": outer,
                    "inner_clause": inner,
                    "judgment": judgment,
                    "review_score": review.get("score", 0),
                    "review_feedback": review.get("feedback", ""),
                    "retry_count": retry_count,
                    "failed_at": datetime.now().isoformat(),
                }
            }

    # 不应该到达这里
    return {
        "status": "failed",
        "failed_pair": {
            "pair_id": candidate["pair_id"],
            "outer_clause": outer,
            "inner_clause": inner,
            "judgment": last_judgment,
            "review_score": last_review.get("score", 0) if last_review else 0,
            "review_feedback": "未知错误",
            "retry_count": retry_count,
        }
    }


def _save_checkpoint(output_dir: Path, qa_pairs: list, conflict_qa_pairs: list,
                     failed_pairs: list, processed_count: int, next_idx: int) -> None:
    """保存断点"""
    import datetime
    checkpoint = {
        "qa_pairs": qa_pairs,
        "conflict_qa_pairs": conflict_qa_pairs,
        "failed_pairs": failed_pairs,
        "processed_count": processed_count,
        "next_candidate_idx": next_idx,
        "saved_at": datetime.datetime.now().isoformat(),
    }
    cp_path = output_dir / ".checkpoints" / "batch_checkpoint.json"
    cp_path.parent.mkdir(parents=True, exist_ok=True)
    # 原子写入：先写临时文件再 rename
    tmp_path = cp_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(cp_path)  # replace 跨平台覆盖，rename 在 Windows 下不允许目标已存在
    print(f"[Checkpoint] 已保存: 进度 {processed_count}, 有效QA {len(qa_pairs)} -> {cp_path}", flush=True)


def _load_checkpoint(output_dir: Path) -> dict | None:
    """加载断点"""
    cp_path = output_dir / ".checkpoints" / "batch_checkpoint.json"
    if not cp_path.exists():
        return None
    data = json.loads(cp_path.read_text(encoding="utf-8"))
    print(f"[Checkpoint] 恢复断点: 进度 {data['processed_count']}, 有效QA {len(data['qa_pairs'])}", flush=True)
    return data


def node_batch_process(state: dict) -> dict:
    """
    节点：批量并发处理候选对（动态调度 + 断点续传 + 无关过滤）

    每 CHECKPOINT_INTERVAL 条保存一次断点，中断后可从中恢复。
    """
    from concurrent.futures import wait, FIRST_COMPLETED

    CHECKPOINT_INTERVAL = 5000

    candidates = state["candidate_pairs"]
    config = state["config"]

    llm_config = config.get("llm", {})
    max_concurrent = llm_config.get("max_concurrent_calls", 5)

    rate_limiter = _get_rate_limiter(config)
    client = get_client_from_config(config)

    total = len(candidates)
    print(f"[BatchProcess] 开始处理 {total} 个候选对，并发数: {max_concurrent}", flush=True)

    # 断点目录
    data_config = config.get("data", {})
    output_dir = Path(data_config.get("output_dir", "output"))

    # 尝试恢复断点
    cp = _load_checkpoint(output_dir)
    if cp is not None:
        qa_pairs = cp["qa_pairs"]
        conflict_qa_pairs = cp.get("conflict_qa_pairs", [])
        failed_pairs = cp["failed_pairs"]
        processed_count = cp["processed_count"]
        next_candidate_idx = cp["next_candidate_idx"]
        print(f"[BatchProcess] 从断点继续: 已完成 {processed_count}/{total}, 跳过前 {next_candidate_idx} 个候选对", flush=True)
    else:
        qa_pairs = []
        conflict_qa_pairs = []
        failed_pairs = []
        processed_count = 0
        next_candidate_idx = 0

    last_checkpoint = processed_count

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = set()

        def submit_one():
            nonlocal next_candidate_idx
            if next_candidate_idx >= total:
                return
            c = candidates[next_candidate_idx]
            futures.add(executor.submit(_process_single_candidate, c, config, rate_limiter, client))
            next_candidate_idx += 1

        # 初始填充
        for _ in range(min(max_concurrent, total - next_candidate_idx)):
            submit_one()

        while futures:
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for f in done:
                processed_count += 1
                try:
                    result = f.result()
                    if result["status"] == "success":
                        if result["qa_pair"].get("label", "") != "无关":
                            qa_pairs.append(result["qa_pair"])
                            if "conflict_qa" in result:
                                conflict_qa_pairs.append(result["conflict_qa"])
                    else:
                        failed_pairs.append(result["failed_pair"])
                except Exception as e:
                    failed_pairs.append({"error": str(e)})

                if processed_count % 100 == 0 or processed_count == total:
                    print(f"[BatchProcess] 进度: 已处理 {processed_count}/{total}，有效QA {len(qa_pairs)}", flush=True)

                # 断点保存
                if processed_count - last_checkpoint >= CHECKPOINT_INTERVAL:
                    _save_checkpoint(output_dir, qa_pairs, conflict_qa_pairs,
                                     failed_pairs, processed_count, next_candidate_idx)
                    last_checkpoint = processed_count

                submit_one()

    # 最终保存断点
    if processed_count > last_checkpoint:
        _save_checkpoint(output_dir, qa_pairs, conflict_qa_pairs,
                         failed_pairs, processed_count, next_candidate_idx)

    # 全部完成后删除断点
    cp_path = output_dir / ".checkpoints" / "batch_checkpoint.json"
    if cp_path.exists():
        cp_path.unlink()

    dropped_irrelevant = processed_count - len(qa_pairs) - len(failed_pairs)
    print(f"[BatchProcess] 完成: 原始QA {len(qa_pairs)}, 冲突QA {len(conflict_qa_pairs)}, "
          f"失败 {len(failed_pairs)}, 已处理 {processed_count}/{total} (丢弃无关: {dropped_irrelevant})", flush=True)

    return {
        "qa_pairs": qa_pairs,
        "conflict_qa_pairs": conflict_qa_pairs,
        "failed_pairs": failed_pairs,
        "candidate_idx": processed_count,
    }


def node_split_dataset(state: dict) -> dict:
    """节点：划分训练集/验证集"""
    import random

    qa_pairs = state["qa_pairs"]
    conflict_qa_pairs = state.get("conflict_qa_pairs", [])  # 新增：获取冲突QA
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

    # 划分原始 QA 对
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

    # 新增：划分冲突 QA（跟随原始 QA 的划分）
    conflict_train_set = []
    conflict_val_set = []

    for conflict_qa in conflict_qa_pairs:
        source_pair_id = conflict_qa.get("source_pair_id", "")
        # 根据 source_pair_id 判断所属集合
        # source_pair_id 格式: outer_uid_inner_uid
        parts = source_pair_id.rsplit("_", 1)
        if len(parts) == 2:
            outer_uid = parts[0]
            if outer_uid in val_outer_ids:
                conflict_val_set.append(conflict_qa)
            else:
                conflict_train_set.append(conflict_qa)
        else:
            conflict_train_set.append(conflict_qa)

    # 合并原始QA和冲突QA
    train_set_extended = train_set + conflict_train_set
    val_set_extended = val_set + conflict_val_set

    # 打乱顺序
    random.shuffle(train_set_extended)
    random.shuffle(val_set_extended)

    print(f"[Split] 原始训练集: {len(train_set)}, 冲突训练集: {len(conflict_train_set)}")
    print(f"[Split] 原始验证集: {len(val_set)}, 冲突验证集: {len(conflict_val_set)}")
    print(f"[Split] 合并后训练集: {len(train_set_extended)}, 验证集: {len(val_set_extended)}")

    return {
        "train_set": train_set_extended,
        "val_set": val_set_extended,
        "train_set_original": train_set,
        "train_set_conflict": conflict_train_set,
    }


def node_persist(state: dict) -> dict:
    """节点：持久化存储"""
    config = state["config"]
    output_dir = Path(config.get("data", {}).get("output_dir", "output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    train_set = state["train_set"]
    val_set = state["val_set"]

    # 保存完整训练集（包含所有字段）
    train_path = output_dir / "train.jsonl"
    with open(train_path, "w", encoding="utf-8") as f:
        for qa in train_set:
            f.write(json.dumps(qa, ensure_ascii=False) + "\n")

    # 保存完整验证集
    val_path = output_dir / "val.jsonl"
    with open(val_path, "w", encoding="utf-8") as f:
        for qa in val_set:
            f.write(json.dumps(qa, ensure_ascii=False) + "\n")

    # 新增：保存 SFT 格式训练集（LLaMA Factory Alpaca 格式）
    def convert_to_sft_format(qa: dict) -> dict:
        """转换为 LLaMA Factory Alpaca 格式"""
        # 检查是否是冲突QA（有instruction字段）
        if "instruction" in qa:
            return {
                "instruction": qa.get("instruction", ""),
                "input": qa.get("input", ""),
                "output": qa.get("output", ""),
            }

        # 原始QA格式转换
        outer = qa.get("outer_clause", {})
        inner = qa.get("inner_clause", {})

        instruction = "请判断以下内规条款是否与外规条款存在冲突？"
        input_text = f"""外规条款：
文书：{outer.get('doc_title', '')}
条号：{outer.get('article_no', '')}
内容：{outer.get('clause_text', '')}

内规条款：
文书：{inner.get('doc_title', '')}
条号：{inner.get('article_no', '')}
内容：{inner.get('clause_text', '')}"""

        output_text = f"""判断结果：{qa.get('label', '')}
置信度：{qa.get('confidence', 0):.2f}
理由：{qa.get('reasoning', '')}"""

        return {
            "instruction": instruction,
            "input": input_text,
            "output": output_text,
        }

    # 保存 SFT 格式训练集
    train_sft_path = output_dir / "train_sft.jsonl"
    with open(train_sft_path, "w", encoding="utf-8") as f:
        for qa in train_set:
            sft_qa = convert_to_sft_format(qa)
            f.write(json.dumps(sft_qa, ensure_ascii=False) + "\n")

    # 保存 SFT 格式验证集
    val_sft_path = output_dir / "val_sft.jsonl"
    with open(val_sft_path, "w", encoding="utf-8") as f:
        for qa in val_set:
            sft_qa = convert_to_sft_format(qa)
            f.write(json.dumps(sft_qa, ensure_ascii=False) + "\n")

    # 保存原始QA（用于分析）
    train_original_path = output_dir / "train_original.jsonl"
    with open(train_original_path, "w", encoding="utf-8") as f:
        for qa in state.get("train_set_original", []):
            f.write(json.dumps(qa, ensure_ascii=False) + "\n")

    # 保存冲突QA（用于分析）
    train_conflict_path = output_dir / "train_conflict.jsonl"
    with open(train_conflict_path, "w", encoding="utf-8") as f:
        for qa in state.get("train_set_conflict", []):
            f.write(json.dumps(qa, ensure_ascii=False) + "\n")

    # 保存失败数据
    if state["failed_pairs"]:
        failed_path = output_dir / "failed_pairs.jsonl"
        with open(failed_path, "w", encoding="utf-8") as f:
            for fp in state["failed_pairs"]:
                f.write(json.dumps(fp, ensure_ascii=False) + "\n")

    # 统计标签分布
    label_counts = {}
    for qa in train_set:
        label = qa.get("label", qa.get("conflict_type", "unknown"))
        label_counts[label] = label_counts.get(label, 0) + 1

    # 更新统计
    stats = state.get("stats", {})
    stats["output_stats"] = {
        "train_total": len(train_set),
        "val_total": len(val_set),
        "train_original": len(state.get("train_set_original", [])),
        "train_conflict": len(state.get("train_set_conflict", [])),
        "label_distribution": label_counts,
    }

    stats_path = output_dir / "stats.json"
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[Persist] 已保存到 {output_dir}")
    print(f"[Persist] SFT训练集: {train_sft_path} ({len(train_set)} 条)")
    print(f"[Persist] SFT验证集: {val_sft_path} ({len(val_set)} 条)")
    print(f"[Persist] 标签分布: {label_counts}")

    return {}
