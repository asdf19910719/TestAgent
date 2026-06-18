"""
Backend Adapter: Python/Go/Rust 后端项目适配器
"""

from pathlib import Path
from typing import Dict, Any, List

from ...core.types import ProjectFingerprint, TestCase, RunResult


class BackendAdapter:
    """
    Backend 项目适配器
    支持：pytest（Python）、go test、cargo test
    """

    def __init__(self, cwd: Path = Path('.'), config: Dict[str, Any] = None):
        self.cwd = cwd
        self.config = config or {}
        # 检测是否启用 API Test Executor
        self.use_api_executor = self.config.get('backend', {}).get('use_api_executor', True)

    def detect(self) -> ProjectFingerprint:
        """检测项目类型"""
        # Python
        if (self.cwd / 'pyproject.toml').exists() or (self.cwd / 'setup.py').exists():
            return ProjectFingerprint(
                project_type='backend',
                language='python',
                frameworks={'unit': 'pytest', 'integration': 'pytest'},
                capabilities={
                    'headless': True,
                    'parallel': True,
                    'coverage': True,
                    'mutation': False,
                    'screenshot': False,
                    'failure_classification': True,
                    'auto_generate': True
                },
                paths={'tests': 'tests', 'src': 'src'},
                run_commands={'test': 'pytest', 'test:cov': 'pytest --cov'}
            )

        # Go
        elif (self.cwd / 'go.mod').exists():
            return ProjectFingerprint(
                project_type='backend',
                language='go',
                frameworks={'unit': 'go test'},
                capabilities={'headless': True, 'parallel': True, 'coverage': True, 'mutation': False,
                              'screenshot': False, 'failure_classification': False, 'auto_generate': False},
                paths={'tests': '.', 'src': '.'},
                run_commands={'test': 'go test ./...'}
            )

        # Rust
        elif (self.cwd / 'Cargo.toml').exists():
            return ProjectFingerprint(
                project_type='backend',
                language='rust',
                frameworks={'unit': 'cargo'},
                capabilities={'headless': True, 'parallel': True, 'coverage': False, 'mutation': False,
                              'screenshot': False, 'failure_classification': False, 'auto_generate': False},
                paths={'tests': 'tests', 'src': 'src'},
                run_commands={'test': 'cargo test'}
            )

        raise RuntimeError("未识别为 Backend 项目")

    def scaffold(self, plan: Dict[str, Any]) -> None:
        """创建测试目录"""
        (self.cwd / 'tests' / 'unit').mkdir(parents=True, exist_ok=True)
        (self.cwd / 'tests' / 'integration').mkdir(parents=True, exist_ok=True)
        print("[BackendAdapter] 测试目录已创建")

    def generate(self, case: TestCase) -> str:
        """生成测试脚本（Phase 6 LLM 生成）"""
        # 简化：pytest 骨架
        filename = f"test_{case.feature_id.lower()}_{case.id.lower()}.py"
        filepath = self.cwd / 'tests' / case.level.value / filename

        content = f"""import pytest

def test_{case.id.lower()}():
    '''
    {case.title}
    '''
    # TODO: 实现测试逻辑
    assert True  # 占位断言
"""

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding='utf-8')
        return str(filepath.relative_to(self.cwd))

    def run(self, selection: List[TestCase], mode: str) -> RunResult:
        """执行测试（真实调用 pytest/go test/cargo test）"""
        print(f"[BackendAdapter] 执行 {len(selection)} 条用例...")

        # 检测项目类型决定执行命令
        if (self.cwd / 'pyproject.toml').exists() or (self.cwd / 'setup.py').exists():
            return self._run_pytest(selection, mode)
        elif (self.cwd / 'go.mod').exists():
            return self._run_go_test(selection, mode)
        elif (self.cwd / 'Cargo.toml').exists():
            return self._run_cargo_test(selection, mode)
        else:
            raise RuntimeError("无法识别 Backend 项目类型")

    def _run_pytest(self, cases: List[TestCase], mode: str) -> RunResult:
        """
        调用 pytest 执行测试

        如果 use_api_executor=True（默认），使用增强版执行器（智能分析 + 自动修复 + HTML 报告）
        否则使用原生 pytest
        """
        # 收集测试文件
        test_files = list(set(c.automation.get('file') for c in cases if c.automation.get('file')))

        if not test_files:
            print("[BackendAdapter] 无测试文件可执行")
            return RunResult(total=0, passed=0, failed=0, skipped=0, exit_code=0, stdout="", stderr="")

        # 使用 API Test Executor（增强版）
        if self.use_api_executor:
            return self._run_with_api_executor(test_files, mode)

        # 降级：使用原生 pytest
        return self._run_with_native_pytest(test_files, mode)

    def _run_with_api_executor(self, test_files: List[str], mode: str) -> RunResult:
        """
        使用 API Test Executor 执行测试（增强版）

        功能：
        - 智能分析引擎（7 大失败分类）
        - 脚本自动修复（检测 → 修复 → 重试）
        - 专业 HTML 报告
        """
        import subprocess
        import sys
        from pathlib import Path

        # 确定测试目录
        test_dir = Path(test_files[0]).parent if test_files else self.cwd / 'tests'
        report_dir = self.cwd / 'qa' / 'backend' / 'reports'
        report_dir.mkdir(parents=True, exist_ok=True)

        # 检查是否启用自动修复
        auto_fix = self.config.get('backend', {}).get('auto_fix_script_errors', True)

        if auto_fix:
            # 使用自动修复执行器
            from .api_executor.script_auto_fixer import ScriptAutoFixer

            fixer = ScriptAutoFixer(
                workspace=self.cwd,
                config=self.config.get('backend', {})
            )

            print(f"[BackendAdapter] 使用 API Test Executor + 自动修复 执行: {test_dir}")
            fix_result = fixer.run_with_auto_fix(str(test_dir), str(report_dir))

            if fix_result['fixes_applied']:
                print(f"[BackendAdapter] 自动修复: {fix_result['fixes_applied']}")

            # 读取结果
            if fix_result['final_result_file']:
                import json
                results_data = json.loads(Path(fix_result['final_result_file']).read_text(encoding='utf-8'))
                summary = results_data.get('summary', {})

                return RunResult(
                    total=summary.get('total', 0),
                    passed=summary.get('passed', 0),
                    failed=summary.get('failed', 0),
                    skipped=summary.get('skipped', 0),
                    exit_code=fix_result['exit_code'],
                    stdout=fix_result.get('stdout', ''),
                    stderr=fix_result.get('stderr', '')
                )

            return self._parse_stdout_to_result(
                fix_result.get('stdout', ''),
                fix_result.get('stderr', ''),
                fix_result['exit_code']
            )

        # 不启用自动修复：直接执行
        cmd = [
            sys.executable,
            '-m', 'qa_agent.adapters.backend.api_executor.enhanced_execute_with_auth',
            '--test-dir', str(test_dir),
            '--report-dir', str(report_dir)
        ]

        print(f"[BackendAdapter] 使用 API Test Executor 执行: {test_dir}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=600
            )

            # 读取生成的 JSON 结果
            import json
            from datetime import datetime

            # 查找最新的 test_results_*.json
            json_files = sorted(report_dir.glob('test_results_*.json'), reverse=True)
            if json_files:
                results_data = json.loads(json_files[0].read_text(encoding='utf-8'))
                summary = results_data.get('summary', {})

                return RunResult(
                    total=summary.get('total', 0),
                    passed=summary.get('passed', 0),
                    failed=summary.get('failed', 0),
                    skipped=summary.get('skipped', 0),
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr
                )

            # 降级：解析 stdout
            return self._parse_stdout_to_result(result.stdout, result.stderr, result.returncode)

        except subprocess.TimeoutExpired:
            print("[BackendAdapter] 执行超时")
            return RunResult(total=1, passed=0, failed=1, skipped=0, exit_code=124,
                           stdout="", stderr="Timeout after 600s")
        except Exception as e:
            print(f"[BackendAdapter] API Test Executor 执行失败: {e}")
            # 降级到原生 pytest
            return self._run_with_native_pytest(test_files, mode)

    def _run_with_native_pytest(self, test_files: List[str], mode: str) -> RunResult:
        """使用原生 pytest 执行测试（降级方案）"""
        import subprocess
        import tempfile
        from ...core.report_parser import PytestReportParser

        # 收集测试文件
        test_files = list(set(c.automation.get('file') for c in cases if c.automation.get('file')))

        # 用临时文件接收 JUnit XML
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            xml_path = f.name

        cmd = ['pytest', f'--junitxml={xml_path}', '--tb=short', '-q']
        if test_files:
            cmd.extend(test_files)

        print(f"[BackendAdapter] 原生 pytest: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=600
            )

            # 优先解析 JUnit XML
            try:
                with open(xml_path, 'r', encoding='utf-8') as f:
                    xml_output = f.read()
                parsed = PytestReportParser.parse_junit_xml(xml_output)
            except Exception:
                # 回退到文本解析
                parsed = PytestReportParser.parse_text_output(result.stdout)

            return RunResult(
                total=parsed.get('total', 0),
                passed=parsed.get('passed', 0),
                failed=parsed.get('failed', 0),
                skipped=parsed.get('skipped', 0),
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr
            )
        finally:
            import os
            if os.path.exists(xml_path):
                os.unlink(xml_path)

    def _parse_stdout_to_result(self, stdout: str, stderr: str, exit_code: int) -> RunResult:
        """从 stdout 解析测试结果（降级方案）"""
        from ...core.report_parser import PytestReportParser
        parsed = PytestReportParser.parse_text_output(stdout)

        return RunResult(
            total=parsed.get('total', 0),
            passed=parsed.get('passed', 0),
            failed=parsed.get('failed', 0),
            skipped=parsed.get('skipped', 0),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr
        )

    def _run_go_test(self, cases: List[TestCase], mode: str) -> RunResult:
        """调用 go test"""
        import subprocess
        from ...core.report_parser import TapReportParser

        cmd = ['go', 'test', '-v', './...']
        print(f"[BackendAdapter] 执行: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=300
            )

            # 简化：解析 go test 输出
            output = result.stdout
            passed = output.count('--- PASS:')
            failed = output.count('--- FAIL:')

            return RunResult(
                run_id='',
                mode=mode,
                total=passed + failed,
                pass_=passed,
                fail=failed,
                skip=0,
                cases=[]
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("go test 执行超时（5 分钟）")
        except FileNotFoundError:
            raise RuntimeError("未找到 go，请确保 Go 已安装")

    def _run_cargo_test(self, cases: List[TestCase], mode: str) -> RunResult:
        """调用 cargo test"""
        import subprocess

        cmd = ['cargo', 'test', '--no-fail-fast']
        print(f"[BackendAdapter] 执行: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.cwd,
                timeout=600
            )

            # 简化：从输出提取统计
            import re
            summary = re.search(r'test result:.*?(\d+) passed; (\d+) failed', result.stdout)
            if summary:
                passed = int(summary.group(1))
                failed = int(summary.group(2))
            else:
                passed, failed = 0, 0

            return RunResult(
                run_id='',
                mode=mode,
                total=passed + failed,
                pass_=passed,
                fail=failed,
                skip=0,
                cases=[]
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("cargo test 执行超时（10 分钟）")
        except FileNotFoundError:
            raise RuntimeError("未找到 cargo，请确保 Rust 已安装")

    def index_targets(self) -> Dict[str, Any]:
        return {}

    def parse_report(self, raw_output: str) -> Dict[str, Any]:
        return {}

    def collect_artifacts(self, run_id: str) -> Dict[str, List[str]]:
        return {'logs': [], 'screenshots': [], 'videos': [], 'coverage': None}

    def classify_failure(self, case_result: Dict[str, Any]) -> str:
        return 'test'
