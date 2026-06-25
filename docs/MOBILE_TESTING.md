# 移动端测试自动化方案（三轨 + AI 填充闭环）

> 本文档整合并取代根目录早期的三份散稿（IMPLEMENTATION_COMPLETE_REPORT / MOBILE_DUAL_TRACK_SUMMARY / PHASE3_ROBOLECTRIC_COMPLETE）。
> 那些早期文档曾给出"需手填 10-20%"的结论，**已被 @AI-FILL 完全自动化链路推翻**，以本文为准。

## 1. 目标与最终结论

**目标**：移动端测试不止单元/集成，还要像测试工程师一样按用例真机操作、覆盖主流程。

**最终结论**：移动端测试从"空骨架 0% 可执行"做到"三轨覆盖 + AI 自动填充"。
生成的脚本是**真实可执行代码**，Arrange/Act 由 Designer 读项目源码自动填充，
不再留 TODO 给人手填。

## 2. 三轨方案（按用例特征智能路由）

Adapter 按 `level` + `assertions.type` 自动选工具：

| 轨 | 工具 | 适用 | 生成路径 | 是否需设备 |
|---|---|---|---|---|
| 第1轨 | Espresso/UiAutomator | integration，有 database/log 断言 | `app/src/androidTest/kotlin/` | 是 |
| 第2轨 | Maestro | system/acceptance，纯 UI 主流程 | `qa/maestro_flows/*.yaml` | 是 |
| 第3轨 | Robolectric | unit，纯逻辑 | `app/src/test/kotlin/` | 否（JVM 秒级） |

**选型依据**（详见 `docs/INDUSTRY_RESEARCH_AI_AGENT_QA.md`）：
- Maestro 作 UI 主力：YAML↔YAML 契合、确定性高、0 API 成本、生态成熟
- Midscene（AI 视觉）作辅助/远期：非确定性，不适合做回归门禁
- 自主探索（DroidAgent 式）列为第三轨远期规划

## 3. AI 填充闭环（完全自动化核心）

```
Adapter 生成「半成品 + @AI-FILL 指令」
  ├─ Assert: 已自动生成真实断言(ContentResolver/Logcat)
  └─ Arrange/Act: @AI-FILL 标记 + @AI-FILL-SPEC 指令块(含 targets 源码锚点)
        ↓
Designer 读 targets 源码 + 侦察项目测试设施 → 替换 @AI-FILL 为真实代码
        ↓
三处 validate-kotlin 自检(Adapter生成 / Designer填充 / Gatekeeper验收)
```

**为什么能自动填**：用例的 `targets.files`/`targets.symbols` 标注了被测源码锚点，
"读源码推断 mock/调用方式"是推理工作，由 Designer(LLM)完成，不是 Python Adapter 的活。

## 4. Android 填充技术手册（实证总结）

在 ClawBoxClient 实证撞到的真实障碍 → 对应打法（写入 `qa-test-engineer.md`）：

| 障碍 | 打法 |
|---|---|
| private 方法 | 反射 `getDeclaredMethod` + `isAccessible` |
| suspend 方法 | `runTest` 包裹 |
| private + suspend | 反射 `callSuspend` |
| object 单例做 HTTP | MockK `mockkObject` + `coEvery` |
| Context 绑定 DB/Provider | Robolectric `RuntimeEnvironment` 或 instrumented |
| Service 类 | `Robolectric.buildService` |
| **source set 冲突** | MockK 仅 testImpl 时，优先 Robolectric（其 ContentProvider shadow 多数够用），不生成引用不存在依赖的代码 |

## 5. 质量保障：validate-kotlin 静态校验

无需 JDK/Android SDK 的纯静态校验，拦截编译阻塞类 bug：
- val/var 同作用域重复声明
- import 缺前缀
- 花括号/圆括号不配平
- @AI-FILL/TODO 残留（warning）
- 空测试方法体（warning）

```bash
qa validate-kotlin --path app/src/test/.../TcXxx.kt --fail-on-warning
qa validate-kotlin --glob "app/src/**/Tc*.kt"
```

接入三处：Adapter 生成后自检、Designer 填充后自检（退出0才标 implemented）、
Gatekeeper 硬规则9 验收。

## 6. 关键约束（防虚标/防半成品）

- **automation.status 真实性**（Designer）：implemented 必须 test_id 可 Grep + 有效断言
- **硬规则8 选中即执行一致性**（Gatekeeper）：虚标 implemented → BLOCKED
- **硬规则9 填充完整性**（Gatekeeper）：脚本残留 @AI-FILL → BLOCKED

## 7. 已知限制

- **无法在本机真编译验证**：AGP 8.11.2 需 JDK17，本机 Java 1.8 + 无 Android SDK；
  static validate-kotlin 是当前能做的最强验证（CI 上有 JDK17 可补真编译）
- **Maestro 步骤转译**：复杂交互可能需手调元素选择器
- **Midscene 集成**：未实现，列为辅助/远期

## 8. 相关提交（本轮）

- Espresso 断言转译引擎 / Maestro / Robolectric 三轨
- @AI-FILL 自动填充链路 + Android 填充技术手册 + source-set 冲突判定
- Kotlin 静态校验器 + validate-kotlin CLI + 三处接入
- 多 database 断言 val 重复修复 / imports 前缀 / 缩进修复

## 9. 后续

- CI 接入真编译（JDK17）验证生成代码
- Midscene 集成（动态内容/视觉验证场景）
- 第三轨自主探索（DroidAgent 式）评估
