"""
校验器模块：将 validate_test_depth 的校验逻辑按维度拆分。

统一接口：
    validate(source_text, source_lines, functions, ast_tree, args) -> ValidatorResult
"""
from typing import List, Tuple, Dict, NamedTuple


class ValidatorResult(NamedTuple):
    gate_fails: List[Tuple[str, List[str]]]
    gate_warns: List[Tuple[str, List[str]]]
    metrics: Dict
