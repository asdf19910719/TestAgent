# AI Test Engineer Agent v3.0 Solo Edition

> **产品级质量 + 个人级流程**

AI Test Engineer Agent 帮助个人开发者把 AI 产出的代码从"看起来能跑"升级为"经过测试和真实验证"的质量。

## 特性

- **五档运行模式**（L0–L4）：按场景选择成本与质量平衡
- **影响面驱动**：基于 GitNexus 代码图精确选择用例
- **两角色独立校验**：Designer+Runner 产出 + Gatekeeper 独立判定
- **检查点恢复**：L3 长时运行支持中断后恢复
- **零配置接入**：`/qa init` 自动检测项目生成配置草稿
- **灵活 bug 引用**：支持 BUG-XXX / TC-XXX / #issue / 关键词 / 自然语言

## 快速开始

```bash
# 安装依赖
poetry install

# 首次接入项目
qa init

# 运行测试
qa feature 用户登录    # L1 功能级测试
qa bugfix BUG-008      # L4 缺陷验证
qa release             # L3 发版质量门
```

## 文档

- [需求与方案文档 v3.0-rev1](docs/AI%20Test%20Engineer%20Agent%20需求与方案文档%20v3.0.md)
- [详细设计 v3.0-rev1](docs/design_v3.0.md)

## 项目结构

```
qa_agent/
  cli/          # CLI 入口
  core/         # Core 引擎（模式路由、状态管理、影响面分析）
  adapters/     # Adapter 插件（Web/Backend/Generic）
  prompts/      # LLM 提示词模板

tests/          # 单元测试 + 集成测试
docs/           # 规范与设计文档
```

## 开发状态

当前：**Phase 1 实现中**（Core 骨架 + /qa init）

## License

MIT
