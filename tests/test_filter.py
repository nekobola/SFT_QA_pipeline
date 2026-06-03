from filter.similarity import compute_set_overlap, compute_similarity
from filter.hard_filter import check_hard_filter
from filter.soft_filter import compute_weighted_score


def test_compute_set_overlap():
    """测试集合重叠计算"""
    assert compute_set_overlap(["A", "B"], ["B", "C"]) == 1
    assert compute_set_overlap(["A", "B"], ["C", "D"]) == 0
    assert compute_set_overlap(["A", "B"], ["A", "B"]) == 2


def test_compute_similarity():
    """测试相似度计算"""
    outer = {
        "subjects": ["商业银行"],
        "objects": ["贷款"],
        "biz_dims": ["信贷管理"],
        "action": "不得",
    }
    inner = {
        "subjects": ["商业银行"],
        "objects": ["贷款"],
        "biz_dims": ["信贷管理"],
        "action": "应当",
    }

    result = compute_similarity(outer, inner)

    assert "biz_dim_match" in result
    assert "subject_match" in result
    assert result["subject_match"] == 1
    assert result["biz_dim_match"] == 1


def test_check_hard_filter():
    """测试硬筛选"""
    similarity = {
        "biz_dim_match": 1,
        "subject_match": 1,
    }
    config = {
        "biz_dim_match": ">= 1",
        "subject_match": ">= 1",
    }

    assert check_hard_filter(similarity, config) is True

    similarity["subject_match"] = 0
    assert check_hard_filter(similarity, config) is False


def test_compute_weighted_score():
    """测试加权评分"""
    similarity = {
        "biz_dim_match": 1,
        "subject_match": 1,
        "object_match": 0,
        "action_match": 0,
        "text_similarity": 0.5,
    }
    weights = {
        "biz_dim_match": 0.30,
        "subject_match": 0.25,
        "object_match": 0.25,
        "action_match": 0.10,
        "text_similarity": 0.10,
    }

    score = compute_weighted_score(similarity, weights)

    # 0.30*1 + 0.25*1 + 0.25*0 + 0.10*0 + 0.10*0.5 = 0.60
    assert abs(score - 0.60) < 0.01
