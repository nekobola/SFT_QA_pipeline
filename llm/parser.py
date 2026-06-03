"""LLM 响应解析器"""
import json
import re


def _extract_json(text: str) -> str:
    """从 LLM 响应中提取 JSON，增强容错"""
    # 移除 markdown 代码块
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    raw = m.group(1) if m else text.strip()

    # 尝试找到最外层的 { ... }
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        return raw[start:end]

    return raw


def _validate_judgment_fields(obj: dict) -> list:
    """验证 judgment 必填字段，返回缺失/无效字段列表"""
    issues = []
    if not obj.get("label"):
        issues.append("label 缺失或为空")
    elif obj["label"] not in ["高度符合", "基本一致", "部分冲突", "直接冲突", "无关"]:
        issues.append(f"label 值无效: {obj['label']}")
    if "confidence" not in obj or not isinstance(obj.get("confidence"), (int, float)):
        issues.append("confidence 缺失或非数字")
    if not obj.get("reasoning"):
        issues.append("reasoning 缺失或为空")
    if not obj.get("key_evidence") or not isinstance(obj.get("key_evidence"), list):
        issues.append("key_evidence 缺失或非数组")
    elif len(obj.get("key_evidence", [])) == 0:
        issues.append("key_evidence 为空数组")
    cd = obj.get("conflict_details")
    if not cd or not isinstance(cd, dict):
        issues.append("conflict_details 缺失或非对象")
    elif not cd.get("conflict_type"):
        issues.append("conflict_details.conflict_type 缺失或为空")
    return issues


def parse_judgment_response(text: str) -> dict:
    """
    解析判定响应

    返回结构：
    {
        "label": str,
        "confidence": float,
        "reasoning": str,
        "key_evidence": list,
        "conflict_details": dict,
        "parse_error": bool,       # 新增：是否有解析错误
        "missing_fields": list,    # 新增：缺失/无效的字段
    }
    """
    raw = _extract_json(text)

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "label": "",
            "confidence": 0.0,
            "reasoning": "",
            "key_evidence": [],
            "conflict_details": {},
            "parse_error": True,
            "missing_fields": ["JSON 无法解析"],
        }

    # 验证必填字段
    missing = _validate_judgment_fields(obj)

    result = {
        "label": obj.get("label", ""),
        "confidence": float(obj.get("confidence", 0.0)),
        "reasoning": obj.get("reasoning", ""),
        "key_evidence": obj.get("key_evidence", []) if isinstance(obj.get("key_evidence"), list) else [],
        "conflict_details": obj.get("conflict_details", {}) if isinstance(obj.get("conflict_details"), dict) else {},
        "parse_error": len(missing) > 0,
        "missing_fields": missing,
    }

    # 验证 label 有效性
    valid_labels = ["高度符合", "基本一致", "部分冲突", "直接冲突", "无关"]
    if result["label"] not in valid_labels:
        result["label"] = ""
        result["parse_error"] = True
        missing.append(f"label 无效: {obj.get('label')}")

    # 验证 confidence 范围
    result["confidence"] = max(0.0, min(1.0, result["confidence"]))

    return result


def parse_review_response(text: str) -> dict:
    """
    解析评审响应

    返回结构：
    {
        "format_valid": bool,
        "format_issues": list,
        "consistency_valid": bool,
        "consistency_issues": list,
        "score": int,
        "passed": bool,
        "feedback": str,
        "corrected_result": dict | None,
    }
    """
    raw = _extract_json(text)

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "format_valid": False,
            "format_issues": ["JSON 解析失败"],
            "consistency_valid": False,
            "consistency_issues": [],
            "score": 0,
            "passed": False,
            "feedback": "判定结果 JSON 格式错误，无法解析",
        }

    return {
        "format_valid": obj.get("format_valid", False),
        "format_issues": obj.get("format_issues", []),
        "consistency_valid": obj.get("consistency_valid", False),
        "consistency_issues": obj.get("consistency_issues", []),
        "score": int(obj.get("score", 0)),
        "passed": obj.get("passed", False),
        "feedback": obj.get("feedback", ""),
        "corrected_result": obj.get("corrected_result"),
    }
