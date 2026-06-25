"""
Mobile Adapter: Android / iOS / 跨端移动应用

支持：
- Android: Gradle + JUnit + Espresso + Robolectric
- iOS: Xcode + XCUITest
- 跨端: Flutter (flutter test) / React Native (jest + detox)

主规范 §14.3 实现
"""

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from ...core.types import ProjectFingerprint, TestCase, RunResult


class MobileAdapter:
    """
    Mobile 适配器
    自动检测 Android / iOS / Flutter / React Native 项目类型
    """

    def __init__(self, cwd: Path = Path('.')):
        self.cwd = cwd
        self._project_subtype: Optional[str] = None

    def detect(self) -> ProjectFingerprint:
        """
        识别移动端项目类型

        优先级：
        1. Flutter (pubspec.yaml)
        2. React Native (package.json + react-native 依赖)
        3. Android 原生 (build.gradle / build.gradle.kts)
        4. iOS 原生 (*.xcodeproj / Package.swift)
        """
        # Flutter
        if (self.cwd / 'pubspec.yaml').exists():
            return self._detect_flutter()

        # React Native
        if (self.cwd / 'package.json').exists():
            pkg = json.loads((self.cwd / 'package.json').read_text(encoding='utf-8'))
            deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
            if 'react-native' in deps:
                return self._detect_react_native(pkg, deps)

        # Android 原生
        if (self.cwd / 'build.gradle').exists() or (self.cwd / 'build.gradle.kts').exists():
            return self._detect_android()

        # 子目录的 Android（多模块项目）
        if (self.cwd / 'app' / 'build.gradle').exists() or (self.cwd / 'app' / 'build.gradle.kts').exists():
            return self._detect_android()

        # iOS 原生
        if list(self.cwd.glob('*.xcodeproj')) or (self.cwd / 'Package.swift').exists():
            return self._detect_ios()

        raise RuntimeError("未识别为 Mobile 项目")

    def _detect_android(self) -> ProjectFingerprint:
        """Android 原生项目"""
        self._project_subtype = 'android'

        # 检测 Kotlin 还是 Java
        language = 'kotlin'
        kotlin_files = list(self.cwd.rglob('*.kt'))[:5]
        java_files = list(self.cwd.rglob('*.java'))[:5]
        if not kotlin_files and java_files:
            language = 'java'

        # 检测测试框架（解析 build.gradle）
        frameworks = {'unit': 'junit'}
        gradle_file = (self.cwd / 'app' / 'build.gradle')
        if not gradle_file.exists():
            gradle_file = (self.cwd / 'app' / 'build.gradle.kts')
        if not gradle_file.exists():
            gradle_file = (self.cwd / 'build.gradle')

        if gradle_file.exists():
            content = gradle_file.read_text(encoding='utf-8', errors='replace')
            if 'espresso' in content.lower():
                frameworks['ui'] = 'espresso'
            if 'robolectric' in content.lower():
                frameworks['unit'] = 'robolectric'
            if 'androidx.test' in content.lower():
                frameworks['integration'] = 'androidx-test'

        return ProjectFingerprint(
            project_type='mobile',
            language=language,
            frameworks=frameworks,
            capabilities={
                'headless': False,           # Android 测试通常需要模拟器/真机
                'parallel': True,            # Gradle 支持并行
                'coverage': True,            # JaCoCo
                'mutation': False,           # 暂不支持
                'screenshot': True,          # Espresso 支持
                'failure_classification': True,
                'auto_generate': True,
                'device_pool': False,        # 默认无设备池
                'cross_os': False
            },
            paths={
                'tests': 'app/src/test',
                'instrumented_tests': 'app/src/androidTest',
                'src': 'app/src/main'
            },
            run_commands={
                'unit': './gradlew test',
                'instrumented': './gradlew connectedAndroidTest',
                'build': './gradlew assembleDebug',
                'lint': './gradlew lint'
            }
        )

    def _detect_ios(self) -> ProjectFingerprint:
        """iOS 原生项目"""
        self._project_subtype = 'ios'

        # 检测 Swift / Objective-C
        language = 'swift'
        swift_files = list(self.cwd.rglob('*.swift'))[:5]
        objc_files = list(self.cwd.rglob('*.m'))[:5]
        if not swift_files and objc_files:
            language = 'objc'

        return ProjectFingerprint(
            project_type='mobile',
            language=language,
            frameworks={'unit': 'xctest', 'ui': 'xcuitest'},
            capabilities={
                'headless': False,           # iOS 模拟器有 GUI
                'parallel': True,
                'coverage': True,
                'mutation': False,
                'screenshot': True,
                'failure_classification': True,
                'auto_generate': True,
                'device_pool': False,
                'cross_os': False            # 仅 macOS
            },
            paths={
                'tests': 'Tests',
                'src': 'Sources'
            },
            run_commands={
                'unit': 'xcodebuild test -scheme <SCHEME> -destination "platform=iOS Simulator,name=iPhone 15"',
                'build': 'xcodebuild build -scheme <SCHEME>'
            }
        )

    def _detect_flutter(self) -> ProjectFingerprint:
        """Flutter 跨端项目"""
        self._project_subtype = 'flutter'

        return ProjectFingerprint(
            project_type='mobile',
            language='dart',
            frameworks={'unit': 'flutter_test', 'integration': 'integration_test'},
            capabilities={
                'headless': True,            # flutter test 默认无头
                'parallel': True,
                'coverage': True,
                'mutation': False,
                'screenshot': True,
                'failure_classification': True,
                'auto_generate': True,
                'device_pool': True,         # flutter 支持多目标
                'cross_os': True             # Android + iOS + Web + Desktop
            },
            paths={'tests': 'test', 'integration_tests': 'integration_test', 'src': 'lib'},
            run_commands={
                'unit': 'flutter test',
                'integration': 'flutter test integration_test',
                'build': 'flutter build apk',
                'lint': 'flutter analyze'
            }
        )

    def _detect_react_native(self, pkg: dict, deps: dict) -> ProjectFingerprint:
        """React Native 跨端项目"""
        self._project_subtype = 'react_native'

        frameworks = {}
        if 'jest' in deps:
            frameworks['unit'] = 'jest'
        if 'detox' in deps:
            frameworks['e2e'] = 'detox'
        elif 'appium' in deps:
            frameworks['e2e'] = 'appium'

        language = 'typescript' if (self.cwd / 'tsconfig.json').exists() else 'javascript'

        return ProjectFingerprint(
            project_type='mobile',
            language=language,
            frameworks=frameworks,
            capabilities={
                'headless': False,           # E2E 需要模拟器
                'parallel': True,
                'coverage': True,
                'mutation': False,
                'screenshot': True,
                'failure_classification': True,
                'auto_generate': True,
                'device_pool': False,
                'cross_os': True
            },
            paths={'tests': '__tests__', 'src': 'src'},
            run_commands={
                'unit': 'npm test',
                'e2e': 'npx detox test' if 'detox' in deps else 'npx appium',
                'build_android': 'cd android && ./gradlew assembleDebug',
                'build_ios': 'cd ios && xcodebuild build'
            }
        )

    def scaffold(self, plan: Dict[str, Any]) -> None:
        """创建测试目录"""
        subtype = self._project_subtype or 'android'

        if subtype == 'android':
            for d in ['app/src/test/java', 'app/src/androidTest/java']:
                (self.cwd / d).mkdir(parents=True, exist_ok=True)
        elif subtype == 'ios':
            (self.cwd / 'Tests').mkdir(exist_ok=True)
        elif subtype == 'flutter':
            for d in ['test', 'integration_test']:
                (self.cwd / d).mkdir(parents=True, exist_ok=True)
        elif subtype == 'react_native':
            (self.cwd / '__tests__').mkdir(exist_ok=True)

        print(f"[MobileAdapter] 测试目录已创建（{subtype}）")

    def generate(self, case: TestCase) -> str:
        """
        生成测试脚本(智能路由)

        根据用例特征选择最合适的工具:
        - 有 database/log 断言 → Espresso instrumented(精确验证)
        - 纯 UI 流程,无后台断言 → Maestro(确定性高、YAML 简洁)
        - 显式标记 ui_complexity=dynamic → Midscene(未来)
        """
        subtype = self._project_subtype or 'android'

        if subtype == 'android':
            tool = self._select_android_tool(case)
            if tool == 'espresso':
                return self._generate_android(case)
            elif tool == 'maestro':
                return self._generate_maestro(case)
            else:
                # 默认回退
                return self._generate_android(case)
        elif subtype == 'ios':
            return self._generate_ios(case)
        elif subtype == 'flutter':
            return self._generate_flutter(case)
        elif subtype == 'react_native':
            return self._generate_react_native(case)
        else:
            raise NotImplementedError(f"未支持的子类型：{subtype}")

    def _select_android_tool(self, case: TestCase) -> str:
        """
        为 Android 用例选择测试工具

        Returns:
            'espresso' | 'maestro' | 'robolectric'
        """
        # 规则1: 有 database/log 断言 → Espresso(需访问后台)
        if case.assertions:
            assertion_types = {a.get('type') for a in case.assertions if isinstance(a, dict)}
            if 'database' in assertion_types or 'log' in assertion_types:
                print(f"[MobileAdapter] {case.id}: 检测到 database/log 断言 → Espresso")
                return 'espresso'

        # 规则2: unit 层 → Robolectric(未来)
        if case.level.value == 'unit':
            print(f"[MobileAdapter] {case.id}: unit 层 → Robolectric(暂用 Espresso)")
            return 'espresso'  # TODO: 第三期改成 robolectric

        # 规则3: system/acceptance 纯 UI 流程 → Maestro
        if case.level.value in ('system', 'acceptance'):
            print(f"[MobileAdapter] {case.id}: system 层纯 UI → Maestro")
            return 'maestro'

        # 默认: Espresso
        print(f"[MobileAdapter] {case.id}: 默认 → Espresso")
        return 'espresso'

    def _generate_maestro(self, case: TestCase) -> str:
        """生成 Maestro flow YAML"""
        from ..maestro import MaestroAdapter

        package = self._detect_android_package()
        adapter = MaestroAdapter(self.cwd)
        return adapter.generate(case, package)

    def _detect_android_package(self) -> str:
        """
        自动检测 Android 项目真实包名
        优先级: AndroidManifest.xml > build.gradle > 'com.example.app' 回退
        """
        import re
        # 方法1: 读 AndroidManifest.xml 的 package 属性
        manifest_paths = [
            self.cwd / 'app' / 'src' / 'main' / 'AndroidManifest.xml',
            self.cwd / 'AndroidManifest.xml',
        ]
        for manifest in manifest_paths:
            if manifest.exists():
                try:
                    content = manifest.read_text(encoding='utf-8')
                    match = re.search(r'<manifest[^>]+package\s*=\s*["\']([^"\']+)["\']', content)
                    if match:
                        pkg = match.group(1)
                        print(f"[MobileAdapter] 从 {manifest.name} 检测到包名: {pkg}")
                        return pkg
                except Exception as e:
                    print(f"[MobileAdapter] 读取 {manifest} 失败: {e}")

        # 方法2: 读 build.gradle(app) 的 applicationId
        gradle_paths = [
            self.cwd / 'app' / 'build.gradle',
            self.cwd / 'app' / 'build.gradle.kts',
        ]
        for gradle in gradle_paths:
            if gradle.exists():
                try:
                    content = gradle.read_text(encoding='utf-8')
                    # Groovy: applicationId "xxx" 或 Kotlin: applicationId = "xxx"
                    match = re.search(r'applicationId\s*[="]?\s*["\']([^"\']+)["\']', content)
                    if match:
                        pkg = match.group(1)
                        print(f"[MobileAdapter] 从 {gradle.name} 检测到包名: {pkg}")
                        return pkg
                except Exception as e:
                    print(f"[MobileAdapter] 读取 {gradle} 失败: {e}")

        # 回退: 无法检测时返回通用包名（会导致路径错误，但比崩溃强）
        print("[MobileAdapter] WARNING: 无法检测真实包名，使用回退值 'com.example.app'")
        print("    建议检查 AndroidManifest.xml 或 app/build.gradle 是否存在")
        return 'com.example.app'

    def _generate_android(self, case: TestCase) -> str:
        """Android instrumented 测试生成(带真实断言)"""
        from .assertion_translator import AssertionTranslator

        # 判断测试目录:instrumented(需设备) vs unit(Robolectric)
        is_instrumented = case.level.value in ('integration', 'system', 'acceptance')
        test_dir = 'app/src/androidTest/kotlin' if is_instrumented else 'app/src/test/kotlin'

        class_name = ''.join(w.capitalize() for w in case.id.replace('-', '_').split('_'))
        package = self._detect_android_package()

        # 转译断言
        translator = AssertionTranslator(package, language='kotlin')
        translated = translator.translate(case.assertions) if case.assertions else {
            'imports': [], 'setup_code': '', 'assertion_code': '// TODO: 添加断言', 'helpers': {}
        }

        # 生成 imports
        imports = [
            'import androidx.test.ext.junit.runners.AndroidJUnit4',
            'import org.junit.Test',
            'import org.junit.runner.RunWith',
        ]
        imports.extend(translated['imports'])

        # 生成测试方法体
        steps_comment = '\n'.join(f'     * - {s}' for s in case.steps)
        expected_comment = '\n'.join(f'     * - {e}' for e in case.expected)

        # 生成 preconditions 提示(需要用户手动填充)
        precond_todos = []
        if case.preconditions:
            precond_todos.append('        // === Arrange: 准备测试数据(需手动补充) ===')
            for precond in case.preconditions:
                precond_todos.append(f'        // TODO[必填]: {precond}')
            precond_todos.append('')

        # Act 部分(从 steps 生成提示)
        act_todos = ['        // === Act: 执行操作 ===']
        for step in case.steps:
            act_todos.append(f'        // TODO: {step}')
        act_todos.append('')

        # Assert 部分(真实生成的断言代码)
        assert_code = translated['assertion_code']
        if translated['setup_code']:
            assert_code = f"{translated['setup_code']}\n\n        {assert_code}"

        # 辅助方法
        helper_methods = '\n'.join(translated['helpers'].values())

        content = f"""package {package}

{chr(10).join(imports)}

/**
 * {case.title}
 *
 * Feature: {case.feature_id}
 * Priority: {case.priority.value}
 *
 * Steps:
{steps_comment}
 *
 * Expected:
{expected_comment}
 */
@RunWith(AndroidJUnit4::class)
class {class_name} {{
    @Test
    fun test_{case.id.lower().replace('-', '_')}() {{
{chr(10).join(precond_todos)}
{chr(10).join(act_todos)}
        // === Assert: 验证结果(自动生成) ===
        {assert_code}
    }}
{helper_methods}
}}
"""

        # 写入文件(Kotlin 路径)
        filename = f"{class_name}.kt"
        filepath = self.cwd / test_dir / package.replace('.', '/') / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')

        return str(filepath.relative_to(self.cwd))

    def _generate_android_old_java_skeleton(self, case: TestCase) -> str:
        """旧版 Java 空骨架生成器(已废弃,保留作参考)"""
        is_ui = case.level.value in ('system', 'acceptance')
        test_dir = 'app/src/androidTest/java' if is_ui else 'app/src/test/java'

        class_name = ''.join(w.capitalize() for w in case.id.replace('-', '_').split('_'))
        package = self._detect_android_package()

        if is_ui:
            content = f"""package {package};

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.espresso.Espresso;
import androidx.test.espresso.matcher.ViewMatchers;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * {case.title}
 *
 * Feature: {case.feature_id}
 * Priority: {case.priority.value}
 *
 * Steps:
{chr(10).join(' * - ' + s for s in case.steps)}
 *
 * Expected:
{chr(10).join(' * - ' + e for e in case.expected)}
 */
@RunWith(AndroidJUnit4.class)
public class {class_name} {{
    @Test
    public void test_{case.id.lower().replace('-', '_')}() {{
        // TODO: 实现 Espresso UI 测试
        // 示例：Espresso.onView(ViewMatchers.withId(R.id.button)).perform(click());
    }}
}}
"""
        else:
            content = f"""package {package};

import org.junit.Test;
import static org.junit.Assert.*;

/**
 * {case.title}
 * Feature: {case.feature_id}
 */
public class {class_name} {{
    @Test
    public void test_{case.id.lower().replace('-', '_')}() {{
        // TODO: 实现单元测试
        assertTrue(true);
    }}
}}
"""

        filename = f"{class_name}.java"
        filepath = self.cwd / test_dir / package.replace('.', '/') / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')

        return str(filepath.relative_to(self.cwd))

    def _generate_ios(self, case: TestCase) -> str:
        """iOS XCTest 骨架"""
        class_name = ''.join(w.capitalize() for w in case.id.replace('-', '_').split('_')) + 'Tests'
        content = f"""import XCTest

/// {case.title}
/// Feature: {case.feature_id}
/// Priority: {case.priority.value}
class {class_name}: XCTestCase {{
    func test_{case.id.lower().replace('-', '_')}() {{
        // TODO: 实现测试
        XCTAssertTrue(true)
    }}
}}
"""
        filename = f"{class_name}.swift"
        filepath = self.cwd / 'Tests' / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')
        return str(filepath.relative_to(self.cwd))

    def _generate_flutter(self, case: TestCase) -> str:
        """Flutter test 骨架"""
        is_integration = case.level.value in ('integration', 'system', 'acceptance')
        test_dir = 'integration_test' if is_integration else 'test'

        filename = f"{case.feature_id.lower().replace('-', '_')}_{case.id.lower().replace('-', '_')}_test.dart"
        content = f"""import 'package:flutter_test/flutter_test.dart';

void main() {{
  // {case.title}
  // Feature: {case.feature_id}
  test('{case.id}: {case.title}', () {{
    // TODO: 实现测试
    expect(true, true);
  }});
}}
"""
        filepath = self.cwd / test_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')
        return str(filepath.relative_to(self.cwd))

    def _generate_react_native(self, case: TestCase) -> str:
        """React Native jest/detox 骨架"""
        is_e2e = case.level.value in ('system', 'acceptance')
        test_dir = 'e2e' if is_e2e else '__tests__'

        filename = f"{case.id.lower()}.test.ts"
        content = f"""/**
 * {case.title}
 * Feature: {case.feature_id}
 */

describe('{case.feature_id}', () => {{
  it('should {case.title}', () => {{
    // TODO: 实现测试
    expect(true).toBe(true);
  }});
}});
"""
        filepath = self.cwd / test_dir / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')
        return str(filepath.relative_to(self.cwd))

    def run(self, selection: List[TestCase], mode: str) -> RunResult:
        """执行测试"""
        subtype = self._project_subtype or 'android'

        if subtype == 'android':
            return self._run_android(selection, mode)
        elif subtype == 'flutter':
            return self._run_flutter(selection, mode)
        elif subtype == 'react_native':
            return self._run_react_native(selection, mode)
        elif subtype == 'ios':
            return self._run_ios(selection, mode)

        return RunResult(
            run_id='', mode=mode,
            total=len(selection), pass_=0, fail=0, skip=len(selection),
            cases=[]
        )

    def _run_android(self, selection: List[TestCase], mode: str) -> RunResult:
        """gradlew test"""
        is_unit_only = all(c.level.value in ('unit',) for c in selection)
        cmd_key = 'unit' if is_unit_only else 'instrumented'

        # 兼容 Windows 的 gradlew.bat
        gradlew = './gradlew'
        if (self.cwd / 'gradlew.bat').exists() and (self.cwd / 'gradlew').exists():
            import platform
            gradlew = './gradlew.bat' if platform.system() == 'Windows' else './gradlew'
        elif (self.cwd / 'gradlew.bat').exists():
            gradlew = 'gradlew.bat'

        task = 'test' if cmd_key == 'unit' else 'connectedAndroidTest'
        print(f"[MobileAdapter/Android] 执行: {gradlew} {task}")

        try:
            result = subprocess.run(
                [gradlew, task, '--continue'],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
                timeout=1800,
                shell=False
            )
            output = result.stdout + result.stderr

            # 解析 gradle test 输出
            passed = len(re.findall(r'PASSED', output))
            failed = len(re.findall(r'FAILED', output))
            skipped = len(re.findall(r'SKIPPED', output))

            # 如果没匹配到，根据 exit code 决定
            if passed + failed + skipped == 0:
                if result.returncode == 0:
                    passed = len(selection)
                else:
                    failed = len(selection)

            return RunResult(
                run_id='', mode=mode,
                total=len(selection),
                pass_=passed, fail=failed, skip=skipped,
                cases=[
                    {'case_id': c.id, 'status': 'pass' if result.returncode == 0 else 'fail',
                     'duration_ms': 0, 'error': ''}
                    for c in selection
                ]
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Android Gradle 测试超时（30 分钟）")
        except FileNotFoundError as e:
            raise RuntimeError(f"未找到 gradlew: {e}")

    def _run_flutter(self, selection: List[TestCase], mode: str) -> RunResult:
        """flutter test"""
        is_integration = any(c.level.value in ('integration', 'system', 'acceptance')
                             for c in selection)

        cmd = ['flutter', 'test', '--machine']  # --machine 输出 JSON
        if is_integration:
            cmd = ['flutter', 'test', 'integration_test', '--machine']

        try:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
                timeout=1800
            )

            # 解析 --machine 输出（每行一个 JSON 事件）
            passed = 0
            failed = 0
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line.startswith('{'):
                    continue
                try:
                    event = json.loads(line)
                    if event.get('type') == 'testDone':
                        if event.get('result') == 'success':
                            passed += 1
                        elif event.get('result') == 'failure':
                            failed += 1
                except json.JSONDecodeError:
                    continue

            return RunResult(
                run_id='', mode=mode,
                total=passed + failed,
                pass_=passed, fail=failed, skip=0,
                cases=[]
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Flutter 测试超时（30 分钟）")
        except FileNotFoundError:
            raise RuntimeError("未找到 flutter，请安装 Flutter SDK")

    def _run_react_native(self, selection: List[TestCase], mode: str) -> RunResult:
        """jest / detox"""
        is_e2e = any(c.level.value in ('system', 'acceptance') for c in selection)

        if is_e2e:
            cmd = ['npx', 'detox', 'test']
        else:
            cmd = ['npx', 'jest', '--json']

        try:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
                timeout=1800
            )
            if not is_e2e and result.stdout:
                try:
                    from ...core.report_parser import VitestReportParser  # Jest 兼容 Vitest JSON
                    parsed = VitestReportParser.parse(result.stdout)
                    return RunResult(
                        run_id='', mode=mode,
                        total=parsed['total'],
                        pass_=parsed['pass'],
                        fail=parsed['fail'],
                        skip=parsed['skip'],
                        cases=parsed['cases']
                    )
                except Exception:
                    pass

            # 兜底
            if result.returncode == 0:
                return RunResult(run_id='', mode=mode,
                                 total=len(selection), pass_=len(selection),
                                 fail=0, skip=0, cases=[])
            else:
                return RunResult(run_id='', mode=mode,
                                 total=len(selection), pass_=0,
                                 fail=len(selection), skip=0, cases=[])
        except subprocess.TimeoutExpired:
            raise RuntimeError("React Native 测试超时（30 分钟）")
        except FileNotFoundError:
            raise RuntimeError("未找到 npx，请确保 Node.js 已安装")

    def _run_ios(self, selection: List[TestCase], mode: str) -> RunResult:
        """xcodebuild test（需要用户手动指定 scheme）"""
        # iOS 测试需要 scheme/destination，无法零配置执行
        print("⚠️ iOS 测试需要在 .qa-agent.yml 中配置 commands.unit（含 scheme 和 destination）")
        return RunResult(
            run_id='', mode=mode,
            total=len(selection), pass_=0, fail=0, skip=len(selection),
            cases=[
                {'case_id': c.id, 'status': 'skip',
                 'error': 'iOS 测试需要手动配置 xcodebuild scheme'}
                for c in selection
            ]
        )

    def index_targets(self) -> Dict[str, Any]:
        """Phase 14+ 实现"""
        return {}

    def parse_report(self, raw_output: str) -> Dict[str, Any]:
        return {}

    def collect_artifacts(self, run_id: str) -> Dict[str, List[str]]:
        """收集 Android 测试报告 / 截图"""
        artifacts: Dict[str, List[str]] = {
            'logs': [], 'screenshots': [], 'videos': [], 'coverage': None
        }

        # Android: app/build/reports/tests/
        reports_dir = self.cwd / 'app' / 'build' / 'reports' / 'tests'
        if reports_dir.exists():
            artifacts['logs'] = [str(p) for p in reports_dir.rglob('*.html')]

        # Flutter: build/test_results
        flutter_results = self.cwd / 'build' / 'test_results'
        if flutter_results.exists():
            artifacts['logs'].extend([str(p) for p in flutter_results.rglob('*.json')])

        return artifacts

    def classify_failure(self, case_result: Dict[str, Any]) -> str:
        """区分环境失败和测试失败"""
        error = case_result.get('error', '').lower()

        env_keywords = [
            'no devices', 'no connected devices',
            'emulator', 'simulator not running',
            'sdk location not found',
            'gradlew: not found', 'command not found',
            'xcode-select',
        ]
        if any(kw in error for kw in env_keywords):
            return 'env'
        return 'test'
