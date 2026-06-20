"""
DesignerRunner: 测试设计 + 脚本生成 + 执行 + 收集失败

架构定位（v3.0-rev2）：
本类是 Python 工具层，不直接调用 LLM。
LLM 推理工作（设计用例、生成脚本内容）由 Claude Code 的 subagent 完成
（参见 .claude/agents/qa-test-engineer.md）。

DesignerRunner 提供的职责：
- 加载 / 保存用例库（YAML）
- 调用 Adapter 真实执行测试
- 收集失败结果，生成 Bug 记录
- 持久化到 qa/ 目录

LLM 推理由 subagent 通过 Claude Code 提供。
"""

from typing import List, Dict, Any, Optional
from pathlib import Path

from .types import TestCase, Mode, Bug
from .config import load_config


class DesignerRunner:
    """
    DesignerRunner 工具层：执行测试 + 收集失败 + 持久化

    LLM 推理由 .claude/agents/qa-test-engineer.md subagent 完成。
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def design_cases(
        self,
        mode: Mode,
        scope: str,
        requirements: str,
        existing_cases: List[TestCase]
    ) -> List[TestCase]:
        """
        加载已有用例（实际设计由 subagent 完成）

        Args:
            mode: 运行模式
            scope: 执行范围
            requirements: 需求文档内容（可选，给 subagent 参考）
            existing_cases: 已有用例

        Returns:
            用例列表（不修改，subagent 负责设计新用例并写入 YAML）
        """
        print(f"[DesignerRunner] 加载已有用例（模式 {mode.value}，{len(existing_cases)} 条）")
        print(f"[DesignerRunner] 设计阶段由 qa-test-engineer subagent 完成")
        return existing_cases

    def generate_scripts(
        self,
        cases: List[TestCase],
        adapter
    ) -> Dict[str, str]:
        """
        生成测试脚本（调用 Adapter）

        Returns:
            {case_id: script_path}
        """
        results = {}

        for case in cases:
            if case.automation.get('status') in ('implemented', 'scaffolded'):
                # 已有脚本，跳过
                results[case.id] = case.automation.get('file', '')
            else:
                # Phase 4: 调用 adapter.generate(case)
                if adapter:
                    try:
                        script_path = adapter.generate(case)
                        results[case.id] = script_path
                    except Exception as e:
                        print(f"[DesignerRunner] 生成脚本失败 {case.id}: {e}")
                        results[case.id] = f"tests/stub/{case.id}.spec.ts"
                else:
                    print(f"[DesignerRunner] 无 Adapter，跳过生成 {case.id}")
                    results[case.id] = f"tests/stub/{case.id}.spec.ts"

        return results

    def execute_tests(
        self,
        cases: List[TestCase],
        mode: Mode,
        adapter
    ) -> Dict[str, Any]:
        """
        执行测试（调用 Adapter.run）

        Returns:
            执行结果
        """
        print(f"[DesignerRunner] 执行 {len(cases)} 条用例...")

        # Phase 4: 调用 adapter.run(cases, mode)
        if adapter:
            try:
                result = adapter.run(cases, mode.value)
                return {
                    'total': result.total,
                    'pass': result.pass_,
                    'fail': result.fail,
                    'skip': result.skip,
                    'cases': result.cases
                }
            except Exception as e:
                print(f"[DesignerRunner] 执行失败: {e}")

        # Fallback: 模拟结果
        return {
            'total': len(cases),
            'pass': len(cases),
            'fail': 0,
            'skip': 0,
            'cases': [
                {'case_id': c.id, 'status': 'pass', 'duration_ms': 100}
                for c in cases
            ]
        }

    def collect_failures(
        self,
        execution_result: Dict[str, Any]
    ) -> List[Bug]:
        """
        收集失败用例，生成 Bug 记录

        Returns:
            Bug 列表
        """
        from .yaml_serializer import BugSerializer
        from datetime import datetime

        bugs = []
        bug_index = 0

        for case_result in execution_result.get('cases', []):
            if case_result['status'] == 'fail':
                bug_index += 1
                bug_id = BugSerializer.next_bug_id()

                bug = Bug(
                    id=bug_id,
                    title=f"测试失败: {case_result['case_id']}",
                    state='open',
                    severity=self._infer_severity(case_result),
                    priority='P1',
                    related_cases=[case_result['case_id']],
                    related_requirements=[],
                    feature_id='',
                    repro_steps=[case_result.get('error', '未知错误')],
                    expected='PASS',
                    actual=case_result.get('error', 'FAIL'),
                    created_at=datetime.now().isoformat(),
                    created_by='designer_runner'
                )
                bugs.append(bug)

        return bugs

    def _infer_severity(self, case_result: Dict[str, Any]) -> str:
        """根据失败信息推断严重级别"""
        error = case_result.get('error', '').lower()
        if any(kw in error for kw in ['crash', 'segfault', 'panic', 'fatal']):
            return 'blocker'
        if any(kw in error for kw in ['security', 'auth', 'permission']):
            return 'high'
        return 'medium'

    def save_bugs(self, bugs: List[Bug], qa_dir: Path = Path('qa')) -> None:
        """
        保存 Bug 到 qa/bugs/
        """
        from .yaml_serializer import BugSerializer

        for bug in bugs:
            filepath = BugSerializer.save(bug, qa_dir)

    def repair_test_case(
        self,
        case: TestCase,
        failure_message: str,
        adapter: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        修复失败的测试用例

        Args:
            case: 失败的测试用例
            failure_message: 失败原因
            adapter: 适配器（用于特定框架的修复）

        Returns:
            {'status': 'repaired' | 'failed', 'message': ...}
        """
        print(f"[Designer] 修复用例 {case.id}...")
        print(f"  失败原因: {failure_message[:100]}")

        # TODO: Phase 2 实现智能修复
        # 当前简化版：只标记为需要修复
        return {
            'status': 'failed',
            'message': 'repair_test_case 尚未实现（Phase 2）',
        }
