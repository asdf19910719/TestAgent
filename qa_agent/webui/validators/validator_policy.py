"""策略校验器：skip/xfail、timeout 密度、helper 缺失、screenshot 缺失。"""
from __future__ import annotations

from typing import List

from . import ValidatorResult


def validate(source_text, source_lines, functions, ast_tree, args) -> ValidatorResult:
    gate_fails: List = []
    gate_warns: List = []
    total_lines = len(source_lines)

    skip_hard_lines = []
    skip_warn_lines = []
    for i, line in enumerate(source_lines, 1):
        stripped = line.strip()
        if 'pytest.skip(' in stripped:
            skip_hard_lines.append(f'L{i} [pytest.skip()]: {stripped[:120]}')
        if stripped.startswith('@pytest.mark.skip') and 'skipif' not in stripped:
            skip_hard_lines.append(f'L{i} [@pytest.mark.skip]: {stripped[:120]}')
        if stripped.startswith('@pytest.mark.xfail'):
            skip_hard_lines.append(f'L{i} [@pytest.mark.xfail]: {stripped[:120]}')
        if stripped.startswith('@pytest.mark.skipif'):
            skip_warn_lines.append(f'L{i} [@pytest.mark.skipif]: {stripped[:120]}')

    if skip_hard_lines:
        gate_fails.append(('pytest.skip/xfail 伪装通过', skip_hard_lines))
    if skip_warn_lines:
        gate_warns.append(('pytest.mark.skipif 条件跳过（可疑）', skip_warn_lines))

    timeout_count = sum(1 for line in source_lines if 'wait_for_timeout' in line)
    timeout_density = timeout_count / max(total_lines, 1)
    if timeout_density > 0.15:
        gate_warns.append(('wait_for_timeout 密度过高',
                           [f'{timeout_count}/{total_lines} 行 ({timeout_density:.1%})']))

    screenshot_calls = sum(1 for line in source_lines if 'screenshot' in line.lower())
    if screenshot_calls == 0 and len(functions) >= 5:
        gate_warns.append(('关键快照缺失', ['无 screenshot 调用点']))

    return ValidatorResult(
        gate_fails=gate_fails,
        gate_warns=gate_warns,
        metrics={
            'skip_hard_count': len(skip_hard_lines),
            'skip_warn_count': len(skip_warn_lines),
            'timeout_density': f'{timeout_density:.1%}',
            'screenshot_calls': screenshot_calls,
        },
    )
