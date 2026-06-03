"""冲突场景生成器 - 基于匹配条款对生成冲突场景QA"""
import json
from typing import Optional

from openai import OpenAI

from .rate_limiter import GlobalRateLimiter
from .prompts import build_conflict_generation_prompt


def parse_conflict_response(response: str) -> dict:
    """
    解析冲突场景生成响应

    Args:
        response: LLM 原始响应字符串

    Returns:
        解析后的字典，包含 conflict_scenario, conflict_type, qa_pair 等字段
    """
    # 尝试提取 JSON
    response = response.strip()

    # 移除可能的 markdown 代码块标记
    if response.startswith("```"):
        lines = response.split("\n")
        # 移除首行
        if lines[0].startswith("```"):
            lines = lines[1:]
        # 移除尾行
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response = "\n".join(lines).strip()

    try:
        result = json.loads(response)
        return result
    except json.JSONDecodeError:
        # 尝试修复常见问题
        # 1. 尝试找到 JSON 对象边界
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(response[start:end])
                return result
            except json.JSONDecodeError:
                pass

        return {
            "error": "无法解析响应",
            "raw_response": response,
        }


def generate_conflict_qa(
    outer_clause: dict,
    inner_clause: dict,
    original_label: str,
    reasoning: str,
    client: OpenAI,
    rate_limiter: GlobalRateLimiter,
    model: str = "qwen-plus",
    max_retries: int = 2,
) -> Optional[dict]:
    """
    基于匹配pair生成冲突场景QA

    Args:
        outer_clause: 外规条款
        inner_clause: 内规条款
        original_label: 原始判断标签
        reasoning: 原始判断理由
        client: OpenAI 客户端
        rate_limiter: 限流器
        model: 模型名称
        max_retries: 最大重试次数

    Returns:
        成功: {
            "id": "conflict_xxx",
            "instruction": "合规问题",
            "input": "场景描述 + 条款信息",
            "output": "合规分析答案",
            "conflict_type": "部分冲突|直接冲突",
            "conflict_scenario": "场景描述",
            "source_pair_id": "原始pair ID",
        }
        失败: None
    """
    # 构建冲突生成 Prompt
    prompt = build_conflict_generation_prompt(
        outer_doc_title=outer_clause.get("doc_title", ""),
        outer_article_no=outer_clause.get("article_no", ""),
        outer_content=outer_clause.get("clause_text", ""),
        inner_doc_title=inner_clause.get("doc_title", ""),
        inner_article_no=inner_clause.get("article_no", ""),
        inner_content=inner_clause.get("clause_text", ""),
        original_label=original_label,
        reasoning=reasoning,
    )

    # 调用 LLM（带重试）
    for attempt in range(max_retries + 1):
        try:
            rate_limiter.wait()
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,  # 稍高温度以获得更多样化的场景
            )
            response_text = resp.choices[0].message.content or ""
            result = parse_conflict_response(response_text)

            # 验证结果
            if "error" in result:
                if attempt < max_retries:
                    continue
                return None

            # 构建最终 QA 格式
            qa_pair = result.get("qa_pair", {})
            conflict_type = result.get("conflict_type", "部分冲突")
            conflict_scenario = result.get("conflict_scenario", "")

            # 如果 qa_pair 字段不完整，手动构建
            if not qa_pair.get("instruction"):
                qa_pair = {
                    "instruction": "基于以下场景，判断内规条款是否与外规条款存在冲突？",
                    "input": f"场景：{conflict_scenario}\n\n外规条款：{outer_clause.get('clause_text', '')}\n\n内规条款：{inner_clause.get('clause_text', '')}",
                    "output": result.get("conflict_reason", ""),
                }

            return {
                "id": f"conflict_{outer_clause.get('uid', '')}_{inner_clause.get('uid', '')}",
                "instruction": qa_pair.get("instruction", ""),
                "input": qa_pair.get("input", ""),
                "output": qa_pair.get("output", ""),
                "label": conflict_type,            # 统一用 label 字段
                "conflict_type": conflict_type,
                "conflict_scenario": conflict_scenario,
                "source_pair_id": f"{outer_clause.get('uid', '')}_{inner_clause.get('uid', '')}",
                "outer_clause": outer_clause,
                "inner_clause": inner_clause,
            }

        except Exception as e:
            if attempt < max_retries:
                continue
            print(f"[ConflictGenerator] 生成失败: {e}")
            return None

    return None
