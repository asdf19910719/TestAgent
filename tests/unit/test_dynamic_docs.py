"""
测试动态需求文档路径
"""

import pytest
from pathlib import Path

from qa_agent.core.requirement_discovery import (
    discover_from_directory, classify_document, merge_discovery_results
)


class TestClassifyDocument:
    """测试文档分类启发式"""

    def test_classify_by_parent_directory_prd(self, tmp_path):
        """父目录名 prd → requirement"""
        prd_dir = tmp_path / 'prd'
        prd_dir.mkdir()
        doc = prd_dir / 'whatever-name.md'
        doc.write_text('')
        assert classify_document(doc) == 'requirement'

    def test_classify_by_parent_directory_design(self, tmp_path):
        """父目录名 design → design"""
        d = tmp_path / 'architecture'
        d.mkdir()
        doc = d / 'random.md'
        doc.write_text('')
        assert classify_document(doc) == 'design'

    def test_classify_by_parent_chinese(self, tmp_path):
        """中文目录名"""
        d = tmp_path / '需求'
        d.mkdir()
        doc = d / 'a.md'
        doc.write_text('')
        assert classify_document(doc) == 'requirement'

    def test_classify_by_filename_english(self, tmp_path):
        """英文文件名关键词"""
        doc1 = tmp_path / 'requirements.md'
        doc1.write_text('')
        assert classify_document(doc1) == 'requirement'

        doc2 = tmp_path / 'tech-design.md'
        doc2.write_text('')
        assert classify_document(doc2) == 'design'

        doc3 = tmp_path / 'api-spec.md'
        doc3.write_text('')
        # 'spec' 是需求关键词，但 'api' 是 api 关键词，先匹配到的是 requirement
        # 这是预期行为：spec 通常含需求内容
        result = classify_document(doc3)
        assert result in ('requirement', 'api')

    def test_classify_by_filename_chinese(self, tmp_path):
        """中文文件名关键词"""
        doc1 = tmp_path / '产品需求文档.md'
        doc1.write_text('')
        assert classify_document(doc1) == 'requirement'

        doc2 = tmp_path / '技术方案.md'
        doc2.write_text('')
        assert classify_document(doc2) == 'design'

        doc3 = tmp_path / '接口契约.md'
        doc3.write_text('')
        assert classify_document(doc3) == 'api'

    def test_classify_excluded_readme(self, tmp_path):
        """README 不应被分类"""
        doc = tmp_path / 'README.md'
        doc.write_text('')
        assert classify_document(doc) == 'unclassified'

    def test_classify_excluded_changelog(self, tmp_path):
        """CHANGELOG 不应被分类"""
        doc = tmp_path / 'CHANGELOG.md'
        doc.write_text('')
        assert classify_document(doc) == 'unclassified'

    def test_classify_unclassifiable(self, tmp_path):
        """无关键词的文件归 unclassified"""
        doc = tmp_path / 'random-stuff.md'
        doc.write_text('')
        assert classify_document(doc) == 'unclassified'

    def test_classify_spec_kit_filenames(self, tmp_path):
        """spec-kit 标准文件名精确分类"""
        feature_dir = tmp_path / 'specs' / '002-auto-llm'
        feature_dir.mkdir(parents=True)

        cases = {
            'spec.md': 'requirement',
            'plan.md': 'design',
            'data-model.md': 'design',
            'research.md': 'design',
            'quickstart.md': 'acceptance',
            'validation-checklist.md': 'acceptance',
            'tasks.md': 'unclassified',
        }
        for fname, expected in cases.items():
            doc = feature_dir / fname
            doc.write_text('')
            assert classify_document(doc) == expected, f'{fname} 应为 {expected}'

    def test_classify_validation_checklist_by_keyword(self, tmp_path):
        """validation / checklist 关键词 → acceptance（即使不在 feature 目录）"""
        doc = tmp_path / 'my-validation-checklist.md'
        doc.write_text('')
        assert classify_document(doc) == 'acceptance'

    def test_classify_by_parent_checklists_dir(self, tmp_path):
        """父目录 checklists/ → acceptance"""
        d = tmp_path / 'checklists'
        d.mkdir()
        doc = d / 'ux.md'
        doc.write_text('')
        assert classify_document(doc) == 'acceptance'


class TestDiscoverFromDirectory:
    """测试用户动态指定目录"""

    def test_discover_clawbox_style(self, tmp_path):
        """ClawBoxClient 风格：分类子目录 + 汇总文件"""
        version_dir = tmp_path / 'doc' / 'v2026-06-17-当前版本文档'
        version_dir.mkdir(parents=True)

        # 多种类型的文档放在同一目录
        (version_dir / '产品需求-总览.md').write_text('# 需求')
        (version_dir / '需求-短信绑定.md').write_text('# 短信绑定需求')
        (version_dir / '技术方案-架构.md').write_text('# 架构设计')
        (version_dir / '接口契约.md').write_text('# API 契约')
        (version_dir / '验收标准.md').write_text('# 验收')
        (version_dir / 'README.md').write_text('# README')

        result = discover_from_directory(str(version_dir))

        assert result['source'] == 'dynamic'
        # 总览/汇总优先
        assert result['primary'] is not None

        # 设计文档识别（'技术方案' 或 '架构' 关键词）
        assert result['design'] is not None
        assert ('技术方案' in result['design']
                or '架构' in result['design']
                or 'design' in result['design'].lower())

        # API 识别（'接口契约'）
        assert result['api'] is not None
        assert ('接口' in result['api'] or '契约' in result['api']
                or 'api' in result['api'].lower())

        # 验收标准识别
        assert result['acceptance'] is not None

        # README 应在 unclassified
        assert any('README' in d for d in result['unclassified'])

    def test_discover_with_subdirectories(self, tmp_path):
        """目录有子目录分类"""
        target = tmp_path / 'docs'
        (target / 'prd').mkdir(parents=True)
        (target / 'design').mkdir(parents=True)

        (target / 'prd' / 'login.md').write_text('# Login PRD')
        (target / 'design' / 'architecture.md').write_text('# Arch')
        (target / 'index.md').write_text('# Index')

        result = discover_from_directory(str(target))

        assert result['primary'] and 'login' in result['primary'].lower()
        assert result['design'] and 'architecture' in result['design'].lower()
        assert len(result['all_docs']) >= 3

    def test_discover_nonexistent_directory(self, tmp_path):
        """不存在的目录返回 error"""
        result = discover_from_directory(str(tmp_path / 'nope'))
        assert result.get('error')
        assert result['primary'] is None

    def test_discover_windows_path(self, tmp_path):
        """Windows 反斜杠路径"""
        target = tmp_path / 'docs'
        target.mkdir()
        (target / 'requirements.md').write_text('# Req')

        # 模拟 Windows 风格路径
        win_path = str(target).replace('/', '\\')
        result = discover_from_directory(win_path)

        assert result['primary'] is not None

    def test_unclassified_fallback_to_primary(self, tmp_path):
        """如果没有需求关键词的文件，未分类文件作为 primary"""
        target = tmp_path / 'docs'
        target.mkdir()
        (target / 'random-doc.md').write_text('# Random')

        result = discover_from_directory(str(target))

        # 没有任何分类匹配，但有未分类文档 → primary 应该指向它
        assert result['primary'] is not None

    def test_discover_spec_kit_feature_dir(self, tmp_path):
        """复现用户场景：spec-kit feature 目录（无 design.md，含 validation-checklist）"""
        feature_dir = tmp_path / 'specs' / '002-auto-llm-material-analysis'
        feature_dir.mkdir(parents=True)

        (feature_dir / 'spec.md').write_text('# Feature Spec')
        (feature_dir / 'plan.md').write_text('# Plan')
        (feature_dir / 'data-model.md').write_text('# Data Model')
        (feature_dir / 'research.md').write_text('# Research')
        (feature_dir / 'quickstart.md').write_text('# Quickstart')
        (feature_dir / 'validation-checklist.md').write_text('# Validation Checklist')
        (feature_dir / 'tasks.md').write_text('# Tasks')
        # 子目录
        (feature_dir / 'checklists').mkdir()
        (feature_dir / 'checklists' / 'ux.md').write_text('# UX Checklist')
        (feature_dir / 'contracts').mkdir()
        (feature_dir / 'contracts' / 'api.md').write_text('# API contract')

        result = discover_from_directory(str(feature_dir))

        assert result['source'] == 'dynamic'
        # spec.md 作为主需求
        assert result['primary'] and 'spec.md' in result['primary']
        # 设计文档：plan/data-model/research 三个都在 all_designs
        assert len(result['all_designs']) >= 3
        design_names = {Path(p).name for p in result['all_designs']}
        assert {'plan.md', 'data-model.md', 'research.md'} <= design_names
        # validation-checklist + quickstart 归 acceptance（不再被丢进 unclassified）
        all_doc_names = {Path(p).name for p in result['all_docs']}
        assert 'validation-checklist.md' in all_doc_names
        unclassified_names = {Path(p).name for p in result['unclassified']}
        assert 'validation-checklist.md' not in unclassified_names
        assert 'quickstart.md' not in unclassified_names
        # tasks.md 仍是 unclassified（参考材料），但出现在 all_docs
        assert 'tasks.md' in unclassified_names
        assert 'tasks.md' in all_doc_names


class TestMergeDiscoveryResults:
    """测试合并自动 + 动态"""

    def test_merge_dynamic_overrides_auto(self):
        """动态结果覆盖自动结果"""
        auto = {
            'primary': 'docs/auto.md',
            'design': 'docs/auto-design.md',
            'specs': ['docs/spec1.md']
        }
        dynamic = {
            'primary': 'custom/req.md',
            'design': None,
            'all_docs': ['custom/req.md', 'custom/notes.md'],
            'directory': 'custom/'
        }

        merged = merge_discovery_results(auto, dynamic)
        assert merged['primary'] == 'custom/req.md'
        # 动态没指定 design，保留 auto
        assert merged['design'] == 'docs/auto-design.md'
        assert merged['source'] == 'dynamic'
        assert merged['directory'] == 'custom/'

    def test_merge_no_dynamic(self):
        """无动态结果时保持 auto"""
        auto = {'primary': 'docs/req.md'}
        merged = merge_discovery_results(auto, None)
        assert merged == auto
