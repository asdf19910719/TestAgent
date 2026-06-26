# TestAgent V2 优化方案

## 设计原则

1. **保持轻量**：仍然是 1 command + 2-3 agent，不搞 60 agent
2. **吸收精华**：从 oec-infra 移植关键规则和方法论，不移植平台依赖
3. **强制执行**：E2E 不可跳过、P0 未执行=BLOCKED、无证据不得 PASS
4. **自主运行**：Agent 自动检测环境、启动服务、执行测试、清理资源
5. **持续学习**：基线 + 历史 + 反馈闭环

## 架构变化（V1 → V2）

### V1 架构（当前）

```
/qa command
  └── 当前上下文直接执行
      ├── prepare（Python 工具：影响面分析）
      ├── scaffold（Python 工具：生成骨架）
      ├── execute（Python 工具：运行测试）
      └── gatekeeper（LLM 判定）
```

### V2 架构（目标）

```
/qa command（入口 + 编排）
  │
  ├── Agent: qa-test-engineer（设计 + 执行）
  │     ├── 用例设计（模板驱动，非裸写）
  │     ├── 环境启动（自动检测）
  │     ├── 测试执行（含 E2E）
  │     ├── 自动重试（flaky 治理）
  │     └── 产物输出（结构化 JSON）
  │
  ├── Agent: qa-gatekeeper（独立判定）
  │     ├── 硬规则检查（P0 未执行 = BLOCKED）
  │     ├── 覆盖率门控
  │     ├── Mutation Score 门控
  │     └── 学习反馈（记录是否被推翻）
  │
  └── Agent: qa-impact-analyzer（新增，可选）
        ├── 代码层：git diff + CodeGraph 符号分析
        ├── 语义层：LLM 理解业务含义
        └── 输出：影响范围 + 推荐用例 + 覆盖缺口
```

## 具体改进项（按优先级）

### P0：必须实现（解决当前痛点）

#### 1. Gatekeeper 硬规则（移植自 oec-infra verify-change）

```yaml
# qa-gatekeeper.md 新增红线
硬规则（违反任意一条 = 结论无效）：
- P0/P1 用例未执行 → BLOCKED（不是 CONDITIONAL PASS）
- 没有真实执行证据（截图/日志/断言输出）→ 不得标记通过
- 报告中有失败记录但总结写通过 → 最终结论必须 FAIL
- E2E 用例标"未执行"但 unit 全过 → L3 不得 PASS
```

#### 2. 用例生成模板化（移植自 oec-infra test-design-agent 理念）

当前问题：LLM 裸写用例 → 可能遗漏字段、断言永真
改进：scaffold 生成完整骨架 → LLM 只填充业务逻辑

```
V1: LLM 从零生成完整 YAML + 测试脚本
V2: scaffold 生成结构化模板 → LLM 填充 steps/assertions → 校验层检查
```

#### 3. 影响面语义分析（移植自 oec-infra impact-analysis-agent 三层融合）

```
V1: git diff → 文件名匹配 → 选用例
V2: git diff → 文件名匹配 + LLM 语义理解 → 扩大选择范围
```

在 prepare 阶段加一步 LLM 推理：
- 输入：diff 内容 + 项目模块清单
- 输出：业务影响范围描述 + 额外需要测试的模块
- 结果合并到 selection.md

#### 4. 自动重试（移植自 oec-infra qe-iterative-loop）

```yaml
# .qa-agent.yml 新增
auto_retry:
  enabled: true
  max_rounds: 3          # 最多重试 3 轮
  retry_scope: failed    # 只重跑失败的用例
  flaky_threshold: 2     # 连续失败 2 次才算真失败
```

### P1：应该实现（提升质量）

#### 5. 覆盖率门控（移植自 oec-infra qe-coverage-specialist）

```yaml
# .qa-agent.yml 新增
coverage_gate:
  line_threshold: 70       # 行覆盖率 < 70% → CONDITIONAL PASS
  branch_threshold: 50     # 分支覆盖率 < 50% → CONDITIONAL PASS
  mutation_threshold: 60   # 变异分数 < 60% → CONDITIONAL PASS
  enabled_modes: [L2, L3]  # 只在 L2/L3 检查
```

#### 6. 多层级质量门（移植自 oec-infra qe-quality-gate 四级门控）

```
V1: 所有模式同一判定逻辑
V2: 分级判定

  L1/L2（PR 级）：允许 CONDITIONAL PASS
  L3（Release 级）：只允许 PASS 或 FAIL
  L4（Bugfix 级）：bug 复现 + 无回归 = PASS
```

#### 7. 学习反馈闭环（移植自 oec-infra MCP memory 机制）

history.jsonl 增加字段：
```json
{
  "run_id": "...",
  "gatekeeper_verdict": "FAIL",
  "user_override": true,      // 用户是否推翻
  "override_reason": "已知 flaky，手动确认通过",
  "feedback_score": 0.3       // 判定质量评分
}
```

用途：
- 统计 gatekeeper 被推翻的频率
- 如果某类判定经常被推翻 → 调整阈值
- 跨 session 积累经验

### P2：值得实现（长期价值）

#### 8. Flaky 治理（移植自 oec-infra qe-flaky-hunter）

- 标记连续 pass-fail-pass 的用例为 flaky
- flaky 用例自动重试 2 次确认
- 统计 flaky 率，超 10% 告警

#### 9. 测试设计方法论内置（移植自 oec-infra test-design-techniques）

在 qa-test-engineer.md 中内置经典方法：
- 等价类划分（Equivalence Partitioning）
- 边界值分析（Boundary Value Analysis）
- 决策表（Decision Table）
- 状态转换图（State Transition）
- 正交实验（Pairwise/Orthogonal Array）

让 Agent 在设计用例时**显式标注使用了哪种方法**。

#### 10. 安全测试基线（移植自 oec-infra security-testing Skill）

L3 默认执行：
- 依赖审计（npm audit / pip-audit）
- 静态安全扫描（semgrep / bandit）
- OWASP Top 10 检查清单

## 文件变更清单

| 文件 | 变更 |
|---|---|
| `.claude/commands/qa.md` | 更新编排逻辑、新增自动重试参数 |
| `.claude/agents/qa-test-engineer.md` | 模板化用例生成、方法论内置 |
| `.claude/agents/qa-gatekeeper.md` | 硬规则、多层级判定、覆盖率门控 |
| `qa_agent/core/impact_analysis.py` | 语义分析步骤（LLM 推理） |
| `qa_agent/core/gatekeeper.py` | 覆盖率/mutation 门控条件 |
| `qa_agent/core/state_manager.py` | 学习反馈字段 |
| `qa_agent/core/config.py` | auto_retry / coverage_gate 配置 |
| `.qa-agent.yml`（模板） | 新增 auto_retry / coverage_gate 字段 |

## 不做的事情

| 不做 | 原因 |
|---|---|
| 60+ Agent 架构 | 单人使用过度设计 |
| 平台集成（UTP） | 无平台可对接 |
| 自定义 Playwright wrapper | 用原生 Playwright 足够 |
| MCP memory 机制 | 用 history.jsonl + baseline.json 替代 |
| Queen/Fleet 编排层 | 2 个 agent 不需要编排器 |
| .aqe-output 产物体系 | 用 qa/ 目录结构替代 |

## 实施顺序

```
Phase 1（本周）：P0 项（硬规则 + 模板化 + 语义分析 + 自动重试）
Phase 2（下周）：P1 项（覆盖率门控 + 多层级判定 + 学习反馈）
Phase 3（后续）：P2 项（flaky + 方法论 + 安全基线）
```
