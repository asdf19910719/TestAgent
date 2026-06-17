"""
Backend Adapter: Python/Go/Rust 后端项目适配器
"""

from pathlib import Path
from typing import Dict, Any, List

from ..core.types import ProjectFingerprint, TestCase, RunResult


class BackendAdapter:
    """
    Backend 项目适配器
    支持：pytest（Python）、go test、cargo test
    """

    def __init__(self, cwd: Path = Path('.')):
        self.cwd = cwd

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
        """调用 pytest 执行测试"""
        import subprocess
        import tempfile
        from ..core.report_parser import PytestReportParser

        # 收集测试文件
        test_files = list(set(c.automation.get('file') for c in cases if c.automation.get('file')))

        # 用临时文件接收 JUnit XML
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            xml_path = f.name

        cmd = ['pytest', f'--junitxml={xml_path}', '--tb=short', '-q']
        if test_files:
            cmd.extend(test_files)

        print(f"[BackendAdapter] 执行: {' '.join(cmd)}")

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
                run_id='',
                mode=mode,
                total=parsed['total'],
                pass_=parsed['pass'],
                fail=parsed['fail'],
                skip=parsed['skip'],
                cases=parsed['cases'] or []
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("pytest 执行超时（10 分钟）")
        except FileNotFoundError:
            raise RuntimeError("未找到 pytest，请运行：pip install pytest")
        finally:
            from pathlib import Path
            Path(xml_path).unlink(missing_ok=True)

    def _run_go_test(self, cases: List[TestCase], mode: str) -> RunResult:
        """调用 go test"""
        import subprocess
        from ..core.report_parser import TapReportParser

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
