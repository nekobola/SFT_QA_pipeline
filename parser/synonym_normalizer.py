"""同义词归一化模块，复用自图数据库 stage3_5_tag.py"""
import json
from pathlib import Path
from typing import Optional


def build_synonym_lookup(synonym_dict: dict) -> dict:
    """
    构建同义词反查表

    将 {"商业银行": ["本行", "该银行"]} 转换为 {"本行": "商业银行", "该银行": "商业银行", "商业银行": "商业银行"}

    Args:
        synonym_dict: 同义词词典，格式为 {category: {canonical: [synonyms]}}

    Returns:
        反查表，格式为 {category: {term: canonical}}
    """
    lookup: dict[str, dict[str, str]] = {}
    for category, entities in synonym_dict.items():
        table: dict[str, str] = {}
        for canonical, synonyms in entities.items():
            # 规范名映射到自身
            table[canonical] = canonical
            # 同义词映射到规范名
            for syn in synonyms:
                table[syn] = canonical
        lookup[category] = table
    return lookup


def normalize_entity(raw_name: str | list, term_table: dict) -> list[str]:
    """
    将实体名规范化为词典中的规范名

    Args:
        raw_name: 原始实体名（字符串或列表）
        term_table: 同义词反查表

    Returns:
        规范化后的实体名列表
    """
    if not raw_name:
        return []

    names = raw_name if isinstance(raw_name, list) else [raw_name]
    results: list[str] = []

    for name in names:
        if not isinstance(name, str) or not name:
            continue

        # 精确匹配
        if name in term_table:
            canonical = term_table[name]
        else:
            canonical = name
            # 尝试子串匹配（长词优先）
            for term, c in sorted(term_table.items(), key=lambda x: len(x[0]), reverse=True):
                if term in name:
                    canonical = c
                    break

        if canonical not in results:
            results.append(canonical)

    return results


def normalize_entities_batch(
    entities: list[str],
    term_table: dict,
) -> list[str]:
    """
    批量归一化实体列表

    Args:
        entities: 实体列表
        term_table: 同义词反查表

    Returns:
        归一化后的实体列表（去重）
    """
    if not entities:
        return []

    normalized = []
    for entity in entities:
        if entity in term_table:
            canonical = term_table[entity]
        else:
            # 尝试子串匹配
            canonical = entity
            for term, c in sorted(term_table.items(), key=lambda x: len(x[0]), reverse=True):
                if term in entity:
                    canonical = c
                    break

        if canonical not in normalized:
            normalized.append(canonical)

    return normalized


def match_text_entities(text: str, term_table: dict) -> list[str]:
    """
    从文本中匹配实体（长词优先）

    Args:
        text: 文本内容
        term_table: 同义词反查表

    Returns:
        匹配到的规范名列表
    """
    # 按长度降序排列，避免短词误匹配
    sorted_terms = sorted(term_table.keys(), key=len, reverse=True)
    matched_canonicals: list[str] = []

    for term in sorted_terms:
        if term in text:
            canonical = term_table[term]
            if canonical not in matched_canonicals:
                matched_canonicals.append(canonical)

    return matched_canonicals


class SynonymNormalizer:
    """同义词归一化器"""

    def __init__(self, synonym_dict_path: Optional[str] = None):
        """
        初始化归一化器

        Args:
            synonym_dict_path: 同义词词典文件路径
        """
        self.lookup: dict[str, dict[str, str]] = {}
        self._loaded = False

        if synonym_dict_path:
            self.load(synonym_dict_path)

    def load(self, path: str) -> None:
        """加载同义词词典"""
        path = Path(path)
        if not path.exists():
            print(f"[Warn] Synonym dictionary not found: {path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            synonym_dict = json.load(f)

        self.lookup = build_synonym_lookup(synonym_dict)
        self._loaded = True
        print(f"[SynonymNormalizer] Loaded {len(self.lookup)} categories")

    def normalize_subjects(self, subjects: list[str]) -> list[str]:
        """归一化主体实体"""
        if not self._loaded or "subjects" not in self.lookup:
            return subjects
        return normalize_entities_batch(subjects, self.lookup["subjects"])

    def normalize_objects(self, objects: list[str]) -> list[str]:
        """归一化客体实体"""
        if not self._loaded or "objects" not in self.lookup:
            return objects
        return normalize_entities_batch(objects, self.lookup["objects"])

    def normalize_biz_dims(self, biz_dims: list[str]) -> list[str]:
        """归一化业务维度"""
        if not self._loaded or "biz_dims" not in self.lookup:
            return biz_dims
        return normalize_entities_batch(biz_dims, self.lookup["biz_dims"])

    def normalize_clause(self, clause: dict) -> dict:
        """
        归一化条款的语义要素

        Args:
            clause: 条款字典，包含 subjects, objects, biz_dims 字段

        Returns:
            更新后的条款字典
        """
        clause["subjects"] = self.normalize_subjects(clause.get("subjects", []))
        clause["objects"] = self.normalize_objects(clause.get("objects", []))
        clause["biz_dims"] = self.normalize_biz_dims(clause.get("biz_dims", []))
        return clause

    def is_loaded(self) -> bool:
        """检查是否已加载词典"""
        return self._loaded


# 全局归一化器实例
_normalizer: Optional[SynonymNormalizer] = None


def get_normalizer(synonym_dict_path: Optional[str] = None) -> SynonymNormalizer:
    """
    获取全局归一化器实例

    Args:
        synonym_dict_path: 同义词词典路径（首次调用时需要）

    Returns:
        SynonymNormalizer 实例
    """
    global _normalizer

    if _normalizer is None:
        _normalizer = SynonymNormalizer(synonym_dict_path)

    return _normalizer
