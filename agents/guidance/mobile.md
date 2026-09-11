# 移动端测试指引（按需加载）

> 由 qa-test-engineer.md 在**检测到移动端项目**（Android/iOS/Flutter/RN）时 Read 加载。
> 非移动端项目不必读此文件。
> 注：@AI-FILL 填充流程、automation.status 真实性约束在主文件（始终生效），
> 此处只放移动端**特有**的维度矩阵与三轨工具选择。

## 移动端维度矩阵

| 维度 | 必测场景 | 用例类型 |
|---|---|---|
| **生命周期** | 前后台切换、横竖屏旋转、低内存kill恢复 | 状态转换 |
| **权限** | 首次弹窗、拒绝后降级、设置页手动开关 | 异常分支 |
| **网络** | 无网提示、弱网加载超时、WiFi→4G切换 | 容错 |
| **数据持久化** | 本地缓存、杀进程后数据不丢、清缓存后恢复 | 功能+状态 |
| **手势/交互** | 滑动、长按、双击、下拉刷新、上拉加载 | 功能 |
| **推送/通知** | 前台收到、后台收到、点击跳转正确页面 | 集成 |

## Android 三轨工具选择（Adapter 自动路由，了解即可）

Adapter 按用例 `level` + `assertions.type` 自动选工具，无需手动指定：

| 轨 | 工具 | 适用 | 生成路径 | 需设备 |
|---|---|---|---|---|
| 第1轨 | Espresso/UiAutomator | integration，有 database/log 断言 | `app/src/androidTest/kotlin/` | 是 |
| 第2轨 | Maestro | system/acceptance，纯 UI 主流程 | `qa/maestro_flows/*.yaml` | 是 |
| 第3轨 | Robolectric | unit，纯逻辑 | `app/src/test/kotlin/` | 否（秒级） |

## Android source set 冲突判定（填充前必查）

实战障碍：MockK 等 mock 框架可能只在 `testImplementation`，instrumented
(androidTest) 源集用不了。填充前先确认"要用的 mock/工具在目标源集可用"：

```bash
# 区分框架在哪个源集
Grep(pattern="(test|androidTest)Implementation.*(mockk|mockito|robolectric)", path="app/build.gradle.kts", -n=true)
```

| 用例需要 | mock 框架在哪 | 打法 |
|---|---|---|
| 真 ContentProvider + 要 mock 单例 | mockk 只在 testImpl | **优先 Robolectric**（其 ContentProvider shadow 多数够用，仍在 src/test 能 mock） |
| 真 ContentProvider + mock | mockk 也在 androidTestImpl | instrumented + mockkObject |
| 框架确实缺 | — | notes 写明需补依赖，标 manual，**不生成引用不存在依赖的代码** |

## Android 填充技术手册（破解 @AI-FILL 常见障碍）

| 障碍 | 打法 |
|---|---|
| private 方法 | 反射 `getDeclaredMethod` + `isAccessible` |
| suspend 方法 | `runTest` 包裹 |
| private + suspend | 反射 `callSuspend` |
| object 单例做 HTTP | MockK `mockkObject` + `coEvery` |
| Context 绑定 DB/Provider | Robolectric `RuntimeEnvironment` 或 instrumented |
| Service 类 | `Robolectric.buildService` |

填充前必做：① Grep build.gradle 看测试设施在哪个源集；② 读一个同类已有测试抄
mock/setup 模式（最可靠）；③ 尊重项目测试约定，别硬塞 unit。

## 实战示例（ClawBoxClient TC-CONTACT-001 的 @AI-FILL:act 填充）

```kotlin
// 障碍: syncContactsOnBoot() 是 private suspend + 依赖 BindingApiClient 单例
// source set 检查: MockK 仅在 testImplementation → 改走 Robolectric unit(src/test),
//                  Robolectric 提供 ContentProvider shadow,断言仍可查 ContactsContract
// 打法: Robolectric + mockkObject mock HTTP + 反射 callSuspend 调私有方法 + runTest
@Test
fun test_tc_contact_001() = runTest {
    // Arrange: mock 云端返回 3 个联系人(MockK mockkObject)
    mockkObject(BindingApiClient)
    coEvery { BindingApiClient.listContacts(any(), any()) } returns listOf(
        ContactDto(contactId = 1, name = "张三", phone = "13900000001"),
        ContactDto(contactId = 2, name = "李四", phone = "13900000002"),
        ContactDto(contactId = 3, name = "王五", phone = "13900000003"),
    )
    // Act: 反射调 private suspend
    val service = Robolectric.buildService(GatewayService::class.java).create().get()
    val m = GatewayService::class.declaredFunctions.first { it.name == "syncContactsOnBoot" }
    m.isAccessible = true
    m.callSuspend(service)
    // Assert: 已由 Adapter 自动生成(ContentResolver 查询)
}
```

