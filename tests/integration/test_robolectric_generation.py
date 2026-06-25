"""测试 Robolectric Adapter 生成"""
import pytest
from pathlib import Path

from qa_agent.core.types import TestCase, TestLevel, Priority, CaseState
from qa_agent.adapters.mobile.adapter import MobileAdapter


@pytest.fixture
def mock_android_project(tmp_path):
    """模拟 Android 项目"""
    (tmp_path / 'app' / 'src' / 'main').mkdir(parents=True)
    (tmp_path / 'app' / 'build.gradle.kts').write_text('''
android {
    namespace = "com.openclaw.agent"
    defaultConfig {
        applicationId = "com.openclaw.agent"
    }
}
''')
    return tmp_path


def test_generate_unit_test_with_robolectric(mock_android_project):
    """测试:unit 层 → 生成 Robolectric JUnit 测试"""
    adapter = MobileAdapter(cwd=mock_android_project)
    adapter.detect()

    case = TestCase(
        id='TC-PHONE-NORMALIZE-001',
        title='手机号归一化 - 去除空格和横杠',
        state=CaseState.ACTIVE,
        feature_id='F-PHONE-UTIL',
        requirement_ids=[],
        level=TestLevel.UNIT,  # ← unit 层
        priority=Priority.P0,
        preconditions=[],
        steps=[
            '调用 PhoneUtil.normalize("139 0000 0001")',
            '调用 PhoneUtil.normalize("139-0000-0001")'
        ],
        expected=[
            '返回 "13900000001"',
            '返回 "13900000001"'
        ],
        assertions=[
            {
                'type': 'return_value',
                'method': 'PhoneUtil.normalize',
                'input': '139 0000 0001',
                'equals': '13900000001'
            },
            {
                'type': 'return_value',
                'method': 'PhoneUtil.normalize',
                'input': '139-0000-0001',
                'equals': '13900000001'
            }
        ]
    )

    # 生成测试
    result_path = adapter.generate(case)

    # 验证生成结果
    result_file = mock_android_project / result_path
    assert result_file.exists(), f"Robolectric 测试应该生成: {result_path}"

    content = result_file.read_text(encoding='utf-8')

    # 验证 Robolectric 特征
    assert 'package com.openclaw.agent' in content, "应包含正确包名"
    assert 'class TcPhoneNormalize001' in content, "应生成正确类名"
    assert '@RunWith(RobolectricTestRunner::class)' in content, "应使用 Robolectric runner"
    assert '@Config(sdk = [28])' in content, "应配置 SDK 版本"
    assert '@Test' in content, "应包含测试注解"

    # 验证生成路径(app/src/test,不是 androidTest)
    assert 'app' in str(result_path) and 'src' in str(result_path) and 'test' in str(result_path), "应生成到 test 目录(非 androidTest)"
    assert 'androidTest' not in str(result_path), "不应生成到 androidTest"

    # 验证 @AI-FILL 范式(未填充即 fail,不假绿)
    assert '@AI-FILL' in content, "应含 @AI-FILL 填充标记"
    assert 'fail(' in content, "未填充应有 fail() 守卫(防红线5假绿)"

    print(f"\nOK Robolectric 生成测试通过")
    print(f"生成路径: {result_path}")
    print(f"文件大小: {len(content)} 字符")
    print(f"包含 @RunWith(Robolectric: {content.count('@RunWith(RobolectricTestRunner')} 处")


def test_routing_to_robolectric(mock_android_project):
    """测试:unit 层用例自动路由到 Robolectric"""
    adapter = MobileAdapter(cwd=mock_android_project)
    adapter.detect()

    case_unit = TestCase(
        id='TC-UNIT-001',
        title='Unit test',
        state=CaseState.ACTIVE,
        feature_id='F-TEST',
        requirement_ids=[],
        level=TestLevel.UNIT,  # ← unit
        priority=Priority.P1,
        steps=['Step 1'],
        expected=['Expected 1'],
        assertions=[]
    )

    tool = adapter._select_android_tool(case_unit)
    assert tool == 'robolectric', "unit 层应选择 Robolectric"

    print(f"\nOK 路由到 Robolectric 测试通过")
