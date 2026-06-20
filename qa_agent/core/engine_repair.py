# engine_repair.py — CONDITIONAL PASS 修复循环

from typing import Dict, List, Any
from .models import TestCase


def repair_loop_l3(
    engine,
    run_id: str,
    designed_cases: List[TestCase],
    all_failures: List[Dict],
    requirements_content: str,
    last_run: Dict,
    max_iterations: int = 3
) -> tuple[Dict, List[Dict]]:
    """
    CONDITIONAL PASS 后的自动修复循环

    遵守 CLAUDE.md 持久性规则：
    - 禁止过早声明"不可修复"
    - 每次修复后报告进度
    - 遇到障碍时先读源码再精确修复
    - 3 次尝试后换策略（不是停止）

    Args:
        engine: Engine 实例
        run_id: 运行 ID
        designed_cases: 所有用例
        all_failures: 失败的用例列表
        requirements_content: 需求文档内容
        last_run: 最近一次运行状态
        max_iterations: 最大修复轮次

    Returns:
        (最终 verdict, 剩余失败列表)
    """
    from .designer_runner import DesignerRunner
    from .gatekeeper import Gatekeeper

    designer = DesignerRunner(engine.config)
    gatekeeper = Gatekeeper(engine.config)

    iteration = 0
    remaining_failures = all_failures.copy()

    while remaining_failures and iteration < max_iterations:
        iteration += 1
        print(f"\n[修复循环] 第 {iteration}/{max_iterations} 轮")
        print(f"[修复循环] 待修复: {len(remaining_failures)} 个失败用例")

        # 打印失败用例清单
        for i, failure in enumerate(remaining_failures[:5], 1):
            case_id = failure.get('case_id', 'unknown')
            message = failure.get('message', '')[:80]
            print(f"  {i}. {case_id}: {message}")
        if len(remaining_failures) > 5:
            print(f"  ... 还有 {len(remaining_failures) - 5} 个")

        # 逐个修复失败用例
        fixed_count = 0
        still_failing = []

        for failure in remaining_failures:
            case_id = failure.get('case_id')
            if not case_id:
                continue

            # 找到对应的用例
            target_case = next((c for c in designed_cases if c.id == case_id), None)
            if not target_case:
                still_failing.append(failure)
                continue

            print(f"\n[修复] {case_id}...")
            print(f"  原因: {failure.get('message', '')[:100]}")

            # 生成修复补丁
            try:
                # 调用 Designer 生成修复后的测试脚本
                repair_result = designer.repair_test_case(
                    target_case,
                    failure_message=failure.get('message', ''),
                    adapter=engine.adapter,
                )

                if repair_result.get('status') == 'repaired':
                    # 重新执行这个用例
                    rerun_result = designer.execute_tests(
                        [target_case],
                        engine.Mode.L3,
                        adapter=engine.adapter,
                    )

                    # 检查是否通过
                    rerun_cases = rerun_result.get('cases', [])
                    if rerun_cases and rerun_cases[0].get('status') == 'pass':
                        print(f"  ✅ 修复成功")
                        fixed_count += 1
                    else:
                        print(f"  ❌ 修复后仍失败")
                        still_failing.append(failure)
                else:
                    print(f"  ⚠️ 修复失败: {repair_result.get('message', '')}")
                    still_failing.append(failure)

            except Exception as e:
                print(f"  ⚠️ 修复异常: {e}")
                still_failing.append(failure)

        print(f"\n[修复循环] 第 {iteration} 轮完成: 修复 {fixed_count}/{len(remaining_failures)} 个")

        # 更新 last.json
        engine.state_manager.update_execution_result(
            run_id=run_id,
            result=type('RunResult', (), {
                'fail': len(still_failing),
                'duration_seconds': 0,
            })(),
            failures=still_failing,
        )

        remaining_failures = still_failing

        # 如果全部修复完成 → 退出
        if not remaining_failures:
            print(f"\n[修复循环] ✅ 全部修复完成")
            break

        # 如果这轮没有任何进展 → 换策略（不是停止）
        if fixed_count == 0:
            print(f"\n[修复循环] ⚠️ 第 {iteration} 轮无进展")
            print(f"[修复循环] 换策略: 尝试批量重跑失败用例（可能是环境问题）")

            # 策略 2：批量重跑（可能是 flaky test）
            retry_result = designer.execute_tests(
                [c for c in designed_cases if c.id in [f['case_id'] for f in remaining_failures]],
                engine.Mode.L3,
                adapter=engine.adapter,
            )

            # 更新失败列表
            retry_failures = [
                f for f in remaining_failures
                if any(c.get('case_id') == f['case_id'] and c.get('status') == 'fail'
                       for c in retry_result.get('cases', []))
            ]

            if len(retry_failures) < len(remaining_failures):
                print(f"[修复循环] 批量重跑修复了 {len(remaining_failures) - len(retry_failures)} 个")
                remaining_failures = retry_failures
            else:
                print(f"[修复循环] 批量重跑无效")

    # 最终判定
    if not remaining_failures:
        print(f"\n[修复循环] ✅ 全部修复完成，更新判定为 PASS")
        final_verdict = {
            'verdict': 'PASS',
            'reason': f'CONDITIONAL PASS 后经过 {iteration} 轮修复，全部用例通过',
            'uncovered_requirements': [],
            'requirement_ids_inconsistencies': [],
            'uncovered_dimensions': [],
        }
    else:
        print(f"\n[修复循环] ⚠️ 修复 {iteration} 轮后仍有 {len(remaining_failures)} 个失败")
        print(f"[修复循环] 保持 CONDITIONAL PASS（需要人工介入）")
        final_verdict = {
            'verdict': 'CONDITIONAL PASS',
            'reason': f'经过 {iteration} 轮修复，剩余 {len(remaining_failures)} 个失败用例需人工修复',
            'uncovered_requirements': [],
            'requirement_ids_inconsistencies': [],
            'uncovered_dimensions': [],
        }

    return final_verdict, remaining_failures
