"""测试覆盖率分析器（第二阶段）"""
import pytest
from pathlib import Path

from qa_agent.core.coverage_analyzer import (
    parse_jacoco_xml, classify_gap, extract_gaps, analyze_coverage,
    GAP_EXCEPTION, GAP_BOUNDARY, GAP_DEFENSIVE, GAP_MAIN_PATH,
)


SAMPLE_JACOCO = """<?xml version="1.0" encoding="UTF-8"?>
<report name="test">
  <package name="com/openclaw/agent">
    <class name="com/openclaw/agent/ContactRepository" sourcefilename="ContactRepository.kt">
      <method name="addContact" line="139"/>
    </class>
    <sourcefile name="ContactRepository.kt">
      <line nr="139" ci="3" mi="0" cb="0" mb="0"/>
      <line nr="140" ci="2" mi="0" cb="2" mb="0"/>
      <line nr="141" ci="0" mi="3" cb="0" mb="2"/>
      <line nr="142" ci="0" mi="2" cb="0" mb="0"/>
    </sourcefile>
  </package>
</report>"""


@pytest.fixture
def jacoco_xml(tmp_path):
    f = tmp_path / 'jacoco.xml'
    f.write_text(SAMPLE_JACOCO, encoding='utf-8')
    return str(f)


def test_parse_jacoco_xml(jacoco_xml):
    """解析 JaCoCo XML 提取行/分支覆盖"""
    report = parse_jacoco_xml(jacoco_xml)

    assert report.line_covered == 2   # nr 139,140
    assert report.line_missed == 2    # nr 141,142
    assert report.line_rate == 50.0
    assert report.branch_covered == 2  # cb on 140
    assert report.branch_missed == 2   # mb on 141

    cls = report.classes['com.openclaw.agent.ContactRepository']
    assert cls.missed_lines == {141, 142}
    assert cls.covered_lines == {139, 140}


def test_parse_nonexistent_xml():
    """文件不存在抛错"""
    with pytest.raises(FileNotFoundError):
        parse_jacoco_xml('/nonexistent.xml')


def test_classify_gap_exception():
    assert classify_gap('throw new IllegalStateException("x")') == GAP_EXCEPTION
    assert classify_gap('raise ValueError("x")') == GAP_EXCEPTION
    assert classify_gap('throw RuntimeException()') == GAP_EXCEPTION


def test_classify_gap_defensive():
    assert classify_gap('} catch (e: Exception) {') == GAP_DEFENSIVE
    assert classify_gap('logger.error("failed", e)') == GAP_DEFENSIVE
    assert classify_gap('except IOError:') == GAP_DEFENSIVE


def test_classify_gap_boundary():
    assert classify_gap('if (list.size() > 0)') == GAP_BOUNDARY
    assert classify_gap('if (name == null)') == GAP_BOUNDARY
    assert classify_gap('require(count >= 0)') == GAP_BOUNDARY
    assert classify_gap('if (text.isEmpty())') == GAP_BOUNDARY


def test_classify_gap_main_path():
    assert classify_gap('val result = repository.save(entity)') == GAP_MAIN_PATH
    assert classify_gap('') == GAP_MAIN_PATH
    assert classify_gap('   ') == GAP_MAIN_PATH


def test_extract_gaps_without_source(jacoco_xml):
    """无源码时提取 gap（kind 默认 main_path）"""
    report = parse_jacoco_xml(jacoco_xml)
    gaps = extract_gaps(report)

    assert len(gaps) == 2  # 141, 142
    assert {g.line_num for g in gaps} == {141, 142}
    # 无源码可读，code 为空 → main_path
    assert all(g.kind == GAP_MAIN_PATH for g in gaps)


def test_extract_gaps_with_source(jacoco_xml, tmp_path):
    """有源码时按行内容分类"""
    # 造一个源码文件，141 行是异常抛出
    src_root = tmp_path / 'src'
    src_dir = src_root / 'com' / 'openclaw' / 'agent'
    src_dir.mkdir(parents=True)
    lines = ['' for _ in range(142)]
    lines[140] = '    throw IllegalStateException("not bound")'  # 141 行(0索引140)
    lines[141] = '    if (count == null) return'                 # 142 行
    (src_dir / 'ContactRepository.kt').write_text('\n'.join(lines), encoding='utf-8')

    report = parse_jacoco_xml(jacoco_xml)
    gaps = extract_gaps(report, source_roots=[str(src_root)])

    by_line = {g.line_num: g for g in gaps}
    assert by_line[141].kind == GAP_EXCEPTION
    assert by_line[142].kind == GAP_BOUNDARY


def test_analyze_coverage_full(jacoco_xml):
    """主入口返回完整结构"""
    result = analyze_coverage(jacoco_xml)

    assert result['line_rate'] == 50.0
    assert result['line_covered'] == 2
    assert result['line_missed'] == 2
    assert result['class_count'] == 1
    assert len(result['gaps']) == 2
    assert 'gap_summary' in result
    assert sum(result['gap_summary'].values()) == 2
