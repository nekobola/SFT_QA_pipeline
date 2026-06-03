"""文本清洗工具，复用自图数据库 stage1_parse.py"""
import re


def clean_text(raw_content: str) -> str:
    """
    清洗文本：去除 HTML 标签、HYPERLINK 残留、多余空白

    复用自: cufrl-r-graph_v5/pipeline/stage1_parse.py 第 64-67 行
    """
    # 去除 HTML 标签
    text = re.sub(r"<[^>]+>", "", raw_content)
    # 去除 HYPERLINK 残留
    text = re.sub(r'HYPERLINK\s+"[^"]*"\s*', "", text)
    # 规范化空白字符（保留单个空格）
    text = re.sub(r"\s+", "", text).strip()
    return text


def clean_clause_text(raw_content: str) -> str:
    """
    清洗条款文本：保留必要的格式，适用于条款正文

    复用自: cufrl-r-graph_v5/pipeline/stage1_parse.py 第 168-171 行
    """
    text = raw_content
    # 移除 HYPERLINK 及其 URL
    text = re.sub(r'HYPERLINK\s*"[^"]*"\s*(?:\\t\s*)?', "", text)
    # 规范化空白为单个空格
    text = re.sub(r"\s+", " ", text).strip()
    return text
