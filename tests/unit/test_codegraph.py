"""
测试 CodeGraph 工具封装（MCP 工具前缀配置 + CLI 客户端）
"""

import os
import pytest
from unittest.mock import patch

from qa_agent.core.codegraph import (
    CodeGraphClient,
    get_codegraph_client,
    DEFAULT_MCP_TOOL_PREFIXES,
)


class TestCodeGraphClient:
    """测试 CodeGraph 工具前缀与可用性"""

    def test_default_prefixes(self):
        """默认前缀列表（codegraph）"""
        client = CodeGraphClient(available=True)
        assert client.mcp_tool_prefixes == ['mcp__codegraph']
        assert client.primary_prefix == 'mcp__codegraph'

        tools = client.get_tool_names('mcp__codegraph')
        assert tools['explore'] == 'mcp__codegraph__codegraph_explore'
        assert tools['node'] == 'mcp__codegraph__codegraph_node'

    def test_custom_single_prefix(self):
        """单个自定义前缀"""
        client = CodeGraphClient(available=True, mcp_tool_prefixes=['mcp__codegraph_v2'])
        assert client.primary_prefix == 'mcp__codegraph_v2'

        tools = client.get_tool_names('mcp__codegraph_v2')
        assert tools['explore'] == 'mcp__codegraph_v2__codegraph_explore'

    def test_reversed_priority(self):
        """多前缀按优先级"""
        client = CodeGraphClient(
            available=True,
            mcp_tool_prefixes=['mcp__codegraph_v2', 'mcp__codegraph'],
        )
        assert client.primary_prefix == 'mcp__codegraph_v2'
        assert client.mcp_tool_prefixes[1] == 'mcp__codegraph'

    def test_availability_autodetect(self):
        """available=None 时按 CLI 是否在 PATH 自动探测"""
        with patch('qa_agent.core.codegraph.shutil.which', return_value='/usr/bin/codegraph'):
            client = CodeGraphClient()
            assert client.check_availability() is True
        with patch('qa_agent.core.codegraph.shutil.which', return_value=None):
            client = CodeGraphClient()
            assert client.check_availability() is False

    def test_factory_default(self):
        """工厂函数默认值"""
        client = get_codegraph_client()
        assert client.mcp_tool_prefixes == DEFAULT_MCP_TOOL_PREFIXES

    def test_factory_with_prefixes_list(self):
        """工厂函数读取 mcp_tool_prefixes 配置"""
        config = {'mcp_tool_prefixes': ['mcp__codegraph_v2', 'mcp__codegraph']}
        client = get_codegraph_client(config)
        assert client.mcp_tool_prefixes == ['mcp__codegraph_v2', 'mcp__codegraph']

    def test_factory_backward_compat_single_prefix(self):
        """兼容旧配置：mcp_tool_prefix（单个）"""
        config = {'mcp_tool_prefix': 'mcp__codegraph_v2'}
        client = get_codegraph_client(config)
        assert client.mcp_tool_prefixes == ['mcp__codegraph_v2']

    def test_factory_env_override(self):
        """环境变量覆盖配置"""
        config = {'mcp_tool_prefixes': ['mcp__codegraph']}
        with patch.dict(os.environ, {'QA_CODEGRAPH_TOOL_PREFIX': 'mcp__codegraph_v3'}):
            client = get_codegraph_client(config)
            assert client.mcp_tool_prefixes == ['mcp__codegraph_v3']

    def test_subagent_instructions_include_all_prefixes(self):
        """subagent 指令包含所有前缀（依次尝试）+ CLI 提示"""
        client = CodeGraphClient(
            available=True,
            mcp_tool_prefixes=['mcp__codegraph', 'mcp__codegraph_v2'],
        )
        instructions = client.get_subagent_instructions()

        assert 'mcp__codegraph__codegraph_explore' in instructions
        assert 'mcp__codegraph_v2__codegraph_explore' in instructions
        assert 'codegraph impact' in instructions

    def test_detect_changes_extracts_symbols(self):
        """detect_changes 从 diff 提取候选符号"""
        client = CodeGraphClient(available=True)
        diff = "+++ b/src/UserService.ts\n--- a/src/UserService.ts\n"
        symbols = client.detect_changes(diff)
        assert 'UserService' in symbols

    def test_impact_analysis_parses_cli_json(self):
        """impact_analysis 解析 CLI JSON 输出为符号列表"""
        client = CodeGraphClient(available=True)
        fake = {'results': [{'name': 'CallerA'}, {'name': 'CallerB'}]}
        with patch.object(client, '_run_cli', return_value=fake):
            result = client.impact_analysis('UserService', direction='upstream')
            assert set(result) == {'CallerA', 'CallerB'}

    def test_impact_analysis_empty_on_cli_failure(self):
        """CLI 失败（返回 None）时影响面为空，由上层降级"""
        client = CodeGraphClient(available=True)
        with patch.object(client, '_run_cli', return_value=None):
            assert client.impact_analysis('X') == []

    def test_affected_tests_parses_output(self):
        """affected_tests 解析受影响测试文件清单"""
        client = CodeGraphClient(available=True)
        with patch.object(client, '_run_cli', return_value={'tests': ['t1.spec.ts', 't2.spec.ts']}):
            tests = client.affected_tests(['src/a.ts'])
            assert tests == ['t1.spec.ts', 't2.spec.ts']
