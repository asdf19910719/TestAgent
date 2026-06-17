"""
Gatekeeper: 独立判定测试结论
"""

from typing import Dict, Any, List, Optional
from pathlib import Path

from .types import Mode, TestCase


class Gatekeeper:
    """
    Gatekeeper 角色：独立上下文判定 PASS/FAIL/BLOCKED
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def judge(
        self,
        run_id: str,
        mode: Mode,
        last_run: Dict[str, Any],
        requirements: str,
        all_cases: List[TestCase],
        waivers: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        独立判定测试结论

        Args:
            run_id: 运行 ID
            mode: 运行模式
            last_run: qa/run/last.json 内容
            requirements: 原始需求文档（独立读取，不 trust Designer）
            all_cases: 用例库
            waivers: qa/waivers.yml

        Returns:
            {
                'verdict': 'PASS' | 'CONDITIONAL PASS' | 'FAIL' | 'BLOCKED',
                'reason': str,
                'uncovered_requirements': List[str],
                'requirement_ids_inconsistencies': List[Dict]
            }
        """
        print(f"[Gatekeeper] 独立判定 {mode.value} 运行 {run_id}...")

        # Phase 2 简化：基于算法判定（L0/L4）或简单 LLM（L1/L2/L3）
        skip_llm_modes = self.config.get('roles', {}).get('gatekeeper_skip_llm_for', ['L0', 'L4'])

        if mode.value in skip_llm_modes:
            return self._judge_algorithmic(mode, last_run)
        else:
            # Phase 2: 简化 LLM 判定，Phase 3 完整实现
            return self._judge_with_llm(mode, last_run, requirements, all_cases, waivers)

    def _judge_algorithmic(self, mode: Mode, last_run: Dict[str, Any]) -> Dict[str, Any]:
        """
        算法判定（L0/L4 不调 LLM，成本优化 P1-1）
        """
        execution = last_run.get('execution', {})
        failures = execution.get('failures', [])

        # 简单规则：有 P0 失败 → FAIL，否则 PASS
        p0_failures = [f for f in failures if self._is_p0_case(f.get('case_id', ''))]

        if p0_failures:
            return {
                'verdict': 'FAIL',
                'reason': f"存在 {len(p0_failures)} 个 P0 用例失败",
                'uncovered_requirements': [],
                'requirement_ids_inconsistencies': []
            }
        elif failures:
            return {
                'verdict': 'CONDITIONAL PASS',
                'reason': f"P0 全通过，但存在 {len(failures)} 个 P1/P2 失败",
                'uncovered_requirements': [],
                'requirement_ids_inconsistencies': []
            }
        else:
            return {
                'verdict': 'PASS',
                'reason': '所有用例通过',
                'uncovered_requirements': [],
                'requirement_ids_inconsistencies': []
            }

    def _judge_with_llm(
        self,
        mode: Mode,
        last_run: Dict[str, Any],
        requirements: str,
        all_cases: List[TestCase],
        waivers: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        LLM 判定（L1/L2/L3）
        Phase 2 简化，Phase 3 调用真实 LLM
        """
        print(f"[Gatekeeper] 使用 LLM 判定（Phase 3 完整实现）")

        execution = last_run.get('execution', {})
        failures = execution.get('failures', [])

        # Phase 2 stub: 同算法判定
        if failures:
            return {
                'verdict': 'FAIL',
                'reason': f"存在 {len(failures)} 个用例失败",
                'uncovered_requirements': [],
                'requirement_ids_inconsistencies': []
            }
        else:
            return {
                'verdict': 'PASS',
                'reason': '所有用例通过',
                'uncovered_requirements': [],
                'requirement_ids_inconsistencies': []
            }

    def validate_requirement_ids(
        self,
        cases: List[TestCase],
        requirements: str
    ) -> List[Dict[str, Any]]:
        """
        独立校验 requirement_ids 关联（P0-3）
        Phase 3 调用 LLM 语义比对
        """
        print(f"[Gatekeeper] 校验 requirement_ids（Phase 3 LLM 实现）")

        # Phase 2 stub: 返回空（无不一致）
        return []

    def write_report(
        self,
        verdict: Dict[str, Any],
        mode: Mode,
        last_run: Dict[str, Any],
        output_path: Path = Path('qa/final_test_report.md')
    ) -> None:
        """
        输出测试报告
        """
        execution = last_run.get('execution', {})

        report = f"""# 测试报告

运行模式: {mode.value}
运行 ID: {last_run['run_id']}
开始时间: {execution.get('start_time', 'N/A')}
结束时间: {execution.get('end_time', 'N/A')}

## 执行统计

总数: {last_run['selection']['total']}
通过: {len([c for c in execution.get('cases', []) if c.get('status') == 'pass'])}
失败: {len(execution.get('failures', []))}

## 失败用例

{''.join(f"- {f['bug_id']}: {f['message']} ({f['case_id']})" + chr(10) for f in execution.get('failures', []))}

## 判定结论

结论: {verdict['verdict']}
理由: {verdict['reason']}

## 未能验证的事项

- 完整执行在 Phase 3 实现
"""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding='utf-8')

        print(f"[Gatekeeper] 报告已写入: {output_path}")

    def _is_p0_case(self, case_id: str) -> bool:
        """
        判断是否 P0 用例（简化）
        """
        # Phase 3: 查询用例库
        return 'P0' in case_id.upper()
