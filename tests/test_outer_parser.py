import pytest
from pathlib import Path
import tempfile
from docx import Document
from parser.outer_parser import parse_outer_docx


def create_test_docx(filename: str, paragraphs: list[str]) -> Path:
    """创建测试用 DOCX 文件"""
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    path = Path(tempfile.gettempdir()) / filename
    doc.save(str(path))
    return path


def test_parse_outer_docx_basic():
    """测试基本外规解析"""
    path = create_test_docx(
        "《中华人民共和国商业银行法》.docx",
        [
            "第一章 总则",
            "第一条 为了保护商业银行的合法权益，制定本法。",
            "第二条 商业银行是吸收公众存款、发放贷款的金融机构。",
            "第二章 贷款",
            "第三条 贷款业务应当遵守相关规定。",
        ]
    )

    result = parse_outer_docx(path)

    assert "regulation" in result
    assert "clauses" in result
    assert result["regulation"]["title"] == "中华人民共和国商业银行法"
    assert len(result["clauses"]) == 3


def test_parse_outer_docx_chapter_structure():
    """测试章→条层级结构"""
    path = create_test_docx(
        "测试法规.docx",
        [
            "第一章 总则",
            "第一条 内容一",
            "第二条 内容二",
            "第二章 细则",
            "第三条 内容三",
        ]
    )

    result = parse_outer_docx(path)

    # 检查条款的章归属
    clauses = result["clauses"]
    assert clauses[0]["chapter_num"] == 1
    assert clauses[1]["chapter_num"] == 1
    assert clauses[2]["chapter_num"] == 2


def test_parse_outer_docx_sub_clauses():
    """测试条款下的款项"""
    path = create_test_docx(
        "测试法规.docx",
        [
            "第一条 主条款内容",
            "第一款 这是第一款的内容",
            "第二款 这是第二款的内容",
            "第二条 下一条",
        ]
    )

    result = parse_outer_docx(path)

    # 第一条应该有款项
    first_clause = result["clauses"][0]
    assert first_clause["sub_clauses"] is not None
    assert len(first_clause["sub_clauses"]) >= 1


def test_parse_outer_docx_metadata():
    """测试元数据提取"""
    path = create_test_docx(
        "测试法规.docx",
        [
            "中华人民共和国主席令第二十号",
            "2021年8月20日",
            "第一条 内容",
        ]
    )

    result = parse_outer_docx(path)

    reg = result["regulation"]
    assert reg["reference_no"] != "" or reg["publish_date"] != ""
