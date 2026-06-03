"""测试外规 JSON 解析器"""
import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from parser.outer_json_parser import OuterJsonParser, parse_outer_json


def _write_temp_json(data: dict) -> Path:
    """写入临时 JSON 文件并返回路径"""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False)
    tmp.close()
    return Path(tmp.name)


def _sample_statute(title="测试法规", num_articles=3):
    """构造一个简单的法规 dict 用于测试"""
    paragraphs = []
    for i in range(1, num_articles + 1):
        paragraphs.append({
            "paragraphId": 1000 + i,
            "content": f"<p><strong class=\"prominent\">第{i}条</strong> 测试条款内容{i}</p>",
            "groupId": (i + 1) * 1000,
            "sort": i + 10,
            "num": i,
            "type": "条",
            "status": "Effective",
            "state": 1,
        })
    return {
        "statuteId": "abc123def456",
        "title": title,
        "referenceNo": "测试文号 第1号",
        "organizationName": "测试机构",
        "publishdate": "2024-01-01 00:00:00",
        "implementdate": "2024-01-01 00:00:00",
        "status": "Effective",
        "categoryStr": "测试-分类",
        "paragraphInfos": paragraphs,
    }


class TestOuterJsonParser:

    def test_parse_basic_statute(self):
        """测试：仅含"条"的法规 → 验证 clause 数量和格式"""
        statute = _sample_statute("测试法规", num_articles=3)
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            assert len(clauses) == 3
            for i, c in enumerate(clauses):
                assert c["source"] == "外规"
                assert c["doc_title"] == "测试法规"
                assert c["statute_id"] == "abc123def456"
                assert c["article_no"] == f"第{i+1}条"
                assert c["uid"] == f"第{i+1}条_测试法规"
                assert f"测试条款内容{i+1}" in c["clause_text"]
                assert c["subjects"] == []
                assert c["objects"] == []
                assert c["biz_dims"] == []
                assert c["action"] is None
        finally:
            path.unlink(missing_ok=True)

    def test_parse_with_chapters(self):
        """测试：含章/条的法规 → 验证 chapter_num"""
        statute = {
            "statuteId": "chapter_test",
            "title": "含章法规",
            "referenceNo": "",
            "organizationName": "",
            "publishdate": "",
            "implementdate": "",
            "status": "Effective",
            "categoryStr": "",
            "paragraphInfos": [
                {"paragraphId": 1, "content": "<p>第一章 总则</p>", "groupId": 10000, "sort": 1, "num": 1, "type": "章", "status": "Effective", "state": 1},
                {"paragraphId": 2, "content": "<p><strong>第一条</strong> 总则条款一</p>", "groupId": 2000, "sort": 2, "num": 1, "type": "条", "status": "Effective", "state": 1},
                {"paragraphId": 3, "content": "<p>第二章 业务</p>", "groupId": 20000, "sort": 3, "num": 2, "type": "章", "status": "Effective", "state": 1},
                {"paragraphId": 4, "content": "<p><strong>第二条</strong> 业务条款一</p>", "groupId": 3000, "sort": 4, "num": 2, "type": "条", "status": "Effective", "state": 1},
                {"paragraphId": 5, "content": "<p><strong>第三条</strong> 业务条款二</p>", "groupId": 4000, "sort": 5, "num": 3, "type": "条", "status": "Effective", "state": 1},
            ],
        }
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            assert len(clauses) == 3
            # 第一条在第一章
            assert clauses[0]["chapter_num"] == 1
            assert clauses[0]["article_no"] == "第1条"
            # 第二、三条在第二章
            assert clauses[1]["chapter_num"] == 2
            assert clauses[2]["chapter_num"] == 2
        finally:
            path.unlink(missing_ok=True)

    def test_parse_with_kuan(self):
        """测试：含款的法规 → 款作为独立 clause"""
        statute = {
            "statuteId": "kuan_test",
            "title": "含款法规",
            "referenceNo": "",
            "organizationName": "",
            "publishdate": "",
            "implementdate": "",
            "status": "Effective",
            "categoryStr": "",
            "paragraphInfos": [
                {"paragraphId": 1, "content": "<p><strong>第一条</strong> 某条款</p>", "groupId": 2000, "sort": 1, "num": 1, "type": "条", "status": "Effective", "state": 1},
                {"paragraphId": 2, "content": "<p>（一）子项内容A</p>", "groupId": 3000, "sort": 2, "num": 1, "type": "款", "status": "Effective", "state": 1},
                {"paragraphId": 3, "content": "<p>（二）子项内容B</p>", "groupId": 4000, "sort": 3, "num": 2, "type": "款", "status": "Effective", "state": 1},
            ],
        }
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            assert len(clauses) == 3
            # 款作为独立 clause
            assert clauses[0]["article_no"] == "第1条"
            assert clauses[1]["article_no"] == "第1款"
            assert clauses[2]["article_no"] == "第2款"
        finally:
            path.unlink(missing_ok=True)

    def test_parse_with_sub_clauses(self):
        """测试：同 groupId 的 "" 段落归为 sub_clauses"""
        statute = {
            "statuteId": "sub_test",
            "title": "含子条款法规",
            "referenceNo": "",
            "organizationName": "",
            "publishdate": "",
            "implementdate": "",
            "status": "Effective",
            "categoryStr": "",
            "paragraphInfos": [
                {"paragraphId": 1, "content": "<p><strong>第一条</strong> 主条款</p>", "groupId": 2000, "sort": 1, "num": 1, "type": "条", "status": "Effective", "state": 1},
                # 续文段落（同 groupId, type=""）
                {"paragraphId": 2, "content": "<p>续文段落A</p>", "groupId": 2000, "sort": 2, "num": None, "type": "", "status": "Effective", "state": 1},
                {"paragraphId": 3, "content": "<p>续文段落B</p>", "groupId": 2000, "sort": 3, "num": None, "type": "", "status": "Effective", "state": 1},
            ],
        }
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            assert len(clauses) == 1
            c = clauses[0]
            assert c["article_no"] == "第1条"
            assert c["sub_clauses"] is not None
            assert len(c["sub_clauses"]) == 2
            assert c["sub_clauses"][0]["content"] == "续文段落A"
            assert c["sub_clauses"][1]["content"] == "续文段落B"
            assert c["sub_clauses"][0]["num"] == 1
            assert c["sub_clauses"][1]["num"] == 2
        finally:
            path.unlink(missing_ok=True)

    def test_html_cleaning(self):
        """测试：HTML 内容被正确清洗"""
        statute = {
            "statuteId": "html_test",
            "title": "HTML测试",
            "referenceNo": "",
            "organizationName": "",
            "publishdate": "",
            "implementdate": "",
            "status": "Effective",
            "categoryStr": "",
            "paragraphInfos": [
                {"paragraphId": 1, "content": "<p><strong class=\"prominent\">第一条</strong> 为了规范<em>相关活动</em>，保护投资者<strong>合法权益</strong>。</p>", "groupId": 2000, "sort": 1, "num": 1, "type": "条", "status": "Effective", "state": 1},
            ],
        }
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            c = clauses[0]
            # HTML 标签应被清洗
            assert "<strong" not in c["clause_text"]
            assert "<p>" not in c["clause_text"]
            # 文本内容应保留
            assert "为了规范" in c["clause_text"]
            assert "相关活动" in c["clause_text"]
            assert "合法权益" in c["clause_text"]
        finally:
            path.unlink(missing_ok=True)

    def test_uid_format(self):
        """测试：uid 格式为 第X条_title"""
        statute = _sample_statute("银行业监督管理法", num_articles=1)
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            assert clauses[0]["uid"] == "第1条_银行业监督管理法"
        finally:
            path.unlink(missing_ok=True)

    def test_skips_preamble(self):
        """测试：前导段落（groupId < 2000）被跳过"""
        statute = {
            "statuteId": "preamble_test",
            "title": "含前导法规",
            "referenceNo": "",
            "organizationName": "",
            "publishdate": "",
            "implementdate": "",
            "status": "Effective",
            "categoryStr": "",
            "paragraphInfos": [
                {"paragraphId": 1, "content": "<p>发布公告文字</p>", "groupId": 400, "sort": 1, "num": None, "type": "", "status": "Effective", "state": 1},
                {"paragraphId": 2, "content": "<p>签署人</p>", "groupId": 800, "sort": 2, "num": None, "type": "", "status": "Effective", "state": 1},
                {"paragraphId": 3, "content": "<p>日期</p>", "groupId": 1200, "sort": 3, "num": None, "type": "", "status": "Effective", "state": 1},
                {"paragraphId": 4, "content": "<p>法规标题</p>", "groupId": 1600, "sort": 4, "num": None, "type": "", "status": "Effective", "state": 1},
                {"paragraphId": 5, "content": "<p><strong>第一条</strong> 正式条款</p>", "groupId": 2000, "sort": 5, "num": 1, "type": "条", "status": "Effective", "state": 1},
            ],
        }
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            assert len(clauses) == 1
            assert clauses[0]["article_no"] == "第1条"
        finally:
            path.unlink(missing_ok=True)

    def test_metadata_fields(self):
        """测试：元数据字段正确填充"""
        statute = _sample_statute("元数据测试")
        statute["referenceNo"] = "银监会令 第5号"
        statute["organizationName"] = "中国银监会"
        statute["publishdate"] = "2023-06-15 00:00:00"
        statute["implementdate"] = "2023-07-01 00:00:00"
        statute["categoryStr"] = "银行监管-信贷业务"
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            c = clauses[0]
            assert c["reference_no"] == "银监会令 第5号"
            assert c["org_name"] == "中国银监会"
            assert c["publish_date"] == "2023-06-15 00:00:00"
            assert c["implement_date"] == "2023-07-01 00:00:00"
            assert c["status"] == "Effective"
            assert c["category"] == "银行监管-信贷业务"
        finally:
            path.unlink(missing_ok=True)

    def test_empty_statute(self):
        """测试：无条款的法规不产生 clause"""
        statute = _sample_statute("空法规", num_articles=0)
        statute["paragraphInfos"] = []
        data = {"total": 1, "statuteList": [statute]}
        path = _write_temp_json(data)

        try:
            clauses = parse_outer_json(path)
            assert len(clauses) == 0
        finally:
            path.unlink(missing_ok=True)

    def test_file_not_found(self):
        """测试：文件不存在时抛异常"""
        import pytest
        with pytest.raises(FileNotFoundError):
            parse_outer_json(Path("/nonexistent/path.json"))

    def test_real_data_spot_check(self):
        """测试：用真实 JSON 做抽查（如果文件存在）"""
        real_path = Path(__file__).parent.parent / "data" / "outer" / "full_outer_data.json"
        if not real_path.exists():
            import pytest
            pytest.skip("真实数据文件不存在，跳过抽查")

        clauses = parse_outer_json(real_path)
        assert len(clauses) > 0

        # 验证每个 clause 有必需字段
        for c in clauses[:100]:
            assert "source" in c
            assert c["source"] == "外规"
            assert "doc_title" in c
            assert "statute_id" in c
            assert "uid" in c
            assert "article_no" in c
            assert "clause_text" in c
            assert isinstance(c["subjects"], list)
            assert isinstance(c["objects"], list)
            assert isinstance(c["biz_dims"], list)
            assert "clause_text" in c and len(c["clause_text"]) > 0

        # 验证统计量级合理
        print(f"\n解析到 {len(clauses)} 条 clause（来自真实数据）")
        # 应该大约在 15万左右（134,231条 条 + 14,891条 款 = 149,122）
        assert 130000 <= len(clauses) <= 200000, f"预期 ~150k clauses，实际 {len(clauses)}"
