"""
YAML 序列化/反序列化：TestCase 和 Bug 持久化

主规范 §9.2 用例 YAML schema 实现
"""

import yaml
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from .types import (
    TestCase, Bug, CaseState, Priority, TestLevel
)


class CaseSerializer:
    """TestCase YAML 序列化器"""

    @staticmethod
    def to_dict(case: TestCase) -> Dict[str, Any]:
        """TestCase → dict"""
        return {
            'id': case.id,
            'title': case.title,
            'state': case.state.value,
            'feature_id': case.feature_id,
            'requirement_ids': case.requirement_ids,
            'level': case.level.value,
            'purpose': 'functional',  # 简化字段
            'priority': case.priority.value,
            'preconditions': case.preconditions,
            'test_data': case.test_data,
            'steps': case.steps,
            'expected': case.expected,
            'assertions': case.assertions,
            'automation': case.automation or {
                'status': 'manual',
                'framework': '',
                'file': '',
                'test_id': ''
            },
            'targets': case.targets or {
                'files': [],
                'symbols': [],
                'generated_by': '',
                'generated_at': ''
            },
            'regression_tags': case.regression_tags,
            'notes': case.notes
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> TestCase:
        """dict → TestCase"""
        return TestCase(
            id=data['id'],
            title=data['title'],
            state=CaseState(data.get('state', 'active')),
            feature_id=data.get('feature_id', ''),
            requirement_ids=data.get('requirement_ids', []),
            level=TestLevel(data.get('level', 'unit')),
            priority=Priority(data.get('priority', 'P2')),
            preconditions=data.get('preconditions', []),
            test_data=data.get('test_data', {}),
            steps=data.get('steps', []),
            expected=data.get('expected', []),
            assertions=data.get('assertions', []),
            automation=data.get('automation', {}),
            targets=data.get('targets', {}),
            regression_tags=data.get('regression_tags', []),
            notes=data.get('notes', '')
        )

    @staticmethod
    def save(case: TestCase, qa_dir: Path = Path('qa')) -> Path:
        """保存用例到 qa/cases/<feature>/<case_id>.yml"""
        feature_dir = qa_dir / 'cases' / case.feature_id
        feature_dir.mkdir(parents=True, exist_ok=True)

        filepath = feature_dir / f"{case.id}.yml"
        data = CaseSerializer.to_dict(case)

        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return filepath

    @staticmethod
    def load(filepath: Path) -> TestCase:
        """从文件加载用例"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return CaseSerializer.from_dict(data)

    @staticmethod
    def load_all(qa_dir: Path = Path('qa')) -> List[TestCase]:
        """加载所有用例"""
        cases_dir = qa_dir / 'cases'
        if not cases_dir.exists():
            return []

        cases = []
        for yml_file in cases_dir.rglob('*.yml'):
            try:
                cases.append(CaseSerializer.load(yml_file))
            except Exception as e:
                print(f"⚠️ 加载用例失败 {yml_file}: {e}")
        return cases

    @staticmethod
    def load_by_id(case_id: str, qa_dir: Path = Path('qa')) -> Optional[TestCase]:
        """根据 ID 加载用例"""
        cases_dir = qa_dir / 'cases'
        for yml_file in cases_dir.rglob(f'{case_id}.yml'):
            return CaseSerializer.load(yml_file)
        return None


class BugSerializer:
    """Bug YAML 序列化器"""

    @staticmethod
    def to_dict(bug: Bug) -> Dict[str, Any]:
        """Bug → dict"""
        return {
            'id': bug.id,
            'title': bug.title,
            'state': bug.state,
            'severity': bug.severity,
            'priority': bug.priority if isinstance(bug.priority, str) else bug.priority.value,
            'related_cases': bug.related_cases,
            'related_requirements': bug.related_requirements,
            'feature_id': bug.feature_id,
            'repro_steps': bug.repro_steps,
            'expected': bug.expected,
            'actual': bug.actual,
            'suspected_cause': bug.suspected_cause,
            'needs_regression': bug.needs_regression,
            'created_at': bug.created_at,
            'created_by': bug.created_by
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Bug:
        """dict → Bug"""
        return Bug(
            id=data['id'],
            title=data['title'],
            state=data.get('state', 'open'),
            severity=data.get('severity', 'medium'),
            priority=data.get('priority', 'P2'),
            related_cases=data.get('related_cases', []),
            related_requirements=data.get('related_requirements', []),
            feature_id=data.get('feature_id', ''),
            repro_steps=data.get('repro_steps', []),
            expected=data.get('expected', ''),
            actual=data.get('actual', ''),
            suspected_cause=data.get('suspected_cause', ''),
            needs_regression=data.get('needs_regression', True),
            created_at=data.get('created_at', ''),
            created_by=data.get('created_by', '')
        )

    @staticmethod
    def save(bug: Bug, qa_dir: Path = Path('qa')) -> Path:
        """保存 Bug 到 qa/bugs/<id>.yml"""
        bugs_dir = qa_dir / 'bugs'
        bugs_dir.mkdir(parents=True, exist_ok=True)

        if not bug.created_at:
            bug.created_at = datetime.now().isoformat()

        filepath = bugs_dir / f"{bug.id}.yml"
        data = BugSerializer.to_dict(bug)

        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        return filepath

    @staticmethod
    def load(filepath: Path) -> Bug:
        """从文件加载 Bug"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return BugSerializer.from_dict(data)

    @staticmethod
    def load_by_id(bug_id: str, qa_dir: Path = Path('qa')) -> Optional[Bug]:
        """根据 ID 加载 Bug"""
        filepath = qa_dir / 'bugs' / f'{bug_id}.yml'
        if not filepath.exists():
            return None
        return BugSerializer.load(filepath)

    @staticmethod
    def load_all(qa_dir: Path = Path('qa'), state_filter: Optional[str] = None) -> List[Bug]:
        """加载所有 Bug，可按 state 过滤"""
        bugs_dir = qa_dir / 'bugs'
        if not bugs_dir.exists():
            return []

        bugs = []
        for yml_file in bugs_dir.glob('*.yml'):
            try:
                bug = BugSerializer.load(yml_file)
                if state_filter is None or bug.state == state_filter:
                    bugs.append(bug)
            except Exception as e:
                print(f"⚠️ 加载 Bug 失败 {yml_file}: {e}")
        return bugs

    @staticmethod
    def next_bug_id(qa_dir: Path = Path('qa')) -> str:
        """生成下一个 Bug ID"""
        bugs_dir = qa_dir / 'bugs'
        bugs_dir.mkdir(parents=True, exist_ok=True)

        existing = list(bugs_dir.glob('BUG-*.yml'))
        if not existing:
            return 'BUG-001'

        # 提取最大编号
        max_num = 0
        for f in existing:
            try:
                num = int(f.stem.replace('BUG-', ''))
                max_num = max(max_num, num)
            except ValueError:
                pass

        return f'BUG-{max_num + 1:03d}'
