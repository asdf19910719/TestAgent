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

    def generate_waivers_draft(
        self,
        failures: list,
        designed_cases: list,
        output_path: Path = None,
    ) -> Path:
        """
        自动生成 waivers.yml 草案

        分析每个失败用例的原因，识别可豁免的项（harness 问题、物理设备等），
        生成草案文件。**用户必须审核 + 签字确认才能生效。**

        Args:
            failures: 失败用例列表 [{case_id, message, ...}]
            designed_cases: 所有用例
            output_path: 输出路径，默认 qa/waivers.draft.yml

        Returns:
            生成的草案文件路径
        """
        from datetime import datetime, timedelta
        import yaml

        if output_path is None:
            output_path = Path('qa/waivers.draft.yml')

        # 分析每个失败用例
        waiver_candidates = []
        for failure in failures:
            case_id = failure.get('case_id', '')
            message = failure.get('message', '').lower()

            # 识别 waiver 类型
            waiver_type, waiver_reason = self._classify_failure_for_waiver(message)

            if waiver_type == 'NOT_WAIVABLE':
                # 真实 bug，不应豁免
                continue

            # 找到对应的用例
            target_case = next((c for c in designed_cases if c.id == case_id), None)
            case_title = target_case.title if target_case else case_id

            waiver_candidates.append({
                'case_id': case_id,
                'case_title': case_title,
                'bug_id': failure.get('bug_id', ''),
                'waiver_type': waiver_type,
                'reason': waiver_reason,
                'failure_message': failure.get('message', '')[:200],
                'waived_by': 'TBD-BY-USER',  # 用户必须填写
                'waived_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(days=30)).isoformat(),
                'requires_signoff': True,  # 必须签字
            })

        # 生成 YAML
        draft = {
            '# 注意': 'AI 自动生成的草案，用户必须审核 + 填写 waived_by 后才能生效',
            '# 使用方法': [
                '1. 审核每个 waiver 是否合理',
                '2. 填写 waived_by 字段（你的标识）',
                '3. 重命名为 waivers.yml（去掉 .draft）',
                '4. 执行 /qa finalize "CONDITIONAL PASS" "X/Y" --reason "..."',
            ],
            'waivers': waiver_candidates,
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'generated_by': 'qa-gatekeeper',
                'total_candidates': len(waiver_candidates),
                'requires_user_review': True,
            },
        }

        # 写入文件
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(draft, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

        print(f"[Gatekeeper] waivers 草案已生成: {output_path}")
        print(f"[Gatekeeper] 共识别 {len(waiver_candidates)} 个可豁免候选")
        print(f"[Gatekeeper] [WARN] 用户必须审核 + 填写 waived_by 才能生效")

        return output_path

    def _classify_failure_for_waiver(self, message: str) -> tuple:
        """
        分类失败原因，判断是否可豁免

        Returns:
            (waiver_type, reason)
        """
        msg = message.lower()

        # 优先级 1: 真实 bug（最优先，避免误豁免）
        if any(kw in msg for kw in [
            'typeerror',
            'referenceerror',
            'assertionerror',
            'expected',
            'undefined is not',
            'cannot read property',
            'syntaxerror',
        ]):
            return ('NOT_WAIVABLE', '代码 bug，必须修复')

        # 优先级 2: 物理设备问题
        if any(kw in msg for kw in [
            'physical device', '物理设备',
            'android device', 'ios simulator',
            'simulator not found',
            'cannot find android', 'cannot find ios',
        ]):
            return ('PHYSICAL_DEVICE', '需要物理设备测试，CI 环境缺失')

        # 优先级 3: 测试 harness 问题
        if any(kw in msg for kw in [
            'playwright',
            'vite cache',
            'harness',
            'test runner',
            'test framework',
            'webview',
        ]):
            return ('HARNESS_ISSUE', '测试框架/harness 自身问题，非代码 bug')

        # 优先级 4: 基础设施问题
        if any(kw in msg for kw in [
            'cloud api 500',
            'gateway timeout',
            '504',
            ' 500',  # API 500（注意空格避免误匹配）
            'returned 500',
            'returned 502',
            'returned 503',
            'returned 504',
            'network unreachable',
            'connection refused',
            'service unavailable',
        ]):
            return ('INFRA_ISSUE', '基础设施/服务不稳定，非代码 bug')

        # 优先级 5: LLM 相关
        if any(kw in msg for kw in [
            'llm timeout',
            'llm api',
            'minimax',
            'openai',
            'anthropic',
        ]):
            return ('INFRA_ISSUE', 'LLM API 不稳定，可用 mock 替代')

        # 优先级 6: Flaky test（最低优先级）
        if any(kw in msg for kw in [
            'timeout',
            'intermittent',
            'flaky',
            'sometimes fails',
        ]):
            return ('FLAKY_TEST', '测试不稳定，需要人工判断')

        # 默认：不可豁免（保守策略）
        return ('NOT_WAIVABLE', '无法分类，建议人工判断是否豁免')

    def load_waivers(self, waivers_path: Path = Path('qa/waivers.yml')) -> Dict[str, Any]:
        """
        加载 waivers.yml（用户已签字的版本）

        如果 waivers.yml 不存在但 waivers.draft.yml 存在，警告用户先签字。
        """
        import yaml

        if not waivers_path.exists():
            # 检查是否有草案
            draft_path = waivers_path.parent / 'waivers.draft.yml'
            if draft_path.exists():
                print(f"[Gatekeeper] [WARN] 发现未签字的 waivers 草案: {draft_path}")
                print(f"[Gatekeeper] [WARN] 请审核 + 填写 waived_by 后重命名为 waivers.yml")
            return {'waivers': []}

        with open(waivers_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        # 验证每个 waiver 都有 waived_by（不能是 TBD-BY-USER）
        valid_waivers = []
        invalid_count = 0
        for w in data.get('waivers', []):
            if w.get('waived_by') in (None, '', 'TBD-BY-USER'):
                print(f"[Gatekeeper] [WARN] Waiver {w.get('case_id')} 缺少签字（waived_by），已忽略")
                invalid_count += 1
                continue
            valid_waivers.append(w)

        if invalid_count > 0:
            print(f"[Gatekeeper] [WARN] 共 {invalid_count} 个 waiver 因缺少签字被忽略")

        return {'waivers': valid_waivers}
