"""验证 @AI-FILL 闭环:生成的骨架是否正确嵌入填充指令 + targets 锚点"""
import pytest
from pathlib import Path

from qa_agent.core.types import TestCase, TestLevel, Priority, CaseState
from qa_agent.adapters.mobile.adapter import MobileAdapter


@pytest.fixture
def android_proj(tmp_path):
    (tmp_path / 'app' / 'src' / 'main').mkdir(parents=True)
    (tmp_path / 'app' / 'build.gradle.kts').write_text(
        'android {\n  namespace = "com.openclaw.agent"\n'
        '  defaultConfig { applicationId = "com.openclaw.agent" }\n}'
    )
    return tmp_path


def test_aifill_directive_embeds_targets(android_proj):
    """@AI-FILL 指令块应嵌入 targets.files/symbols 作为 AI 填充锚点"""
    adapter = MobileAdapter(cwd=android_proj)
    adapter.detect()

    case = TestCase(
        id='TC-CONTACT-001',
        title='联系人完全同步',
        state=CaseState.ACTIVE,
        feature_id='F-CONTACT-SYNC',
        requirement_ids=['FR-033'],
        level=TestLevel.INTEGRATION,
        priority=Priority.P0,
        preconditions=['云端通讯录有 3 个联系人'],
        steps=['触发 syncContactsOnBoot()'],
        expected=['本地联系人总数 = 3'],
        assertions=[{
            'type': 'database',
            'query': "SELECT COUNT(*) FROM RawContacts WHERE account_type='com.openclaw.agent'",
            'equals': 3
        }],
        targets={
            'files': [
                'app/src/main/java/com/openclaw/agent/service/GatewayService.kt',
                'app/src/main/java/com/openclaw/agent/service/ContactRepository.kt',
            ],
            'symbols': ['GatewayService.syncContactsOnBoot']
        }
    )

    result_path = adapter.generate(case)
    content = (android_proj / result_path).read_text(encoding='utf-8')

    # 1. 填充指令块存在
    assert '@AI-FILL-SPEC' in content
    assert '@AI-FILL:arrange' in content
    assert '@AI-FILL:act' in content

    # 2. targets 源码锚点嵌入(AI 知道读哪些文件)
    assert 'GatewayService.kt' in content, "targets.files 应嵌入指令块"
    assert 'ContactRepository.kt' in content
    assert 'GatewayService.syncContactsOnBoot' in content, "targets.symbols 应嵌入"

    # 3. 断言部分已是真实代码(非 @AI-FILL)
    assert 'ContactsContract.RawContacts.CONTENT_URI' in content
    assert 'assertEquals(3,' in content

    # 4. 需求上下文保留(AI 知道填什么)
    assert '云端通讯录有 3 个联系人' in content
    assert 'syncContactsOnBoot()' in content

    print("\n=== @AI-FILL 指令块(供 AI 填充)===")
    for line in content.split('\n'):
        if '@AI-FILL' in line or 'GatewayService' in line or 'ContactRepository' in line:
            print(f"  {line.strip()}")

    print("\nOK @AI-FILL 闭环验证通过: 指令+锚点+真实断言齐备")
