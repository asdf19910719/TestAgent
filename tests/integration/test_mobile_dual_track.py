"""
端到端测试:验证双轨方案在真实项目上的生成效果
模拟 ClawBoxClient 的联系人用例,测试 Espresso + Maestro 生成
"""
import pytest
from pathlib import Path
import yaml

from qa_agent.core.types import TestCase, TestLevel, Priority, CaseState
from qa_agent.adapters.mobile.adapter import MobileAdapter


@pytest.fixture
def mock_android_project(tmp_path):
    """模拟 Android 项目结构"""
    # 创建基本目录
    (tmp_path / 'app' / 'src' / 'main').mkdir(parents=True)
    (tmp_path / 'qa' / 'cases' / 'contact').mkdir(parents=True)

    # 创建 build.gradle.kts 设置包名
    (tmp_path / 'app' / 'build.gradle.kts').write_text('''
android {
    namespace = "com.openclaw.agent"
    defaultConfig {
        applicationId = "com.openclaw.agent"
    }
}
''')

    return tmp_path


def test_generate_integration_with_database_assertions(mock_android_project):
    """测试:integration 层,database 断言 → 生成 Espresso"""
    adapter = MobileAdapter(cwd=mock_android_project)
    adapter.detect()

    case = TestCase(
        id='TC-CONTACT-001',
        title='联系人完全同步 - 正常场景',
        state=CaseState.ACTIVE,
        feature_id='F-CONTACT-SYNC',
        requirement_ids=[],
        level=TestLevel.INTEGRATION,
        priority=Priority.P0,
        preconditions=[
            '云端通讯录有 3 个联系人（张三、李四、王五）',
            '本地通讯录有 2 个联系人（李四、旧联系人）'
        ],
        steps=[
            '启动 GatewayService',
            '触发 syncContactsOnBoot()',
            '等待同步完成'
        ],
        expected=[
            '本地新增张三、王五',
            '保留李四',
            '删除旧联系人'
        ],
        assertions=[
            {
                'type': 'database',
                'query': "SELECT COUNT(*) FROM RawContacts WHERE account_type='com.openclaw.agent'",
                'equals': 3
            },
            {
                'type': 'database',
                'query': "SELECT displayName FROM Contacts WHERE phone='13900000001'",
                'equals': '张三'
            },
            {
                'type': 'log',
                'pattern': '完全同步完成: 新增=2, 删除=1'
            }
        ]
    )

    # 生成测试
    result_path = adapter.generate(case)

    # 验证生成结果
    result_file = mock_android_project / result_path
    assert result_file.exists(), f"测试文件应该生成: {result_path}"

    content = result_file.read_text(encoding='utf-8')

    # 验证关键元素
    assert 'package com.openclaw.agent' in content, "应包含正确包名"
    assert 'class TcContact001' in content, "应生成正确类名"
    assert '@Test' in content, "应包含测试注解"

    # 验证断言转译效果
    assert 'ContentResolver' in content, "应生成 ContentResolver 查询"
    assert 'ContactsContract.RawContacts.CONTENT_URI' in content, "应识别 RawContacts 表"
    assert 'assertEquals(3,' in content, "应生成精确断言"
    assert 'assertLogContains' in content, "应生成日志断言方法"

    # 验证 TODO 提示(前置条件)
    assert 'TODO[必填]:' in content, "应生成前置条件提示"
    assert '云端通讯录有 3 个联系人' in content, "应包含具体前置条件"

    print(f"\nOK Espresso 生成测试通过")
    print(f"生成路径: {result_path}")
    print(f"文件大小: {len(content)} 字符")
    print(f"包含 assertEquals: {content.count('assertEquals')} 处")


def test_generate_system_with_ui_flow(mock_android_project):
    """测试:system 层,纯 UI 流程 → 生成 Maestro"""
    adapter = MobileAdapter(cwd=mock_android_project)
    adapter.detect()

    case = TestCase(
        id='TC-CONTACT-016',
        title='陌生号码短信拒绝服务',
        state=CaseState.ACTIVE,
        feature_id='F-CONTACT-SYNC',
        requirement_ids=[],
        level=TestLevel.SYSTEM,
        priority=Priority.P1,
        preconditions=[
            '设备已安装 ClawBox Agent',
            '已授予短信权限'
        ],
        steps=[
            '触发陌生号码(13900000099)发送短信到设备',
            'GatewayService 接收到短信',
            '系统应拒绝转发(不调用消息 API)'
        ],
        expected=[
            '消息列表中没有出现该陌生号码的消息'
        ],
        assertions=[]  # system 层通常是视觉验证,无后台断言
    )

    # 生成测试
    result_path = adapter.generate(case)

    # 验证生成结果
    result_file = mock_android_project / result_path
    assert result_file.exists(), f"Maestro flow 应该生成: {result_path}"

    content = result_file.read_text(encoding='utf-8')

    # 验证 Maestro flow 结构
    assert 'appId: com.openclaw.agent' in content, "应包含正确 appId"
    assert '---' in content, "应包含 YAML 分隔符"
    assert '- launchApp' in content, "应包含启动应用操作"

    # 验证步骤转译
    assert 'assertNotVisible' in content or 'TODO' in content, "应包含断言或 TODO"

    print(f"\nOK Maestro 生成测试通过")
    print(f"生成路径: {result_path}")
    print(f"文件大小: {len(content)} 字符")


def test_routing_logic(mock_android_project):
    """测试:路由逻辑 - 按断言类型自动选择工具"""
    adapter = MobileAdapter(cwd=mock_android_project)
    adapter.detect()

    # 场景1: 有 database 断言 → Espresso
    case_with_db = TestCase(
        id='TC-TEST-001',
        title='Test with DB',
        state=CaseState.ACTIVE,
        feature_id='F-TEST',
        requirement_ids=[],
        level=TestLevel.INTEGRATION,
        priority=Priority.P1,
        steps=['Step 1'],
        expected=['Expected 1'],
        assertions=[{'type': 'database', 'query': 'SELECT 1', 'equals': 1}]
    )

    tool = adapter._select_android_tool(case_with_db)
    assert tool == 'espresso', "有 database 断言应选 Espresso"

    # 场景2: system 层无后台断言 → Maestro
    case_system_ui = TestCase(
        id='TC-TEST-002',
        title='Test UI flow',
        state=CaseState.ACTIVE,
        feature_id='F-TEST',
        requirement_ids=[],
        level=TestLevel.SYSTEM,
        priority=Priority.P1,
        steps=['Step 1'],
        expected=['Expected 1'],
        assertions=[]
    )

    tool = adapter._select_android_tool(case_system_ui)
    assert tool == 'maestro', "system 层纯 UI 应选 Maestro"

    print(f"\nOK 路由逻辑测试通过")
