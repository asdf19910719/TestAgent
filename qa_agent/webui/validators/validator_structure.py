"""结构校验器：测试函数数量、操作深度、重复名、骨架标记。"""
from __future__ import annotations

import ast
from typing import Dict, List

from . import ValidatorResult


def validate(source_text, source_lines, functions, ast_tree, args) -> ValidatorResult:
    gate_fails: List = []
    gate_warns: List = []

    shallow_funcs = [f for f in functions if f.action_count < args.min_actions]
    has_skeleton_marker = '# AQE-SKELETON' in source_text

    test_name_locs: Dict[str, List[str]] = {}
    for f in functions:
        test_name_locs.setdefault(f.name, []).append(f'L{f.line_start}')
    duplicate_tests = {n: locs for n, locs in test_name_locs.items() if len(locs) > 1}

    helper_name_locs: Dict[str, List[str]] = {}
    for node in ast.iter_child_nodes(ast_tree):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith('test_'):
            helper_name_locs.setdefault(node.name, []).append(f'L{node.lineno}')
    duplicate_helpers = {n: locs for n, locs in helper_name_locs.items() if len(locs) > 1}

    if not has_skeleton_marker and len(functions) >= 3:
        gate_fails.append(('骨架 provenance 缺失', ['未找到 # AQE-SKELETON 标记']))

    helper_funcs = [node for node in ast.iter_child_nodes(ast_tree)
                    if isinstance(node, ast.FunctionDef) and node.name.startswith('_helper')]
    has_helpers = len(helper_funcs) > 0
    if not has_helpers and len(functions) >= 3:
        gate_warns.append(('helper 缺失', [f'{len(functions)} 个测试函数但无 _helper_ 公共函数']))

    if shallow_funcs:
        gate_fails.append((
            '测试函数操作深度不足',
            [f'{f.name}: 仅 {f.action_count} 步操作（要求 >= {args.min_actions}）' for f in shallow_funcs],
        ))

    return ValidatorResult(
        gate_fails=gate_fails,
        gate_warns=gate_warns,
        metrics={
            'shallow_funcs': [f.name for f in shallow_funcs],
            'duplicate_tests': duplicate_tests,
            'duplicate_helpers': duplicate_helpers,
            'has_skeleton_marker': has_skeleton_marker,
            'has_helpers': has_helpers,
        },
    )
