#!/usr/bin/env python3
"""
测试脚本深度校验工具（orchestrator）

在 04-script-generator 生成脚本后、05-test-executor 执行前，校验每个 test 函数
是否实现了足够深度的操作链，防止生成只做存在性断言的浅层测试。

校验规则分布在 validators/ 子模块中：
  - validator_structure: 深度、重复名、骨架标记
  - validator_quality:   吞异常、空断言、降级断言、无效 API
  - validator_selector:  禁用选择器、smart XPath 覆盖率、resolved 步 XPath
  - validator_policy:    skip/xfail、timeout 密度、helper/screenshot 缺失

用法:
    python validate_test_depth.py --test-file test_webui.py [--csv-file ...] [--min-actions 3]

退出码:
    0 - 校验通过
    1 - 存在不达标的测试函数（输出详细报告）
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple


class FuncAnalysis(NamedTuple):
    name: str
    action_count: int
    assert_count: int
    effective_assert_count: int
    trivial_assert_count: int
    has_exception_swallowing: bool
    actions: List[str]
    line_start: int
    line_end: int
    swallowing_lines: List[int] = []


ACTION_METHODS = {
    'click', 'dblclick', 'fill', 'type', 'press', 'check', 'uncheck',
    'select_option', 'set_input_files', 'drag_to', 'hover',
    'focus', 'clear', 'press_sequential',
}

WAIT_METHODS = {
    'wait_for', 'wait_for_selector', 'wait_for_url',
    'wait_for_load_state',
}
IDLE_WAIT_METHODS = {'wait_for_timeout'}

ASSERT_PATTERNS = {'expect', 'assert', 'to_be_visible', 'to_be_hidden',
                   'to_have_text', 'to_have_count', 'to_contain_text'}

TRIVIAL_ASSERTION_TARGETS = {'body', 'html'}


class TestDepthAnalyzer(ast.NodeVisitor):
    """AST 遍历器，分析每个 test 函数的操作深度。"""

    def __init__(self):
        self.functions: List[FuncAnalysis] = []
        self._current_actions: List[str] = []
        self._current_asserts: int = 0
        self._effective_asserts: int = 0
        self._trivial_asserts: int = 0
        self._has_exception_swallowing: bool = False
        self._swallowing_lines: List[int] = []
        self._module_tree: ast.Module | None = None

    def set_module(self, tree: ast.Module):
        self._module_tree = tree

    def _count_helper_actions(self, func_name: str) -> List[str]:
        if not self._module_tree:
            return []
        for node in ast.iter_child_nodes(self._module_tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                actions = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        method = self._get_call_method(child)
                        if method and (method in ACTION_METHODS or method in WAIT_METHODS):
                            actions.append(method)
                return actions
        return []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if not node.name.startswith('test_'):
            return

        self._current_actions = []
        self._current_asserts = 0
        self._effective_asserts = 0
        self._trivial_asserts = 0
        self._has_exception_swallowing = False
        self._swallowing_lines = []

        for child in ast.walk(node):
            if isinstance(child, ast.ExceptHandler):
                has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(child))
                has_assert = any(isinstance(n, ast.Assert) for n in ast.walk(child))
                if not has_raise and not has_assert:
                    self._has_exception_swallowing = True
                    self._swallowing_lines.append(child.lineno)

        called_helpers = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                method_name = self._get_call_method(child)
                if method_name:
                    if method_name in ACTION_METHODS or method_name in WAIT_METHODS:
                        self._current_actions.append(method_name)
                    elif method_name in ASSERT_PATTERNS:
                        self._current_asserts += 1
                    elif not method_name.startswith('test_'):
                        called_helpers.add(method_name)

            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                if child.func.id == 'expect':
                    self._current_asserts += 1
                    if self._is_trivial_assertion(child):
                        self._trivial_asserts += 1
                    else:
                        self._effective_asserts += 1

            if isinstance(child, ast.Assert):
                self._current_asserts += 1
                self._effective_asserts += 1

        for helper in called_helpers:
            helper_actions = self._count_helper_actions(helper)
            if helper_actions:
                self._current_actions.extend(helper_actions)

        line_end = node.end_lineno or (node.lineno + len(node.body))
        self.functions.append(FuncAnalysis(
            name=node.name,
            action_count=len(self._current_actions),
            assert_count=self._current_asserts,
            effective_assert_count=self._effective_asserts,
            trivial_assert_count=self._trivial_asserts,
            has_exception_swallowing=self._has_exception_swallowing,
            actions=self._current_actions[:],
            line_start=node.lineno,
            line_end=line_end,
            swallowing_lines=self._swallowing_lines[:],
        ))

    @staticmethod
    def _is_trivial_assertion(expect_call: ast.Call) -> bool:
        if not expect_call.args:
            return False
        arg = expect_call.args[0]
        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
            if arg.func.attr == 'locator' and arg.args:
                first_arg = arg.args[0]
                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                    return first_arg.value.strip().lower() in TRIVIAL_ASSERTION_TARGETS
        return False

    @staticmethod
    def _get_call_method(node: ast.Call) -> str | None:
        func = node.func
        if isinstance(func, ast.Attribute):
            return func.attr
        if isinstance(func, ast.Name):
            return func.id
        return None


def count_csv_cases(csv_path: str) -> int:
    path = Path(csv_path)
    if not path.exists():
        return -1
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return 0
        return sum(1 for _ in reader)


def analyze_test_file(test_path: str):
    path = Path(test_path)
    if not path.exists():
        print(f'ERROR: 文件不存在: {test_path}', file=sys.stderr)
        sys.exit(2)

    source = path.read_text(encoding='utf-8-sig')
    try:
        tree = ast.parse(source, filename=test_path)
    except SyntaxError as e:
        print(f'ERROR: 语法错误: {e}', file=sys.stderr)
        sys.exit(2)

    analyzer = TestDepthAnalyzer()
    analyzer.set_module(tree)
    analyzer.visit(tree)
    return analyzer.functions, tree


def main():
    parser = argparse.ArgumentParser(description='测试脚本深度校验工具')
    parser.add_argument('--test-file', required=True, help='test_webui.py 文件路径')
    parser.add_argument('--csv-file', default='', help='CSV 用例文件路径（可选，用于数量对比）')
    parser.add_argument('--min-actions', type=int, default=3,
                        help='每个 test 函数最少需要的实际操作数（默认 3）')
    parser.add_argument('--cases-file', default='',
                        help='ui-test-cases.json 文件路径（可选，用于 smart XPath 覆盖率趋势统计）')
    parser.add_argument('--page-elements-file', default='',
                        help='page-elements.json 文件路径（可选，配合 --cases-file 做 resolved 步骤精确校验）')
    parser.add_argument('--output', default='', help='输出 JSON 报告路径（可选）')
    args = parser.parse_args()

    functions, ast_tree = analyze_test_file(args.test_file)

    if not functions:
        print('WARNING: 未找到任何 test_ 函数', file=sys.stderr)
        sys.exit(1)

    source_text = Path(args.test_file).read_text(encoding='utf-8-sig')
    source_lines = source_text.split('\n')

    # ── 调度各维度 validator ──
    from validators import validator_structure, validator_quality, validator_selector, validator_policy

    r_structure = validator_structure.validate(source_text, source_lines, functions, ast_tree, args)
    r_quality = validator_quality.validate(source_text, source_lines, functions, ast_tree, args)
    r_selector = validator_selector.validate(source_text, source_lines, functions, ast_tree, args)
    r_policy = validator_policy.validate(source_text, source_lines, functions, ast_tree, args)

    gate_fails = []
    gate_warns = []
    for r in (r_structure, r_quality, r_selector, r_policy):
        gate_fails.extend(r.gate_fails)
        gate_warns.extend(r.gate_warns)

    has_gate_fail = len(gate_fails) > 0

    # ── 聚合结构性指标 ──
    shallow_funcs = [f for f in functions if f.action_count < args.min_actions]
    deep_funcs = [f for f in functions if f.action_count >= args.min_actions]
    swallowing_funcs = [f for f in functions if f.has_exception_swallowing]
    trivial_only_funcs = [f for f in functions
                          if f.assert_count > 0 and f.effective_assert_count == 0]
    no_assert_funcs = [f for f in functions if f.effective_assert_count == 0]
    select_option_funcs = [f for f in functions if 'select_option' in f.actions]
    domcontent_only_funcs = [
        f for f in functions
        if 'wait_for_load_state' in f.actions
        and 'wait_for' not in f.actions
        and 'wait_for_selector' not in f.actions
    ]
    has_banned_pattern = bool(select_option_funcs)

    csv_count = -1
    count_mismatch = False
    if args.csv_file:
        csv_count = count_csv_cases(args.csv_file)
        if csv_count > 0:
            ratio = len(functions) / csv_count
            count_mismatch = ratio > 1.5 or ratio < 0.5

    duplicate_tests = r_structure.metrics.get('duplicate_tests', {})
    duplicate_helpers = r_structure.metrics.get('duplicate_helpers', {})
    has_quality_issue = bool(swallowing_funcs) or bool(trivial_only_funcs) or bool(no_assert_funcs)
    has_duplicates = bool(duplicate_tests) or bool(duplicate_helpers)

    xpath_coverage = r_selector.metrics.get('xpath_coverage')
    resolved_xpath_violations = r_selector.metrics.get('resolved_xpath_violations') or []

    # ── 构建报告 ──
    report = {
        'test_file': args.test_file,
        'min_actions_required': args.min_actions,
        'total_functions': len(functions),
        'deep_functions': len(deep_funcs),
        'shallow_functions': len(shallow_funcs),
        'exception_swallowing_functions': len(swallowing_funcs),
        'trivial_assertion_only_functions': len(trivial_only_funcs),
        'no_assertion_functions': len(no_assert_funcs),
        'duplicate_test_functions': duplicate_tests,
        'duplicate_helper_functions': duplicate_helpers,
        'select_option_functions': len(select_option_funcs),
        'domcontentloaded_only_functions': len(domcontent_only_funcs),
        'csv_case_count': csv_count,
        'count_mismatch': count_mismatch,
        'gate_checks': {
            'has_skeleton_marker': r_structure.metrics.get('has_skeleton_marker', False),
            'has_helpers': r_structure.metrics.get('has_helpers', False),
            'timeout_density': r_policy.metrics.get('timeout_density', '0.0%'),
            'screenshot_calls': r_policy.metrics.get('screenshot_calls', 0),
            'gate_fails': len(gate_fails),
            'gate_warns': len(gate_warns),
        },
        'pass': (not count_mismatch
                 and not has_quality_issue and not has_duplicates
                 and not has_banned_pattern and not has_gate_fail),
        'xpath_coverage': xpath_coverage,
        'resolved_xpath_violations': resolved_xpath_violations if resolved_xpath_violations else None,
        'details': [],
    }

    # ── 控制台输出 ──
    print(f'\n===== 测试深度校验报告 =====')
    print(f'文件: {args.test_file}')
    print(f'最低操作数要求: {args.min_actions}')
    print(f'测试函数总数: {len(functions)}')
    if csv_count > 0:
        print(f'CSV 用例数: {csv_count}')
        if count_mismatch:
            print(f'⚠ 数量不匹配: {len(functions)} 个函数 vs {csv_count} 条用例'
                  f'（比例 {len(functions)/csv_count:.1f}x，期望约 1:1）')

    print(f'\n--- 各函数分析 ---')
    for func in functions:
        depth_ok = func.action_count >= args.min_actions
        has_any_assert = func.effective_assert_count > 0
        no_swallowing = not func.has_exception_swallowing
        no_trivial_only = not (func.assert_count > 0 and func.effective_assert_count == 0)
        quality_ok = no_swallowing and has_any_assert and no_trivial_only
        status = '✅' if (depth_ok and quality_ok) else '❌'
        print(f'{status} {func.name} (L{func.line_start}-L{func.line_end})')
        print(f'   操作数: {func.action_count}  断言数: {func.assert_count}'
              f' (有效: {func.effective_assert_count}, 永真: {func.trivial_assert_count})')
        if func.has_exception_swallowing:
            print(f'   ⚠ 检测到 try/except 吞异常（except 内无 raise/assert）')
        if func.assert_count > 0 and func.effective_assert_count == 0:
            print(f'   ⚠ 所有断言均为永真断言（如 expect(body).to_be_visible()）')
        if func.assert_count == 0:
            print(f'   ⚠ 无任何断言 — 操作链未验证业务结果，需补充有效断言')
        if func.actions:
            print(f'   操作: {", ".join(func.actions)}')
        else:
            print(f'   操作: (无实际操作)')

        report['details'].append({
            'name': func.name,
            'action_count': func.action_count,
            'assert_count': func.assert_count,
            'effective_assert_count': func.effective_assert_count,
            'trivial_assert_count': func.trivial_assert_count,
            'has_exception_swallowing': func.has_exception_swallowing,
            'actions': func.actions,
            'line_range': f'L{func.line_start}-L{func.line_end}',
            'pass': depth_ok and quality_ok,
        })

    print(f'\n--- 结论 ---')
    if duplicate_tests:
        print(f'❌ 不通过: 检测到重复的测试函数定义（pytest 只执行最后一个，旧逻辑残留会导致混乱）：')
        for name, locs in duplicate_tests.items():
            print(f'   - {name} 定义了 {len(locs)} 次: {", ".join(locs)}')
        print(f'   修复方式：删除旧定义，只保留最新版本。')
    if duplicate_helpers:
        print(f'❌ 不通过: 检测到重复的辅助函数定义：')
        for name, locs in duplicate_helpers.items():
            print(f'   - {name} 定义了 {len(locs)} 次: {", ".join(locs)}')
        print(f'   修复方式：删除旧定义，只保留最新版本。')
    if shallow_funcs:
        print(f'❌ 不通过: {len(shallow_funcs)} 个函数操作深度不足（< {args.min_actions} 步操作）：')
        for f in shallow_funcs:
            print(f'   - {f.name}: 仅 {f.action_count} 步操作')
    if swallowing_funcs:
        print(f'❌ 不通过: {len(swallowing_funcs)} 个函数存在 try/except 吞异常：')
        for f in swallowing_funcs:
            print(f'   - {f.name}')
        print(f'   脚本可能通过吞掉异常来伪装为通过，必须在 except 中 raise 或 assert。')
    if trivial_only_funcs:
        print(f'❌ 不通过: {len(trivial_only_funcs)} 个函数仅含永真断言：')
        for f in trivial_only_funcs:
            print(f'   - {f.name}: {f.assert_count} 个断言全部为永真')
        print(f'   expect(page.locator("body")).to_be_visible() 不是有效断言。')
    no_assert_non_trivial = [f for f in no_assert_funcs if f not in trivial_only_funcs]
    if no_assert_non_trivial:
        print(f'❌ 不通过: {len(no_assert_non_trivial)} 个函数无任何断言：')
        for f in no_assert_non_trivial:
            print(f'   - {f.name}: {f.action_count} 步操作但 0 个断言')
        print(f'   每个测试函数必须至少包含 1 个有效业务断言（expect/assert）。')
    if select_option_funcs:
        print(f'❌ 不通过: {len(select_option_funcs)} 个函数使用了 select_option（已禁止，自定义下拉框应用 click+click 模式）：')
        for f in select_option_funcs:
            print(f'   - {f.name}')
        print(f'   修复方式：将 .select_option() 替换为 click 触发器 + click 选项两步操作。')
    if domcontent_only_funcs:
        print(f'⚠ 警告: {len(domcontent_only_funcs)} 个函数仅使用 wait_for_load_state 而无业务元素等待：')
        for f in domcontent_only_funcs:
            print(f'   - {f.name}')
        print(f'   建议：SPA 页面应使用 page.locator("<业务元素>").wait_for(state="visible") 替代。')

    if xpath_coverage and xpath_coverage.get('resolved_steps', 0) > 0:
        ratio = xpath_coverage['coverage_ratio']
        print(f'\n--- smart XPath 覆盖率（趋势指标） ---')
        print(f'resolved 步骤数: {xpath_coverage["resolved_steps"]}')
        print(f'源码 xpath= 出现数: {xpath_coverage["xpath_locators"]}')
        print(f'覆盖率: {ratio:.0%}（仅趋势观察，不代表精确映射）')
    if resolved_xpath_violations:
        print(f'\n--- resolved 步骤 smart XPath 精确校验 ---')
        print(f'❌ {len(resolved_xpath_violations)} 个 resolved 步骤未使用对应的 smart XPath:')
        for v in resolved_xpath_violations[:10]:
            print(f'   {v["case_id"]} step {v["step_idx"]}: "{v["step_text"]}"')
            print(f'     expected xpath: {v["expected_xpath"]}')

    if gate_fails or gate_warns:
        print(f'\n--- 执行前质检门禁 ---')
        for check_name, details in gate_fails:
            print(f'❌ FAIL — {check_name}:')
            for d in details[:5]:
                print(f'   {d}')
        for check_name, details in gate_warns:
            print(f'⚠ WARN — {check_name}:')
            for d in details[:5]:
                print(f'   {d}')
        if gate_fails:
            print(f'\n门禁结论: {len(gate_fails)} 个 FAIL 项阻塞执行，必须修复后重新校验。')

    all_pass = (not count_mismatch and not has_quality_issue and not has_duplicates
                and not has_banned_pattern and not has_gate_fail)
    if all_pass:
        if count_mismatch:
            print(f'⚠ 警告: 函数数量与 CSV 用例数量不匹配。')
        else:
            print(f'✅ 通过: 所有 {len(functions)} 个函数均包含 >= {args.min_actions} 步操作，'
                  f'且至少有 1 个有效断言，无异常吞掉，无重复定义，无禁止模式。')

    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        print(f'\n报告已保存至: {args.output}')

    sys.exit(0 if report['pass'] else 1)


if __name__ == '__main__':
    import io as _io
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    elif sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    main()
