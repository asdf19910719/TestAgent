# /qa finalize 快速使用指南

## 什么时候用？

当你**手动修复测试**后，使用 `/qa finalize` 更新 QA Agent 状态。

---

## 典型场景

### 场景 1：L3 CONDITIONAL PASS 后全部修复

```bash
# 1. L3 执行完成
/qa release
# → Gatekeeper 判定: CONDITIONAL PASS (2 个失败)
# → 自动修复循环 3 轮后仍有失败
# → 输出: "需要人工介入"

# 2. 你手动修复代码
# （修复选择器、API 调用等）

# 3. 重跑验证
/qa retry
# → 全部通过

# 4. 更新状态
/qa finalize PASS "40/40 (100%)" --reason "修复选择器 + Cloud API 重试"
```

---

### 场景 2：接受 waiver（部分失败）

```bash
# 1. L3 判定 CONDITIONAL PASS
# 失败原因: v53 物理设备缺失、v622 Cloud API 500

# 2. 创建 waivers.yml
# 记录豁免原因

# 3. 接受 CONDITIONAL PASS
/qa finalize "CONDITIONAL PASS" "38/40 (95%)" \
  --reason "v53/v622 为 harness 问题，已创建 waivers.yml"
```

---

### 场景 3：任何模式修复后

```bash
# 任何模式执行后发现问题
/qa feature login
# → 发现 1 个失败

# 手动修复
# ...

# 更新状态（默认 PASS）
/qa finalize
```

---

## 命令格式

```bash
qa finalize [verdict] [pass_rate] [--reason <原因>] [--fixes <修复内容>]
```

**参数**：
- `verdict`: 可选，默认 `PASS`
  - `PASS` — 全部通过
  - `CONDITIONAL PASS` — 部分失败已 waive
  - `FAIL` — 仍有失败
- `pass_rate`: 可选，如 `"40/40 (100%)"`
- `--reason` / `-r`: 修复原因说明
- `--fixes` / `-f`: 修复内容（可多次指定）

---

## 实际效果

```bash
$ qa finalize PASS "40/40 (100%)" -r "修复选择器"

[QA Agent] 检查状态一致性...
⚠️  检测到状态不一致:
  - last.json status='running'，可能未正确完成

[QA Agent] 准备更新状态
  Run ID: run_20260621_091547
  模式: L3
  判定: PASS
  通过率: 40/40 (100%)
  原因: 修复选择器

确认更新？ [Y/n]: y

✅ 状态已更新:
  ✅ qa/run/last.json
  ✅ qa/run/baseline.json
  ✅ qa/run/history.jsonl

[QA Agent] 验证状态一致性...
✅ 状态一致性检查: 通过

[QA Agent] 下次执行 /qa l3 将读取最新状态
```

---

## 修复前 vs 修复后

### Before（手动修复但不更新）

```
last.json:
  status: "running"          ← 错误
  verdict: "FAIL"            ← 错误

baseline.json:
  updated_at: 13:20          ← 手动写入
  pass_rate: "38/40 (95%)"

问题：下次启动会读 last.json → 状态混乱
```

---

### After（使用 /qa finalize）

```
last.json:
  status: "completed"        ← 正确
  verdict: "PASS"            ← 正确
  execution.end_time: ...

baseline.json:
  updated_at: 14:00          ← 自动更新
  pass_rate: "40/40 (100%)"
  updated_by: run_20260621_091547

history.jsonl:
  + {"manually_repaired": true, ...}

状态一致：✅
```

---

## 只检查不更新

```bash
qa finalize --check-only
```

输出：
```
[QA Agent] 检查状态一致性...
✅ 当前状态一致

[QA Agent] --check-only 模式，仅检查不更新
```

---

## 与自动修复循环的区别

| 场景 | 行为 |
|---|---|
| **自动修复循环** | Gatekeeper 判定后自动触发，Agent 修复 + 重跑 + 更新状态 |
| **/qa finalize** | 用户手动修复后，手动更新状态（不重跑测试） |

**时机**：
- 自动修复循环 → L3 CONDITIONAL PASS 后**立即自动执行**
- /qa finalize → 自动修复 3 轮后仍失败 → **用户手动执行**

---

## 配合 waivers.yml

创建 `qa/waivers.yml`：

```yaml
waivers:
  - case_id: TC-rele-004
    bug_id: BUG-L3-003
    reason: v53 物理设备缺失，Playwright WebView 问题
    waived_by: user@example.com
    waived_at: 2026-06-21T10:30:00
    expires_at: 2026-07-21T10:30:00
```

然后：

```bash
qa finalize "CONDITIONAL PASS" "38/40 (95%)" \
  --reason "v53/v622 已豁免，见 waivers.yml"
```

---

## 常见问题

### Q1: 忘记执行 /qa finalize 会怎样？

**A**: 下次执行 `/qa release`，Agent 会读 `last.json` → 看到 `status='running'` → 尝试 checkpoint 恢复 → 状态混乱。

**建议**: 每次手动修复后必须执行 `/qa finalize`。

---

### Q2: 可以不写 pass_rate 吗？

**A**: 可以。如果不写，Agent 会从 last.json 中推断。但建议明确指定，避免歧义。

---

### Q3: 多次执行 /qa finalize 会覆盖吗？

**A**: 会。每次执行都会更新 `last.json`、`baseline.json` 和追加 `history.jsonl`。

---

### Q4: 可以在 L1/L2/L4 使用吗？

**A**: 可以。`/qa finalize` 适用于所有模式。

---

## 参考

- [REPAIR_LOOP.md](../docs/REPAIR_LOOP.md) — 修复循环机制
- [BASELINE_AND_CHECKPOINT.md](../docs/BASELINE_AND_CHECKPOINT.md) — Baseline 管理
- `qa/run/last.json` — 最近执行状态
- `qa/run/baseline.json` — 用例规模基线
