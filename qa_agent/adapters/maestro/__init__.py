"""
Maestro Adapter: 将 TestCase YAML 用例转译成 Maestro flow YAML

核心能力:
- YAML steps → Maestro actions (tapOn / inputText / assertVisible)
- 自动识别常见操作模式(点击、输入、等待、验证)
- 生成可直接由 Maestro CLI 执行的 .yaml flow 文件
"""

from typing import Dict, List, Any
from pathlib import Path
import re


class MaestroFlowGenerator:
    """Maestro flow 生成器"""

    def __init__(self, package_name: str):
        """
        Args:
            package_name: Android 应用包名(如 com.openclaw.agent)
        """
        self.package = package_name

    def generate(self, case_title: str, steps: List[str], expected: List[str]) -> str:
        """
        生成 Maestro flow YAML

        Args:
            case_title: 用例标题
            steps: 操作步骤列表
            expected: 预期结果列表

        Returns:
            Maestro flow YAML 字符串
        """
        flow_lines = [
            f"# {case_title}",
            f"appId: {self.package}",
            "---",
            ""
        ]

        # 启动应用
        flow_lines.append("- launchApp")
        flow_lines.append("")

        # 转译 steps
        for step in steps:
            actions = self._translate_step(step)
            flow_lines.extend(actions)
            flow_lines.append("")

        # 转译 expected(作为断言)
        if expected:
            flow_lines.append("# === 验证预期结果 ===")
            for exp in expected:
                assertions = self._translate_expected(exp)
                flow_lines.extend(assertions)
                flow_lines.append("")

        return '\n'.join(flow_lines)

    def _translate_step(self, step: str) -> List[str]:
        """
        转译单个操作步骤

        支持的模式:
        - "点击XXX" → tapOn
        - "输入XXX" → inputText
        - "触发XXX方法" → (注释,Maestro 无法直接调方法)
        - "等待XXX" → waitForAnimationToEnd
        """
        step_lower = step.lower()

        # 模式1: 点击
        if '点击' in step_lower or '点按' in step_lower or 'tap' in step_lower:
            target = self._extract_target(step)
            if target:
                return [f"- tapOn: \"{target}\""]
            else:
                return [f"# TODO: {step} (需指定具体元素ID或文本)"]

        # 模式2: 输入
        if '输入' in step_lower or 'input' in step_lower or '填写' in step_lower:
            match = re.search(r'输入["""\'](.*?)[""""]', step)
            if match:
                text = match.group(1)
                return [
                    f"# {step}",
                    f"- inputText: \"{text}\""
                ]
            else:
                return [f"# TODO: {step} (需提取具体输入内容)"]

        # 模式3: 触发方法/启动服务(Maestro 做不了,生成注释)
        if '触发' in step_lower or '调用' in step_lower or '启动' in step_lower:
            if '方法' in step or 'Service' in step or '服务' in step:
                return [
                    f"# {step}",
                    f"# ⚠️  Maestro 无法直接调用方法,需通过 UI 操作触发或使用 Espresso"
                ]

        # 模式4: 等待
        if '等待' in step_lower or 'wait' in step_lower:
            return [
                f"# {step}",
                "- waitForAnimationToEnd"
            ]

        # 模式5: 滚动
        if '滚动' in step_lower or 'scroll' in step_lower:
            return [
                f"# {step}",
                "- scroll"
            ]

        # 默认:生成 TODO
        return [f"# TODO: {step} (需手动转译成 Maestro 操作)"]

    def _translate_expected(self, expected: str) -> List[str]:
        """
        转译预期结果为 Maestro 断言

        支持:
        - "显示XXX" → assertVisible
        - "不显示XXX" → assertNotVisible
        - "包含XXX" → assertVisible(模糊匹配)
        """
        expected_lower = expected.lower()

        # 模式1: 显示/可见
        if '显示' in expected_lower or '可见' in expected_lower or 'visible' in expected_lower:
            target = self._extract_target(expected)
            if '不' in expected_lower or 'not' in expected_lower:
                return [f"- assertNotVisible: \"{target}\""]
            else:
                return [f"- assertVisible: \"{target}\""]

        # 模式2: 包含/存在
        if '包含' in expected_lower or '存在' in expected_lower or 'contains' in expected_lower:
            target = self._extract_target(expected)
            return [f"- assertVisible: \"{target}\""]

        # 模式3: 数量(Maestro 视觉断言做不了精确数量,生成警告)
        if '个' in expected or 'count' in expected_lower or '数量' in expected_lower:
            return [
                f"# ⚠️  {expected}",
                "# Maestro 视觉断言无法精确验证数量,需配合 Espresso database 断言"
            ]

        # 默认
        return [f"# TODO: 验证 {expected}"]

    def _extract_target(self, text: str) -> str:
        """
        从描述中提取目标元素(简化版,提取引号内或关键词)

        例如:
        - "点击同步按钮" → "同步"
        - "点击右下角的提交按钮" → "提交"
        """
        # 尝试提取引号内容
        match = re.search(r'["""\'](.*?)[""""]', text)
        if match:
            return match.group(1)

        # 提取关键名词(常见按钮名)
        keywords = ['同步', '提交', '登录', '注册', '保存', '取消', '确定', '返回',
                    '搜索', '刷新', '删除', '编辑', '添加', '设置']
        for kw in keywords:
            if kw in text:
                return kw

        # 回退:返回整句(用户需手动改)
        return text.strip()


class MaestroAdapter:
    """Maestro 测试适配器(集成到 Mobile Adapter 体系)"""

    def __init__(self, cwd: Path):
        self.cwd = cwd

    def generate(self, case, package_name: str) -> str:
        """
        生成 Maestro flow 文件

        Args:
            case: TestCase 对象
            package_name: Android 包名

        Returns:
            生成的 .yaml 文件路径(相对项目根)
        """
        generator = MaestroFlowGenerator(package_name)

        # 生成 flow 内容
        flow_content = generator.generate(
            case_title=case.title,
            steps=case.steps,
            expected=case.expected
        )

        # 写入文件: qa/maestro_flows/{case_id}.yaml
        output_dir = self.cwd / 'qa' / 'maestro_flows'
        output_dir.mkdir(parents=True, exist_ok=True)

        flow_file = output_dir / f'{case.id}.yaml'
        flow_file.write_text(flow_content, encoding='utf-8')

        return str(flow_file.relative_to(self.cwd))
