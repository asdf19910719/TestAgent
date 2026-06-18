#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
接口测试执行器 - 支持 401 鉴权处理
通过 conftest_plugin.py 捕获每个接口的请求/响应详情（包括请求体、响应头），
使用 report_template_fixed.py 生成 HTML 报告。

跨平台编码兼容：
- 使用 UTF-8 编码源文件
- subprocess 输出自动检测 UTF-8/GB18030 编码
- Windows 控制台输出使用 replace 错误处理
"""

import os
import sys
import io
import json
import argparse
import subprocess
import re
from datetime import datetime
from typing import Dict, Any

# 设置标准输出编码为 UTF-8，兼容 Windows 控制台
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass  # 如果失败，使用默认编码

script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from .report_template_fixed import generate_fixed_report


def extract_total_endpoints_from_api_definition(test_file_dir: str) -> int:
    """从 api_definition.json 或 api_definition.jsonl 中提取应测接口总数

    Args:
        test_file_dir: 测试文件所在目录

    Returns:
        应测接口总数
    """
    # 优先检查 api_definition.json（标准 JSON 格式）
    try:
        api_def_path = os.path.join(test_file_dir, 'api_definition.json')
        if os.path.exists(api_def_path):
            with open(api_def_path, 'r', encoding='utf-8') as f:
                api_data = json.load(f)
                return len(api_data.get('apis', []))
    except Exception:
        pass

    # 兼容 api_definition.jsonl（JSONL 格式，每行一个 JSON 对象）
    try:
        api_def_path = os.path.join(test_file_dir, 'api_definition.jsonl')
        if os.path.exists(api_def_path):
            count = 0
            with open(api_def_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        count += 1
            return count
    except Exception:
        pass

    return 0


def extract_endpoints_info_from_test_dir(test_dir_path: str) -> tuple:
    """从测试目录下的所有文件中提取接口列表和源码路径

    Returns:
        (endpoint_list, source_path): 接口列表和源码路径
    """
    endpoint_list = set()
    source_path = None

    try:
        # 遍历目录下所有的 test_*.py 文件
        for filename in os.listdir(test_dir_path):
            if not filename.startswith("test_") or not filename.endswith(".py"):
                continue

            test_file_path = os.path.join(test_dir_path, filename)
            with open(test_file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 查找源码路径信息 (只获取第一个匹配的)
            if source_path is None:
                match = re.search(r'源码路径:\s*(.+)', content)
                if match:
                    temp_path = match.group(1).strip()
                    if temp_path and temp_path != '':
                        if os.path.exists(temp_path):
                            source_path = temp_path

            # 查找接口列表信息
            match = re.search(r'接口列表:\s*(\[[\s\S]*?\])\n', content)
            if match:
                try:
                    endpoint_list_data = json.loads(match.group(1))
                    for ep in endpoint_list_data:
                        endpoint_list.add(f"{ep['method']} {ep['path']}")
                except json.JSONDecodeError:
                    pass

        return list(endpoint_list), source_path
    except Exception:
        return list(endpoint_list), source_path


def _normalize_path_slashes(path: str) -> str:
    """标准化路径斜杠，去除尾部斜杠"""
    if not path:
        return path
    # 去除尾部斜杠，但保留根路径 "/"
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/')
    return path


def _path_matches_pattern(path: str, pattern: str) -> bool:
    """检查路径是否匹配模式（支持 {param} 占位符）"""
    # 先标准化路径，去除尾部斜杠
    path = _normalize_path_slashes(path)
    pattern = _normalize_path_slashes(pattern)

    path_parts = path.strip('/').split('/')
    pattern_parts = pattern.strip('/').split('/')
    if len(path_parts) != len(pattern_parts):
        return False
    for p, q in zip(path_parts, pattern_parts):
        if q.startswith('{') and q.endswith('}'):
            continue
        if p != q:
            return False
    return True


def _match_to_defined_endpoint(method: str, path: str, defined_set: set) -> str:
    """将测试路径归属到已定义的接口（用于处理 404 异常用例路径）

    匹配优先级：
    1. 精确匹配（标准化尾部斜杠后）
    2. 标准化路径参数后精确匹配
    3. 路径模式匹配（{param} 占位符）
    4. 前缀匹配（异常用例路径以定义路径开头）
    """
    if not defined_set:
        return f"{method} {_normalize_path_slashes(path)}"

    # 标准化尾部斜杠
    path = _normalize_path_slashes(path)

    # 1. 精确匹配
    key = f"{method} {path}"
    if key in defined_set:
        return key

    # 检查定义集合中是否有标准化版本
    for defined_key in defined_set:
        parts = defined_key.split(' ', 1)
        if len(parts) != 2:
            continue
        defined_method, defined_path = parts
        if defined_method == method and _normalize_path_slashes(defined_path) == path:
            return defined_key

    # 2. 标准化路径参数后精确匹配
    normalized = _normalize_path_params(path)
    key = f"{method} {normalized}"
    if key in defined_set:
        return key

    # 检查定义集合中是否有标准化版本
    for defined_key in defined_set:
        parts = defined_key.split(' ', 1)
        if len(parts) != 2:
            continue
        defined_method, defined_path = parts
        if defined_method == method and _normalize_path_slashes(_normalize_path_params(defined_path)) == normalized:
            return defined_key

    # 3. 路径模式匹配（处理 {param} 占位符）
    for defined_key in defined_set:
        parts = defined_key.split(' ', 1)
        if len(parts) != 2:
            continue
        defined_method, defined_path = parts
        if defined_method != method:
            continue
        if _path_matches_pattern(path, defined_path):
            return defined_key

    # 4. 前缀匹配（处理异常用例路径以定义路径开头，如 /a/1 归属到 /a）
    best_match = None
    best_match_len = 0
    for defined_key in defined_set:
        parts = defined_key.split(' ', 1)
        if len(parts) != 2:
            continue
        defined_method, defined_path = parts
        if defined_method != method:
            continue
        defined_path_normalized = _normalize_path_slashes(defined_path)
        if (path == defined_path_normalized or path.startswith(defined_path_normalized + '/')) and len(defined_path_normalized) > best_match_len:
            best_match = defined_key
            best_match_len = len(defined_path_normalized)

    if best_match:
        return best_match

    return f"{method} {normalized}"


def extract_tested_endpoints_from_results(test_results: Dict[str, Any], defined_endpoints: list = None) -> int:
    """从测试结果中提取实测接口数（去重）

    Args:
        test_results: 测试结果数据，包含 test_cases 列表
        defined_endpoints: 已定义的接口列表（"METHOD /path" 格式），用于将异常用例路径归属到正确接口

    Returns:
        实测接口数（去重后）
    """
    tested_endpoints = set()
    defined_set = set(defined_endpoints) if defined_endpoints else set()
    test_cases = test_results.get('test_cases', [])

    for case in test_cases:
        # 从单接口测试用例中提取接口
        if not case.get('is_scenario'):
            url = case.get('url', '')
            method = case.get('method', '').upper()

            if url and method:
                # 从完整 URL 中提取路径部分
                path = _extract_path_from_url(url)
                if path:
                    endpoint_key = _match_to_defined_endpoint(method, path, defined_set)
                    tested_endpoints.add(endpoint_key)

        # 从场景测试的步骤中提取接口
        if case.get('is_scenario') and case.get('scenario_steps'):
            for step in case['scenario_steps']:
                step_method = step.get('method', '').upper()
                step_path = step.get('path', '')
                if step_method and step_path:
                    endpoint_key = _match_to_defined_endpoint(step_method, step_path, defined_set)
                    tested_endpoints.add(endpoint_key)

    return len(tested_endpoints)


def _normalize_path_params(path: str) -> str:
    """标准化路径参数，将具体值替换为占位符

    Args:
        path: 接口路径

    Returns:
        标准化后的路径

    Examples:
        /review/getReviewDetail/2f034432-e45a-4e87-a953-5992e45d44ff -> /review/getReviewDetail/{id}
        /review/getReviewDetail/test_review_id -> /review/getReviewDetail/{id}
        /reviewRecord/startReview/123 -> /reviewRecord/startReview/{id}
    """
    if not path:
        return path

    # 先移除基础路径前缀（如果存在）
    # 例如：/cyxt/gateway/tm/review/add -> /review/add
    if '/gateway/tm/' in path:
        path = path.split('/gateway/tm/', 1)[1]
        if not path.startswith('/'):
            path = '/' + path

    # 替换 UUID 格式的参数 (8-4-4-4-12)
    path = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=/|$)', '/{id}', path, flags=re.IGNORECASE)

    # 替换 test_xxx 格式的测试数据
    path = re.sub(r'/test_[a-zA-Z0-9_]+(?=/|$)', '/{id}', path)

    # 替换纯数字 ID (路径末尾或后面跟/)
    # 但要避免替换路径中有意义的数字，如 /api/v1/users
    # 只替换看起来像 ID 的长数字串（3 位以上）
    path = re.sub(r'/\d{3,}(?=/|$)', '/{id}', path)

    return path


def _extract_path_from_url(url: str) -> str:
    """从完整 URL 中提取路径部分并标准化

    Args:
        url: 完整 URL

    Returns:
        标准化后的路径部分
    """
    if not url:
        return ''

    # 移除协议和域名
    # http://example.com/api/users?id=1 -> /api/users
    match = re.search(r'https?://[^/]+(/[^?#]*)', url)
    if match:
        path = match.group(1)
        return _normalize_path_params(path)

    # 如果已经是路径格式
    if url.startswith('/'):
        # 移除查询参数
        path = url.split('?')[0].split('#')[0]
        return _normalize_path_params(path)

    return url


def extract_auth_header_from_test_dir(test_dir_path: str) -> tuple:
    """从测试目录下的任一测试文件中提取当前的 Authorization 头"""
    for filename in os.listdir(test_dir_path):
        if not filename.startswith("test_") or not filename.endswith(".py"):
            continue

        test_file_path = os.path.join(test_dir_path, filename)
        with open(test_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        match = re.search(r"'Authorization':\s*'([^']*)'", content)
        if match:
            return match.group(1), content

    return None, ""


def update_auth_in_test_dir(test_dir_path: str, old_auth: str, new_auth: str):
    """更新测试目录中所有测试文件中的 Authorization 头"""
    for filename in os.listdir(test_dir_path):
        if not filename.startswith("test_") or not filename.endswith(".py"):
            continue

        test_file_path = os.path.join(test_dir_path, filename)
        with open(test_file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if old_auth in content:
            with open(test_file_path, "w", encoding="utf-8") as f:
                f.write(content.replace(old_auth, new_auth))


def run_tests_and_collect_results(test_target: str, results_json_path: str) -> Dict[str, Any]:
    """运行 pytest 并收集每个接口的测试结果

    Args:
        test_target: 测试目标，可以是目录路径或具体的 .py 文件路径
        results_json_path: 测试结果 JSON 输出路径
    """
    # 确定 pytest 的工作目录
    if os.path.isfile(test_target):
        cwd = os.path.dirname(os.path.abspath(test_target))
    else:
        cwd = test_target

    env = os.environ.copy()
    env["TEST_RESULTS_PATH"] = os.path.abspath(results_json_path)
    # 不需要修改 PYTHONPATH，使用模块路径加载 conftest

    # 设置 PYTHONIOENCODING 为 utf-8，并设置 unbuffered 输出
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"  # 禁用 Python 输出缓冲

    # 使用完整包路径加载 conftest_plugin
    cmd = [sys.executable, "-m", "pytest", test_target, "-v", "--tb=short",
           "-p", "qa_agent.adapters.backend.api_executor.conftest_plugin", "--color=no"]

    print("\n" + "=" * 60)
    print("[INFO] 开始执行测试，实时进度如下：")
    print("=" * 60 + "\n")

    # 使用 Popen 实现实时输出
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=env
    )

    # 定义进度符号（使用 ASCII 兼容符号，避免 Windows 控制台编码问题）
    SYMBOLS = {
        'pass': '[OK]',
        'fail': '[FAIL]',
        'error': '[ERR]',
        'collect': '[COLLECT]',
        'info': '[INFO]',
        'success': '[OK]',
        'warning': '[WARN]'
    }

    try:
        # 使用非阻塞方式读取输出
        import threading

        # 统计变量需要在内部线程中更新，用锁保护
        import threading as _th
        stats_lock = _th.Lock()
        total_collected = [0]  # 用列表包装以便在内部函数中修改
        passed_collected = [0]
        failed_collected = [0]

        def decode_line(line_bytes):
            """解码一行字节流，尝试 UTF-8，失败则用 GB18030"""
            try:
                return line_bytes.decode('utf-8').rstrip()
            except UnicodeDecodeError:
                return line_bytes.decode('gb18030', errors='replace').rstrip()

        def read_output():
            """在后台线程中实时读取并输出 pytest 进度"""
            try:
                for line_bytes in iter(process.stdout.readline, b''):
                    if not line_bytes:
                        break
                    line = decode_line(line_bytes)

                    # 实时打印所有输出行
                    print(line, flush=True)

                    # 统计测试用例结果
                    if line.startswith("test_") and ("PASSED" in line or "FAILED" in line or "ERROR" in line):
                        match = re.match(r'(test_\S+\.py::\S+)\s+(PASSED|FAILED|ERROR)', line)
                        if match:
                            with stats_lock:
                                total_collected[0] += 1
                                if match.group(2) == "PASSED":
                                    passed_collected[0] += 1
                                else:
                                    failed_collected[0] += 1
            except Exception:
                pass

        # 启动读取线程
        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()

        # 等待 pytest 进程结束
        process.wait()

        # 等待读取线程完成（最多等 5 秒）
        reader_thread.join(timeout=5)

        # 从列表中取出最终统计
        with stats_lock:
            total_collected = total_collected[0]
            passed_collected = passed_collected[0]
            failed_collected = failed_collected[0]

    except KeyboardInterrupt:
        # 用户中断（Ctrl+C），终止进程并输出提示
        print("\n\n[WARN] 检测到用户中断，正在终止测试进程...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        print("[INFO] 测试已终止，部分结果可能未保存。")
        # 尝试读取已有的测试结果
        if os.path.exists(results_json_path):
            with open(results_json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"test_cases": [], "interrupted": True}

    print(f"\n测试执行完成，返回码：{process.returncode}")
    print(f"实时统计：通过 {passed_collected}/{total_collected}, 失败 {failed_collected}/{total_collected}")

    if os.path.exists(results_json_path):
        with open(results_json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return {"test_cases": []}


def _has_401_error(test_results: Dict[str, Any]) -> bool:
    """判断测试结果中是否存在 401 错误"""
    for case in test_results.get("test_cases", []):
        if case.get("status_code") == 401:
            return True
        err = case.get("error_message", "")
        if "401" in err or "Unauthorized" in err or "权限认证失败" in err:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description="接口测试执行器 - 支持 401 鉴权处理")
    parser.add_argument("--test-dir", required=True, help="测试脚本所在目录或具体的 .py 测试文件")
    parser.add_argument("--report-dir", required=False, default=None, help="报告输出目录（可选，默认生成到 --test-dir 所在目录）")
    args = parser.parse_args()

    # 判断 --test-dir 是文件还是目录
    test_target = args.test_dir
    if os.path.isfile(test_target):
        test_file = os.path.abspath(test_target)
        test_dir_for_context = os.path.dirname(test_file)
    elif os.path.isdir(test_target):
        test_file = None
        test_dir_for_context = os.path.abspath(test_target)
    else:
        print(f"错误：--test-dir 指定的路径不存在：{test_target}")
        sys.exit(1)

    # --report-dir 默认为测试目录
    report_dir = args.report_dir if args.report_dir else test_dir_for_context
    os.makedirs(report_dir, exist_ok=True)

    # 生成时间戳，从一开始就使用带时间戳的文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_json_path = os.path.join(report_dir, f"test_results_{timestamp}.json")

    # 确定 pytest 的执行目标：具体文件或整个目录
    pytest_target = test_file if test_file else test_dir_for_context

    print("开始执行接口测试...")
    test_results = run_tests_and_collect_results(pytest_target, results_json_path)

    # 检查是否有测试结果，如果没有则不生成报告
    if not test_results.get("test_cases"):
        print("\n警告：没有收集到测试结果，可能是测试执行失败。")
        print("请检查测试脚本是否正确，以及是否安装了必要的依赖（pytest, requests 等）。")
        return

    # 检测到 401 错误时，不再交互式询问用户，直接继续后续流程
    if _has_401_error(test_results):
        print("\n" + "=" * 60)
        print("检测到 401 权限认证错误！")
        print("建议检查 test_data_config.json 或测试脚本中的 Authorization 配置。")
        print("=" * 60)

    passed = sum(1 for c in test_results.get("test_cases", []) if c.get("status") == "PASSED")
    total = len(test_results.get("test_cases", []))
    print(f"\n测试执行完成！通过：{passed}/{total}")

    # 从 api_definition.jsonl 中提取应测接口总数
    total_endpoints = extract_total_endpoints_from_api_definition(test_dir_for_context)

    # 从测试目录中提取接口列表和源码路径
    endpoint_list, source_path = extract_endpoints_info_from_test_dir(test_dir_for_context)

    # 从测试结果中提取实测接口数（去重），传入已定义接口列表以正确归属异常用例路径
    tested_endpoints_count = extract_tested_endpoints_from_results(test_results, endpoint_list)

    # 构建接口覆盖度信息
    # 应测接口数 = api_definition.jsonl 中的接口数
    # 实测接口数 = test_results.json 中的去重接口数
    # 覆盖度 = 实测接口数 / 应测接口数
    # 注意：实测接口数不能超过应测接口数，覆盖率最多为 100%
    if tested_endpoints_count > total_endpoints:
        tested_endpoints_count = total_endpoints

    endpoints_info = {
        "total_endpoints": total_endpoints,
        "tested_endpoints": tested_endpoints_count,
        "coverage": round(tested_endpoints_count / total_endpoints * 100, 2) if total_endpoints > 0 else 0,
        "endpoint_list": endpoint_list,
        "source_path": source_path
    }

    # 生成基础 HTML 报告（包含接口覆盖度，但不包含智能分析）
    report_path = os.path.join(report_dir, f"report_{timestamp}.html")

    # 创建一个占位的分析结果，标记为"等待 AI 分析"
    placeholder_analysis = {
        "status": "pending",
        "message": "⏳ 智能分析进行中，请稍候...",
        "endpoints_info": endpoints_info
    }

    generate_fixed_report(test_results, report_path, placeholder_analysis)
    print(f"\n详细测试报告已生成：{report_path}")

    # 更新已有的测试结果文件，添加元数据供 AI 分析使用
    with open(results_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 添加元数据
    data.update({
        "total_endpoints": total_endpoints,
        "endpoint_list": endpoint_list,
        "source_path": source_path,
        "test_dir": test_dir_for_context,
        "timestamp": timestamp,
        "report_path": report_path,
        "endpoints_info": endpoints_info
    })

    with open(results_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 输出结构化摘要，供 skill 后续步骤使用
    print("\n" + "=" * 80)
    print("测试执行完成")
    print("=" * 80)
    print(f"测试结果：{results_json_path}")
    print(f"HTML 报告：{report_path}")
    print(f"源码路径：{source_path}")
    print(f"接口覆盖：{tested_endpoints_count}/{total_endpoints} ({endpoints_info['coverage']}%)")


if __name__ == "__main__":
    main()
