"""
GitNexus MCP 工具封装

架构说明（v3.0-rev2）：
本类不直接调用 MCP——Python 代码无法访问 Claude Code 的 MCP 工具。
真正的 MCP 调用由 subagent（.claude/agents/qa-test-engineer.md）完成。

本类提供：
1. 配置 MCP 工具前缀列表（支持 fallback：gitnexus → gitnexus22 依次尝试）
2. 可用性检测（基于本地标志，避免不必要尝试）
3. 简单的 stub 用于单元测试

MCP 工具实际名称由 .qa-agent.yml 中的 gitnexus.mcp_tool_prefixes 决定（列表，按优先级）：
- 默认: ['mcp__gitnexus', 'mcp__gitnexus22'] — 先尝试 gitnexus，不可用则降级到 gitnexus22
- 用户可反转优先级: ['mcp__gitnexus22', 'mcp__gitnexus']
- 或仅用单个前缀: ['mcp__gitnexus22']
"""

import json
import os
import subprocess
from typing import List, Dict, Any, Optional


# MCP 工具前缀默认值（可在 .qa-agent.yml 中覆盖）
DEFAULT_MCP_TOOL_PREFIXES = ['mcp__gitnexus', 'mcp__gitnexus22']


class GitNexusClient:
    """
    GitNexus MCP 工具客户端封装
    Python 层仅提供配置和元数据，实际调用由 subagent 在 Claude Code 中完成
    """

    def __init__(self, available: bool = True, mcp_tool_prefixes: Optional[List[str]] = None):
        """
        Args:
            available: 是否可用（默认 True，subagent 调用前不强制检测）
            mcp_tool_prefixes: MCP 工具前缀列表（按优先级尝试）
        """
        self.available = available
        self.mcp_tool_prefixes = mcp_tool_prefixes or DEFAULT_MCP_TOOL_PREFIXES

    @property
    def primary_prefix(self) -> str:
        """首选前缀（subagent 优先尝试）"""
        return self.mcp_tool_prefixes[0] if self.mcp_tool_prefixes else 'mcp__gitnexus'

    def get_tool_names(self, prefix: str) -> Dict[str, str]:
        """获取完整工具名（给定前缀）"""
        return {
            'detect_changes': f"{prefix}__detect_changes",
            'impact': f"{prefix}__impact",
            'query': f"{prefix}__query",
            'context': f"{prefix}__context"
        }

    def get_subagent_instructions(self) -> str:
        """
        返回 subagent 应该使用的 MCP 工具调用说明
        Subagent 通过此方法获知本项目应该用哪个 MCP 服务
        """
        instructions = [
            "本项目的 GitNexus MCP 工具配置（按优先级依次尝试）：\n"
        ]

        for i, prefix in enumerate(self.mcp_tool_prefixes, 1):
            tools = self.get_tool_names(prefix)
            instructions.append(
                f"{i}. 优先级 {i}:\n"
                f"   - 检测变更: {tools['detect_changes']}\n"
                f"   - 影响面分析: {tools['impact']}\n"
            )

        instructions.append(
            "\n调用策略：依次尝试，第一个成功的就用。\n"
            "如全部失败，提示用户在 .qa-agent.yml 配置正确的前缀：\n"
            "  gitnexus:\n"
            "    mcp_tool_prefixes: ['mcp__gitnexus_v3']  # 改为实际服务名"
        )

        return ''.join(instructions)

    def detect_changes(self, diff: str) -> List[str]:
        """
        检测变更涉及的符号列表（stub，实际由 subagent 调用 MCP）

        Returns:
            符号列表
        """
        if not self.available:
            raise RuntimeError("GitNexus 不可用")

        # 从 diff 提取候选符号（备用算法，仅在 subagent 不可用时降级）
        symbols = []
        for line in diff.splitlines():
            if line.startswith('+++') or line.startswith('---'):
                parts = line.split('/')
                if parts:
                    filename = parts[-1].replace('.tsx', '').replace('.ts', '').replace('.py', '')
                    if filename not in ('a', 'b', 'dev', 'null'):
                        symbols.append(filename)

        return list(set(symbols))

    def impact_analysis(
        self,
        target: str,
        direction: str = 'upstream',
        max_depth: int = 3
    ) -> List[str]:
        """
        影响面分析（stub）
        """
        if not self.available:
            raise RuntimeError("GitNexus 不可用")

        # 备用：返回简单模拟（仅用于本地降级路径）
        if direction == 'upstream':
            return [f"{target}Caller1", f"{target}Caller2"]
        else:
            return [f"{target}Callee1"]

    def check_availability(self) -> bool:
        """
        检查 GitNexus 是否可用
        Python 层不能真正检测 MCP，返回构造时的标志
        """
        return self.available


def get_gitnexus_client(config: Optional[Dict[str, Any]] = None) -> GitNexusClient:
    """
    工厂函数：根据 config 创建 GitNexus 客户端

    config: .qa-agent.yml 的 gitnexus 节点
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
    env_prefix = os.environ.get('QA_GITNEXUS_TOOL_PREFIX')
    if env_prefix:
        prefixes = [env_prefix]

    return GitNexusClient(available=True, mcp_tool_prefixes=prefixes)


