"""硬筛选"""


def check_hard_filter(similarity: dict, config: dict) -> bool:
    """
    检查是否通过硬筛选

    Args:
        similarity: 相似度字典
        config: 筛选配置，如 {"biz_dim_match": ">= 1"}

    Returns:
        True 如果通过所有硬筛选条件
    """
    for key, condition in config.items():
        value = similarity.get(key, 0)

        # 解析条件
        if condition.startswith(">="):
            threshold = int(condition[2:])
            if value < threshold:
                return False
        elif condition.startswith(">"):
            threshold = int(condition[1:])
            if value <= threshold:
                return False
        elif condition.startswith("=="):
            threshold = int(condition[2:])
            if value != threshold:
                return False

    return True
