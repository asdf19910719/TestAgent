"""
Gatekeeper: 独立判定测试结论

架构定位（v3.0-rev2）：
本类是 Python 工具层，提供算法判定（L0/L4 用算法即足够）和报告写入。
LLM 推理判定（L1/L2/L3 复杂判定、需求关联校验）由 Claude Code 的
.claude/agents/qa-gatekeeper.md subagent 完成。

Gatekeeper 工具层职责：
- 加载执行结果、用例库、Waivers
- 算法判定（L0/L4 简单规则）
- 输出报告框架（subagent 填充判定理由）
- 校验自检清单
"""

from typing import Dict, Any, List, Optional
from pathlib import Path

from .types import Mode, TestCase


class Gatekeeper:
    """
    Gatekeeper 工具层：算法判定 + 报告写入

    复杂 LLM 判定由 .claude/agents/qa-gatekeeper.md subagent 完成。
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
        判定测试结论

        Args:
            run_id: 运行 ID
            mode: 运行模式
            last_run: qa/run/last.json 内容
            requirements: 原始需求文档
            all_cases: 用例库
            waivers: qa/waivers.yml

        Returns:
            {
                'verdict': 'PASS' | 'CONDITIONAL PASS' | 'FAIL' | 'BLOCKED',
                'reason': str,
                'uncovered_requirements': List[str],
                'requirement_ids_inconsistencies': List[Dict],
                'needs_subagent_review': bool   # 是否需要 subagent 进一步判定
            }
        """
        print(f"[Gatekeeper] 判定 {mode.value} 运行 {run_id}...")

        # L0/L4 算法判定即可（不需要 subagent）
        skip_subagent_modes = self.config.get('roles', {}).get(
            'gatekeeper_skip_llm_for', ['L0', 'L4']
        )

        if mode.value in skip_subagent_modes:
            verdict = self._judge_algorithmic(mode, last_run)
            verdict['needs_subagent_review'] = False
            return verdict
        else:
            # L1/L2/L3: 算法做基础判定，标记 needs_subagent_review=True
            # 由 .claude/agents/qa-gatekeeper.md 接管深度判定
            verdict = self._judge_algorithmic(mode, last_run)
            verdict['needs_subagent_review'] = True
            verdict['subagent_input'] = {
                'run_id': run_id,
                'mode': mode.value,
                'last_run_path': 'qa/run/last.json',
                'requirements_path': 'docs/requirements.md',
                'cases_dir': 'qa/cases/',
                'waivers_path': 'qa/waivers.yml'
            }
            print(f"[Gatekeeper] L1/L2/L3 模式，已标记 needs_subagent_review=True")
            print(f"[Gatekeeper] 请用 .claude/agents/qa-gatekeeper.md subagent 完成深度判定")
            return verdict

    def _judge_algorithmic(self, mode: Mode, last_run: Dict[str, Any]) -> Dict[str, Any]:
        """
        算法判定（适用 L0/L4，作为 L1-L3 的基础判定）
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

    def validate_requirement_ids(
        self,
        cases: List[TestCase],
        requirements: str
    ) -> List[Dict[str, Any]]:
        """
        校验 requirement_ids 关联（P0-3）

        本方法返回空列表 + 标记需要 subagent 校验。
        实际语义比对由 .claude/agents/qa-gatekeeper.md subagent 完成。

        Returns:
            空列表（subagent 会写入 qa/run/last.json 的
            gatekeeper_verdict.requirement_ids_inconsistencies 字段）
        """
        print(f"[Gatekeeper] requirement_ids 校验已委派给 qa-gatekeeper subagent")
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
