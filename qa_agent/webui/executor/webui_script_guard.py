#!/usr/bin/env python3
"""
WebUI 测试脚本静态审计（Script Guard）

在 batch_run 步骤 4.5 之后、pytest 执行前运行。
6 条规则分 ERROR（阻断） / WARNING（播报） 两级。

用法:
    python webui_script_guard.py --test-file test_webui.py [--output guard_result.json]
"""
import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


R1_SKIP_THRESHOLD = 5
R2_HARD_WAIT_THRESHOLD = 3
R4_FRAGILE_SELECTOR_THRESHOLD = 3
R6_HARDCODED_DATA_THRESHOLD = 3


def _count_pattern(source: str, pattern: str) -> list[int]:
    """返回 pattern 在 source 中匹配到的所有行号"""
    lines = []
    for i, line in enumerate(source.splitlines(), 1):
        if re.search(pattern, line):
            lines.append(i)
    return lines


def rule_r1_excessive_skip(source: str) -> dict | None:
    """WARNING: 单文件 pytest.skip() 调用超过阈值"""
    hits = _count_pattern(source, r'pytest\.skip\s*\(')
    if len(hits) > R1_SKIP_THRESHOLD:
        return {
            "rule": "R1", "level": "WARNING",
            "message": f"pytest.skip() 调用 {len(hits)} 次（>{R1_SKIP_THRESHOLD}），可能过度使用 skip 兜底",
            "lines": hits,
        }
    return None


def rule_r2_hard_wait(source: str) -> dict | None:
    """WARNING: wait_for_timeout 硬等待超过阈值"""
    hits = _count_pattern(source, r'wait_for_timeout\s*\(')
    if len(hits) > R2_HARD_WAIT_THRESHOLD:
        return {
            "rule": "R2", "level": "WARNING",
            "message": f"wait_for_timeout 硬等待 {len(hits)} 次（>{R2_HARD_WAIT_THRESHOLD}），应使用 expect() 条件等待",
            "lines": hits,
        }
    return None


def rule_r3_no_assertion(source: str) -> dict | None:
    """ERROR: test 函数无 expect / assert 调用"""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    empty_tests = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith('test_'):
                continue
            body_source = ast.get_source_segment(source, node)
            if body_source is None:
                continue
            has_assert = bool(re.search(r'\bassert\b|\bexpect\s*\(', body_source))
            if not has_assert:
                empty_tests.append({"name": node.name, "line": node.lineno})

    if empty_tests:
        names = [t["name"] for t in empty_tests]
        return {
            "rule": "R3", "level": "ERROR",
            "message": f"以下 test 函数无 assert/expect 断言: {', '.join(names)}",
            "lines": [t["line"] for t in empty_tests],
        }
    return None


def rule_r4_fragile_selector(source: str) -> dict | None:
    """WARNING: 主路径依赖 .first / .nth(0) 超过阈值"""
    hits = _count_pattern(source, r'\.(first|nth\s*\(\s*0\s*\))')
    if len(hits) > R4_FRAGILE_SELECTOR_THRESHOLD:
        return {
            "rule": "R4", "level": "WARNING",
            "message": f".first/.nth(0) 使用 {len(hits)} 次（>{R4_FRAGILE_SELECTOR_THRESHOLD}），选择器可能不够精确",
            "lines": hits,
        }
    return None


def rule_r5_provenance_deleted(source: str) -> dict | None:
    """ERROR: AQE-SKELETON provenance 标记被删"""
    if 'AQE-SKELETON' not in source and 'aqe-skeleton' not in source.lower():
        has_test_func = bool(re.search(r'def test_', source))
        if has_test_func:
            return {
                "rule": "R5", "level": "ERROR",
                "message": "缺少 AQE-SKELETON provenance 标记，骨架来源不可追溯",
                "lines": [],
            }
    return None


_R6_EXCLUDE_KEYWORDS = [
    '测试', '验证', '检查', '确认', '断言', '期望',
    '页面', '按钮', '输入', '选择', '步骤', '等待',
    '状态', '提示', '成功', '失败', '取消', '保存',
    '删除', '新增', '编辑', '提交', '搜索', '查询',
    '操作', '返回', '刷新', '加载', '登录', '退出',
    '复制', '上传',
]

_R6_ASSERTION_PATTERN = re.compile(
    r'(\.to_have_text|\.to_contain_text|\.text_content|assert\b|expect\s*\()',
)


def rule_r6_hardcoded_data(source: str) -> dict | None:
    """WARNING: 硬编码特定任务名/数据 ID（排除断言预期值）"""
    cn_var_pattern = r'["\'][\u4e00-\u9fa5]{4,}["\']'
    hits = []
    for i, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        if _R6_ASSERTION_PATTERN.search(line):
            continue
        matches = re.findall(cn_var_pattern, line)
        for m in matches:
            if any(kw in m for kw in _R6_EXCLUDE_KEYWORDS):
                continue
            hits.append(i)
            break

    if len(hits) > R6_HARDCODED_DATA_THRESHOLD:
        return {
            "rule": "R6", "level": "WARNING",
            "message": f"可能硬编码了 {len(hits)} 处业务数据（中文字符串），换环境可能失败",
            "lines": hits[:10],
        }
    return None


ALL_RULES = [
    rule_r1_excessive_skip,
    rule_r2_hard_wait,
    rule_r3_no_assertion,
    rule_r4_fragile_selector,
    rule_r5_provenance_deleted,
    rule_r6_hardcoded_data,
]


def run_guard(test_file: str) -> dict:
    path = Path(test_file)
    if not path.exists():
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "test_file": str(path),
            "passed": False,
            "errors": [{"rule": "GUARD", "level": "ERROR",
                        "message": f"文件不存在: {path}", "lines": []}],
            "warnings": [],
        }

    source = path.read_text(encoding='utf-8')
    errors = []
    warnings = []

    for rule_fn in ALL_RULES:
        result = rule_fn(source)
        if result:
            if result["level"] == "ERROR":
                errors.append(result)
            else:
                warnings.append(result)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_file": str(path.name),
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description="WebUI 测试脚本静态审计")
    parser.add_argument('--test-file', required=True, help="待审计的测试脚本路径")
    parser.add_argument('--output', default='', help="结果输出 JSON 路径")
    args = parser.parse_args()

    result = run_guard(args.test_file)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n[Script Guard] {result['test_file']}")
    if result["errors"]:
        for e in result["errors"]:
            print(f"  ERROR {e['rule']}: {e['message']}")
    if result["warnings"]:
        for w in result["warnings"]:
            print(f"  WARNING {w['rule']}: {w['message']}")
    if result["passed"]:
        print("  PASSED (0 errors)")
    else:
        print(f"  BLOCKED ({len(result['errors'])} errors)")

    sys.exit(0 if result["passed"] else 1)


if __name__ == '__main__':
    main()
