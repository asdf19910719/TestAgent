"""
测试 Core 引擎模式路由
"""

import pytest
from pathlib import Path

from qa_agent.core.engine import Engine
from qa_agent.core.types import Mode


class TestEngine:
    """测试 Engine 核心功能"""

    def test_generate_run_id(self):
        """测试 run ID 生成"""
        engine = Engine()
        run_id = engine._generate_run_id()

        assert run_id.startswith('run_')
        assert len(run_id) > 10

    def test_group_by_level(self):
        """测试按层级分组"""
        from qa_agent.core.types import TestCase, CaseState, TestLevel, Priority

        engine = Engine()
        cases = [
            TestCase(
                id='TC-001', title='Test 1', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.UNIT, priority=Priority.P0
            ),
            TestCase(
                id='TC-002', title='Test 2', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.UNIT, priority=Priority.P1
            ),
            TestCase(
                id='TC-003', title='Test 3', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.INTEGRATION, priority=Priority.P0
            )
        ]

        result = engine._group_by_level(cases)

        assert result['unit'] == 2
        assert result['integration'] == 1

    def test_group_by_priority(self):
        """测试按优先级分组"""
        from qa_agent.core.types import TestCase, CaseState, TestLevel, Priority

        engine = Engine()
        cases = [
            TestCase(
                id='TC-001', title='Test 1', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.UNIT, priority=Priority.P0
            ),
            TestCase(
                id='TC-002', title='Test 2', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.UNIT, priority=Priority.P0
            ),
            TestCase(
                id='TC-003', title='Test 3', state=CaseState.ACTIVE,
                feature_id='F-1', requirement_ids=['REQ-1'],
                level=TestLevel.INTEGRATION, priority=Priority.P1
            )
        ]

        result = engine._group_by_priority(cases)

        assert result['P0'] == 2
        assert result['P1'] == 1
