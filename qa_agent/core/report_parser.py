"""
报告解析器：解析 vitest/playwright/pytest 输出
"""

import json
import re
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional


class VitestReportParser:
    """Vitest JSON 报告解析"""

    @staticmethod
    def parse(json_output: str) -> Dict[str, Any]:
        """
        解析 vitest --reporter=json 输出

        Returns:
            {
                'total': int,
                'pass': int,
                'fail': int,
                'skip': int,
                'cases': [
                    {'case_id': str, 'status': 'pass'|'fail'|'skip',
                     'duration_ms': int, 'error': str}
                ]
            }
        """
        try:
            data = json.loads(json_output)
        except json.JSONDecodeError as e:
            return {'total': 0, 'pass': 0, 'fail': 0, 'skip': 0, 'cases': [],
                    'parse_error': str(e)}

        cases = []
        for test_result in data.get('testResults', []):
            for test in test_result.get('assertionResults', []):
                status = 'pass' if test['status'] == 'passed' else (
                    'skip' if test['status'] == 'pending' else 'fail'
                )
                cases.append({
                    'case_id': test.get('fullName', test.get('title', '')),
                    'status': status,
                    'duration_ms': test.get('duration', 0),
                    'error': '\n'.join(test.get('failureMessages', []))
                })

        return {
            'total': data.get('numTotalTests', 0),
            'pass': data.get('numPassedTests', 0),
            'fail': data.get('numFailedTests', 0),
            'skip': data.get('numPendingTests', 0),
            'cases': cases
        }


class PlaywrightReportParser:
    """Playwright JSON 报告解析"""

    @staticmethod
    def parse(json_output: str) -> Dict[str, Any]:
        """
        解析 playwright --reporter=json 输出
        """
        try:
            data = json.loads(json_output)
        except json.JSONDecodeError as e:
            return {'total': 0, 'pass': 0, 'fail': 0, 'skip': 0, 'cases': [],
                    'parse_error': str(e)}

        cases = []
        stats = data.get('stats', {})

        # 递归遍历 suites
        def walk_suites(suites):
            for suite in suites:
                for spec in suite.get('specs', []):
                    for test in spec.get('tests', []):
                        for result in test.get('results', []):
                            status_map = {
                                'passed': 'pass',
                                'failed': 'fail',
                                'skipped': 'skip',
                                'timedOut': 'fail',
                                'interrupted': 'fail'
                            }
                            cases.append({
                                'case_id': spec.get('title', ''),
                                'status': status_map.get(result['status'], 'fail'),
                                'duration_ms': result.get('duration', 0),
                                'error': result.get('error', {}).get('message', '')
                            })
                walk_suites(suite.get('suites', []))

        walk_suites(data.get('suites', []))

        return {
            'total': stats.get('expected', 0) + stats.get('unexpected', 0) + stats.get('skipped', 0),
            'pass': stats.get('expected', 0),
            'fail': stats.get('unexpected', 0),
            'skip': stats.get('skipped', 0),
            'cases': cases
        }


class PytestReportParser:
    """Pytest JUnit XML 报告解析"""

    @staticmethod
    def parse_junit_xml(xml_output: str) -> Dict[str, Any]:
        """
        解析 pytest --junitxml=- 输出
        """
        try:
            root = ET.fromstring(xml_output)
        except ET.ParseError as e:
            return {'total': 0, 'pass': 0, 'fail': 0, 'skip': 0, 'cases': [],
                    'parse_error': str(e)}

        # JUnit XML 可能有多种根节点
        if root.tag == 'testsuites':
            testsuite = root.find('testsuite')
        else:
            testsuite = root

        if testsuite is None:
            return {'total': 0, 'pass': 0, 'fail': 0, 'skip': 0, 'cases': []}

        total = int(testsuite.get('tests', 0))
        failures = int(testsuite.get('failures', 0))
        errors = int(testsuite.get('errors', 0))
        skipped = int(testsuite.get('skipped', 0))
        passed = total - failures - errors - skipped

        cases = []
        for testcase in testsuite.findall('testcase'):
            classname = testcase.get('classname', '')
            name = testcase.get('name', '')
            duration = float(testcase.get('time', 0)) * 1000  # 秒 → 毫秒

            # 判定状态
            failure_node = testcase.find('failure')
            error_node = testcase.find('error')

            if failure_node is not None or error_node is not None:
                status = 'fail'
                fail_node = failure_node if failure_node is not None else error_node
                error = fail_node.get('message', '')
                if fail_node.text:
                    error += '\n' + fail_node.text
            elif testcase.find('skipped') is not None:
                status = 'skip'
                error = ''
            else:
                status = 'pass'
                error = ''

            cases.append({
                'case_id': f"{classname}::{name}" if classname else name,
                'status': status,
                'duration_ms': int(duration),
                'error': error.strip()
            })

        return {
            'total': total,
            'pass': passed,
            'fail': failures + errors,
            'skip': skipped,
            'cases': cases
        }

    @staticmethod
    def parse_text_output(text: str) -> Dict[str, Any]:
        """
        解析 pytest 纯文本输出（兜底）

        匹配类似：
            tests/test_foo.py::test_bar PASSED
            tests/test_foo.py::test_baz FAILED
            ===== 5 passed, 1 failed in 0.5s =====
        """
        cases = []
        # 匹配 testcase 行
        case_pattern = re.compile(r'^([^\s]+)\s+(PASSED|FAILED|SKIPPED|ERROR)', re.MULTILINE)

        for match in case_pattern.finditer(text):
            case_id = match.group(1)
            status_raw = match.group(2)
            status_map = {
                'PASSED': 'pass',
                'FAILED': 'fail',
                'SKIPPED': 'skip',
                'ERROR': 'fail'
            }
            cases.append({
                'case_id': case_id,
                'status': status_map.get(status_raw, 'fail'),
                'duration_ms': 0,
                'error': ''
            })

        # 提取统计
        passed_match = re.search(r'(\d+)\s+passed', text)
        passed = int(passed_match.group(1)) if passed_match else 0

        fail_match = re.search(r'(\d+)\s+failed', text)
        failed = int(fail_match.group(1)) if fail_match else 0

        skip_match = re.search(r'(\d+)\s+skipped', text)
        skipped = int(skip_match.group(1)) if skip_match else 0

        return {
            'total': passed + failed + skipped,
            'pass': passed,
            'fail': failed,
            'skip': skipped,
            'cases': cases if cases else None
        }


class TapReportParser:
    """TAP (Test Anything Protocol) 解析"""

    @staticmethod
    def parse(text: str) -> Dict[str, Any]:
        """
        解析 TAP 输出（用于 Generic Adapter）

        Format:
            1..N
            ok 1 - test name
            not ok 2 - test name
        """
        cases = []
        passed = 0
        failed = 0

        for line in text.splitlines():
            line = line.strip()
            if line.startswith('ok '):
                # ok N - description
                match = re.match(r'ok\s+(\d+)\s*-?\s*(.*)', line)
                if match:
                    cases.append({
                        'case_id': match.group(2) or f"test_{match.group(1)}",
                        'status': 'pass',
                        'duration_ms': 0,
                        'error': ''
                    })
                    passed += 1
            elif line.startswith('not ok '):
                match = re.match(r'not ok\s+(\d+)\s*-?\s*(.*)', line)
                if match:
                    cases.append({
                        'case_id': match.group(2) or f"test_{match.group(1)}",
                        'status': 'fail',
                        'duration_ms': 0,
                        'error': ''
                    })
                    failed += 1

        return {
            'total': passed + failed,
            'pass': passed,
            'fail': failed,
            'skip': 0,
            'cases': cases
        }
