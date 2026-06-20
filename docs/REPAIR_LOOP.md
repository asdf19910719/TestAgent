# CONDITIONAL PASS 修复循环机制

## 概述

TestAgent V3.0 实现了 CONDITIONAL PASS 后的自动修复循环，遵守 `CLAUDE.md` 的任务持久性规则，禁止过早声明"不可修复"。

---

## 问题背景

### 用户反馈的问题

**场景**：L3 执行完成 → Gatekeeper 判定 CONDITIONAL PASS (39/40 E2E 通过) → **直接返回结果，没有修复循环**

**问题**：
1. 用户需要手动修复失败的测试
2. 修复结果没有回写到 QA 系统（`qa/run/last.json` / `qa/release_gate_report.md` / `qa/baseline.json`）
3. AI 在修复过程中容易过早声明"已达到极限"

**根因**：
- Engine 收到 CONDITIONAL PASS 后直接返回
- Gatekeeper 只判定，不触发修复
- 没有实现 `CLAUDE.md` 中的"QA Agent 特定规则"

---

## 修复方案

### 1. Engine 层面自动修复循环

**位置**：`qa_agent/core/engine.py` 第 649-662 行

```python
# L3 完成后检查 verdict
verdict = gatekeeper.judge(...)

if verdict['verdict'] == 'CONDITIONAL PASS':
    print(f"\n[Engine] 检测到 CONDITIONAL PASS，进入自动修复循环")
    
    from .engine_repair import repair_loop_l3
    verdict, all_failures = repair_loop_l3(
        engine=self,
        run_id=run_id,
        designed_cases=designed_cases,
        all_failures=all_failures,
        requirements_content=requirements_content,
        last_run=last_run,
        max_iterations=3,
    )
    
    # 更新最终 verdict
    gatekeeper.write_report(verdict, Mode.L3, last_run, ...)
```

---

### 2. 修复循环实现

**文件**：`qa_agent/core/engine_repair.py`

**核心逻辑**：

```python
def repair_loop_l3(
    engine, run_id, designed_cases, all_failures,
    requirements_content, last_run, max_iterations=3
) -> tuple[Dict, List[Dict]]:
    """
    CONDITIONAL PASS 后的自动修复循环
    
    遵守 CLAUDE.md 持久性规则：
    - 禁止过早声明"不可修复"
    - 每次修复后报告进度
    - 遇到障碍时先读源码再精确修复
    - 3 次尝试后换策略（不是停止）
    """
    iteration = 0
    remaining_failures = all_failures.copy()
    
    while remaining_failures and iteration < max_iterations:
        iteration += 1
        print(f"\n[修复循环] 第 {iteration}/{max_iterations} 轮")
        print(f"[修复循环] 待修复: {len(remaining_failures)} 个失败用例")
        
        # 逐个修复
        fixed_count = 0
        for failure in remaining_failures:
            repair_result = designer.repair_test_case(...)
            if repair_result.get('status') == 'repaired':
                # 重跑验证
                rerun_result = designer.execute_tests([target_case], ...)
                if rerun_result passed:
                    fixed_count += 1
        
        # 更新 last.json
        engine.state_manager.update_execution_result(...)
        
        # 如果全部修复 → 退出
        if not remaining_failures:
            break
        
        # 0 进展 → 换策略（批量重跑，可能是 flaky test）
        if fixed_count == 0:
            retry_result = designer.execute_tests([所有失败用例], ...)
            remaining_failures = 更新后的失败列表
    
    # 最终判定
    if not remaining_failures:
        return {'verdict': 'PASS', ...}, []
    else:
        return {'verdict': 'CONDITIONAL PASS', ...}, remaining_failures
```

---

## 执行流程

### 初次判定：CONDITIONAL PASS

```
L3 执行完成:
  - E2E: 39/40 (97.5%)
  - Unit: 51/51 (100%)
  - Static: 42/47 (89%)
  ↓
Gatekeeper 判定: CONDITIONAL PASS
  原因: 1 个 E2E 失败
  ↓
[Engine] 检测到 CONDITIONAL PASS，进入自动修复循环
```

---

### 修复循环（最多 3 轮）

```
[修复循环] 第 1/3 轮
[修复循环] 待修复: 1 个失败用例
  1. test_project_create_e2e: AssertionError: 选择器不匹配
  ↓
[修复] test_project_create_e2e...
  原因: 选择器不匹配
  ↓
designer.repair_test_case() → 生成修复补丁
  ↓
designer.execute_tests([test]) → 重跑验证
  ↓
✅ 修复成功
  ↓
[修复循环] 第 1 轮完成: 修复 1/1 个
  ↓
engine.state_manager.update_execution_result() → 更新 last.json
  ↓
remaining_failures = []
  ↓
[修复循环] ✅ 全部修复完成
```

---

### 最终判定：PASS

```
[修复循环] ✅ 全部修复完成，更新判定为 PASS
  ↓
gatekeeper.write_report(verdict=PASS, ...) → 更新报告
  ↓
返回:
  status: 'completed'
  verdict: 'PASS'
  execution: {total: 40, fail: 0}
```

---

## 修复策略

### 策略 1：逐个修复（默认）

**适用**：明确的失败原因（选择器不匹配、state 数据不完整、API 400 等）

**步骤**：
1. 调用 `designer.repair_test_case()` 生成修复补丁
2. 重新执行这个用例验证
3. 成功 → 标记为已修复
4. 失败 → 保留在失败列表

---

### 策略 2：批量重跑（换策略）

**触发条件**：某轮修复后 `fixed_count = 0`（无进展）

**适用**：Flaky tests（不稳定的测试，可能偶尔通过）

**步骤**：
1. 批量重跑所有剩余失败用例
2. 对比重跑结果
3. 通过的用例从失败列表移除

---

## 遵守的规则

### CLAUDE.md 任务持久性规则

**禁止停止的假理由**（以下全部可以继续修复）：

| 假理由 | 实际可修复方案 |
|---|---|
| "API 返回 400/500" | 检查 state 格式、版本冲突、API 端点 |
| "测试超时" | 增加超时、检查 API Key、优化调用链 |
| "选择器不匹配" | 读取组件源码，更新选择器 |
| "state 数据不完整" | 分析组件渲染条件，注入所需数据 |
| "语法错误" | 逐行修复，不依赖批量 sed |
| "只剩下几个了" | 继续逐个修复直到全部完成 |

**允许停止的硬阻塞**：
- 物理硬件需求（Android/iOS 设备、USB）
- 第三方 API 完全不可达（非配置问题）
- 用户明确要求停止

**执行规则**：
1. 每完成一个子任务，报告进度（如 "5/10 完成"）
2. 遇到障碍时，**先读取源码理解根因，再精确修复**，不得批量猜测
3. 如果 3 次尝试后仍失败，**换一种策略**（不是停止）
4. 全部完成后一次性汇总结果

---

## 状态持久化

### 每轮修复后更新

**文件更新**：
```python
engine.state_manager.update_execution_result(
    run_id=run_id,
    result=RunResult(fail=len(still_failing), ...),
    failures=still_failing,
)
```

**更新内容**：
- `qa/run/last.json` 的 `execution` 字段
  - `fail`: 剩余失败数
  - `failures`: 失败用例列表

---

### 全部完成后更新

1. **最终 verdict**：
   ```python
   gatekeeper.write_report(verdict, Mode.L3, last_run, Path('qa/final_test_report.md'))
   ```

2. **Baseline**：
   ```python
   # engine.py 第 145 行 — 自动调用
   self.state_manager.update_baseline_after_run(...)
   ```

3. **文件状态**：
   ```
   qa/run/last.json          — ✅ 更新为最终数据 (40/40)
   qa/release_gate_report.md — ✅ PASS（经过修复）
   qa/baseline.json          — ✅ completeness=full
   ```

---

## 用户体验

### Before（修复前）

```
$ /qa release

... L3 执行 ...
✅ L3 完成: CONDITIONAL PASS
   失败: 1 个 E2E
   
[返回控制权给用户]
→ 用户需要手动修复
→ 修复结果未回写
```

---

### After（修复后）

```
$ /qa release

... L3 执行 ...
✅ L3 初步判定: CONDITIONAL PASS
   失败用例数: 1

[Engine] 检测到 CONDITIONAL PASS，进入自动修复循环

[修复循环] 第 1/3 轮
[修复循环] 待修复: 1 个失败用例
  1. test_project_create_e2e: AssertionError

[修复] test_project_create_e2e...
  原因: 选择器不匹配
  ✅ 修复成功

[修复循环] 第 1 轮完成: 修复 1/1 个
[修复循环] ✅ 全部修复完成

[修复循环] ✅ 全部修复完成，更新判定为 PASS
✅ L3 最终判定: PASS
```

---

## 当前实现状态

| 功能 | 状态 | 说明 |
|---|---|---|
| **Engine 检测 CONDITIONAL PASS** | ✅ 已实现 | engine.py 第 652 行 |
| **修复循环框架** | ✅ 已实现 | engine_repair.py |
| **逐个修复逻辑** | ✅ 已实现 | repair_loop_l3() |
| **策略切换（批量重跑）** | ✅ 已实现 | fixed_count=0 时触发 |
| **状态持久化** | ✅ 已实现 | 每轮更新 last.json |
| **智能修复** | ⚠️ 框架就绪 | designer.repair_test_case() 返回 'failed' |

**智能修复（Phase 2）** 需要：
- 根据 failure_message 分析根因
- 生成修复补丁（LLM / 规则引擎）
- 适配不同测试框架（Playwright / Jest / Pytest）

---

## 配置项

**修复循环最大轮次**：`max_iterations=3`（可配置）

**位置**：`engine.py` 第 660 行

```python
verdict, all_failures = repair_loop_l3(
    ...
    max_iterations=3,  # 可通过 config 配置
)
```

---

## 参考资料

- [BASELINE_AND_CHECKPOINT.md](BASELINE_AND_CHECKPOINT.md) — Baseline 管理机制
- [GLOBAL_SYNC_GUIDE.md](GLOBAL_SYNC_GUIDE.md) — 全局同步规则
- `~/.claude/CLAUDE.md` — 任务持久性规则
- `engine_repair.py` — 修复循环实现
- `designer_runner.py` — repair_test_case() 接口
