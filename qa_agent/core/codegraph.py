"""
CodeGraph 代码图工具封装

架构说明（v3.1 - CodeGraph 迁移）：
与旧 GitNexus 不同，CodeGraph 提供真实 CLI（`codegraph impact/affected/callers/query`），
Python 层可以**直接调用**，不再强依赖 subagent 转发 MCP。

本类提供两条路径：
1. CLI 直调（首选）：Python 直接 shell 出 `codegraph` 命令做影响面分析
2. MCP 工具前缀（subagent 路径）：subagent 在 Claude Code 内调用 codegraph MCP 工具

MCP 工具（Claude Code 内）：
- mcp__codegraph__codegraph_explore — 区域探索：相关符号源码 + 调用路径
- mcp__codegraph__codegraph_node    — 单符号视图：源码 + 调用链 + 依赖者

CLI 命令（Python 可直调）：
- codegraph impact <symbol>     — 改动某符号的影响面（爆炸半径）
- codegraph affected [files...] — 改动文件 → 受影响的测试文件
- codegraph callers <symbol>    — 谁调用了该符号（upstream）
- codegraph callees <symbol>    — 该符号调用了谁（downstream）
- codegraph query <search>      — 按概念搜索符号

工具前缀由 .qa-agent.yml 的 codegraph.mcp_tool_prefixes 决定（列表，按优先级）：
- 默认: ['mcp__codegraph']
- 用户可自定义/追加备用前缀
"""

import json
import os
import shutil
import subprocess
from typing import List, Dict, Any, Optional


# MCP 工具前缀默认值（可在 .qa-agent.yml 中覆盖）
DEFAULT_MCP_TOOL_PREFIXES = ['mcp__codegraph']

# CodeGraph CLI 可执行名
CODEGRAPH_CLI = 'codegraph'


class CodeGraphClient:
    """
    CodeGraph 工具客户端封装

    既支持 Python 直接调用 CLI（首选），也提供 MCP 工具前缀给 subagent 使用。
    """

    def __init__(
        self,
        available: Optional[bool] = None,
        mcp_tool_prefixes: Optional[List[str]] = None,
        project_path: Optional[str] = None,
    ):
        """
        Args:
            available: 是否可用。None 时按 CLI 是否在 PATH 自动探测；显式传值则覆盖（便于测试）。
            mcp_tool_prefixes: MCP 工具前缀列表（subagent 路径，按优先级尝试）
            project_path: CodeGraph 项目路径（默认当前目录）
        """
        self.mcp_tool_prefixes = mcp_tool_prefixes or DEFAULT_MCP_TOOL_PREFIXES
        self.project_path = project_path
        if available is None:
            self.available = shutil.which(CODEGRAPH_CLI) is not None
        else:
            self.available = available

    @property
    def primary_prefix(self) -> str:
        """首选前缀（subagent 优先尝试）"""
        return self.mcp_tool_prefixes[0] if self.mcp_tool_prefixes else 'mcp__codegraph'

    def get_tool_names(self, prefix: str) -> Dict[str, str]:
        """获取完整 MCP 工具名（给定前缀）"""
        return {
            'explore': f"{prefix}__codegraph_explore",
            'node': f"{prefix}__codegraph_node",
        }

    def get_subagent_instructions(self) -> str:
        """
        返回 subagent 应该使用的 MCP 工具调用说明。
        Subagent 通过此方法获知本项目应该用哪个 MCP 服务。
        """
        instructions = [
            "本项目的 CodeGraph MCP 工具配置（按优先级依次尝试）：\n"
        ]

        for i, prefix in enumerate(self.mcp_tool_prefixes, 1):
            tools = self.get_tool_names(prefix)
            instructions.append(
                f"{i}. 优先级 {i}:\n"
                f"   - 区域探索: {tools['explore']}\n"
                f"   - 单符号视图: {tools['node']}\n"
            )

        instructions.append(
            "\n影响面/调用链亦可直接用 CLI（Python 或 Bash）：\n"
            "  codegraph impact <symbol>     # 爆炸半径\n"
            "  codegraph affected <files...> # 改动文件 → 受影响测试\n"
            "  codegraph callers <symbol>    # upstream 调用者\n"
            "\n调用策略：CLI 直调优先；MCP 工具依次尝试，第一个成功的就用。\n"
            "如全部失败，提示用户在 .qa-agent.yml 配置正确的前缀：\n"
            "  codegraph:\n"
            "    mcp_tool_prefixes: ['mcp__codegraph']  # 改为实际服务名"
        )

        return ''.join(instructions)

    def _run_cli(self, args: List[str]) -> Optional[Any]:
        """
        调用 codegraph CLI 并解析 JSON 输出。失败返回 None（由调用方决定降级）。
        """
        cmd = [CODEGRAPH_CLI] + args + ['--json']
        if self.project_path:
            cmd += ['--path', self.project_path]
        try:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding='utf-8',
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return None
            return json.loads(result.stdout)
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
            return None

    def detect_changes(self, diff: str) -> List[str]:
        """
        从 diff 提取变更涉及的候选符号列表。

        CodeGraph 没有 detect_changes 端点，改用文件名启发式提取符号，
        真正的精确影响面由 impact_analysis() 通过 CLI 计算。
        """
        if not self.available:
            raise RuntimeError("CodeGraph 不可用")

        symbols = []
        for line in diff.splitlines():
            if line.startswith('+++') or line.startswith('---'):
                parts = line.split('/')
                if parts:
                    filename = parts[-1].replace('.tsx', '').replace('.ts', '').replace('.py', '')
                    if filename not in ('a', 'b', 'dev', 'null'):
                        symbols.append(filename)

        return list(set(symbols))

    def affected_tests(self, changed_files: List[str], depth: int = 5) -> List[str]:
        """
        改动文件 → 受影响的测试文件（CodeGraph 原生 `affected` 命令）。

        Returns:
            受影响的测试文件路径列表（CLI 不可用时返回空列表，由上层降级）
        """
        if not self.available or not changed_files:
            return []

        data = self._run_cli(['affected'] + changed_files + ['-d', str(depth)])
        if not data:
            return []
        # affected --json 返回受影响测试文件清单
        if isinstance(data, dict):
            return data.get('tests', data.get('affected', []))
        if isinstance(data, list):
            return data
        return []

    def impact_analysis(
        self,
        target: str,
        direction: str = 'upstream',
        max_depth: int = 3
    ) -> List[str]:
        """
        影响面分析：改动某符号会波及哪些符号。

        - upstream（默认）：谁依赖/调用该符号（爆炸半径）→ codegraph callers
        - downstream：该符号调用了谁 → codegraph callees

        CLI 不可用或无结果时返回空列表（由上层决定是否降级到 local）。
        """
        if not self.available:
            raise RuntimeError("CodeGraph 不可用")

        depth = max_depth if max_depth and max_depth > 0 else 3
        cmd = 'callers' if direction == 'upstream' else 'callees'
        data = self._run_cli([cmd, target, '-d', str(depth)])
        if not data:
            return []

        # 解析 CLI JSON 输出，提取符号名
        symbols: List[str] = []
        items = data.get('results', data) if isinstance(data, dict) else data
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    name = it.get('name') or it.get('symbol')
                    if name:
                        symbols.append(name)
                elif isinstance(it, str):
                    symbols.append(it)
        return list(set(symbols))

    def check_availability(self) -> bool:
        """
        检查 CodeGraph 是否可用（CLI 是否在 PATH）。
        """
        return self.available


def get_codegraph_client(config: Optional[Dict[str, Any]] = None) -> CodeGraphClient:
    """
    工厂函数：根据 config 创建 CodeGraph 客户端

    config: .qa-agent.yml 的 codegraph 节点
    """
    config = config or {}

    # 兼容旧配置：mcp_tool_prefix（单个）→ mcp_tool_prefixes（列表）
    if 'mcp_tool_prefix' in config:
        prefixes = [config['mcp_tool_prefix']]
    elif 'mcp_tool_prefixes' in config:
        prefixes = config['mcp_tool_prefixes']
    else:
        prefixes = DEFAULT_MCP_TOOL_PREFIXES

    # 从环境变量覆盖（便于临时切换）
    env_prefix = os.environ.get('QA_CODEGRAPH_TOOL_PREFIX')
    if env_prefix:
        prefixes = [env_prefix]

    project_path = config.get('project_path')

    return CodeGraphClient(mcp_tool_prefixes=prefixes, project_path=project_path)
