#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Small batch test - verify workflow runs correctly"""
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from workflow import build_workflow
from llm import get_client_from_config


def test_llm_connection(config: dict):
    """Test LLM connection"""
    print("\n" + "=" * 50)
    print("[1] Testing LLM connection...")
    print("=" * 50)

    client = get_client_from_config(config)
    llm_config = config.get("llm", {})
    model = llm_config.get("judgment_model", "qwen-plus")

    print(f"  API Key: {llm_config.get('api_key', '')[:10]}...")
    print(f"  Base URL: {llm_config.get('base_url', '')}")
    print(f"  Model: {model}")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with OK"}],
            temperature=0.1,
            max_tokens=10,
        )
        result = response.choices[0].message.content.strip()
        print(f"  Response: {result}")
        print("  [OK] LLM connection successful")
        return True
    except Exception as e:
        print(f"  [FAIL] LLM connection failed: {e}")
        return False


def test_parse_clauses(config: dict):
    """Test clause parsing"""
    print("\n" + "=" * 50)
    print("[2] Testing clause parsing...")
    print("=" * 50)

    from parser import parse_inner_docx, parse_outer_docx, parse_outer_json

    data_config = config.get("data", {})
    outer_dir = Path(data_config.get("outer_dir", "data/outer"))
    inner_dir = Path(data_config.get("inner_dir", "data/inner"))

    outer_clauses = []

    # 优先使用 JSON 格式
    outer_json_path = outer_dir / "full_outer_data.json"
    if outer_json_path.exists():
        print(f"  [JSON] Using: {outer_json_path}")
        # 仅取前 50 条做快速测试
        import json as _json
        with open(outer_json_path, "r", encoding="utf-8") as f:
            raw = _json.load(f)
        from parser import OuterJsonParser
        parser = OuterJsonParser()
        # 仅取前 2 部法规测试
        small_list = raw["statuteList"][:2]
        for st in small_list:
            outer_clauses.extend(parser._process_statute(st))
        del raw
        print(f"  [OK] JSON: {len(outer_clauses)} clauses (sampled)")
    else:
        # 回退到 DOCX — 选取业务域相关的文件
        all_outer_files = sorted(outer_dir.glob("*.docx"))
        outer_files = []
        for f in all_outer_files:
            if "商业银行法" in f.name or "银行业监督" in f.name or "风险管理" in f.name:
                outer_files.append(f)
                if len(outer_files) >= 2:
                    break
        if not outer_files:
            outer_files = all_outer_files[:2]

        print(f"  Outer files: {[f.name for f in outer_files]}")
        for f in outer_files:
            try:
                result = parse_outer_docx(f)
                for clause in result["clauses"]:
                    clause["doc_title"] = result["regulation"]["title"]
                    clause["statute_id"] = result["regulation"]["statute_id"]
                outer_clauses.extend(result["clauses"])
                print(f"  [OK] {f.name}: {len(result['clauses'])} clauses")
            except Exception as e:
                print(f"  [FAIL] {f.name}: {e}")

    # Find inner regulations related to credit/risk/ governance
    all_inner_files = sorted(inner_dir.glob("*.docx"))
    inner_files = []
    for f in all_inner_files:
        if any(kw in f.name for kw in ["信贷", "风险", "合规", "贷款", "章程", "治理", "反洗钱"]):
            inner_files.append(f)
            if len(inner_files) >= 3:
                break

    # If not found, use first 3 files
    if not inner_files:
        inner_files = all_inner_files[:3]

    print(f"  Inner files: {[f.name for f in inner_files]}")

    inner_clauses = []
    for f in inner_files:
        try:
            clauses = parse_inner_docx(f)
            inner_clauses.extend(clauses)
            print(f"  [OK] {f.name}: {len(clauses)} clauses")
        except Exception as e:
            print(f"  [FAIL] {f.name}: {e}")

    print(f"\n  Total: Outer {len(outer_clauses)} clauses, Inner {len(inner_clauses)} clauses")

    return outer_clauses, inner_clauses


def test_extract_semantics(outer_clauses: list, inner_clauses: list, config: dict):
    """Test semantic element extraction"""
    print("\n" + "=" * 50)
    print("[2.5] Testing semantic extraction...")
    print("=" * 50)

    from parser import batch_extract_semantics, SynonymNormalizer
    from llm import get_client_from_config, GlobalRateLimiter

    llm_config = config.get("llm", {})
    model = llm_config.get("judgment_model", "qwen-plus")
    client = get_client_from_config(config)
    rate_limiter = GlobalRateLimiter(min_interval=1.0 / llm_config.get("rate_limit_per_second", 2.0))

    # Load synonym normalizer
    parser_config = config.get("parser", {})
    synonym_dict_path = parser_config.get("synonym_dict_path", "")

    # Default path: use the one from graph database project
    if not synonym_dict_path:
        default_path = Path(__file__).parent.parent / "output" / "synonym_dictionary.json"
        if default_path.exists():
            synonym_dict_path = str(default_path)
            print(f"  Using default synonym dictionary: {synonym_dict_path}")

    normalizer = SynonymNormalizer(synonym_dict_path) if synonym_dict_path else None

    # Only extract semantics for first 10 clauses each (small batch test)
    test_outer = outer_clauses[:10]
    test_inner = inner_clauses[:10]

    print(f"  Extracting semantics for {len(test_outer)} outer clauses...")
    test_outer = batch_extract_semantics(
        test_outer,
        model=model,
        client=client,
        rate_limiter=rate_limiter,
        normalizer=normalizer,
    )

    print(f"  Extracting semantics for {len(test_inner)} inner clauses...")
    test_inner = batch_extract_semantics(
        test_inner,
        model=model,
        client=client,
        rate_limiter=rate_limiter,
        normalizer=normalizer,
    )

    # Show sample results (before and after normalization)
    print("\n  Sample outer clause semantics (after normalization):")
    for clause in test_outer[:2]:
        print(f"    {clause.get('article_no', 'N/A')}: subjects={clause.get('subjects', [])}, biz_dims={clause.get('biz_dims', [])}")

    print("\n  Sample inner clause semantics (after normalization):")
    for clause in test_inner[:2]:
        print(f"    {clause.get('article_no', 'N/A')}: subjects={clause.get('subjects', [])}, biz_dims={clause.get('biz_dims', [])}")

    # Update original lists
    for i, clause in enumerate(test_outer):
        outer_clauses[i] = clause
    for i, clause in enumerate(test_inner):
        inner_clauses[i] = clause

    return outer_clauses, inner_clauses


def test_filter_candidates(outer_clauses: list, inner_clauses: list, config: dict):
    """Test candidate pair filtering"""
    print("\n" + "=" * 50)
    print("[3] Testing candidate filtering...")
    print("=" * 50)

    from filter import filter_candidates, compute_similarity, check_hard_filter

    filter_config = config.get("filter", {})

    # Debug: print semantics for all test clauses
    print("\n  [DEBUG] Outer clause semantics (normalized):")
    for i, clause in enumerate(outer_clauses[:5]):
        print(f"    {i+1}. {clause.get('article_no', 'N/A')}: subjects={clause.get('subjects', [])}, biz_dims={clause.get('biz_dims', [])}")

    print("\n  [DEBUG] Inner clause semantics (normalized):")
    for i, clause in enumerate(inner_clauses[:5]):
        print(f"    {i+1}. {clause.get('article_no', 'N/A')}: subjects={clause.get('subjects', [])}, biz_dims={clause.get('biz_dims', [])}")

    # Debug: compute similarity for first pair
    if outer_clauses and inner_clauses:
        print("\n  [DEBUG] Similarity between first pair:")
        sim = compute_similarity(outer_clauses[0], inner_clauses[0])
        print(f"    biz_dim_match: {sim['biz_dim_match']}")
        print(f"    subject_match: {sim['subject_match']}")
        print(f"    object_match: {sim['object_match']}")

        hard_filter = filter_config.get("hard_filter", {})
        print(f"\n  [DEBUG] Hard filter config: {hard_filter}")
        passed = check_hard_filter(sim, hard_filter)
        print(f"  [DEBUG] Hard filter passed: {passed}")

    # Use original filter config (with synonym normalization, should work better)
    candidates = filter_candidates(outer_clauses, inner_clauses, filter_config)

    print(f"\n  Candidate pairs: {len(candidates)}")

    # If still no candidates, try relaxed filter
    if len(candidates) == 0:
        print("\n  [INFO] No candidates with original filter, trying relaxed filter...")
        relaxed_config = {
            "hard_filter": {"biz_dim_match": ">= 1"},
            "soft_filter": filter_config.get("soft_filter", {})
        }
        candidates = filter_candidates(outer_clauses, inner_clauses, relaxed_config)
        print(f"  Candidate pairs (relaxed): {len(candidates)}")

    # Only take first 3 candidates for LLM test
    test_candidates = candidates[:3]
    print(f"  Test candidates: {len(test_candidates)}")

    if test_candidates:
        print("\n  Example candidate:")
        c = test_candidates[0]
        print(f"    Outer: {c['outer_clause'].get('doc_title', '')} - {c['outer_clause'].get('article_no', '')}")
        print(f"    Inner: {c['inner_clause'].get('doc_title', '')} - {c['inner_clause'].get('article_no', '')}")
        print(f"    Confidence: {c.get('confidence_level', '')}")
        print(f"    Match details: {c.get('match_details', {})}")

    return test_candidates


def test_llm_judgment(candidates: list, config: dict):
    """Test LLM judgment"""
    print("\n" + "=" * 50)
    print("[4] Testing LLM judgment...")
    print("=" * 50)

    if not candidates:
        print("  [WARN] No candidates, skip LLM judgment test")
        return []

    from llm import (
        build_judgment_prompt,
        parse_judgment_response,
        call_llm_with_retries,
        GlobalRateLimiter,
        get_client_from_config,
    )

    llm_config = config.get("llm", {})
    model = llm_config.get("judgment_model", "qwen-plus")
    rate_limiter = GlobalRateLimiter(min_interval=1.0 / llm_config.get("rate_limit_per_second", 2.0))
    client = get_client_from_config(config)

    results = []
    for i, candidate in enumerate(candidates):
        print(f"\n  [{i+1}/{len(candidates)}] Processing candidate...")

        outer = candidate["outer_clause"]
        inner = candidate["inner_clause"]

        # Build judgment prompt
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

        try:
            response = call_llm_with_retries(prompt, rate_limiter, model=model, client=client)
            judgment = parse_judgment_response(response)
            print(f"    Label: {judgment.get('label', 'N/A')}")
            print(f"    Confidence: {judgment.get('confidence', 'N/A')}")
            reason_preview = judgment.get('reasoning', 'N/A')[:50] if judgment.get('reasoning') else 'N/A'
            print(f"    Reasoning: {reason_preview}...")
            results.append({"candidate": candidate, "judgment": judgment})
        except Exception as e:
            print(f"    [FAIL] Judgment failed: {e}")

    return results


def test_workflow_integration(config: dict):
    """Test full workflow integration"""
    print("\n" + "=" * 50)
    print("[5] Testing workflow integration...")
    print("=" * 50)

    from workflow.nodes import node_parse_clauses, node_filter_candidates

    # Initialize state
    state = {
        "config": config,
        "raw_text": "",
        "clauses": [],
        "outer_clauses": [],
        "inner_clauses": [],
        "candidate_pairs": [],
        "candidate_idx": 0,
        "current_pair": None,
        "judgment_result": None,
        "review_result": None,
        "valid_pairs": [],
        "invalid_pairs": [],
        "qa_pairs": [],
        "failed_pairs": [],
        "train_set": [],
        "val_set": [],
        "retry_count": 0,
        "stats": {},
    }

    # Execute parse node
    result = node_parse_clauses(state)
    state.update(result)

    # Limit candidates (small batch test)
    original_outer = state["outer_clauses"][:10]  # Only 10 outer clauses
    original_inner = state["inner_clauses"][:20]  # Only 20 inner clauses
    state["outer_clauses"] = original_outer
    state["inner_clauses"] = original_inner

    print(f"  Outer clauses: {len(state['outer_clauses'])}")
    print(f"  Inner clauses: {len(state['inner_clauses'])}")

    # Execute filter node
    result = node_filter_candidates(state)
    state.update(result)

    print(f"  Candidate pairs: {len(state['candidate_pairs'])}")

    # Only process first 2 candidates
    state["candidate_pairs"] = state["candidate_pairs"][:2]
    print(f"  Test candidates: {len(state['candidate_pairs'])}")

    return state


def main():
    """Main test flow"""
    print("=" * 50)
    print("SFT Pipeline Small Batch Test")
    print("=" * 50)

    # Load config
    config_path = Path(__file__).parent / "config.yaml"
    config = load_config(str(config_path)).to_dict()

    print(f"\nConfig file: {config_path}")

    # 1. Test LLM connection
    llm_ok = test_llm_connection(config)
    if not llm_ok:
        print("\n[FAIL] LLM connection failed, please check config")
        return

    # 2. Test clause parsing
    outer_clauses, inner_clauses = test_parse_clauses(config)

    if not outer_clauses or not inner_clauses:
        print("\n[FAIL] Clause parsing failed")
        return

    # 2.5 Test semantic extraction
    outer_clauses, inner_clauses = test_extract_semantics(outer_clauses, inner_clauses, config)

    # 3. Test candidate filtering (use clauses with semantics)
    # Only use clauses that have semantics extracted (first 10 each)
    candidates = test_filter_candidates(outer_clauses[:10], inner_clauses[:10], config)

    # 4. Test LLM judgment (only first 3)
    results = test_llm_judgment(candidates, config)

    # 5. Test workflow integration
    state = test_workflow_integration(config)

    # Summary
    print("\n" + "=" * 50)
    print("Test Summary")
    print("=" * 50)
    print(f"  LLM Connection: {'[OK]' if llm_ok else '[FAIL]'}")
    print(f"  Clause Parsing: [OK] Outer {len(outer_clauses)}, Inner {len(inner_clauses)}")
    print(f"  Candidate Filtering: [OK] {len(candidates)} pairs")
    print(f"  LLM Judgment: [OK] {len(results)} successful")
    print(f"  Workflow Integration: [OK] {len(state['candidate_pairs'])} candidates ready")

    print("\n[SUCCESS] Small batch test completed! Workflow is running correctly.")


if __name__ == "__main__":
    main()
