"""外规 JSON 解析器 — 从 full_outer_data.json 直接解析条款

替代原有 DOCX 解析路径，直接从结构化 JSON 提取条款，避免 OCR/格式解析损耗。

JSON 结构:
  { total, statuteList: [{ statuteId, title, referenceNo, organizationName,
      publishdate, implementdate, status, categoryStr,
      paragraphInfos: [{ paragraphId, content, groupId, sort, num, type }]
  }] }

解析策略:
  - 按 sort 顺序扫描，sort 跟踪章归属（groupId 跨法规不一致）
  - type="条"/"款" 独立成 clause
  - type="" 段落归属到当前 clause 的 sub_clauses
  - 前导段落 (groupId < 2000, type="") 跳过
"""

import json
from pathlib import Path
from .text_cleaner import clean_text


class OuterJsonParser:
    """外规 JSON 解析器 — 输出与 OuterParser (DOCX) 格式兼容的 clause dict"""

    def parse(self, file_path: Path) -> list[dict]:
        """解析 JSON 文件，返回 clause 列表"""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"外规 JSON 文件不存在: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        statute_list = raw.get("statuteList", [])
        total_statutes = len(statute_list)
        clauses = []

        for i, statute in enumerate(statute_list):
            clauses.extend(self._process_statute(statute))
            if (i + 1) % 1000 == 0:
                print(f"  [OuterJsonParser] 进度: {i+1}/{total_statutes} 部法规", flush=True)

        # 显式释放原始数据
        del raw
        print(f"  [OuterJsonParser] 解析完成: {len(clauses)} 条 clause (来自 {total_statutes} 部法规)", flush=True)
        return clauses

    def _process_statute(self, statute: dict) -> list[dict]:
        """处理单部法规，按 sort 顺序跟踪章归属，提取条款"""
        paragraphs = statute.get("paragraphInfos", [])
        if not paragraphs:
            return []

        sorted_paras = sorted(paragraphs, key=lambda p: p.get("sort", 0))

        clauses = []
        current_chapter_num = 0
        current_chapter_title = ""
        current_article = None  # 正在构建的 clause

        for para in sorted_paras:
            ptype = para.get("type", "")
            gid = para.get("groupId", 0)

            if ptype == "编":
                continue

            if ptype == "章":
                current_chapter_num = para.get("num", 0)
                current_chapter_title = self._extract_chapter_title(para)
                continue

            if ptype == "节":
                # 节不改变章归属，也不作为独立 clause
                continue

            if ptype in ("条", "款"):
                # flush 上一个 clause
                if current_article is not None:
                    clauses.append(current_article)

                content = clean_text(para.get("content", ""))
                num = para.get("num")

                current_article = self._build_clause(
                    statute=statute,
                    para=para,
                    content=content,
                    article_num=num,
                    chapter_num=current_chapter_num,
                )

            elif ptype == "":
                # 前导段落：按 groupId 跳过（< 2000 是发布公告、签署、日期等元数据）
                if gid < 2000:
                    # 仅在 clauses 为空且无当前 clause 时才是前导
                    if not clauses and current_article is None:
                        continue

                # 续文段落：归入当前 clause 的 sub_clauses
                if current_article is not None:
                    content = clean_text(para.get("content", ""))
                    if content:
                        if current_article.get("sub_clauses") is None:
                            current_article["sub_clauses"] = []
                        sub_num = len(current_article["sub_clauses"]) + 1
                        current_article["sub_clauses"].append({
                            "num": sub_num,
                            "content": content,
                        })

        # flush 最后一个 clause
        if current_article is not None:
            clauses.append(current_article)

        return clauses

    def _build_clause(
        self,
        statute: dict,
        para: dict,
        content: str,
        article_num,
        chapter_num: int,
    ) -> dict:
        """构建标准 clause dict，格式与 OuterParser 输出兼容"""
        title = statute.get("title", "")
        ptype = para.get("type", "条")

        article_no = f"第{article_num}{ptype}" if article_num else ""

        return {
            "source": "外规",
            "doc_title": title,
            "statute_id": statute.get("statuteId", ""),
            "uid": f"{article_no}_{title}" if article_no else f"p{para.get('paragraphId')}_{title}",
            "article_no": article_no,
            "clause_text": content,
            "sub_clauses": None,
            "chapter_num": chapter_num,
            "subjects": [],
            "objects": [],
            "biz_dims": [],
            "action": None,
            # 新增元数据（不影响下游兼容性）
            "reference_no": statute.get("referenceNo", ""),
            "org_name": statute.get("organizationName", ""),
            "publish_date": statute.get("publishdate", ""),
            "implement_date": statute.get("implementdate", ""),
            "status": statute.get("status", ""),
            "category": statute.get("categoryStr", ""),
        }

    @staticmethod
    def _extract_chapter_title(para: dict) -> str:
        """从章段落提取章标题"""
        content = para.get("content", "")
        cleaned = clean_text(content)
        # 格式: "第X章 标题" — 去掉"第X章"部分
        import re
        m = re.match(r"第[一二三四五六七八九十百零\d]+章\s*(.*)", cleaned)
        return m.group(1) if m else cleaned


def parse_outer_json(file_path: Path | str) -> list[dict]:
    """解析外规 JSON 文件的便捷函数"""
    parser = OuterJsonParser()
    return parser.parse(Path(file_path))
