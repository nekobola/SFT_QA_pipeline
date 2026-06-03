"""条件边"""


def should_retry(state: dict) -> str:
    """
    判断是否打回重做（已废弃，保留兼容）

    Returns:
        "retry" - 打回重做
        "next" - 继续下一步
    """
    review_result = state.get("review_result", {})
    retry_count = state.get("retry_count", 0)
    config = state.get("config", {})

    review_config = config.get("review", {})
    pass_threshold = review_config.get("pass_threshold", 70)
    max_retries = review_config.get("max_retries", 2)

    # 评审通过
    if review_result.get("passed") and review_result.get("score", 0) >= pass_threshold:
        print(f"[Condition] should_retry → next (passed, score={review_result.get('score')})", flush=True)
        return "next"

    # 还可重试
    if retry_count < max_retries:
        print(f"[Condition] should_retry → retry (retry_count={retry_count}, max={max_retries})", flush=True)
        return "retry"

    # 重试耗尽
    print(f"[Condition] should_retry → next (exhausted retries)", flush=True)
    return "next"


def should_continue(state: dict) -> str:
    """
    判断是否继续处理下一个候选对

    Returns:
        "judge" - 继续判定（下一个候选对或重试）
        "split" - 进入数据集划分
    """
    candidate_idx = state.get("candidate_idx", 0)
    candidate_pairs = state.get("candidate_pairs", [])
    need_retry = state.get("need_retry", False)

    # 如果需要重试，回到 judge
    if need_retry:
        print(f"[Condition] should_continue → judge (retry needed)", flush=True)
        return "judge"

    # 如果所有候选对都处理完，进入 split
    if candidate_idx >= len(candidate_pairs):
        print(f"[Condition] should_continue → split (idx={candidate_idx}, total={len(candidate_pairs)})", flush=True)
        return "split"

    # 否则继续下一个候选对
    print(f"[Condition] should_continue → judge (idx={candidate_idx}/{len(candidate_pairs)})", flush=True)
    return "judge"
