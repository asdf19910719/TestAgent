"""测试 Kotlin 静态结构校验器 — 验证它能拦截实战撞到的 bug 类"""
import pytest
from pathlib import Path

from qa_agent.core.types import TestCase, TestLevel, Priority, CaseState
from qa_agent.adapters.mobile.adapter import MobileAdapter
from qa_agent.adapters.mobile.kotlin_validator import KotlinStructureValidator


@pytest.fixture
def android_proj(tmp_path):
    (tmp_path / 'app' / 'src' / 'main').mkdir(parents=True)
    (tmp_path / 'app' / 'build.gradle.kts').write_text(
        'android {\n  namespace = "com.openclaw.agent"\n'
        '  defaultConfig { applicationId = "com.openclaw.agent" }\n}'
    )
    return tmp_path


# === 校验器单元测试:能否拦截各类 bug ===

def test_catches_duplicate_val():
    """拦截同方法体内 val 重复声明(实战撞到的 val resolver x3 bug)"""
    buggy = '''package com.x
class T {
    fun test() {
        val resolver = getResolver()
        val resolver = getResolver()
        assertEquals(1, 1)
    }
}'''
    result = KotlinStructureValidator().validate(buggy)
    assert not result['ok']
    assert any('resolver' in e and '重复' in e for e in result['errors'])


def test_catches_missing_import_prefix():
    """拦截裸类名(缺 import 前缀)"""
    buggy = '''package com.x

import org.junit.Test
android.content.ContentResolver

class T {
    @Test fun t() { assertTrue(true) }
}'''
    result = KotlinStructureValidator().validate(buggy)
    assert not result['ok']
    assert any('import' in e for e in result['errors'])


def test_catches_brace_imbalance():
    """拦截花括号不配平"""
    buggy = '''package com.x
class T {
    fun test() {
        if (x) {
        assertEquals(1, 1)
    }
}'''
    result = KotlinStructureValidator().validate(buggy)
    assert not result['ok']
    assert any('花括号' in e for e in result['errors'])


def test_warns_aifill_residue():
    """警告 @AI-FILL 残留"""
    code = '''package com.x
class T {
    fun test() {
        // @AI-FILL:arrange
        assertEquals(1, 1)
    }
}'''
    result = KotlinStructureValidator().validate(code)
    assert result['ok']  # @AI-FILL 是 warning 不是 error
    assert any('@AI-FILL' in w for w in result['warnings'])


def test_clean_code_passes():
    """正确代码应通过"""
    clean = '''package com.x

import org.junit.Test
import org.junit.Assert.assertEquals

class T {
    @Test
    fun test() {
        val resolver = getResolver()
        run {
            val cursor = resolver.query()
            cursor?.use { assertEquals(3, it.count) }
        }
        run {
            val cursor = resolver.query()
            cursor?.use { assertEquals("x", it.getString(0)) }
        }
    }
}'''
    result = KotlinStructureValidator().validate(clean)
    assert result['ok'], f"干净代码不应报错: {result['errors']}"


# === 集成测试:校验 Adapter 实际生成的代码结构合法 ===

def test_generated_espresso_passes_validation(android_proj):
    """Adapter 生成的多 database 断言代码应通过结构校验(回归保护)"""
    adapter = MobileAdapter(cwd=android_proj)
    adapter.detect()

    case = TestCase(
        id='TC-CONTACT-001', title='Contact sync', state=CaseState.ACTIVE,
        feature_id='F-CONTACT-SYNC', requirement_ids=['FR-033'],
        level=TestLevel.INTEGRATION, priority=Priority.P0,
        preconditions=['cloud has 3 contacts'],
        steps=['trigger sync'],
        expected=['local total = 3'],
        # 3 个 database 断言(就是触发 val 重复 bug 的场景)
        assertions=[
            {'type': 'database', 'query': "SELECT COUNT(*) FROM RawContacts WHERE account_type='com.openclaw.agent'", 'equals': 3},
            {'type': 'database', 'query': "SELECT displayName FROM Contacts WHERE phone='13900000001'", 'equals': '张三'},
            {'type': 'database', 'query': "SELECT Note FROM Data WHERE MIMETYPE='note'", 'contains': '[openclaw:contactId=1]'},
        ],
    )

    result_path = adapter.generate(case)
    content = (android_proj / result_path).read_text(encoding='utf-8')

    validation = KotlinStructureValidator().validate(content)
    # 结构必须合法(无 val 重复、无 import 缺失、括号配平)
    assert validation['ok'], f"生成代码结构非法: {validation['errors']}"

    print(f"\nOK 生成代码通过结构校验")
    print(f"warnings(预期含@AI-FILL): {validation['warnings']}")
