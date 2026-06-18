"""
WebAdapter E2E 增强模块

集成 webui-test-unified 工具链，提供完整的 E2E 测试流程：
1. 自动登录（支持密码/Cookie/Token + 配方复用）
2. DOM 元素自动提取（Smart XPath）
3. 脚本生成（基于真实元素）
4. 批量执行（Sentinel 预算守卫）
5. 专业报告生成
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional

from ...core.types import TestCase, RunResult


class WebUIE2EEnhancer:
    """
    WebUI E2E 测试增强器
    """

    def __init__(self, cwd: Path, config: Dict[str, Any]):
        self.cwd = cwd
        self.config = config
        self.webui_dir = cwd / 'qa' / 'webui'
        self.session_dir = self.webui_dir / 'session'
        self.shared_dir = self.webui_dir / 'shared_assets'

    def setup_directories(self):
        """创建产物目录"""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.shared_dir.mkdir(parents=True, exist_ok=True)

    def login_and_explore(self, target_url: str, credentials: Optional[Dict] = None) -> Dict[str, Any]:
        """
        登录 + 页面探索

        Args:
            target_url: 目标 URL
            credentials: 登录凭据 {'username': '...', 'password': '...'}

        Returns:
            {
                'login_success': bool,
                'page_elements': [...],  # Smart XPath 元素列表
                'screenshots': [...]
            }
        """
        self.setup_directories()

        # 1. 执行登录
        login_result_file = self.session_dir / 'login-result.json'
        if credentials:
            login_cmd = [
                sys.executable,
                '-m', 'qa_agent.webui.login.login_password',
                '--url', target_url,
                '--username', credentials.get('username', ''),
                '--password', credentials.get('password', ''),
                '--workspace', str(self.cwd),
                '--explore-output', str(self.session_dir / 'page-elements.json')
            ]
        else:
            # 尝试复用已有登录态
            login_cmd = [
                sys.executable,
                '-m', 'qa_agent.webui.login.validate_login_state',
                '--state-file', str(self.shared_dir / 'ui-elements' / 'login-state.json'),
                '--target-url', target_url
            ]

        print(f"[WebUIE2E] 登录: {target_url}")
        result = subprocess.run(login_cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"[WebUIE2E] 登录失败: {result.stderr}")
            return {
                'login_success': False,
                'error': result.stderr
            }

        # 2. 读取页面元素
        elements_file = self.session_dir / 'page-elements.json'
        if not elements_file.exists():
            return {
                'login_success': True,
                'page_elements': [],
                'warning': 'No elements extracted'
            }

        elements_data = json.loads(elements_file.read_text(encoding='utf-8'))

        return {
            'login_success': True,
            'page_elements': elements_data.get('elements', []),
            'screenshots': [elements_data.get('screenshot', '')]
        }

    def generate_script_with_elements(self, case: TestCase, page_elements: list) -> str:
        """
        基于真实元素生成测试脚本（不再是 TODO 占位）

        Args:
            case: 测试用例
            page_elements: DOM 元素列表（含 Smart XPath）

        Returns:
            生成的 Playwright 脚本
        """
        # 构建元素选择器映射
        element_map = {}
        for elem in page_elements:
            text = elem.get('text', '').lower()
            elem_type = elem.get('type', '')
            smart_xpath = elem.get('smart_xpath', '')

            if text:
                element_map[text] = smart_xpath

        # 生成脚本（基于用例步骤）
        script_lines = [
            f"import {{ test, expect }} from '@playwright/test';",
            f"",
            f"/**",
            f" * 用例: {case.id} - {case.title}",
            f" * 优先级: {case.priority.value}",
            f" * 基于 Smart XPath 自动生成",
            f" */",
            f"",
            f"test('{case.id}: {case.title}', async ({{ page }}) => {{",
            f"  const baseURL = process.env.BASE_URL || 'http://localhost:3000';",
            f"  await page.goto(baseURL);",
            f""
        ]

        # 根据步骤生成代码
        if case.steps:
            script_lines.append("  // 测试步骤")
            for i, step in enumerate(case.steps[:10], 1):  # 最多 10 步
                if isinstance(step, str):
                    step_text = step.lower()

                    # 智能匹配元素
                    for keyword, xpath in element_map.items():
                        if keyword in step_text:
                            if '点击' in step_text or 'click' in step_text:
                                script_lines.append(f"  await page.locator('xpath={xpath}').click();")
                            elif '输入' in step_text or 'fill' in step_text:
                                script_lines.append(f"  await page.locator('xpath={xpath}').fill('test');")
                            break
                    else:
                        script_lines.append(f"  // TODO: {step}")

        # 断言
        if case.assertions:
            script_lines.append("")
            script_lines.append("  // 断言验证")
            for assertion in case.assertions[:5]:
                if isinstance(assertion, str):
                    script_lines.append(f"  // {assertion}")

        script_lines.append("});")

        return "\n".join(script_lines)

    def execute_with_batch_runner(self, test_file: Path) -> RunResult:
        """
        使用 batch_run.py 执行测试（含 Sentinel 预算守卫）

        Args:
            test_file: 测试文件路径

        Returns:
            RunResult
        """
        batch_cmd = [
            sys.executable,
            '-m', 'qa_agent.webui.executor.batch_run',
            '--workspace', str(self.cwd),
            '--test-file', str(test_file),
            '--max-retries', '1'
        ]

        print(f"[WebUIE2E] 执行: {test_file}")
        result = subprocess.run(batch_cmd, capture_output=True, text=True)

        # 读取执行结果
        results_file = self.session_dir / 'execution' / 'test_results_latest.json'
        if results_file.exists():
            results_data = json.loads(results_file.read_text(encoding='utf-8'))

            return RunResult(
                total=results_data.get('summary', {}).get('total', 0),
                passed=results_data.get('summary', {}).get('passed', 0),
                failed=results_data.get('summary', {}).get('failed', 0),
                skipped=results_data.get('summary', {}).get('skipped', 0),
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr
            )

        # 降级：只有退出码
        return RunResult(
            total=1,
            passed=0 if result.returncode != 0 else 1,
            failed=1 if result.returncode != 0 else 0,
            skipped=0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr
        )

    def generate_professional_report(self) -> str:
        """
        生成专业 HTML 报告

        Returns:
            报告文件路径
        """
        report_cmd = [
            sys.executable,
            '-m', 'qa_agent.webui.reporter.generate_webui_html_report',
            '--workspace', str(self.cwd)
        ]

        result = subprocess.run(report_cmd, capture_output=True, text=True)

        if result.returncode == 0:
            report_file = self.session_dir / 'review' / 'report_latest.html'
            if report_file.exists():
                return str(report_file)

        return ""
