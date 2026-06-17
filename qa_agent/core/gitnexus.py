"""
GitNexus MCP 工具封装
"""

import json
import subprocess
from typing import List, Dict, Any, Optional


class GitNexusClient:
    """
    GitNexus MCP 工具客户端
    通过 Claude Code 的 MCP 支持调用 GitNexus
    """

    def __init__(self, available: bool = True):
        self.available = available

    def detect_changes(self, diff: str) -> List[str]:
        """
        检测变更涉及的符号列表

        Args:
            diff: git diff 输出

        Returns:
            符号列表 ['LoginPage', 'authenticate', ...]
        """
        if not self.available:
            raise RuntimeError("GitNexus 不可用")

        # Phase 2: 实际调用 MCP
        # 当前为 stub：从 diff 提取文件名作为符号
        symbols = []
        for line in diff.splitlines():
            if line.startswith('+++') or line.startswith('---'):
                # 简化：从文件路径提取符号名
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
        影响面分析：找出受影响的符号

        Args:
            target: 目标符号
            direction: 'upstream'（谁调用了它）或 'downstream'（它调用了谁）
            max_depth: 最大追溯深度（-1 = 不限）

        Returns:
            受影响符号列表
        """
        if not self.available:
            raise RuntimeError("GitNexus 不可用")

        # Phase 2: 实际调用 MCP
        # 当前 stub：返回简单模拟
        if direction == 'upstream':
            # 模拟：假设每个符号有 2-3 个上游调用者
            return [f"{target}Caller1", f"{target}Caller2", f"use{target}"]
        else:
            return [f"{target}Callee1", f"{target}Callee2"]

    def check_availability(self) -> bool:
        """
        检查 GitNexus 是否可用
        """
        # Phase 2: 实际检查 MCP 工具
        # 当前 stub：假设总是可用（除非构造时指定）
        return self.available


def get_gitnexus_client() -> GitNexusClient:
    """
    获取 GitNexus 客户端实例
    """
    # Phase 2: 检查 MCP 是否配置
    try:
        # 简化检查：假设总是可用
        return GitNexusClient(available=True)
    except Exception:
        return GitNexusClient(available=False)
