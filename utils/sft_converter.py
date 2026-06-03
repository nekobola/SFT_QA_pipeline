"""SFT 格式转换"""
import json


SFT_INSTRUCTION = """你是银行业合规专家，负责判断内规条款与外规条款的匹配关系。请根据条款内容和语义要素判断两者的关系，并以JSON格式输出结果。

判断标准：
1. 完全符合：内规条款完全落实外规要求，语义要素完全对应
2. 基本一致：内规条款落实外规要求，但存在非实质性差异
3. 部分冲突：内规条款与外规存在部分不一致，某些语义要素冲突
4. 直接冲突：内规条款与外规要求直接矛盾，行为模态相反或阈值突破
5. 无关：内规与外规条款无对应关系

输出格式：
{"label": "标签", "confidence": 0.0-1.0, "reasoning": "判断依据", "conflict_type": "冲突类型"}"""


def convert_to_sft_format(qa_pair: dict) -> dict:
    """
    将完整 QA 对转换为 SFT 训练格式

    Args:
        qa_pair: 完整记录格式的 QA 对

    Returns:
        SFT 训练格式 {"instruction": ..., "input": ..., "output": ...}
    """
    outer = qa_pair.get("outer_clause", {})
    inner = qa_pair.get("inner_clause", {})

    # 构建 input
    input_data = {
        "outer_clause": {
            "doc_title": outer.get("doc_title", ""),
            "article_no": outer.get("article_no", ""),
            "content": outer.get("clause_text", outer.get("content", "")),
            "subjects": outer.get("subjects", []),
            "objects": outer.get("objects", []),
            "biz_dims": outer.get("biz_dims", []),
            "action": outer.get("action", ""),
        },
        "inner_clause": {
            "doc_title": inner.get("doc_title", ""),
            "article_no": inner.get("article_no", ""),
            "content": inner.get("clause_text", inner.get("content", "")),
            "subjects": inner.get("subjects", []),
            "objects": inner.get("objects", []),
            "biz_dims": inner.get("biz_dims", []),
            "action": inner.get("action", ""),
        }
    }

    # 构建 output
    conflict_details = qa_pair.get("conflict_details", {})
    conflict_type = conflict_details.get("conflict_type", "无冲突")
    if qa_pair.get("label") in ["无关", "完全符合"]:
        conflict_type = "无冲突"

    output_data = {
        "label": qa_pair.get("label", ""),
        "confidence": qa_pair.get("confidence", 0.0),
        "reasoning": qa_pair.get("reasoning", ""),
        "conflict_type": conflict_type,
    }

    return {
        "instruction": SFT_INSTRUCTION,
        "input": json.dumps(input_data, ensure_ascii=False),
        "output": json.dumps(output_data, ensure_ascii=False),
    }


def convert_dataset_to_sft(qa_pairs: list[dict]) -> list[dict]:
    """批量转换数据集"""
    return [convert_to_sft_format(qa) for qa in qa_pairs]
