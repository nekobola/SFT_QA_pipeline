"""内规 DOCX 解析器，复用自图数据库 stage1_parse.py"""
import re
from pathlib import Path
from docx import Document
from typing import Optional

from .base import BaseParser
from .text_cleaner import clean_clause_text


class InnerParser(BaseParser):
    """内规 DOCX 解析器"""

    # 条号匹配正则
    ARTICLE_PATTERN = re.compile(r"^第[一二三四五六七八九十百零\d]+条")

    def __init__(self):
        self.current_article: Optional[str] = None
        self.current_lines: list[str] = []

    def parse(self, file_path: Path) -> list[dict]:
        """解析内规 DOCX 文件"""
        if file_path.suffix.lower() != ".docx":
            raise ValueError(f"仅支持 .docx，当前文件: {file_path.name}")

        # 提取标题
        title = self.extract_title_from_filename(file_path.name)
        statute_id = self.generate_uid(title, "")

        # 读取文档
        doc = Document(str(file_path))
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

        # 清洗并按条切分
        clauses = self._split_by_articles(paragraphs, title, statute_id)

        return clauses

    def _split_by_articles(
        self,
        paragraphs: list[str],
        title: str,
        statute_id: str
    ) -> list[dict]:
        """按条切分条款"""
        clauses = []
        current_article = None
        current_lines: list[str] = []

        for line in paragraphs:
            line = clean_clause_text(line)
            if not line:
                continue

            # 跳过附件、附则等非正文部分
            if re.match(r"^附[件则]", line):
                continue

            if self.ARTICLE_PATTERN.match(line):
                # 保存上一条
                if current_article is not None and current_lines:
                    clauses.append(self._build_clause(
                        title, statute_id, current_article, current_lines
                    ))
                # 开始新一条
                m = re.match(r"(第[一二三四五六七八九十百零\d]+条)", line)
                current_article = m.group(1) if m else ""
                current_lines = [line]
            else:
                if current_article is not None:
                    current_lines.append(line)

        # 保存最后一条
        if current_article is not None and current_lines:
            clauses.append(self._build_clause(
                title, statute_id, current_article, current_lines
            ))

        return clauses

    def _build_clause(
        self,
        title: str,
        statute_id: str,
        article_no: str,
        lines: list[str]
    ) -> dict:
        """构建条款字典"""
        return {
            "source": "内规",
            "doc_title": title,
            "statute_id": statute_id,
            "uid": self.generate_uid(title, article_no),
            "article_no": article_no,
            "clause_text": "\n".join(lines),
            "subjects": [],
            "objects": [],
            "biz_dims": [],
            "action": None,
        }


def parse_inner_docx(file_path: Path | str) -> list[dict]:
    """解析内规 DOCX 文件的便捷函数"""
    parser = InnerParser()
    return parser.parse(Path(file_path))
