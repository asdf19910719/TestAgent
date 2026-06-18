#!/usr/bin/env python3
"""
WebUI 自动化测试 JSON 报告生成器

功能说明：
- 读取 conftest_webui_plugin.py 输出的原始测试结果 JSON
- 丰富元数据（目标 URL、浏览器、视口、平台等）
- 计算统计汇总（总数、通过、失败、错误、跳过、通过率、总耗时）
- 输出符合 webui-test-results-v1 schema 的结构化 JSON 报告

使用方式：
    python generate_webui_json_report.py \\
        --results qa/webui/session/execution/test_results_20240101.json \\
        --output qa/webui/session/execution/report_20240101.json \\
        --target-url https://example.com \\
        --browser chromium \\
        --viewport-width 1280 \\
        --viewport-height 720
"""
import argparse
import hashlib
import json
import platform
import re
import sys
from datetime import datetime
from pathlib import Path


# ── 报告 Schema 版本号 ────────────────────────────────────────────
SCHEMA_VERSION = "1.0"


def _generate_case_id(test_name: str, nodeid: str = "") -> str:
    """
    根据测试名称生成唯一的用例 ID。

    策略：
    - 优先使用 nodeid 生成哈希
    - 如果 nodeid 为空，使用 test_name 生成哈希
    - 取前 8 位短哈希，加上 "tc_" 前缀

    Args:
        test_name: 测试用例名称
        nodeid: pytest node ID（如 test_login.py::test_login_success）

    Returns:
        str: 用例 ID，如 "tc_a1b2c3d4"
    """
    source = nodeid if nodeid else test_name
    hash_hex = hashlib.md5(source.encode('utf-8')).hexdigest()[:8]
    # 清理测试名中的特殊字符，生成可读前缀
    safe_prefix = re.sub(r'[^a-zA-Z0-9_]', '_', test_name)[:32]
    return f"tc_{safe_prefix}_{hash_hex}"


def _normalize_status(raw_status: str) -> str:
    """
    标准化测试状态值。

    Args:
        raw_status: 原始状态字符串

    Returns:
        str: 标准化后的状态（passed/failed/error/skipped）
    """
    status_map = {
        'PASSED': 'passed',
        'FAILED': 'failed',
        'ERROR': 'error',
        'SKIPPED': 'skipped',
        'passed': 'passed',
        'failed': 'failed',
        'error': 'error',
        'skipped': 'skipped',
    }
    return status_map.get(raw_status, 'error')


def _extract_assertions(steps: list, error_message: str) -> list:
    """
    从步骤和错误信息中提取断言信息。

    如果步骤中有 assertion 类型的操作，直接提取；
    否则根据错误信息推断断言结果。

    Args:
        steps: 步骤列表
        error_message: 错误信息

    Returns:
        list: 断言信息列表
    """
    assertions = []

    # 从步骤中提取断言
    for step in steps:
        action_type = step.get('action_type', '')
        if action_type in ('assert', 'assertion', 'verify', 'check'):
            assertions.append({
                'expression': step.get('description', ''),
                'status': 'passed',
                'detail': step.get('value', ''),
            })

    # 如果有错误信息且没有从步骤中提取到断言，创建一个失败断言
    if error_message and not assertions:
        # 尝试从错误信息中提取 assert 语句
        assert_match = re.search(r'(assert .+)', error_message)
        expression = assert_match.group(1)[:200] if assert_match else '测试断言失败'
        assertions.append({
            'expression': expression,
            'status': 'failed',
            'detail': error_message[:500],
        })

    return assertions


def _transform_steps(raw_steps: list) -> list:
    """
    将原始步骤数据转换为标准化的步骤格式。

    Args:
        raw_steps: 原始步骤列表

    Returns:
        list: 标准化步骤列表
    """
    transformed = []
    for step in raw_steps:
        transformed.append({
            'step_no': step.get('step_no', len(transformed) + 1),
            'action': step.get('description', ''),
            'target': step.get('selector', ''),
            'status': step.get('status', 'done'),
            'screenshot': step.get('screenshot', ''),
        })
    return transformed


def generate_json_report(
    results: dict,
    target_url: str = "",
    browser: str = "chromium",
    viewport_width: int = 1920,
    viewport_height: int = 1080,
) -> dict:
    """
    从原始测试结果生成结构化 JSON 报告。

    Args:
        results: 原始测试结果字典（conftest_webui_plugin 输出格式）
        target_url: 被测目标 URL
        browser: 浏览器类型
        viewport_width: 视口宽度
        viewport_height: 视口高度

    Returns:
        dict: 符合 webui-test-results-v1 schema 的报告字典
    """
    raw_cases = results.get('test_cases', [])
    session_info = results.get('session_info', {})

    # ── 来源校验 + 一致性检查 ──
    consistency_warnings = []
    producer = results.get('_producer', '')
    if producer != 'conftest_webui_plugin':
        consistency_warnings.append(
            "CRITICAL: test_results 不是由 conftest_webui_plugin 生成"
            f"（_producer={producer!r}），结果可信度不可保证"
        )
    if not session_info:
        consistency_warnings.append(
            "WARN: test_results 缺少 session_info，可能不是 conftest plugin 的标准输出"
        )
    si_total = session_info.get('total_tests', -1)
    if si_total >= 0 and si_total != len(raw_cases):
        consistency_warnings.append(
            f"WARN: session_info.total_tests={si_total} "
            f"与 test_cases 长度={len(raw_cases)} 不一致"
        )

    # ── 构建元数据 ──
    metadata = {
        'timestamp': session_info.get('timestamp', datetime.now().isoformat()),
        'target_url': target_url,
        'browser': browser,
        'viewport': {
            'width': viewport_width,
            'height': viewport_height,
        },
        'platform': platform.platform(),
        'python_version': platform.python_version(),
    }

    # ── 转换用例数据 ──
    test_cases = []
    for raw_case in raw_cases:
        case_name = raw_case.get('name', '')
        case_nodeid = raw_case.get('nodeid', '')
        case_status = _normalize_status(raw_case.get('status', 'ERROR'))
        case_error = raw_case.get('error_message', '')
        raw_steps = raw_case.get('steps', [])

        # 转换步骤
        steps = _transform_steps(raw_steps)

        # 提取断言
        assertions = _extract_assertions(raw_steps, case_error)

        # 构建标准化用例
        test_case = {
            'case_id': raw_case.get('case_id', _generate_case_id(case_name, case_nodeid)),
            'title': case_name,
            'description': raw_case.get('description', ''),
            'status': case_status,
            'duration_ms': raw_case.get('duration_ms', 0),
            'steps': steps,
            'assertions': assertions,
            'screenshots': raw_case.get('screenshots', []),
            'video': raw_case.get('video', ''),
            'error_message': case_error,
        }
        test_cases.append(test_case)

    # ── 计算统计汇总 ──
    total = len(test_cases)
    passed = sum(1 for tc in test_cases if tc['status'] == 'passed')
    failed = sum(1 for tc in test_cases if tc['status'] == 'failed')
    error_count = sum(1 for tc in test_cases if tc['status'] == 'error')
    skipped = sum(1 for tc in test_cases if tc['status'] == 'skipped')
    pass_rate = round(passed / total * 100, 2) if total > 0 else 0.0
    total_duration_ms = sum(tc['duration_ms'] for tc in test_cases)

    summary = {
        'total': total,
        'passed': passed,
        'failed': failed,
        'error': error_count,
        'skipped': skipped,
        'pass_rate': pass_rate,
        'duration_ms': round(total_duration_ms, 2),
        'duration_display': f'{total_duration_ms / 1000:.1f}s' if total_duration_ms >= 1000 else f'{total_duration_ms:.0f}ms',
    }

    # ── 组装完整报告 ──
    report = {
        'schema_version': SCHEMA_VERSION,
        '_producer': 'generate_webui_json_report.py',
        'metadata': metadata,
        'summary': summary,
        'test_cases': test_cases,
        'consistency_warnings': consistency_warnings,
    }

    return report


def main():
    """
    命令行入口。
    解析参数并生成 JSON 报告文件。
    """
    parser = argparse.ArgumentParser(
        description='WebUI 自动化测试 JSON 报告生成器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
    python generate_webui_json_report.py \\
        --results test_results_20240101.json \\
        --output report_20240101.json \\
        --target-url https://example.com \\
        --browser chromium
        """
    )
    parser.add_argument(
        '--results', required=True,
        help='原始测试结果 JSON 文件路径（conftest_webui_plugin.py 输出）'
    )
    parser.add_argument(
        '--output', required=True,
        help='输出 JSON 报告文件路径'
    )
    parser.add_argument(
        '--target-url', default='',
        help='被测目标 URL 地址'
    )
    parser.add_argument(
        '--browser', default='chromium',
        help='浏览器类型（默认: chromium）'
    )
    parser.add_argument(
        '--viewport-width', type=int, default=1920,
        help='视口宽度（默认: 1920）'
    )
    parser.add_argument(
        '--viewport-height', type=int, default=1080,
        help='视口高度（默认: 1080）'
    )
    args = parser.parse_args()

    # 读取原始测试结果
    results_path = Path(args.results)
    if not results_path.exists():
        print(f'错误: 测试结果文件不存在: {results_path}', file=sys.stderr)
        sys.exit(1)

    try:
        raw_results = json.loads(results_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        print(f'错误: 测试结果 JSON 解析失败: {e}', file=sys.stderr)
        sys.exit(1)

    # 生成结构化 JSON 报告
    report = generate_json_report(
        results=raw_results,
        target_url=args.target_url,
        browser=args.browser,
        viewport_width=args.viewport_width,
        viewport_height=args.viewport_height,
    )

    # 写入输出文件
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    # 打印摘要信息
    summary = report['summary']
    print(f'JSON 报告已生成: {output_path}')
    print(f'  Schema: {SCHEMA_VERSION}')
    print(f'  总用例: {summary["total"]}')
    print(f'  通过: {summary["passed"]}  失败: {summary["failed"]}  '
          f'错误: {summary["error"]}  跳过: {summary["skipped"]}')
    print(f'  通过率: {summary["pass_rate"]}%')
    print(str(output_path))


if __name__ == '__main__':
    main()
