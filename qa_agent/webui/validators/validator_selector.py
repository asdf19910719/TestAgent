"""选择器校验器：禁用选择器、smart XPath 覆盖率、resolved 步 XPath 消费。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

from . import ValidatorResult

# smart XPath 强制覆盖率门禁阈值
_SMART_XPATH_HARD_GATE_RATIO = 0.40

# 豁免行模式：这些行中的 locator 不计入 CSS 分母
_XPATH_EXEMPT_PATTERNS = (
    'el-message--success', 'el-message--error', 'el-message--warning', 'el-message--info',
    'el-loading-mask', 'el-loading',
    'expect(', 'assert ',
    'wait_for(state="hidden"',
    '.count()', '.is_visible()',
    # canvas 等无法 XPath 定位的元素走坐标方案，豁免 smart XPath 检查
    '"canvas"', "'canvas'", 'canvas_', 'mouse.click(', 'mouse.move(',
    'bounding_box', 'canvas_locate', 'canvas_click',
)

# 豁免函数名前缀：这些辅助函数内部不强制 smart XPath
_XPATH_EXEMPT_FUNC_PREFIXES = ('_fallback_', '_canvas_', 'canvas_',)


def compute_smart_xpath_ratio(source_lines: list) -> dict:
    """统计源码中 XPath 定位器 vs 总 locator 调用的比率（排除注释行和豁免行）。

    返回 {'xpath_calls': int, 'total_locator_calls': int, 'ratio': float,
           'css_lines': list[str]}
    """
    _locator_re = re.compile(r'(?:page|dialog|row|frame|container|wrapper|locator)\S*\.locator\s*\(')
    _xpath_re = re.compile(r'''xpath=''')
    _func_def_re = re.compile(r'^def\s+(\w+)\s*\(')

    xpath_calls = 0
    total_calls = 0
    css_lines = []
    current_func = ''

    for i, line in enumerate(source_lines):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue

        func_m = _func_def_re.match(stripped)
        if func_m:
            current_func = func_m.group(1)

        if any(current_func.startswith(p) for p in _XPATH_EXEMPT_FUNC_PREFIXES):
            continue

        if not _locator_re.search(stripped):
            continue

        if any(pat in stripped for pat in _XPATH_EXEMPT_PATTERNS):
            continue

        total_calls += 1
        if _xpath_re.search(stripped):
            xpath_calls += 1
        else:
            css_lines.append(f'L{i + 1}: {stripped[:120]}')

    ratio = xpath_calls / total_calls if total_calls > 0 else 1.0
    return {
        'xpath_calls': xpath_calls,
        'total_locator_calls': total_calls,
        'ratio': round(ratio, 2),
        'css_lines': css_lines,
    }


def _compute_xpath_coverage(cases_file: str, source_lines: list) -> dict | None:
    cases_path = Path(cases_file)
    if not cases_path.exists():
        return None
    try:
        data = json.loads(cases_path.read_text(encoding='utf-8'))
    except Exception:
        return None

    cases = data.get('cases', [])
    resolved_steps = 0
    for case in cases:
        for step in case.get('steps', []):
            if isinstance(step, dict):
                binding = step.get('binding', {})
                if isinstance(binding, dict) and binding.get('status') == 'resolved':
                    resolved_steps += 1

    if resolved_steps == 0:
        return {'resolved_steps': 0, 'xpath_locators': 0, 'coverage_ratio': 0.0}

    xpath_pattern = re.compile(r'''xpath=''')
    xpath_count = 0
    for line in source_lines:
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        xpath_count += len(xpath_pattern.findall(stripped))

    ratio = xpath_count / resolved_steps if resolved_steps > 0 else 0.0
    return {
        'resolved_steps': resolved_steps,
        'xpath_locators': xpath_count,
        'coverage_ratio': round(ratio, 2),
    }


def _check_resolved_xpath_usage(cases_file: str, page_elements_file: str,
                                source_text: str) -> list:
    cases_path = Path(cases_file)
    pe_path = Path(page_elements_file)
    if not cases_path.exists() or not pe_path.exists():
        return []

    try:
        cases_data = json.loads(cases_path.read_text(encoding='utf-8'))
        pe_data = json.loads(pe_path.read_text(encoding='utf-8'))
    except Exception:
        return []

    elements = pe_data.get('elements', [])
    cases = cases_data.get('cases', [])
    violations = []

    for case in cases:
        case_id = case.get('case_id') or case.get('id', '')
        for step_idx, step in enumerate(case.get('steps', [])):
            if not isinstance(step, dict):
                continue
            binding = step.get('binding', {})
            if not isinstance(binding, dict) or binding.get('status') != 'resolved':
                continue
            selector_ref = binding.get('selector_ref', '')

            elem = None
            m_id = re.match(r'page-elements\.elements#(.+)', selector_ref)
            if m_id:
                target_id = m_id.group(1)
                for e in elements:
                    eid = e.get('mock_id') or e.get('id', '')
                    if eid == target_id:
                        elem = e
                        break
            else:
                m_idx = re.match(r'page-elements\.elements\[(\d+)\]', selector_ref)
                if not m_idx:
                    continue
                idx = int(m_idx.group(1))
                if idx >= len(elements):
                    continue
                elem = elements[idx]

            if elem is None:
                continue
            smart_xpath = elem.get('smart_xpath', '')
            if not smart_xpath:
                for sel in elem.get('selectors', []):
                    if sel.get('strategy') == 'xpath':
                        smart_xpath = sel.get('value', '')
                        break
            if not smart_xpath:
                continue

            xpath_escaped = re.escape(smart_xpath)
            if not re.search(xpath_escaped, source_text):
                step_text = step.get('text', step.get('description', ''))
                violations.append({
                    'case_id': case_id,
                    'step_idx': step_idx + 1,
                    'step_text': str(step_text)[:80],
                    'expected_xpath': smart_xpath[:100],
                    'selector_ref': selector_ref,
                })

    return violations


def validate(source_text, source_lines, functions, ast_tree, args) -> ValidatorResult:
    gate_fails: List = []
    gate_warns: List = []
    metrics = {}

    banned_selector_patterns = [
        (re.compile(r'''(?:get_by_text|has.text)\s*\(\s*["'](?:取消|保存|确定|确认|删除|关闭)["']\s*\)'''), 'unscoped button text'),
        (re.compile(r'''\.first(?:\s*$|\s*\.)'''), 'unscoped positional locator (.first)'),
        (re.compile(r'''\.nth\(\s*0\s*\)'''), 'unscoped positional locator (.nth(0))'),
        (re.compile(r'''locator\s*\(\s*["']\.el-table["']\s*\)'''), 'bare .el-table (strict mode risk)'),
        (re.compile(r'''locator\s*\(\s*["']\.el-form["']\s*\)'''), 'bare .el-form (strict mode risk)'),
        (re.compile(r'''locator\s*\(\s*["']input\[placeholder\*?='''), 'bare input[placeholder] (needs scope)'),
        (re.compile(r'''locator\s*\(\s*["']textarea["']\s*\)'''), 'bare textarea (strict mode risk)'),
    ]
    _scope_exemptions = (
        '.el-dialog', '.el-form-item', 'filter(', 'dialog.', 'form_item.', 'row.',
        'card.', 'item.', 'dropdown.', 'iframe.',
        ':has-text(', '[data-testid', '[placeholder', ':has(',
        '.el-tabs__item', '.el-dropdown', '.el-cascader',
        '.el-table__body', '.el-table__fixed', '.el-select-dropdown',
        '.el-tree', '.el-menu', '.el-pagination',
        'tbody', '.count()', '.is_visible()', '_wrapper',
    )
    _locator_selector_re = re.compile(r'''locator\s*\(\s*["']([^"']+)["']\s*\)''')

    def _has_deep_selector_context(line: str) -> bool:
        """Check if the locator(...) on this line has >= 2 CSS selector levels."""
        m = _locator_selector_re.search(line)
        if not m:
            return False
        sel = m.group(1).strip()
        parts = [p for p in sel.split() if p]
        return len(parts) >= 2

    _var_assign_re = re.compile(r'^(\s*)([a-zA-Z_]\w*)\s*=\s*(.+)')

    def _variable_has_scope(line: str, all_lines: list, line_idx: int):
        """Check if the variable was assigned from a scoped locator.

        Returns True (confirmed safe), False (confirmed unscoped), or
        None (assignment not found within 30 lines — uncertain).
        """
        stripped = line.strip()
        m = re.match(r'(\w+)\.(?:first|nth\()', stripped)
        if not m:
            return None
        var_name = m.group(1)
        start = max(0, line_idx - 30)
        for j in range(line_idx - 1, start - 1, -1):
            am = _var_assign_re.match(all_lines[j])
            if am and am.group(2) == var_name:
                rhs = am.group(3)
                if any(ex in rhs for ex in _scope_exemptions):
                    return True
                if _has_deep_selector_context(rhs):
                    return True
                if 'xpath=' in rhs and '@id=' in rhs:
                    return True
                if 'get_by_' in rhs:
                    return True
                return False
        return None

    banned_selectors_found = []
    for i, line in enumerate(source_lines, 1):
        for pat, desc in banned_selector_patterns:
            if pat.search(line):
                if any(ex in line for ex in _scope_exemptions):
                    continue
                if 'positional' in desc and _has_deep_selector_context(line):
                    continue
                if 'positional' in desc:
                    scope_result = _variable_has_scope(line, source_lines, i - 1)
                    if scope_result is True or scope_result is None:
                        continue
                banned_selectors_found.append(f'L{i} [{desc}]: {line.strip()[:100]}')

    if banned_selectors_found:
        gate_fails.append(('禁用选择器', banned_selectors_found))

    time_sleep_lines = []
    _time_sleep_pat = re.compile(r'\btime\.sleep\s*\(')
    for i, line in enumerate(source_lines, 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if _time_sleep_pat.search(stripped):
            time_sleep_lines.append(
                f'L{i}: {stripped[:100]} — 请改用 page.wait_for_timeout(ms) 或显式等待')
    if time_sleep_lines:
        gate_fails.append(('禁止 time.sleep()（秒/毫秒混淆风险，且阻塞进程）', time_sleep_lines))

    select_option_funcs = [f for f in functions if 'select_option' in f.actions]
    metrics['select_option_funcs'] = [f.name for f in select_option_funcs]
    metrics['banned_selectors_count'] = len(banned_selectors_found)

    xpath_coverage = None
    resolved_xpath_violations = []
    cases_file = getattr(args, 'cases_file', '')
    page_elements_file = getattr(args, 'page_elements_file', '')

    if cases_file:
        xpath_coverage = _compute_xpath_coverage(cases_file, source_lines)
        if xpath_coverage and xpath_coverage.get('resolved_steps', 0) > 0:
            ratio = xpath_coverage['coverage_ratio']
            if ratio < 0.6:
                gate_warns.append(('smart XPath 覆盖率偏低（趋势观察）',
                                   [f'{xpath_coverage["xpath_locators"]}/{xpath_coverage["resolved_steps"]}'
                                    f' ({ratio:.0%})'
                                    f' — 仅趋势指标，不代表 step-to-selector 严格映射']))

        if page_elements_file:
            resolved_xpath_violations = _check_resolved_xpath_usage(
                cases_file, page_elements_file, source_text)
            if resolved_xpath_violations:
                violation_details = []
                for v in resolved_xpath_violations[:10]:
                    violation_details.append(
                        f'{v["case_id"]} step {v["step_idx"]}: '
                        f'"{v["step_text"]}" — 未使用 {v["selector_ref"]} 的 smart XPath')
                gate_fails.append(('resolved 步骤未使用 smart XPath', violation_details))

    metrics['xpath_coverage'] = xpath_coverage
    metrics['resolved_xpath_violations'] = resolved_xpath_violations if resolved_xpath_violations else None

    # ── smart XPath 强制覆盖率门禁 ──
    # 当 page-elements.json 的 element_source == 'smart_xpath' 时，
    # 整体 XPath 使用率必须 >= _SMART_XPATH_HARD_GATE_RATIO，否则硬拦截。
    pe_element_source = ''
    if page_elements_file and Path(page_elements_file).exists():
        try:
            pe_data = json.loads(Path(page_elements_file).read_text(encoding='utf-8'))
            pe_element_source = pe_data.get('element_source', '')
        except Exception:
            pass

    smart_xpath_ratio_data = compute_smart_xpath_ratio(source_lines)
    metrics['smart_xpath_ratio'] = smart_xpath_ratio_data

    if pe_element_source == 'smart_xpath' and smart_xpath_ratio_data['total_locator_calls'] > 0:
        ratio = smart_xpath_ratio_data['ratio']
        if ratio < _SMART_XPATH_HARD_GATE_RATIO:
            detail_lines = [
                f'XPath 使用率 {ratio:.0%} < 强制阈值 {_SMART_XPATH_HARD_GATE_RATIO:.0%}'
                f' ({smart_xpath_ratio_data["xpath_calls"]}/{smart_xpath_ratio_data["total_locator_calls"]})',
                'page-elements.json 已提供 smart XPath (element_source=smart_xpath)，'
                '脚本必须使用 xpath= 定位器，禁止用裸 CSS 选择器',
            ]
            for css_line in smart_xpath_ratio_data['css_lines'][:8]:
                detail_lines.append(f'  裸 CSS: {css_line}')
            if len(smart_xpath_ratio_data['css_lines']) > 8:
                detail_lines.append(
                    f'  ... 共 {len(smart_xpath_ratio_data["css_lines"])} 处裸 CSS 选择器')
            gate_fails.append(('smart XPath 强制覆盖率不达标', detail_lines))

    return ValidatorResult(
        gate_fails=gate_fails,
        gate_warns=gate_warns,
        metrics=metrics,
    )
