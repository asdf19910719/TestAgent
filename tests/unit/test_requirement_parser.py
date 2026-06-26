"""测试需求文档解析器（迁移自 oec-ai-infra）"""
import pytest
from pathlib import Path

from qa_agent.core.requirement_parser import RequirementParser


@pytest.fixture
def parser():
    return RequirementParser()


def test_parse_md_file(parser, tmp_path):
    """解析 Markdown 文件"""
    f = tmp_path / 'PRD.md'
    f.write_text('# 登录需求\n\nFR-001: 用户输入账号密码登录\nFR-002: 密码错误提示',
                 encoding='utf-8')

    result = parser.parse(file_path=str(f))

    assert result['format'] == 'md'
    assert 'FR-001' in result['content']
    assert 'FR-002' in result['content']
    assert result['source_type'] == 'file'
    assert result['metadata']['content_length'] > 0


def test_parse_txt_file(parser, tmp_path):
    """解析纯文本文件"""
    f = tmp_path / 'req.txt'
    f.write_text('需求：用户登录\n约束：3次失败锁定', encoding='utf-8')

    result = parser.parse(file_path=str(f))

    assert result['format'] == 'txt'
    assert '用户登录' in result['content']


def test_parse_text_input(parser):
    """直接文本输入（不经文件）"""
    result = parser.parse(text='FR-001: 直接输入的需求文本')

    assert result['source_type'] == 'text'
    assert 'FR-001' in result['content']


def test_parse_nonexistent_file_raises(parser):
    """文件不存在抛 FileNotFoundError"""
    with pytest.raises(FileNotFoundError):
        parser.parse(file_path='/nonexistent/path/req.pdf')


def test_parse_requires_input(parser):
    """既无 file_path 也无 text 时报错"""
    with pytest.raises(ValueError):
        parser.parse()


def test_result_has_images_field(parser, tmp_path):
    """返回结构含 images 字段（即使无图片也应为空列表）"""
    f = tmp_path / 'PRD.md'
    f.write_text('# 无图需求', encoding='utf-8')

    result = parser.parse(file_path=str(f))

    assert 'images' in result
    assert isinstance(result['images'], list)
    assert len(result['images']) == 0  # 纯文本无图片
