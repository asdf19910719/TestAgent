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
