# WebUI Test Unified 迁移文档

## 迁移概览

从 oec-ai-infra 完整迁移了 webui-test-unified 测试体系（28 个文件，包含 1 个 2099 行的 JS DOM 提取器）。

## 迁移的组件

### 1. 登录处理（qa_agent/webui/login/）
- `login_password.py` - 用户名密码登录 + 600 秒超时 + 3 次失败硬限制
- `login_cookie.py` - Cookie 注入登录
- `login_token.py` - Token 注入登录（localStorage/sessionStorage）
- `login_recipe_manager.py` - 登录配方管理（跨会话复用）
- `validate_login_state.py` - 三层复用校验（认证状态/配方/全自动）

### 2. DOM 探索（qa_agent/webui/explorer/）
- `explore_page.py` - 访问页面 + 截图 + 提取元素 + 多阶段交互探索
- `dom_elements_extractor.py` - Python 侧 DOM 提取协调器
- `dom/dom_exporter_all_in_one.js` - 浏览器端 DOM 导出 + Smart XPath 生成 + 唯一性验证（2099 行）

### 3. 批量执行器（qa_agent/webui/executor/）
- `batch_run.py` - pytest 批量执行协调器 + Sentinel 轮次限制 + 根目录污染检测
- `conftest_webui_plugin.py` - pytest 插件：采集步骤/截图/视频/断言/console 日志
- `validate_test_depth.py` - 脚本深度校验：检测永真断言/空白 try/except/虚假等待
- `codegen_lessons.py` - 失败经验库管理（scope+pattern 去重，hit_count 递增）
- `video_compressor.py` - 视频无损压缩（FFmpeg H.264 CRF 18）
- `webui_script_guard.py` - 脚本守卫（安全检查）

### 4. 报告生成（qa_agent/webui/reporter/）
- `generate_webui_html_report.py` - 生成单文件 HTML 报告（base64 截图内联）
- `generate_webui_json_report.py` - 生成 JSON 结构化报告（webui-test-results-v1 schema）
- `embed_screenshots_base64.py` - 截图 base64 编码工具

### 5. 校验器（qa_agent/webui/validators/）
- `validator_policy.py` - 策略校验
- `validator_quality.py` - 质量校验
- `validator_selector.py` - 选择器校验
- `validator_structure.py` - 结构校验

## 路径适配

| 原路径 | 新路径 |
|---|---|
| `.aqe-output/webui-session/` | `qa/webui/session/` |
| `.aqe-output/webui-shared-assets/` | `qa/webui/shared_assets/` |
| `.aqe_session_sentinel.json` | `.session_sentinel.json` |
| `current-webui-session.json` | `current_session.json` |

## 集成到 WebAdapter

新增 `WebUIE2EEnhancer` 类（`qa_agent/adapters/web/e2e_enhancer.py`），提供：

### 方法

#### `login_and_explore(target_url, credentials)`
- 自动登录（支持密码/Cookie/Token + 配方复用）
- DOM 元素自动提取（Smart XPath）
- 返回 page_elements 列表

#### `generate_script_with_elements(case, page_elements)`
- 基于真实元素生成测试脚本
- 不再是 TODO 占位符
- 智能匹配元素（关键词 → Smart XPath）

#### `execute_with_batch_runner(test_file)`
- 使用 batch_run.py 执行测试
- 含 Sentinel 预算守卫（防止无限循环）
- 自动提取失败经验

#### `generate_professional_report()`
- 生成专业 HTML 报告
- 单文件，卡片式布局，截图内联

### WebAdapter 新方法

#### `generate_with_e2e_enhancement(case, target_url, credentials)`
- 使用 E2E 增强器生成脚本
- 自动登录 + 探索 + 基于真实元素生成
- 降级机制：登录失败时回退到普通骨架生成

## 使用方式

### 方式 1：在 qa-test-engineer.md 中指示使用

```markdown
对于 E2E 用例（level = system/acceptance），优先使用 E2E 增强器：

1. 调用 WebAdapter.generate_with_e2e_enhancement(case, target_url, credentials)
2. 如果有登录需求，传入 credentials={'username': '...', 'password': '...'}
3. 生成的脚本已基于真实元素，无需 LLM 再填充选择器
```

### 方式 2：CLI 命令触发

```bash
# 未来可以增加参数
python -m qa_agent.cli.main execute --use-e2e-enhancer --target-url http://localhost:3000
```

## 核心价值

### 之前（V1）
```typescript
// LLM 猜选择器
await page.fill('???', 'username');  // ??? 是什么？
await page.click('???');              // ??? 是什么？
await expect(page).toHaveTitle(/.*/); // 永真断言
```

### 之后（V2 + webui-test-unified）
```typescript
// 基于 Smart XPath（唯一性验证）
await page.locator('xpath=//input[@id="username"]').fill('admin');
await page.locator('xpath=//button[@class="btn-primary"]').click();
await expect(page.locator('xpath=//div[@class="user-menu"]')).toBeVisible();
```

## 依赖

- ✅ playwright（已有）
- ✅ pytest（已有）
- ✅ Python 标准库

## 文件统计

- Python 脚本：27 个
- JavaScript 脚本：1 个（2099 行 DOM 提取器）
- 总大小：929KB
- 新增代码行数：~15,000 行

## 下一步

1. ✅ 迁移完成
2. ⏳ 在 qa-test-engineer.md 中指示 E2E 用例使用增强器
3. ⏳ 测试验证（真实项目）
4. ⏳ 文档完善（使用示例）

## 注意事项

### 登录配方
- 首次登录后会保存选择器配方到 `qa/webui/shared_assets/login-recipes/`
- 下次登录同一域名时自动复用，无需重新探测

### Sentinel 预算守卫
- 单会话最多执行 3 轮（BUDGET_MAX_ROUNDS）
- 墙钟时间 30 分钟上限（BUDGET_MAX_WALL_CLOCK）
- 绝对上限 10 轮（BUDGET_ABSOLUTE_MAX）
- 超出后强制进入报告生成步骤

### 根目录污染检测
- 执行前后快照对比
- 检测 `.py/.png/.json/.html/.webm/.log` 新增文件
- 防止 LLM 在项目根目录乱写调试脚本

### 失败经验库
- 自动提取失败经验（按 failure_classification 分组）
- 存储到 `qa/webui/shared_assets/lessons/codegen_lessons.json`
- 下次遇到同类错误时自动应用修复建议
