"""语义要素提取器，复用自图数据库 stage2_extract.py"""
import json
import re
from typing import Optional
from pathlib import Path

from openai import OpenAI

from llm.rate_limiter import GlobalRateLimiter


# 实体抽取 Prompt（复用自 stage2_extract.py）
EXTRACT_PROMPT = """你是银行业法律法规分析专家。请从以下条款中抽取三类实体：

1. 法律主体(Subject)：行为主体或被约束对象
   例：商业银行、借款人、银保监会、董事会
2. 法律客体(Object)：涉及的业务对象或事物
   例：贷款、个人信息、不良资产、风险准备金
3. 业务维度(BizDim)：所属业务领域
   例：信贷管理、反洗钱、公司治理、信息披露

条款内容：
{clause_text}

请严格以JSON格式输出，不要输出其他内容：
{{"subjects": ["实体1", "实体2"], "objects": ["实体1"], "biz_dims": ["维度1"], "action": "应当|不得|可以|禁止|null"}}
"""


def extract_semantic_elements(
    clause_text: str,
    model: str = "qwen-plus",
    client: Optional[OpenAI] = None,
    rate_limiter: Optional[GlobalRateLimiter] = None,
) -> dict:
    """
    从条款文本中提取语义要素

    Args:
        clause_text: 条款文本
        model: LLM 模型名称
        client: OpenAI 客户端
        rate_limiter: 限流器

    Returns:
        {
            "subjects": list[str],
            "objects": list[str],
            "biz_dims": list[str],
            "action": str | None
        }
    """
    if not clause_text or not clause_text.strip():
        return {"subjects": [], "objects": [], "biz_dims": [], "action": None}

    prompt = EXTRACT_PROMPT.format(clause_text=clause_text)

    try:
        if rate_limiter:
            rate_limiter.wait()

        if client is None:
            from .client import get_default_client
            client = get_default_client()

        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = resp.choices[0].message.content or ""

        return parse_extract_response(content)

    except Exception as e:
        print(f"    [Extract Error] {e}")
        return {"subjects": [], "objects": [], "biz_dims": [], "action": None}


def parse_extract_response(response: str) -> dict:
    """
    解析 LLM 响应，提取语义要素

    Args:
        response: LLM 响应文本

    Returns:
        语义要素字典
    """
    result = {
        "subjects": [],
        "objects": [],
        "biz_dims": [],
        "action": None,
    }

    # 尝试提取 JSON
    try:
        # 查找 JSON 块
        json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            result["subjects"] = data.get("subjects", []) or []
            result["objects"] = data.get("objects", []) or []
            result["biz_dims"] = data.get("biz_dims", []) or []
            result["action"] = data.get("action")

            # 确保 action 为有效值
            valid_actions = {"应当", "不得", "可以", "禁止", "必须", "应该"}
            if result["action"] and result["action"] not in valid_actions:
                # 尝试从文本中推断
                if "不得" in response or "禁止" in response:
                    result["action"] = "不得"
                elif "应当" in response or "应该" in response:
                    result["action"] = "应当"
                elif "可以" in response:
                    result["action"] = "可以"
                else:
                    result["action"] = None

    except json.JSONDecodeError:
        # 尝试正则提取
        subjects = re.findall(r'"subjects"\s*:\s*\[(.*?)\]', response, re.DOTALL)
        if subjects:
            result["subjects"] = [s.strip('" ') for s in subjects[0].split(",") if s.strip()]

        objects = re.findall(r'"objects"\s*:\s*\[(.*?)\]', response, re.DOTALL)
        if objects:
            result["objects"] = [s.strip('" ') for s in objects[0].split(",") if s.strip()]

        biz_dims = re.findall(r'"biz_dims"\s*:\s*\[(.*?)\]', response, re.DOTALL)
        if biz_dims:
            result["biz_dims"] = [s.strip('" ') for s in biz_dims[0].split(",") if s.strip()]

    # 确保所有字段都是列表
    if not isinstance(result["subjects"], list):
        result["subjects"] = []
    if not isinstance(result["objects"], list):
        result["objects"] = []
    if not isinstance(result["biz_dims"], list):
        result["biz_dims"] = []

    return result


def extract_action_from_text(text: str) -> Optional[str]:
    """
    从文本中直接提取行为模态（不调用 LLM）

    Args:
        text: 条款文本

    Returns:
        行为模态字符串或 None
    """
    # 按优先级匹配
    patterns = [
        (r"不得", "不得"),
        (r"禁止", "禁止"),
        (r"必须", "必须"),
        (r"应当", "应当"),
        (r"应该", "应当"),
        (r"可以", "可以"),
    ]

    for pattern, action in patterns:
        if re.search(pattern, text):
            return action

    return None


def batch_extract_semantics(
    clauses: list[dict],
    model: str = "qwen-plus",
    client: Optional[OpenAI] = None,
    rate_limiter: Optional[GlobalRateLimiter] = None,
    concurrency: int = 3,
    normalizer: Optional["SynonymNormalizer"] = None,
) -> list[dict]:
    """
    批量提取条款的语义要素（并发版本）

    Args:
        clauses: 条款列表
        model: LLM 模型
        client: OpenAI 客户端
        rate_limiter: 限流器
        concurrency: 并发数
        normalizer: 同义词归一化器（可选）

    Returns:
        更新后的条款列表
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from tqdm import tqdm

    def extract_one(clause: dict) -> dict:
        clause_text = clause.get("clause_text", "")
        if not clause_text:
            return clause

        semantics = extract_semantic_elements(
            clause_text,
            model=model,
            client=client,
            rate_limiter=rate_limiter,
        )

        clause["subjects"] = semantics["subjects"]
        clause["objects"] = semantics["objects"]
        clause["biz_dims"] = semantics["biz_dims"]

        if semantics["action"]:
            clause["action"] = semantics["action"]
        else:
            clause["action"] = extract_action_from_text(clause_text)

        return clause

    # 过滤空文本条款（无需 LLM 调用）
    empty_clauses = []
    nonempty_clauses = []
    for c in clauses:
        if c.get("clause_text", "").strip():
            nonempty_clauses.append(c)
        else:
            empty_clauses.append(c)

    if not nonempty_clauses:
        return clauses

    results = [None] * len(nonempty_clauses)
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_idx = {
            executor.submit(extract_one, clause): i
            for i, clause in enumerate(nonempty_clauses)
        }
        for future in tqdm(as_completed(future_to_idx), total=len(nonempty_clauses), desc="Extracting semantics"):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                print(f"    [Extract Error] clause {idx}: {e}")
                results[idx] = nonempty_clauses[idx]

    updated = [r for r in results if r is not None] + empty_clauses

    # 应用同义词归一化
    if normalizer and normalizer.is_loaded():
        for clause in updated:
            normalizer.normalize_clause(clause)

    return updated
