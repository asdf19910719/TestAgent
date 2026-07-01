"""
测试 Gatekeeper 自检工具
"""

import pytest
from pathlib import Path
import tempfile
import shutil
import yaml


def test_check_yaml_status_consistency_all_valid(tmp_path):
    """测试：所有 YAML 声称 implemented 且脚本真实存在"""
    from qa_agent.core.gatekeeper_selfcheck import check_yaml_status_consistency

    # 创建用例目录
    cases_dir = tmp_path / 'qa' / 'cases' / 'feature1'
    cases_dir.mkdir(parents=True)

    # 创建测试文件
    test_file = tmp_path / 'tests' / 'test_login.py'
    test_file.parent.mkdir(parents=True)
    test_file.write_text('def test_login():\n    pass\n', encoding='utf-8')

    # 创建 YAML（声称 implemented 且脚本存在）
    case_yaml = {
        'id': 'TC-LOGIN-001',
        'title': '用户登录',
        'automation': {
            'status': 'implemented',
            'file': 'tests/test_login.py',
            'test_id': 'test_login'
        }
    }
    yaml_file = cases_dir / 'TC-LOGIN-001.yml'
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(case_yaml, f, allow_unicode=True)

    # 检查
    result = check_yaml_status_consistency(tmp_path)

    assert result['total_cases'] == 1
    assert result['implemented_claimed'] == 1
    assert result['script_found'] == 1
    assert result['inconsistent_count'] == 0
    assert result['consistency_rate'] == 1.0


def test_check_yaml_status_consistency_missing_file(tmp_path):
    """测试：YAML 声称 implemented 但脚本不存在"""
    from qa_agent.core.gatekeeper_selfcheck import check_yaml_status_consistency

    cases_dir = tmp_path / 'qa' / 'cases' / 'feature1'
    cases_dir.mkdir(parents=True)

    # 创建 YAML（声称 implemented 但脚本不存在）
    case_yaml = {
        'id': 'TC-LOGIN-001',
        'title': '用户登录',
        'automation': {
            'status': 'implemented',
            'file': 'tests/test_login.py',  # 文件不存在
            'test_id': 'test_login'
        }
    }
    yaml_file = cases_dir / 'TC-LOGIN-001.yml'
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(case_yaml, f, allow_unicode=True)

    # 检查
    result = check_yaml_status_consistency(tmp_path)

    assert result['total_cases'] == 1
    assert result['implemented_claimed'] == 1
    assert result['script_found'] == 0
    assert result['inconsistent_count'] == 1
    assert result['consistency_rate'] == 0.0
    assert result['inconsistent'][0]['actual'] == 'file_not_found'


def test_check_yaml_status_consistency_test_id_not_found(tmp_path):
    """测试：文件存在但 test_id 找不到"""
    from qa_agent.core.gatekeeper_selfcheck import check_yaml_status_consistency

    cases_dir = tmp_path / 'qa' / 'cases' / 'feature1'
    cases_dir.mkdir(parents=True)

    # 创建测试文件（不含 test_login）
    test_file = tmp_path / 'tests' / 'test_login.py'
    test_file.parent.mkdir(parents=True)
    test_file.write_text('def test_other():\n    pass\n', encoding='utf-8')

    # 创建 YAML
    case_yaml = {
        'id': 'TC-LOGIN-001',
        'title': '用户登录',
        'automation': {
            'status': 'implemented',
            'file': 'tests/test_login.py',
            'test_id': 'test_login'  # 在文件中找不到
        }
    }
    yaml_file = cases_dir / 'TC-LOGIN-001.yml'
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(case_yaml, f, allow_unicode=True)

    # 检查
    result = check_yaml_status_consistency(tmp_path)

    assert result['inconsistent_count'] == 1
    assert result['inconsistent'][0]['actual'] == 'test_id_not_found'


def test_check_l3_main_flows_exists(tmp_path):
    """测试：主流程清单存在且有足够数量"""
    from qa_agent.core.gatekeeper_selfcheck import check_l3_main_flows

    main_flows_file = tmp_path / 'qa' / 'run' / 'main_flows.md'
    main_flows_file.parent.mkdir(parents=True)
    main_flows_file.write_text("""# 主流程清单

1. 用户登录
2. 创建订单
3. 支付订单
4. 查看订单历史
""", encoding='utf-8')

    exists, message = check_l3_main_flows(tmp_path)

    assert exists is True
    assert "4 条" in message


def test_check_l3_main_flows_insufficient(tmp_path):
    """测试：主流程清单数量不足"""
    from qa_agent.core.gatekeeper_selfcheck import check_l3_main_flows

    main_flows_file = tmp_path / 'qa' / 'run' / 'main_flows.md'
    main_flows_file.parent.mkdir(parents=True)
    main_flows_file.write_text("""# 主流程清单

1. 用户登录
2. 查看首页
""", encoding='utf-8')

    exists, message = check_l3_main_flows(tmp_path)

    assert exists is False
    assert "只有 2 条" in message


def test_run_full_selfcheck_pass(tmp_path):
    """测试：完整自检通过"""
    from qa_agent.core.gatekeeper_selfcheck import run_full_selfcheck

    # 创建有效的用例
    cases_dir = tmp_path / 'qa' / 'cases' / 'feature1'
    cases_dir.mkdir(parents=True)

    test_file = tmp_path / 'tests' / 'test_login.py'
    test_file.parent.mkdir(parents=True)
    test_file.write_text('def test_login():\n    pass\n', encoding='utf-8')

    case_yaml = {
        'id': 'TC-LOGIN-001',
        'title': '用户登录',
        'automation': {
            'status': 'implemented',
            'file': 'tests/test_login.py',
            'test_id': 'test_login'
        }
    }
    yaml_file = cases_dir / 'TC-LOGIN-001.yml'
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(case_yaml, f, allow_unicode=True)

    # 创建主流程清单
    main_flows_file = tmp_path / 'qa' / 'run' / 'main_flows.md'
    main_flows_file.parent.mkdir(parents=True)
    main_flows_file.write_text("""1. 登录
2. 创建订单
3. 支付
4. 查看历史""", encoding='utf-8')

    # 执行自检
    result = run_full_selfcheck(tmp_path)

    assert result['status'] in ('PASS', 'WARN')  # WARN 可能因为测试覆盖


def test_run_full_selfcheck_blocked(tmp_path):
    """测试：自检失败（多个问题）"""
    from qa_agent.core.gatekeeper_selfcheck import run_full_selfcheck

    # 创建无效的用例（虚标 implemented）
    cases_dir = tmp_path / 'qa' / 'cases' / 'feature1'
    cases_dir.mkdir(parents=True)

    case_yaml = {
        'id': 'TC-LOGIN-001',
        'title': '用户登录',
        'automation': {
            'status': 'implemented',
            'file': 'tests/test_login.py',  # 文件不存在
            'test_id': 'test_login'
        }
    }
    yaml_file = cases_dir / 'TC-LOGIN-001.yml'
    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(case_yaml, f, allow_unicode=True)

    # 不创建主流程清单

    # 执行自检
    result = run_full_selfcheck(tmp_path)

    assert result['status'] in ('WARN', 'BLOCKED')
    assert len(result['issues']) >= 2  # YAML 一致性 + 主流程缺失
