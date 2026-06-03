"""LLM 客户端，复用自图数据库 stage2_extract.py"""
import os
import random
import time
from typing import Optional

from openai import OpenAI

from .rate_limiter import GlobalRateLimiter

# 全局客户端缓存
_cached_client: Optional[OpenAI] = None
_cached_config: Optional[dict] = None


def get_default_client() -> OpenAI:
    """获取默认 OpenAI 客户端（兼容 DashScope）"""
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    base_url = os.environ.get(
        "OPENAI_LLM_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    return OpenAI(api_key=api_key, base_url=base_url)


def get_client_with_config(api_key: str, base_url: str) -> OpenAI:
    """使用指定配置创建客户端"""
    return OpenAI(api_key=api_key, base_url=base_url)


def get_client_from_config(config: dict) -> OpenAI:
    """
    从配置获取客户端（优先使用配置文件中的 API Key）

    Args:
        config: 配置字典，包含 llm.api_key 和 llm.base_url

    Returns:
        OpenAI 客户端实例
    """
    global _cached_client, _cached_config

    llm_config = config.get("llm", {})

    # 检查是否可以使用缓存的客户端
    if _cached_client is not None and _cached_config == llm_config:
        return _cached_client

    # 优先使用配置文件中的 API Key，否则使用环境变量
    api_key = llm_config.get("api_key") or os.environ.get("DASHSCOPE_API_KEY", "")
    base_url = llm_config.get("base_url") or os.environ.get(
        "OPENAI_LLM_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    _cached_client = OpenAI(api_key=api_key, base_url=base_url)
    _cached_config = llm_config

    return _cached_client


def call_llm(
    prompt: str,
    model: str = "qwen-plus",
    client: Optional[OpenAI] = None,
) -> str:
    """
    调用 LLM API

    复用自: cufrl-r-graph_v5/pipeline/stage2_extract.py 第 74-86 行
    """
    if client is None:
        client = get_default_client()

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    return resp.choices[0].message.content or ""


def call_llm_with_retries(
    prompt: str,
    rate_limiter: GlobalRateLimiter,
    model: str = "qwen-plus",
    max_retries: int = 3,
    backoff_base: float = 0.5,
    backoff_mult: float = 2.0,
    backoff_max: float = 10.0,
    jitter: float = 0.1,
    client: Optional[OpenAI] = None,
) -> str:
    """
    带重试与指数退避的 LLM 调用

    复用自: cufrl-r-graph_v5/pipeline/stage2_extract.py 第 27-49 行
    """
    for attempt in range(max_retries):
        try:
            rate_limiter.wait()
            return call_llm(prompt, model=model, client=client)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = min(backoff_base * (backoff_mult ** attempt), backoff_max)
            delay += random.uniform(-jitter, jitter)
            delay = max(0, delay)
            print(f"    LLM 调用失败 (尝试 {attempt+1}/{max_retries}): {e}，{delay:.2f}s 后重试")
            time.sleep(delay)

    raise RuntimeError("call_llm_with_retries: 不应到达此处")
