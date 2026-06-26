"""测试产物路径约束机制"""
import pytest
from pathlib import Path

from qa_agent.core import paths


def test_case_file_path():
    """用例文件路径拼接"""
    assert paths.case_file('F-CONTACT-SYNC', 'TC-CONTACT-001') == \
        'qa/cases/F-CONTACT-SYNC/TC-CONTACT-001.yml'


def test_bug_file_path():
    """缺陷文件路径拼接"""
    assert paths.bug_file('BUG-001') == 'qa/bugs/BUG-001.yml'


def test_report_file_path():
    """报告文件路径(多格式)"""
    assert paths.report_file('run_123', 'html') == 'qa/reports/run_123.html'
    assert paths.report_file('run_123', 'json') == 'qa/reports/run_123.json'
    assert paths.report_file('run_123', 'markdown') == 'qa/reports/run_123.md'


def test_validate_allowed_qa_path():
    """qa/ 下路径应通过校验"""
    r = paths.validate_output_path('qa/cases/F-X/TC-001.yml')
    assert r['ok']
    assert r['matched_prefix'] == 'qa'


def test_validate_allowed_android_path():
    """Android 测试源集路径应通过"""
    r = paths.validate_output_path('app/src/androidTest/kotlin/com/x/T.kt')
    assert r['ok']
    assert r['matched_prefix'] == 'app/src/androidTest'

    r2 = paths.validate_output_path('app/src/test/kotlin/com/x/T.kt')
    assert r2['ok']


def test_validate_rejects_outside_path():
    """约定结构外的路径应被拒绝"""
    r = paths.validate_output_path('src/main/random/leak.kt')
    assert not r['ok']
    assert 'random' in r['reason'] or '未落在' in r['reason']


def test_validate_rejects_workspace_root_pollution():
    """工作区根直接落文件应被拒绝"""
    r = paths.validate_output_path('node_modules/junk.js')
    assert not r['ok']

    r2 = paths.validate_output_path('testcases.md')  # 散落根目录
    assert not r2['ok']


def test_validate_windows_backslash_normalized():
    """Windows 反斜杠路径应被规范化后校验"""
    r = paths.validate_output_path('qa\\cases\\F-X\\TC-001.yml')
    assert r['ok']
    assert '/' in r['normalized']
    assert '\\' not in r['normalized']


def test_ensure_qa_dirs(tmp_path):
    """创建所有规范 QA 目录"""
    created = paths.ensure_qa_dirs(cwd=tmp_path)

    assert (tmp_path / 'qa' / 'cases').is_dir()
    assert (tmp_path / 'qa' / 'run').is_dir()
    assert (tmp_path / 'qa' / 'bugs').is_dir()
    assert (tmp_path / 'qa' / 'reports').is_dir()
    assert 'qa/cases' in created


def test_run_files_constants():
    """执行记录文件常量正确"""
    assert paths.RUN_FILES['last'] == 'qa/run/last.json'
    assert paths.RUN_FILES['baseline'] == 'qa/run/baseline.json'
    assert paths.RUN_FILES['history'] == 'qa/run/history.jsonl'
