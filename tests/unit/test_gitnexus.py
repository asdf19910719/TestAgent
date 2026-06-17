"""
测试 GitNexus MCP 工具前缀配置
"""

import os
import pytest
from unittest.mock import patch

from qa_agent.core.gitnexus import GitNexusClient, get_gitnexus_client, DEFAULT_MCP_TOOL_PREFIX


class TestGitNexusClient:
    """测试 GitNexus 工具前缀"""

    def test_default_prefix(self):
        """默认前缀 mcp__gitnexus"""
        client = GitNexusClient()
        assert client.mcp_tool_prefix == 'mcp__gitnexus'
        assert client.detect_changes_tool == 'mcp__gitnexus__detect_changes'
        assert client.impact_tool == 'mcp__gitnexus__impact'

    def test_custom_prefix_gitnexus22(self):
        """支持本机 gitnexus22 前缀"""
        client = GitNexusClient(mcp_tool_prefix='mcp__gitnexus22')
        assert client.detect_changes_tool == 'mcp__gitnexus22__detect_changes'
        assert client.impact_tool == 'mcp__gitnexus22__impact'

    def test_factory_default(self):
        """工厂函数默认值"""
        client = get_gitnexus_client()
        assert client.mcp_tool_prefix == DEFAULT_MCP_TOOL_PREFIX

    def test_factory_with_config(self):
        """工厂函数读取配置"""
        config = {'mcp_tool_prefix': 'mcp__gitnexus22'}
        client = get_gitnexus_client(config)
        assert client.mcp_tool_prefix == 'mcp__gitnexus22'

    def test_factory_env_override(self):
        """环境变量覆盖配置"""
        config = {'mcp_tool_prefix': 'mcp__gitnexus'}
        with patch.dict(os.environ, {'QA_GITNEXUS_TOOL_PREFIX': 'mcp__gitnexus_v3'}):
            client = get_gitnexus_client(config)
            assert client.mcp_tool_prefix == 'mcp__gitnexus_v3'

    def test_subagent_instructions_include_tool_names(self):
        """subagent 指令包含完整工具名"""
        client = GitNexusClient(mcp_tool_prefix='mcp__gitnexus22')
        instructions = client.get_subagent_instructions()
        assert 'mcp__gitnexus22__detect_changes' in instructions
        assert 'mcp__gitnexus22__impact' in instructions
