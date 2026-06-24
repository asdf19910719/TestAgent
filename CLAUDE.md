# CLAUDE.md — TestAgent 项目规则

## 全局副本同步规则（强制）

本项目的 Agent / Command 文件存在**两份副本**：

| 位置 | 作用 |
|---|---|
| `E:\AIProject\TestAgent\.claude\agents\*.md` | 项目内副本（git 管理，开发源） |
| `E:\AIProject\TestAgent\.claude\commands\*.md` | 项目内副本（git 管理，开发源） |
| `C:\Users\91799\.claude\agents\*.md` | **全局副本（其他项目实际加载的位置）** |
| `C:\Users\91799\.claude\commands\*.md` | **全局副本（其他项目实际加载的位置）** |

**关键事实**：StudySkill 等外部项目调用 `/qa` 时，按查找顺序**全局副本优先**。只改项目内副本不会生效。

**规则**：每次修改 `.claude/agents/` 或 `.claude/commands/` 下的文件并 `git commit` 后，**必须同步到全局副本**：

```bash
# 提交后立即执行
cp .claude/agents/*.md /c/Users/91799/.claude/agents/
cp .claude/commands/*.md /c/Users/91799/.claude/commands/
# 验证同步成功（对比关键新增内容）
```

不同步 = 改动对外部项目无效。这是 TestAgent 作为"全局 QA Agent 提供方"的发布步骤，不可省略。

注意：全局副本不在本项目 git 仓库内，无法用 git 跟踪，只能靠这条规则保证一致。
