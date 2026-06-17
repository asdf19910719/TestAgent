"""
Core data structures and types
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class Mode(str, Enum):
    """运行模式"""
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class CaseState(str, Enum):
    """用例状态"""
    ACTIVE = "active"
    REVIEW = "review"
    STALE = "stale"
    FLAKY = "flaky"
    RETIRED = "retired"


class Priority(str, Enum):
    """优先级"""
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class TestLevel(str, Enum):
    """测试层级"""
    UNIT = "unit"
    INTEGRATION = "integration"
    SYSTEM = "system"
    ACCEPTANCE = "acceptance"
    SMOKE = "smoke"
    PERFORMANCE = "performance"
    SECURITY = "security"


@dataclass
class TestCase:
    """测试用例"""
    id: str
    title: str
    state: CaseState
    feature_id: str
    requirement_ids: List[str]
    level: TestLevel
    priority: Priority
    preconditions: List[str] = field(default_factory=list)
    test_data: Dict[str, Any] = field(default_factory=dict)
    steps: List[str] = field(default_factory=list)
    expected: List[str] = field(default_factory=list)
    assertions: List[Dict[str, Any]] = field(default_factory=list)
    automation: Dict[str, Any] = field(default_factory=dict)
    targets: Dict[str, Any] = field(default_factory=dict)
    regression_tags: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class Bug:
    """缺陷记录"""
    id: str
    title: str
    state: str  # open | fixed | verified | wont_fix
    severity: str  # blocker | high | medium | low
    priority: Priority
    related_cases: List[str]
    related_requirements: List[str]
    feature_id: str
    repro_steps: List[str]
    expected: str
    actual: str
    suspected_cause: str = ""
    needs_regression: bool = True
    created_at: str = ""
    created_by: str = ""


@dataclass
class RunResult:
    """执行结果"""
    run_id: str
    mode: Mode
    total: int
    pass_: int  # 'pass' is reserved keyword
    fail: int
    skip: int
    flaky: int = 0
    cases: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class ProjectFingerprint:
    """项目指纹（Adapter detect 返回）"""
    project_type: str  # web | backend | mobile | desktop | game | generic
    language: str
    frameworks: Dict[str, str]
    capabilities: Dict[str, bool]
    paths: Dict[str, str]
    run_commands: Dict[str, str]


@dataclass
class Checkpoint:
    """检查点（L3 恢复用）"""
    current_phase: int
    phase_name: str
    completed_phases: List[Dict[str, Any]]
    git_head: str
    git_diff_hash: str
    expires_at: str
