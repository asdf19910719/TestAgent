"""测试 scope 兜底的三个 bug 修复"""
import pytest
from qa_agent.core.types import TestCase, TestLevel, Priority, CaseState
from qa_agent.core.impact_analysis import ImpactAnalyzer


@pytest.fixture
def cases_with_bugs():
    """模拟 ClawBoxClient 的用例集（含三个 bug 场景）"""
    return [
        # Bug 3: 联系人模块跨两个 feature_id
        TestCase(id='TC-CONTACT-001', title='同步', feature_id='F-CONTACT-SYNC',
                 state=CaseState.ACTIVE, priority=Priority.P0, level=TestLevel.INTEGRATION,
                 requirement_ids=[], steps=[], expected=[]),
        TestCase(id='TC-CONTACT-007', title='身份', feature_id='F-CONTACT-IDENTITY',
                 state=CaseState.ACTIVE, priority=Priority.P0, level=TestLevel.INTEGRATION,
                 requirement_ids=[], steps=[], expected=[]),
        # Bug 2: 空 feature_id（不应被任何 scope 匹配）
        TestCase(id='TC-SMS-001', title='短信', feature_id='',
                 state=CaseState.ACTIVE, priority=Priority.P0, level=TestLevel.INTEGRATION,
                 requirement_ids=[], steps=[], expected=[]),
        TestCase(id='TC-SMS-002', title='短信2', feature_id=None,
                 state=CaseState.ACTIVE, priority=Priority.P0, level=TestLevel.INTEGRATION,
                 requirement_ids=[], steps=[], expected=[]),
        # 正常用例
        TestCase(id='TC-ORDER-001', title='订单', feature_id='F-ORDER-MANAGEMENT',
                 state=CaseState.ACTIVE, priority=Priority.P0, level=TestLevel.INTEGRATION,
                 requirement_ids=[], steps=[], expected=[]),
    ]


def test_bug2_empty_feature_id_not_matched(cases_with_bugs):
    """Bug 2: 空 feature_id 不应被任何 scope 匹配（之前空串是任意串子串）"""
    analyzer = ImpactAnalyzer(config={})

    # 用任意 scope 都不应匹配到空 feature_id 的用例
    result = analyzer._scope_fallback(
        current_selection=[],
        all_cases=cases_with_bugs,
        scope='联系人通讯录',  # 任意 scope
        priority_filter=['P0', 'P1', 'P2']
    )

    # TC-SMS-001 和 TC-SMS-002（空 feature_id）不应被选中
    assert not any(c.id.startswith('TC-SMS') for c in result), \
        "空 feature_id 用例不应被任何 scope 匹配"


def test_bug1_natural_language_rejected(cases_with_bugs):
    """Bug 1: 纯自然语言子串不应匹配（"联系人通讯录" 不匹配 "F-CONTACT-SYNC"）"""
    analyzer = ImpactAnalyzer(config={})

    # 纯自然语言 scope 不应匹配成功（之前会因为子串匹配误中）
    result = analyzer._scope_fallback(
        current_selection=[],
        all_cases=cases_with_bugs,
        scope='联系人通讯录功能',  # 纯中文，不含 contact/sync 等词
        priority_filter=['P0', 'P1', 'P2']
    )

    # 应该匹配失败（返回空）
    assert len(result) == 0, \
        "纯自然语言 scope 不应匹配 feature_id（需用 contact/F-CONTACT-SYNC 等）"


def test_bug3_multi_feature_via_prefix(cases_with_bugs):
    """Bug 3: 用共同前缀匹配多个 feature_id（"contact" 匹 F-CONTACT-*）"""
    analyzer = ImpactAnalyzer(config={})

    # 用 "contact" 应匹配 F-CONTACT-SYNC 和 F-CONTACT-IDENTITY
    result = analyzer._scope_fallback(
        current_selection=[],
        all_cases=cases_with_bugs,
        scope='contact',
        priority_filter=['P0', 'P1', 'P2']
    )

    ids = {c.id for c in result}
    assert 'TC-CONTACT-001' in ids, "应匹配 F-CONTACT-SYNC"
    assert 'TC-CONTACT-007' in ids, "应匹配 F-CONTACT-IDENTITY"
    assert len(result) == 2, f"应恰好匹配 2 条联系人用例，实际: {ids}"


def test_bug3_multi_feature_via_comma(cases_with_bugs):
    """Bug 3: 用逗号分隔多个 feature_id（"F-CONTACT-SYNC,F-CONTACT-IDENTITY"）"""
    analyzer = ImpactAnalyzer(config={})

    result = analyzer._scope_fallback(
        current_selection=[],
        all_cases=cases_with_bugs,
        scope='F-CONTACT-SYNC,F-CONTACT-IDENTITY',
        priority_filter=['P0', 'P1', 'P2']
    )

    ids = {c.id for c in result}
    assert 'TC-CONTACT-001' in ids
    assert 'TC-CONTACT-007' in ids
    assert len(result) == 2


def test_exact_match_still_works(cases_with_bugs):
    """精确匹配仍然工作"""
    analyzer = ImpactAnalyzer(config={})

    result = analyzer._scope_fallback(
        current_selection=[],
        all_cases=cases_with_bugs,
        scope='F-ORDER-MANAGEMENT',
        priority_filter=['P0', 'P1', 'P2']
    )

    assert len(result) == 1
    assert result[0].id == 'TC-ORDER-001'


def test_token_match_works(cases_with_bugs):
    """分词匹配工作（"order management" 匹 "F-ORDER-MANAGEMENT"）"""
    analyzer = ImpactAnalyzer(config={})

    result = analyzer._scope_fallback(
        current_selection=[],
        all_cases=cases_with_bugs,
        scope='order-management',
        priority_filter=['P0', 'P1', 'P2']
    )

    assert len(result) == 1
    assert result[0].id == 'TC-ORDER-001'


def test_no_fallback_when_selection_exists(cases_with_bugs):
    """有正常选择时不触发兜底"""
    analyzer = ImpactAnalyzer(config={})

    existing = [cases_with_bugs[0]]  # TC-CONTACT-001
    result = analyzer._scope_fallback(
        current_selection=existing,
        all_cases=cases_with_bugs,
        scope='order',  # 不应生效
        priority_filter=['P0', 'P1', 'P2']
    )

    assert result == existing, "有现存选择时应直接返回，不触发兜底"
