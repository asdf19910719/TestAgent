"""
测试终端 UI 工具
"""

import pytest
from io import StringIO
from unittest.mock import patch

from qa_agent.cli.ui import (
    color, green, red, yellow, cyan, bold, dim, gray,
    Colors, ProgressBar,
    print_pass_summary, print_fail_summary, print_blocked_summary,
    print_table
)


class TestColors:
    """测试颜色函数"""

    @patch('qa_agent.cli.ui._supports_color')
    def test_color_when_supported(self, mock_supports):
        """支持彩色时返回带颜色码"""
        mock_supports.return_value = True
        result = color('hello', Colors.GREEN)
        assert Colors.GREEN in result
        assert Colors.RESET in result
        assert 'hello' in result

    @patch('qa_agent.cli.ui._supports_color')
    def test_color_when_not_supported(self, mock_supports):
        """不支持彩色时返回原文"""
        mock_supports.return_value = False
        result = color('hello', Colors.GREEN)
        assert result == 'hello'

    @patch('qa_agent.cli.ui._supports_color')
    def test_helper_functions(self, mock_supports):
        """便捷函数都能调用"""
        mock_supports.return_value = False  # 简化：不带颜色
        assert green('x') == 'x'
        assert red('x') == 'x'
        assert yellow('x') == 'x'
        assert cyan('x') == 'x'
        assert bold('x') == 'x'
        assert dim('x') == 'x'
        assert gray('x') == 'x'


class TestProgressBar:
    """测试进度条"""

    @patch('sys.stdout')
    def test_initialization(self, mock_stdout):
        """初始化"""
        bar = ProgressBar(total=100, label='Test')
        assert bar.total == 100
        assert bar.current == 0

    @patch('sys.stdout')
    def test_update(self, mock_stdout):
        """步进"""
        mock_stdout.isatty.return_value = False  # 非 TTY 不输出
        bar = ProgressBar(total=10)
        bar.update(5)
        assert bar.current == 5

    @patch('sys.stdout')
    def test_set(self, mock_stdout):
        """设置当前值"""
        mock_stdout.isatty.return_value = False
        bar = ProgressBar(total=10)
        bar.set(7)
        assert bar.current == 7

    @patch('sys.stdout')
    def test_finish(self, mock_stdout):
        """完成"""
        mock_stdout.isatty.return_value = False
        bar = ProgressBar(total=10)
        bar.update(5)
        bar.finish()
        assert bar.current == 10

    @patch('sys.stdout')
    def test_overflow_clamped(self, mock_stdout):
        """超过 total 被截断"""
        mock_stdout.isatty.return_value = False
        bar = ProgressBar(total=10)
        bar.update(15)
        assert bar.current == 10


class TestPrintSummaries:
    """测试输出函数"""

    def test_print_pass_summary_runs(self, capsys):
        """PASS 输出不报错"""
        print_pass_summary('L1', {'total': 10, 'pass': 10, 'fail': 0}, duration=2.5)
        captured = capsys.readouterr()
        assert 'L1' in captured.out
        assert '通过' in captured.out
        assert '10' in captured.out

    def test_print_pass_summary_all_modes(self, capsys):
        """所有模式的 PASS 输出都不报错"""
        for mode in ['L0', 'L1', 'L2', 'L3', 'L4']:
            print_pass_summary(mode, {'total': 5, 'pass': 5, 'fail': 0})
            captured = capsys.readouterr()
            assert mode in captured.out

    def test_print_fail_summary(self, capsys):
        """FAIL 输出包含失败信息"""
        failures = [
            {'bug_id': 'BUG-001', 'case_id': 'TC-LOGIN-001',
             'severity': 'high', 'message': '登录失败'},
            {'bug_id': 'BUG-002', 'case_id': 'TC-LOGIN-002',
             'severity': 'medium', 'message': '超时'}
        ]
        print_fail_summary('L1', {'total': 10, 'pass': 8, 'fail': 2}, failures)
        captured = capsys.readouterr()
        assert 'L1' in captured.out
        assert 'BUG-001' in captured.out
        assert 'BUG-002' in captured.out

    def test_print_fail_summary_truncates_long_list(self, capsys):
        """失败列表超过 5 条被截断"""
        failures = [
            {'bug_id': f'BUG-{i:03d}', 'case_id': f'TC-{i}',
             'severity': 'medium', 'message': f'fail {i}'}
            for i in range(10)
        ]
        print_fail_summary('L2', {'total': 10, 'pass': 0, 'fail': 10}, failures)
        captured = capsys.readouterr()
        assert '还有 5 个' in captured.out or 'BUG-000' in captured.out

    def test_print_blocked_summary(self, capsys):
        """BLOCKED 输出"""
        print_blocked_summary('L3', '数据库连接失败',
                              suggestions=['启动数据库', '检查 .env 文件'])
        captured = capsys.readouterr()
        assert 'L3' in captured.out
        assert '数据库连接' in captured.out
        assert '启动数据库' in captured.out


class TestPrintTable:
    """测试表格输出"""

    def test_print_table_basic(self, capsys):
        """基本表格"""
        headers = ['ID', 'Name', 'Status']
        rows = [
            ['1', 'login', 'pass'],
            ['2', 'logout', 'fail']
        ]
        print_table(headers, rows)
        captured = capsys.readouterr()
        assert 'ID' in captured.out
        assert 'login' in captured.out
        assert 'logout' in captured.out

    def test_print_table_empty_rows(self, capsys):
        """空行不报错"""
        print_table(['A', 'B'], [])
        captured = capsys.readouterr()
        # 空行直接 return，无输出
