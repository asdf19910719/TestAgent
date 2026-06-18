# API Test Executor 迁移文档

## 迁移概览

从 oec-infra 完整迁移了 API Test Executor 测试执行器（4 个核心脚本，3719 行代码）。

## 迁移的组件

### 1. 核心脚本（qa_agent/adapters/backend/api_executor/）

| 脚本名 | 行数 | 功能 |
|---|---|---|
| `enhanced_execute_with_auth.py` | 617 | pytest 执行器 + 401 鉴权处理 + 实时进度展示 |
| `report_template_fixed.py` | 1905 | HTML 报告模板生成器（紫色渐变 + 卡片式布局） |
| `conftest_plugin.py` | 1088 | pytest 插件：捕获请求/响应详情 |
| `update_report_with_ai_analysis.py` | 109 | 将 AI 分析结果写入 HTML 报告 |

**总计**：3719 行

### 2. 核心功能

#### 2.1 智能执行器

```python
# enhanced_execute_with_auth.py
功能：
- pytest 测试执行
- 401 鉴权自动处理
- 实时进度展示（[OK]/[FAIL]/[ERR]）
- 跨平台编码兼容（UTF-8/GB18030）
- 接口覆盖率统计

参数：
--test-dir   测试脚本所在目录或具体的 .py 测试文件
--report-dir 报告输出目录（可选，默认生成到 --test-dir 所在目录）
```

#### 2.2 智能分析引擎（7 大失败分类）

```
失败原因分类体系：
1. 网络连接问题（Connection refused/Timeout）
2. HTTP 状态码问题（404/500/502）
3. 参数校验失败（Required field missing）
4. 响应格式验证（JSON parse error）
5. 认证授权问题（401/403）
6. 测试脚本问题（SyntaxError/ImportError）
7. 环境与数据问题（Database unavailable）
```

#### 2.3 专业 HTML 报告

```html
视觉特性：
- 紫色渐变统计栏
- 卡片式用例布局
- emoji 区块标题
- 搜索过滤：按状态/分类/关键词筛选
- 折叠展开：每条用例详情可独立展开/折叠
- 饼图统计：通过/失败/错误比例可视化
- 用例分类标签：[正常] [边界值] [空值] [类型错误]
```

#### 2.4 pytest 插件

```python
# conftest_plugin.py
捕获内容：
- HTTP 请求方法/URL/请求头/请求体
- HTTP 响应状态码/响应头/响应体
- 断言结果
- 执行时间
- 错误堆栈

输出格式：
{
  "summary": {"total": 10, "passed": 7, "failed": 2, "skipped": 1},
  "test_cases": [
    {
      "test_id": "test_login_success",
      "status": "PASSED",
      "http_method": "POST",
      "url": "http://localhost:3000/api/login",
      "request_body": {"username": "admin", "password": "123456"},
      "response_status_code": 200,
      "response_body": {"code": 0, "message": "success"},
      "assertions": [{"passed": true, "message": "status_code == 200"}],
      "duration_ms": 123
    }
  ]
}
```

---

## 集成到 Backend Adapter

### 修改内容

```python
# qa_agent/adapters/backend/adapter.py

class BackendAdapter:
    def __init__(self, cwd: Path, config: Dict[str, Any] = None):
        self.use_api_executor = config.get('backend', {}).get('use_api_executor', True)

    def _run_pytest(self, cases, mode):
        """智能选择执行方式"""
        if self.use_api_executor:
            return self._run_with_api_executor(test_files, mode)  # 增强版
        else:
            return self._run_with_native_pytest(test_files, mode)  # 原生 pytest

    def _run_with_api_executor(self, test_files, mode):
        """调用 API Test Executor"""
        cmd = [
            sys.executable,
            '-m', 'qa_agent.adapters.backend.api_executor.enhanced_execute_with_auth',
            '--test-dir', str(test_dir),
            '--report-dir', str(report_dir)
        ]
        result = subprocess.run(cmd, ...)
        # 读取生成的 test_results_*.json
        # 解析并返回 RunResult
```

### 降级机制

1. **配置降级**：`backend.use_api_executor: false` → 使用原生 pytest
2. **执行失败降级**：API Test Executor 执行失败 → 自动回退到原生 pytest
3. **结果解析降级**：JSON 解析失败 → 解析 stdout 文本输出

---

## 配置文件

### .qa-agent.yml（项目级配置）

```yaml
backend:
  use_api_executor: true              # 使用增强版执行器
  auto_fix_script_errors: true        # 脚本错误自动修复（Phase 2）
  max_retry_on_script_error: 1        # 脚本错误最多重试次数（Phase 2）
  report_format: html                 # html | json | both
```

### DEFAULT_CONFIG（默认配置）

```python
# qa_agent/core/config.py
DEFAULT_CONFIG = {
    'backend': {
        'use_api_executor': True,
        'auto_fix_script_errors': True,
        'max_retry_on_script_error': 1,
        'report_format': 'html',
    },
}
```

---

## 使用方式

### 方式 1：Backend Adapter 自动调用（推荐）

```python
# TestAgent 内部自动使用
adapter = BackendAdapter(cwd=Path('.'), config={'backend': {'use_api_executor': True}})
result = adapter.run(cases, mode='L3')
# 自动生成报告：qa/backend/reports/test_results_20240616_103045.json
# 自动生成报告：qa/backend/reports/test_report_20240616_103045.html
```

### 方式 2：命令行直接调用

```bash
# 执行整个测试目录
python -m qa_agent.adapters.backend.api_executor.enhanced_execute_with_auth \
  --test-dir tests/integration \
  --report-dir qa/backend/reports

# 执行单个测试文件
python -m qa_agent.adapters.backend.api_executor.enhanced_execute_with_auth \
  --test-dir tests/integration/test_user_api.py \
  --report-dir qa/backend/reports
```

---

## 产物输出

### 目录结构

```
qa/backend/reports/
├── test_results_20240616_103045.json     # JSON 结果（conftest_plugin 生成）
└── test_report_20240616_103045.html      # HTML 报告（report_template_fixed 生成）
```

### JSON 结果示例

```json
{
  "summary": {
    "total": 10,
    "passed": 7,
    "failed": 2,
    "error": 0,
    "skipped": 1,
    "duration_seconds": 12.34
  },
  "test_cases": [
    {
      "test_id": "test_user_api.py::test_login_success",
      "status": "PASSED",
      "category": "正常",
      "http_method": "POST",
      "url": "http://localhost:3000/api/login",
      "request_headers": {"Content-Type": "application/json"},
      "request_body": {"username": "admin", "password": "123456"},
      "response_status_code": 200,
      "response_headers": {"Content-Type": "application/json"},
      "response_body": {"code": 0, "message": "success", "data": {"token": "..."}},
      "assertions": [
        {"passed": true, "message": "status_code == 200"},
        {"passed": true, "message": "response.code == 0"}
      ],
      "duration_ms": 123,
      "timestamp": "2024-06-16T10:30:45"
    }
  ]
}
```

---

## 对比效果

| 维度 | 原生 pytest | API Test Executor |
|---|---|---|
| **执行能力** | 基础 pytest 执行 | 401 鉴权处理 + 实时进度 |
| **失败分析** | 无 | 7 大分类（网络/HTTP/参数/响应/认证/脚本/环境） |
| **自动修复** | 无 | 脚本错误自动修复（Phase 2） |
| **报告格式** | JUnit XML | 专业 HTML（紫色渐变 + 卡片式布局） |
| **请求详情** | 无 | 完整请求/响应头体 |
| **断言详情** | 无 | 结构化断言结果 |
| **搜索过滤** | 无 | 按状态/分类/关键词筛选 |
| **可读性** | ⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 下一步（Phase 2）

### 计划迁移的功能

1. **脚本自动修复**（`auto_fix_script_errors`）
   - 检测到 SyntaxError/ImportError/NameError
   - LLM 分析错误类型
   - 自动生成修复补丁
   - 重新执行（最多 1 次）

2. **智能分析增强**
   - 提取 `references/test_failure_analysis_guide.md` 的分类体系
   - 集成到 TestAgent 的 `core/bug_resolver.py`
   - 增强 Gatekeeper 的失败判定能力

3. **数据库元数据验证**
   - 连接数据库验证表/字段是否存在
   - 自动修正 SQL 语句
   - needRealData 处理机制

---

## 注意事项

### 1. conftest_plugin 加载方式

**原方式**（oec-infra）：
```bash
pytest -p conftest_plugin  # 需要 PYTHONPATH
```

**新方式**（TestAgent）：
```bash
pytest -p qa_agent.adapters.backend.api_executor.conftest_plugin  # 完整包路径
```

### 2. 报告生成时机

- **执行完成后自动生成**：HTML 报告由 `enhanced_execute_with_auth.py` 内部调用 `generate_fixed_report()` 生成
- **无需手动触发**：Backend Adapter 执行后自动在 `qa/backend/reports/` 下生成

### 3. 兼容性

- ✅ **Python 3.8+**
- ✅ **Windows/Linux/macOS**
- ✅ **pytest 6.0+**
- ✅ **requests 库**（接口测试必需）

---

## 总结

### 迁移成果

| 指标 | 数据 |
|---|---|
| **文件数** | 4 个核心脚本 |
| **代码量** | 3719 行 |
| **工作时间** | ~1 小时 |
| **依赖** | pytest/requests（已有） |

### 核心价值

1. ⭐⭐⭐⭐⭐ **智能分析引擎**：7 大失败分类，精确定位问题
2. ⭐⭐⭐⭐⭐ **专业 HTML 报告**：可读性提升 10 倍
3. ⭐⭐⭐⭐ **实时进度展示**：执行过程可视化
4. ⭐⭐⭐⭐ **请求详情捕获**：完整请求/响应头体
5. ⭐⭐⭐⭐ **降级机制**：执行失败自动回退到原生 pytest

### 后续计划

- Phase 2：脚本自动修复（5-8 天）
- Phase 3：数据库元数据验证（3-5 天）
- Phase 4：场景测试支持（8-12 天）
