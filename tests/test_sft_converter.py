import json
from utils.sft_converter import convert_to_sft_format, SFT_INSTRUCTION


def test_sft_instruction():
    """测试 SFT 指令"""
    assert "银行业合规专家" in SFT_INSTRUCTION
    assert "完全符合" in SFT_INSTRUCTION


def test_convert_to_sft_format():
    """测试转换为 SFT 格式"""
    qa_pair = {
        "outer_clause": {
            "doc_title": "商业银行法",
            "article_no": "第四十条",
            "clause_text": "内容",
            "subjects": ["商业银行"],
            "objects": ["贷款"],
            "biz_dims": ["信贷管理"],
            "action": "不得",
        },
        "inner_clause": {
            "doc_title": "信贷制度",
            "article_no": "第十五条",
            "clause_text": "内容",
            "subjects": ["商业银行"],
            "objects": ["贷款"],
            "biz_dims": ["信贷管理"],
            "action": "应当",
        },
        "label": "部分冲突",
        "confidence": 0.85,
        "reasoning": "判断依据",
    }

    sft = convert_to_sft_format(qa_pair)

    assert "instruction" in sft
    assert "input" in sft
    assert "output" in sft

    # output 是 JSON 字符串，需要解析
    output_data = json.loads(sft["output"])
    assert output_data["label"] == "部分冲突"


def test_convert_to_sft_format_with_conflict_details():
    """测试包含冲突详情的转换"""
    qa_pair = {
        "outer_clause": {
            "doc_title": "监管规定",
            "article_no": "第十条",
            "clause_text": "银行不得向关系人发放信用贷款",
            "subjects": ["银行"],
            "objects": ["信用贷款"],
            "biz_dims": ["信贷管理"],
            "action": "不得",
        },
        "inner_clause": {
            "doc_title": "内部信贷制度",
            "article_no": "第二十条",
            "clause_text": "银行可以向关系人发放信用贷款，但需审批",
            "subjects": ["银行"],
            "objects": ["信用贷款"],
            "biz_dims": ["信贷管理"],
            "action": "可以",
        },
        "label": "直接冲突",
        "confidence": 0.95,
        "reasoning": "内规允许而外规禁止，存在直接矛盾",
        "conflict_details": {
            "conflict_type": "行为模态冲突",
            "conflict_fields": ["action"],
        },
    }

    sft = convert_to_sft_format(qa_pair)
    output_data = json.loads(sft["output"])

    assert output_data["label"] == "直接冲突"
    assert output_data["confidence"] == 0.95
    assert output_data["conflict_type"] == "行为模态冲突"


def test_convert_to_sft_format_no_conflict():
    """测试无冲突情况的转换"""
    qa_pair = {
        "outer_clause": {
            "doc_title": "监管规定",
            "article_no": "第五条",
            "clause_text": "银行应当建立风险管理制度",
            "subjects": ["银行"],
            "objects": ["风险管理制度"],
            "biz_dims": ["风险管理"],
            "action": "应当",
        },
        "inner_clause": {
            "doc_title": "内部制度",
            "article_no": "第三条",
            "clause_text": "本行建立全面风险管理制度",
            "subjects": ["银行"],
            "objects": ["风险管理制度"],
            "biz_dims": ["风险管理"],
            "action": "建立",
        },
        "label": "完全符合",
        "confidence": 0.90,
        "reasoning": "内规完全落实外规要求",
        "conflict_details": {
            "conflict_type": "无冲突",
        },
    }

    sft = convert_to_sft_format(qa_pair)
    output_data = json.loads(sft["output"])

    assert output_data["label"] == "完全符合"
    assert output_data["conflict_type"] == "无冲突"


def test_convert_to_sft_format_irrelevant():
    """测试无关情况的转换"""
    qa_pair = {
        "outer_clause": {
            "doc_title": "监管规定",
            "article_no": "第一条",
            "clause_text": "银行应当遵守本规定",
            "subjects": ["银行"],
            "objects": ["本规定"],
            "biz_dims": ["合规管理"],
            "action": "应当",
        },
        "inner_clause": {
            "doc_title": "内部制度",
            "article_no": "第一条",
            "clause_text": "本制度适用于全体员工",
            "subjects": ["员工"],
            "objects": ["本制度"],
            "biz_dims": ["人事管理"],
            "action": "适用",
        },
        "label": "无关",
        "confidence": 0.80,
        "reasoning": "内外规条款主题不相关",
    }

    sft = convert_to_sft_format(qa_pair)
    output_data = json.loads(sft["output"])

    assert output_data["label"] == "无关"
    assert output_data["conflict_type"] == "无冲突"


def test_convert_to_sft_format_missing_fields():
    """测试缺失字段的情况"""
    qa_pair = {
        "outer_clause": {
            "doc_title": "监管规定",
        },
        "inner_clause": {
            "doc_title": "内部制度",
        },
        "label": "基本一致",
        "confidence": 0.75,
    }

    sft = convert_to_sft_format(qa_pair)
    output_data = json.loads(sft["output"])

    assert output_data["label"] == "基本一致"
    assert output_data["confidence"] == 0.75
    assert output_data["reasoning"] == ""
    assert output_data["conflict_type"] == "无冲突"


def test_convert_to_sft_input_structure():
    """测试 input 结构正确性"""
    qa_pair = {
        "outer_clause": {
            "doc_title": "外规标题",
            "article_no": "第十条",
            "clause_text": "外规内容",
            "subjects": ["主体A", "主体B"],
            "objects": ["客体A"],
            "biz_dims": ["业务维度A"],
            "action": "应当",
        },
        "inner_clause": {
            "doc_title": "内规标题",
            "article_no": "第二十条",
            "clause_text": "内规内容",
            "subjects": ["主体C"],
            "objects": ["客体B", "客体C"],
            "biz_dims": ["业务维度B"],
            "action": "不得",
        },
        "label": "部分冲突",
        "confidence": 0.85,
        "reasoning": "判断依据",
    }

    sft = convert_to_sft_format(qa_pair)

    input_data = json.loads(sft["input"])

    # 验证 outer_clause
    assert input_data["outer_clause"]["doc_title"] == "外规标题"
    assert input_data["outer_clause"]["article_no"] == "第十条"
    assert input_data["outer_clause"]["content"] == "外规内容"
    assert input_data["outer_clause"]["subjects"] == ["主体A", "主体B"]
    assert input_data["outer_clause"]["objects"] == ["客体A"]
    assert input_data["outer_clause"]["biz_dims"] == ["业务维度A"]
    assert input_data["outer_clause"]["action"] == "应当"

    # 验证 inner_clause
    assert input_data["inner_clause"]["doc_title"] == "内规标题"
    assert input_data["inner_clause"]["article_no"] == "第二十条"
    assert input_data["inner_clause"]["content"] == "内规内容"
    assert input_data["inner_clause"]["subjects"] == ["主体C"]
    assert input_data["inner_clause"]["objects"] == ["客体B", "客体C"]
    assert input_data["inner_clause"]["biz_dims"] == ["业务维度B"]
    assert input_data["inner_clause"]["action"] == "不得"


def test_convert_to_sft_output_is_json_string():
    """测试 output 是有效的 JSON 字符串"""
    qa_pair = {
        "outer_clause": {
            "doc_title": "监管规定",
            "article_no": "第十条",
            "clause_text": "内容",
            "subjects": ["银行"],
            "objects": ["贷款"],
            "biz_dims": ["信贷管理"],
            "action": "不得",
        },
        "inner_clause": {
            "doc_title": "内部制度",
            "article_no": "第二十条",
            "clause_text": "内容",
            "subjects": ["银行"],
            "objects": ["贷款"],
            "biz_dims": ["信贷管理"],
            "action": "应当",
        },
        "label": "部分冲突",
        "confidence": 0.85,
        "reasoning": "判断依据",
    }

    sft = convert_to_sft_format(qa_pair)

    # 验证 output 是字符串
    assert isinstance(sft["output"], str)

    # 验证可以被解析为 JSON
    output_data = json.loads(sft["output"])
    assert isinstance(output_data, dict)

    # 验证必要字段存在
    assert "label" in output_data
    assert "confidence" in output_data
    assert "reasoning" in output_data
    assert "conflict_type" in output_data
