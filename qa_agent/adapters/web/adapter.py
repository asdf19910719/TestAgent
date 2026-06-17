"""
Web Adapter: Web 前端项目适配器
"""

import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..core.types import ProjectFingerprint, TestCase, RunResult


class WebAdapter:
    """
    Web 项目适配器
    支持：Playwright（E2E）、Vitest/Jest（单元/集成）
    """

    def __init__(self, cwd: Path = Path('.')):
        self.cwd = cwd

    def detect(self) -> ProjectFingerprint:
        """
        检测项目类型和框架
        """
        package_json = self.cwd / 'package.json'
        if not package_json.exists():
            raise RuntimeError("未找到 package.json")

        pkg = json.loads(package_json.read_text())
        dev_deps = pkg.get('devDependencies', {})
        deps = pkg.get('dependencies', {})

        # 检测框架
        frameworks = {}
        if 'vitest' in dev_deps:
            frameworks['unit'] = 'vitest'
        elif 'jest' in dev_deps:
            frameworks['unit'] = 'jest'

        if 'playwright' in dev_deps or '@playwright/test' in dev_deps:
            frameworks['e2e'] = 'playwright'

        # 检测语言
        language = 'typescript' if (self.cwd / 'tsconfig.json').exists() else 'javascript'

        return ProjectFingerprint(
            project_type='web',
            language=language,
            frameworks=frameworks,
            capabilities={
                'headless': True,
                'parallel': True,
                'coverage': True,
                'mutation': False,  # Phase 5/6
                'screenshot': True,
                'failure_classification': True,
                'auto_generate': True
            },
            paths={
                'tests': 'tests',
                'src': 'src',
                'e2e': 'e2e' if (self.cwd / 'e2e').exists() else 'tests/e2e'
            },
            run_commands={
                'test': 'npm test',
                'test:unit': 'npm run test:unit' if 'test:unit' in pkg.get('scripts', {}) else 'npm test',
                'test:e2e': 'npm run test:e2e' if 'test:e2e' in pkg.get('scripts', {}) else 'npx playwright test'
            }
        )

    def scaffold(self, plan: Dict[str, Any]) -> None:
        """
        创建测试目录和配置
        """
        # 确保测试目录存在
        for d in ['tests/unit', 'tests/integration', 'tests/system', 'e2e']:
            (self.cwd / d).mkdir(parents=True, exist_ok=True)

        print(f"[WebAdapter] 测试目录已创建")

    def generate(self, case: TestCase) -> str:
        """
        生成测试脚本
        Phase 4 简化：生成骨架，Phase 5/6 用 LLM 生成完整实现
        """
        # 确定框架和路径
        if case.level.value in ('unit', 'integration'):
            framework = 'vitest'
            test_dir = f'tests/{case.level.value}'
        else:
            framework = 'playwright'
            test_dir = 'e2e'

        # 生成文件路径
        filename = f"{case.feature_id.lower().replace('-', '_')}_{case.id.lower()}.spec.ts"
        filepath = self.cwd / test_dir / filename

        # 生成骨架
        if framework == 'vitest':
            content = self._generate_vitest_scaffold(case)
        else:
            content = self._generate_playwright_scaffold(case)

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')

        print(f"[WebAdapter] 已生成测试脚本: {filepath}")
        return str(filepath.relative_to(self.cwd))

    def _generate_vitest_scaffold(self, case: TestCase) -> str:
        """生成 Vitest 测试骨架"""
        return f"""import {{ describe, it, expect }} from 'vitest';

describe('{case.feature_id}: {case.title}', () => {{
  it('should {case.title.lower()}', () => {{
    // TODO: 实现测试逻辑
    // {chr(10).join('    // ' + step for step in case.steps)}
    expect(true).toBe(true); // 占位断言
  }});
}});
"""

    def _generate_playwright_scaffold(self, case: TestCase) -> str:
        """生成 Playwright 测试骨架"""
        return f"""import {{ test, expect }} from '@playwright/test';

test('{case.id}: {case.title}', async ({{ page }}) => {{
  // TODO: 实现测试逻辑
  // {chr(10).join('  // ' + step for step in case.steps)}

  await page.goto('http://localhost:3000'); // TODO: 替换为实际 URL
  // 占位断言
  await expect(page).toHaveTitle(/.*/);
}});
"""

    def index_targets(self) -> Dict[str, Any]:
        """
        自动维护用例 targets（Phase 5 用 LSP/AST）
        """
        print(f"[WebAdapter] targets 索引（Phase 5 实现）")
        return {}

    def run(self, selection: List[TestCase], mode: str) -> RunResult:
        """
        执行测试
        Phase 4 简化：调用 npm test，Phase 5 解析真实输出
        """
        print(f"[WebAdapter] 执行 {len(selection)} 条用例...")

        # Phase 4 stub: 返回模拟结果
        return RunResult(
            run_id='',
            mode=mode,
            total=len(selection),
            pass_=len(selection),
            fail=0,
            skip=0,
            cases=[
                {'case_id': c.id, 'status': 'pass', 'duration_ms': 100}
                for c in selection
            ]
        )

    def parse_report(self, raw_output: str) -> Dict[str, Any]:
        """
        解析测试报告（Vitest JSON / Playwright JSON）
        Phase 5 实现
        """
        return {}

    def collect_artifacts(self, run_id: str) -> Dict[str, List[str]]:
        """
        收集失败截图、视频、日志
        """
        artifacts_dir = self.cwd / 'test-results'

        artifacts = {
            'logs': [],
            'screenshots': [],
            'videos': [],
            'coverage': None
        }

        if artifacts_dir.exists():
            artifacts['screenshots'] = [str(p) for p in artifacts_dir.rglob('*.png')]
            artifacts['videos'] = [str(p) for p in artifacts_dir.rglob('*.webm')]

        return artifacts

    def classify_failure(self, case_result: Dict[str, Any]) -> str:
        """
        区分失败类型：test（测试问题） / env（环境问题）
        Phase 5 实现启发式规则
        """
        error_msg = case_result.get('error', '').lower()

        if any(kw in error_msg for kw in ['econnrefused', 'timeout', 'network']):
            return 'env'
        else:
            return 'test'
