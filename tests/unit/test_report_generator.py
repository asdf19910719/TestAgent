"""测试报告生成器（第一阶段任务3）"""
import json
import pytest

from qa_agent.core.report_generator import ReportGenerator, generate_report


@pytest.fixture
def sample_last_run():
    """模拟一次执行的 last.json"""
    return {
        'run_id': 'run_20260626_001',
        'mode': 'L2',
        'scope': '联系人通讯录',
        'gatekeeper_verdict': {'verdict': 'CONDITIONAL PASS'},
        'selection': {'total': 17},
        'execution': {
            'totals': {'total': 17, 'passed': 14, 'failed': 2, 'blocked': 1, 'skipped': 0},
            'failures': [
                {'case_id': 'TC-CONTACT-003', 'message': '断言失败: 期望 3 实际 2'},
                {'case_id': 'TC-CONTACT-009', 'message': 'LLM 超时'},
            ],
        },
    }


@pytest.fixture
def sample_history():
    """模拟历史记录（上次 + 本次）"""
    return [
        {'run_id': 'run_old', 'verdict': 'FAIL', 'pass_rate': '10/17 (58.8%)'},
        {'run_id': 'run_20260626_001', 'verdict': 'CONDITIONAL PASS', 'pass_rate': '14/16 (87.5%)'},
    ]


def test_compute_stats(sample_last_run):
    """确定性统计计算"""
    gen = ReportGenerator(sample_last_run)
    s = gen.compute_stats()

    assert s['total'] == 17
    assert s['passed'] == 14
    assert s['failed'] == 2
    assert s['blocked'] == 1
    assert s['executed'] == 16
    assert s['pass_rate'] == 87.5  # 14/16
    assert s['exec_rate'] == round(16/17*100, 1)


def test_compute_stats_fallback(sample_last_run):
    """totals 缺失时从 selection + failures 回退"""
    sample_last_run['execution']['totals'] = {}
    gen = ReportGenerator(sample_last_run)
    s = gen.compute_stats()

    assert s['total'] == 17  # 从 selection
    assert s['failed'] == 2  # 从 failures 长度


def test_compute_trend(sample_last_run, sample_history):
    """历史趋势计算"""
    gen = ReportGenerator(sample_last_run, sample_history)
    t = gen.compute_trend()

    assert t['available']
    assert t['prev_verdict'] == 'FAIL'
    assert t['cur_verdict'] == 'CONDITIONAL PASS'
    assert t['prev_pass_rate'] == 58.8
    assert t['cur_pass_rate'] == 87.5
    assert t['pass_rate_delta'] == round(87.5 - 58.8, 1)


def test_trend_unavailable_with_short_history(sample_last_run):
    """历史不足 2 条时趋势不可用"""
    gen = ReportGenerator(sample_last_run, history=[])
    assert not gen.compute_trend()['available']


def test_to_markdown(sample_last_run, sample_history):
    """markdown 报告含关键信息"""
    gen = ReportGenerator(sample_last_run, sample_history)
    md = gen.to_markdown()

    assert '联系人通讯录' in md
    assert 'CONDITIONAL PASS' in md
    assert '87.5' in md
    assert 'TC-CONTACT-003' in md  # 失败用例
    assert '历史趋势' in md


def test_to_json(sample_last_run, sample_history):
    """JSON 元数据结构正确"""
    gen = ReportGenerator(sample_last_run, sample_history)
    data = gen.to_json()

    assert data['run_id'] == 'run_20260626_001'
    assert data['verdict'] == 'CONDITIONAL PASS'
    assert data['stats']['pass_rate'] == 87.5
    assert data['trend']['available']
    assert len(data['failures']) == 2


def test_to_html(sample_last_run, sample_history):
    """HTML 报告含卡片和转义"""
    gen = ReportGenerator(sample_last_run, sample_history)
    h = gen.to_html()

    assert '<!DOCTYPE html>' in h
    assert '联系人通讯录' in h
    assert '87.5%' in h
    assert 'TC-CONTACT-003' in h


def test_html_escapes_malicious_content(sample_last_run):
    """HTML 转义防注入"""
    sample_last_run['scope'] = '<script>alert(1)</script>'
    gen = ReportGenerator(sample_last_run)
    h = gen.to_html()

    assert '<script>alert(1)</script>' not in h
    assert '&lt;script&gt;' in h


def test_generate_report_dispatch(sample_last_run):
    """便捷入口分发三种格式"""
    md = generate_report(sample_last_run, fmt='markdown')
    assert '# 测试报告' in md

    js = generate_report(sample_last_run, fmt='json')
    assert json.loads(js)['run_id'] == 'run_20260626_001'

    h = generate_report(sample_last_run, fmt='html')
    assert '<!DOCTYPE html>' in h
