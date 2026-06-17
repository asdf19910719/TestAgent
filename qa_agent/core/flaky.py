"""
Flaky 检测算法（规范 §4）
"""

from typing import List, Dict, Any


def detect_flaky(
    case_id: str,
    last_run_result: str,
    history: Dict[str, Any],
    retry_runs: int = 5
) -> Dict[str, Any]:
    """
    Flaky 检测：失败用例隔离重跑

    Args:
        case_id: 用例 ID
        last_run_result: 本次结果 (pass/fail)
        history: qa/run/history.json 内容
        retry_runs: 重跑次数（默认 5）

    Returns:
        {
            'is_flaky': bool,
            'pass_count': int,
            'fail_count': int,
            'flaky_score': float
        }
    """
    # 仅失败用例触发检测
    if last_run_result != 'fail':
        return {'is_flaky': False, 'pass_count': 0, 'fail_count': 0, 'flaky_score': 0.0}

    # 隔离重跑 5 次
    results = []
    for i in range(retry_runs):
        # Phase 3 简化：模拟重跑（Phase 4 调用真实 Adapter）
        result = 'pass' if i % 2 == 0 else 'fail'  # 模拟 50% 通过率
        results.append(result)

    pass_count = results.count('pass')
    fail_count = results.count('fail')

    # 全 PASS → flaky
    is_flaky = pass_count == retry_runs

    # Flaky 分数
    flaky_score = pass_count / retry_runs if retry_runs > 0 else 0.0

    return {
        'is_flaky': is_flaky,
        'pass_count': pass_count,
        'fail_count': fail_count,
        'flaky_score': flaky_score
    }


def update_flaky_statistics(
    case_id: str,
    is_flaky: bool,
    history_path: str = 'qa/run/history.json'
) -> None:
    """
    更新滚动窗口统计
    Phase 4 实现
    """
    print(f"[Flaky] 更新统计（Phase 4 实现）：{case_id} flaky={is_flaky}")
