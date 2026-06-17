"""
测试报告解析器
"""

import pytest
import json

from qa_agent.core.report_parser import (
    VitestReportParser, PlaywrightReportParser,
    PytestReportParser, TapReportParser
)


class TestVitestReportParser:
    """Vitest 报告解析"""

    def test_parse_passing_tests(self):
        """解析全通过的测试报告"""
        json_output = json.dumps({
            'numTotalTests': 3,
            'numPassedTests': 3,
            'numFailedTests': 0,
            'numPendingTests': 0,
            'testResults': [{
                'assertionResults': [
                    {'fullName': 'login should work', 'status': 'passed', 'duration': 50, 'failureMessages': []},
                    {'fullName': 'logout should work', 'status': 'passed', 'duration': 30, 'failureMessages': []},
                    {'fullName': 'auth check', 'status': 'passed', 'duration': 20, 'failureMessages': []}
                ]
            }]
        })

        result = VitestReportParser.parse(json_output)

        assert result['total'] == 3
        assert result['pass'] == 3
        assert result['fail'] == 0
        assert len(result['cases']) == 3
        assert all(c['status'] == 'pass' for c in result['cases'])

    def test_parse_with_failures(self):
        """解析含失败的报告"""
        json_output = json.dumps({
            'numTotalTests': 2,
            'numPassedTests': 1,
            'numFailedTests': 1,
            'numPendingTests': 0,
            'testResults': [{
                'assertionResults': [
                    {'fullName': 'test1', 'status': 'passed', 'duration': 10, 'failureMessages': []},
                    {'fullName': 'test2', 'status': 'failed', 'duration': 20,
                     'failureMessages': ['Expected true, got false']}
                ]
            }]
        })

        result = VitestReportParser.parse(json_output)

        assert result['fail'] == 1
        failed_cases = [c for c in result['cases'] if c['status'] == 'fail']
        assert len(failed_cases) == 1
        assert 'Expected true' in failed_cases[0]['error']

    def test_parse_invalid_json(self):
        """解析失败时返回 parse_error"""
        result = VitestReportParser.parse('not json')

        assert 'parse_error' in result
        assert result['total'] == 0


class TestPytestReportParser:
    """Pytest 报告解析"""

    def test_parse_junit_xml_passing(self):
        """解析全通过的 JUnit XML"""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" tests="2" failures="0" errors="0" skipped="0" time="0.5">
    <testcase classname="test_foo" name="test_one" time="0.1"/>
    <testcase classname="test_foo" name="test_two" time="0.2"/>
  </testsuite>
</testsuites>'''

        result = PytestReportParser.parse_junit_xml(xml)

        assert result['total'] == 2
        assert result['pass'] == 2
        assert result['fail'] == 0
        assert len(result['cases']) == 2

    def test_parse_junit_xml_with_failure(self):
        """解析含失败的 JUnit XML"""
        xml = '''<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="2" failures="1" errors="0" skipped="0" time="1.0">
  <testcase classname="test_auth" name="test_login" time="0.1"/>
  <testcase classname="test_auth" name="test_logout" time="0.2">
    <failure message="AssertionError: Expected logged out">
Traceback...
    </failure>
  </testcase>
</testsuite>'''

        result = PytestReportParser.parse_junit_xml(xml)

        assert result['total'] == 2
        assert result['fail'] == 1
        failed = [c for c in result['cases'] if c['status'] == 'fail']
        assert len(failed) == 1
        assert 'AssertionError' in failed[0]['error']

    def test_parse_text_output(self):
        """解析 pytest 文本输出"""
        text = '''
tests/test_auth.py::test_login PASSED
tests/test_auth.py::test_logout FAILED
tests/test_auth.py::test_skip SKIPPED

===== 1 passed, 1 failed, 1 skipped in 0.5s =====
'''
        result = PytestReportParser.parse_text_output(text)

        assert result['pass'] == 1
        assert result['fail'] == 1
        assert result['skip'] == 1


class TestPlaywrightReportParser:
    """Playwright 报告解析"""

    def test_parse_basic(self):
        """解析基本 playwright JSON"""
        json_output = json.dumps({
            'stats': {'expected': 2, 'unexpected': 1, 'skipped': 0},
            'suites': [{
                'specs': [{
                    'title': 'login flow',
                    'tests': [{
                        'results': [{
                            'status': 'passed',
                            'duration': 1000,
                        }]
                    }]
                }, {
                    'title': 'logout flow',
                    'tests': [{
                        'results': [{
                            'status': 'failed',
                            'duration': 500,
                            'error': {'message': 'Timeout'}
                        }]
                    }]
                }]
            }]
        })

        result = PlaywrightReportParser.parse(json_output)

        assert result['pass'] == 2
        assert result['fail'] == 1


class TestTapReportParser:
    """TAP 解析（Generic Adapter 用）"""

    def test_parse_basic_tap(self):
        """解析基础 TAP 输出"""
        tap = '''1..3
ok 1 - test login
ok 2 - test logout
not ok 3 - test register
'''
        result = TapReportParser.parse(tap)

        assert result['total'] == 3
        assert result['pass'] == 2
        assert result['fail'] == 1
        assert result['cases'][0]['status'] == 'pass'
        assert result['cases'][2]['status'] == 'fail'
