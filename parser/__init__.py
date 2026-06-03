"""解析器模块"""
from .text_cleaner import clean_text, clean_clause_text
from .inner_parser import InnerParser, parse_inner_docx
from .outer_parser import OuterParser, parse_outer_docx
from .outer_json_parser import OuterJsonParser, parse_outer_json
from .semantics_extractor import (
    extract_semantic_elements,
    batch_extract_semantics,
    extract_action_from_text,
)
from .synonym_normalizer import (
    SynonymNormalizer,
    build_synonym_lookup,
    normalize_entity,
    normalize_entities_batch,
    match_text_entities,
    get_normalizer,
)

__all__ = [
    "clean_text",
    "clean_clause_text",
    "InnerParser",
    "parse_inner_docx",
    "OuterParser",
    "parse_outer_docx",
    "OuterJsonParser",
    "parse_outer_json",
    "extract_semantic_elements",
    "batch_extract_semantics",
    "extract_action_from_text",
    "SynonymNormalizer",
    "build_synonym_lookup",
    "normalize_entity",
    "normalize_entities_batch",
    "match_text_entities",
    "get_normalizer",
]
