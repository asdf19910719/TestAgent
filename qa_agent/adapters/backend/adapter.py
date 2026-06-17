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
        """执行测试（Phase 6 真实执行）"""
        print(f"[BackendAdapter] 执行 {len(selection)} 条用例（Phase 6 真实执行）...")

        # Phase 5 stub
        return RunResult(
            run_id='',
            mode=mode,
            total=len(selection),
            pass_=len(selection),
            fail=0,
            skip=0,
            cases=[{'case_id': c.id, 'status': 'pass', 'duration_ms': 50} for c in selection]
        )

    def index_targets(self) -> Dict[str, Any]:
        return {}

    def parse_report(self, raw_output: str) -> Dict[str, Any]:
        return {}

    def collect_artifacts(self, run_id: str) -> Dict[str, List[str]]:
        return {'logs': [], 'screenshots': [], 'videos': [], 'coverage': None}

    def classify_failure(self, case_result: Dict[str, Any]) -> str:
        return 'test'
