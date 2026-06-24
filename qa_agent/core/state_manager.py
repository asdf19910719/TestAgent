"""
State manager: 管理 last.json / history.json / selection.md
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from .types import Mode, RunResult, Checkpoint


class StateManager:
    """状态持久化管理"""

    def __init__(self, qa_dir: str = "qa"):
        self.qa_dir = Path(qa_dir)
        self.run_dir = self.qa_dir / "run"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.run_dir / "history.jsonl"  # 历史记录（追加模式）
        self.baseline_path = self.run_dir / "baseline.json"  # 用例规模基线

    def save_last_run(
        self,
        run_id: str,
        mode: Mode,
        scope: str,
        selection: Dict[str, Any],
        impact_analysis: Dict[str, Any],
        command: str = "",
        checkpoint: Optional[Checkpoint] = None
    ) -> None:
        """
        保存执行状态到 last.json
        """
        last_run = {
            "run_id": run_id,
            "mode": mode.value,
            "scope": scope,
            "status": "running",
            "trigger": {
                "source": "human",
                "command": command,
                "timestamp": datetime.now().isoformat()
            },
            "selection": selection,
            "impact_analysis": impact_analysis,
            "execution": {
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "duration_seconds": None,
                "results_by_phase": {},
                "failures": []
            },
            "repair_loop": {
                "mode": "manual",
                "rounds_used": 0,
                "max_rounds": 5
            },
            "gatekeeper_verdict": None,
            "checksum": self._compute_checksum(run_id)
        }

        if checkpoint:
            last_run["checkpoint"] = {
                "current_phase": checkpoint.current_phase,
                "phase_name": checkpoint.phase_name,
                "completed_phases": checkpoint.completed_phases,
                "git_head": checkpoint.git_head,
                "git_diff_hash": checkpoint.git_diff_hash,
                "expires_at": checkpoint.expires_at
            }

        self._atomic_write_json(self.run_dir / "last.json", last_run)

    def load_last_run(self) -> Optional[Dict[str, Any]]:
        """
        加载 last.json
        """
        path = self.run_dir / "last.json"
        if not path.exists():
            return None

        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_checkpoint(
        self,
        run_id: str,
        phase: int,
        phase_name: str,
        results: Dict[str, Any],
        git_head: str,
        git_diff_hash: str
    ) -> None:
        """
        Phase 完成后写检查点（P1-4）
        """
        last_run = self.load_last_run()
        if not last_run or last_run['run_id'] != run_id:
            raise ValueError(f"Run {run_id} not found in last.json")

        if 'checkpoint' not in last_run:
            last_run['checkpoint'] = {
                'current_phase': 1,
                'completed_phases': [],
                'git_head': git_head,
                'git_diff_hash': git_diff_hash,
                'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
            }

        last_run['checkpoint']['current_phase'] = phase + 1
        last_run['checkpoint']['completed_phases'].append({
            'phase': phase,
            'name': phase_name,
            'completed_at': datetime.now().isoformat(),
            'duration_s': results.get('duration_s', 0)
        })
        last_run['checkpoint']['git_head'] = git_head
        last_run['checkpoint']['git_diff_hash'] = git_diff_hash

        last_run['execution']['results_by_phase'][phase_name] = results
        last_run['status'] = 'running'

        self._atomic_write_json(self.run_dir / "last.json", last_run)

    def update_execution_result(
        self,
        run_id: str,
        result: RunResult,
        failures: List[Dict[str, Any]]
    ) -> None:
        """
        更新执行结果
        """
        last_run = self.load_last_run()
        if not last_run or last_run['run_id'] != run_id:
            raise ValueError(f"Run {run_id} not found")

        last_run['execution']['end_time'] = datetime.now().isoformat()
        last_run['execution']['duration_seconds'] = result.duration_seconds
        last_run['execution']['failures'] = failures
        last_run['status'] = 'completed' if result.fail == 0 else 'failed'

        self._atomic_write_json(self.run_dir / "last.json", last_run)

    def save_selection_md(
        self,
        mode: Mode,
        scope: str,
        selection: List[Any],
        diff_files: List[str],
        affected_symbols: List[str],
        impact_mode: str
    ) -> None:
        """
        写 selection.md（视图文件）
        """
        run_id = self.load_last_run()['run_id'] if self.load_last_run() else 'unknown'

        by_level = {}
        by_priority = {}
        for case in selection:
            by_level[case.level.value] = by_level.get(case.level.value, 0) + 1
            by_priority[case.priority.value] = by_priority.get(case.priority.value, 0) + 1

        content = f"""# 执行选择（{mode.value} {scope}）

运行 ID: {run_id}
影响面来源: {impact_mode}
执行模式: {mode.value}

## 变更文件

{chr(10).join(f'- {f}' for f in diff_files[:20])}
{'...' if len(diff_files) > 20 else ''}

## 受影响符号

{chr(10).join(f'- {s}' for s in affected_symbols[:20])}
{'...' if len(affected_symbols) > 20 else ''}

## 选中用例（{len(selection)} 条）

按层级: {', '.join(f'{k}={v}' for k, v in by_level.items())}
按优先级: {', '.join(f'{k}={v}' for k, v in by_priority.items())}

### 详细清单

{chr(10).join(f'- {case.id} ({case.level.value}, {case.priority.value}): {case.title}' for case in selection[:50])}
{'...' if len(selection) > 50 else ''}
"""

        (self.run_dir / "selection.md").write_text(content, encoding='utf-8')

    def save_coverage_warning(self, reason: str, existing_tests: list) -> None:
        """
        保存覆盖不足警告（L3 两阶段 prepare 时使用）

        写入 qa/run/coverage_warning.json，让 Gatekeeper 能看到。
        """
        warning = {
            'timestamp': datetime.now().isoformat(),
            'reason': reason,
            'existing_test_files': len(existing_tests),
            'by_level': {},
        }
        for t in existing_tests:
            level = t.get('level', 'unknown')
            warning['by_level'][level] = warning['by_level'].get(level, 0) + 1

        self._atomic_write_json(self.run_dir / "coverage_warning.json", warning)
        print(f"[StateManager] 覆盖警告已保存: {self.run_dir / 'coverage_warning.json'}")

    def save_main_flows(self, main_flows: list) -> None:
        """
        保存主流程清单（L3 主流程显式确认）

        写入 qa/run/main_flows.md，人类可读 + Gatekeeper 可检查。
        """
        content = "# 主流程清单（L3 Release Gate）\n\n"
        content += "> 这些是用户完成核心任务的最短路径。\n"
        content += "> Gatekeeper 会检查每条主流程是否有对应的 E2E 用例通过。\n\n"

        if not main_flows:
            content += "⚠️ **未提取到主流程清单**\n\n"
            content += "请手动补充：\n\n"
            content += "```\n1. 用户登录并进入首页\n2. 用户创建XX并提交\n3. ...\n```\n"
        else:
            for i, flow in enumerate(main_flows, 1):
                title = flow.get('title', '未知流程')
                source = flow.get('source', '')
                content += f"{i}. **{title}**\n"
                if source:
                    content += f"   - 来源: `{source}`\n"
                content += "\n"

        (self.run_dir / "main_flows.md").write_text(content, encoding='utf-8')
        print(f"[StateManager] 主流程清单已保存: {self.run_dir / 'main_flows.md'}")

    def _atomic_write_json(self, path: Path, data: Dict[str, Any]) -> None:
        """
        原子写 JSON（先写临时文件再 rename）
        """
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(path)

    def _compute_checksum(self, run_id: str) -> str:
        """
        计算 checksum
        """
        return hashlib.sha256(run_id.encode()).hexdigest()[:16]

    def append_to_history(self, run_summary: Dict[str, Any]) -> None:
        """
        追加一条执行记录到 history.jsonl

        run_summary 包含：
        - run_id / mode / scope / timestamp
        - selection: {total, by_level, by_priority}
        - result: {total, pass, fail, skip, duration}
        - gatekeeper_verdict
        """
        with open(self.history_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(run_summary, ensure_ascii=False) + '\n')

    def load_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        加载最近 N 条历史记录
        """
        if not self.history_path.exists():
            return []

        lines = self.history_path.read_text(encoding='utf-8').strip().split('\n')
        return [json.loads(line) for line in lines[-limit:] if line]

    def save_baseline(self, baseline: Dict[str, Any]) -> None:
        """
        保存/更新用例规模基线

        baseline 包含：
        - established_at: 首次建立时间（不覆盖）
        - updated_at: 最近更新时间
        - established_by: 建立时的 run_id
        - updated_by: 最近更新的 run_id
        - total_cases: 基线用例总数
        - by_module: {module_name: case_count}
        - by_level: {level: count}
        - coverage_matrix: {module: [dimension1, dimension2, ...]}
        - target_coverage: 预期覆盖标准
        - completeness: 'partial' | 'full'（L3 完成为 full）
        - history: [{run_id, mode, total_cases, timestamp}, ...]
        """
        # 合并已有基线（保留 established_at 和 history）
        existing = self.load_baseline()
        if existing:
            baseline.setdefault('established_at', existing.get('established_at'))
            baseline.setdefault('established_by', existing.get('established_by'))
            # 追加 history
            history = existing.get('history', [])
            history.append({
                'run_id': baseline.get('updated_by', 'unknown'),
                'mode': baseline.get('mode', 'unknown'),
                'total_cases': baseline.get('total_cases', 0),
                'timestamp': baseline.get('updated_at', datetime.now().isoformat()),
            })
            # 只保留最近 20 条
            baseline['history'] = history[-20:]
        else:
            baseline['history'] = []

        self._atomic_write_json(self.baseline_path, baseline)

    def update_baseline_after_run(self, run_id: str, mode: str, selection: Dict[str, Any],
                                   execution: Dict[str, Any] = None) -> None:
        """
        每次测试执行后自动更新基线

        调用时机：Engine.run() 完成后（无论什么模式）
        """
        now = datetime.now().isoformat()
        total_cases = selection.get('total', 0)

        # 只在有实际用例时更新（避免空执行覆盖已有基线）
        if total_cases == 0:
            return

        existing = self.load_baseline()

        # 计算 completeness
        completeness = 'full' if mode == 'L3' else 'partial'
        # 如果已有 full 基线，非 L3 模式不降级
        if existing and existing.get('completeness') == 'full' and mode != 'L3':
            completeness = 'full'

        # 合并用例数（取较大值，因为 L1 可能只跑了子集）
        if existing:
            existing_total = existing.get('total_cases', 0)
            total_cases = max(total_cases, existing_total)

        baseline = {
            'established_at': existing.get('established_at', now) if existing else now,
            'established_by': existing.get('established_by', run_id) if existing else run_id,
            'updated_at': now,
            'updated_by': run_id,
            'mode': mode,
            'total_cases': total_cases,
            'by_level': selection.get('by_level', {}),
            'by_priority': selection.get('by_priority', {}),
            'completeness': completeness,
            'pass_rate': execution.get('pass_rate', '') if execution else '',
            'target_coverage': '主流程全覆盖 + 异常/边界 + 容错',
        }

        self.save_baseline(baseline)
        print(f"[Baseline] 已更新: {total_cases} 条用例, "
              f"completeness={completeness}, mode={mode}")

    def load_baseline(self) -> Optional[Dict[str, Any]]:
        """
        加载基线
        """
        if not self.baseline_path.exists():
            return None

        with open(self.baseline_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def needs_baseline_refresh(self) -> bool:
        """
        判断是否需要刷新基线

        触发条件：
        - 基线不存在
        - 基线建立时间超过 30 天
        - 需求文档有重大更新（通过 git diff 判断）
        """
        baseline = self.load_baseline()
        if not baseline:
            return True

        # 检查时效性（30 天）
        established = datetime.fromisoformat(baseline['established_at'])
        if datetime.now() - established > timedelta(days=30):
            return True

        return False

    def finalize_after_manual_repair(
        self,
        verdict: str,
        verdict_reason: str,
        remaining_failures: list = None,
        fixes_applied: Dict[str, Any] = None,
        pass_rate: str = '',
        passed_case_ids: list = None,
    ) -> None:
        """
        手动修复完成后的状态回写助手（会话感知）

        修复完成后必须调用此方法，确保 last.json + baseline.json + history.jsonl 一致。

        失败清单更新逻辑（优先级从高到低）：
        - 传 remaining_failures：直接用它作为修复后的失败清单（显式覆盖）
        - 传 passed_case_ids：从现有 failures 中**只移除**已验证通过的，其余保留（增量）
        - 都不传：保持现有 failures 不变（不动）

        ⚠️ 不再无条件清空 failures。调用方（qa.md finalize 流程）必须基于真实
        重跑证据，明确告知哪些用例已验证通过（passed_case_ids），未验证的保留。

        Args:
            verdict: 'PASS' | 'CONDITIONAL PASS' | 'FAIL' | 'BLOCKED'
            verdict_reason: 判定原因
            remaining_failures: 修复后剩余的失败列表（显式覆盖）
            fixes_applied: 修复内容字典
            pass_rate: 通过率字符串
            passed_case_ids: 本次已验证通过（重跑通过）的用例 ID 列表（增量移除用）
        """
        last_run = self.load_last_run()
        if not last_run:
            print("[StateManager] 警告：last.json 不存在，无法 finalize")
            return

        now = datetime.now().isoformat()
        run_id = last_run.get('run_id', 'unknown')
        mode = last_run.get('mode', 'unknown')

        # 1. 更新 last.json
        last_run['status'] = 'completed'
        last_run.setdefault('execution', {})
        last_run['execution']['end_time'] = now

        # 计算 duration
        try:
            start = datetime.fromisoformat(last_run['execution']['start_time'])
            duration = (datetime.now() - start).total_seconds()
            last_run['execution']['duration_seconds'] = duration
        except Exception:
            pass

        # 失败清单更新（不再无条件清空）
        existing_failures = last_run['execution'].get('failures', []) or []
        if remaining_failures is not None:
            last_run['execution']['failures'] = remaining_failures
        elif passed_case_ids:
            passed_set = set(passed_case_ids)
            kept = [f for f in existing_failures if f.get('case_id') not in passed_set]
            removed = len(existing_failures) - len(kept)
            last_run['execution']['failures'] = kept
            print(f"[StateManager] 移除 {removed} 个已验证通过的失败，保留 {len(kept)} 个未解决")
        # else：保持 existing_failures 不动

        if pass_rate:
            last_run['execution']['pass_rate'] = pass_rate

        # 更新 gatekeeper_verdict
        last_run['gatekeeper_verdict'] = {
            **(last_run.get('gatekeeper_verdict') or {}),
            'verdict': verdict,
            'reason': verdict_reason,
            'judged_at': now,
        }

        self._atomic_write_json(self.run_dir / 'last.json', last_run)
        print(f"[StateManager] last.json 已更新: status=completed, verdict={verdict}")

        # 2. 更新 baseline.json
        selection = last_run.get('selection', {})
        baseline_update = {
            'updated_at': now,
            'updated_by': run_id,
            'mode': mode,
            'total_cases': selection.get('total', 0),
            'by_level': selection.get('by_level', {}),
            'by_priority': selection.get('by_priority', {}),
            'pass_rate': pass_rate,
            'completeness': 'full' if mode == 'L3' and verdict == 'PASS' else 'partial',
            'target_coverage': '主流程全覆盖 + 异常/边界 + 容错',
        }
        if fixes_applied:
            baseline_update['fixes_applied'] = fixes_applied

        self.save_baseline(baseline_update)
        print(f"[StateManager] baseline.json 已更新")

        # 3. 追加到 history.jsonl
        history_entry = {
            'run_id': run_id,
            'mode': mode,
            'timestamp': now,
            'verdict': verdict,
            'pass_rate': pass_rate,
            'manually_repaired': True,
        }
        self.append_to_history(history_entry)
        print(f"[StateManager] history.jsonl 已追加")

    def check_state_consistency(self) -> Dict[str, Any]:
        """
        检查 last.json + baseline.json 的状态一致性

        Returns:
            {
                'consistent': bool,
                'issues': [...],
                'last_run': {...},
                'baseline': {...},
            }
        """
        issues = []

        last_run = self.load_last_run()
        baseline = self.load_baseline()

        if not last_run:
            return {
                'consistent': False,
                'issues': ['last.json 不存在'],
                'last_run': None,
                'baseline': baseline,
            }

        if not baseline:
            return {
                'consistent': True,
                'issues': ['baseline.json 不存在（首次执行）'],
                'last_run': last_run,
                'baseline': None,
            }

        # 检查 1：状态是否完成
        if last_run.get('status') == 'running':
            issues.append("last.json status='running'，可能未正确完成")

        # 检查 2：last.json 与 baseline.json 是否同步
        last_run_id = last_run.get('run_id')
        baseline_run_id = baseline.get('updated_by')
        if last_run_id != baseline_run_id:
            issues.append(
                f"last.json (run_id={last_run_id}) 与 "
                f"baseline.json (updated_by={baseline_run_id}) 不一致"
            )

        # 检查 3：execution 是否有结果
        execution = last_run.get('execution', {})
        if execution.get('end_time') is None:
            issues.append("last.json execution.end_time 为空，未正确结束")

        # 检查 4：gatekeeper_verdict 是否存在
        verdict_obj = last_run.get('gatekeeper_verdict')
        if not verdict_obj:
            issues.append("last.json gatekeeper_verdict 未设置")

        # 检查 5（实质校验）：verdict 与真实失败记录是否矛盾
        # 防止「verdict=PASS 但 execution.failures 还有未解决失败」这种洗白状态
        if verdict_obj:
            verdict_str = verdict_obj.get('verdict', '')
            failures = execution.get('failures', []) or []
            if verdict_str == 'PASS' and failures:
                fail_ids = [f.get('case_id', '?') for f in failures]
                issues.append(
                    f"verdict=PASS 但 execution.failures 非空（{len(failures)} 个未解决: "
                    f"{', '.join(fail_ids)}）— 判定与真实状态矛盾"
                )

        return {
            'consistent': len(issues) == 0,
            'issues': issues,
            'last_run': last_run,
            'baseline': baseline,
        }
