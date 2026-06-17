"""
测试 Mutation 真实集成
"""

import pytest
from unittest.mock import patch, MagicMock

from qa_agent.core.mutation import MutationRunner, MutationToolNotFound


class TestMutationRunner:
    """测试 MutationRunner"""

    def test_skipped_when_not_l3(self):
        """非 L3 模式跳过"""
        config = {'mutation': {'enabled_modes': ['L3']}}
        runner = MutationRunner(config, language='python')

        result = runner.run(mode='L1', diff_files=[], capabilities={'mutation': True})

        assert result['status'] == 'skipped'
        assert 'L1' in result['reason']
        assert result['pass'] is True

    def test_skipped_when_capabilities_false(self):
        """capabilities.mutation = false 跳过"""
        config = {'mutation': {'enabled_modes': ['L3']}}
        runner = MutationRunner(config, language='python')

        result = runner.run(mode='L3', diff_files=['src/a.py'], capabilities={'mutation': False})

        assert result['status'] == 'skipped'
        assert 'capabilities' in result['reason']

    @patch('qa_agent.core.mutation.shutil.which')
    def test_skipped_when_tool_not_found(self, mock_which):
        """工具未安装跳过（默认 on_tool_missing='skip'）"""
        mock_which.return_value = None

        config = {'mutation': {'enabled_modes': ['L3'], 'on_tool_missing': 'skip'}}
        runner = MutationRunner(config, language='python')

        result = runner.run(mode='L3', diff_files=['src/a.py'], capabilities={'mutation': True})

        assert result['status'] == 'skipped'
        assert result['reason'] == 'tool_not_found'
        assert result['pass'] is True  # 不阻断 L3

    @patch('qa_agent.core.mutation.shutil.which')
    def test_fail_when_tool_missing_and_strict(self, mock_which):
        """on_tool_missing='fail' 时工具未找到抛异常"""
        mock_which.return_value = None

        config = {'mutation': {'enabled_modes': ['L3'], 'on_tool_missing': 'fail'}}
        runner = MutationRunner(config, language='python')

        with pytest.raises(MutationToolNotFound):
            runner.run(mode='L3', diff_files=['src/a.py'], capabilities={'mutation': True})

    @patch('qa_agent.core.mutation.shutil.which')
    def test_no_target_files_skipped(self, mock_which):
        """无可变异源文件跳过"""
        mock_which.return_value = '/usr/bin/mutmut'

        config = {'mutation': {'enabled_modes': ['L3'], 'scope': 'diff'}}
        runner = MutationRunner(config, language='python')

        # 只有测试文件，无源文件
        result = runner.run(
            mode='L3',
            diff_files=['tests/test_a.py'],
            capabilities={'mutation': True}
        )

        assert result['status'] == 'skipped'
        assert '无可变异' in result['reason']

    def test_filter_source_files_excludes_tests(self):
        """过滤排除测试文件"""
        runner = MutationRunner({}, language='python')
        result = runner._filter_source_files([
            'src/app.py',
            'tests/test_app.py',
            'src/util.py',
            'test_helper.py',
            'spec/spec_a.py',
            'src/config.py'
        ])

        assert 'src/app.py' in result
        assert 'src/util.py' in result
        assert 'src/config.py' in result
        assert 'tests/test_app.py' not in result
        assert 'test_helper.py' not in result
        assert 'spec/spec_a.py' not in result

    def test_filter_source_files_by_extension(self):
        """按语言扩展名过滤"""
        runner_py = MutationRunner({}, language='python')
        runner_ts = MutationRunner({}, language='typescript')

        files = ['src/a.py', 'src/b.ts', 'src/c.js', 'src/d.rs']

        py_files = runner_py._filter_source_files(files)
        assert py_files == ['src/a.py']

        ts_files = runner_ts._filter_source_files(files)
        assert ts_files == ['src/b.ts']

    @patch('qa_agent.core.mutation.shutil.which')
    def test_detect_tool_priority(self, mock_which):
        """工具检测按优先级"""
        # mutmut 可用
        mock_which.side_effect = lambda cmd: '/usr/bin/mutmut' if cmd == 'mutmut' else None

        runner = MutationRunner({}, language='python')
        assert runner.detect_tool() == 'mutmut'

    @patch('qa_agent.core.mutation.shutil.which')
    def test_detect_tool_unknown_language(self, mock_which):
        """未知语言返回 None"""
        mock_which.return_value = None

        runner = MutationRunner({}, language='unknown')
        assert runner.detect_tool() is None

    def test_parse_mutmut_output(self):
        """解析 mutmut 输出"""
        runner = MutationRunner({}, language='python')

        output = "Mutation testing complete: 15 killed, 5 survived in 30.5s"
        result = runner._parse_mutmut_output(output)

        assert result['killed'] == 15
        assert result['survived'] == 5
        assert result['total'] == 20
