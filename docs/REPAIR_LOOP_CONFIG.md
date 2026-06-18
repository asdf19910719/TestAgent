# repair_loop 配置说明

## 配置项

```yaml
# .qa-agent.yml
repair_loop:
  mode: manual                # manual | auto-dev | auto-fixer
  per_case_attempts: 3        # 单个用例最多重试次数
  total_rounds: 5             # 整体最多执行轮数
```

---

## 三种模式

### 1. `manual`（手动修复，默认）

**适用场景**：开发调试阶段，希望手动查看每次失败

**行为**：
- ❌ 不自动重试失败用例（`max_retries_per_case = 0`）
- ❌ 不自动修复脚本错误（`script_auto_fix_enabled = False`）
- ✅ 执行 1 轮后停止（`max_execution_rounds = 1`）

**适合**：
- 本地开发时快速反馈
- 调试单个用例失败原因
- 不想自动重试浪费时间

---

### 2. `auto-dev`（自动重试，开发模式）

**适用场景**：持续集成（CI）环境，希望自动处理 flaky 用例

**行为**：
- ✅ 自动重试失败用例（最多 `per_case_attempts` 次，默认 3）
- ❌ 不自动修复脚本错误（假设脚本已通过人工审查）
- ✅ 最多执行 `total_rounds` 轮（默认 5）

**适合**：
- CI/CD 流水线
- 夜间回归测试
- 自动化验证

---

### 3. `auto-fixer`（自动修复，生产模式）

**适用场景**：AI 生成的测试脚本，可能存在语法/导入错误

**行为**：
- ✅ 自动重试失败用例（最多 `per_case_attempts` 次，默认 3）
- ✅ **自动修复脚本错误**（SyntaxError/ImportError/NameError 等）
- ✅ 最多执行 `total_rounds` 轮（默认 5）

**适合**：
- AI 生成测试脚本后首次执行
- TestAgent 自动化流程（`/qa feature` / `/qa module`）
- 需要脚本自愈能力的场景

---

## 配置映射关系

| 配置项 | manual | auto-dev | auto-fixer |
|---|---|---|---|
| `enabled` | ❌ False | ✅ True | ✅ True |
| `max_retries_per_case` | 0 | 3 | 3 |
| `max_execution_rounds` | 1 | 5 | 5 |
| `script_auto_fix_enabled` | ❌ False | ❌ False | ✅ True |

---

## 使用示例

### 示例 1：本地开发（不重试）

```yaml
# .qa-agent.yml
repair_loop:
  mode: manual
  per_case_attempts: 3     # 不生效（manual 模式强制 0）
  total_rounds: 5          # 不生效（manual 模式强制 1）
```

**效果**：执行 1 次失败立即停止，便于快速定位问题。

---

### 示例 2：CI 环境（重试但不修复脚本）

```yaml
# .qa-agent.yml
repair_loop:
  mode: auto-dev
  per_case_attempts: 2     # 失败用例最多重试 2 次
  total_rounds: 3          # 整体最多执行 3 轮
```

**效果**：
- WebUI Sentinel 预算上限：3 轮
- Backend 脚本错误：**不自动修复**（假设脚本已人工审查）
- 失败用例自动重试 2 次

---

### 示例 3：AI 生成脚本（自动修复）

```yaml
# .qa-agent.yml
repair_loop:
  mode: auto-fixer
  per_case_attempts: 3     # 失败用例最多重试 3 次
  total_rounds: 5          # 整体最多执行 5 轮
```

**效果**：
- WebUI Sentinel 预算上限：5 轮
- Backend 脚本错误：**自动修复** SyntaxError/ImportError/NameError
- 修复后自动重试（最多 1 次）
- 失败用例自动重试 3 次

---

## 配置优先级

1. **`.qa-agent.yml` 项目配置**（最高优先级）
2. **命令行参数**（如 `batch_run.py --max-retries N`，覆盖 `per_case_attempts`）
3. **`qa_agent/core/config.py` 默认值**（最低优先级）

---

## 预算上限机制

### WebUI Sentinel 预算守卫

从 `repair_loop.total_rounds` 读取：

```python
# qa_agent/webui/executor/batch_run.py
BUDGET_MAX_ROUNDS = repair_loop.max_execution_rounds  # 默认 3（manual）或 5（auto）
BUDGET_MAX_WALL_CLOCK = 1800  # 30 分钟墙钟时间（硬编码）
BUDGET_ABSOLUTE_MAX = 10      # 绝对上限（即使 --force-reopen 也不能突破）
```

**三级预算**：
- **轮数上限**：`BUDGET_MAX_ROUNDS`（可配置）
- **墙钟时间上限**：30 分钟（硬编码）
- **绝对上限**：10 轮（硬编码，防止死循环）

---

### Backend Script Auto-Fixer

从 `repair_loop.per_case_attempts` 读取：

```python
# qa_agent/adapters/backend/api_executor/script_auto_fixer.py
max_retries = repair_loop.max_retries_per_case  # 默认 0（manual）或 3（auto）
auto_fix_enabled = repair_loop.script_auto_fix_enabled  # 仅 auto-fixer 为 True
```

**重试机制**：
- 执行测试 → 失败 → 分析错误类型
- 如果 `auto_fix_enabled=True` 且错误可修复 → 应用修复 → 重试
- 最多重试 `max_retries` 次

---

## 注意事项

### 1. `manual` 模式下配置无效

`manual` 模式强制覆盖：
- `per_case_attempts` → 0（不重试）
- `total_rounds` → 1（不重复执行）
- `script_auto_fix_enabled` → False（不修复脚本）

即使配置文件写了 `per_case_attempts: 10`，实际也是 0。

---

### 2. `auto-dev` vs `auto-fixer` 的区别

唯一区别是 **`script_auto_fix_enabled`**：

- `auto-dev`：假设脚本已经过人工审查，语法/导入错误不应出现，**不自动修复**
- `auto-fixer`：假设脚本由 AI 生成，可能存在小错误，**自动修复后重试**

其他行为（重试次数、执行轮数）完全相同。

---

### 3. 向后兼容

如果配置文件中没有 `repair_loop` 项，使用以下默认值：

```yaml
repair_loop:
  mode: manual
  per_case_attempts: 3
  total_rounds: 5
```

旧项目升级后不需要修改配置文件，默认行为保持不变（manual 模式）。

---

## 推荐配置

### 本地开发
```yaml
repair_loop:
  mode: manual
```

### CI/CD
```yaml
repair_loop:
  mode: auto-dev
  per_case_attempts: 2
  total_rounds: 3
```

### AI Agent 自动化
```yaml
repair_loop:
  mode: auto-fixer
  per_case_attempts: 3
  total_rounds: 5
```

---

## 相关文件

- `qa_agent/core/repair_loop.py` - 配置管理模块
- `qa_agent/core/config.py` - 默认配置
- `qa_agent/webui/executor/batch_run.py` - WebUI Sentinel 预算守卫
- `qa_agent/adapters/backend/api_executor/script_auto_fixer.py` - 脚本自动修复器
- `qa_agent/adapters/backend/adapter.py` - Backend Adapter 集成
