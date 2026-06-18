# Baseline 与断点恢复机制说明

## 概述

TestAgent V3.0 实现了完整的基线（baseline）管理和断点恢复（checkpoint resume）机制，确保测试执行的连续性和状态持久化。

---

## 一、Baseline 管理机制

### 1.1 设计目标

**问题**：之前只有 L3 完成后才保存 baseline，导致：
- L1/L2 执行后基线未更新
- L3 中断后重新开始会从头跑
- 下次运行 `load_baseline() = None` 被当作"首次 L3"

**解决方案**：每次测试执行后（任何模式）自动更新 baseline。

---

### 1.2 Baseline 数据结构

```json
{
  "established_at": "2026-06-16T10:00:00",    // 首次建立时间（不覆盖）
  "established_by": "run_20260616_100000",    // 首次建立的 run_id
  "updated_at": "2026-06-18T15:00:00",        // 最近更新时间
  "updated_by": "run_20260618_150000",        // 最近更新的 run_id
  "mode": "L2",                               // 最近执行模式
  "total_cases": 40,                          // 用例总数（累积最大值）
  "by_level": {                               // 按测试级别分组
    "static_check": 10,
    "unit": 15,
    "e2e": 15
  },
  "by_priority": {                            // 按优先级分组
    "P0": 10,
    "P1": 20,
    "P2": 10
  },
  "completeness": "partial",                  // full=L3完成, partial=其他
  "pass_rate": "85%",                         // 最近一次通过率
  "target_coverage": "主流程全覆盖 + 异常/边界 + 容错",
  "history": [                                // 最近 20 条执行历史
    {
      "run_id": "run_20260616_100000",
      "mode": "L1",
      "total_cases": 20,
      "timestamp": "2026-06-16T10:00:00"
    },
    {
      "run_id": "run_20260618_150000",
      "mode": "L2",
      "total_cases": 40,
      "timestamp": "2026-06-18T15:00:00"
    }
  ]
}
```

---

### 1.3 更新时机

**触发点**：`Engine.run()` 完成后（步骤 6）

```python
# qa_agent/core/engine.py
def run(self, mode: Mode, scope: str, ...):
    # ... 执行测试 ...
    
    # 步骤 6: 每次执行后自动更新基线
    self.state_manager.update_baseline_after_run(
        run_id=run_id,
        mode=mode.value,
        selection=selection,
        execution=result.get('execution', {}),
    )
```

**所有模式都会更新**：L0 / L1 / L2 / L3 / L4

---

### 1.4 合并策略

**合并逻辑**（`StateManager.save_baseline()`）：
1. 读取已有 baseline
2. 保留 `established_at`（首次建立时间）
3. 保留 `established_by`（首次建立者）
4. 更新 `updated_at` 和 `updated_by`
5. 追加 `history` 记录（只保留最近 20 条）
6. 用例总数取较大值（因为 L1 可能只跑子集）

**completeness 字段**：
- `full`：L3 完整执行完成
- `partial`：其他模式 / L3 未完成
- 如果已有 `full` 基线，非 L3 模式不降级

---

### 1.5 使用场景

#### 场景 1：L1 → L2 → L3 累积

```
L1 执行 20 条 → baseline = {total_cases: 20, completeness: 'partial'}
L2 执行 40 条 → baseline = {total_cases: 40, completeness: 'partial'}  # 累积
L3 执行 50 条 → baseline = {total_cases: 50, completeness: 'full'}     # 完整
```

#### 场景 2：L3 中断后恢复

```
L3 执行到 Phase 3 中断 → baseline = {total_cases: 30, completeness: 'partial'}
L3 下次运行 → load_baseline() 返回 30 条 → 自动恢复 → 继续执行
```

#### 场景 3：检查基线时效性

```python
def needs_baseline_refresh(self) -> bool:
    baseline = self.load_baseline()
    if not baseline:
        return True
    
    # 检查时效性（30 天）
    established = datetime.fromisoformat(baseline['established_at'])
    if datetime.now() - established > timedelta(days=30):
        return True
    
    return False
```

---

## 二、断点恢复机制（Checkpoint Resume）

### 2.1 设计目标

**问题**：L3 执行需要 8 个 Phase，中断后重新开始会浪费时间和资源。

**解决方案**：自动检测未完成的 checkpoint，智能恢复执行。

---

### 2.2 Checkpoint 数据结构

```json
{
  "checkpoint": {
    "current_phase": 3,                      // 下次应执行的 Phase
    "phase_name": "complete_functional",
    "completed_phases": [                    // 已完成的 Phase
      {
        "phase": 1,
        "name": "designer",
        "completed_at": "2026-06-18T10:00:00",
        "duration_s": 120
      },
      {
        "phase": 2,
        "name": "main_flow_e2e",
        "completed_at": "2026-06-18T10:05:00",
        "duration_s": 300
      }
    ],
    "git_head": "a1b2c3d4...",              // 当时的 Git HEAD
    "git_diff_hash": "e5f6g7h8...",         // 当时的 diff hash
    "expires_at": "2026-06-19T10:00:00"     // 过期时间（24 小时）
  }
}
```

**存储位置**：`qa/run/last.json` 的 `checkpoint` 字段

---

### 2.3 恢复流程

#### 步骤 0：检查可恢复的 checkpoint

```python
# Engine.run() 开头
resumable = self._check_resumable_checkpoint(mode, scope)
if resumable:
    print(f"\n[Engine] 检测到上次未完成的 {mode.value} 执行")
    print(f"  Run ID: {resumable['run_id']}")
    print(f"  已完成 Phase: {len(resumable.get('completed_phases', []))} / 8")
    print(f"  当前 Phase: {resumable.get('current_phase', '?')}")
    
    # 默认自动恢复
    if not user_overrides.get('force_new'):
        print(f"\n[Engine] 自动从断点恢复（使用 --force-new 重新开始）")
        return self._resume_from_checkpoint(resumable)
```

#### 检查条件

**`_check_resumable_checkpoint()` 检查**：
1. ✅ checkpoint 存在
2. ✅ 未过期（24 小时内）
3. ✅ Git HEAD 未变化
4. ✅ 模式和 scope 匹配

**任何一个不满足 → 不恢复**

---

### 2.4 恢复策略

#### L3 恢复逻辑（当前实现）

```python
def _resume_l3_from_checkpoint(self, run_id, current_phase, ...):
    """
    L3 断点恢复逻辑
    
    跳过已完成的 Phase：
    - Phase 1 (Designer) 已完成 → 跳过（保留已有用例库）
    - Phase 2 (主流程 E2E) 已完成 → 跳过
    - 从 Phase 3 (完整功能测试) 继续执行
    """
    print("[Engine] 跳过 Designer（保留已有用例库）")
    print("[Engine] 从主流程 E2E 开始重新执行")
    
    # 加载已有用例库
    all_cases = self._load_all_cases()
    
    # 构造 impact_result
    impact_result = {...}
    
    # 从主流程 E2E 开始执行（跳过 Designer）
    result = self._run_l3(run_id, impact_result, skip_designer=True)
    
    return result
```

**当前实现（基础版）**：
- ✅ 跳过 Designer（不重新生成用例）
- ✅ 保留已有用例库（qa/cases/）
- ✅ 从主流程 E2E 开始执行
- ⚠️ 不会精确跳转到 current_phase（会重跑部分已完成的 Phase）

**完整版（Phase 2 实现）**：
- 根据 `current_phase` 精确跳转
- 读取已完成 Phase 的结果（避免重复执行）
- Phase 内的断点续跑（如 Phase 3 执行到 50%）

---

#### 其他模式

**L0 / L1 / L2 / L4**：当前不支持断点恢复（单 Phase 执行）

```python
if mode != Mode.L3:
    print(f"[Engine] {mode.value} 模式不支持断点恢复（单 phase 执行）")
    return {
        'status': 'not_supported',
        'message': f'{mode.value} 模式不支持断点恢复',
    }
```

---

### 2.5 用户交互

#### 默认行为：自动恢复

```bash
$ /qa release

[Engine] 检测到上次未完成的 L3 执行
  Run ID: run_20260618_100000
  已完成 Phase: 2 / 8
  当前 Phase: 3
  上次执行: 2026-06-19T10:00:00

[Engine] 自动从断点恢复（使用 --force-new 重新开始）
[Engine] 跳过 Designer（保留已有用例库）
[Engine] 从主流程 E2E 开始重新执行
```

#### 强制重新开始

```bash
$ /qa release --force-new

[Engine] 检测到上次未完成的 L3 执行
  ...
[Engine] --force-new 指定，忽略 checkpoint，重新开始
```

---

### 2.6 保存时机

**每个 Phase 完成后保存**：

```python
# Engine._run_l3()
def _run_l3(self, run_id, impact_result):
    # Phase 1: Designer
    designer_result = self._phase_designer(...)
    self.state_manager.save_checkpoint(
        run_id, 1, 'designer', designer_result, git_head, git_diff_hash
    )
    
    # Phase 2: 主流程 E2E
    e2e_result = self._phase_main_flow_e2e(...)
    self.state_manager.save_checkpoint(
        run_id, 2, 'main_flow_e2e', e2e_result, git_head, git_diff_hash
    )
    
    # ... Phase 3-8 ...
```

---

## 三、L3 发版门完整流程（含断点恢复）

### 3.1 首次执行

```
用户执行: /qa release

步骤 0: 检查 checkpoint → 无
步骤 1: 预估 + 用户确认
步骤 2: 影响面分析
  - L3 Phase 0: 主流程清单显式确认
  - L3 Phase A: 检查用例库是否充分
步骤 3: 应用用户覆盖
步骤 4: 保存 last.json + selection.md
步骤 5: 路由到 L3 处理器
  - Phase 1: Designer 生成用例 → [checkpoint]
  - Phase 2: 主流程 E2E → [checkpoint]
  - Phase 3: 完整功能测试 → 中断 ❌
步骤 6: 更新 baseline
  - total_cases: 30
  - completeness: partial
  - history: [...]
```

---

### 3.2 断点恢复执行

```
用户执行: /qa release

步骤 0: 检查 checkpoint → 有
  - 打印提示（Run ID / 已完成 Phase / 当前 Phase）
  - 自动恢复（默认行为）
  
恢复流程:
  1. 读取上次状态（run_id, selection, impact_analysis）
  2. 加载已有用例库（_load_all_cases）
  3. 跳过 Phase 1 (Designer) → 保留 qa/cases/ 中的用例
  4. 从 Phase 2 (主流程 E2E) 开始执行
  5. Phase 3-8 依次执行
  6. 更新 baseline
     - completeness: full（L3 完整完成）
```

---

### 3.3 强制重新开始

```
用户执行: /qa release --force-new

步骤 0: 检查 checkpoint → 有
  - 打印提示
  - --force-new 指定 → 忽略 checkpoint
  - 继续正常流程（从步骤 1 开始）
  
正常流程:
  - Phase 1-8 全部重新执行
  - 会重新生成用例（覆盖 qa/cases/）
  - 更新 baseline（覆盖已有）
```

---

## 四、实现细节

### 4.1 核心文件

| 文件 | 关键方法 | 功能 |
|---|---|---|
| `state_manager.py` | `save_baseline()` | 保存/合并 baseline |
| `state_manager.py` | `update_baseline_after_run()` | 每次执行后自动更新 |
| `state_manager.py` | `load_baseline()` | 加载 baseline |
| `state_manager.py` | `save_checkpoint()` | 保存 Phase checkpoint |
| `engine.py` | `_check_resumable_checkpoint()` | 检查可恢复的 checkpoint |
| `engine.py` | `_resume_from_checkpoint()` | 断点恢复入口 |
| `engine.py` | `_resume_l3_from_checkpoint()` | L3 专用恢复逻辑 |

---

### 4.2 文件位置

```
qa/run/
├── baseline.json          # Baseline 数据
├── last.json              # 最近一次执行状态（含 checkpoint）
├── main_flows.md          # 主流程清单（L3）
└── ...
```

---

### 4.3 配置项

**checkpoint 过期时间**：24 小时（`state_manager.py` 第 110 行）

```python
'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
```

**baseline 刷新条件**：30 天（`state_manager.py` 第 319 行）

```python
if datetime.now() - established > timedelta(days=30):
    return True
```

---

## 五、使用建议

### 5.1 日常开发

**推荐工作流**：
1. L1 功能测试 → 自动更新 baseline（20 条）
2. L2 模块测试 → 累积更新 baseline（40 条）
3. L3 发版门 → 完整更新 baseline（50 条，completeness=full）

**断点恢复**：
- L3 中断 → 下次自动恢复（默认行为）
- 想重新开始 → 加 `--force-new` 参数

---

### 5.2 CI/CD 集成

**建议配置**：
- CI 环境：总是使用 `--force-new`（避免依赖 checkpoint）
- 本地开发：默认行为（自动恢复）

```yaml
# .github/workflows/qa.yml
- name: Run L3 Release Gate
  run: qa release --force-new  # CI 总是重新开始
```

---

### 5.3 监控与维护

**定期检查**：
- baseline 刷新时效（30 天）
- checkpoint 清理（过期的自动忽略）
- history 记录（只保留 20 条）

**手动清理**：
```bash
# 删除过期的 checkpoint
rm qa/run/last.json

# 重建 baseline
/qa release --force-new
```

---

## 六、后续改进（Roadmap）

### Phase 2 完整实现 ✅ 已完成（2026-06-18）

1. **精确 Phase 跳转** ✅
   - `_run_l3(skip_phases=[1,2,3])` 跳过已完成 Phase
   - 每个 Phase 检查是否在 skip_phases 中 → 打印 [已完成，跳过]
   - Phase 1 跳过时从磁盘加载用例（`_load_designed_cases_from_disk`）

2. **已完成 Phase 结果复用** ✅
   - `_run_l3(cached_results={1: {...}, 2: {...}})` 传入缓存
   - 从 checkpoint 的 `results_by_phase` 提取结果
   - 跳过的 Phase 使用缓存的 failures/duration/score

3. **其他模式断点恢复** ✅
   - `_resume_simple_mode_from_checkpoint()` 统一处理 L1/L2/L4
   - Designer 完成 + Execute 完成 → `_run_gatekeeper_only()`
   - Designer 完成 + Execute 未完成 → 从 Execute 继续
   - Designer 未完成 → 重新开始

4. **Phase 内断点续跑** ⚠️ 部分实现
   - 当前：Phase 级别的跳转（整个 Phase 跳过或重跑）
   - 未来：Phase 内用例级别（Phase 3 执行到第 15/30 条 → 只跑剩下 15 条）
   - 需要细粒度进度追踪（每条用例完成后保存）

---

## 七、常见问题

### Q1: baseline 何时刷新？

**A**: 每次测试执行后自动更新。不需要手动触发。

---

### Q2: checkpoint 过期了怎么办？

**A**: 自动忽略，按正常流程重新开始。过期时间 24 小时。

---

### Q3: Git HEAD 变化了，checkpoint 还有效吗？

**A**: 无效。Git HEAD 变化说明代码已更新，checkpoint 不再适用。

---

### Q4: 如何强制重新开始？

**A**: 使用 `--force-new` 参数：
```bash
/qa release --force-new
```

---

### Q5: 断点恢复会重新生成用例吗？

**A**: 不会。断点恢复会跳过 Designer Phase，保留已有的 qa/cases/ 用例库。

---

### Q6: baseline 的 history 有什么用？

**A**: 用于追踪用例库的演变历史，方便审计和问题定位。

---

## 八、参考资料

- [全局同步指南](GLOBAL_SYNC_GUIDE.md)
- [StudySkill L3 质量逃逸分析](../qa/bugs/BUG-001-StudySkill-L3-Quality-Escape.md)
- [业界经验调研](INDUSTRY_RESEARCH_AI_AGENT_QA.md)
