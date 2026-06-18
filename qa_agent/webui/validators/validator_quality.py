"""质量校验器：吞异常、空断言、永真断言、降级断言、无效 Playwright API。"""
from __future__ import annotations

import re
from typing import List

from . import ValidatorResult


def validate(source_text, source_lines, functions, ast_tree, args) -> ValidatorResult:
    gate_fails: List = []
    gate_warns: List = []

    swallowing_funcs = [f for f in functions if f.has_exception_swallowing]
    trivial_only_funcs = [f for f in functions
                          if f.assert_count > 0 and f.effective_assert_count == 0]
    no_assert_funcs = [f for f in functions if f.effective_assert_count == 0]

    if swallowing_funcs:
        details = []
        for f in swallowing_funcs:
            lines_str = ', '.join(f'L{ln}' for ln in f.swallowing_lines) if f.swallowing_lines else f'L{f.line_start}'
            details.append(f'{f.name} ({lines_str}): except 块内无 raise/assert，会静默吞掉测试失败')
        gate_fails.append(('try/except 吞异常', details))

    degraded_assertions = []
    for i, line in enumerate(source_lines, 1):
        stripped = line.strip()
        if stripped.startswith('assert ') and stripped.count(' or ') >= 2:
            degraded_assertions.append(f'L{i}: {stripped[:120]}')

    if degraded_assertions:
        gate_fails.append(('降级断言', degraded_assertions))

    _invalid_api_patterns = [
        (re.compile(r'\.triple_click\s*\('), 'triple_click 不存在，使用 click(click_count=3)'),
        (re.compile(r'\.double_click\s*\('), 'double_click 不存在，使用 dblclick()'),
        (re.compile(r'\.select_text\s*\('), 'select_text 不存在'),
        (re.compile(r'\.clear_input\s*\('), 'clear_input 不存在，使用 fill("")'),
        (re.compile(r'\.wait_for_navigation\s*\('), 'wait_for_navigation 已废弃，使用 wait_for_url'),
        (re.compile(r'\.type_text\s*\('), 'type_text 不存在，使用 type() 或 fill()'),
        (re.compile(r'\.click_and_hold\s*\('), 'click_and_hold 不存在'),
        (re.compile(r'\.send_keys\s*\('), 'send_keys 不存在（Selenium API），使用 fill() 或 type()'),
    ]
    invalid_api_found = []
    for i, line in enumerate(source_lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        for pat, desc in _invalid_api_patterns:
            if pat.search(stripped):
                invalid_api_found.append(f'L{i} [{desc}]: {stripped[:100]}')

    if invalid_api_found:
        gate_fails.append(('无效 Playwright API', invalid_api_found))

    _loose_assertion_pattern = re.compile(
        r'''\bin\b\s+\w+\.(input_value|get_attribute|text_content|inner_text)\s*\('''
    )
    loose_assertions_found = []
    for i, line in enumerate(source_lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if _loose_assertion_pattern.search(stripped):
            loose_assertions_found.append(f'L{i}: {stripped[:120]}')

    if loose_assertions_found:
        gate_warns.append(('松散断言（可能需要精确匹配）', loose_assertions_found))

    return ValidatorResult(
        gate_fails=gate_fails,
        gate_warns=gate_warns,
        metrics={
            'swallowing_funcs': [f.name for f in swallowing_funcs],
            'trivial_only_funcs': [f.name for f in trivial_only_funcs],
            'no_assert_funcs': [f.name for f in no_assert_funcs],
            'degraded_assertions_count': len(degraded_assertions),
            'invalid_api_count': len(invalid_api_found),
        },
    )
