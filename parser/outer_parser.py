"""外规 DOCX 解析器，复用自图数据库 stage1_parse.py"""
import re
from pathlib import Path
from docx import Document
from typing import Optional
from hashlib import md5

from .base import BaseParser
from .text_cleaner import clean_clause_text


class OuterParser(BaseParser):
    """外规 DOCX 解析器"""

    # 章号匹配正则
    CHAPTER_PATTERN = re.compile(r"^第[一二三四五六七八九十百零\d]+章")
    # 条号匹配正则
    ARTICLE_PATTERN = re.compile(r"^第[一二三四五六七八九十百零\d]+条")

    def parse(self, file_path: Path) -> dict:
        """解析外规 DOCX 文件，返回 {regulation, clauses}"""
        file_path = Path(file_path)
        if file_path.suffix.lower() != ".docx":
            raise ValueError(f"仅支持 .docx，当前文件: {file_path.name}")

        # 提取标题
        title = self.extract_title_from_filename(file_path.name)

        # 读取文档
        doc = Document(str(file_path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

        # 识别层级结构
        structure = self._identify_structure(paragraphs)

        # 按条切分
        clauses = self._split_by_articles(paragraphs, structure, title)

        # 提取元数据
        metadata = self._extract_metadata(paragraphs[:20], title)

        return {
            "regulation": metadata,
            "clauses": clauses,
        }

    def _identify_structure(self, paragraphs: list[str]) -> dict:
        """识别章→条层级结构"""
        chapters = []
        articles = []
        current_chapter = None

        for idx, p in enumerate(paragraphs):
            # 识别章
            if self.CHAPTER_PATTERN.match(p):
                if current_chapter:
                    current_chapter["end_idx"] = idx - 1
                m = re.match(r"第([一二三四五六七八九十百零\d]+)章\s*(.*)", p)
                current_chapter = {
                    "num": self._convert_chinese_num(m.group(1)) if m else 0,
                    "title": m.group(2) if m else "",
                    "start_idx": idx,
                    "end_idx": None,
                }
                chapters.append(current_chapter)

            # 识别条
            if self.ARTICLE_PATTERN.match(p):
                m = re.match(r"(第[一二三四五六七八九十百零\d]+条)", p)
                articles.append({
                    "num": m.group(1) if m else "",
                    "idx": idx,
                    "chapter_num": current_chapter["num"] if current_chapter else 0,
                })

        # 处理最后一章
        if current_chapter and current_chapter["end_idx"] is None:
            current_chapter["end_idx"] = len(paragraphs) - 1

        return {"chapters": chapters, "articles": articles}

    def _split_by_articles(
        self,
        paragraphs: list[str],
        structure: dict,
        title: str
    ) -> list[dict]:
        """按条切分条款"""
        clauses = []
        articles = structure["articles"]

        for i, article_info in enumerate(articles):
            start_idx = article_info["idx"]
            end_idx = articles[i + 1]["idx"] if i + 1 < len(articles) else len(paragraphs)

            # 收集该条的所有段落
            article_paragraphs = paragraphs[start_idx:end_idx]

            # 第一段是条号+正文
            first_para = clean_clause_text(article_paragraphs[0])

            # 后续段落可能是款
            sub_clauses = []
            for j, para in enumerate(article_paragraphs[1:], start=1):
                para = clean_clause_text(para)
                # 跳过章标题
                if self.CHAPTER_PATTERN.match(para):
                    continue
                if para:
                    sub_clauses.append({
                        "num": j,
                        "content": para,
                    })

            clause = {
                "source": "外规",
                "doc_title": title,
                "statute_id": md5(title.encode()).hexdigest(),
                "uid": f"{article_info['num']}_{title}",
                "article_no": article_info["num"],
                "clause_text": first_para,
                "sub_clauses": sub_clauses if sub_clauses else None,
                "chapter_num": article_info["chapter_num"],
                "subjects": [],
                "objects": [],
                "biz_dims": [],
                "action": None,
            }
            clauses.append(clause)

        return clauses

    def _extract_metadata(self, paragraphs: list[str], title: str) -> dict:
        """从文档开头提取法规元数据"""
        metadata = {
            "statute_id": md5(title.encode()).hexdigest(),
            "title": title,
            "reference_no": "",
            "org_name": "",
            "publish_date": "",
            "implement_date": "",
            "status": "Effective",
            "state": 1,
            "source": "外规",
        }

        full_text = "\n".join(paragraphs)

        # 文号
        m = re.search(r"第[一二三四五六七八九十百零\d]+号", full_text)
        if m:
            metadata["reference_no"] = m.group(0)

        # 发布日期
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", full_text)
        if m:
            metadata["publish_date"] = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"

        # 发布机构
        for p in paragraphs[:5]:
            if any(kw in p for kw in ["委员会", "银行", "监管", "政府", "人民"]):
                metadata["org_name"] = p
                break

        return metadata

    @staticmethod
    def _convert_chinese_num(num_str: str) -> int:
        """中文数字转阿拉伯数字"""
        mapping = {
            "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
            "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
            "十": 10, "百": 100,
        }
        # 简化处理：仅支持 1-99
        if len(num_str) == 1:
            return mapping.get(num_str, 0)
        if num_str == "十":
            return 10
        if num_str.startswith("十"):
            return 10 + mapping.get(num_str[1], 0)
        if num_str.endswith("十"):
            return mapping.get(num_str[0], 0) * 10
        return 0


def parse_outer_docx(file_path: Path | str) -> dict:
    """解析外规 DOCX 文件的便捷函数"""
    parser = OuterParser()
    return parser.parse(Path(file_path))
