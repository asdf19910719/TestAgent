# CLAUDE.md — TestAgent 项目规则

## 发布规则（插件机制，替代旧的手工 cp 同步）

本项目已改造为标准 Claude Code 插件。**旧的"改完 cp 到 `~/.claude/agents`、`~/.claude/commands` 全局副本"规则已废弃**——不要再手工复制文件到全局目录。

### 目录约定

| 位置 | 作用 |
|---|---|
| `agents/*.md`（含 `agents/guidance/` 子目录） | 插件 agents（git 管理，唯一开发源） |
| `commands/qa.md` | 插件 command（安装后为 `/testagent:qa`） |
| `.claude-plugin/marketplace.json` | 市场清单（仓库根 = 插件根） |
| `.claude-plugin/plugin.json` | 插件清单（`version` 决定用户何时收到更新） |
| `qa_agent/` | Python 工具层（在插件根下，靠 `${CLAUDE_PLUGIN_ROOT}` + PYTHONPATH 被导入） |

### 发布流程

1. 改 `agents/` `commands/` `qa_agent/` 等
2. 若为对外可见的功能变更，bump `.claude-plugin/plugin.json` 和 `marketplace.json` 里的 `version`
3. `git commit` + `git push`（远端 https://github.com/asdf19910719/TestAgent）
4. 外部用户 `/plugin update testagent` 即可获取更新——**无需任何手工同步**

### 关键约束（改动 agents/commands 时必守）

- guidance 分册路径必须用 `${CLAUDE_PLUGIN_ROOT}/agents/guidance/xxx.md`，不能写死 `.claude/` 或 `~/.claude/`（插件安装在 `~/.claude/plugins/cache/...`，写死路径会失效）
- 任何 `python -m qa_agent.cli.main` / `python -c "from qa_agent..."` 调用，正文里都要带 `PYTHONPATH="${CLAUDE_PLUGIN_ROOT}"` 前缀
- 本地开发调试：`claude --plugin-dir .` 加载当前目录为插件；`claude plugin validate .` 校验清单

### 遗留：全局 `~/.claude/` 旧副本清理

改造前手工 cp 的旧副本可能还在 `C:\Users\91799\.claude\agents\{qa-test-engineer,qa-gatekeeper}.md`、
`commands\qa.md`（对应 `/qa` 无前缀命令）。这些与插件版（`/testagent:qa`）并存不冲突，
但已不再维护。确认插件工作正常后可手工删除旧副本，避免 `/qa` 与 `/testagent:qa` 两套并行造成困惑。
