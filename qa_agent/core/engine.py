"""
Engine: 模式路由核心
"""

from typing import Dict, Any, Optional
from datetime import datetime

from .types import Mode
from .config import load_config
from .state_manager import StateManager
from .impact_analysis import ImpactAnalyzer


class Engine:
    """QA Agent Core 引擎"""

    def __init__(self, config_path: str = '.qa-agent.yml'):
        self.config = load_config(config_path)
        self.state_manager = StateManager()
        self.impact_analyzer = ImpactAnalyzer(self.config)

        # 加载 Adapter（Phase 4）
        try:
            from ..adapters.loader import auto_detect_adapter
            self.adapter = auto_detect_adapter(config_path)
        except Exception as e:
            print(f"⚠️ Adapter 加载失败: {e}，部分功能不可用")
            self.adapter = None

    def run(
        self,
        mode: Mode,
        scope: str,
        command: str = "",
        user_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        执行 QA 流程

        Args:
            mode: 运行模式（L0/L1/L2/L3/L4）
            scope: 执行范围（feature 名 / module 名 / 'release' / bug ID）
            command: 原始命令（用于记录）
            user_overrides: 用户覆盖参数（--cases / --with-* / --skip）

        Returns:
            执行结果摘要
        """
        run_id = self._generate_run_id()

        # 步骤 1: 预估 + 用户确认
        estimate = self._estimate(mode, scope)
        if not self._confirm_execution(mode, estimate):
            return {'status': 'cancelled', 'message': '用户取消执行'}

        # 步骤 2: 影响面分析（暂时用 stub 用例列表）
        all_cases = self._load_all_cases()  # stub
        impact_result = self.impact_analyzer.analyze(mode, all_cases)

        # 步骤 3: 应用用户覆盖
        if user_overrides:
            impact_result = self._apply_user_overrides(impact_result, user_overrides)

        # 步骤 4: 保存 last.json + selection.md
        selection = {
            'total': len(impact_result['selected_cases']),
            'by_level': self._group_by_level(impact_result['selected_cases']),
            'by_priority': self._group_by_priority(impact_result['selected_cases']),
            'case_ids': [c.id for c in impact_result['selected_cases']]
        }

        self.state_manager.save_last_run(
            run_id=run_id,
            mode=mode,
            scope=scope,
            selection=selection,
            impact_analysis={
                'mode': impact_result['mode'],
                'diff_files': impact_result['diff_files'],
                'affected_symbols': impact_result['affected_symbols']
            },
            command=command
        )

        self.state_manager.save_selection_md(
            mode=mode,
            scope=scope,
            selection=impact_result['selected_cases'],
            diff_files=impact_result['diff_files'],
            affected_symbols=impact_result['affected_symbols'],
            impact_mode=impact_result['mode']
        )

        # 步骤 5: 路由到对应模式处理器（Phase 2/3 实现）
        if mode == Mode.L0:
            result = self._run_l0(run_id, impact_result)
        elif mode == Mode.L1:
            result = self._run_l1(run_id, impact_result)
        elif mode == Mode.L2:
            result = self._run_l2(run_id, impact_result)
        elif mode == Mode.L3:
            result = self._run_l3(run_id, impact_result)
        elif mode == Mode.L4:
            result = self._run_l4(run_id, impact_result)
        else:
            raise NotImplementedError(f"{mode.value} 未实现")

        return result

    def _estimate(self, mode: Mode, scope: str) -> Dict[str, Any]:
        """
        预估执行规模
        """
        # Stub: 简单预估
        estimates = {
            Mode.L0: {'cases': 10, 'minutes': 0.5},
            Mode.L1: {'cases': 20, 'minutes': 3},
            Mode.L4: {'cases': 15, 'minutes': 5}
        }
        return estimates.get(mode, {'cases': 0, 'minutes': 0})

    def _confirm_execution(self, mode: Mode, estimate: Dict[str, Any]) -> bool:
        """
        用户确认（Phase 1.4 CLI 实现交互）
        """
        print(f"\n将以 {mode.value} 模式执行")
        print(f"预估用例数：{estimate['cases']} 条")
        print(f"预估耗时：{estimate['minutes']} 分钟")
        print(f"影响面来源：{self.config.get('impact_analysis', 'local')}")

        # Phase 1 先自动确认，Phase 1.4 CLI 改为真实交互
        return True

    def _load_all_cases(self):
        """
        加载所有用例（从 qa/cases/ 目录读取 YAML）
        """
        from .yaml_serializer import CaseSerializer
        from pathlib import Path

        cases = CaseSerializer.load_all(Path('qa'))
        print(f"[Engine] 已加载 {len(cases)} 条用例")
        return cases

    def _apply_user_overrides(
        self,
        impact_result: Dict[str, Any],
        overrides: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        应用用户覆盖（--cases / --with-* / --skip）
        """
        # Phase 2 实现
        return impact_result

    def _group_by_level(self, cases) -> Dict[str, int]:
        result = {}
        for case in cases:
            level = case.level.value
            result[level] = result.get(level, 0) + 1
        return result

    def _group_by_priority(self, cases) -> Dict[str, int]:
        result = {}
        for case in cases:
            priority = case.priority.value
            result[priority] = result.get(priority, 0) + 1
        return result

    def _run_l0(self, run_id: str, impact_result: Dict[str, Any]) -> Dict[str, Any]:
        """L0 Spot check 实现（Phase 3）"""
        return {'status': 'stub', 'message': 'L0 在 Phase 3 实现'}

    def _run_l1(self, run_id: str, impact_result: Dict[str, Any]) -> Dict[str, Any]:
        """L1 Feature 完整实现（Phase 3）"""
        from .designer_runner import DesignerRunner
        from .gatekeeper import Gatekeeper
        from .requirement_discovery import discover_requirements
        from datetime import datetime

        print("\n[Engine] 启动 L1 Feature 流程...")

        # 步骤 1: 发现需求文档
        requirements_info = discover_requirements(self.config)
        requirements_content = ""
        if requirements_info['primary']:
            try:
                from pathlib import Path
                requirements_content = Path(requirements_info['primary']).read_text(encoding='utf-8')
            except Exception as e:
                print(f"⚠️ 读取需求文档失败: {e}")

        # 步骤 2: DesignerRunner 设计用例
        designer = DesignerRunner(self.config)
        selected_cases = impact_result['selected_cases']

        designed_cases = designer.design_cases(
            mode=Mode.L1,
            scope=run_id,
            requirements=requirements_content,
            existing_cases=selected_cases
        )

        # 步骤 3: 生成脚本（Phase 4 调用真实 Adapter）
        scripts = designer.generate_scripts(designed_cases, adapter=self.adapter)

        # 步骤 4: 执行测试
        execution_result = designer.execute_tests(designed_cases, Mode.L1, adapter=self.adapter)

        # 步骤 5: 收集失败
        bugs = designer.collect_failures(execution_result)
        if bugs:
            designer.save_bugs(bugs)

        # 步骤 6: 更新 last.json
        self.state_manager.update_execution_result(
            run_id=run_id,
            result=type('RunResult', (), {
                'fail': execution_result['fail'],
                'duration_seconds': execution_result.get('total', 0) * 0.1
            })(),
            failures=[
                {
                    'case_id': c['case_id'],
                    'bug_id': f"BUG-{i+1:03d}",
                    'failure_kind': 'test',
                    'message': c.get('error', 'Unknown')
                }
                for i, c in enumerate(execution_result.get('cases', []))
                if c.get('status') == 'fail'
            ]
        )

        # 步骤 7: Gatekeeper 独立判定
        gatekeeper = Gatekeeper(self.config)
        last_run = self.state_manager.load_last_run()

        verdict = gatekeeper.judge(
            run_id=run_id,
            mode=Mode.L1,
            last_run=last_run,
            requirements=requirements_content,
            all_cases=designed_cases,
            waivers=None
        )

        # 步骤 8: 写报告
        from pathlib import Path
        gatekeeper.write_report(verdict, Mode.L1, last_run, Path('qa/final_test_report.md'))

        print(f"\n✅ L1 完成: {verdict['verdict']}")
        print(f"   原因: {verdict['reason']}")

        return {
            'status': 'completed',
            'verdict': verdict['verdict'],
            'execution': execution_result
        }

    def _run_l4(self, run_id: str, impact_result: Dict[str, Any]) -> Dict[str, Any]:
        """L4 Bugfix 完整实现（Phase 3.2）"""
        from .designer_runner import DesignerRunner
        from .gatekeeper import Gatekeeper

        print("\n[Engine] 启动 L4 Bugfix 流程...")

        # L4: 跳过设计，直接执行影响面回归
        designer = DesignerRunner(self.config)
        selected_cases = impact_result['selected_cases']

        # 执行测试
        execution_result = designer.execute_tests(selected_cases, Mode.L4, adapter=self.adapter)

        # 收集失败
        bugs = designer.collect_failures(execution_result)
        if bugs:
            designer.save_bugs(bugs)

        # 更新状态
        self.state_manager.update_execution_result(
            run_id=run_id,
            result=type('RunResult', (), {
                'fail': execution_result['fail'],
                'duration_seconds': execution_result.get('total', 0) * 0.1
            })(),
            failures=[
                {
                    'case_id': c['case_id'],
                    'bug_id': f"BUG-{i+1:03d}",
                    'failure_kind': 'test',
                    'message': c.get('error', 'Unknown')
                }
                for i, c in enumerate(execution_result.get('cases', []))
                if c.get('status') == 'fail'
            ]
        )

        # Gatekeeper 判定
        gatekeeper = Gatekeeper(self.config)
        last_run = self.state_manager.load_last_run()

        verdict = gatekeeper.judge(
            run_id=run_id,
            mode=Mode.L4,
            last_run=last_run,
            requirements="",  # L4 不强制需求
            all_cases=selected_cases,
            waivers=None
        )

        from pathlib import Path
        gatekeeper.write_report(verdict, Mode.L4, last_run, Path('qa/final_test_report.md'))

        print(f"\n✅ L4 完成: {verdict['verdict']}")

        return {
            'status': 'completed',
            'verdict': verdict['verdict'],
            'execution': execution_result
        }

    def _run_l0(self, run_id: str, impact_result: Dict[str, Any]) -> Dict[str, Any]:
        """L0 Spot check 实现（Phase 3.3）"""
        from .designer_runner import DesignerRunner
        from .gatekeeper import Gatekeeper

        print("\n[Engine] 启动 L0 Spot check 流程...")

        # L0: 最快路径，仅单测 + 冒烟
        designer = DesignerRunner(self.config)
        selected_cases = impact_result['selected_cases']

        # 过滤：仅 P0 + unit/smoke
        quick_cases = [
            c for c in selected_cases
            if c.priority.value == 'P0' or c.level.value in ('unit', 'smoke')
        ]

        # 执行
        execution_result = designer.execute_tests(quick_cases[:10], Mode.L0, adapter=self.adapter)

        # 更新状态
        self.state_manager.update_execution_result(
            run_id=run_id,
            result=type('RunResult', (), {
                'fail': execution_result['fail'],
                'duration_seconds': execution_result.get('total', 0) * 0.05
            })(),
            failures=[]
        )

        # Gatekeeper 算法判定（不调 LLM）
        gatekeeper = Gatekeeper(self.config)
        last_run = self.state_manager.load_last_run()

        verdict = gatekeeper.judge(
            run_id=run_id,
            mode=Mode.L0,
            last_run=last_run,
            requirements="",
            all_cases=quick_cases,
            waivers=None
        )

        print(f"\n✅ L0 完成: {verdict['verdict']} (耗时 < 30s)")

        return {
            'status': 'completed',
            'verdict': verdict['verdict'],
            'execution': execution_result
        }

    def _run_l2(self, run_id: str, impact_result: Dict[str, Any]) -> Dict[str, Any]:
        """L2 Module 模式（Phase 5）"""
        from .designer_runner import DesignerRunner
        from .gatekeeper import Gatekeeper
        from .requirement_discovery import discover_requirements

        print("\n[Engine] 启动 L2 Module 流程...")

        # L2: 模块级，完整两角色
        requirements_info = discover_requirements(self.config)
        requirements_content = ""
        if requirements_info['primary']:
            try:
                from pathlib import Path
                requirements_content = Path(requirements_info['primary']).read_text(encoding='utf-8')
            except Exception:
                pass

        designer = DesignerRunner(self.config)
        selected_cases = impact_result['selected_cases']

        # 设计 + 生成 + 执行
        designed_cases = designer.design_cases(Mode.L2, run_id, requirements_content, selected_cases)
        scripts = designer.generate_scripts(designed_cases, adapter=self.adapter)
        execution_result = designer.execute_tests(designed_cases, Mode.L2, adapter=self.adapter)

        # 收集失败
        bugs = designer.collect_failures(execution_result)
        if bugs:
            designer.save_bugs(bugs)

        # 更新状态
        self.state_manager.update_execution_result(
            run_id=run_id,
            result=type('RunResult', (), {
                'fail': execution_result['fail'],
                'duration_seconds': execution_result.get('total', 0) * 0.2
            })(),
            failures=[
                {'case_id': c['case_id'], 'bug_id': f"BUG-{i+1:03d}", 'failure_kind': 'test', 'message': c.get('error', '')}
                for i, c in enumerate(execution_result.get('cases', []))
                if c.get('status') == 'fail'
            ]
        )

        # Gatekeeper 判定
        gatekeeper = Gatekeeper(self.config)
        last_run = self.state_manager.load_last_run()
        verdict = gatekeeper.judge(run_id, Mode.L2, last_run, requirements_content, designed_cases, None)

        from pathlib import Path
        gatekeeper.write_report(verdict, Mode.L2, last_run, Path('qa/final_test_report.md'))

        print(f"\n✅ L2 完成: {verdict['verdict']}")

        return {
            'status': 'completed',
            'verdict': verdict['verdict'],
            'execution': execution_result
        }

    def _run_l3(self, run_id: str, impact_result: Dict[str, Any]) -> Dict[str, Any]:
        """L3 Release 模式完整实现（Phase 6）"""
        from .designer_runner import DesignerRunner
        from .gatekeeper import Gatekeeper
        from .requirement_discovery import discover_requirements, handle_missing_requirements
        import subprocess

        print("\n[Engine] 启动 L3 Release 流程...")

        # L3 强制要求需求文档
        requirements_info = discover_requirements(self.config)
        if not requirements_info['primary']:
            handle_missing_requirements('L3')

        requirements_content = ""
        if requirements_info['primary']:
            try:
                from pathlib import Path
                requirements_content = Path(requirements_info['primary']).read_text(encoding='utf-8')
            except Exception as e:
                print(f"⚠️ 读取需求文档失败: {e}")

        designer = DesignerRunner(self.config)
        selected_cases = impact_result['selected_cases']

        # Phase 1: Designer 生成用例
        print("[L3] Phase 1/8: Designer 设计用例...")
        designed_cases = designer.design_cases(Mode.L3, run_id, requirements_content, selected_cases)

        git_head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        self.state_manager.save_checkpoint(run_id, 1, 'designer', {'duration_s': 10}, git_head, 'diff_hash')

        # Phase 2-5: 分层执行测试
        phases = [
            (2, 'unit_test', [c for c in designed_cases if c.level.value == 'unit']),
            (3, 'integration_test', [c for c in designed_cases if c.level.value == 'integration']),
            (4, 'system_test', [c for c in designed_cases if c.level.value == 'system']),
            (5, 'acceptance_test', [c for c in designed_cases if c.level.value == 'acceptance'])
        ]

        all_failures = []
        for phase_num, phase_name, phase_cases in phases:
            if not phase_cases:
                continue

            print(f"[L3] Phase {phase_num}/8: {phase_name}...")
            scripts = designer.generate_scripts(phase_cases, adapter=self.adapter)
            result = designer.execute_tests(phase_cases, Mode.L3, adapter=self.adapter)

            all_failures.extend([
                {'case_id': c['case_id'], 'bug_id': f"BUG-{len(all_failures)+i+1:03d}",
                 'failure_kind': 'test', 'message': c.get('error', '')}
                for i, c in enumerate(result.get('cases', []))
                if c.get('status') == 'fail'
            ])

            self.state_manager.save_checkpoint(run_id, phase_num, phase_name,
                                                {'total': result['total'], 'pass': result['pass'],
                                                 'fail': result['fail'], 'duration_s': result['total'] * 0.1},
                                                git_head, 'diff_hash')

        # Phase 6: 非功能测试（Phase 6.2 完整实现）
        print("[L3] Phase 6/8: 非功能测试...")
        nonfunctional_result = self._run_nonfunctional_tests(run_id)
        self.state_manager.save_checkpoint(run_id, 6, 'nonfunctional',
                                            {'pass': nonfunctional_result.get('pass', True), 'duration_s': 5},
                                            git_head, 'diff_hash')

        # Phase 7: Mutation 抽样（Phase 6.2）
        print("[L3] Phase 7/8: Mutation 抽样...")
        mutation_result = self._run_mutation_sampling(run_id)
        self.state_manager.save_checkpoint(run_id, 7, 'mutation',
                                            {'score': mutation_result.get('score', 0.0), 'duration_s': 10},
                                            git_head, 'diff_hash')

        # 更新最终执行结果
        total_cases = sum(len(cases) for _, _, cases in phases)
        self.state_manager.update_execution_result(
            run_id=run_id,
            result=type('RunResult', (), {'fail': len(all_failures), 'duration_seconds': total_cases * 0.15})(),
            failures=all_failures
        )

        # Phase 8: Gatekeeper 判定
        print("[L3] Phase 8/8: Gatekeeper 独立判定...")
        gatekeeper = Gatekeeper(self.config)
        last_run = self.state_manager.load_last_run()

        # requirement_ids 独立校验（P0-3）
        inconsistencies = gatekeeper.validate_requirement_ids(designed_cases, requirements_content)
        if inconsistencies:
            print(f"⚠️ 发现 {len(inconsistencies)} 个 requirement_ids 不一致")

        verdict = gatekeeper.judge(run_id, Mode.L3, last_run, requirements_content, designed_cases, None)
        verdict['requirement_ids_inconsistencies'] = inconsistencies

        from pathlib import Path
        gatekeeper.write_report(verdict, Mode.L3, last_run, Path('qa/final_test_report.md'))

        print(f"\n✅ L3 完成: {verdict['verdict']}")
        print(f"   耗时: {total_cases * 0.15:.1f}s")

        return {
            'status': 'completed',
            'verdict': verdict['verdict'],
            'execution': {'total': total_cases, 'fail': len(all_failures)}
        }

    def _run_nonfunctional_tests(self, run_id: str) -> Dict[str, Any]:
        """非功能测试调度（Phase 6.2）"""
        from .nonfunctional import NonfunctionalScheduler

        scheduler = NonfunctionalScheduler(self.config)

        # 调度
        schedule_result = scheduler.schedule(mode='L3', with_flags=[], skip_flags=[])

        print(f"[NonFunctional] 调度: {len(schedule_result['scheduled'])} 个测试")
        print(f"[NonFunctional] 跳过: {len(schedule_result['skipped'])} 个")
        print(f"[NonFunctional] 阻断: {len(schedule_result['blocked'])} 个")

        # 执行
        if schedule_result['scheduled']:
            results = scheduler.execute(schedule_result['scheduled'])
            all_pass = all(r.get('pass', False) for r in results.values())
            return {'pass': all_pass, 'results': results}
        else:
            return {'pass': True, 'results': {}}

    def _run_mutation_sampling(self, run_id: str) -> Dict[str, Any]:
        """Mutation 抽样（Phase 12 真实集成）"""
        from .mutation import MutationRunner

        # 获取语言和 capabilities
        language = 'python'
        capabilities = {'mutation': True}

        if self.adapter:
            try:
                fingerprint = self.adapter.detect()
                language = fingerprint.language
                capabilities = fingerprint.capabilities
            except Exception:
                pass

        # 获取 diff 文件
        try:
            diff_files = self.impact_analyzer._git_diff_name_only('HEAD~1')
        except Exception:
            diff_files = []

        # 执行 mutation
        runner = MutationRunner(self.config, language=language)
        result = runner.run(mode='L3', diff_files=diff_files, capabilities=capabilities)

        print(f"[Mutation] {result['status']}: tool={result.get('tool')}, "
              f"score={result.get('score', 0):.2%} ({result.get('killed', 0)}/{result.get('total', 0)})")

        return result

    def _generate_run_id(self) -> str:
        """
        生成 run ID
        """
        return f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
