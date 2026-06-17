"""
Generic Adapter: 支持任意项目（Rust/C++/Make/嵌入式/任意 CI）

主规范 §14.4 兜底实现
"""

import subprocess
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

from ..core.types import ProjectFingerprint, TestCase, RunResult


class GenericAdapter:
    """
    Generic 兜底 Adapter
    通过 .qa-agent.yml 中的 commands 配置任意测试命令
    """

    def __init__(self, cwd: Path = Path('.'), config: Optional[Dict[str, Any]] = None):
        self.cwd = cwd
        self.config = config or {}

    def detect(self) -> ProjectFingerprint:
        """
        Generic 不强制识别项目类型，使用配置中的 commands
        """
        commands = self.config.get('commands', {})

        # 推断语言
        language = self.config.get('language', 'unknown')
        if language == 'unknown':
            if (self.cwd / 'Cargo.toml').exists():
                language = 'rust'
            elif (self.cwd / 'go.mod').exists():
                language = 'go'
            elif (self.cwd / 'CMakeLists.txt').exists() or (self.cwd / 'Makefile').exists():
                language = 'cpp'
            elif (self.cwd / 'pubspec.yaml').exists():
                language = 'dart'

        return ProjectFingerprint(
            project_type='generic',
            language=language,
            frameworks={'unit': commands.get('unit', 'unknown')},
            capabilities={
                'headless': True,
                'parallel': False,  # 保守
                'coverage': False,
                'mutation': False,
                'screenshot': False,
                'failure_classification': False,
                'auto_generate': False  # Generic 不自动生成脚本
            },
            paths={'tests': 'tests', 'src': 'src'},
            run_commands=commands
        )

    def scaffold(self, plan: Dict[str, Any]) -> None:
        """创建测试目录"""
        for d in ['tests/unit', 'tests/integration']:
            (self.cwd / d).mkdir(parents=True, exist_ok=True)
        print("[GenericAdapter] 测试目录已创建")
        print("[GenericAdapter] 提示：请在 .qa-agent.yml 的 commands 中配置实际测试命令")

    def generate(self, case: TestCase) -> str:
        """
        Generic 不自动生成脚本，仅创建占位文件
        """
        filename = f"{case.feature_id.lower()}_{case.id.lower()}.test"
        filepath = self.cwd / 'tests' / case.level.value / filename

        content = f"""# Generic Test Placeholder
# Test ID: {case.id}
# Feature: {case.feature_id}
# Title: {case.title}
# Level: {case.level.value}
# Priority: {case.priority.value}

# TODO: 用你的测试框架实现以下逻辑
# Steps:
{chr(10).join('#   - ' + s for s in case.steps)}

# Expected:
{chr(10).join('#   - ' + e for e in case.expected)}
"""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')
        return str(filepath.relative_to(self.cwd))

    def run(self, selection: List[TestCase], mode: str) -> RunResult:
        """
        执行配置中的测试命令
        """
        commands = self.config.get('commands', {})

        # 按层级选择命令
        by_level = self._group_by_level(selection)
        all_cases_results = []
        total_pass = 0
        total_fail = 0
        total_skip = 0

        # 按层级映射到命令
        level_to_cmd_key = {
            'unit': 'unit',
            'integration': 'integration',
            'system': 'system',
            'acceptance': 'acceptance'
        }

        for level, cases in by_level.items():
            if not cases:
                continue

            cmd_key = level_to_cmd_key.get(level, 'unit')
            cmd_str = commands.get(cmd_key) or commands.get('test')

            if not cmd_str:
                print(f"⚠️ {level} 层级未配置命令，跳过")
                for case in cases:
                    all_cases_results.append({
                        'case_id': case.id,
                        'status': 'skip',
                        'failure_kind': 'config',
                        'duration_ms': 0,
                        'error': f'No command configured for {level}'
                    })
                    total_skip += 1
                continue

            try:
                result = self._execute_command(cmd_str, cases)
                all_cases_results.extend(result['cases'])
                total_pass += result['pass']
                total_fail += result['fail']
                total_skip += result['skip']
            except Exception as e:
                print(f"⚠️ {level} 执行失败: {e}")
                for case in cases:
                    all_cases_results.append({
                        'case_id': case.id,
                        'status': 'fail',
                        'failure_kind': 'env',
                        'duration_ms': 0,
                        'error': str(e)
                    })
                    total_fail += 1

        return RunResult(
            run_id='',
            mode=mode,
            total=len(selection),
            pass_=total_pass,
            fail=total_fail,
            skip=total_skip,
            cases=all_cases_results
        )

    def _execute_command(self, cmd_str: str, cases: List[TestCase]) -> Dict[str, Any]:
        """
        执行单条测试命令并解析输出
        """
        from ..core.report_parser import TapReportParser, PytestReportParser

        # Windows 兼容：用 shell=True 处理复合命令
        print(f"[GenericAdapter] 执行: {cmd_str}")

        try:
            result = subprocess.run(
                cmd_str,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=600
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"命令执行超时: {cmd_str}")

        output = result.stdout + '\n' + result.stderr

        # 检测输出格式并选择解析器
        parsed = self._parse_output(output, result.returncode)

        # 如果解析器没识别出任何用例，但 returncode 标识结果
        if parsed['total'] == 0:
            if result.returncode == 0:
                # 命令成功，假定全部通过
                parsed = {
                    'total': len(cases),
                    'pass': len(cases),
                    'fail': 0,
                    'skip': 0,
                    'cases': [
                        {'case_id': c.id, 'status': 'pass', 'duration_ms': 0, 'error': ''}
                        for c in cases
                    ]
                }
            else:
                # 命令失败，假定全部失败
                parsed = {
                    'total': len(cases),
                    'pass': 0,
                    'fail': len(cases),
                    'skip': 0,
                    'cases': [
                        {'case_id': c.id, 'status': 'fail', 'duration_ms': 0,
                         'error': f'Exit code {result.returncode}: {output[:500]}'}
                        for c in cases
                    ]
                }

        return parsed

    def _parse_output(self, output: str, returncode: int) -> Dict[str, Any]:
        """
        多格式输出解析（启发式）
        """
        from ..core.report_parser import TapReportParser, PytestReportParser

        # 1. 尝试 TAP
        if 'ok ' in output and ('1..' in output or 'not ok ' in output):
            return TapReportParser.parse(output)

        # 2. 尝试 cargo test 输出
        if 'test result:' in output:
            match = re.search(r'(\d+) passed.*?(\d+) failed.*?(\d+) ignored', output)
            if match:
                passed = int(match.group(1))
                failed = int(match.group(2))
                skipped = int(match.group(3))
                return {
                    'total': passed + failed + skipped,
                    'pass': passed,
                    'fail': failed,
                    'skip': skipped,
                    'cases': []
                }

        # 3. 尝试 go test 输出
        if '--- PASS' in output or '--- FAIL' in output:
            passed = output.count('--- PASS:')
            failed = output.count('--- FAIL:')
            return {
                'total': passed + failed,
                'pass': passed,
                'fail': failed,
                'skip': 0,
                'cases': []
            }

        # 4. 尝试 pytest 文本输出
        if 'PASSED' in output or 'FAILED' in output:
            return PytestReportParser.parse_text_output(output)

        # 5. 兜底：返回空
        return {'total': 0, 'pass': 0, 'fail': 0, 'skip': 0, 'cases': []}

    def _group_by_level(self, cases: List[TestCase]) -> Dict[str, List[TestCase]]:
        """按层级分组"""
        groups: Dict[str, List[TestCase]] = {}
        for case in cases:
            level = case.level.value
            groups.setdefault(level, []).append(case)
        return groups

    def index_targets(self) -> Dict[str, Any]:
        return {}

    def parse_report(self, raw_output: str) -> Dict[str, Any]:
        return self._parse_output(raw_output, 0)

    def collect_artifacts(self, run_id: str) -> Dict[str, List[str]]:
        return {'logs': [], 'screenshots': [], 'videos': [], 'coverage': None}

    def classify_failure(self, case_result: Dict[str, Any]) -> str:
        error = case_result.get('error', '').lower()
        env_keywords = ['command not found', 'no such file', 'permission denied',
                        'connection refused', 'timeout', 'cannot find']
        if any(kw in error for kw in env_keywords):
            return 'env'
        return 'test'
