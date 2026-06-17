"""
测试 Mobile Adapter
"""

import pytest
from pathlib import Path

from qa_agent.adapters.mobile import MobileAdapter


class TestMobileAdapterDetect:
    """检测各种移动端项目类型"""

    def test_detect_android_with_root_gradle(self, tmp_path):
        """根目录 build.gradle 的 Android 项目"""
        (tmp_path / 'build.gradle').write_text('android { }')
        (tmp_path / 'app').mkdir()
        (tmp_path / 'app' / 'build.gradle').write_text('android { }')

        adapter = MobileAdapter(cwd=tmp_path)
        fp = adapter.detect()

        assert fp.project_type == 'mobile'
        assert fp.language in ('kotlin', 'java')
        assert 'unit' in fp.frameworks
        assert 'unit' in fp.run_commands

    def test_detect_android_kotlin_kts(self, tmp_path):
        """Kotlin DSL Android 项目"""
        (tmp_path / 'build.gradle.kts').write_text('plugins { id("com.android.application") }')
        (tmp_path / 'app').mkdir()
        (tmp_path / 'app' / 'build.gradle.kts').write_text('android { }')

        adapter = MobileAdapter(cwd=tmp_path)
        fp = adapter.detect()
        assert fp.project_type == 'mobile'

    def test_detect_flutter(self, tmp_path):
        """Flutter 项目"""
        (tmp_path / 'pubspec.yaml').write_text('name: my_app\nflutter:\n  uses-material-design: true\n')

        adapter = MobileAdapter(cwd=tmp_path)
        fp = adapter.detect()

        assert fp.project_type == 'mobile'
        assert fp.language == 'dart'
        assert fp.frameworks['unit'] == 'flutter_test'
        assert fp.capabilities['cross_os'] is True

    def test_detect_react_native(self, tmp_path):
        """React Native 项目"""
        (tmp_path / 'package.json').write_text(
            '{"dependencies":{"react-native":"^0.72.0"},"devDependencies":{"jest":"^29","detox":"^20"}}'
        )

        adapter = MobileAdapter(cwd=tmp_path)
        fp = adapter.detect()

        assert fp.project_type == 'mobile'
        assert fp.frameworks.get('unit') == 'jest'
        assert fp.frameworks.get('e2e') == 'detox'

    def test_detect_ios_xcodeproj(self, tmp_path):
        """iOS Xcode 项目"""
        (tmp_path / 'MyApp.xcodeproj').mkdir()

        adapter = MobileAdapter(cwd=tmp_path)
        fp = adapter.detect()

        assert fp.project_type == 'mobile'
        assert fp.language == 'swift'
        assert fp.frameworks['ui'] == 'xcuitest'

    def test_detect_ios_swift_package(self, tmp_path):
        """Swift Package iOS 项目"""
        (tmp_path / 'Package.swift').write_text('// swift-tools-version: 5.9')

        adapter = MobileAdapter(cwd=tmp_path)
        fp = adapter.detect()
        assert fp.project_type == 'mobile'

    def test_detect_fails_on_non_mobile(self, tmp_path):
        """非移动端项目应该报错"""
        (tmp_path / 'requirements.txt').write_text('flask==2.0')

        adapter = MobileAdapter(cwd=tmp_path)
        with pytest.raises(RuntimeError):
            adapter.detect()


class TestMobileAdapterGenerate:
    """生成测试脚本骨架"""

    def test_generate_android_unit(self, tmp_path):
        """Android 单元测试生成"""
        from qa_agent.core.types import TestCase, CaseState, TestLevel, Priority

        (tmp_path / 'app').mkdir()
        (tmp_path / 'app' / 'build.gradle').write_text('android { }')

        adapter = MobileAdapter(cwd=tmp_path)
        adapter.detect()

        case = TestCase(
            id='TC-LOGIN-001',
            title='Login unit test',
            state=CaseState.ACTIVE,
            feature_id='F-LOGIN',
            requirement_ids=['REQ-1'],
            level=TestLevel.UNIT,
            priority=Priority.P0,
            steps=['Step 1'],
            expected=['Expected 1']
        )

        path = adapter.generate(case)
        assert 'app/src/test' in path.replace('\\', '/')
        full_path = tmp_path / path
        assert full_path.exists()
        assert '@Test' in full_path.read_text(encoding='utf-8')

    def test_generate_flutter(self, tmp_path):
        """Flutter 测试生成"""
        from qa_agent.core.types import TestCase, CaseState, TestLevel, Priority

        (tmp_path / 'pubspec.yaml').write_text('name: my_app\n')

        adapter = MobileAdapter(cwd=tmp_path)
        adapter.detect()

        case = TestCase(
            id='TC-LOGIN-001',
            title='Login test',
            state=CaseState.ACTIVE,
            feature_id='F-LOGIN',
            requirement_ids=['REQ-1'],
            level=TestLevel.UNIT,
            priority=Priority.P1
        )

        path = adapter.generate(case)
        assert path.endswith('.dart')
        full_path = tmp_path / path
        assert full_path.exists()
        assert 'flutter_test' in full_path.read_text(encoding='utf-8')


class TestMobileAdapterScaffold:
    """测试目录搭建"""

    def test_scaffold_android(self, tmp_path):
        """Android scaffold 创建测试目录"""
        (tmp_path / 'app').mkdir()
        (tmp_path / 'app' / 'build.gradle').write_text('android { }')

        adapter = MobileAdapter(cwd=tmp_path)
        adapter.detect()
        adapter.scaffold({})

        assert (tmp_path / 'app' / 'src' / 'test' / 'java').exists()
        assert (tmp_path / 'app' / 'src' / 'androidTest' / 'java').exists()

    def test_scaffold_flutter(self, tmp_path):
        """Flutter scaffold 创建 test/integration_test"""
        (tmp_path / 'pubspec.yaml').write_text('name: my_app\n')

        adapter = MobileAdapter(cwd=tmp_path)
        adapter.detect()
        adapter.scaffold({})

        assert (tmp_path / 'test').exists()
        assert (tmp_path / 'integration_test').exists()


class TestMobileAdapterClassifyFailure:
    """失败分类"""

    def test_classify_no_devices_as_env(self, tmp_path):
        """无设备 → 环境失败"""
        (tmp_path / 'pubspec.yaml').write_text('name: app\n')
        adapter = MobileAdapter(cwd=tmp_path)

        result = adapter.classify_failure({'error': 'No devices found'})
        assert result == 'env'

    def test_classify_assertion_as_test(self, tmp_path):
        """断言失败 → 测试失败"""
        (tmp_path / 'pubspec.yaml').write_text('name: app\n')
        adapter = MobileAdapter(cwd=tmp_path)

        result = adapter.classify_failure({'error': 'AssertionError: expected true'})
        assert result == 'test'
