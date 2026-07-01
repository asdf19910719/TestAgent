"""
Gatekeeper 自检工具

防止 YAML status 与实际测试脚本不一致（虚标 implemented）
"""

from pathlib import Path
from typing import Dict, Any, List, Tuple
import yaml


def check_yaml_status_consistency(
    workspace: Path = Path('.')
) -> Dict[str, Any]:
    """
    检查 YAML 中的 automation.status 与实际测试脚本的一致性

    Returns:
        {
            'total_cases': 10,
            'implemented_claimed': 8,
            'script_found': 6,
            'inconsistent': [
                {'case_id': 'TC-001', 'claimed': 'implemented', 'actual': 'not_found'},
                ...
            ]
        }
    """
    cases_dir = workspace / 'qa' / 'cases'

    if not cases_dir.exists():
        return {
            'total_cases': 0,
            'implemented_claimed': 0,
            'script_found': 0,
            'inconsistent': [],
            'error': 'qa/cases/ 目录不存在'
        }

    # 读取所有用例 YAML
    yaml_files = list(cases_dir.rglob('*.yml'))

    total_cases = 0
    implemented_claimed = 0
    script_found = 0
    inconsistent = []

    for yaml_file in yaml_files:
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                case = yaml.safe_load(f)

            if not case:
                continue

            total_cases += 1
            case_id = case.get('id', yaml_file.stem)
            automation = case.get('automation', {})
            status = automation.get('status', 'manual')

            # 如果声称 implemented/scaffolded
            if status in ('implemented', 'scaffolded'):
                implemented_claimed += 1

                # 检查测试脚本是否存在
                test_file = automation.get('file', '')
                test_id = automation.get('test_id', '')

                if not test_file:
                    inconsistent.append({
                        'case_id': case_id,
                        'yaml_file': str(yaml_file.relative_to(workspace)),
                        'claimed': status,
                        'actual': 'no_file_specified',
                        'message': 'automation.file 未指定'
                    })
                    continue

                # 检查文件是否存在
                test_file_path = workspace / test_file
                if not test_file_path.exists():
                    inconsistent.append({
                        'case_id': case_id,
                        'yaml_file': str(yaml_file.relative_to(workspace)),
                        'claimed': status,
                        'actual': 'file_not_found',
                        'message': f'测试文件不存在: {test_file}'
                    })
                    continue

                # 检查 test_id 是否在文件中
                if test_id:
                    try:
                        test_content = test_file_path.read_text(encoding='utf-8', errors='ignore')
                        if test_id not in test_content:
                            inconsistent.append({
                                'case_id': case_id,
                                'yaml_file': str(yaml_file.relative_to(workspace)),
                                'claimed': status,
                                'actual': 'test_id_not_found',
                                'message': f'test_id "{test_id}" 在文件中找不到'
                            })
                            continue
                    except Exception as e:
                        inconsistent.append({
                            'case_id': case_id,
                            'yaml_file': str(yaml_file.relative_to(workspace)),
                            'claimed': status,
                            'actual': 'read_error',
                            'message': f'文件读取失败: {e}'
                        })
                        continue

                # 检查通过
                script_found += 1

        except Exception as e:
            print(f"[SelfCheck] YAML 解析失败 {yaml_file}: {e}")
            continue

    return {
        'total_cases': total_cases,
        'implemented_claimed': implemented_claimed,
        'script_found': script_found,
        'inconsistent_count': len(inconsistent),
        'inconsistent': inconsistent,
        'consistency_rate': script_found / implemented_claimed if implemented_claimed > 0 else 1.0
    }


def check_existing_tests_coverage(
    workspace: Path = Path('.')
) -> Dict[str, Any]:
    """
    检查已有测试文件是否都纳入 YAML 管理

    Returns:
        {
            'existing_test_files': 50,
            'covered_in_yaml': 30,
            'uncovered': [
                {'file': 'tests/unit/utils.test.ts', 'reason': '未在 YAML 中引用'},
                ...
            ]
        }
    """
    from qa_agent.core.test_discovery import discover_tests

    # 发现已有测试文件
    existing_tests = discover_tests(workspace)

    # 读取所有 YAML 中引用的测试文件
    cases_dir = workspace / 'qa' / 'cases'
    yaml_referenced_files = set()

    if cases_dir.exists():
        for yaml_file in cases_dir.rglob('*.yml'):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    case = yaml.safe_load(f)

                automation = case.get('automation', {})
                test_file = automation.get('file', '')
                if test_file:
                    yaml_referenced_files.add(test_file)
            except:
                continue

    # 对比
    uncovered = []
    # existing_tests 是一个列表，每个元素是 {'file': '...', 'level': '...', ...}
    existing_test_files = [t.get('file', '') for t in existing_tests if t.get('file')]

    for test_file in existing_test_files:
        if test_file not in yaml_referenced_files:
            uncovered.append({
                'file': test_file,
                'reason': '未在任何 YAML 用例中引用'
            })

    return {
        'existing_test_files': len(existing_test_files),
        'covered_in_yaml': len(yaml_referenced_files),
        'uncovered_count': len(uncovered),
        'uncovered': uncovered,
        'coverage_rate': len(yaml_referenced_files) / len(existing_test_files) if existing_test_files else 1.0
    }


def check_l3_main_flows(
    workspace: Path = Path('.')
) -> Tuple[bool, str]:
    """
    检查 L3 主流程清单是否存在（防止 AI 跳过主流程验证）

    Returns:
        (exists: bool, message: str)
    """
    main_flows_file = workspace / 'qa' / 'run' / 'main_flows.md'

    if not main_flows_file.exists():
        return False, "qa/run/main_flows.md 不存在（L3 必须显式列出主流程）"

    try:
        content = main_flows_file.read_text(encoding='utf-8')
        lines = [l.strip() for l in content.split('\n') if l.strip() and not l.strip().startswith('#')]

        if len(lines) < 3:
            return False, f"主流程清单只有 {len(lines)} 条（通常应有 3+ 条核心流程）"

        return True, f"主流程清单已建立（{len(lines)} 条）"

    except Exception as e:
        return False, f"主流程清单读取失败: {e}"


def run_full_selfcheck(
    workspace: Path = Path('.')
) -> Dict[str, Any]:
    """
    运行完整自检（L3 模式前置检查）

    Returns:
        {
            'status': 'PASS' | 'WARN' | 'BLOCKED',
            'checks': {...},
            'summary': str
        }
    """
    results = {}
    issues = []

    # 检查 1: YAML status 一致性
    print("[SelfCheck] 检查 YAML automation.status 一致性...")
    yaml_check = check_yaml_status_consistency(workspace)
    results['yaml_consistency'] = yaml_check

    if yaml_check.get('inconsistent_count', 0) > 0:
        rate = yaml_check.get('consistency_rate', 0)
        issues.append(f"YAML 一致性: {rate:.1%} ({yaml_check['inconsistent_count']} 个不一致)")

    # 检查 2: 已有测试覆盖
    print("[SelfCheck] 检查已有测试文件覆盖...")
    coverage_check = check_existing_tests_coverage(workspace)
    results['existing_tests_coverage'] = coverage_check

    if coverage_check.get('uncovered_count', 0) > 0:
        rate = coverage_check.get('coverage_rate', 0)
        issues.append(f"已有测试覆盖: {rate:.1%} ({coverage_check['uncovered_count']} 个文件未纳入 YAML)")

    # 检查 3: L3 主流程清单
    print("[SelfCheck] 检查 L3 主流程清单...")
    main_flows_ok, main_flows_msg = check_l3_main_flows(workspace)
    results['main_flows'] = {
        'exists': main_flows_ok,
        'message': main_flows_msg
    }

    if not main_flows_ok:
        issues.append(f"L3 主流程: {main_flows_msg}")

    # 综合判定
    if len(issues) == 0:
        status = 'PASS'
        summary = "✅ 所有自检通过"
    elif len(issues) <= 1:
        status = 'WARN'
        summary = f"⚠️ 发现 {len(issues)} 个潜在问题（可继续，但建议修复）"
    else:
        status = 'BLOCKED'
        summary = f"❌ 发现 {len(issues)} 个问题（建议先修复再执行 L3）"

    results['status'] = status
    results['summary'] = summary
    results['issues'] = issues

    return results


def generate_selfcheck_report(
    selfcheck_result: Dict[str, Any],
    output_path: Path = None
) -> Path:
    """
    生成自检报告
    """
    if output_path is None:
        output_path = Path('qa/run/selfcheck_report.md')

    yaml_check = selfcheck_result.get('yaml_consistency', {})
    coverage_check = selfcheck_result.get('existing_tests_coverage', {})
    main_flows = selfcheck_result.get('main_flows', {})

    report = f"""# Gatekeeper 自检报告

**执行时间**: {__import__('datetime').datetime.now().isoformat()}
**判定**: {selfcheck_result['status']}

## 摘要

{selfcheck_result['summary']}

## 检查详情

### 1. YAML automation.status 一致性

- 总用例数: {yaml_check.get('total_cases', 0)}
- 声称 implemented/scaffolded: {yaml_check.get('implemented_claimed', 0)}
- 实际找到脚本: {yaml_check.get('script_found', 0)}
- 一致性: {yaml_check.get('consistency_rate', 0):.1%}

"""

    if yaml_check.get('inconsistent'):
        report += "#### 不一致的用例\n\n"
        for item in yaml_check['inconsistent'][:10]:  # 最多显示 10 个
            report += f"- **{item['case_id']}**: {item['message']}\n"

        if len(yaml_check['inconsistent']) > 10:
            report += f"\n（还有 {len(yaml_check['inconsistent']) - 10} 个...）\n"

    report += f"""
### 2. 已有测试文件覆盖

- 已有测试文件: {coverage_check.get('existing_test_files', 0)}
- YAML 中引用: {coverage_check.get('covered_in_yaml', 0)}
- 未纳入管理: {coverage_check.get('uncovered_count', 0)}
- 覆盖率: {coverage_check.get('coverage_rate', 0):.1%}

"""

    if coverage_check.get('uncovered'):
        report += "#### 未纳入 YAML 的测试文件\n\n"
        for item in coverage_check['uncovered'][:10]:
            report += f"- {item['file']}\n"

        if len(coverage_check['uncovered']) > 10:
            report += f"\n（还有 {len(coverage_check['uncovered']) - 10} 个...）\n"

    report += f"""
### 3. L3 主流程清单

- 状态: {'✅ 已建立' if main_flows.get('exists') else '❌ 缺失'}
- 详情: {main_flows.get('message', 'N/A')}

## 建议

"""

    if selfcheck_result['status'] == 'PASS':
        report += "✅ 所有检查通过，可以执行 L3 测试。\n"
    elif selfcheck_result['status'] == 'WARN':
        report += "⚠️ 发现一些潜在问题，建议先修复：\n\n"
        for issue in selfcheck_result.get('issues', []):
            report += f"- {issue}\n"
    else:  # BLOCKED
        report += "❌ 发现严重问题，必须先修复再执行 L3：\n\n"
        for issue in selfcheck_result.get('issues', []):
            report += f"- {issue}\n"

    # 写入文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding='utf-8')

    return output_path
