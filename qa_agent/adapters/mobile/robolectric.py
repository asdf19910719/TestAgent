"""
Robolectric Adapter: 为 unit 层用例生成 JUnit + Robolectric 测试

特点:
- 无需设备/模拟器(JVM 上跑)
- 秒级执行(比 instrumented 快 10-100 倍)
- 适合纯逻辑测试(工具方法、数据转换、业务规则)

生成目标:
- 路径: app/src/test/kotlin/{package}/TcXxx.kt
- 框架: JUnit4 + Robolectric
- 支持: Android SDK shadow 对象(Context/SharedPreferences/ContentResolver)
"""

from typing import Dict, Any, List
from pathlib import Path


class RobolectricGenerator:
    """Robolectric 单元测试生成器"""

    def __init__(self, package_name: str):
        self.package = package_name

    def generate(
        self,
        case_id: str,
        class_name: str,
        title: str,
        feature_id: str,
        priority: str,
        preconditions: List[str],
        steps: List[str],
        expected: List[str],
        assertions: List[Dict[str, Any]]
    ) -> str:
        """
        生成 Robolectric 测试代码

        与 Espresso 的区别:
        - 不用 @RunWith(AndroidJUnit4) → @RunWith(RobolectricTestRunner)
        - 不用 InstrumentationRegistry → RuntimeEnvironment / ApplicationProvider
        - 更轻量的 imports
        """
        # 基础 imports
        imports = [
            'import org.junit.Test',
            'import org.junit.runner.RunWith',
            'import org.robolectric.RobolectricTestRunner',
            'import org.robolectric.annotation.Config',
            'import org.junit.Assert.*',
        ]

        # 如果有断言,加对应 imports
        if assertions:
            for assertion in assertions:
                atype = assertion.get('type')
                if atype == 'return_value' or atype == 'state':
                    # 纯逻辑断言,不需要额外 import
                    pass
                elif atype == 'database':
                    imports.append('import org.robolectric.RuntimeEnvironment')
                    imports.append('import android.provider.ContactsContract')

        imports_str = '\n'.join(sorted(set(imports)))

        # 生成测试方法体(@AI-FILL 范式,与其他端对齐)
        precond_todos = ['        // === Arrange: 准备测试数据 ===']
        precond_todos.append('        // @AI-FILL:arrange — 按下列需求 + 源码生成准备代码')
        for precond in (preconditions or ['(无显式前置)']):
            precond_todos.append(f'        // 需求: {precond}')
        precond_todos.append('')

        act_todos = ['        // === Act: 执行操作 ===']
        act_todos.append('        // @AI-FILL:act — 调用被测方法(读 targets 源码确认签名)')
        for step in steps:
            act_todos.append(f'        // 步骤: {step}')
        act_todos.append('')

        # Assert 部分(@AI-FILL,未填充则 fail 而非空过)
        assert_lines = ['        // === Assert: 验证结果 ===']
        assert_lines.append('        // @AI-FILL:assert — 按 Expected 生成真实断言')
        if assertions:
            for assertion in assertions:
                atype = assertion.get('type')
                if atype == 'return_value':
                    method = assertion.get('method', 'unknownMethod')
                    equals = assertion.get('equals')
                    assert_lines.append(f'        // 期望: {method}() 返回 == {equals}')
                elif atype == 'state':
                    field = assertion.get('field', 'unknownField')
                    equals = assertion.get('equals')
                    assert_lines.append(f'        // 期望: 状态 {field} == {equals}')
                else:
                    assert_lines.append(f'        // 期望: {atype} 断言')
        for exp in (expected or []):
            assert_lines.append(f'        // 期望: {exp}')
        # 未填充守卫:确保空骨架 fail 而非假过(红线5)
        assert_lines.append('        fail("@AI-FILL 未填充：本测试尚未实现，不得标 implemented")')

        # 生成完整代码
        steps_comment = '\n'.join(f' * {s}' for s in steps)
        expected_comment = '\n'.join(f' * {e}' for e in expected)

        content = f"""package {self.package}

{imports_str}

/**
 * {title}
 *
 * Feature: {feature_id}
 * Priority: {priority}
 *
 * Steps:
{steps_comment}
 *
 * Expected:
{expected_comment}
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])  // Android 9.0 Pie
class {class_name} {{
    @Test
    fun test_{case_id.lower().replace('-', '_')}() {{
{chr(10).join(precond_todos)}
{chr(10).join(act_todos)}
{chr(10).join(assert_lines)}
    }}
}}
"""
        return content


class RobolectricAdapter:
    """Robolectric 测试适配器"""

    def __init__(self, cwd: Path):
        self.cwd = cwd

    def generate(self, case, package_name: str) -> str:
        """
        生成 Robolectric 测试文件

        Returns:
            生成的 .kt 文件路径(相对项目根)
        """
        class_name = ''.join(w.capitalize() for w in case.id.replace('-', '_').split('_'))

        generator = RobolectricGenerator(package_name)
        content = generator.generate(
            case_id=case.id,
            class_name=class_name,
            title=case.title,
            feature_id=case.feature_id,
            priority=case.priority.value if hasattr(case.priority, 'value') else str(case.priority),
            preconditions=case.preconditions or [],
            steps=case.steps or [],
            expected=case.expected or [],
            assertions=case.assertions or []
        )

        # 写入文件: app/src/test/kotlin/{package}/TcXxx.kt
        test_dir = self.cwd / 'app' / 'src' / 'test' / 'kotlin' / package_name.replace('.', '/')
        test_dir.mkdir(parents=True, exist_ok=True)

        test_file = test_dir / f'{class_name}.kt'
        test_file.write_text(content, encoding='utf-8')

        return str(test_file.relative_to(self.cwd))
