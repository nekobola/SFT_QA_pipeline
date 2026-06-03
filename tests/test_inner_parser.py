import pytest
from pathlib import Path
import tempfile
from docx import Document
from parser.inner_parser import parse_inner_docx


def create_test_docx(filename: str, paragraphs: list[str]) -> Path:
    """创建测试用 DOCX 文件"""
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    path = Path(tempfile.gettempdir()) / filename
    doc.save(str(path))
    return path


def test_parse_inner_docx_basic():
    """测试基本内规解析"""
    path = create_test_docx(
        "《测试制度》.docx",
        [
            "第一条 为了规范管理，制定本制度。",
            "第二条 本制度适用于全行。",
            "第三条 其他事项按相关规定执行。",
        ]
    )

    clauses = parse_inner_docx(path)

    assert len(clauses) == 3
    assert clauses[0]["article_no"] == "第一条"
    assert "规范管理" in clauses[0]["clause_text"]
    assert clauses[0]["source"] == "内规"


def test_parse_inner_docx_title_extraction():
    """测试从文件名提取标题"""
    path = create_test_docx(
        "某银行规章〔2025〕1号《某商业银行章程》.docx",
        ["第一条 内容"]
    )

    clauses = parse_inner_docx(path)

    assert clauses[0]["doc_title"] == "某商业银行章程"


def test_parse_inner_docx_skip_attachment():
    """测试跳过附件部分"""
    path = create_test_docx(
        "测试.docx",
        [
            "第一条 正文内容",
            "附件一",
            "附表格式",
        ]
    )

    clauses = parse_inner_docx(path)

    assert len(clauses) == 1
    assert clauses[0]["article_no"] == "第一条"


def test_parse_inner_docx_multi_line_clause():
    """测试多行条款内容"""
    path = create_test_docx(
        "测试.docx",
        [
            "第一条 这是第一条的内容",
            "这是第一条的续行",
            "第二条 这是第二条的内容",
        ]
    )

    clauses = parse_inner_docx(path)

    assert len(clauses) == 2
    assert "续行" in clauses[0]["clause_text"]
