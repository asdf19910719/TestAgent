"""
GitNexus MCP 工具封装

架构说明（v3.0-rev2）：
本类不直接调用 MCP——Python 代码无法访问 Claude Code 的 MCP 工具。
真正的 MCP 调用由 subagent（.claude/agents/qa-test-engineer.md）完成。

本类提供：
1. 配置 MCP 工具前缀（适配不同 MCP 服务名，如 gitnexus / gitnexus22）
2. 可用性检测（基于本地标志，避免不必要尝试）
3. 简单的 stub 用于单元测试

MCP 工具实际名称由 .qa-agent.yml 中的 gitnexus.mcp_tool_prefix 决定：
- 默认: mcp__gitnexus__detect_changes / mcp__gitnexus__impact
- 配置 gitnexus22: mcp__gitnexus22__detect_changes / mcp__gitnexus22__impact
"""

import json
import os
import subprocess
from typing import List, Dict, Any, Optional


# MCP 工具前缀默认值（可在 .qa-agent.yml 中覆盖）
DEFAULT_MCP_TOOL_PREFIX = 'mcp__gitnexus'


class GitNexusClient:
    """
    GitNexus MCP 工具客户端封装
    Python 层仅提供配置和元数据，实际调用由 subagent 在 Claude Code 中完成
    """

    def __init__(self, available: bool = True, mcp_tool_prefix: str = DEFAULT_MCP_TOOL_PREFIX):
        """
        Args:
            available: 是否可用（默认 True，subagent 调用前不强制检测）
            mcp_tool_prefix: MCP 工具前缀，如 'mcp__gitnexus' 或 'mcp__gitnexus22'
        """
        self.available = available
        self.mcp_tool_prefix = mcp_tool_prefix

    @property
    def detect_changes_tool(self) -> str:
        """完整的 detect_changes 工具名"""
        return f"{self.mcp_tool_prefix}__detect_changes"

    @property
    def impact_tool(self) -> str:
        """完整的 impact 工具名"""
        return f"{self.mcp_tool_prefix}__impact"

    def get_subagent_instructions(self) -> str:
        """
        返回 subagent 应该使用的 MCP 工具调用说明
        Subagent 通过此方法获知本项目应该用哪个 MCP 服务
        """
        return (
            f"本项目使用 GitNexus MCP 工具调用：\n"
            f"  - 检测变更: {self.detect_changes_tool}\n"
            f"  - 影响面分析: {self.impact_tool}\n"
            f"如果上述工具不存在，请尝试其他后缀（如 gitnexus22 / gitnexus_v2）\n"
            f"并提示用户在 .qa-agent.yml 配置 gitnexus.mcp_tool_prefix"
        )

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
    prefix = config.get('mcp_tool_prefix', DEFAULT_MCP_TOOL_PREFIX)

    # 从环境变量覆盖（便于临时切换）
    prefix = os.environ.get('QA_GITNEXUS_TOOL_PREFIX', prefix)

    return GitNexusClient(available=True, mcp_tool_prefix=prefix)

