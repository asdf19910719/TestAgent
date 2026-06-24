"""
Impact analysis: 影响面分析算法
"""

import subprocess
from pathlib import Path
from typing import List, Dict, Any, Set
from .types import TestCase, Mode
from .config import load_config


class ImpactAnalyzer:
    """影响面分析"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @property
    def mode(self) -> str:
        """动态读取 impact_analysis 模式（支持运行时覆盖）"""
        return self.config.get('impact_analysis', 'gitnexus')

    def analyze(
        self,
        mode: Mode,
        all_cases: List[TestCase],
        diff_base: str = 'HEAD~1',
        scope: str = None
    ) -> Dict[str, Any]:
        """
        执行影响面分析
        返回: {
            'mode': 'gitnexus' | 'local' | 'full',
            'diff_files': List[str],
            'affected_symbols': List[str],
            'selected_cases': List[TestCase]
        }

        Args:
            scope: 本次运行范围（feature/module 名）。当 targets 匹配为空时，
                   用作兜底——选中 feature_id 关联 scope 的用例。详见 _scope_fallback。
        """
        # L3 模式：选全部用例，不限于 diff（发版门必须覆盖全部功能）
        if mode == Mode.L3:
            active_cases = [
                c for c in all_cases
                if c.state.value in ('active', 'review')
            ]
            # 仍然获取 diff 信息（用于 mutation 测试范围，但不限制用例选择）
            try:
                diff_files = self._git_diff_name_only(diff_base)
            except Exception:
                diff_files = []
            return {
                'mode': 'full',
                'diff_files': diff_files,
                'affected_symbols': [],
                'selected_cases': active_cases
            }

        if self.mode == 'gitnexus':
            try:
                return self._analyze_gitnexus(mode, all_cases, diff_base, scope)
            except Exception as e:
                fallback = self.config.get('impact_fallback', 'prompt')
                if fallback == 'local':
                    print(f"⚠️ GitNexus 不可用: {e}. 回退到 local 模式")
                    return self._analyze_local(mode, all_cases, diff_base, scope)
                elif fallback == 'fail':
                    raise
                else:
                    raise RuntimeError(
                        f"GitNexus 不可用: {e}\n"
                        f"请选择: 1) 等待修复 2) 切到 local 模式 3) 取消"
                    )
        else:
            return self._analyze_local(mode, all_cases, diff_base, scope)

    def _analyze_local(
        self,
        mode: Mode,
        all_cases: List[TestCase],
        diff_base: str,
        scope: str = None
    ) -> Dict[str, Any]:
        """
        Local 模式：基于 git diff 文件名前缀匹配（规范 §8.2）
        """
        # 步骤 1: git diff --name-only
        diff_files = self._git_diff_name_only(diff_base)

        # 步骤 2: 匹配 targets.files 前缀
        hit_cases = []
        for case in all_cases:
            if case.state.value not in ('active', 'review'):
                continue

            targets_files = case.targets.get('files', [])
            for changed_file in diff_files:
                if any(changed_file.startswith(target) for target in targets_files):
                    hit_cases.append(case)
                    break

        # 步骤 3: 补集兜底（同 feature_id）
        feature_ids = set(c.feature_id for c in hit_cases)
        补集 = [
            c for c in all_cases
            if c.feature_id in feature_ids and c not in hit_cases and c.state.value in ('active', 'review')
        ]

        # 步骤 4: 优先级过滤
        priority_filter = self._get_priority_filter(mode)
        final_selection = [
            c for c in (hit_cases + 补集)
            if c.priority.value in priority_filter
        ]

        # 步骤 5: scope 兜底（targets 全空/无匹配时，按 scope 关联 feature）
        final_selection = self._scope_fallback(
            final_selection, all_cases, scope, priority_filter
        )

        return {
            'mode': 'local',
            'diff_files': diff_files,
            'affected_symbols': [],  # local 不分析符号
            'selected_cases': self._deduplicate(final_selection)
        }

    def _analyze_gitnexus(
        self,
        mode: Mode,
        all_cases: List[TestCase],
        diff_base: str,
        scope: str = None
    ) -> Dict[str, Any]:
        """
        GitNexus 模式：基于代码图精确分析（规范 §8.1）
        Phase 2 实现
        """
        from .gitnexus import get_gitnexus_client

        # 步骤 1: 获取 GitNexus 客户端（使用 .qa-agent.yml 配置的 MCP 工具前缀列表）
        gitnexus_config = self.config.get('gitnexus', {})
        client = get_gitnexus_client(gitnexus_config)

        if not client.check_availability():
            prefixes_str = ', '.join(client.mcp_tool_prefixes)
            raise RuntimeError(
                f"GitNexus 不可用\n"
                f"配置的 MCP 工具前缀（按优先级）: {prefixes_str}\n"
                f"请检查：\n"
                f"  1. MCP 服务是否启动\n"
                f"  2. .qa-agent.yml 中 gitnexus.mcp_tool_prefixes 是否正确\n"
                f"     默认: ['mcp__gitnexus', 'mcp__gitnexus22']  # 依次尝试\n"
                f"  3. 如本机仅用 gitnexus22，配置：\n"
                f"     gitnexus:\n"
                f"       mcp_tool_prefixes: ['mcp__gitnexus22']"
            )

        # 步骤 2: git diff
        diff_files = self._git_diff_name_only(diff_base)
        diff_content = self._git_diff_full(diff_base)

        # 步骤 3: 检测变更符号
        changed_symbols = client.detect_changes(diff_content)

        # 步骤 4: 影响面分析（upstream）
        depth = self.config.get('gitnexus', {}).get('upstream_depth', {}).get(mode.value, 3)
        affected_symbols = []

        for symbol in changed_symbols:
            try:
                upstream = client.impact_analysis(symbol, direction='upstream', max_depth=depth)
                affected_symbols.extend(upstream)
            except Exception as e:
                print(f"⚠️ GitNexus 分析符号 {symbol} 失败: {e}")

        affected_symbols = list(set(affected_symbols + changed_symbols))

        # 步骤 5: 反查用例库（匹配 targets.symbols）
        hit_cases = []
        for case in all_cases:
            if case.state.value not in ('active', 'review'):
                continue

            targets_symbols = case.targets.get('symbols', [])
            if any(sym in targets_symbols for sym in affected_symbols):
                hit_cases.append(case)

        # 步骤 6: 补集兜底（同 feature_id）
        feature_ids = set(c.feature_id for c in hit_cases)
        priority_filter = self._get_priority_filter(mode)

        补集 = [
            c for c in all_cases
            if c.feature_id in feature_ids
            and c not in hit_cases
            and c.state.value in ('active', 'review')
            and c.priority.value in priority_filter
        ]

        # 步骤 7: 最终选择
        final_selection = [c for c in (hit_cases + 补集) if c.priority.value in priority_filter]

        # 步骤 8: scope 兜底（targets.symbols 全空/无匹配时，按 scope 关联 feature）
        final_selection = self._scope_fallback(
            final_selection, all_cases, scope, priority_filter
        )

        return {
            'mode': 'gitnexus',
            'diff_files': diff_files,
            'affected_symbols': affected_symbols,
            'selected_cases': self._deduplicate(final_selection)
        }

    def _git_diff_name_only(self, base: str) -> List[str]:
        """
        执行 git diff --name-only
        """
        result = subprocess.run(
            ['git', 'diff', '--name-only', base, 'HEAD'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            text=True,
            check=True
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _git_diff_full(self, base: str) -> str:
        """
        执行 git diff（完整内容）
        """
        result = subprocess.run(
            ['git', 'diff', base, 'HEAD'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8',
            text=True,
            check=True
        )
        return result.stdout

    def _get_priority_filter(self, mode: Mode) -> List[str]:
        """
        按模式返回优先级过滤列表
        """
        filters = {
            Mode.L0: ['P0'],
            Mode.L1: ['P0', 'P1'],
            Mode.L2: ['P0', 'P1', 'P2'],
            Mode.L3: ['P0', 'P1', 'P2', 'P3'],
            Mode.L4: ['P0', 'P1']
        }
        return filters.get(mode, ['P0', 'P1', 'P2'])

    def _scope_fallback(
        self,
        current_selection: List[TestCase],
        all_cases: List[TestCase],
        scope: str,
        priority_filter: List[str]
    ) -> List[TestCase]:
        """
        scope 兜底：当 targets 匹配为空导致 selection 为空时，按 scope 关联 feature。

        背景：用例 YAML 缺 targets 字段时（Adapter/Indexer 未回填），
        gitnexus/local 的 targets 匹配会全部落空 → selection=0 → 一条都不跑。
        此时若用户给了明确 scope（feature/module 名），按 feature_id 关联兜底。

        触发条件（两者都满足才兜底，避免误扩范围）：
        1. current_selection 为空（正常 targets 匹配没选出任何用例）
        2. scope 非空

        匹配规则：feature_id == scope 或 scope 是 feature_id 的子串（宽松，
        容忍 "订单" 匹配 "order-management" 之外的命名差异由调用方保证）。
        仍受 priority_filter 和 state 约束，不会越权选 P3 或 retired 用例。
        """
        if current_selection or not scope:
            return current_selection

        scope_lower = scope.lower()
        scope_cases = [
            c for c in all_cases
            if c.state.value in ('active', 'review')
            and c.priority.value in priority_filter
            and (c.feature_id == scope
                 or scope_lower in c.feature_id.lower()
                 or c.feature_id.lower() in scope_lower)
        ]

        if scope_cases:
            print(
                f"⚠️ targets 匹配为空（用例可能缺 targets 字段），"
                f"按 scope '{scope}' 兜底选中 {len(scope_cases)} 条用例"
            )
        return scope_cases

    def _deduplicate(self, cases: List[TestCase]) -> List[TestCase]:
        """
        去重
        """
        seen: Set[str] = set()
        result = []
        for case in cases:
            if case.id not in seen:
                seen.add(case.id)
                result.append(case)
        return result
