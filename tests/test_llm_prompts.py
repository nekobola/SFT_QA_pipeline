from llm.prompts import build_judgment_prompt, JUDGMENT_PROMPT, REVIEW_PROMPT
from llm.parser import parse_judgment_response, parse_review_response


def test_build_judgment_prompt():
    """测试构建判定 Prompt"""
    prompt = build_judgment_prompt(
        outer_doc_title="商业银行法",
        outer_article_no="第四十条",
        outer_content="商业银行不得向关系人发放信用贷款",
        outer_subjects=["商业银行"],
        outer_objects=["信用贷款"],
        outer_biz_dims=["信贷管理"],
        outer_action="不得",
        outer_threshold="",
        inner_doc_title="信贷制度",
        inner_article_no="第十五条",
        inner_content="本行向关联方发放贷款应当审查",
        inner_subjects=["商业银行"],
        inner_objects=["贷款"],
        inner_biz_dims=["信贷管理"],
        inner_action="应当",
    )

    assert "商业银行法" in prompt
    assert "第四十条" in prompt
    assert "信贷制度" in prompt
    assert "第十五条" in prompt


def test_parse_judgment_response_json():
    """测试解析 JSON 格式的判定响应"""
    response = '''
    ```json
    {
      "label": "部分冲突",
      "confidence": 0.85,
      "reasoning": "判断依据",
      "key_evidence": ["证据1"],
      "conflict_details": {
        "conflict_type": "条件放宽",
        "description": "描述"
      }
    }
    ```
    '''

    result = parse_judgment_response(response)

    assert result["label"] == "部分冲突"
    assert result["confidence"] == 0.85
    assert result["reasoning"] == "判断依据"


def test_parse_judgment_response_plain_json():
    """测试解析纯 JSON 格式的判定响应"""
    response = '{"label": "完全符合", "confidence": 0.9, "reasoning": "依据", "key_evidence": [], "conflict_details": {"conflict_type": "无冲突", "description": "无"}}'

    result = parse_judgment_response(response)

    assert result["label"] == "完全符合"
    assert result["confidence"] == 0.9


def test_parse_review_response():
    """测试解析评审响应"""
    response = '''
    {
      "format_valid": true,
      "format_issues": [],
      "consistency_valid": false,
      "consistency_issues": ["问题1"],
      "score": 65,
      "passed": false,
      "feedback": "修改建议"
    }
    '''

    result = parse_review_response(response)

    assert result["format_valid"] is True
    assert result["score"] == 65
    assert result["passed"] is False
