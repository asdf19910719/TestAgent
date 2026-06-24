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


class TestScopeFallback:
    """测试 scope 兜底（targets 缺失时按 feature 关联）"""

    def _make_cases(self):
        """构造一批缺 targets 的用例（模拟 StudySkill 场景）"""
        return [
            TestCase(
                id='TC-LLM-001', title='LLM test', state=CaseState.ACTIVE,
                feature_id='auto-llm-material-analysis', requirement_ids=['FR-001'],
                level=TestLevel.SYSTEM, priority=Priority.P0
                # 注意：无 targets 字段（default_factory=dict → {}）
            ),
            TestCase(
                id='TC-LLM-002', title='Size check', state=CaseState.ACTIVE,
                feature_id='auto-llm-material-analysis', requirement_ids=['FR-002'],
                level=TestLevel.SYSTEM, priority=Priority.P1
            ),
            TestCase(
                id='TC-OTHER-001', title='Unrelated', state=CaseState.ACTIVE,
                feature_id='user-login', requirement_ids=['FR-100'],
                level=TestLevel.UNIT, priority=Priority.P0
            ),
        ]

    def test_fallback_triggers_when_targets_empty(self):
        """targets 全空 + 有 scope → 按 scope 兜底选中该 feature 用例"""
        config = {'impact_analysis': 'local', 'impact_fallback': 'local'}
        analyzer = ImpactAnalyzer(config)
        cases = self._make_cases()

        # diff 命中无关文件，targets 全空 → 正常匹配为 0
        with patch.object(analyzer, '_git_diff_name_only', return_value=['some/unrelated/file.py']):
            result = analyzer._analyze_local(
                Mode.L2, cases, 'HEAD~1', scope='auto-llm-material-analysis'
            )

        selected_ids = [c.id for c in result['selected_cases']]
        # 兜底选中同 feature 的 P0/P1（L2 含 P0/P1/P2）
        assert 'TC-LLM-001' in selected_ids
        assert 'TC-LLM-002' in selected_ids
        # 不选无关 feature
        assert 'TC-OTHER-001' not in selected_ids

    def test_no_fallback_without_scope(self):
        """targets 全空 + 无 scope → 仍为空（不误选）"""
        config = {'impact_analysis': 'local', 'impact_fallback': 'local'}
        analyzer = ImpactAnalyzer(config)
        cases = self._make_cases()

        with patch.object(analyzer, '_git_diff_name_only', return_value=['some/unrelated/file.py']):
            result = analyzer._analyze_local(Mode.L2, cases, 'HEAD~1', scope=None)

        assert result['selected_cases'] == []

    def test_no_fallback_when_targets_match(self):
        """targets 有值正常匹配 → 不触发兜底（回归保护）"""
        config = {'impact_analysis': 'local', 'impact_fallback': 'local'}
        analyzer = ImpactAnalyzer(config)
        cases = self._make_cases()
        # 给 TC-LLM-001 加 targets，让它正常命中
        cases[0].targets = {'files': ['scripts/llm']}

        with patch.object(analyzer, '_git_diff_name_only', return_value=['scripts/llm/server.py']):
            result = analyzer._analyze_local(
                Mode.L2, cases, 'HEAD~1', scope='auto-llm-material-analysis'
            )

        selected_ids = [c.id for c in result['selected_cases']]
        # 正常命中 TC-LLM-001，补集带出同 feature 的 TC-LLM-002
        # 关键：不是走兜底（兜底只在 selection 为空时触发）
        assert 'TC-LLM-001' in selected_ids
        # 无关 feature 不被选
        assert 'TC-OTHER-001' not in selected_ids

    def test_l3_ignores_fallback(self):
        """L3 + targets 全空 → 选全部 active（不受兜底影响，走独立分支）"""
        config = {'impact_analysis': 'local', 'impact_fallback': 'local'}
        analyzer = ImpactAnalyzer(config)
        cases = self._make_cases()

        with patch.object(analyzer, '_git_diff_name_only', return_value=[]):
            result = analyzer.analyze(Mode.L3, cases, scope='auto-llm-material-analysis')

        selected_ids = [c.id for c in result['selected_cases']]
        # L3 选全部 active，含无关 feature
        assert 'TC-LLM-001' in selected_ids
        assert 'TC-LLM-002' in selected_ids
        assert 'TC-OTHER-001' in selected_ids
        assert result['mode'] == 'full'
