"""
测试 GitNexus MCP 工具前缀配置（含双前缀 fallback）
"""

import os
import pytest
from unittest.mock import patch

from qa_agent.core.gitnexus import GitNexusClient, get_gitnexus_client, DEFAULT_MCP_TOOL_PREFIXES


class TestGitNexusClient:
    """测试 GitNexus 工具前缀"""

    def test_default_prefixes(self):
        """默认前缀列表（gitnexus + gitnexus22）"""
        client = GitNexusClient()
        assert client.mcp_tool_prefixes == ['mcp__gitnexus', 'mcp__gitnexus22']
        assert client.primary_prefix == 'mcp__gitnexus'

        tools = client.get_tool_names('mcp__gitnexus')
        assert tools['detect_changes'] == 'mcp__gitnexus__detect_changes'
        assert tools['impact'] == 'mcp__gitnexus__impact'

    def test_custom_single_prefix(self):
        """单个前缀（仅 gitnexus22）"""
        client = GitNexusClient(mcp_tool_prefixes=['mcp__gitnexus22'])
        assert client.primary_prefix == 'mcp__gitnexus22'

        tools = client.get_tool_names('mcp__gitnexus22')
        assert tools['detect_changes'] == 'mcp__gitnexus22__detect_changes'

    def test_reversed_priority(self):
        """反转优先级（先 gitnexus22，后 gitnexus）"""
        client = GitNexusClient(mcp_tool_prefixes=['mcp__gitnexus22', 'mcp__gitnexus'])
        assert client.primary_prefix == 'mcp__gitnexus22'
        assert client.mcp_tool_prefixes[1] == 'mcp__gitnexus'

    def test_factory_default(self):
        """工厂函数默认值"""
        client = get_gitnexus_client()
        assert client.mcp_tool_prefixes == DEFAULT_MCP_TOOL_PREFIXES

    def test_factory_with_prefixes_list(self):
        """工厂函数读取 mcp_tool_prefixes 配置"""
        config = {'mcp_tool_prefixes': ['mcp__gitnexus22', 'mcp__gitnexus']}
        client = get_gitnexus_client(config)
        assert client.mcp_tool_prefixes == ['mcp__gitnexus22', 'mcp__gitnexus']

    def test_factory_backward_compat_single_prefix(self):
        """兼容旧配置：mcp_tool_prefix（单个）"""
        config = {'mcp_tool_prefix': 'mcp__gitnexus22'}
        client = get_gitnexus_client(config)
        assert client.mcp_tool_prefixes == ['mcp__gitnexus22']

    def test_factory_env_override(self):
        """环境变量覆盖配置"""
        config = {'mcp_tool_prefixes': ['mcp__gitnexus']}
        with patch.dict(os.environ, {'QA_GITNEXUS_TOOL_PREFIX': 'mcp__gitnexus_v3'}):
            client = get_gitnexus_client(config)
            # 环境变量直接设置单个前缀（临时调试用）
            assert client.mcp_tool_prefixes == ['mcp__gitnexus_v3']

    def test_subagent_instructions_include_all_prefixes(self):
        """subagent 指令包含所有前缀（依次尝试）"""
        client = GitNexusClient(mcp_tool_prefixes=['mcp__gitnexus', 'mcp__gitnexus22'])
        instructions = client.get_subagent_instructions()

        assert 'mcp__gitnexus__detect_changes' in instructions
        assert 'mcp__gitnexus22__detect_changes' in instructions
        assert '依次尝试' in instructions

