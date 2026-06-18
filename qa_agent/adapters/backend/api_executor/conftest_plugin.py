"""
pytest 捕获插件 —— 通过 monkey-patch requests.Session.request 捕获每个测试的
HTTP 请求/响应详情（请求体、响应头、完整请求头），并在会话结束时将结果写入
TEST_RESULTS_PATH 环境变量指定的 JSON 文件。

加载方式：pytest -p conftest_plugin <test_file>
（由 enhanced_execute_with_auth.py 在执行测试时自动注入，无需手动调用）
"""

import ast
import inspect
import json
import os
import re
import textwrap
import time

import pytest
import requests

try:
    import pymysql
except Exception:
    pymysql = None

_test_results = []
_current_http_calls = []
_current_steps = []
_pending_db_queries = {}

_original_request = requests.Session.request
_original_pymysql_cursor_execute = None
_original_pymysql_cursor_fetchone = None
_original_pymysql_cursor_fetchall = None
_original_pymysql_cursor_fetchmany = None


# ---------------------------------------------------------------------------
# HTTP 捕获
# ---------------------------------------------------------------------------

def _safe_serialize(obj):
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except Exception:
            return repr(obj)
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    return repr(obj)


def _patched_request(self, method, url, **kwargs):
    start_time = time.time()
    try:
        response = _original_request(self, method, url, **kwargs)
        duration = (time.time() - start_time) * 1000

        request_body = kwargs.get("json")
        if request_body is None:
            raw_data = kwargs.get("data")
            if raw_data is not None:
                if isinstance(raw_data, bytes):
                    try:
                        request_body = json.loads(raw_data.decode("utf-8"))
                    except Exception:
                        request_body = raw_data.decode("utf-8", errors="replace")
                elif isinstance(raw_data, str):
                    try:
                        request_body = json.loads(raw_data)
                    except Exception:
                        request_body = raw_data
                else:
                    request_body = raw_data

        actual_headers = {}
        if hasattr(response, "request") and response.request is not None:
            actual_headers = dict(response.request.headers or {})
        elif kwargs.get("headers"):
            actual_headers = dict(kwargs["headers"])

        call_info = {
            "step_type": "http",
            "method": method.upper(),
            "url": url,
            "headers": actual_headers,
            "params": _safe_serialize(kwargs.get("params")),
            "request_body": _safe_serialize(request_body),
            "status_code": response.status_code,
            "response_headers": dict(response.headers),
            "response_body": response.text[:5000],
            "execution_time": duration,
        }
        _current_http_calls.append(call_info)
        _current_steps.append(call_info)
        return response
    except Exception as e:
        duration = (time.time() - start_time) * 1000
        call_info = {
            "step_type": "http",
            "method": method.upper(),
            "url": url,
            "headers": dict(kwargs.get("headers") or {}),
            "params": _safe_serialize(kwargs.get("params")),
            "request_body": _safe_serialize(kwargs.get("json") or kwargs.get("data")),
            "status_code": 0,
            "response_headers": {},
            "response_body": str(e),
            "execution_time": duration,
        }
        _current_http_calls.append(call_info)
        _current_steps.append(call_info)
        raise


def _install_pymysql_hooks():
    global _original_pymysql_cursor_execute, _original_pymysql_cursor_fetchone, _original_pymysql_cursor_fetchall, _original_pymysql_cursor_fetchmany
    if pymysql is None:
        return
    if _original_pymysql_cursor_execute is not None:
        return

    cursor_cls = pymysql.cursors.Cursor
    _original_pymysql_cursor_execute = cursor_cls.execute
    _original_pymysql_cursor_fetchone = cursor_cls.fetchone
    _original_pymysql_cursor_fetchall = cursor_cls.fetchall
    _original_pymysql_cursor_fetchmany = cursor_cls.fetchmany

    def _patched_execute(self, query, args=None):
        start_time = time.time()
        try:
            result = _original_pymysql_cursor_execute(self, query, args)
            query_id = id(self)
            _pending_db_queries[query_id] = {
                "sql": query,
                "sql_params": _safe_serialize(args),
                "start_time": start_time,
                "duration_ms": (time.time() - start_time) * 1000,
                "rowcount": getattr(self, "rowcount", None),
                "status": "ok",
            }
            return result
        except Exception as e:
            _current_steps.append({
                "step_type": "db",
                "db_operation": "query",
                "sql": query,
                "sql_params": _safe_serialize(args),
                "status_code": "ERROR",
                "response_body": str(e),
                "result_count": 0,
                "result_preview": [],
                "execution_time": (time.time() - start_time) * 1000,
                "duration_ms": (time.time() - start_time) * 1000,
            })
            raise

    def _finalize_db_step(cursor_obj, results):
        query_id = id(cursor_obj)
        pending = _pending_db_queries.pop(query_id, None)
        if not pending:
            return results

        preview = results
        if isinstance(results, tuple):
            preview = list(results)
        if not isinstance(preview, list):
            preview = [preview] if preview is not None else []
        preview = preview[:5]

        result_count = 0
        if isinstance(results, list):
            result_count = len(results)
        elif results is None:
            result_count = 0
        else:
            result_count = 1

        _current_steps.append({
            "step_type": "db",
            "db_operation": "query",
            "sql": pending.get("sql"),
            "sql_params": pending.get("sql_params"),
            "status_code": "OK",
            "response_body": "",
            "result_count": result_count,
            "result_preview": _safe_serialize(preview),
            "rowcount": pending.get("rowcount"),
            "execution_time": pending.get("duration_ms", 0),
            "duration_ms": pending.get("duration_ms", 0),
        })
        return results

    def _patched_fetchone(self):
        result = _original_pymysql_cursor_fetchone(self)
        return _finalize_db_step(self, result)

    def _patched_fetchall(self):
        result = _original_pymysql_cursor_fetchall(self)
        return _finalize_db_step(self, result)

    def _patched_fetchmany(self, size=None):
        result = _original_pymysql_cursor_fetchmany(self, size)
        return _finalize_db_step(self, result)

    cursor_cls.execute = _patched_execute
    cursor_cls.fetchone = _patched_fetchone
    cursor_cls.fetchall = _patched_fetchall
    cursor_cls.fetchmany = _patched_fetchmany


requests.Session.request = _patched_request
_install_pymysql_hooks()


# ---------------------------------------------------------------------------
# 断言提取辅助
# ---------------------------------------------------------------------------

def _extract_assert_lines(func):
    try:
        src_lines, _ = inspect.getsourcelines(func)
        src = textwrap.dedent("".join(src_lines))
        tree = ast.parse(src)
        result = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                line_idx = node.lineno - 1
                if 0 <= line_idx < len(src_lines):
                    result.append(src_lines[line_idx].strip())
        return result
    except Exception:
        return []


def _extract_step_descriptions(func):
    """从测试函数源码中提取步骤描述

    提取模式：
    1. 注释: # Step 1: 描述 或 # 步骤1：描述
    2. 打印语句: print("步骤1：描述")
    3. 打印语句: print(f"步骤{step_num}：描述")
    """
    try:
        src_lines, _ = inspect.getsourcelines(func)
        step_descriptions = []

        for line in src_lines:
            stripped = line.strip()

            # 模式1: # Step 1: 描述 或 # 步骤1：描述
            if stripped.startswith("#") and ("Step " in stripped or "步骤" in stripped) and (":" in stripped or "：" in stripped):
                # 分割冒号（支持中英文冒号）
                if "：" in stripped:
                    parts = stripped.split("：", 1)
                else:
                    parts = stripped.split(":", 1)
                if len(parts) == 2:
                    desc = parts[1].strip()
                    step_descriptions.append(desc)

            # 模式2: print("步骤1：描述") 或 print("步骤 1：描述")
            elif "print(" in stripped and "步骤" in stripped and (":" in stripped or "：" in stripped):
                # 提取完整步骤描述（包括"步骤X："部分）
                match = re.search(r'print\(["\']([^"\']+)["\']', stripped)
                if match:
                    full_desc = match.group(1).strip()
                    # 只保留包含"步骤"的描述
                    if "步骤" in full_desc:
                        step_descriptions.append(full_desc)

            # 模式3: print("[Step 1] 描述") 或 print("[步骤1] 描述")
            elif "print(" in stripped and (("[Step " in stripped) or ("[步骤" in stripped)) and "]" in stripped:
                # 提取 [Step X] 或 [步骤X] 后面的描述
                match = re.search(r'\[(?:Step|步骤)\s*\d+\]\s*([^"\'\\]+)', stripped)
                if match:
                    desc = match.group(1).strip()
                    step_descriptions.append(desc)

        return step_descriptions
    except Exception:
        return []


def _extract_step_assertions(func, http_call_count=0):
    """从测试函数源码中提取每个步骤的断言

    支持两种模式：
    1. 有步骤注释标记时：按注释提取（如 # 步骤 1:）
    2. 无步骤注释标记时：按 HTTP 请求顺序自动分配断言

    Args:
        func: 测试函数
        http_call_count: HTTP 请求次数，用于模式 2

    Returns: {step_num: [assertion_lines]}
    """
    try:
        src_lines, start_line = inspect.getsourcelines(func)
        step_assertions = {}
        current_step = None
        has_step_markers = False

        # 第一遍：检测是否有步骤标记
        for line in src_lines:
            stripped = line.strip()
            if stripped.startswith("#") and ("Step " in stripped or "步骤" in stripped) and (":" in stripped or "：" in stripped):
                has_step_markers = True
                break
            if "print(" in stripped and (("[步骤" in stripped) or ("[Step " in stripped)) and "]" in stripped:
                has_step_markers = True
                break

        if has_step_markers:
            # 模式 1：按步骤注释标记提取
            for i, line in enumerate(src_lines):
                stripped = line.strip()

                # 格式 1: # Step 1: 或 # 步骤 1：或 # 步骤 1：
                if stripped.startswith("#") and ("Step " in stripped or "步骤" in stripped) and (":" in stripped or "：" in stripped):
                    match = re.search(r'(?:Step\s+|步骤\s*)(\d+)', stripped)
                    if match:
                        current_step = int(match.group(1))
                        if current_step not in step_assertions:
                            step_assertions[current_step] = []

                # 格式 2: print("[步骤 1] ...") 或 print("[Step 1] ...")
                elif "print(" in stripped and (("[步骤" in stripped) or ("[Step " in stripped)) and "]" in stripped:
                    match = re.search(r'\[(?:步骤|Step)\s*(\d+)\]', stripped)
                    if match:
                        current_step = int(match.group(1))
                        if current_step not in step_assertions:
                            step_assertions[current_step] = []

                # 如果在某个步骤内，收集断言
                if current_step is not None and stripped.startswith("assert "):
                    step_assertions[current_step].append(stripped)
        else:
            # 模式 2：无步骤标记时，按 HTTP 请求顺序自动分配断言
            # 策略：每个 HTTP 请求（requests.get/post/put/delete/patch）后面的断言属于该步骤
            http_step_index = 0

            for i, line in enumerate(src_lines):
                stripped = line.strip()

                # 检测 HTTP 请求开始
                if re.search(r'requests\.(get|post|put|delete|patch)\s*\(', stripped, re.IGNORECASE):
                    http_step_index += 1
                    if http_step_index not in step_assertions:
                        step_assertions[http_step_index] = []
                    continue

                # 收集断言：在 HTTP 请求后、下一个 HTTP 请求前的所有断言
                if stripped.startswith("assert ") and http_step_index > 0:
                    step_assertions[http_step_index].append(stripped)

        return step_assertions
    except Exception:
        return {}




def _parse_failure_comparison(longrepr):
    comparisons = []
    for line in str(longrepr).splitlines():
        stripped = line.strip()
        if stripped.startswith("E ") or stripped.startswith("E\t"):
            text = stripped[2:].strip()
            if text:
                comparisons.append(text)
        elif "AssertionError:" in stripped and "E " not in stripped:
            comparisons.append(stripped)
        elif "AssertionError" in stripped:
            comparisons.append(stripped)
    return comparisons


def _identify_main_http_step(step_calls, source_file):
    """根据测试文件名识别主 HTTP 请求在 step_calls 中的索引。

    从 source_file (如 test_api_post_variable_update.py) 提取
    被测接口的 method + path，匹配 step_calls 中对应的 HTTP 调用。

    Returns:
        主请求在 step_calls 中的索引，无法识别返回 -1
    """
    if not source_file or not source_file.startswith('test_api_'):
        return -1

    name = source_file
    if name.startswith('test_api_'):
        name = name[len('test_api_'):]
    if name.endswith('.py'):
        name = name[:-3]

    parts = name.split('_', 1)
    method_candidates = {'get', 'post', 'put', 'delete', 'patch'}
    if len(parts) < 2 or parts[0].lower() not in method_candidates:
        return -1

    expected_method = parts[0].upper()
    # path_parts: ['variable', 'update'] → 匹配 URL 以 /variable/update 结尾
    path_parts = parts[1].split('_')
    expected_path_suffix = '/' + '/'.join(path_parts)

    for idx, step in enumerate(step_calls):
        if step.get('step_type') != 'http':
            continue
        if step.get('method', '').upper() != expected_method:
            continue
        url = step.get('url', '')
        # 提取路径部分
        if '://' in url:
            after = url.split('://', 1)[1]
            path = '/' + after.split('/', 1)[1] if '/' in after else '/'
        else:
            path = url
        # 去除查询参数
        path = path.split('?')[0]
        if path.endswith(expected_path_suffix):
            return idx

    return -1


# ---------------------------------------------------------------------------
# pytest hooks
# ---------------------------------------------------------------------------

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    # 处理 setup/call/teardown 各阶段的报告
    # setup 阶段的 skip 也需要捕获（如 setup_class 中的 pytest.skip()）
    if call.when == "call":
        # call 阶段：正常处理
        pass
    elif call.when == "setup" and report.skipped:
        # setup 阶段的 skip 也需要记录（如 setup_class 中的 pytest.skip()）
        pass
    elif call.when != "call":
        # 其他阶段（setup/teardown）且不是 skip：
        # 必须清理全局列表，防止 teardown_class 中的 DB/HTTP 操作
        # 残留到下一个测试方法的 call 阶段
        _current_http_calls.clear()
        _current_steps.clear()
        _pending_db_queries.clear()
        return

    http_calls = _current_http_calls.copy()
    step_calls = _current_steps.copy()
    _current_http_calls.clear()
    _current_steps.clear()
    _pending_db_queries.clear()

    # 正确判断测试状态：passed / failed / skipped / error
    if report.passed:
        status = "PASSED"
    elif report.failed:
        status = "FAILED"
    elif report.skipped:
        status = "SKIPPED"
    else:
        status = "ERROR"

    assert_lines = _extract_assert_lines(item.function)

    failure_comparisons = []
    if not report.passed and report.longrepr:
        failure_comparisons = _parse_failure_comparison(report.longrepr)

    # 根据测试状态设置断言状态
    if report.passed:
        # 测试通过：所有断言都标记为 passed
        assertions = [{"expression": line, "status": "passed", "detail": ""} for line in assert_lines]
    elif report.skipped:
        # 测试跳过：所有断言都标记为 skipped（跳过的测试没有实际执行断言）
        assertions = [{"expression": line, "status": "skipped", "detail": "测试被跳过，未实际执行"} for line in assert_lines]
    else:
        # 测试失败：最后一个断言标记为 failed，其他标记为 passed
        assertions = [
            {
                "expression": line,
                "status": "failed" if i == len(assert_lines) - 1 else "passed",
                "detail": "",
            }
            for i, line in enumerate(assert_lines)
        ]

    result = {
        "name": item.name,
        "description": (item.function.__doc__ or "").strip(),
        "status": status,
        "execution_time": (report.duration or 0) * 1000,
        "error_message": str(report.longrepr) if not report.passed else "",
        "assertions": assertions,
        "failure_comparisons": failure_comparisons,
    }

    # 记录来源文件路径（用于报告按文件分组）
    result["_source_file"] = os.path.basename(item.fspath) if hasattr(item, 'fspath') else ""

    # 记录类上下文，供 pytest_sessionfinish 阶段做 class 级场景合并
    if item.cls:
        result["_class_name"] = item.cls.__name__
        result["_class_doc"] = (item.cls.__doc__ or "").strip()

    # 判断是否为场景测试：支持多种命名模式
    # 1. test_scene{N}_step{N}_xxx（显式场景编号）
    # 2. test_step{N}_xxx（无 sceneXX 前缀）
    # 3. test_scenario_XX_*.py 文件中的测试函数（如 test_scenario_01_create_scenario.py）
    scene_name_match = _CLASS_SCENE_PATTERN.match(item.name)
    step_name_match = _STEP_PATTERN.match(item.name)
    scenario_file_match = _SCENARIO_FILE_PATTERN.match(item.name)
    is_scenario_test = scene_name_match or step_name_match or scenario_file_match

    if is_scenario_test and step_calls:
        result["is_scenario"] = True
        result["scenario_steps"] = []

        step_assertions_map = _extract_step_assertions(item.function)
        failed_assertion = None
        if not report.passed and report.longrepr:
            longrepr_str = str(report.longrepr)
            for line in longrepr_str.splitlines():
                stripped = line.strip()
                if stripped.startswith("assert ") or (stripped.startswith(">") and "assert " in stripped):
                    if "assert " in stripped:
                        failed_assertion = stripped.split("assert ", 1)[1].strip()
                        break

        for idx, call_info in enumerate(step_calls, 1):
            step_type = call_info.get("step_type", "http")
            if step_type == "http":
                url = call_info["url"]
                path = url
                if "://" in url:
                    path = "/" + url.split("://", 1)[1].split("/", 1)[1] if "/" in url.split("://", 1)[1] else "/"
                step = {
                    "step_number": idx,
                    "step_name": f"Step {idx}",
                    "step_type": "http",
                    "method": call_info["method"],
                    "url": call_info["url"],
                    "path": path,
                    "headers": call_info["headers"],
                    "params": call_info["params"],
                    "request_body": call_info["request_body"],
                    "status_code": call_info["status_code"],
                    "response_headers": call_info["response_headers"],
                    "response_body": call_info["response_body"],
                    "execution_time": call_info["execution_time"],
                    "duration_ms": call_info["execution_time"],
                    "assertions": [],
                }
            else:
                step = {
                    "step_number": idx,
                    "step_name": f"Step {idx}",
                    "step_type": "db",
                    "method": "DB",
                    "url": "",
                    "path": "DB Query",
                    "headers": {},
                    "params": None,
                    "request_body": None,
                    "status_code": call_info.get("status_code", "OK"),
                    "response_headers": {},
                    "response_body": call_info.get("response_body", ""),
                    "execution_time": call_info.get("execution_time", 0),
                    "duration_ms": call_info.get("duration_ms", 0),
                    "assertions": [],
                    "sql": call_info.get("sql"),
                    "sql_params": call_info.get("sql_params"),
                    "result_count": call_info.get("result_count", 0),
                    "result_preview": call_info.get("result_preview", []),
                    "rowcount": call_info.get("rowcount"),
                    "db_operation": call_info.get("db_operation", "query"),
                }

            if idx in step_assertions_map:
                for assert_line in step_assertions_map[idx]:
                    is_failed = False
                    if failed_assertion and failed_assertion in assert_line:
                        is_failed = True
                    step["assertions"].append({
                        "expression": assert_line,
                        "status": "failed" if is_failed else "passed",
                        "detail": ""
                    })

            result["scenario_steps"].append(step)

        if http_calls:
            first = http_calls[0]
            result.update({
                "url": first["url"],
                "method": first["method"],
                "headers": first["headers"],
                "params": first["params"],
                "request_body": first["request_body"],
                "status_code": first["status_code"],
                "response_headers": first["response_headers"],
                "response_body": first["response_body"],
            })
    elif http_calls:
        result["is_scenario"] = False

        # 当存在多个操作步骤（DB 查询 + HTTP 混合）时，保存完整操作时序
        if len(step_calls) > 1:
            source_file = os.path.basename(item.fspath) if hasattr(item, 'fspath') else ""
            main_idx = _identify_main_http_step(step_calls, source_file)

            if main_idx >= 0:
                # 用主请求填充顶层字段
                main_step = step_calls[main_idx]
                result.update({
                    "url": main_step["url"],
                    "method": main_step["method"],
                    "headers": main_step["headers"],
                    "params": main_step["params"],
                    "request_body": main_step["request_body"],
                    "status_code": main_step["status_code"],
                    "response_headers": main_step["response_headers"],
                    "response_body": main_step["response_body"],
                })
                # 标记每个步骤的角色并保存
                aux_steps = []
                for idx, s in enumerate(step_calls):
                    step_copy = dict(s)
                    if idx < main_idx:
                        step_copy["role"] = "pre"
                    elif idx == main_idx:
                        step_copy["role"] = "main"
                    else:
                        step_copy["role"] = "post"
                    aux_steps.append(step_copy)
                result["auxiliary_steps"] = aux_steps
            else:
                # 无法从文件名识别主请求，回退到原有逻辑
                first = http_calls[0]
                result.update({
                    "url": first["url"],
                    "method": first["method"],
                    "headers": first["headers"],
                    "params": first["params"],
                    "request_body": first["request_body"],
                    "status_code": first["status_code"],
                    "response_headers": first["response_headers"],
                    "response_body": first["response_body"],
                })
                if len(http_calls) > 1:
                    result["additional_calls"] = http_calls[1:]
        else:
            first = http_calls[0]
            result.update({
                "url": first["url"],
                "method": first["method"],
                "headers": first["headers"],
                "params": first["params"],
                "request_body": first["request_body"],
                "status_code": first["status_code"],
                "response_headers": first["response_headers"],
                "response_body": first["response_body"],
            })
    else:
        result["is_scenario"] = False
        result.update({
            "url": "",
            "method": "",
            "headers": {},
            "params": None,
            "request_body": None,
            "status_code": 0,
            "response_headers": {},
            "response_body": "",
        })

    _test_results.append(result)


_CLASS_SCENE_PATTERN = re.compile(r'^test_scene(\d+)_step(\d+)')
# 支持 test_step{N}_xxx 命名模式（无 sceneXX 前缀）
_STEP_PATTERN = re.compile(r'^test_step(\d+)_')
# 支持 TestScenario/TestScene 类名模式（如 TestScenario_05_ExportWord 或 TestScene01CreateReport）
_SCENARIO_CLASS_PATTERN = re.compile(r'^Test(Scene|Scenario)(_?\d*)')
# 支持 test_scenario_XX_*.py 文件中的测试函数（如 test_scenario_01_create_scenario.py）
_SCENARIO_FILE_PATTERN = re.compile(r'^test_scenario_(\d+)_')


def _is_scenario_class(class_name):
    """判断类名是否为场景测试类（如 TestScenario_05_ExportWord 或 TestScene01CreateReport）"""
    return bool(_SCENARIO_CLASS_PATTERN.match(class_name))


def _merge_class_scenario_steps():
    """后处理：将同一 class 下的场景测试方法合并为一条场景结果。

    支持三种模式：

    模式 1: test_scene{NN}_step{N}_xxx（显式场景编号）
      class TestScene01CreateReport:
          def test_scene01_step1_xxx(self): ...
          def test_scene01_step2_xxx(self): ...

    模式 2: test_step{N}_xxx（按 class 聚合，无 sceneXX 前缀）
      class TestScenario_01_NewReport:
          def test_step1_xxx(self): ...
          def test_step2_xxx(self): ...

    模式 3: TestScenario/TestScene 类下的所有方法（自动按类名聚合）
      class TestScenario_05_ExportWord:
          def test_exportWord_fromDatabase(self): ...
          def test_exportWord_fromFrontend(self): ...

    合并后：一条 is_scenario=True 的结果，scenario_steps 包含所有步骤。
    只在有 >=2 个步骤时合并，单步骤保持原样不影响已有逻辑。

    模式 4: test_scenario_XX_*.py 文件中的测试函数（自动按文件聚合）
      test_scenario_01_create_scenario.py:
          def test_create_scenario_normal(self): ...
          def test_create_scenario_missing_name(self): ...
    """
    global _test_results

    merged = []
    i = 0

    # 首先处理 test_scenario_XX_*.py 文件级别的场景（模式 4）
    # 按 source_file 分组，同一文件下的所有测试函数合并为一个场景
    from collections import OrderedDict
    scenario_file_groups = OrderedDict()  # source_file -> [result, ...]

    # 第一遍：收集所有 test_scenario_XX_*.py 的测试结果
    # 按 source_file 分组，同一文件下的所有测试函数合并为一个场景
    for result in _test_results:
        source_file = result.get('_source_file', '')
        name = result.get('name', '')

        # 检查 source_file 是否以 test_scenario_ 开头
        if source_file.startswith('test_scenario_') and source_file.endswith('.py'):
            # 从文件名提取场景编号，如 test_scenario_01_xxx.py → 01
            scene_id_match = re.search(r'test_scenario_(\d+)', source_file)
            if scene_id_match:
                scene_id = scene_id_match.group(1)
                key = f"{scene_id}_{source_file}"
                if key not in scenario_file_groups:
                    scenario_file_groups[key] = {
                        'scene_id': scene_id,
                        'source_file': source_file,
                        'results': []
                    }
                scenario_file_groups[key]['results'].append(result)

    # 标记已处理的 result 索引
    processed_indices = set()

    # 第二遍：合并非单步骤的场景文件
    for key, group_data in scenario_file_groups.items():
        group_results = group_data['results']
        scene_id = group_data['scene_id']
        source_file = group_data['source_file']

        # 只有多步骤才合并为场景，单步骤保持原样
        if len(group_results) > 1:
            # 标记这些结果为已处理
            for r in group_results:
                idx = _test_results.index(r)
                processed_indices.add(idx)

            # 优先使用类 docstring 作为场景描述，其次用文件名
            class_doc = ''
            for r in group_results:
                doc = r.get('_class_doc', '')
                if doc:
                    class_doc = doc
                    break
            if class_doc:
                scene_desc = class_doc
            else:
                scene_desc = source_file.replace('test_scenario_', '').replace('.py', '').replace('_', ' ')
                scene_desc = f'场景 {int(scene_id)}: {scene_desc}'

            merged.append(_build_merged_scenario_from_file(scene_id, scene_desc, group_results, source_file))

    # 第三遍：处理剩余的结果（class-based 场景和非场景测试）
    while i < len(_test_results):
        if i in processed_indices:
            i += 1
            continue

        result = _test_results[i]
        name = result.get('name', '')
        class_name = result.get('_class_name', '')

        # 检查是否为场景类的步骤方法（三种模式）
        scene_match = _CLASS_SCENE_PATTERN.match(name)
        step_match = _STEP_PATTERN.match(name)
        is_scenario_class = _is_scenario_class(class_name)

        if class_name and (scene_match or step_match or is_scenario_class):
            # 发现 class-based 场景的步骤，收集同 class 的连续步骤
            group_class = class_name
            group_results = [result]

            j = i + 1
            while j < len(_test_results):
                next_result = _test_results[j]
                next_name = next_result.get('name', '')
                next_scene_match = _CLASS_SCENE_PATTERN.match(next_name)
                next_step_match = _STEP_PATTERN.match(next_name)
                next_is_scenario_class = _is_scenario_class(next_result.get('_class_name', ''))

                # 同一 class 下的步骤方法（三种模式都支持）
                if next_result.get('_class_name', '') == group_class and (next_scene_match or next_step_match or next_is_scenario_class):
                    group_results.append(next_result)
                    j += 1
                else:
                    break

            if len(group_results) > 1:
                # 多步骤 → 合并为一条场景记录
                # 优先使用 scene_match 中的场景编号，否则用类名提取场景号
                if scene_match:
                    scene_id = scene_match.group(1)
                else:
                    # 从类名提取场景号，如 TestScenario_05_ExportWord → 05
                    scene_id_match = re.search(r'_(\d+)_', class_name)
                    scene_id = scene_id_match.group(1) if scene_id_match else class_name

                merged.append(_build_merged_scenario(scene_id, group_results))
            else:
                # 仅 1 个步骤 → 保持原样，不标记为场景测试
                # 因为它只有一个步骤，作为普通单接口测试展示更合适
                result['is_scenario'] = False
                result.pop('scenario_steps', None)
                merged.append(result)
            i = j
        else:
            merged.append(result)
            i += 1

    _test_results = merged


def _build_merged_scenario(scene_id, group_results):
    """将多个步骤结果合并为一条完整的场景测试记录。"""
    class_doc = group_results[0].get('_class_doc', '') or f'场景 {int(scene_id)}'

    # 综合状态：任一步骤失败则整体失败
    statuses = [r.get('status', 'ERROR') for r in group_results]
    overall_status = 'PASSED' if all(s == 'PASSED' for s in statuses) else 'FAILED'

    # 累计执行时间
    total_time = sum(r.get('execution_time', 0) for r in group_results)

    # 收集错误信息
    error_messages = [r['error_message'] for r in group_results if r.get('error_message')]

    # 构建合并后的 scenario_steps
    scenario_steps = []
    all_assertions = []
    all_failure_comparisons = []

    for step_idx, r in enumerate(group_results, 1):
        step_desc = r.get('description', '') or f'Step {step_idx}'
        existing_steps = r.get('scenario_steps', [])

        if existing_steps:
            # 已有 scenario_steps（单 HTTP 调用被 conftest 包装为 1 步），取出重新编号
            step = dict(existing_steps[0])
            step['step_number'] = step_idx
            step['step_name'] = step_desc
            scenario_steps.append(step)
        elif r.get('url'):
            # 从顶层 HTTP 信息构建步骤（兜底）
            url = r.get('url', '')
            path = url
            if '://' in url:
                after = url.split('://', 1)[1]
                path = '/' + after.split('/', 1)[1] if '/' in after else '/'

            step = {
                'step_number': step_idx,
                'step_name': step_desc,
                'step_type': 'http',
                'method': r.get('method', 'GET'),
                'url': url,
                'path': path,
                'headers': r.get('headers', {}),
                'params': r.get('params'),
                'request_body': r.get('request_body'),
                'status_code': r.get('status_code', 0),
                'response_headers': r.get('response_headers', {}),
                'response_body': r.get('response_body', ''),
                'execution_time': r.get('execution_time', 0),
                'duration_ms': r.get('execution_time', 0),
                'assertions': r.get('assertions', []),
            }
            scenario_steps.append(step)
        else:
            # 没有 HTTP 调用的步骤（如 SKIPPED/ERROR），仍需保留以保持步骤完整性
            step_status = r.get('status', 'SKIPPED')
            step = {
                'step_number': step_idx,
                'step_name': step_desc,
                'step_type': 'skipped' if step_status == 'SKIPPED' else 'error',
                'method': '',
                'url': '',
                'path': '',
                'headers': {},
                'params': None,
                'request_body': None,
                'status_code': 0,
                'response_headers': {},
                'response_body': r.get('error_message', '') or f'步骤状态: {step_status}',
                'execution_time': r.get('execution_time', 0),
                'duration_ms': r.get('execution_time', 0),
                'assertions': r.get('assertions', []),
                'step_status': step_status,
            }
            scenario_steps.append(step)

        all_assertions.extend(r.get('assertions', []))
        all_failure_comparisons.extend(r.get('failure_comparisons', []))

    # 用第一个步骤的 HTTP 信息填充顶层字段
    first = group_results[0]

    return {
        'name': f'scene_{scene_id}_combined',
        'description': class_doc,
        'status': overall_status,
        'execution_time': total_time,
        'error_message': '\n\n'.join(error_messages) if error_messages else '',
        'assertions': all_assertions,
        'failure_comparisons': all_failure_comparisons,
        'is_scenario': True,
        'scenario_steps': scenario_steps,
        'url': first.get('url', ''),
        'method': first.get('method', ''),
        'headers': first.get('headers', {}),
        'params': first.get('params'),
        'request_body': first.get('request_body'),
        'status_code': first.get('status_code', 0),
        'response_headers': first.get('response_headers', {}),
        'response_body': first.get('response_body', ''),
    }


def _build_merged_scenario_from_file(scene_id, scene_desc, group_results, source_file):
    """将同一 test_scenario_XX_*.py 文件中的多个测试函数合并为一条场景记录。"""
    # 综合状态：任一步骤失败则整体失败
    statuses = [r.get('status', 'ERROR') for r in group_results]
    overall_status = 'PASSED' if all(s == 'PASSED' for s in statuses) else 'FAILED'

    # 累计执行时间
    total_time = sum(r.get('execution_time', 0) for r in group_results)

    # 收集错误信息
    error_messages = [r['error_message'] for r in group_results if r.get('error_message')]

    # 构建 scenario_steps
    scenario_steps = []
    all_assertions = []
    all_failure_comparisons = []

    for step_idx, r in enumerate(group_results, 1):
        step_desc = r.get('description', '') or r.get('name', f'Step {step_idx}')
        existing_steps = r.get('scenario_steps', [])

        if existing_steps:
            # 已有 scenario_steps，取出重新编号
            step = dict(existing_steps[0])
            step['step_number'] = step_idx
            step['step_name'] = step_desc
            scenario_steps.append(step)
        elif r.get('url'):
            # 从顶层 HTTP 信息构建步骤
            url = r.get('url', '')
            path = url
            if '://' in url:
                after = url.split('://', 1)[1]
                path = '/' + after.split('/', 1)[1] if '/' in after else '/'

            step = {
                'step_number': step_idx,
                'step_name': step_desc,
                'step_type': 'http',
                'method': r.get('method', 'GET'),
                'url': url,
                'path': path,
                'headers': r.get('headers', {}),
                'params': r.get('params'),
                'request_body': r.get('request_body'),
                'status_code': r.get('status_code', 0),
                'response_headers': r.get('response_headers', {}),
                'response_body': r.get('response_body', ''),
                'execution_time': r.get('execution_time', 0),
                'duration_ms': r.get('execution_time', 0),
                'assertions': r.get('assertions', []),
            }
            scenario_steps.append(step)
        else:
            # 没有 HTTP 调用的步骤（如 SKIPPED/ERROR），仍需保留以保持步骤完整性
            step_status = r.get('status', 'SKIPPED')
            step = {
                'step_number': step_idx,
                'step_name': step_desc,
                'step_type': 'skipped' if step_status == 'SKIPPED' else 'error',
                'method': '',
                'url': '',
                'path': '',
                'headers': {},
                'params': None,
                'request_body': None,
                'status_code': 0,
                'response_headers': {},
                'response_body': r.get('error_message', '') or f'步骤状态: {step_status}',
                'execution_time': r.get('execution_time', 0),
                'duration_ms': r.get('execution_time', 0),
                'assertions': r.get('assertions', []),
                'step_status': step_status,
            }
            scenario_steps.append(step)

        all_assertions.extend(r.get('assertions', []))
        all_failure_comparisons.extend(r.get('failure_comparisons', []))

    # 用第一个测试的 HTTP 信息填充顶层字段
    first = group_results[0]

    return {
        'name': f'scene_{scene_id}_from_file',
        'description': scene_desc,
        'status': overall_status,
        'execution_time': total_time,
        'error_message': '\n\n'.join(error_messages) if error_messages else '',
        'assertions': all_assertions,
        'failure_comparisons': all_failure_comparisons,
        'is_scenario': True,
        'scenario_steps': scenario_steps,
        'source_file': source_file,
        'url': first.get('url', ''),
        'method': first.get('method', ''),
        'headers': first.get('headers', {}),
        'params': first.get('params'),
        'request_body': first.get('request_body'),
        'status_code': first.get('status_code', 0),
        'response_headers': first.get('response_headers', {}),
        'response_body': first.get('response_body', ''),
    }


def pytest_sessionfinish(session, exitstatus):
    # 合并 class-based 场景步骤（同一 class 下的 test_sceneXX_stepN 合并为一条）
    _merge_class_scenario_steps()

    # 清理内部辅助字段，保留 source_file 用于报告分组
    for result in _test_results:
        # 将 _source_file 转为 source_file（公开字段）
        if '_source_file' in result:
            result['source_file'] = result.pop('_source_file')
        result.pop('_class_name', None)
        result.pop('_class_doc', None)

    # TEST_RESULTS_PATH 由 enhanced_execute_with_auth.py 以绝对路径注入
    results_path = os.environ.get("TEST_RESULTS_PATH")
    if not results_path:
        return

    # 只在有测试结果时才写入文件，避免生成空文件
    if not _test_results:
        print("⚠️  没有收集到测试结果，跳过生成 JSON 文件")
        return

    os.makedirs(os.path.dirname(results_path), exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"test_cases": _test_results}, f, ensure_ascii=False, indent=2)
