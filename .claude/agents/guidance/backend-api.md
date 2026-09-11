# 后端 API 测试指引（按需加载）

> 由 qa-test-engineer.md 在**检测到后端/API 项目**时 Read 加载。
> 非 API 项目不必读此文件。

## 后端 API 维度矩阵

| 维度 | 必测场景 | 用例类型 |
|---|---|---|
| **接口契约** | 每个 API 的 200/4xx/5xx 响应、字段类型正确 | 功能+异常 |
| **鉴权** | 无 token 拒绝、过期 token、越权访问他人数据 | 安全 |
| **数据操作** | CRUD 完整性、级联删除、唯一约束、外键完整 | 功能+边界 |
| **幂等性** | 重复请求不产生副作用（POST除外） | 容错 |
| **分页/过滤** | 首页、末页、超范围、排序、组合过滤 | 边界 |
| **并发写入** | 同一资源并发更新、乐观锁冲突处理 | 竞态 |

## Spring MVC：先扫接口清单（A1，避免"猜接口"）⭐

设计 API 用例前，先用静态扫描提取真实接口清单（源码模式，无需编译）：
```bash
python -m qa_agent.cli.main scan-api \
  --source-root src/main/java \
  --output qa/run/api_definition.json
```
产出 `api_definition.json`（`{'apis': [{method, path, class, handler}]}`），用它：
1. **设计用例**：对照真实接口清单逐个覆盖，不靠读源码"猜"有哪些接口
2. **算应测接口数**：执行器 enhanced_execute_with_auth 直接读它算接口覆盖率
   （之前这个文件没人生成，覆盖率算不准）

非 Spring 项目跳过；源码模式不解析外部依赖类型的请求体/响应体字段。

## 接口定义增强：调用链 + SQL + testPoints（A2）⭐

`scan-api` 给出接口骨架后，对**核心接口**（增删改、涉及数据一致性的）用
CodeGraph 追调用链，提取 SQL 和测试点，让断言有据可依：

1. **追调用链**（Controller → Service → Dao/Mapper）：
   ```bash
   codegraph callees <ControllerClass>.<handler>   # 该接口调了谁
   codegraph callees <ServiceClass>.<method>        # 逐层下钻到 Dao
   ```
2. **提取 SQL**：读 Dao 方法对应的 Mapper XML（`<select>/<insert>/<update>/
   <delete>`）或注解（`@Select/@Insert` 等），拿到真实 SQL。
3. **分析参数映射**：SQL 的 WHERE 字段哪些需接口参数提供（注意变量重命名，
   如 `userId` 传入后赋给 `uid`，要追踪映射）。
4. **提炼 testPoints**：基于 SQL + 业务逻辑提炼"该接口必须验证什么"，写进用例
   `assertions`。例如有 `WHERE status=? AND owner_id=?` → 必测"越权访问他人数据被拒"。

把每个核心接口的 `{调用链, sql, 参数映射, testPoints}` 记到用例 notes 或
`qa/run/api_definition.json` 对应条目，作为断言依据——这是把"猜断言"升级为
"基于真实 SQL/调用链设计断言"的关键。非核心接口（纯查询/无副作用）可只做骨架。

## 场景设计 6 维度 + scenario.md 产物（A3，防漏场景）⭐

单接口的参数校验/边界值在上面维度矩阵里覆盖；而**跨接口的业务场景**易漏，
需用 6 个**场景视角**维度系统化提取，并产出可自检的 `qa/run/scenario.md`：

| 维度 | 含义 | 例 |
|---|---|---|
| 核心业务流程 | 用户完成核心任务的端到端链路 | 下单→支付→发货→确认 |
| CRUD 闭环 | 创建→查询→修改→删除→查不到 | 变量 CRUD 完整闭环 |
| 业务规则跨接口 | 规则在多接口间一致 | 同环境变量名唯一性 |
| 数据一致性与流转 | 改后查、多查询方式结果一致 | 修改 value 后查询返回新值 |
| 跨模块联动 | 一个操作触发其他模块 | 删环境→级联处理其下变量 |
| 关键业务异常路径 | 重要的异常分支 | 删除已删除的资源报错 |

**流程**：
1. **提测试点清单**：从需求按 6 维度提取，建表
   `| ID | 类别 | 优先级 | 业务能力 | 验证点 | 覆盖场景 |`（覆盖场景列先留空）
2. **设计场景**：每个场景声明"覆盖测试点: REQ-XXX"，每步标"对应验证点: REQ-XXX.vN"
3. **覆盖自检**：回填测试点清单的"覆盖场景"列，输出覆盖统计 + **未覆盖列表**
   （P0/P1 测试点必须全覆盖，未覆盖的列出补救建议）
4. 写入 `qa/run/scenario.md`（头部=测试点清单+统计，下面=场景设计），
   场景再落地为 `qa/cases/<feature>/*.yml`。

这把 Gatekeeper"防漏场景/主流程清单显式确认"的要求固化成**可检产物**——
未覆盖的 P0/P1 测试点一目了然，比散文式设计更难漏。

## pytest 脚本生成规范 + DB 校验（A5，降生成 bug 率）⭐

生成 API pytest 脚本时遵守以下规范（借鉴 oec，避高频坑）：
- **一接口一文件 / 一场景一文件**：`test_api_<method>_<path_slug>.py` / `test_scenario_<name>.py`，
  不要把多接口塞一个文件（失败定位困难）
- **fixture scope**：场景测试的前置数据用 `@pytest.fixture(scope="class")`，
  避免每个用例重复建数据（高频坑：scope 默认 function 导致数据被反复创建/清理）
- **断言三层**：状态码 → 响应体字段/类型 → 数据库副作用（用 conftest 已有的 DB 查询能力）
- **DB 元数据校验**（涉及建表/查库的用例）：写 SQL 断言前先确认表名/字段真实存在
  （`codegraph query` 或读 Mapper XML/实体类核对），SQL 标识符加反引号防关键字冲突；
  别假设字段名——查不到的字段断言会让测试"假绿失败"。

## 双轨覆盖交叉自检（A4，找真漏场景）⭐ 依赖 A2+A3 产物

scenario.md 的"需求侧测试点"和 api_definition.json 的"代码侧 testPoints"
（A2 提炼）做矩阵交叉，分三级标记，**双轨都未覆盖的才是真漏**：
- 🔴 需求侧明确要求但未设计场景 → **必补**
- 🟠 代码侧有逻辑（如 SQL 有 WHERE 分支）但无场景触发 → 补
- 🟡 仅代码侧细节、需求未要求 → 可低优先

跑完 JaCoCo 后用 `qa coverage --gap-report` 拿代码侧未覆盖行，
与 scenario.md 未覆盖测试点对照，输出"双轨漏场景"清单驱动补用例。
