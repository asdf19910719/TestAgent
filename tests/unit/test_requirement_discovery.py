"""
测试需求文档自动发现（含 ai-docs/ 等约定）
"""

import pytest
from pathlib import Path

from qa_agent.core.requirement_discovery import (
    discover_requirements, scan_convention_paths, validate_explicit_paths
)


class TestRequirementDiscovery:
    """需求文档自动发现"""

    def test_finds_docs_requirements(self, tmp_path):
        """优先发现 docs/requirements.md"""
        docs = tmp_path / 'docs'
        docs.mkdir()
        (docs / 'requirements.md').write_text('# Requirements')

        result = discover_requirements({}, cwd=tmp_path)
        assert result['source'] == 'convention'
        assert 'requirements.md' in result['primary']

    def test_finds_ai_docs_directory(self, tmp_path):
        """发现 ai-docs/ 目录（其他 AI 工作流）"""
        ai_docs = tmp_path / 'ai-docs'
        ai_docs.mkdir()
        (ai_docs / 'requirements.md').write_text('# AI Docs Requirements')
        (ai_docs / 'design.md').write_text('# Design')

        result = discover_requirements({}, cwd=tmp_path)
        assert result['source'] == 'convention'
        assert 'requirements.md' in result['primary']
        assert len(result['all_docs']) >= 2

    def test_finds_ai_docs_design(self, tmp_path):
        """ai-docs/design.md 作为设计文档"""
        ai_docs = tmp_path / 'ai-docs'
        ai_docs.mkdir()
        (ai_docs / 'requirements.md').write_text('# Req')
        (ai_docs / 'design.md').write_text('# Design')

        result = discover_requirements({}, cwd=tmp_path)
        assert result['design'] is not None
        assert 'design.md' in result['design']

    def test_finds_bmad_output(self, tmp_path):
        """支持 BMAD 框架"""
        bmad = tmp_path / '.bmad' / 'output'
        bmad.mkdir(parents=True)
        (bmad / 'prd.md').write_text('# PRD')

        result = discover_requirements({}, cwd=tmp_path)
        assert result['source'] == 'convention'
        # all_docs 包含 .bmad/output 下的文档
        assert any('.bmad' in p or 'bmad' in p for p in result['all_docs'])

    def test_finds_specs_kit(self, tmp_path):
        """支持 spec-kit"""
        spec_dir = tmp_path / 'specs' / 'login'
        spec_dir.mkdir(parents=True)
        (spec_dir / 'spec.md').write_text('# Login Spec')

        result = discover_requirements({}, cwd=tmp_path)
        assert result['source'] == 'convention'
        assert len(result['specs']) >= 1

    def test_explicit_config_overrides(self, tmp_path):
        """显式配置优先级最高"""
        # 同时存在 docs/ 和自定义路径
        docs = tmp_path / 'docs'
        docs.mkdir()
        (docs / 'requirements.md').write_text('# Auto')

        custom = tmp_path / 'custom'
        custom.mkdir()
        (custom / 'spec.md').write_text('# Custom')

        config = {'requirements': {'primary': 'custom/spec.md'}}
        result = discover_requirements(config, cwd=tmp_path)
        assert result['source'] == 'explicit'
        assert 'custom' in result['primary']

    def test_no_docs_fallback_to_reverse(self, tmp_path):
        """无文档时返回反向梳理标记"""
        result = discover_requirements({}, cwd=tmp_path)
        assert result['source'] == 'reverse_engineered'
        assert result['primary'] is None

    def test_explicit_ai_docs_dir(self, tmp_path):
        """显式配置 ai_docs_dir"""
        ai_dir = tmp_path / 'my-ai-docs'
        ai_dir.mkdir()
        (ai_dir / 'doc1.md').write_text('# Doc 1')
        (ai_dir / 'doc2.md').write_text('# Doc 2')

        config = {
            'requirements': {
                'primary': 'my-ai-docs/doc1.md',
                'ai_docs_dir': 'my-ai-docs'
            }
        }
        result = discover_requirements(config, cwd=tmp_path)
        assert result['source'] == 'explicit'
        assert len(result['all_docs']) == 2

    def test_clawbox_style_project(self, tmp_path):
        """模拟 ClawBoxClient 项目结构"""
        # 模拟 D:\AndroidProject\ClawBoxClient 的目录结构
        (tmp_path / 'app').mkdir()
        (tmp_path / 'app' / 'build.gradle').write_text('android { }')

        ai_docs = tmp_path / 'ai-docs'
        ai_docs.mkdir()
        (ai_docs / '需求文档.md').write_text('# 项目需求')
        (ai_docs / '技术方案.md').write_text('# 技术设计')
        (ai_docs / 'API设计.md').write_text('# API')

        result = discover_requirements({}, cwd=tmp_path)
        assert result['source'] == 'convention'
        # 应该找到至少一个文档
        assert result['primary'] or len(result['all_docs']) >= 3
        assert len(result['all_docs']) >= 3
