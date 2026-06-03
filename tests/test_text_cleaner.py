from parser.text_cleaner import clean_text, clean_clause_text


def test_clean_text_removes_html():
    """测试移除 HTML 标签"""
    text = "<p>内容</p><br/>更多内容"
    result = clean_text(text)
    assert "<p>" not in result
    assert "</p>" not in result
    assert "内容更多内容" == result


def test_clean_text_removes_hyperlink():
    """测试移除 HYPERLINK 残留"""
    text = 'HYPERLINK "http://example.com" 链接文本'
    result = clean_text(text)
    assert "HYPERLINK" not in result
    assert "链接文本" in result


def test_clean_text_normalizes_whitespace():
    """测试规范化空白字符"""
    text = "多个   空格  和\n换行"
    result = clean_text(text)
    assert "   " not in result
    assert "\n" not in result


def test_clean_clause_text():
    """测试条款文本清洗"""
    text = 'HYPERLINK "url" 第一条 内容'
    result = clean_clause_text(text)
    assert "HYPERLINK" not in result
    assert result.startswith("第一条")
