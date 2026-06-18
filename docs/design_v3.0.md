# AI Test Engineer Agent v3.0 Solo Edition 详细设计

> 版本：v3.0-design-rev1
> 修订日期：2026-06-17
> 配套规范：`AI Test Engineer Agent 需求与方案文档 v3.0.md`（v3.0-rev1）
> 文档定位：架构设计、数据结构、算法伪代码、提示词框架、实施路径

---

## 修订摘要（rev1 相对 design-01）

同步主规范 v3.0-rev1 的 15 项修订：

* §2.1 `last.json` 增加 `phase` / `checkpoint` 字段（支持 P1-4 检查点恢复）
* §3.1 影响面分析增加深度配置覆盖、漏选兜底实现（P0-2、补集兜底）
* §3.5 新增 bug 引用解析算法（P2-2）
* §3.6 新增需求文档自动发现算法（P0-1）
* §6.3 Gatekeeper 提示词增加独立校验 `requirement_ids` 步骤（P0-3）
* §6.5 Gatekeeper LLM 成本优化（P1-1）：算法判定 + Haiku + 缓存
* §6.7 新增非功能测试调度提示词（P0-5）
* §7.4 新增 Generic Adapter 实现骨架（P0-4）
* §8.4 新增检查点恢复机制（P1-4）
* §8.5 新增 Mutation 工具降级算法（P1-3）
* §10 实施路径调整：Phase 1 增加 `/qa init` 引导式初始化（P2-1）

**rev2 修订（2026-06-18）— 断点恢复 Phase 2 + Baseline 管理**：

* §8.4 检查点恢复机制升级为完整实现：
  - 精确 Phase 跳转（`skip_phases` 参数）
  - 已完成 Phase 结果复用（`cached_results` 参数）
  - L1/L2/L4 断点恢复支持（`_resume_simple_mode_from_checkpoint`）
  - 仅 Gatekeeper 执行模式（`_run_gatekeeper_only`）
* §8.6 新增 Baseline 管理机制：
  - 每次执行后自动更新 baseline（`update_baseline_after_run`）
  - 合并策略（保留 `established_at`、累积 `total_cases`、追加 `history`）
  - L3 Gatekeeper PASS 后自动保存基线
* §8.7 新增智能默认恢复：
  - 检测到 checkpoint → 自动恢复（默认行为）
  - `--force-new` 参数强制重新开始

---

## 目录

1. 架构设计
2. 核心数据结构
3. 算法详解（影响面、需求扫描、bug 引用、Flaky、Mutation）
4. ~~（合并到 §3）~~
5. ~~（合并到 §3）~~
6. 提示词框架
7. Adapter 插件系统
8. 状态恢复与容错
9. 技术栈决策
10. 实施路径（MVP → v1.0）
11. 测试策略

---

## 1. 架构设计

### 1.1 进程模型

```text
用户输入 /qa feature 登录
    ↓
┌─────────────────────────────────────────────────┐
│ qa-cli (入口脚本)                                 │
│ - 解析命令行参数                                   │
│ - 加载 .qa-agent.yml                             │
│ - 调用 Core.run(mode, scope)                     │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│ Core (qa_core/engine.py)                        │
│ - 模式路由（L0/L1/L2/L3/L4）                      │
│ - 角色编排                                        │
│ - 状态持久化                                      │
└─────────────────────────────────────────────────┘
    ↓
┌──────────────────┐        ┌──────────────────┐
│ DesignerRunner   │        │ Gatekeeper       │
│ (同一进程)        │───────▶│ (独立子进程)      │
│                  │ 产物   │                  │
│ LLM 调用 #1      │────────│ LLM 调用 #2      │
│ - 设计用例        │ last.  │ - 读原始需求     │
│ - 生成脚本        │ json   │ - 独立判定       │
│ - 执行           │        │ - 输出报告       │
└──────────────────┘        └──────────────────┘
    ↓                           ↓
┌─────────────────────────────────────────────────┐
│ Adapter (adapters/web/adapter.py)               │
│ - detect() / scaffold() / generate()            │
│ - run() / parse_report() / collect_artifacts()  │
│ - index_targets() / classify_failure()          │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│ 测试框架 (Playwright / Vitest / pytest)          │
└─────────────────────────────────────────────────┘
```

### 1.2 角色实现方案

**DesignerRunner（同一上下文）**：

```python
class DesignerRunner:
    def execute(self, mode: str, scope: str, config: Config):
        # 阶段 1: 设计（仅 L1/L2/L3）
        if mode in ['L1', 'L2', 'L3']:
            cases = self.design_cases(scope, config)
            self.save_cases(cases)
        
        # 阶段 2: 影响面分析
        selection = self.analyze_impact(mode, scope, config)
        self.write_selection_md(selection)
        
        # 阶段 3: 生成/更新自动化脚本
        for case in selection:
            if case.automation.status != 'implemented':
                adapter.generate(case)
        
        # 阶段 4: 执行
        results = adapter.run(selection, mode)
        
        # 阶段 5: 收集失败
        bugs = self.collect_failures(results)
        self.save_bugs(bugs)
        
        # 阶段 6: Flaky 检测（仅失败用例）
        if mode in ['L2', 'L3']:
            self.detect_flaky(results)
        
        # 阶段 7: Mutation（仅 L3 + diff）
        if mode == 'L3':
            self.run_mutation_sampling(config)
        
        # 持久化状态
        self.save_last_run(results, selection, bugs)
        
        return results
```

**Gatekeeper（独立进程 / 独立 Agent 实例）**：

```python
class Gatekeeper:
    def judge(self, run_id: str, config: Config):
        # 步骤 1: 加载执行结果（不读 Designer 的推理过程）
        last_run = load_json('qa/run/last.json')
        
        # 步骤 2: 独立从原始需求摘录
        requirements = self.read_original_requirements()
        
        # 步骤 3: 加载用例库
        cases = load_all_cases('qa/cases')
        
        # 步骤 4: 加载 waivers
        waivers = load_yaml('qa/waivers.yml')
        
        # 步骤 5: 独立判定
        verdict = self.make_verdict(last_run, requirements, cases, waivers, config)
        
        # 步骤 6: 输出报告
        self.write_report(verdict, last_run['mode'])
        
        return verdict
```

### 1.3 调用方式

**技术栈选择**：Python 3.11+ + Claude Code 的 Workflow/Agent 工具

```python
# qa-cli 主入口
def main():
    args = parse_args()  # /qa feature 登录
    config = load_config('.qa-agent.yml')
    
    # 步骤 1: DesignerRunner
    results = DesignerRunner(config).execute(args.mode, args.scope, config)
    
    # 步骤 2: Gatekeeper（独立子进程）
    verdict = subprocess_call_gatekeeper(results.run_id, config)
    
    # 步骤 3: 输出到终端
    print_summary(results, verdict)
```

---

## 2. 核心数据结构

### 2.1 `qa/run/last.json`

支持检查点恢复（P1-4），新增 `phase`、`checkpoint`、`status` 字段：

```json
{
  "run_id": "run_20260616_100000",
  "mode": "L3",
  "scope": "release",
  "status": "running",            
  "trigger": {
    "source": "human",
    "command": "/qa release",
    "timestamp": "2026-06-16T10:00:00+08:00"
  },
  
  "checkpoint": {
    "current_phase": 4,
    "phase_name": "system_test",
    "completed_phases": [
      {"phase": 1, "name": "designer", "completed_at": "2026-06-16T10:01:00+08:00", "duration_s": 60},
      {"phase": 2, "name": "unit_test", "completed_at": "2026-06-16T10:03:00+08:00", "duration_s": 120},
      {"phase": 3, "name": "integration_test", "completed_at": "2026-06-16T10:08:00+08:00", "duration_s": 300}
    ],
    "git_head": "abc123def",
    "git_diff_hash": "sha256:...",
    "expires_at": "2026-06-17T10:00:00+08:00"
  },
  
  "selection": {
    "total": 80,
    "by_level": {"unit": 12, "integration": 20, "system": 30, "acceptance": 18},
    "by_priority": {"P0": 30, "P1": 35, "P2": 15},
    "case_ids": ["TC-LOGIN-001", "TC-LOGIN-002", "..."]
  },
  
  "impact_analysis": {
    "mode": "gitnexus",
    "diff_files": ["src/pages/login.tsx", "src/api/auth.ts"],
    "affected_symbols": ["LoginPage", "authenticate", "validateCredentials"],
    "depth_used": 3,
    "direct_hit_cases": ["TC-LOGIN-001", "TC-LOGIN-002"],
    "补集_from_feature_id": ["TC-LOGIN-003"],
    "补集_from_regression_tags": ["TC-AUTH-001"],
    "flaky_candidates": []
  },
  
  "execution": {
    "start_time": "2026-06-16T10:00:10+08:00",
    "end_time": null,
    "duration_seconds": null,
    "results_by_phase": {
      "unit_test": {"total": 12, "pass": 12, "fail": 0, "skip": 0},
      "integration_test": {"total": 20, "pass": 20, "fail": 0, "skip": 0},
      "system_test": null,
      "acceptance_test": null,
      "nonfunctional": null,
      "mutation": null
    },
    "failures": []
  },
  
  "repair_loop": {
    "mode": "manual",
    "rounds_used": 0,
    "max_rounds": 5
  },
  
  "gatekeeper_verdict": null,
  "checksum": "sha256:..."
}
```

#### 关键字段说明

| 字段 | 含义 | P1-4 用途 |
|---|---|---|
| `status` | `running` / `paused` / `completed` / `failed` / `blocked` | 恢复时区分中断类型 |
| `checkpoint.current_phase` | 当前所处 phase 编号（1-8） | 恢复起点 |
| `checkpoint.completed_phases[]` | 已完成 phase 列表 | 跳过已完成步骤 |
| `checkpoint.git_head` | 中断时的 git HEAD | 恢复时检查 git 是否变化 |
| `checkpoint.git_diff_hash` | 中断时 diff 的 hash | 检测代码变更影响 |
| `checkpoint.expires_at` | 检查点过期时间（24 小时） | 超时自动失效 |
| `repair_loop.mode` | manual / auto-dev / auto-fixer | 失败处理策略 |
| `repair_loop.rounds_used` | 已用修复轮次 | 受 5 轮上限保护 |

### 2.2 `qa/run/history.json`（滚动窗口）

```json
{
  "window_size": 50,
  "runs": [
    {
      "run_id": "run_20260616_100000",
      "timestamp": "2026-06-16T10:00:00+08:00",
      "mode": "L1",
      "total": 8,
      "pass": 6,
      "fail": 2
    }
  ],
  "flaky_statistics": {
    "TC-LOGIN-003": {
      "total_runs": 12,
      "pass_count": 10,
      "fail_count": 2,
      "flaky_score": 0.167,
      "last_flaky_at": "2026-06-10T14:00:00+08:00"
    }
  }
}
```

### 2.3 `qa/run/selection.md`（视图文件）

```markdown
# 执行选择（L1 Feature: 登录）

运行 ID: run_20260616_100000
影响面来源: GitNexus
执行模式: L1

## 变更文件

- src/pages/login.tsx
- src/api/auth.ts

## 受影响符号

- LoginPage (src/pages/login.tsx:15)
- authenticate (src/api/auth.ts:42)
- validateCredentials (src/api/auth.ts:58)

## 直接命中用例（3 条）

- TC-LOGIN-001 (system, P0): 用户使用正确账号密码登录成功
- TC-LOGIN-002 (system, P0): 用户使用错误密码登录失败
- TC-LOGIN-003 (system, P1): 用户使用空密码登录失败

## 补集兜底（5 条，来自 feature_id=F-LOGIN）

- TC-LOGIN-004 (integration, P1): 认证 API 返回 401
- ...

## 总计：8 条

按层级: unit=2, integration=2, system=3, acceptance=1
按优先级: P0=4, P1=3, P2=1
```

### 2.4 `qa/bugs/<bug_id>.yml`

```yaml
id: BUG-008
title: 登录后昵称未渲染
state: open
severity: high
priority: P1
related_cases: [TC-LOGIN-003]
related_requirements: [REQ-101]
feature_id: F-LOGIN

repro_steps:
  - 打开登录页
  - 输入 alice / test123
  - 点击登录
  - 观察首页右上角

expected: 显示 "alice"
actual: 显示 undefined

logs: |
  [Playwright] page.locator('[data-testid=username-display]').textContent()
  → ""

suspected_cause: |
  authenticate() 返回 {token, userId} 但缺少 nickname 字段

failure_kind: test
needs_regression: true
regression_scope_hint: [F-LOGIN, smoke]

created_at: 2026-06-16T10:02:15+08:00
created_by: qa-agent@v3.0
```

---

## 3. 影响面分析算法

### 3.1 完整流程（GitNexus 模式）

```python
def analyze_impact_gitnexus(mode: str, scope: str, config: Config) -> List[TestCase]:
    """
    规范 §8.1 的完整实现
    """
    # 步骤 1: 取本次变更 diff
    diff = git_diff('HEAD~1', 'HEAD')
    
    # 步骤 2: 调用 GitNexus 工具
    try:
        changed_symbols = mcp_gitnexus_detect_changes(diff)
    except MCPError as e:
        # §8.4: 不得静默回退
        raise ImpactAnalysisError(f"GitNexus 不可用: {e}. 请选择: 等待修复 / 切到 local 模式 / 取消")
    
    affected_symbols = []
    depth_map = {'L0': 2, 'L1': 3, 'L2': 3, 'L3': -1, 'L4': 3}
    depth = depth_map[mode]
    
    for sym in changed_symbols:
        upstream = mcp_gitnexus_impact(
            target=sym,
            direction='upstream',
            max_depth=depth
        )
        affected_symbols.extend(upstream)
    
    # 步骤 3: 反查用例库
    all_cases = load_all_cases('qa/cases')
    direct_hit = []
    
    for case in all_cases:
        if case.state not in ['active', 'review']:
            continue
        
        # 匹配 targets.symbols
        if any(sym in case.targets.symbols for sym in affected_symbols):
            direct_hit.append(case)
    
    # 步骤 4: 补集兜底
    feature_ids = set(c.feature_id for c in direct_hit)
    补集_cases = []
    
    priority_filter = {
        'L0': ['P0'],
        'L1': ['P0', 'P1'],
        'L2': ['P0', 'P1', 'P2'],
        'L3': ['P0', 'P1', 'P2', 'P3'],
        'L4': ['P0', 'P1']
    }
    
    for case in all_cases:
        if case.feature_id in feature_ids and case not in direct_hit:
            if case.priority in priority_filter[mode]:
                补集_cases.append(case)
    
    # 步骤 5: 历史 flaky / 易失败用例
    history = load_json('qa/run/history.json')
    flaky_candidates = []
    for case_id, stats in history['flaky_statistics'].items():
        if stats['flaky_score'] > 0.1:  # 10% 失败率
            case = find_case_by_id(case_id, all_cases)
            if case and case not in direct_hit and case not in 补集_cases:
                flaky_candidates.append(case)
    
    # 合并去重
    final_selection = deduplicate(direct_hit + 补集_cases + flaky_candidates)
    
    # 步骤 6: 写 selection.md
    write_selection_md(final_selection, diff, affected_symbols, mode)
    
    return final_selection
```

### 3.2 Local 模式回退

```python
def analyze_impact_local(mode: str, scope: str, config: Config) -> List[TestCase]:
    """
    规范 §8.2 的本地模式
    """
    diff_files = git_diff_name_only('HEAD~1', 'HEAD')
    all_cases = load_all_cases('qa/cases')
    
    hit_cases = []
    for case in all_cases:
        if case.state not in ['active', 'review']:
            continue
        
        # 匹配 targets.files 前缀
        for changed_file in diff_files:
            if any(changed_file.startswith(target) for target in case.targets.files):
                hit_cases.append(case)
                break
    
    # 补集兜底（同上）
    feature_ids = set(c.feature_id for c in hit_cases)
    补集 = [c for c in all_cases if c.feature_id in feature_ids and c not in hit_cases]
    
    return deduplicate(hit_cases + 补集)
```

### 3.3 用户扩充接口

```python
def apply_user_overrides(selection: List[TestCase], user_input: str) -> List[TestCase]:
    """
    规范 §8.3: 用户可追加，Agent 不可缩减
    """
    # 解析用户输入："+TC-001 +tag:smoke -TC-002"
    additions = parse_additions(user_input)  # [case_id, ...] 或 [tag:xxx]
    removals = parse_removals(user_input)
    
    # 只允许追加
    for add in additions:
        if add.startswith('tag:'):
            tag = add[4:]
            selection.extend(find_cases_by_tag(tag))
        else:
            case = find_case_by_id(add)
            if case:
                selection.append(case)
    
    # 移除项需用户二次确认
    if removals:
        print(f"警告：Agent 不得缩减执行集。你确定要移除 {removals} 吗？(yes/no)")
        # 需用户显式 yes 才执行
    
    return deduplicate(selection)
```

### 3.4 Bug 引用解析算法（P2-2）

`/qa bugfix <reference>` 中的 `<reference>` 支持多种形式，按以下顺序解析：

```python
import re

def resolve_bugfix_target(user_input: str) -> Bug:
    """
    解析 /qa bugfix 的引用参数
    """
    user_input = user_input.strip()
    
    # 优先级 1: BUG-XXX (精确匹配)
    if re.match(r'^BUG-\d+$', user_input):
        bug = load_bug(f'qa/bugs/{user_input}.yml')
        if bug is None:
            raise BugNotFound(f"未找到 {user_input}，请检查 qa/bugs/")
        return bug
    
    # 优先级 2: TC-XXX-NNN (用例 ID，反查关联 bug)
    if re.match(r'^TC-[A-Z]+-\d+$', user_input):
        case = load_case_by_id(user_input)
        bugs = find_bugs_by_case(case.id, state='open')
        if not bugs:
            raise BugNotFound(f"用例 {user_input} 当前无 open bug")
        if len(bugs) > 1:
            return prompt_user_choice(f"用例 {user_input} 有多个 open bug", bugs)
        return bugs[0]
    
    # 优先级 3: #NNN (issue 编号)
    if re.match(r'^#\d+$', user_input):
        bug = find_bug_by_issue(user_input)
        if bug is None:
            raise BugNotFound(f"未找到关联 issue {user_input} 的 bug")
        return bug
    
    # 优先级 4: 短关键词 (< 30 字符) - 模糊匹配
    if len(user_input) < 30 and not re.search(r'[。.!?！？]', user_input):
        matches = fuzzy_search_bugs(user_input)
        if not matches:
            return None  # 进入优先级 5
        if len(matches) == 1:
            return matches[0]
        return prompt_user_choice(f"找到 {len(matches)} 个匹配", matches)
    
    # 优先级 5: 自然语言描述 - 创建新 bug
    return create_bug_from_description(user_input)


def create_bug_from_description(description: str) -> Bug:
    """
    从自然语言描述创建新 bug 记录
    """
    bug_id = next_bug_id()  # BUG-XXX
    bug = Bug(
        id=bug_id,
        title=summarize_with_llm(description, max_len=80),
        state='open',
        severity='medium',  # 默认中等，用户可改
        priority='P2',
        repro_steps=[description],  # 原描述作为 repro 步骤起点
        created_by='user_via_qa_bugfix',
        created_at=datetime.now().isoformat()
    )
    save_bug(bug)
    print(f"已创建新 bug 记录：{bug_id}（请补充详情：qa/bugs/{bug_id}.yml）")
    return bug
```

#### 模糊搜索算法

```python
def fuzzy_search_bugs(keyword: str) -> List[Bug]:
    """
    在 qa/bugs/*.yml 中模糊匹配 title 和 repro_steps
    """
    matches = []
    for bug_file in glob('qa/bugs/*.yml'):
        bug = load_bug(bug_file)
        if bug.state != 'open':
            continue
        
        # 简单模糊匹配（可改用 LLM 语义比对）
        score = 0
        if keyword.lower() in bug.title.lower():
            score += 10
        if any(keyword.lower() in step.lower() for step in bug.repro_steps):
            score += 5
        
        if score > 0:
            matches.append((bug, score))
    
    matches.sort(key=lambda x: x[1], reverse=True)
    return [bug for bug, _ in matches[:5]]  # 取 top 5
```

### 3.5 需求文档自动发现算法（P0-1）

主规范 §12.1 的具体实现：

```python
from pathlib import Path
from typing import Optional, List

REQUIREMENTS_SEARCH_PATHS = [
    'docs/requirements.md',
    'docs/acceptance_criteria.md',
    'specs/*/spec.md',          # glob
    'specs/*/acceptance.feature', # glob
    'features/*.feature',         # glob
    '.bmad/output/*.md',          # glob (BMAD 默认产出)
    'REQUIREMENTS.md',
    'PRD.md',
]

def discover_requirements(config: dict) -> dict:
    """
    需求文档自动发现，三档优先级
    返回: {
        'primary': str | None,
        'acceptance': str | None,
        'specs': List[str],
        'bdd': List[str],
        'source': 'explicit' | 'convention' | 'reverse_engineered'
    }
    """
    # 优先级 1: 显式配置
    if 'requirements' in config:
        explicit = config['requirements']
        validated = validate_explicit_paths(explicit)
        if validated['primary'] is not None:
            return {**validated, 'source': 'explicit'}
    
    # 优先级 2: 约定路径自动扫描
    found = {}
    for pattern in REQUIREMENTS_SEARCH_PATHS:
        if '*' in pattern:
            matches = list(Path('.').glob(pattern))
            if matches:
                found.setdefault('specs' if 'specs' in pattern else 'bdd' if 'feature' in pattern else 'misc', []).extend(matches)
        else:
            if Path(pattern).exists():
                found.setdefault('primary' if 'requirements' in pattern.lower() or 'prd' in pattern.lower() else 'acceptance', []).append(pattern)
    
    # README 章节扫描
    readme = Path('README.md')
    if readme.exists():
        sections = extract_sections(readme, ['Requirements', '验收标准', '需求'])
        if sections:
            found.setdefault('readme_sections', []).append(sections)
    
    if found:
        return {
            'primary': found.get('primary', [None])[0],
            'acceptance': found.get('acceptance', [None])[0],
            'specs': found.get('specs', []),
            'bdd': found.get('bdd', []),
            'source': 'convention'
        }
    
    # 优先级 3: 反向梳理兜底
    return trigger_reverse_engineering(config)


def trigger_reverse_engineering(config: dict) -> dict:
    """
    无需求文档时反向梳理（兜底）
    """
    print("⚠️ 未发现需求文档，进入反向梳理流程")
    
    # 扫描代码 + 测试
    inferred = scan_code_and_infer_requirements()
    
    # 写到 docs/requirements_inferred.md
    output_path = Path('docs/requirements_inferred.md')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_inferred_requirements(inferred))
    
    # 检查签字
    signoff = Path('qa/signoff/requirements.signed')
    if not signoff.exists():
        raise SignoffRequired(
            "反向梳理产物未签字，请审阅 docs/requirements_inferred.md 后\n"
            "执行：echo 'approved' > qa/signoff/requirements.signed"
        )
    
    return {
        'primary': str(output_path),
        'acceptance': None,
        'specs': [],
        'bdd': [],
        'source': 'reverse_engineered'
    }


def handle_missing_requirements(mode: str):
    """
    主规范 §12.1 表格的代码实现
    """
    if mode in ['L0', 'L4']:
        warn("需求文档缺失，但 L0/L4 模式下不阻断")
        return 'continue'
    elif mode in ['L1', 'L2']:
        warn("需求文档缺失，进入增量补用例模式（不强制需求覆盖）")
        return 'continue'
    elif mode == 'L3':
        raise BlockedError("L3 强制要求需求文档存在")
```

### 3.6 Gatekeeper requirement_ids 校验算法（P0-3）

主规范 §3.3 的具体实现。Gatekeeper 必须独立校验 Designer+Runner 写的 `requirement_ids`：

```python
def gatekeeper_validate_requirements(config: dict, run_id: str) -> dict:
    """
    Gatekeeper 独立校验 requirement_ids 关联
    返回: {
        'consistent': bool,
        'inconsistencies': List[dict],
        'review_cases': List[str]
    }
    """
    # 步骤 1: Gatekeeper 独立读取原始需求文档（不读 Designer 摘录）
    requirements_doc = read_original_requirements(config)
    
    # 步骤 2: 加载执行用例（仅本次涉及的）
    last_run = load_json('qa/run/last.json')
    cases = [load_case(case_id) for case_id in last_run['selection']['case_ids']]
    
    inconsistencies = []
    review_cases = []
    
    for case in cases:
        # 步骤 3: LLM 独立判断"这条用例验证的是哪个需求"
        designer_says = set(case.requirement_ids)
        gatekeeper_infers = set(llm_infer_requirements(case, requirements_doc))
        
        # 步骤 4: 对比
        if designer_says != gatekeeper_infers:
            inconsistencies.append({
                'case_id': case.id,
                'designer_says': list(designer_says),
                'gatekeeper_infers': list(gatekeeper_infers),
                'missing': list(gatekeeper_infers - designer_says),
                'extra': list(designer_says - gatekeeper_infers)
            })
            
            # 标记 review
            case.state = 'review'
            save_case(case)
            review_cases.append(case.id)
    
    return {
        'consistent': len(inconsistencies) == 0,
        'inconsistencies': inconsistencies,
        'review_cases': review_cases
    }


def llm_infer_requirements(case: Case, requirements_doc: str) -> List[str]:
    """
    用 LLM 独立推断用例验证的需求 ID
    
    重要：Gatekeeper 上下文中不允许包含 Designer 的推理过程
    """
    prompt = f"""
你是 QA Gatekeeper，正在独立验证测试用例与需求的关联。

请阅读以下原始需求文档：
---
{requirements_doc}
---

以下是一条测试用例（注意：你不应该看到 Designer 的关联结果，只看用例本身的描述）：

用例 ID: {case.id}
用例标题: {case.title}
测试层级: {case.level}
前置条件: {case.preconditions}
操作步骤: {case.steps}
预期结果: {case.expected}
断言点: {case.assertions}

请独立判断：这条用例验证了上述需求文档中的哪些需求条目？

输出格式（仅 JSON）：
{{
  "requirement_ids": ["REQ-101", "REQ-102"],
  "reasoning": "简短说明"
}}
"""
    
    response = call_gatekeeper_llm(prompt)
    return response['requirement_ids']
```

#### 输出报告

校验结果写入 `release_gate_report.md`：

```markdown
## 需求关联一致性校验

总用例数：80
一致：78
不一致：2 → 已标记 state=review

### 不一致详情

#### TC-LOGIN-003

* Designer 关联：[REQ-101]
* Gatekeeper 推断：[REQ-102]
* 差异：缺少 REQ-102，多余 REQ-101
* 建议：请人工复审用例与需求关系

#### TC-LOGIN-005

* Designer 关联：[REQ-103]
* Gatekeeper 推断：[REQ-103, REQ-105]
* 差异：缺少 REQ-105
* 建议：请补充关联或确认 REQ-105 不在范围
```

#### L3 质量门规则

* 不一致用例数 = 0 → 可 PASS
* 不一致用例数 > 0 → 自动降级为 `CONDITIONAL PASS`，必须人工复审
* 不一致用例数 > 总数 30% → 自动降级为 `BLOCKED`（Designer 质量严重不达标）

---

## 4. Flaky 检测算法

### 4.1 完整流程

```python
def detect_flaky(results: RunResult, config: Config):
    """
    规范 §5.6: 仅对失败用例隔离重跑
    """
    retry_runs = config.flaky.retry_runs  # 默认 5
    history = load_json('qa/run/history.json')
    
    # 只对失败用例重跑
    failed_cases = [r for r in results.cases if r.status == 'fail']
    
    for case_result in failed_cases:
        case = load_case(case_result.case_id)
        
        # 隔离重跑 N 次
        retry_results = []
        for i in range(retry_runs):
            retry = adapter.run([case], mode='isolated', run_id=f"{results.run_id}_retry_{i}")
            retry_results.append(retry.cases[0].status)
        
        # 判定
        pass_count = retry_results.count('pass')
        fail_count = retry_results.count('fail')
        
        if pass_count == retry_runs:
            # 全 PASS → 标记 flaky 候选
            case.state = 'flaky'
            case.notes += f"\n[Flaky] 初次失败，重跑 {retry_runs} 次全 PASS"
            save_case(case)
            
            # 更新 history.json 统计
            update_flaky_statistics(history, case.id, pass_count=retry_runs, fail_count=1)
        else:
            # 仍有失败 → 真失败，不是 flaky
            pass
    
    save_json('qa/run/history.json', history)
```

### 4.2 滚动窗口更新

```python
def update_flaky_statistics(history: dict, case_id: str, pass_count: int, fail_count: int):
    """
    滚动窗口 50 runs
    """
    if case_id not in history['flaky_statistics']:
        history['flaky_statistics'][case_id] = {
            'total_runs': 0,
            'pass_count': 0,
            'fail_count': 0,
            'flaky_score': 0.0,
            'last_flaky_at': None
        }
    
    stats = history['flaky_statistics'][case_id]
    stats['total_runs'] += (pass_count + fail_count)
    stats['pass_count'] += pass_count
    stats['fail_count'] += fail_count
    
    # 滚动窗口：超过 50 runs 时丢弃旧数据（简化：全局计数，实际应按时间戳滚动）
    if stats['total_runs'] > 50:
        stats['total_runs'] = 50
        stats['pass_count'] = int(stats['pass_count'] * 50 / stats['total_runs'])
        stats['fail_count'] = 50 - stats['pass_count']
    
    stats['flaky_score'] = stats['fail_count'] / stats['total_runs']
    stats['last_flaky_at'] = datetime.now().isoformat()
```

---

## 5. Mutation 抽样算法

### 5.1 完整流程

```python
def run_mutation_sampling(config: Config):
    """
    规范 §5.6: 仅 L3 + 仅 diff + 文件数 ≤ 20
    """
    # 步骤 1: 取本次 diff 涉及的源文件
    diff_files = git_diff_name_only('HEAD~1', 'HEAD', filter_pattern='*.{py,js,ts,tsx}')
    diff_files = [f for f in diff_files if not f.startswith('tests/')]  # 排除测试文件
    
    # 步骤 2: 超过 20 个文件时抽样
    if len(diff_files) > 20:
        # 按本次 diff 修改行数降序排序
        files_with_lines = []
        for f in diff_files:
            lines_changed = git_diff_stat(f, 'HEAD~1', 'HEAD')
            files_with_lines.append((f, lines_changed))
        
        files_with_lines.sort(key=lambda x: x[1], reverse=True)
        selected_files = [f for f, _ in files_with_lines[:20]]
    else:
        selected_files = diff_files
    
    # 步骤 3: 调用 mutation 工具
    framework = config.frameworks.get('mutation', 'mutmut')  # mutmut / stryker
    
    if framework == 'mutmut':
        # mutmut run --paths-to-mutate=src/auth.py,src/login.py
        paths = ','.join(selected_files)
        result = subprocess.run(
            ['mutmut', 'run', f'--paths-to-mutate={paths}'],
            capture_output=True
        )
    elif framework == 'stryker':
        # stryker run --mutate src/auth.ts,src/login.ts
        result = subprocess.run(
            ['npx', 'stryker', 'run', '--mutate', ','.join(selected_files)],
            capture_output=True
        )
    
    # 步骤 4: 解析结果
    mutation_score = parse_mutation_report(result.stdout, framework)
    
    # 步骤 5: 写入报告
    report = {
        'run_id': current_run_id(),
        'selected_files': selected_files,
        'total_mutants': mutation_score['total'],
        'killed': mutation_score['killed'],
        'survived': mutation_score['survived'],
        'score': mutation_score['killed'] / mutation_score['total'],
        'threshold': config.mutation.threshold  # 默认 0.75
    }
    
    save_json('qa/run/mutation_report.json', report)
    
    # 步骤 6: 校验阈值
    if report['score'] < config.mutation.threshold:
        print(f"警告：Mutation 分数 {report['score']:.2%} 低于阈值 {config.mutation.threshold:.2%}")
        print(f"存活变异体：{mutation_score['survived']} 个")
```

---

## 6. 提示词框架

### 6.1 DesignerRunner System Prompt

```text
你是 AI Test Engineer Agent 的 DesignerRunner 角色（v3.0 Solo Edition）。

你的职责：
1. 测试设计：基于需求生成或更新测试用例（YAML 格式）
2. 脚本生成：调用 Adapter 生成可执行测试脚本
3. 执行：调用 Adapter 运行测试
4. 收集失败：失败用例写入 qa/bugs/<id>.yml

## 红线（违反即视为失败）

1. 不得删除失败测试来伪造通过
2. 不得降低断言标准来伪造通过
3. 不得跳过失败测试但仍宣布完成
4. 不得只运行程序不做断言
5. 不得只手动体验一次就认为完成
6. 不得自行降档运行模式
7. 不得自行缩减用例选择范围

## 输入

- 需求文档：docs/requirements.md、docs/acceptance_criteria.md
- 架构设计：docs/architecture.md（可选）
- 已有用例库：qa/cases/
- 运行模式：{mode}
- 执行范围：{scope}

## 输出

- 用例 YAML：qa/cases/<feature>/<case>.yml
- 测试脚本：tests/ 目录下对应文件
- 执行结果：qa/run/last.json
- 缺陷报告：qa/bugs/<id>.yml

## 用例 YAML Schema

```yaml
id: TC-{FEATURE}-{NUM}
title: 简短描述（一行）
state: active | review | stale | flaky | retired
feature_id: F-{FEATURE}
requirement_ids: [REQ-xxx]
level: unit | integration | system | acceptance | smoke
priority: P0 | P1 | P2 | P3

test_data:
  username: alice
  password: "${env:TEST_PASSWORD}"  # 机密必须用引用

steps: [...]
expected: [...]

assertions:
  - selector: "[data-testid=username-display]"
    equals: "alice"

automation:
  status: implemented | scaffolded | manual
  framework: playwright | vitest | pytest
  file: tests/system/login.spec.ts
  test_id: login_with_valid_credentials

targets:  # 由 Adapter 自动维护，你不填
  files: []
  symbols: []
  generated_by: ""
  generated_at: ""

regression_tags: [auth, smoke]
notes: ""
```

## 工作流

1. 读取需求和已有用例库
2. {mode} 模式下的设计策略：
   - L0: 跳过设计
   - L1: 增量补该功能用例
   - L2: 复核该模块所有用例完整性
   - L3: 校验需求追踪矩阵 100% 覆盖
   - L4: 跳过设计
3. 调用影响面分析（Core 已完成，你读取 selection.md）
4. 对选中用例调用 Adapter.generate() 补齐脚本
5. 调用 Adapter.run(selection, mode)
6. 解析结果，失败用例写 qa/bugs/<id>.yml
7. 写 qa/run/last.json

## 关键约束

- 凭据不得明文写入 test_data，必须用 ${env:NAME} 或 ${secret:path.key}
- automation.file 必须指向实际生成的文件路径
- 失败用例必须生成 bug YAML，不能只打印到终端
- 不得修改 Gatekeeper 的判定结果
```

### 6.2 DesignerRunner User Prompt（L1 示例）

```text
## 任务

以 L1 模式执行测试流程，范围：feature 登录

## 上下文

需求文档：docs/requirements.md
已有用例库：qa/cases/F-LOGIN/
运行模式：L1
执行范围：F-LOGIN

## 步骤

1. 读取 docs/requirements.md 中关于登录功能的需求
2. 读取 qa/cases/F-LOGIN/ 下已有用例
3. 检查是否有新需求未覆盖 → 增量补用例
4. 读取 qa/run/selection.md（影响面分析结果）
5. 对选中用例调用 Adapter.generate()
6. 调用 Adapter.run()
7. 收集失败用例，写 qa/bugs/
8. 写 qa/run/last.json

## 配置

.qa-agent.yml:
```yaml
project_type: web
frameworks:
  unit: vitest
  e2e: playwright
impact_analysis: gitnexus
mode_limits:
  L1: 80
```

开始执行。
```

### 6.3 Gatekeeper System Prompt（rev1：增加 requirement_ids 校验 P0-3）

```text
你是 AI Test Engineer Agent 的 Gatekeeper 角色（v3.0-rev1 Solo Edition）。

你的职责：独立判定测试结论（PASS / CONDITIONAL PASS / FAIL / BLOCKED）。

## 独立性约束（强制）

**你不能看到 DesignerRunner 的推理过程。** 你只能基于：

1. 原始需求文档（docs/）—— 你必须独立读取，不 trust Designer 的摘录
2. 用例库（qa/cases/）
3. 执行结果（qa/run/last.json）
4. Waivers（qa/waivers.yml）

来做判定。

## 强制校验步骤（按顺序执行）

### 步骤 1：独立读取原始需求

执行 `read_original_requirements()`，从 docs/ 目录独立读取需求文档。
**禁止**直接使用 Designer 写入用例 YAML 中的 requirement_ids 关联。

### 步骤 2：LLM 独立推断 requirement_ids（P0-3）

对本次执行的每条用例：

1. 读取用例的 title / steps / assertions（不读 requirement_ids 字段）
2. 独立判断"这条用例验证了哪些需求"
3. 与 case.requirement_ids 对比

不一致时：
- 标记 case.state = 'review'
- 写入 inconsistencies 列表到 release_gate_report.md
- 不一致用例数 > 总数 30% → 自动 BLOCKED

### 步骤 3：执行结果校验

按下文判定标准给出结论。

### 步骤 4：必填字段

- "未能验证的事项"（不允许空，无内容时显式声明"审查不足"）
- "建议人工复核的项"（P0 用例、安全用例、影响支付/权限/数据保存的用例）

## 判定标准（仅 L3 适用完整质量门）

### PASS

- 全部 P0 用例通过
- 核心冒烟测试通过
- 覆盖率达标
- 无 active flaky 用例
- manual 用例已签字
- waivers.yml 无过期项
- requirement_ids 一致性校验：不一致 = 0

### CONDITIONAL PASS

- P0 全通过，但存在 P1/P2 失败 + 有 waiver
- 覆盖率低于阈值但 ≥ 最低线
- requirement_ids 不一致 > 0 但 < 30%（必须人工复审）
- L3 维度切片：跳过部分非功能维度（必须在 uncovered_dimensions 登记）

### FAIL

- 任何 P0 用例失败
- 核心冒烟失败
- 安全用例 critical/high 失败

### BLOCKED

- 项目无法启动
- 环境依赖缺失（环境失败 ≠ 测试失败，参见 §19）
- manual 用例无人签字
- waivers 过期或缺 approved_by
- requirement_ids 不一致 ≥ 30%（Designer 质量严重不达标）
- 反向梳理产物未签字（qa/signoff/requirements.signed 不存在）

## 输出格式

### 报告结构（final_test_report.md）

```markdown
# 测试报告

运行模式: {mode}
运行 ID: {run_id}
开始时间: {start_time}
结束时间: {end_time}
耗时: {duration}

## 执行统计

总数: {total}
通过: {pass}
失败: {fail}
跳过: {skip}
Flaky: {flaky}

按层级:
- 单元测试: {unit_pass}/{unit_total}
- 集成测试: {integration_pass}/{integration_total}
- 系统测试: {system_pass}/{system_total}
- 验收测试: {acceptance_pass}/{acceptance_total}

## requirement_ids 一致性校验（P0-3）

总用例数: {total}
一致: {consistent}
不一致: {inconsistent} → 已标记 state=review

[如有不一致，列出详情]

## 失败用例

- BUG-008: 登录后昵称未渲染 (TC-LOGIN-003, severity=high)
- BUG-009: 登录超时 (TC-LOGIN-004, severity=medium)

## 未覆盖需求

- REQ-105: 记住密码功能（未实现）

## 未能验证的事项（必填，不允许空）

- 性能测试：未在 L1 模式下执行
- 兼容性：未测试 Safari

## 建议人工复核的项

- TC-LOGIN-001（P0 + 涉及鉴权，建议人工复核）

## 质量门判定（仅 L3）

结论: {PASS | CONDITIONAL PASS | FAIL | BLOCKED}
理由: ...
```

## 关键约束

- 必须独立从原始需求摘录条款，不 trust DesignerRunner 的关联关系
- "未能验证的事项" 不允许为空
- L0/L1/L4 不输出质量门判定（仅 L3）
- 不得修改 qa/run/last.json（只读）
- L0/L4 默认走算法判定，不调 LLM（成本优化 P1-1）
- 判定结果可缓存（基于输入 hash），相同输入返回相同结论
```

### 6.4 Gatekeeper User Prompt（L3 示例）

```text
## 任务

以 Gatekeeper 角色判定本次 L3 运行的质量门结论。

## 输入

- qa/run/last.json（执行结果）
- qa/cases/（用例库）
- docs/requirements.md（原始需求）
- qa/waivers.yml（风险接受清单）
- .qa-agent.yml（配置）

## 步骤

1. 加载 qa/run/last.json
2. **独立**从 docs/requirements.md 摘录需求条款
3. 检查需求追踪矩阵：所有需求是否有对应用例？
4. 检查执行结果：P0 全通过？
5. 检查 waivers.yml：有无过期项？
6. 输出 final_test_report.md
7. 输出 release_gate_report.md（仅 L3）

## 配置

.qa-agent.yml:
```yaml
coverage_thresholds:
  p0_line: 0.80
waivers:
  forbid_security_waiver_severity: [critical, high]
```

开始判定。
```

### 6.5 对抗式 Review Prompt

```text
你是 Gatekeeper 的对抗式 reviewer（独立上下文）。

目标：尝试构造"实现错误但用例仍 PASS"的反例。

## 输入

- 用例 YAML: {case_yaml}
- 实现代码片段: {implementation_snippet}

## 输出格式

JSON 数组，每个反例：

```json
[
  {
    "反例": "如果 authenticate() 返回 {token: null, userId: 123}，用例仍会 PASS",
    "为什么用例没抓住": "用例只断言了 userId 存在，没断言 token 非空",
    "建议补强": "增加断言：assert response.token != null"
  }
]
```

## 约束

- 反例必须是**代码层面可构造**的（不是需求层面的缺失）
- 如果找不到反例，返回空数组 []
- 不要假设需求错误（需求是对的，只看用例能否抓住实现 bug）
```

### 6.6 非功能测试调度提示词（P0-5）

L3 模式下，DesignerRunner 在执行非功能测试前先调度决策：

```text
你是 DesignerRunner 的非功能测试调度子角色。

## 输入

- .qa-agent.yml 中 nonfunctional 配置
- 命令行参数（--with-* 临时开启项）
- 当前模式（L3）
- 项目类型（web / backend / mobile / ...）
- 当前 git diff（确定是否触及性能敏感代码）

## 决策流程

### 步骤 1: 默认开启项（成本低）
- dependency_audit: 始终运行（npm audit / pip-audit / cargo audit）
- static_security: 始终运行（bandit / semgrep / eslint-plugin-security）

### 步骤 2: 默认关闭项（按配置/参数开启）
检查每项是否需要执行：
- dynamic_security_scan: 命令行 --with-dynamic-security 或 config.enabled=true
- performance: 命令行 --with-performance 或 config.enabled=true
- compatibility: 命令行 --with-compatibility 或 config.enabled=true
- 或 --with-all-nonfunctional 一次开启所有

### 步骤 3: 环境校验（高成本测试前）
- dynamic_security_scan / performance：必须命中隔离环境，否则中止
- compatibility：必须有矩阵配置（matrix: [chromium, firefox]）

### 步骤 4: L3 维度切片
- 用户用 --skip 显式跳过的维度，记入 release_gate_report 的 uncovered_dimensions

## 输出（JSON）

{
  "scheduled": [
    {"type": "dependency_audit", "tool": "npm audit", "estimated_minutes": 0.5},
    {"type": "static_security", "tool": "bandit", "estimated_minutes": 2}
  ],
  "skipped": [
    {"type": "performance", "reason": "默认关闭，未通过命令行开启"},
    {"type": "compatibility", "reason": "用户显式 --skip compatibility"}
  ],
  "blocked": [
    {"type": "dynamic_security_scan", "reason": "目标环境未隔离，命中生产标识"}
  ]
}

## 约束

- skipped 必须给出明确原因
- blocked 必须列出阻断原因（不允许悄悄跳过）
- 总耗时预估必须报告（单位：分钟）
```

---

## 7. Adapter 插件系统

### 7.1 接口定义

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass

@dataclass
class ProjectFingerprint:
    project_type: str  # web | backend | fullstack | mobile | desktop | game
    language: str
    frameworks: Dict[str, str]  # {'unit': 'vitest', 'e2e': 'playwright'}
    capabilities: Dict[str, bool]
    paths: Dict[str, str]
    run_commands: Dict[str, str]

@dataclass
class TestCase:
    # ... (参见规范 §9.2)
    pass

@dataclass
class RunResult:
    run_id: str
    total: int
    pass_: int
    fail: int
    skip: int
    cases: List[dict]

class TestAdapter(ABC):
    @abstractmethod
    def detect(self) -> ProjectFingerprint:
        """
        识别项目类型、框架、capabilities
        """
        pass
    
    @abstractmethod
    def scaffold(self, plan: dict) -> None:
        """
        创建/补齐测试目录、配置
        """
        pass
    
    @abstractmethod
    def generate(self, case: TestCase) -> str:
        """
        生成可执行测试脚本，返回文件路径
        """
        pass
    
    @abstractmethod
    def index_targets(self) -> Dict[str, Any]:
        """
        自动维护用例 targets.{files,symbols}
        返回: {case_id: {files: [...], symbols: [...]}}
        """
        pass
    
    @abstractmethod
    def run(self, selection: List[TestCase], mode: str) -> RunResult:
        """
        执行用例集合
        """
        pass
    
    @abstractmethod
    def parse_report(self, raw_output: str) -> RunResult:
        """
        归一化结果
        """
        pass
    
    @abstractmethod
    def collect_artifacts(self, run_id: str) -> Dict[str, Any]:
        """
        收集失败截图、日志、覆盖率
        返回: {screenshots: [...], logs: [...], coverage: {...}}
        """
        pass
    
    @abstractmethod
    def classify_failure(self, case_result: dict) -> str:
        """
        区分 env_failure / test_failure / unknown
        """
        pass
```

### 7.2 Web Adapter 实现骨架

```python
# adapters/web/adapter.py

import os
import json
import subprocess
from pathlib import Path
from qa_core.adapter import TestAdapter, ProjectFingerprint, TestCase, RunResult

class WebAdapter(TestAdapter):
    def detect(self) -> ProjectFingerprint:
        """
        检测 Web 项目
        """
        if not (Path('package.json').exists()):
            raise NotWebProject()
        
        pkg = json.load(open('package.json'))
        
        # 识别框架
        frameworks = {}
        if 'vitest' in pkg.get('devDependencies', {}):
            frameworks['unit'] = 'vitest'
        if 'playwright' in pkg.get('devDependencies', {}):
            frameworks['e2e'] = 'playwright'
        
        # Capabilities
        capabilities = {
            'headless': True,
            'parallel': True,
            'coverage': 'vitest' in frameworks.values(),
            'mutation': os.path.exists('stryker.config.js'),
            'screenshot': 'playwright' in frameworks.values()
        }
        
        return ProjectFingerprint(
            project_type='web',
            language='typescript',  # 简化：从 tsconfig.json 判断
            frameworks=frameworks,
            capabilities=capabilities,
            paths={'tests': 'tests', 'src': 'src'},
            run_commands={
                'unit': 'npm run test:unit',
                'e2e': 'npx playwright test'
            }
        )
    
    def generate(self, case: TestCase) -> str:
        """
        生成 Playwright 测试脚本
        """
        if case.level in ['unit', 'integration']:
            return self._generate_vitest(case)
        elif case.level in ['system', 'acceptance']:
            return self._generate_playwright(case)
    
    def _generate_playwright(self, case: TestCase) -> str:
        """
        Playwright 脚本生成
        """
        template = f"""
import {{ test, expect }} from '@playwright/test';

test('{case.title}', async ({{ page }}) => {{
  // Preconditions
  {self._render_preconditions(case)}
  
  // Steps
  {self._render_steps(case)}
  
  // Assertions
  {self._render_assertions(case)}
}});
"""
        file_path = f"tests/{case.level}/{case.feature_id.lower()}.spec.ts"
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(template)
        
        return file_path
    
    def run(self, selection: List[TestCase], mode: str) -> RunResult:
        """
        执行测试
        """
        # 按 level 分组
        by_level = {}
        for case in selection:
            by_level.setdefault(case.level, []).append(case)
        
        all_results = []
        
        # 单元/集成 → vitest
        if 'unit' in by_level or 'integration' in by_level:
            result = subprocess.run(
                ['npm', 'run', 'test:unit'],
                capture_output=True,
                text=True
            )
            all_results.append(self.parse_report(result.stdout))
        
        # 系统/验收 → playwright
        if 'system' in by_level or 'acceptance' in by_level:
            result = subprocess.run(
                ['npx', 'playwright', 'test'],
                capture_output=True,
                text=True
            )
            all_results.append(self.parse_report(result.stdout))
        
        return self._merge_results(all_results)
    
    def classify_failure(self, case_result: dict) -> str:
        """
        规范 §19.2: 环境失败 vs 测试失败
        """
        error_msg = case_result.get('error', '')
        
        # 环境失败正则
        env_patterns = [
            r'ECONNREFUSED',
            r'port.*already in use',
            r'Cannot find module',
            r'docker.*not running',
            r'database.*connection failed'
        ]
        
        import re
        for pattern in env_patterns:
            if re.search(pattern, error_msg, re.IGNORECASE):
                return 'env'
        
        return 'test'
```

### 7.3 Adapter 发现与加载（rev1：增加 Generic 兜底）

```python
# qa_core/adapter_loader.py

import importlib
from pathlib import Path
from typing import Optional
from qa_core.adapter import TestAdapter

def load_adapter(project_type: str) -> Optional[TestAdapter]:
    """
    动态加载 Adapter
    """
    adapter_dir = Path(__file__).parent.parent / 'adapters' / project_type
    
    if not adapter_dir.exists():
        return None
    
    # 动态 import
    module = importlib.import_module(f'adapters.{project_type}.adapter')
    adapter_class = getattr(module, f'{project_type.capitalize()}Adapter')
    
    return adapter_class()

def auto_detect_adapter(config: dict) -> TestAdapter:
    """
    自动检测项目类型并加载对应 Adapter
    P0-4: 失败时回退到 Generic Adapter（不是 raise）
    """
    # 优先级 1: 配置显式指定
    if config.get('project_type'):
        adapter = load_adapter(config['project_type'])
        if adapter:
            return adapter
    
    # 优先级 2: 自动尝试已知类型
    candidates = ['web', 'backend', 'mobile', 'desktop', 'game']
    
    for project_type in candidates:
        adapter = load_adapter(project_type)
        if adapter:
            try:
                fingerprint = adapter.detect()
                print(f"检测到项目类型: {fingerprint.project_type}")
                return adapter
            except Exception:
                continue
    
    # 优先级 3: Generic Adapter 兜底（P0-4）
    print("⚠️ 无法识别项目类型，使用 Generic Adapter（请在 .qa-agent.yml 配置 test_command）")
    return load_adapter('generic')
```

### 7.4 Generic Adapter 实现骨架（P0-4）

兜底实现，覆盖 Rust / Go / C++ / 嵌入式 / 文档生成等非标准项目。

```python
# adapters/generic/adapter.py

import os
import re
import subprocess
from pathlib import Path
from qa_core.adapter import TestAdapter, ProjectFingerprint, TestCase, RunResult

class GenericAdapter(TestAdapter):
    """
    通用兜底 Adapter
    适用：Rust CLI / Go 微服务非标准布局 / C++ 嵌入式 / 文档生成器
    限制：不能自动生成测试脚本，依赖用户预先编写
    """
    
    def detect(self) -> ProjectFingerprint:
        """
        从 .qa-agent.yml 读取配置（不自动推断框架）
        """
        config = load_config('.qa-agent.yml')
        
        if config.get('project_type') != 'generic':
            raise NotGenericProject()
        
        if not config.get('test_command'):
            raise ConfigError(
                "Generic Adapter 必须在 .qa-agent.yml 配置 test_command\n"
                "示例：\n"
                "  project_type: generic\n"
                "  test_command: cargo test"
            )
        
        return ProjectFingerprint(
            project_type='generic',
            language=config.get('language', 'unknown'),
            frameworks={'custom': config['test_command']},
            capabilities={
                'headless': True,                    # 通常 CLI/工具默认无头
                'parallel': False,                   # 保守
                'coverage': False,                   # 不自动收集
                'mutation': False,                   # 不支持
                'screenshot': False,                 # 无 GUI
                'failure_classification': False,     # 无法精细分类
                'auto_generate': False               # 不能自动生成脚本
            },
            paths={
                'tests': config.get('test_dir', 'tests'),
                'src': config.get('src_dir', 'src')
            },
            run_commands={
                'test': config['test_command'],
                'build': config.get('build_command'),
                'lint': config.get('lint_command')
            }
        )
    
    def scaffold(self, plan: dict) -> None:
        """
        Generic 不创建测试文件，仅创建 qa/ 目录结构
        """
        for d in ['qa/cases', 'qa/bugs', 'qa/run', 'qa/feedback']:
            Path(d).mkdir(parents=True, exist_ok=True)
        
        # 在 README 提示用户：测试文件需自己维护
        Path('qa/GENERIC_NOTE.md').write_text(
            "# Generic Adapter Note\n\n"
            "本项目使用 Generic Adapter，自动化测试脚本由你自己维护。\n"
            "qa/cases/<feature>/<case>.yml 中的 automation.file 需指向你已有的测试文件。\n"
        )
    
    def generate(self, case: TestCase) -> str:
        """
        Generic 不能自动生成脚本
        """
        raise NotImplementedError(
            f"Generic Adapter 不支持自动生成测试脚本。\n"
            f"请手动编写测试，并在 {case.id}.yml 中填写 automation.file 指向脚本位置。\n"
            f"将 case.automation.status 改为 'manual' 或 'scaffolded'"
        )
    
    def index_targets(self) -> dict:
        """
        Generic 无法自动索引 targets（无 LSP/AST），使用文件名前缀启发式
        """
        result = {}
        for case in load_all_cases():
            if not case.automation.file:
                continue
            
            # 启发式：从测试文件名推断被测代码
            test_path = Path(case.automation.file)
            stem = test_path.stem.replace('test_', '').replace('_test', '')
            
            # 在 src/ 下查找同名文件
            candidates = list(Path('src').rglob(f'{stem}.*'))
            
            result[case.id] = {
                'files': [str(c) for c in candidates],
                'symbols': [],  # Generic 无法静态分析符号
                'generated_by': 'generic_adapter@0.1.0',
                'generated_at': datetime.now().isoformat()
            }
        return result
    
    def run(self, selection: list, mode: str) -> RunResult:
        """
        Generic 调用用户配置的测试命令，解析输出
        """
        config = load_config('.qa-agent.yml')
        cmd = config['test_command']
        output_format = config.get('test_output_format', 'plain')
        
        # 拼接用例过滤参数（如果工具支持）
        case_ids = [c.id for c in selection]
        
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=mode_timeout_seconds(mode)
        )
        
        # 解析输出
        return self.parse_report(result.stdout, output_format, selection)
    
    def parse_report(self, raw_output: str, format: str = 'plain', selection: list = None) -> RunResult:
        """
        支持 TAP / JUnit XML / 纯文本三种格式
        """
        if format == 'tap':
            return parse_tap(raw_output)
        elif format == 'junit_xml':
            return parse_junit_xml(raw_output)
        else:
            # 纯文本启发式：找 PASS / FAIL / OK / NOT OK 关键词
            return parse_plain_text(raw_output, selection)
    
    def collect_artifacts(self, run_id: str) -> dict:
        """
        Generic 仅收集 stdout/stderr 日志
        """
        return {
            'logs': [f'qa/run/{run_id}/output.log'],
            'screenshots': [],
            'videos': [],
            'coverage': None,
            'mutation_report': None
        }
    
    def classify_failure(self, case_result: dict) -> str:
        """
        Generic 无法精细分类，全部视为 test
        """
        return 'test'
```

#### Generic 配置示例

```yaml
# .qa-agent.yml

project_type: generic
language: rust

# 必填
test_command: cargo test --no-fail-fast

# 可选（提升体验）
test_output_format: junit_xml          # tap | junit_xml | plain
test_dir: tests/
src_dir: src/
build_command: cargo build --release
lint_command: cargo clippy

# 用例 YAML 中的 automation:
#   status: manual            # 手动维护
#   framework: cargo          # 任意标识
#   file: tests/integration.rs
#   test_id: test_authenticate
```

#### 报告标注

使用 Generic Adapter 时，所有报告头部加显著提示：

```python
GENERIC_REPORT_HEADER = """
> ℹ️ **本项目使用 Generic Adapter**
> 
> 限制：
> - 测试脚本由人工维护（无法自动生成）
> - 影响面分析降级为 local 模式（基于文件名前缀）
> - 无 mutation / 覆盖率 / 失败分类
> 
> 建议：长期接入时考虑开发专用 Adapter
"""
```

---

## 8. 状态恢复与容错

### 8.1 中断恢复机制

```python
def resume_from_checkpoint(run_id: str) -> RunResult:
    """
    从 qa/run/last.json 恢复执行
    """
    last_run = load_json('qa/run/last.json')
    
    if last_run['run_id'] != run_id:
        raise ValueError(f"Run ID 不匹配: 期望 {run_id}, 实际 {last_run['run_id']}")
    
    # 检查执行阶段
    if last_run.get('execution', {}).get('end_time'):
        # 已完成执行，跳到 Gatekeeper
        print("执行已完成，恢复 Gatekeeper 判定...")
        return resume_gatekeeper(run_id)
    
    # 未完成执行，恢复 DesignerRunner
    selection = [find_case_by_id(cid) for cid in last_run['selection']['case_ids']]
    executed_cases = [c['case_id'] for c in last_run['execution'].get('results', {}).get('cases', [])]
    
    # 过滤已执行用例
    remaining = [c for c in selection if c.id not in executed_cases]
    
    print(f"恢复执行：剩余 {len(remaining)} 条用例")
    
    # 继续执行
    results = adapter.run(remaining, last_run['mode'])
    
    # 合并结果
    merged = merge_run_results(last_run['execution'], results)
    last_run['execution'] = merged
    save_json('qa/run/last.json', last_run)
    
    return results
```

### 8.2 并发控制（文件锁）

```python
import fcntl
from contextlib import contextmanager

@contextmanager
def acquire_case_lock(case_id: str):
    """
    防止同时写同一用例文件
    """
    lock_file = Path(f'qa/.locks/{case_id}.lock')
    lock_file.parent.mkdir(exist_ok=True)
    
    with open(lock_file, 'w') as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            lock_file.unlink(missing_ok=True)

# 使用示例
def save_case(case: TestCase):
    with acquire_case_lock(case.id):
        yaml.dump(case.to_dict(), open(f'qa/cases/{case.feature_id}/{case.id}.yml', 'w'))
```

### 8.3 失败重试策略

```python
def run_with_retry(func, max_attempts=3, backoff=2):
    """
    LLM 调用、GitNexus 调用的重试装饰器
    """
    import time
    
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as e:
            if attempt == max_attempts:
                raise
            
            wait_time = backoff ** attempt
            print(f"第 {attempt} 次失败: {e}. {wait_time} 秒后重试...")
            time.sleep(wait_time)
```

### 8.4 检查点恢复机制（P1-4）

L3 完整跑可能 30 分钟–2 小时，必须支持中断后恢复。

#### Phase 划分

```python
L3_PHASES = [
    (1, 'designer', 'DesignerRunner 生成/更新用例'),
    (2, 'unit_test', '单元测试'),
    (3, 'integration_test', '集成测试'),
    (4, 'system_test', '系统测试'),
    (5, 'acceptance_test', '验收测试'),
    (6, 'nonfunctional', '非功能测试（性能/安全/兼容）'),
    (7, 'mutation', 'Mutation 抽样'),
    (8, 'gatekeeper', 'Gatekeeper 判定'),
]
```

#### 检查点写入

每个 phase 完成后立即持久化：

```python
def save_checkpoint(run_id: str, phase: int, phase_name: str, results: dict):
    """
    Phase 完成后写检查点
    """
    last_run = load_json('qa/run/last.json')
    
    last_run['checkpoint']['current_phase'] = phase + 1  # 下一个 phase
    last_run['checkpoint']['completed_phases'].append({
        'phase': phase,
        'name': phase_name,
        'completed_at': datetime.now().isoformat(),
        'duration_s': results.get('duration_s', 0)
    })
    last_run['checkpoint']['git_head'] = git_rev_parse('HEAD')
    last_run['checkpoint']['git_diff_hash'] = compute_diff_hash()
    last_run['checkpoint']['expires_at'] = (datetime.now() + timedelta(hours=24)).isoformat()
    last_run['execution']['results_by_phase'][phase_name] = results
    last_run['status'] = 'running'
    
    atomic_write_json('qa/run/last.json', last_run)
```

#### 中断处理

```python
import signal

def install_interrupt_handler(run_id: str):
    """
    SIGINT (Ctrl+C) 处理：保存检查点后退出
    """
    def handler(signum, frame):
        last_run = load_json('qa/run/last.json')
        last_run['status'] = 'paused'
        last_run['paused_at'] = datetime.now().isoformat()
        atomic_write_json('qa/run/last.json', last_run)
        
        print("\n[Agent] 中断信号收到，已保存检查点")
        print(f"[Agent] 已完成: {[p['name'] for p in last_run['checkpoint']['completed_phases']]}")
        print(f"[Agent] 下次运行 /qa resume 可从此处继续")
        sys.exit(130)  # 130 = SIGINT 退出码
    
    signal.signal(signal.SIGINT, handler)
```

#### 恢复执行

```python
def resume_l3_run() -> RunResult:
    """
    /qa resume 实现
    """
    last_run = load_json('qa/run/last.json')
    
    # 校验 1: 是否有未完成的运行
    if last_run.get('status') not in ('paused', 'running'):
        raise NoResumableRun("没有可恢复的运行（status 非 paused/running）")
    
    # 校验 2: 是否过期
    expires_at = datetime.fromisoformat(last_run['checkpoint']['expires_at'])
    if datetime.now() > expires_at:
        raise CheckpointExpired(
            f"检查点已过期（{expires_at}）。请重新运行 /qa release"
        )
    
    # 校验 3: git 是否变化
    current_head = git_rev_parse('HEAD')
    saved_head = last_run['checkpoint']['git_head']
    
    if current_head != saved_head:
        print(f"⚠️ git HEAD 已变化（{saved_head[:8]} → {current_head[:8]}）")
        print(f"已完成 phase 的结果可能不再代表当前代码状态。")
        choice = prompt("是否仍要继续？(yes / 重新开始 / 取消)")
        
        if choice == '重新开始':
            return start_fresh_l3()
        elif choice == '取消':
            sys.exit(0)
        # else: 继续
    
    # 显示状态
    print(f"\n[Agent] 检测到未完成的 L3 运行（{last_run['run_id']}）")
    print(f"[Agent] 已完成阶段：")
    for p in last_run['checkpoint']['completed_phases']:
        print(f"  ✓ Phase {p['phase']}: {p['name']}（耗时 {p['duration_s']}s）")
    
    next_phase = last_run['checkpoint']['current_phase']
    pending = [p for p in L3_PHASES if p[0] >= next_phase]
    print(f"[Agent] 待执行阶段：")
    for phase, name, desc in pending:
        print(f"  ○ Phase {phase}: {desc}")
    
    if not confirm("是否继续？"):
        return None
    
    # 从 next_phase 继续执行
    for phase, name, desc in pending:
        results = execute_phase(phase, name, last_run)
        save_checkpoint(last_run['run_id'], phase, name, results)
    
    # 全部完成
    last_run['status'] = 'completed'
    atomic_write_json('qa/run/last.json', last_run)
    return finalize_run(last_run['run_id'])
```

#### 限制

* 仅 L3 支持检查点恢复（其他模式耗时短，重跑成本低）
* 检查点 24 小时内有效
* git 大幅变化时警告并提供"重新开始"选项

---

**v3.0 实现更新（2026-06-18）**：

1. **智能默认恢复**：检测到 checkpoint 时自动恢复（不再需要 `--resume` 参数），使用 `--force-new` 强制重新开始

2. **Baseline 管理机制**：每次测试执行后（任何模式）自动更新 `qa/run/baseline.json`，记录用例规模和历史，支持累积和时效性检查

3. **L3 断点恢复实现（Phase 2 完整版）**：
   - 精确 Phase 跳转：`_run_l3(skip_phases=[1,2,3])` 跳过已完成 Phase
   - 结果复用：`cached_results={1: {...}, 2: {...}}` 避免重复执行
   - 从磁盘加载用例：`_load_designed_cases_from_disk()` 跳过 Designer 时使用
   - Phase 2-7 跳过时从缓存加载 failures/score

4. **L1/L2/L4 断点恢复**：
   - `_resume_simple_mode_from_checkpoint()` 统一处理
   - Designer 完成 + Execute 完成 → `_run_gatekeeper_only()` 仅判定
   - Designer 完成 + Execute 未完成 → 从 Execute 继续
   - Designer 未完成 → 重新开始

**核心 API**：

```python
# L3 精确跳转
_run_l3(run_id, impact_result, skip_phases=[1,2,3], cached_results={...})

# L1/L2/L4 恢复
_resume_simple_mode_from_checkpoint(run_id, mode, last_run, selection, impact)

# 仅 Gatekeeper
_run_gatekeeper_only(run_id, mode, last_run)
```

**详细说明**：参见 [BASELINE_AND_CHECKPOINT.md](BASELINE_AND_CHECKPOINT.md)

---

### 8.5 Mutation 工具降级算法（P1-3）

```python
import shutil
from pathlib import Path

def detect_mutation_tool(config: dict, language: str) -> str | None:
    """
    检测 mutation 工具是否可用
    """
    # 配置已显式指定
    if config.get('mutation', {}).get('tool'):
        tool = config['mutation']['tool']
        if shutil.which(tool):
            return tool
        else:
            return None  # 配置了但不存在
    
    # 自动检测
    if language == 'python':
        if shutil.which('mutmut'):
            return 'mutmut'
        if shutil.which('cosmic-ray'):
            return 'cosmic-ray'
    elif language in ('javascript', 'typescript'):
        if Path('node_modules/@stryker-mutator/core').exists():
            return 'stryker'
    elif language == 'java':
        if Path('pom.xml').exists() or Path('build.gradle').exists():
            return 'pitest'  # 需要在 build 文件配置
    elif language == 'rust':
        if shutil.which('cargo-mutants'):
            return 'cargo-mutants'
    
    return None  # 不可用


def run_mutation_with_fallback(config: dict, mode: str, fingerprint: ProjectFingerprint):
    """
    Mutation 抽样 + 优雅降级
    """
    # 检查模式是否启用
    enabled_modes = config.get('mutation', {}).get('enabled_modes', ['L3'])
    if mode not in enabled_modes:
        return {'status': 'skipped', 'reason': f'未在 {mode} 模式下启用'}
    
    # 检查 capabilities
    if not fingerprint.capabilities.get('mutation'):
        return {
            'status': 'skipped',
            'reason': f'Adapter capabilities.mutation = false'
        }
    
    # 检测工具
    tool = detect_mutation_tool(config, fingerprint.language)
    
    on_missing = config.get('mutation', {}).get('on_tool_missing', 'skip')
    
    if not tool:
        if on_missing == 'fail':
            raise MutationToolNotFound(
                f"未找到 mutation 工具（语言：{fingerprint.language}）\n"
                f"请安装 mutmut/Stryker/PIT/cargo-mutants 之一"
            )
        elif on_missing == 'warn':
            print(f"⚠️ Mutation 工具未找到，本次跳过（不阻断 L3）")
        # skip 或 warn 都跳过
        return {
            'status': 'skipped',
            'reason': 'tool_not_found',
            'note': 'L3 报告中已标注：未跑 mutation（工具未安装）'
        }
    
    # 工具存在，开始执行
    diff_files = git_diff_name_only('HEAD~1', 'HEAD', filter_pattern='*.{py,js,ts,tsx,rs,java}')
    diff_files = [f for f in diff_files if not is_test_file(f)]
    
    if len(diff_files) > 20:
        diff_files = sample_top_changed_files(diff_files, top_n=20)
    
    cmd = build_mutation_command(tool, diff_files)
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    score = parse_mutation_report(result.stdout, tool)
    
    threshold = config.get('mutation', {}).get('threshold', 0.60)
    return {
        'status': 'completed',
        'tool': tool,
        'files_tested': len(diff_files),
        'score': score['killed'] / score['total'],
        'threshold': threshold,
        'pass': (score['killed'] / score['total']) >= threshold
    }
```

---

## 9. 技术栈决策

### 9.1 核心技术选型

| 组件 | 技术选择 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | 生态丰富、LLM SDK 完善 |
| LLM 调用 | Claude Code Workflow/Agent 工具 | 复用 Claude Code 的 session 管理、MCP 集成 |
| 配置解析 | PyYAML | 标准库 |
| Git 操作 | GitPython | 成熟稳定 |
| MCP 集成 | Claude Code 原生支持 | 无需额外封装 |
| 测试框架 | pytest（自测用） | 测试 Agent 本身的逻辑 |

### 9.2 目录结构

```text
qa_agent/
  qa_core/
    __init__.py
    engine.py                # Core 引擎（模式路由、角色编排）
    designer_runner.py       # DesignerRunner 实现
    gatekeeper.py            # Gatekeeper 实现
    adapter.py               # Adapter 抽象基类
    adapter_loader.py        # Adapter 动态加载
    impact_analysis.py       # 影响面分析算法
    flaky_detector.py        # Flaky 检测
    mutation_sampler.py      # Mutation 抽样
    state_manager.py         # 状态持久化、恢复
    
  adapters/
    web/
      __init__.py
      adapter.py             # WebAdapter 实现
      templates/             # Playwright/Vitest 模板
    backend/
      __init__.py
      adapter.py
    mobile/
      adapter.py             # stub
    desktop/
      adapter.py             # stub
    game/
      adapter.py             # stub
  
  prompts/
    designer_runner_system.txt
    designer_runner_user_l1.txt
    designer_runner_user_l3.txt
    gatekeeper_system.txt
    gatekeeper_user.txt
    adversarial_review.txt
  
  cli/
    __init__.py
    main.py                  # 入口脚本 qa-cli
    parser.py                # 命令行解析
  
  tests/                     # Agent 自身的测试
    test_impact_analysis.py
    test_flaky_detector.py
    test_web_adapter.py
  
  pyproject.toml
  README.md
```

### 9.3 依赖清单

```toml
[tool.poetry.dependencies]
python = "^3.11"
anthropic = "^0.40.0"
pyyaml = "^6.0"
gitpython = "^3.1"
click = "^8.1"               # CLI 框架
jinja2 = "^3.1"              # 提示词模板渲染

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-cov = "^5.0"
black = "^24.0"
mypy = "^1.11"
```

---

## 10. 实施路径（MVP → v1.0）

### 10.1 Phase 1: Core 骨架 + 引导式初始化（1 周）

**目标**：Core 引擎 + local 影响面 + 数据结构 + `/qa init`（P2-1）

**任务**：
- [ ] 搭建项目骨架（目录、pyproject.toml）
- [ ] 实现 `qa_core/engine.py` 模式路由
- [ ] 实现 `qa_core/state_manager.py` 数据结构（last.json 含 phase/checkpoint，history.json）
- [ ] 实现 `qa_core/impact_analysis.py` local 模式
- [ ] 实现 `qa_core/init_wizard.py` 引导式初始化（P2-1）
  - [ ] 自动扫描项目（package.json / pyproject.toml / Cargo.toml / ...）
  - [ ] 检测已识别的框架与测试目录
  - [ ] 生成 `.qa-agent.yml` 草稿
  - [ ] 创建 `qa/` 目录结构（cases/ bugs/ run/ feedback/）
  - [ ] 列出现有测试为 orphan（写入 `qa/orphan_tests.md`）
  - [ ] 终端引导式提示（"下一步建议"）
- [ ] 实现 `qa_core/requirement_discovery.py` 需求文档自动发现（P0-1）
- [ ] 实现 CLI 入口 `qa-cli`（命令行解析：init / L0 / L1 / L4 / retry / status）
- [ ] 单元测试：Core 模式路由、数据序列化、init 流程

**产物**：
- `qa-cli init` 能在新项目零配置生成草稿 + 引导
- `qa-cli L1 feature 登录 --impact=local` 可执行
- 输出 selection.md（基于 git diff）
- 写入含 checkpoint 字段的 last.json

### 10.2 Phase 2: GitNexus + 两角色分离（1 周）

**目标**：GitNexus 集成 + DesignerRunner / Gatekeeper 独立

**任务**：
- [ ] 实现 GitNexus 影响面分析（§3.1 完整流程）
- [ ] 实现 DesignerRunner LLM 调用（使用 Claude Code Workflow 工具）
- [ ] 实现 Gatekeeper 独立进程（subprocess 调用）
- [ ] 实现提示词模板加载（prompts/ 目录）
- [ ] 单元测试：影响面分析、补集兜底

**产物**：
- GitNexus 模式可用
- DesignerRunner 能生成用例 YAML（手写 Adapter stub）
- Gatekeeper 能输出 final_test_report.md

### 10.3 Phase 3: L1/L4 完整流程（1 周）

**目标**：L1/L4 模式完整跑通

**任务**：
- [ ] 实现 L1 模式完整流程（设计 → 执行 → 判定）
- [ ] 实现 L4 模式完整流程（验证修复）
- [ ] 实现 Flaky 检测（§4.1）
- [ ] 实现自检清单（8 项）
- [ ] 实现状态恢复（§8.1）
- [ ] 集成测试：完整 L1/L4 流程

**产物**：
- 对一个真实小项目（手动准备测试脚本），L1/L4 能跑通
- 输出 final_test_report.md

### 10.4 Phase 4: Web Adapter 完整实现（1 周）

**目标**：Web Adapter 完整实现（Playwright + Vitest）

**任务**：
- [ ] 实现 WebAdapter.detect()
- [ ] 实现 WebAdapter.generate()（Playwright 模板）
- [ ] 实现 WebAdapter.run()
- [ ] 实现 WebAdapter.parse_report()
- [ ] 实现 WebAdapter.classify_failure()
- [ ] 实现 WebAdapter.index_targets()（基于 LSP 或 git）
- [ ] 单元测试：Web Adapter 各接口

**产物**：
- 对一个真实 Web 项目（用 Playwright），完整 L1 流程自动生成脚本并执行

### 10.5 Phase 5: L0/L2 + Backend Adapter（2 周）

**目标**：新增 L0/L2 模式 + Backend Adapter

**任务**：
- [ ] 实现 L0 模式（spot check）
- [ ] 实现 L2 模式（module + 对抗式 review）
- [ ] 实现对抗式 review prompt（§6.5）
- [ ] 实现 BackendAdapter（pytest）
- [ ] 集成测试：L0/L2 完整流程

**产物**：
- MVP 完成（v0.1）

### 10.6 Phase 6: L3 + 非功能（2 周）

**目标**：L3 模式 + mutation + 性能/安全

**任务**：
- [ ] 实现 L3 模式完整流程
- [ ] 实现 Mutation 抽样（§5.1）
- [ ] 实现非功能测试集成（性能/安全/兼容）
- [ ] 实现 Waiver 流程（简化版）
- [ ] 实现 release_gate_report.md 输出
- [ ] 集成测试：L3 完整流程

**产物**：
- v1.0 完成

---

## 11. 测试策略

### 11.1 单元测试

**覆盖目标**：Core 逻辑 ≥ 80%

```python
# tests/test_impact_analysis.py

def test_gitnexus_mode_direct_hit():
    """
    测试 GitNexus 模式直接命中
    """
    mock_cases = [
        TestCase(id='TC-001', targets={'symbols': ['LoginPage']}),
        TestCase(id='TC-002', targets={'symbols': ['HomePage']}),
    ]
    
    mock_affected_symbols = ['LoginPage', 'authenticate']
    
    result = analyze_impact_gitnexus_mock(
        changed_symbols=['LoginPage'],
        all_cases=mock_cases,
        affected_symbols=mock_affected_symbols
    )
    
    assert 'TC-001' in [c.id for c in result]
    assert 'TC-002' not in [c.id for c in result]

def test_补集_兜底():
    """
    测试 feature_id 补集兜底
    """
    direct_hit = [TestCase(id='TC-001', feature_id='F-LOGIN')]
    all_cases = [
        TestCase(id='TC-001', feature_id='F-LOGIN'),
        TestCase(id='TC-002', feature_id='F-LOGIN', priority='P1'),
        TestCase(id='TC-003', feature_id='F-HOME'),
    ]
    
    result = apply_补集_兜底(direct_hit, all_cases, mode='L1')
    
    assert len(result) == 2
    assert 'TC-002' in [c.id for c in result]
```

### 11.2 集成测试

**覆盖目标**：完整流程（L1/L4）

```python
# tests/integration/test_l1_flow.py

def test_l1_complete_flow():
    """
    测试 L1 完整流程（使用 fixture 项目）
    """
    # 准备测试项目
    setup_fixture_project('tests/fixtures/web-login-app')
    
    # 执行 L1
    result = subprocess.run(
        ['qa-cli', 'L1', 'feature', '登录'],
        capture_output=True
    )
    
    assert result.returncode == 0
    
    # 检查产物
    assert os.path.exists('qa/run/last.json')
    assert os.path.exists('qa/run/selection.md')
    assert os.path.exists('qa/final_test_report.md')
    
    last_run = json.load(open('qa/run/last.json'))
    assert last_run['mode'] == 'L1'
    assert last_run['execution']['total'] > 0
```

### 11.3 E2E 测试

**覆盖目标**：真实项目

```python
# tests/e2e/test_real_web_project.py

def test_real_web_project_l1():
    """
    对真实 Web 项目运行 L1
    """
    os.chdir('tests/fixtures/real-todo-app')
    
    # 初始化
    subprocess.run(['qa-cli', 'init'])
    
    # 修改代码
    edit_file('src/TodoList.tsx', '...')
    subprocess.run(['git', 'commit', '-am', 'feat: add filter'])
    
    # 执行 L1
    result = subprocess.run(['qa-cli', 'L1', 'feature', 'todo-filter'])
    
    assert result.returncode == 0
    
    # 检查生成的测试脚本
    assert os.path.exists('tests/system/todo_filter.spec.ts')
```

### 11.4 Mock 策略

**LLM 调用 Mock**：

```python
# tests/mocks/llm_mock.py

class MockLLM:
    """
    Mock Claude API，返回预定义响应
    """
    def __init__(self, responses: dict):
        self.responses = responses
    
    def create_message(self, prompt: str, **kwargs):
        # 根据 prompt 关键词返回不同响应
        if 'DesignerRunner' in prompt:
            return self.responses['designer']
        elif 'Gatekeeper' in prompt:
            return self.responses['gatekeeper']

# 使用示例
def test_designer_with_mock():
    mock = MockLLM({
        'designer': {'cases': [{'id': 'TC-001', ...}]}
    })
    
    designer = DesignerRunner(llm=mock)
    result = designer.design_cases('F-LOGIN', config)
    
    assert len(result) == 1
```

---

## 总结

本设计文档覆盖了 v3.0 Solo Edition 的：

1. **架构设计**：两角色 + Adapter 插件系统
2. **数据结构**：last.json / history.json / selection.md / bugs YAML
3. **关键算法**：影响面分析、Flaky 检测、Mutation 抽样
4. **提示词框架**：DesignerRunner / Gatekeeper / 对抗式 review
5. **技术栈**：Python + Claude Code Workflow/Agent
6. **实施路径**：MVP（4 周）→ v1.0（8 周）

下一步：基于本文档启动 Phase 1 实现。
