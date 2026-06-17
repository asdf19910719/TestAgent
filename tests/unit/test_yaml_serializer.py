"""
测试 YAML 序列化
"""

import pytest
import tempfile
from pathlib import Path

from qa_agent.core.types import TestCase, Bug, CaseState, Priority, TestLevel
from qa_agent.core.yaml_serializer import CaseSerializer, BugSerializer


class TestCaseSerializer:
    """测试 CaseSerializer"""

    def test_to_dict_and_from_dict(self):
        """TestCase 双向转换"""
        case = TestCase(
            id='TC-LOGIN-001',
            title='用户登录测试',
            state=CaseState.ACTIVE,
            feature_id='F-LOGIN',
            requirement_ids=['REQ-101'],
            level=TestLevel.SYSTEM,
            priority=Priority.P0,
            preconditions=['用户已注册'],
            steps=['打开登录页', '输入账号', '点击登录'],
            expected=['跳转首页']
        )

        d = CaseSerializer.to_dict(case)
        case2 = CaseSerializer.from_dict(d)

        assert case2.id == case.id
        assert case2.title == case.title
        assert case2.state == case.state
        assert case2.feature_id == case.feature_id
        assert case2.requirement_ids == case.requirement_ids
        assert case2.level == case.level
        assert case2.priority == case.priority
        assert case2.steps == case.steps

    def test_save_and_load(self, tmp_path):
        """保存和加载用例"""
        case = TestCase(
            id='TC-AUTH-001',
            title='鉴权测试',
            state=CaseState.ACTIVE,
            feature_id='F-AUTH',
            requirement_ids=['REQ-201'],
            level=TestLevel.UNIT,
            priority=Priority.P1
        )

        filepath = CaseSerializer.save(case, tmp_path)
        assert filepath.exists()

        loaded = CaseSerializer.load(filepath)
        assert loaded.id == case.id
        assert loaded.feature_id == case.feature_id

    def test_load_all(self, tmp_path):
        """批量加载用例"""
        cases = [
            TestCase(
                id=f'TC-FEATURE-{i:03d}',
                title=f'Test {i}',
                state=CaseState.ACTIVE,
                feature_id='F-FEATURE',
                requirement_ids=['REQ-1'],
                level=TestLevel.UNIT,
                priority=Priority.P1
            )
            for i in range(1, 4)
        ]

        for case in cases:
            CaseSerializer.save(case, tmp_path)

        loaded = CaseSerializer.load_all(tmp_path)
        assert len(loaded) == 3

    def test_load_by_id(self, tmp_path):
        """按 ID 加载"""
        case = TestCase(
            id='TC-FOO-005',
            title='Foo Test',
            state=CaseState.ACTIVE,
            feature_id='F-FOO',
            requirement_ids=[],
            level=TestLevel.UNIT,
            priority=Priority.P0
        )
        CaseSerializer.save(case, tmp_path)

        loaded = CaseSerializer.load_by_id('TC-FOO-005', tmp_path)
        assert loaded is not None
        assert loaded.id == 'TC-FOO-005'


class TestBugSerializer:
    """测试 BugSerializer"""

    def test_save_and_load(self, tmp_path):
        """保存和加载 Bug"""
        bug = Bug(
            id='BUG-100',
            title='登录失败',
            state='open',
            severity='high',
            priority='P1',
            related_cases=['TC-LOGIN-001'],
            related_requirements=['REQ-101'],
            feature_id='F-LOGIN',
            repro_steps=['打开登录页', '输入错误密码'],
            expected='提示密码错误',
            actual='页面无响应'
        )

        filepath = BugSerializer.save(bug, tmp_path)
        assert filepath.exists()

        loaded = BugSerializer.load_by_id('BUG-100', tmp_path)
        assert loaded is not None
        assert loaded.id == 'BUG-100'
        assert loaded.severity == 'high'
        assert loaded.repro_steps == bug.repro_steps

    def test_load_all_with_filter(self, tmp_path):
        """按状态过滤加载"""
        bugs = [
            Bug(id='BUG-001', title='Bug 1', state='open', severity='high',
                priority='P1', related_cases=[], related_requirements=[],
                feature_id='', repro_steps=[], expected='', actual=''),
            Bug(id='BUG-002', title='Bug 2', state='fixed', severity='medium',
                priority='P2', related_cases=[], related_requirements=[],
                feature_id='', repro_steps=[], expected='', actual=''),
            Bug(id='BUG-003', title='Bug 3', state='open', severity='low',
                priority='P3', related_cases=[], related_requirements=[],
                feature_id='', repro_steps=[], expected='', actual='')
        ]
        for bug in bugs:
            BugSerializer.save(bug, tmp_path)

        open_bugs = BugSerializer.load_all(tmp_path, state_filter='open')
        assert len(open_bugs) == 2
        assert all(b.state == 'open' for b in open_bugs)

    def test_next_bug_id(self, tmp_path):
        """生成递增 Bug ID"""
        # 空目录
        assert BugSerializer.next_bug_id(tmp_path) == 'BUG-001'

        # 已有 bug
        bug = Bug(id='BUG-007', title='', state='open', severity='medium',
                  priority='P2', related_cases=[], related_requirements=[],
                  feature_id='', repro_steps=[], expected='', actual='')
        BugSerializer.save(bug, tmp_path)

        assert BugSerializer.next_bug_id(tmp_path) == 'BUG-008'
