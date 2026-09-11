# Web 前端测试指引（按需加载）

> 由 qa-test-engineer.md 在**检测到 Web 前端项目**时 Read 加载。
> 非 Web 项目不必读此文件。

## Web 前端维度矩阵

| 维度 | 必测场景 | 用例类型 |
|---|---|---|
| **页面导航** | 每个路由可达、前进后退、直接访问URL、404处理 | E2E |
| **表单提交** | 正常提交、空值校验、格式校验、重复提交防护 | 功能+边界 |
| **数据展示** | 列表加载、空状态、加载中、错误状态、分页 | 功能+异常 |
| **登录态** | 未登录重定向、token过期刷新、退出清理 | 状态转换 |
| **响应式** | 关键页面在移动端/平板/桌面可用 | 兼容性 |
| **网络异常** | 请求失败提示、超时重试、离线提示 | 容错 |

## Vue 项目：先做前端静态分析（W1，补运行时探测短板）⭐

设计 Vue 前端用例前，先用静态分析提取路由→组件→字段/按钮/API 知识图，
**不依赖登录成功**（运行时 Playwright 探测必须先登录才能拿元素，复杂前置时拿不到）：
```bash
python -m qa_agent.webui.analyzer.analyze \
  --frontend-repo <前端项目根> --test-urls /目标路由 \
  --output qa/run/frontend_knowledge.json
```
产出 `frontend_knowledge.json` 含：路由表、组件 form_fields（含中文 label/type）、
按钮、调用的 API、element_index。用它做两件事：
1. **设计用例**：知道页面有哪些字段/按钮/业务规则，断言带语义（"用户名"而非裸 selector）
2. **喂给 e2e_enhancer**：静态知识 + 运行时 DOM 元素互补，生成更准的 Playwright 脚本

仅 Vue2/Vue3 项目支持；非 Vue 或拿不到源码时跳过，回退到运行时探测。

## 选择器质量（Web E2E）

- 优先 `data-testid` / `role` / 文案，避免脆弱的 CSS 路径（如 `div>div:nth-child(3)`）
- 静态分析拿到的 `element_index` 可提供稳定锚点
- 运行时探测的元素优先用语义选择器，retry 前先确认元素真实存在
