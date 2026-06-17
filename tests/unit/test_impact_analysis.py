"""
测试影响面分析算法
"""

import pytest
from unittest.mock import Mock, patch

from qa_agent.core.impact_analysis import ImpactAnalyzer
from qa_agent.core.types import TestCase, CaseState, TestLevel, Priority, Mode


class TestImpactAnalyzer:
    """测试影响面分析"""

    def test_get_priority_filter(self):
        """测试优先级过滤器"""
        config = {'impact_analysis': 'local'}
        analyzer = ImpactAnalyzer(config)

        assert analyzer._get_priority_filter(Mode.L0) == ['P0']
        assert analyzer._get_priority_filter(Mode.L1) == ['P0', 'P1']
        assert analyzer._get_priority_filter(Mode.L3) == ['P0', 'P1', 'P2', 'P3']

    def test_deduplicate(self):
        """测试去重"""
        config = {'impact_analysis': 'local'}
        analyzer = ImpactAnalyzer(config)

        cases = [
            TestCase(
                id='TC-001', title='Test 1', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.UNIT, priority=Priority.P0
            ),
            TestCase(
                id='TC-001', title='Test 1 dup', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.UNIT, priority=Priority.P0
            ),
            TestCase(
                id='TC-002', title='Test 2', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.UNIT, priority=Priority.P1
            )
        ]

        result = analyzer._deduplicate(cases)

        assert len(result) == 2
        assert result[0].id == 'TC-001'
        assert result[1].id == 'TC-002'

    @patch('qa_agent.core.impact_analysis.subprocess.run')
    def test_git_diff_name_only(self, mock_run):
        """测试 git diff 调用"""
        mock_run.return_value = Mock(
            stdout='src/login.ts\nsrc/auth.ts\n',
            returncode=0
        )

        config = {'impact_analysis': 'local'}
        analyzer = ImpactAnalyzer(config)

        result = analyzer._git_diff_name_only('HEAD~1')

        assert result == ['src/login.ts', 'src/auth.ts']
        mock_run.assert_called_once()

    def test_analyze_local_matches_targets_files(self):
        """测试 local 模式匹配 targets.files"""
        config = {'impact_analysis': 'local', 'impact_fallback': 'local'}
        analyzer = ImpactAnalyzer(config)

        cases = [
            TestCase(
                id='TC-LOGIN-001', title='Login test', state=CaseState.ACTIVE,
                feature_id='F-LOGIN', requirement_ids=['REQ-1'],
                level=TestLevel.UNIT, priority=Priority.P0,
                targets={'files': ['src/pages/login']}
            ),
            TestCase(
                id='TC-HOME-001', title='Home test', state=CaseState.ACTIVE,
                feature_id='F-HOME', requirement_ids=['REQ-2'],
                level=TestLevel.UNIT, priority=Priority.P0,
                targets={'files': ['src/pages/home']}
            )
        ]

        with patch.object(analyzer, '_git_diff_name_only', return_value=['src/pages/login.tsx']):
            result = analyzer._analyze_local(Mode.L1, cases, 'HEAD~1')

        # 应该命中 TC-LOGIN-001（前缀匹配）
        selected_ids = [c.id for c in result['selected_cases']]
        assert 'TC-LOGIN-001' in selected_ids
        assert 'TC-HOME-001' not in selected_ids
