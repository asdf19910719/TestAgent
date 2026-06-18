#!/usr/bin/env python3
"""
WebUI 批量测试执行脚本
通过 pytest 批量执行 Playwright 测试脚本，协调截图、视频录制和结果采集。
执行完成后生成结构化的测试结果和执行摘要。
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Session Sentinel ──────────────────────────────────────────────────
#
# sentinel 绑定到 {workspace}/qa/webui/session/ —— 即"当前活跃会话"目录。
# 生命周期约束：
#   - 主 Agent 在启动新会话时会重建 webui-session/ 目录，旧 sentinel 随目录清除。
#   - 如果目录未被清除（同一会话内多次调用 batch_run.py），sentinel 正常累积。
#   - 跨会话串扰场景：旧 session 遗留的 sentinel 会阻止新执行 → 用 --force-reopen 重置。

SENTINEL_FILE_NAME = '.session_sentinel.json'

# 预算上限（默认值，可被 repair_loop 配置覆盖）
BUDGET_MAX_ROUNDS = 3           # 默认最多 3 轮
BUDGET_MAX_WALL_CLOCK = 1800    # 默认 30 分钟
BUDGET_ABSOLUTE_MAX = 10        # 绝对上限（即使 --force-reopen 也不能突破）

_SESSION_BASE_DEFAULT = 'qa/webui/session'

# ── 失败分类 → lesson scope 映射 ────────────────────────────────────
_CLASSIFICATION_SCOPE = {
    'intercepted_click': '通用/点击交互',
    'selector_not_found': '通用/选择器',
    'spa_timing': '通用/页面加载',
    'strict_mode': '通用/选择器',
    'hidden_element': '通用/元素可见性',
    'navigation_failure': '通用/页面导航',
    'authentication': '通用/登录认证',
    'assertion': '通用/断言验证',
    'environment': '通用/环境依赖',
    'environment_failure': '通用/环境就绪',
}
_CLASSIFICATION_PATTERN = {
    'intercepted_click': '元素被遮挡导致点击拦截',
    'selector_not_found': '选择器未找到目标元素',
    'spa_timing': '页面异步渲染未完成导致超时',
    'strict_mode': '选择器匹配到多个元素 (strict mode)',
    'hidden_element': '目标元素不可见或在视口外',
    'navigation_failure': '页面导航失败',
    'authentication': '登录态失效或认证跳转',
    'assertion': '业务断言不通过',
    'environment': '运行环境依赖缺失',
    'environment_failure': '环境就绪检查失败 (readiness gate skip)',
}
_CLASSIFICATION_DEFAULT_FIX = {
    'intercepted_click': '使用 resilient_click fixture 或操作前等待遮挡层消失',
    'selector_not_found': '使用 smart XPath 或增加选择器上下文约束',
    'spa_timing': '用 wait_for(state="visible") 等具体元素，避免固定等待',
    'strict_mode': '缩小选择器作用域或使用 .nth(0)',
    'hidden_element': '先 scroll_into_view 或 hover 使元素可见',
    'navigation_failure': '检查网络连通性和目标 URL 可用性',
    'authentication': '重新执行登录流程刷新 login-state.json',
    'assertion': '检查断言条件是否匹配当前页面状态',
    'environment': '检查 PYTHONPATH 和模块依赖安装',
    'environment_failure': '检查网络连通性、登录态有效性和目标 URL',
}


def _resolve_session_base(workspace):
    """通过根指针获取当前会话的 sessionBase，降级时自动跟随动态路径。"""
    pointer = Path(workspace) / 'qa/webui' / 'current_session.json'
    if pointer.exists():
        try:
            data = json.loads(pointer.read_text(encoding='utf-8'))
            sb = data.get('sessionBase', '')
            if sb:
                return sb
        except (json.JSONDecodeError, OSError):
            pass
    return _SESSION_BASE_DEFAULT


def _sentinel_path(workspace):
    return Path(workspace) / _resolve_session_base(workspace) / SENTINEL_FILE_NAME


def _read_sentinel(workspace):
    p = _sentinel_path(workspace)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        'status': 'running',
        'execution_rounds': 0,
        'wall_clock_seconds': 0,
        'created_at': datetime.now().astimezone().isoformat(),
    }


def _write_sentinel(workspace, data):
    p = _sentinel_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    data['updated_at'] = datetime.now().astimezone().isoformat()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    rounds = data.get('execution_rounds', 0)
    status = data.get('status', '?')
    print(f'[sentinel] rounds={rounds} status={status} path={p}')


def _check_final_review_exists(workspace):
    sb = _resolve_session_base(workspace)
    review_path = Path(workspace) / sb / 'review' / 'final-review.md'
    return review_path.exists()


import re as _re_mod

_LESSON_SELECTOR_RE = _re_mod.compile(r'locator\(["\'](.+?)["\']\)')
_LESSON_XPATH_RE = _re_mod.compile(r"xpath=([^\s'\")\]]+)")
_LESSON_INTERCEPT_RE = _re_mod.compile(
    r'<(\S+?)[\s>].*?intercept|intercept.*?<(\S+?)[\s>]'
    r'|element.*?pointer.*?at.*?<(\S+)',
    _re_mod.IGNORECASE,
)
_LESSON_TIMEOUT_RE = _re_mod.compile(r'Timeout\s+(\d[\d.]*)\s*ms', _re_mod.IGNORECASE)


def _extract_selector_from_error(error_message: str) -> str:
    """Extract the most specific selector mentioned in a Playwright error message."""
    m = _LESSON_SELECTOR_RE.search(error_message)
    if m:
        return m.group(1)
    m = _LESSON_XPATH_RE.search(error_message)
    if m:
        return f'xpath={m.group(1)}'
    return ''


def _extract_root_cause_line(error_message: str) -> str:
    """Pick the most informative line from error_message for root_cause."""
    if not error_message:
        return ''
    priority_keywords = (
        'Timeout', 'strict mode', 'intercept', 'not visible',
        'waiting for', 'expected to be', 'element is', 'locator resolved',
    )
    lines = [
        ln.strip() for ln in error_message.split('\n')
        if ln.strip()
        and not ln.strip().startswith(('qa/webui/', 'E ', '> '))
        and 'Traceback' not in ln
        and 'File "' not in ln
    ]
    for ln in lines:
        if any(kw.lower() in ln.lower() for kw in priority_keywords):
            return ln[:200]
    e_lines = [
        ln.strip()[2:].strip() for ln in error_message.split('\n')
        if ln.strip().startswith('E ') and len(ln.strip()) > 4
    ]
    if e_lines:
        return e_lines[-1][:200]
    return lines[-1][:200] if lines else ''


def _auto_extract_lessons(results_path: Path, workspace: Path, target_url: str):
    """从本轮测试结果自动提取失败经验写入 lessons 库。

    按 failure_classification 去重汇总，同一分类只生成一条 lesson。
    codegen_lessons 内置的 scope+pattern 去重机制防止跨轮重复写入（hit_count 递增）。
    自动提取的 lesson confidence='low'，优先级低于 LLM 手动写入的经验。
    """
    mod_path = Path(__file__).resolve().parent / 'codegen_lessons.py'
    if not mod_path.exists():
        return
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location('codegen_lessons', str(mod_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        return

    if not results_path.exists():
        return
    try:
        rd = json.loads(results_path.read_text(encoding='utf-8'))
    except Exception:
        return

    if not target_url:
        ctx_path = workspace / _resolve_session_base(workspace) / 'session-context.json'
        if ctx_path.exists():
            try:
                target_url = json.loads(
                    ctx_path.read_text(encoding='utf-8')).get('targetUrl', '')
            except Exception:
                pass
    if not target_url:
        return

    classification_groups = {}
    for tc in rd.get('test_cases', []):
        st = tc.get('status', '').upper()
        fc = tc.get('failure_classification', '')
        if st in ('FAILED', 'ERROR'):
            if not fc or fc == 'unknown':
                continue
            classification_groups.setdefault(fc, []).append(tc)
        elif st == 'SKIPPED' and fc == 'environment_failure':
            classification_groups.setdefault(fc, []).append(tc)

    if not classification_groups:
        return

    added = 0
    for classification, cases in classification_groups.items():
        representative = cases[0]
        err_msg = representative.get('error_message', '')
        fg = representative.get('fix_guidance', {})

        selector = fg.get('failed_selector', '') or _extract_selector_from_error(err_msg)

        suggestions = fg.get('suggestions', [])
        fix_text = '; '.join(suggestions) if suggestions else ''
        if not fix_text:
            fix_text = _CLASSIFICATION_DEFAULT_FIX.get(classification, '')
        if selector and fix_text and selector not in fix_text:
            fix_text = f'选择器 `{selector[:80]}` — {fix_text}'

        root_cause = _extract_root_cause_line(err_msg) or classification

        scope = _CLASSIFICATION_SCOPE.get(classification, f'通用/{classification}')
        base_pattern = _CLASSIFICATION_PATTERN.get(classification, classification)
        if selector:
            sel_short = selector if len(selector) <= 60 else selector[:57] + '...'
            pattern = f'{base_pattern} ({sel_short})'
        else:
            pattern = base_pattern

        lesson = {
            'scope': scope,
            'pattern': pattern,
            'root_cause': root_cause,
            'fix': fix_text,
            'severity': 'high' if len(cases) >= 3 else 'medium',
            'confidence': 'low',
            'source': 'auto_batch_run',
        }
        try:
            mod.add_lesson(str(workspace), target_url, lesson)
            added += 1
        except Exception:
            pass

    if added:
        print(f'  [lessons] 自动提取 {added} 条失败经验 (confidence=low)')


# Extensions considered suspicious when found as new files in workspace root.
_ROOT_POLLUTION_EXTENSIONS = {'.py', '.png', '.json', '.html', '.webm', '.log'}

# Exact filenames in workspace root that are legitimate project config files.
_ROOT_ALLOWLIST_EXACT = {
    '.gitignore', '.python-version', '.env',
    'package.json', 'package-lock.json', 'tsconfig.json',
    'requirements.txt', 'pyproject.toml', 'setup.cfg',
}


def _snapshot_root_files(workspace):
    """Return set of filenames (not dirs) in workspace root matching pollution extensions."""
    root = Path(workspace)
    try:
        return {
            f.name for f in root.iterdir()
            if f.is_file()
            and f.suffix in _ROOT_POLLUTION_EXTENSIONS
            and f.name not in _ROOT_ALLOWLIST_EXACT
        }
    except OSError:
        return set()


def _check_root_pollution(before_snapshot, workspace):
    """Compare current root files against pre-execution snapshot.
    Returns list of newly created files (only files, dirs are ignored by snapshot)."""
    after = _snapshot_root_files(workspace)
    return sorted(after - before_snapshot)


def parse_viewport(viewport_str):
    """
    解析视口尺寸字符串。

    Args:
        viewport_str: 格式为 "WxH" 的字符串，如 "1280x720"

    Returns:
        tuple: (width, height)
    """
    try:
        w, h = viewport_str.lower().split('x')
        return int(w), int(h)
    except ValueError:
        print(f'  警告: 视口尺寸格式错误 "{viewport_str}"，使用默认值 1920x1080')
        return 1920, 1080


def setup_directories(report_dir, run_timestamp):
    """
    创建执行所需的输出目录。

    Args:
        report_dir: 报告根目录
        run_timestamp: 本次运行的时间戳字符串（如 20260312143000）

    Returns:
        dict: 各子目录路径
    """
    dirs = {
        'report': Path(report_dir),
        'screenshots': Path(report_dir) / 'screenshots',
        'videos': Path(report_dir) / 'videos' / run_timestamp,
        'videos_root': Path(report_dir) / 'videos',
        'logs': Path(report_dir) / 'logs',
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def find_conftest_plugin():
    """
    查找 conftest_webui_plugin.py 的路径。
    优先从当前脚本所在目录查找。

    Returns:
        Path or None: 插件文件路径
    """
    script_dir = Path(__file__).parent.resolve()

    # 查找路径优先级
    candidates = [
        script_dir / 'conftest_webui_plugin.py',
        script_dir.parent / 'scripts' / 'conftest_webui_plugin.py',
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def build_pytest_command(args, dirs, conftest_path, results_path):
    """
    构建 pytest 执行命令。

    Args:
        args: 命令行参数
        dirs: 目录路径字典
        conftest_path: conftest 插件路径
        results_path: 测试结果 JSON 输出路径

    Returns:
        list: 命令参数列表
    """
    cmd = [
        sys.executable, '-m', 'pytest',
        str(args.test_file),
        '-v',                          # 详细输出
        '--tb=short',                  # 简短的错误回溯
        '-p', 'no:cacheprovider',      # 禁用缓存（避免 .pytest_cache 污染工作空间）
        '-p', 'no:html',              # 禁用 pytest-html（报告由 generate_webui_html_report.py 生成）
        '-p', 'pytest_playwright',     # 显式加载 pytest-playwright（某些环境下 entry point 自动注册会失败）
        '--browser', args.browser,      # 激活 pytest-playwright 的 page/context/browser fixture
        '--override-ini=addopts=',     # 清空用户 pytest.ini/pyproject.toml 中的 addopts，防止注入 --html
    ]

    # 加载 conftest 插件
    if conftest_path:
        # 将插件所在目录添加到 conftest 搜索路径
        cmd.extend(['--confcutdir', str(conftest_path.parent)])
        # 通过 conftest_paths 传入（pytest 会自动加载同目录下的 conftest）
        # 更可靠的方式：将插件目录加入 Python 路径
        cmd.extend(['-p', 'conftest_webui_plugin'])

    # 超时设置：仅当 pytest-timeout 已安装时才传 --timeout 参数
    import importlib.util as _imputil
    if _imputil.find_spec('pytest_timeout'):
        per_test_timeout = getattr(args, 'timeout', 120) or 120
        cmd.extend([f'--timeout={per_test_timeout}'])

    return cmd


def setup_environment(args, dirs, results_path):
    """
    设置测试执行所需的环境变量。

    Args:
        args: 命令行参数
        dirs: 目录路径字典
        results_path: 测试结果文件路径

    Returns:
        dict: 环境变量字典
    """
    env = os.environ.copy()

    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'

    # 核心路径环境变量
    env['TEST_RESULTS_PATH'] = str(results_path)
    env['SCREENSHOT_DIR'] = str(dirs['screenshots'])
    env['VIDEO_DIR'] = str(dirs['videos'])
    env['LOG_DIR'] = str(dirs['logs'])

    # 浏览器配置
    env['BROWSER_TYPE'] = args.browser
    # 强制无头模式：忽略 args.headless 的值，始终设为 '1'
    # 唯一例外：环境变量 FORCE_HEADED=1（供人工调试使用）
    env['HEADLESS'] = '0' if os.environ.get('FORCE_HEADED') == '1' else '1'

    # 视口尺寸
    vw, vh = parse_viewport(args.viewport)
    env['VIEWPORT_WIDTH'] = str(vw)
    env['VIEWPORT_HEIGHT'] = str(vh)

    # 截图和视频开关
    env['SCREENSHOT_ON_FAILURE'] = '1' if args.screenshot_on_failure else '0'
    env['SCREENSHOT_ALWAYS'] = '1' if getattr(args, 'screenshot_always', False) else '0'
    env['VIDEO_ENABLED'] = '1' if args.video else '0'

    # 工作空间路径
    env['WORKSPACE'] = str(Path(args.workspace).resolve())

    # SPA 二段等待毫秒数（传递给 conftest readiness gate）
    spa_wait = getattr(args, 'spa_wait_ms', None)
    if spa_wait is not None:
        env['SPA_WAIT_MS'] = str(spa_wait)

    # 被测目标 URL（供 conftest 写入结果元数据）
    if args.target_url:
        env['TARGET_URL'] = args.target_url

    # 登录状态文件（如果存在）
    login_state = Path(args.workspace).resolve() / 'qa/webui' / 'shared_assets' / 'ui-elements' / 'login-state.json'
    if login_state.exists():
        env['LOGIN_STATE_PATH'] = str(login_state)

    return env


def generate_exec_summary(results_path, dirs, start_time, end_time, pytest_returncode,
                          run_timestamp, retry_info=None, sentinel_data=None):
    """
    根据测试结果生成执行摘要。

    Args:
        results_path: 测试结果 JSON 文件路径
        dirs: 目录路径字典
        start_time: 执行开始时间
        end_time: 执行结束时间
        pytest_returncode: pytest 退出码
        run_timestamp: 本次运行的时间戳字符串
        retry_info: 重试信息字典（可选）
        sentinel_data: sentinel 字典（可选，提供 execution_round / stop_reason）

    Returns:
        dict: 执行摘要
    """
    summary = {
        'run_timestamp': run_timestamp,
        'execution_time': {
            'start': start_time.isoformat(),
            'end': end_time.isoformat(),
            'duration_ms': round((end_time - start_time).total_seconds() * 1000, 2),
            'duration_seconds': (end_time - start_time).total_seconds(),
            'duration_display': f'{(end_time - start_time).total_seconds():.1f}s',
        },
        'schema_version': '1.0',
        'pytest_exit_code': pytest_returncode,
        'total': 0,
        'passed': 0,
        'failed': 0,
        'error': 0,
        'skipped': 0,
        'pass_rate': '0%',
        'screenshots': [],
        'videos': [],
        'results_file': str(results_path),
    }

    # 读取测试结果
    results_file = Path(results_path)
    if results_file.exists():
        try:
            results_data = json.loads(results_file.read_text(encoding='utf-8'))
            test_cases = results_data.get('test_cases', [])
            summary['total'] = len(test_cases)

            for tc in test_cases:
                status = tc.get('status', 'ERROR').upper()
                if status == 'PASSED':
                    summary['passed'] += 1
                elif status == 'FAILED':
                    summary['failed'] += 1
                elif status == 'ERROR':
                    summary['error'] += 1
                elif status == 'SKIPPED':
                    summary['skipped'] += 1

                # 收集截图
                screenshots = tc.get('screenshots', [])
                summary['screenshots'].extend(screenshots)

                # 收集视频
                video = tc.get('video', '')
                if video:
                    summary['videos'].append(video)

            if summary['total'] > 0:
                rate = summary['passed'] / summary['total'] * 100
                summary['pass_rate'] = f'{rate:.1f}%'

        except (json.JSONDecodeError, KeyError) as e:
            print(f'  警告: 读取测试结果文件失败: {e}')
    else:
        print(f'  警告: 测试结果文件不存在: {results_path}')

    # Current run counts (from test_results references)
    summary['current_run_screenshots'] = len(summary.get('screenshots', []))
    summary['current_run_videos'] = len(summary.get('videos', []))

    # Directory-level totals (cumulative across all runs)
    screenshots_dir = dirs['screenshots']
    if screenshots_dir.exists():
        png_files = list(screenshots_dir.glob('*.png'))
        summary['dir_total_screenshot_count'] = len(png_files)
    else:
        summary['dir_total_screenshot_count'] = 0

    videos_dir = dirs['videos']
    if videos_dir.exists():
        video_files = list(videos_dir.glob('*.webm'))
        summary['dir_total_video_count'] = len(video_files)
    else:
        summary['dir_total_video_count'] = 0

    # Backward-compatible aliases
    summary['screenshot_count'] = summary['dir_total_screenshot_count']
    summary['video_count'] = summary['dir_total_video_count']
    summary['video_dir'] = str(dirs['videos'])

    # 重试信息
    if retry_info:
        summary['retry'] = retry_info

    # 失败/通过用例名列表 + 修复建议（P1-1/P1-3）
    failed_cases = []
    passed_cases = []
    fix_guidance_list = []
    results_file_r = Path(results_path)
    if results_file_r.exists():
        try:
            rd2 = json.loads(results_file_r.read_text(encoding='utf-8'))
            for tc in rd2.get('test_cases', []):
                st = tc.get('status', '').upper()
                name = tc.get('name', '')
                if st in ('FAILED', 'ERROR'):
                    failed_cases.append(name)
                    fg = tc.get('fix_guidance', {})
                    if fg and fg.get('suggestions'):
                        fix_guidance_list.append({'case': name, **fg})
                elif st == 'PASSED':
                    passed_cases.append(name)
        except Exception:
            pass
    summary['failed_cases'] = failed_cases
    summary['passed_cases'] = passed_cases
    summary['fix_guidance'] = fix_guidance_list
    summary['fix_scope'] = 'failed_only' if failed_cases else 'all_passed'

    # 失败分类汇总
    classification_counter = {}
    results_file_p = Path(results_path)
    if results_file_p.exists():
        try:
            rd = json.loads(results_file_p.read_text(encoding='utf-8'))
            for tc in rd.get('test_cases', []):
                fc = tc.get('failure_classification', '')
                if fc:
                    classification_counter[fc] = classification_counter.get(fc, 0) + 1
        except Exception:
            pass
    summary['failure_classification_summary'] = classification_counter

    # sentinel 数据（P2-1）
    has_failures = (summary.get('failed', 0) + summary.get('error', 0)) > 0
    if sentinel_data:
        summary['execution_round'] = sentinel_data.get('execution_rounds', 0)
        status = sentinel_data.get('status', '')
        if status == 'budget_exceeded':
            summary['stop_reason'] = 'budget_exceeded'
        elif status == 'final_review_generated':
            summary['stop_reason'] = 'session_closed'
        else:
            summary['stop_reason'] = 'completed_with_failures' if has_failures else 'completed_pass'
    else:
        summary['execution_round'] = 0
        summary['stop_reason'] = 'completed_with_failures' if has_failures else 'completed_pass'

    # 产物命名映射（供下游 Agent 使用统一文件名）
    summary['artifacts'] = {
        'test_results': str(results_path),
        'exec_summary': str(dirs['report'] / f'exec_summary_{run_timestamp}.json'),
        'report_html': str(dirs['report'] / f'report_{run_timestamp}.html'),
        'report_json': str(dirs['report'] / f'report_{run_timestamp}.json'),
    }

    return summary


def _collect_failed_cases(results_path):
    """
    从测试结果 JSON 中收集失败/错误的用例名称。

    Args:
        results_path: 测试结果 JSON 文件路径

    Returns:
        list: 失败用例的函数名列表
    """
    results_file = Path(results_path)
    if not results_file.exists():
        return []

    try:
        data = json.loads(results_file.read_text(encoding='utf-8'))
        failed = []
        for tc in data.get('test_cases', []):
            status = tc.get('status', '').upper()
            if status in ('FAILED', 'ERROR'):
                nid = tc.get('nodeid', '') or tc.get('node_id', '') or tc.get('name', '')
                func_name = nid.split('::')[-1] if '::' in nid else nid
                # 剥离参数化后缀 [chromium] 等，-k 使用子串匹配无需精确参数后缀
                if '[' in func_name:
                    func_name = func_name[:func_name.index('[')]
                if func_name:
                    failed.append(func_name)
        return failed
    except (json.JSONDecodeError, KeyError):
        return []


def _collect_passed_cases(results_path):
    """从测试结果 JSON 中收集通过的用例名称。"""
    results_file = Path(results_path)
    if not results_file.exists():
        return []
    try:
        data = json.loads(results_file.read_text(encoding='utf-8'))
        passed = []
        for tc in data.get('test_cases', []):
            if tc.get('status', '').upper() == 'PASSED':
                nid = tc.get('nodeid', '') or tc.get('node_id', '') or tc.get('name', '')
                func_name = nid.split('::')[-1] if '::' in nid else nid
                if func_name:
                    passed.append(func_name)
        return passed
    except (json.JSONDecodeError, KeyError):
        return []


def _resolve_dependency_chain(case_ids, workspace):
    """
    根据 ui-test-cases.json 中的 data_dependency 字段，
    扩展失败用例集，包含其依赖链上的所有前置用例（含环检测）。
    """
    sb = _resolve_session_base(workspace)
    tc_file = Path(workspace) / sb / 'artifacts' / 'ui-test-cases.json'
    if not tc_file.exists():
        return case_ids

    try:
        tc_data = json.loads(tc_file.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return case_ids

    dep_map = {}
    for tc in tc_data if isinstance(tc_data, list) else tc_data.get('test_cases', []):
        tc_id = tc.get('function_name', '') or tc.get('id', '')
        deps = tc.get('data_dependency', [])
        if isinstance(deps, str):
            deps = [deps]
        if tc_id and deps:
            dep_map[tc_id] = deps

    expanded = set(case_ids)
    for cid in list(case_ids):
        visited = set()
        stack = [cid]
        while stack:
            current = stack.pop()
            if current in visited:
                print(f'  [依赖链] 检测到循环依赖: {current}，退化为全量执行')
                return []
            visited.add(current)
            for dep in dep_map.get(current, []):
                if dep not in visited:
                    expanded.add(dep)
                    stack.append(dep)

    if len(expanded) > len(case_ids):
        added = expanded - set(case_ids)
        print(f'  [依赖链] 自动包含 {len(added)} 个前置依赖用例: {sorted(added)}')

    return sorted(expanded)


def _merge_retry_results(main_results_path, retry_results_path):
    """
    将重试中通过的用例合并到主结果文件中，覆盖之前的失败记录。

    Args:
        main_results_path: 主测试结果 JSON 路径
        retry_results_path: 重试结果 JSON 路径

    Returns:
        list: 本轮重试中通过的用例名列表
    """
    main_path = Path(main_results_path)
    retry_path = Path(retry_results_path)
    newly_passed = []

    if not main_path.exists() or not retry_path.exists():
        return newly_passed

    try:
        main_data = json.loads(main_path.read_text(encoding='utf-8'))
        retry_data = json.loads(retry_path.read_text(encoding='utf-8'))

        # 建立重试结果的索引（按 nodeid / node_id / name）
        retry_map = {}
        for tc in retry_data.get('test_cases', []):
            key = tc.get('nodeid', '') or tc.get('node_id', '') or tc.get('name', '')
            retry_map[key] = tc

        # 遍历主结果，用重试通过的结果替换失败记录
        for i, tc in enumerate(main_data.get('test_cases', [])):
            key = tc.get('nodeid', '') or tc.get('node_id', '') or tc.get('name', '')
            if key in retry_map:
                retry_tc = retry_map[key]
                if retry_tc.get('status', '').upper() == 'PASSED':
                    newly_passed.append(key.split('::')[-1] if '::' in key else key)
                    main_data['test_cases'][i] = retry_tc

        main_path.write_text(
            json.dumps(main_data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    except (json.JSONDecodeError, KeyError):
        pass

    return newly_passed


def run_video_compression(dirs):
    """
    执行视频压缩（如果有视频文件）。

    Args:
        dirs: 目录路径字典
    """
    video_dir = dirs['videos']
    video_files = list(video_dir.glob('*.webm'))
    if not video_files:
        return

    print(f'\n[后处理] 视频压缩（{len(video_files)} 个文件）...')

    # 查找 video_compressor.py
    compressor = Path(__file__).parent / 'video_compressor.py'
    if not compressor.exists():
        print('  警告: video_compressor.py 未找到，跳过视频压缩')
        return

    cmd = [
        sys.executable, str(compressor),
        '--input-dir', str(video_dir),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                encoding='utf-8', errors='replace')
        if result.returncode == 0:
            print('  视频压缩完成')
            if result.stdout:
                # 打印压缩报告的最后几行
                lines = result.stdout.strip().split('\n')
                for line in lines[-5:]:
                    print(f'  {line}')
        else:
            print(f'  视频压缩失败: {result.stderr[:200]}')
    except subprocess.TimeoutExpired:
        print('  视频压缩超时（超过 5 分钟），已跳过')
    except Exception as e:
        print(f'  视频压缩出错: {e}')


def _check_conftest_conflicts(test_file):
    """
    检测 LLM 生成的 conftest.py 中与 conftest_webui_plugin.py 冲突的 fixture。
    返回 (has_conflicts, conflict_details) 元组。

    Inheritance override pattern (KEEP):
        def browser_context_args(browser_context_args):
    Full replacement pattern (DISABLE):
        def browser_context_args():
        def browser_context_args(request):
    """
    conftest = Path(test_file).parent / 'conftest.py'
    if not conftest.exists():
        return False, []

    try:
        text = conftest.read_text(encoding='utf-8')
    except Exception:
        return False, []

    import re as _re
    conflicts = []

    always_check = (
        'screenshot_on_failure',
        'pytest_runtest_makereport',
    )
    for fixture_name in always_check:
        pattern = _re.compile(rf'\bdef\s+{fixture_name}\b')
        if pattern.search(text):
            conflicts.append(
                f'  ⚠️  冲突 fixture: {fixture_name}\n'
                f'     建议: 该 fixture 会覆盖执行插件，建议重命名或移除'
            )

    inherit_aware = (
        'browser_context_args',
        'browser_type_launch_args',
    )
    for fixture_name in inherit_aware:
        inherit_pat = _re.compile(
            rf'\bdef\s+{fixture_name}\s*\(\s*{fixture_name}\b'
        )
        replace_pat = _re.compile(rf'\bdef\s+{fixture_name}\b')
        if replace_pat.search(text) and not inherit_pat.search(text):
            conflicts.append(
                f'  ⚠️  冲突 fixture: {fixture_name}（非继承重写模式）\n'
                f'     建议: 改为 def {fixture_name}({fixture_name}) 继承模式，或移除'
            )

    return len(conflicts) > 0, conflicts


def _conftest_conflict_check(test_file, auto_fix=False):
    """检测 + 可选自动修复 conftest.py 冲突。"""
    has_conflicts, conflicts = _check_conftest_conflicts(test_file)
    if not has_conflicts:
        return

    print('\n  [安全网] 检测到 conftest.py 中与执行插件冲突的 fixture:')
    for c in conflicts:
        print(c)

    if auto_fix:
        print('  --auto-fix-conftest 已启用，正在自动修复...')
        _sanitize_conftest(test_file)
    else:
        print('  [安全网] 请手动修复上述冲突，或传入 --auto-fix-conftest 自动处理')
        print('  继续执行，但可能存在插件行为被覆盖的风险')


def _sanitize_conftest(test_file):
    """
    仅在 --auto-fix-conftest 显式传入时才改写 conftest.py。
    默认行为改为检测+警告。
    """
    has_conflicts, conflicts = _check_conftest_conflicts(test_file)
    if not has_conflicts:
        return

    import re as _re
    conftest = Path(test_file).parent / 'conftest.py'
    text = conftest.read_text(encoding='utf-8')
    changed = False

    always_disable = (
        'screenshot_on_failure',
        'pytest_runtest_makereport',
    )
    for fixture_name in always_disable:
        pattern = _re.compile(rf'\bdef\s+{fixture_name}\b')
        if pattern.search(text):
            text = pattern.sub(f'def _disabled_{fixture_name}', text)
            changed = True

    inherit_aware = (
        'browser_context_args',
        'browser_type_launch_args',
    )
    for fixture_name in inherit_aware:
        inherit_pat = _re.compile(
            rf'\bdef\s+{fixture_name}\s*\(\s*{fixture_name}\b'
        )
        replace_pat = _re.compile(rf'\bdef\s+{fixture_name}\b')
        if replace_pat.search(text) and not inherit_pat.search(text):
            text = replace_pat.sub(f'def _disabled_{fixture_name}', text)
            changed = True
            print(f'  [安全网] 禁用 conftest.py 中的完全替换 fixture: {fixture_name}')

    if changed:
        conftest.write_text(text, encoding='utf-8')
        print('  [安全网] 已处理 conftest.py 中与插件冲突的 fixture')


PHASE_MARKERS = {
    'smoke': 'smoke',
    'dialog': 'dialog',
    'create': 'create',
    'full': None,
}

# ── smart XPath 预检阈值（贯穿 Step 4.5 + Step 5 修复循环） ──
_SMART_XPATH_PRECHECK_RATIO = 0.40


def _precheck_smart_xpath_usage(test_file, workspace):
    """执行前 smart XPath 使用率预检。

    读取 page-elements.json 的 element_source，统计脚本中 XPath 使用率。
    当 element_source=='smart_xpath' 且使用率低于阈值时输出强制警告。

    返回预检结果字典（写入 exec_summary 供 Agent 消费）。
    """
    sb = _resolve_session_base(workspace)
    pe_path = Path(workspace) / sb / 'artifacts' / 'page-elements.json'
    if not pe_path.exists():
        return None

    try:
        pe_data = json.loads(pe_path.read_text(encoding='utf-8'))
    except Exception:
        return None

    element_source = pe_data.get('element_source', '')
    if element_source != 'smart_xpath':
        return None

    test_path = Path(test_file)
    if not test_path.exists():
        return None

    try:
        lines = test_path.read_text(encoding='utf-8').splitlines()
    except Exception:
        return None

    # 复用 validator_selector 的统计核心逻辑
    try:
        validator_path = Path(__file__).resolve().parent / 'validators' / 'validator_selector.py'
        if validator_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location('validator_selector', str(validator_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ratio_data = mod.compute_smart_xpath_ratio(lines)
        else:
            raise FileNotFoundError
    except Exception:
        import re as _re
        _loc_re = _re.compile(r'\.locator\s*\(')
        _xp_re = _re.compile(r'xpath=')
        _canvas_exempt = ('"canvas"', "'canvas'", 'canvas_', 'mouse.click(',
                          'mouse.move(', 'bounding_box', 'canvas_locate', 'canvas_click')
        total = 0
        xp = 0
        for ln in lines:
            s = ln.strip()
            if s.startswith('#'):
                continue
            if _loc_re.search(s):
                if any(p in s for p in _canvas_exempt):
                    continue
                total += 1
                if _xp_re.search(s):
                    xp += 1
        ratio_data = {
            'xpath_calls': xp,
            'total_locator_calls': total,
            'ratio': round(xp / total, 2) if total > 0 else 1.0,
            'css_lines': [],
        }

    result = {
        'element_source': element_source,
        'xpath_calls': ratio_data['xpath_calls'],
        'total_locator_calls': ratio_data['total_locator_calls'],
        'ratio': ratio_data['ratio'],
        'threshold': _SMART_XPATH_PRECHECK_RATIO,
        'passed': ratio_data['ratio'] >= _SMART_XPATH_PRECHECK_RATIO,
    }

    if not result['passed']:
        print(f'\n  [selector 预检] ⛔ smart XPath 使用率 {result["ratio"]:.0%}'
              f' < 强制阈值 {_SMART_XPATH_PRECHECK_RATIO:.0%}'
              f' ({result["xpath_calls"]}/{result["total_locator_calls"]})')
        print(f'  [selector 预检] page-elements.json 已提供 smart XPath，'
              f'脚本中必须使用 xpath= 定位器')
        for css_ln in ratio_data.get('css_lines', [])[:5]:
            print(f'    裸 CSS: {css_ln}')
        if len(ratio_data.get('css_lines', [])) > 5:
            print(f'    ... 共 {len(ratio_data["css_lines"])} 处裸 CSS 选择器需替换为 smart XPath')
    else:
        print(f'\n  [selector 预检] ✅ smart XPath 使用率 {result["ratio"]:.0%}'
              f' >= {_SMART_XPATH_PRECHECK_RATIO:.0%}')

    return result


def _find_latest_results(report_dir):
    """查找报告目录下最新的 test_results JSON 文件。"""
    report_path = Path(report_dir)
    if not report_path.exists():
        return None
    candidates = sorted(report_path.glob('test_results_*.json'), reverse=True)
    for c in candidates:
        if 'retry' not in c.name:
            return c
    return None


def _build_filter_expression(args, report_dir):
    """
    根据 --phase / --failed-only / --case-id 构建 pytest 过滤参数。
    优先级：--case-id > --failed-only > --phase。

    返回: (k_expr, m_expr) 元组
      k_expr: pytest -k 表达式（子串匹配，用于 case-id / failed-only）
      m_expr: pytest -m 表达式（marker 精确匹配，用于 phase）
    """
    if args.case_id:
        case_ids = [c.strip() for c in args.case_id.split(',') if c.strip()]
        if case_ids:
            return ' or '.join(case_ids), ''

    if args.failed_only:
        latest = _find_latest_results(report_dir)
        if latest:
            failed = _collect_failed_cases(str(latest))
            if failed:
                # 排除已标记为 known_issue 的用例
                sentinel = _read_sentinel(Path(args.workspace).resolve()) if hasattr(args, 'workspace') else {}
                known = set(sentinel.get('known_issues', {}).keys())
                if known:
                    before_count = len(failed)
                    failed = [c for c in failed if c not in known]
                    excluded = before_count - len(failed)
                    if excluded:
                        print(f'  [known_issue] 已排除 {excluded} 个 known_issue 用例')
                if not failed:
                    print('  提示: 排除 known_issue 后无剩余失败用例，跳过执行')
                    return '', ''
                workspace = str(Path(args.workspace).resolve()) if hasattr(args, 'workspace') else ''
                if workspace:
                    failed = _resolve_dependency_chain(failed, workspace)
                    if not failed:
                        print('  [依赖链] 检测到循环依赖，退化为全量执行')
                        return '', ''
                return ' or '.join(failed), ''
            else:
                print('  提示: 上一轮无失败用例，--failed-only 不生效，执行全量')
                return '', ''
        else:
            print('  警告: 未找到上一轮结果文件，--failed-only 不生效')
            return '', ''

    if args.phase:
        marker = PHASE_MARKERS.get(args.phase)
        if marker:
            return '', marker

    return '', ''


def main():
    parser = argparse.ArgumentParser(description='WebUI 批量测试执行')
    parser.add_argument('--workspace', required=True,
                        help='工作空间根路径')
    parser.add_argument('--test-file', required=True,
                        help='测试文件路径（相对于工作空间或绝对路径）')
    parser.add_argument('--report-dir', default=None,
                        help='报告输出目录（默认: workspace/qa/webui/session/execution）')
    parser.add_argument('--video', action='store_true', default=True,
                        help='启用视频录制（默认开启）')
    parser.add_argument('--no-video', dest='video', action='store_false',
                        help='禁用视频录制')
    parser.add_argument('--screenshot-on-failure', action='store_true', default=True,
                        help='失败时截图（默认开启）')
    parser.add_argument('--no-screenshot-on-failure', dest='screenshot_on_failure',
                        action='store_false', help='禁用失败截图')
    parser.add_argument('--browser', default='chromium',
                        choices=['chromium', 'chrome'],
                        help='浏览器类型，默认 chromium')
    parser.add_argument('--headless', action='store_true', default=True,
                        help='无头模式运行（默认开启，强制生效，忽略 --no-headless）')
    # --no-headless 已废弃：Agent 禁止传入此参数，脚本层面也不再接受
    # 如需有头调试，请手动设置环境变量 FORCE_HEADED=1
    parser.add_argument('--viewport', default='1920x1080',
                        help='浏览器视口尺寸（宽x高），默认 1920x1080')
    parser.add_argument('--timeout', type=int, default=120,
                        help='单个测试用例超时时间（秒），默认 120')
    parser.add_argument('--max-retries', type=int, default=0,
                        help='失败用例最大重试次数，默认 0（不重试）。建议设为 3')
    parser.add_argument('--target-url', default='',
                        help='被测目标 URL（写入测试结果元数据，供报告展示）')
    parser.add_argument('--phase', default=None,
                        choices=['smoke', 'dialog', 'create', 'full'],
                        help='分层回归阶段：smoke=冒烟层, dialog=弹窗层, create=创建层, full=全量')
    parser.add_argument('--failed-only', action='store_true', default=False,
                        help='仅运行上一轮失败的用例（从最新 test_results_*.json 读取）')
    parser.add_argument('--case-id', default=None,
                        help='指定用例 ID 或函数名执行（逗号分隔多个，如 test_create_report,test_fill_form）')
    parser.add_argument('--force-reopen', action='store_true', default=False,
                        help='强制重新打开已终止的会话（绕过 sentinel 和 final-review 检查）')
    parser.add_argument('--auto-fix-conftest', action='store_true', default=False,
                        help='自动修复 conftest.py 中与执行插件冲突的 fixture（默认仅检测+警告，不修改文件）')
    parser.add_argument('--spa-wait-ms', type=int, default=5000,
                        help='SPA 页面 readiness gate 轮询等待上限毫秒数（默认 5000，每 500ms 检测一次）')
    parser.add_argument('--screenshot-always', action='store_true', default=True,
                        help='所有用例（含通过）都截图（默认开启）'
    )
    parser.add_argument('--no-screenshot-always', dest='screenshot_always',
                        action='store_false',
                        help='仅失败时截图（关闭全量截图）')
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()

    # ── Step 0a: 加载 repair_loop 配置并覆盖预算上限 ─────────────────────
    global BUDGET_MAX_ROUNDS, BUDGET_MAX_WALL_CLOCK
    try:
        # 尝试加载配置文件
        import sys
        sys.path.insert(0, str(workspace))
        from qa_agent.core.config import load_config
        from qa_agent.core.repair_loop import get_repair_loop_config

        config = load_config(workspace)
        repair_cfg = get_repair_loop_config(config)

        # 覆盖默认值
        BUDGET_MAX_ROUNDS = repair_cfg.max_execution_rounds
        print(f'[config] repair_loop.mode={repair_cfg.mode}, '
              f'max_execution_rounds={BUDGET_MAX_ROUNDS}, '
              f'per_case_attempts={repair_cfg.max_retries_per_case}')
    except Exception as e:
        # 配置加载失败，使用默认值
        print(f'[config] 无法加载 repair_loop 配置，使用默认值: {e}')
        pass

    # ── Step 0b: Session Sentinel 守卫 ─────────────────────
    sentinel = _read_sentinel(workspace)

    # Hard ceiling: even --force-reopen cannot exceed BUDGET_ABSOLUTE_MAX
    if sentinel.get('execution_rounds', 0) >= BUDGET_ABSOLUTE_MAX:
        sentinel['status'] = 'budget_exceeded'
        _write_sentinel(workspace, sentinel)
        print(f'[sentinel] 已达绝对执行上限 ({BUDGET_ABSOLUTE_MAX})，--force-reopen 也无法继续。退出码 2')
        sys.exit(2)

    if args.force_reopen:
        print('[sentinel] --force-reopen: 重置会话状态')
        sentinel['status'] = 'running'
        sentinel['env_failure_rounds'] = 0
        sentinel['reopened_at'] = datetime.now().astimezone().isoformat()
        _write_sentinel(workspace, sentinel)
    else:
        if _check_final_review_exists(workspace):
            sentinel['status'] = 'final_review_generated'
            _write_sentinel(workspace, sentinel)
            print('[sentinel] final-review.md 已存在，会话已终止。退出码 2')
            sys.exit(2)

        terminal_states = ('final_review_generated', 'closed', 'budget_exceeded')
        if sentinel.get('status') in terminal_states:
            print(f'[sentinel] 会话状态为 {sentinel["status"]}，拒绝执行。退出码 2')
            print(f'[sentinel] 如需重新打开，请使用 --force-reopen')
            sys.exit(2)

        if sentinel.get('execution_rounds', 0) >= BUDGET_MAX_ROUNDS:
            sentinel['status'] = 'budget_exceeded'
            _write_sentinel(workspace, sentinel)
            print(f'[sentinel] 已达执行轮次上限 ({BUDGET_MAX_ROUNDS})。退出码 2')
            print(f'[sentinel] 如需在修复脚本后继续执行，请使用 --force-reopen（绝对上限 {BUDGET_ABSOLUTE_MAX} 轮）')
            sys.exit(2)

        if sentinel.get('wall_clock_seconds', 0) >= BUDGET_MAX_WALL_CLOCK:
            sentinel['status'] = 'budget_exceeded'
            _write_sentinel(workspace, sentinel)
            print(f'[sentinel] 已达墙钟时间上限 ({BUDGET_MAX_WALL_CLOCK}s)。退出码 2')
            print(f'[sentinel] 如需在修复脚本后继续执行，请使用 --force-reopen（绝对上限 {BUDGET_ABSOLUTE_MAX} 轮）')
            sys.exit(2)

    # 累计执行轮次
    sentinel['execution_rounds'] = sentinel.get('execution_rounds', 0) + 1
    sentinel['status'] = 'running'
    _write_sentinel(workspace, sentinel)
    current_round = sentinel['execution_rounds']
    print(f'[sentinel] 执行轮次: {current_round}/{BUDGET_MAX_ROUNDS}')

    # 解析测试文件路径
    test_file = Path(args.test_file)
    if not test_file.is_absolute():
        test_file = workspace / test_file
    if not test_file.exists():
        print(f'错误: 测试文件不存在: {test_file}')
        sys.exit(1)
    args.test_file = str(test_file)

    # 设置报告目录
    report_dir = Path(args.report_dir) if args.report_dir else (
        workspace / _resolve_session_base(workspace) / 'execution'
    )
    if not report_dir.is_absolute():
        report_dir = workspace / report_dir
    args.report_dir = str(report_dir)

    print('=' * 60)
    print('WebUI 批量测试执行')
    print('=' * 60)
    print(f'  工作空间: {workspace}')
    print(f'  测试文件: {test_file}')
    print(f'  浏览器: {args.browser}')
    print(f'  无头模式: True (强制)')
    print(f'  视口尺寸: {args.viewport}')
    print(f'  视频录制: {"启用" if args.video else "禁用"}')
    print(f'  失败截图: {"启用" if args.screenshot_on_failure else "禁用"}')
    print(f'  全量截图: {"启用" if getattr(args, "screenshot_always", False) else "禁用（默认）"}')
    print(f'  失败重试: {args.max_retries} 次' if args.max_retries > 0 else '  失败重试: 禁用')

    # ── 准备目录 ────────────────────────────────────────────
    print('\n[1/5] 准备输出目录...')
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    dirs = setup_directories(args.report_dir, run_timestamp=timestamp)
    for name, path in dirs.items():
        print(f'  {name}: {path}')

    # ── 查找 conftest 插件 ──────────────────────────────────
    print('\n[2/5] 加载 pytest 插件...')
    conftest_path = find_conftest_plugin()
    if conftest_path:
        print(f'  插件路径: {conftest_path}')
    else:
        print('  警告: conftest_webui_plugin.py 未找到，将不使用自定义插件')

    # ── 配置环境变量 ────────────────────────────────────────
    print('\n[3/5] 配置执行环境...')
    results_path = report_dir / f'test_results_{timestamp}.json'
    env = setup_environment(args, dirs, results_path)

    # 将 conftest 插件目录加入 PYTHONPATH
    if conftest_path:
        plugin_dir = str(conftest_path.parent)
        existing_pythonpath = env.get('PYTHONPATH', '')
        env['PYTHONPATH'] = f'{plugin_dir}{os.pathsep}{existing_pythonpath}' if existing_pythonpath else plugin_dir

    print(f'  结果文件: {results_path}')
    print(f'  环境变量已设置: {len(env) - len(os.environ)} 个自定义变量')

    # ── 安全网：检测 conftest.py 中与插件冲突的 fixture ──
    _conftest_conflict_check(args.test_file, auto_fix=getattr(args, 'auto_fix_conftest', False))

    # ── smart XPath 使用率预检（贯穿 Step 5 修复循环） ──
    selector_precheck = _precheck_smart_xpath_usage(args.test_file, workspace)

    # ── 用例过滤：--phase / --failed-only / --case-id ──────
    pytest_k_expr, pytest_m_expr = _build_filter_expression(args, report_dir)
    if pytest_k_expr:
        print(f'  用例过滤 (-k): {pytest_k_expr}')
    if pytest_m_expr:
        print(f'  用例过滤 (-m): {pytest_m_expr}')

    # ── 根目录污染快照（执行前） ──────────────────────────────
    pre_exec_snapshot = _snapshot_root_files(workspace)

    # ── 执行 pytest ─────────────────────────────────────────
    print('\n[4/5] 执行 pytest...')
    start_time = datetime.now().astimezone()

    cmd = build_pytest_command(args, dirs, conftest_path, results_path)
    if pytest_k_expr:
        cmd.extend(['-k', pytest_k_expr])
    if pytest_m_expr:
        cmd.extend(['-m', pytest_m_expr])
    log_file = dirs['logs'] / f'pytest_output_{timestamp}.log'

    print(f'  命令: {" ".join(cmd[:6])}...')
    print(f'  日志: {log_file}')
    print('-' * 60)

    retry_info = {
        'max_retries': args.max_retries,
        'retry_count': 0,
        'retried_cases': [],
    }

    # 执行 pytest 并将输出同时写入日志和终端
    try:
        process = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=args.timeout * 100,  # 总超时 = 单用例超时 * 100（上限）
            cwd=str(workspace),
        )

        # 保存日志
        log_content = f'=== STDOUT ===\n{process.stdout}\n\n=== STDERR ===\n{process.stderr}'
        log_file.write_text(log_content, encoding='utf-8')

        # 打印 pytest 输出
        if process.stdout:
            print(process.stdout)
        if process.stderr:
            # 只打印重要的 stderr 信息
            for line in process.stderr.split('\n'):
                if line.strip() and not line.startswith('==='):
                    print(f'  [stderr] {line}')

        pytest_returncode = process.returncode
        print('-' * 60)
        print(f'  pytest 退出码: {pytest_returncode}')

        # ── 失败重试 ─────────────────────────────────────
        if args.max_retries > 0 and pytest_returncode != 0:
            failed_cases = _collect_failed_cases(results_path)
            retry_round = 0

            while failed_cases and retry_round < args.max_retries:
                retry_round += 1
                print(f'\n[重试 {retry_round}/{args.max_retries}] 重新执行 {len(failed_cases)} 个失败用例...')

                retry_results_path = report_dir / f'test_results_{timestamp}_retry{retry_round}.json'
                retry_env = env.copy()
                retry_env['TEST_RESULTS_PATH'] = str(retry_results_path)

                retry_cmd = cmd.copy()
                # 移除首轮可能携带的 -k 参数，避免重复
                _clean = []
                _skip_next = False
                for _arg in retry_cmd:
                    if _skip_next:
                        _skip_next = False
                        continue
                    if _arg == '-k':
                        _skip_next = True
                        continue
                    _clean.append(_arg)
                retry_cmd = _clean
                # 剥离参数化后缀 [chromium] 后用 -k 子串匹配
                stripped = []
                for c in failed_cases:
                    name = c[:c.index('[')] if '[' in c else c
                    if name not in stripped:
                        stripped.append(name)
                filter_expr = ' or '.join(stripped)
                retry_cmd.extend(['-k', filter_expr])

                retry_log = dirs['logs'] / f'pytest_retry{retry_round}_{timestamp}.log'

                try:
                    retry_process = subprocess.run(
                        retry_cmd,
                        env=retry_env,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        timeout=args.timeout * len(failed_cases) * 2,
                        cwd=str(workspace),
                    )

                    retry_log.write_text(
                        f'=== STDOUT ===\n{retry_process.stdout}\n\n=== STDERR ===\n{retry_process.stderr}',
                        encoding='utf-8',
                    )

                    if retry_process.stdout:
                        print(retry_process.stdout)

                    # 将重试通过的用例合并到主结果
                    newly_passed = _merge_retry_results(results_path, retry_results_path)
                    retry_info['retried_cases'].extend(
                        {'case': c, 'passed_at_retry': retry_round} for c in newly_passed
                    )

                    print(f'  重试第 {retry_round} 轮: {len(newly_passed)}/{len(failed_cases)} 个用例通过')

                    # 更新失败列表
                    failed_cases = _collect_failed_cases(results_path)
                    if not failed_cases:
                        print('  所有用例已通过，停止重试')
                        pytest_returncode = 0
                        break

                except (subprocess.TimeoutExpired, Exception) as e:
                    print(f'  重试第 {retry_round} 轮执行异常: {e}')
                    retry_log.write_text(f'执行异常: {e}', encoding='utf-8')
                    break

            retry_info['retry_count'] = retry_round

    except subprocess.TimeoutExpired:
        print('  错误: pytest 执行超时')
        log_file.write_text('执行超时', encoding='utf-8')
        pytest_returncode = -1

    except Exception as e:
        print(f'  错误: pytest 执行失败: {e}')
        log_file.write_text(f'执行失败: {e}', encoding='utf-8')
        pytest_returncode = -1

    end_time = datetime.now().astimezone()

    # ── 根目录污染检测（执行后） ──────────────────────────────
    root_pollution = _check_root_pollution(pre_exec_snapshot, workspace)
    if root_pollution:
        print(f'\n  [根目录污染告警] 执行期间根目录新增 {len(root_pollution)} 个非标准文件:')
        for f in root_pollution:
            print(f'    - {f}')
        print('  标准产物只允许在 qa/webui/session/ 和 qa/webui/shared_assets/ 内创建。')
        print('  请排查原因后手动清理。如为 Agent 脱轨，应停止执行并报告。')

    # ── 更新 sentinel：本轮墙钟 + final-review 检查 + 收敛检测 ──
    round_wall = (end_time - start_time).total_seconds()
    sentinel['wall_clock_seconds'] = sentinel.get('wall_clock_seconds', 0) + round_wall

    # 记录本轮通过率和失败集合到 sentinel（P1-2）
    round_pass_rate = 0.0
    round_failed_set = []
    round_failed_detail = {}  # {case_name: failure_classification}
    if results_path.exists():
        try:
            _rd = json.loads(results_path.read_text(encoding='utf-8'))
            _tcs = _rd.get('test_cases', [])
            if _tcs:
                _passed = sum(1 for t in _tcs if t.get('status', '').upper() == 'PASSED')
                round_pass_rate = _passed / len(_tcs)
                round_failed_set = sorted(
                    t.get('name', '') for t in _tcs if t.get('status', '').upper() in ('FAILED', 'ERROR'))
                for t in _tcs:
                    if t.get('status', '').upper() in ('FAILED', 'ERROR'):
                        round_failed_detail[t.get('name', '')] = t.get(
                            'failure_classification', 'unknown')
        except Exception:
            pass

    pass_rate_history = sentinel.get('pass_rate_history', [])
    pass_rate_history.append(round_pass_rate)
    sentinel['pass_rate_history'] = pass_rate_history

    failed_set_history = sentinel.get('failed_set_history', [])
    failed_set_history.append(round_failed_set)
    sentinel['failed_set_history'] = failed_set_history

    # known_issue 自动标记：同一用例连续 3 轮以相同错误分类失败
    failed_detail_history = sentinel.get('failed_detail_history', [])
    failed_detail_history.append(round_failed_detail)
    sentinel['failed_detail_history'] = failed_detail_history
    known_issues = sentinel.get('known_issues', {})
    KNOWN_ISSUE_THRESHOLD = 3
    if len(failed_detail_history) >= KNOWN_ISSUE_THRESHOLD:
        recent = failed_detail_history[-KNOWN_ISSUE_THRESHOLD:]
        all_cases = set()
        for d in recent:
            all_cases.update(d.keys())
        for case_name in all_cases:
            if case_name in known_issues:
                continue
            classifications = [d.get(case_name) for d in recent]
            if all(c and c == classifications[0] for c in classifications):
                known_issues[case_name] = {
                    'failure_classification': classifications[0],
                    'consecutive_rounds': KNOWN_ISSUE_THRESHOLD,
                    'marked_at_round': sentinel.get('execution_rounds', 0),
                }
                print(f'  [known_issue] {case_name} 连续 {KNOWN_ISSUE_THRESHOLD} 轮'
                      f'以相同错误 ({classifications[0]}) 失败，标记为 known_issue')
    sentinel['known_issues'] = known_issues

    # ── 基础设施失败回退：pytest 收集失败/子进程崩溃时不消耗有效预算 ──
    _infra_failure = False
    if not results_path.exists():
        _infra_failure = True
    elif results_path.exists():
        try:
            _rd_infra = json.loads(results_path.read_text(encoding='utf-8'))
            if not _rd_infra.get('test_cases'):
                _infra_failure = True
        except Exception:
            _infra_failure = True
    if _infra_failure:
        sentinel['execution_rounds'] = max(0, sentinel.get('execution_rounds', 1) - 1)
        sentinel['env_failure_rounds'] = sentinel.get('env_failure_rounds', 0) + 1
        _efr = sentinel['env_failure_rounds']
        print(f'  [sentinel] 基础设施失败（无有效测试结果），不消耗有效预算 '
              f'(env_failure_rounds={_efr}/3)')
        if _efr >= 3:
            sentinel['status'] = 'budget_exceeded'
            _write_sentinel(workspace, sentinel)
            print(f'  [sentinel] 连续基础设施/环境失败达 3 轮，会话终止。退出码 2')
            sys.exit(2)

    # ── 环境失败轮次回退：全部 SKIP + environment_failure 时不消耗有效预算 ──
    _all_env_skip = False
    if not _infra_failure and results_path.exists() and not round_failed_set:
        try:
            _rd_env = json.loads(results_path.read_text(encoding='utf-8'))
            _tcs_env = _rd_env.get('test_cases', [])
            if _tcs_env and all(
                t.get('status', '').upper() == 'SKIPPED'
                and t.get('failure_classification') == 'environment_failure'
                for t in _tcs_env
            ):
                _all_env_skip = True
        except Exception:
            pass
    if _all_env_skip:
        sentinel['execution_rounds'] = max(0, sentinel.get('execution_rounds', 1) - 1)
        sentinel['env_failure_rounds'] = sentinel.get('env_failure_rounds', 0) + 1
        _efr = sentinel['env_failure_rounds']
        print(f'  [sentinel] 本轮全部 ENVIRONMENT_FAILURE SKIP，不消耗有效预算 '
              f'(env_failure_rounds={_efr}/3)')
        if _efr >= 3:
            sentinel['status'] = 'budget_exceeded'
            _write_sentinel(workspace, sentinel)
            print(f'  [sentinel] 连续环境失败达 3 轮，会话终止。退出码 2')
            sys.exit(2)

    # 复合收敛检测（P1-2）
    convergence_triggered = False
    convergence_reason = ''
    rounds = sentinel.get('execution_rounds', 0)
    # (a) 连续 2 轮失败集合完全相同
    if len(failed_set_history) >= 2 and failed_set_history[-1] == failed_set_history[-2] and failed_set_history[-1]:
        convergence_triggered = True
        convergence_reason = f'连续 2 轮失败集合完全相同: {failed_set_history[-1]}'
    # (b) 连续 3 轮通过率无提升（最新一轮不高于 3 轮前，覆盖持平和下降）
    if not convergence_triggered and len(pass_rate_history) >= 3:
        last3 = pass_rate_history[-3:]
        if last3[-1] <= last3[0]:
            convergence_triggered = True
            convergence_reason = f'连续 3 轮通过率无提升: {[f"{r:.0%}" for r in last3]}'
    # (c) 累计轮次 > 5 且通过率 < 50% 且最近 3 轮无提升
    if not convergence_triggered and rounds > 5 and round_pass_rate < 0.5:
        if len(pass_rate_history) >= 3:
            last3 = pass_rate_history[-3:]
            if max(last3) <= last3[0]:
                convergence_triggered = True
                convergence_reason = (f'累计 {rounds} 轮且通过率 {round_pass_rate:.0%} < 50%，'
                                      f'最近 3 轮无提升: {[f"{r:.0%}" for r in last3]}')

    if convergence_triggered:
        sentinel['convergence_detected'] = True
        sentinel['convergence_reason'] = convergence_reason
        sentinel['convergence_action'] = 'strategy_upgrade'
        print(f'\n  [收敛检测] {convergence_reason}')
        print(f'  [收敛检测] 建议 Agent 升级修复策略（如重新探索页面、切换选择器方案）')

    # 状态判定
    if not args.force_reopen and _check_final_review_exists(workspace):
        sentinel['status'] = 'final_review_generated'
    elif sentinel.get('execution_rounds', 0) >= BUDGET_ABSOLUTE_MAX:
        sentinel['status'] = 'budget_exceeded'
        print(f'  [sentinel] 已达绝对执行上限 ({BUDGET_ABSOLUTE_MAX})，会话终止')
    elif sentinel['wall_clock_seconds'] >= BUDGET_MAX_WALL_CLOCK:
        sentinel['status'] = 'budget_exceeded'
    elif sentinel['execution_rounds'] >= BUDGET_MAX_ROUNDS and not convergence_triggered:
        sentinel['status'] = 'budget_exceeded'
    else:
        sentinel['status'] = 'idle'
    _write_sentinel(workspace, sentinel)

    # ── 自动提取失败经验 → lessons 库 ─────────────────────────
    _has_env_failure_skips = False
    if results_path.exists() and not round_failed_detail:
        try:
            _rd2 = json.loads(results_path.read_text(encoding='utf-8'))
            _has_env_failure_skips = any(
                t.get('failure_classification') == 'environment_failure'
                for t in _rd2.get('test_cases', [])
                if t.get('status', '').upper() == 'SKIPPED')
        except Exception:
            pass
    if round_failed_detail or _has_env_failure_skips:
        _auto_extract_lessons(results_path, workspace, args.target_url)

    # ── 生成执行摘要 ────────────────────────────────────────
    print('\n[5/5] 生成执行摘要...')
    summary = generate_exec_summary(
        results_path, dirs, start_time, end_time, pytest_returncode,
        run_timestamp=timestamp,
        retry_info=retry_info if args.max_retries > 0 else None,
        sentinel_data=sentinel,
    )

    if root_pollution:
        summary['warnings'] = summary.get('warnings', [])
        summary['warnings'].append({
            'type': 'root_dir_pollution',
            'files': root_pollution,
            'message': f'执行期间根目录新增 {len(root_pollution)} 个非标准文件',
        })

    if selector_precheck:
        summary['selector_precheck'] = selector_precheck
        if not selector_precheck.get('passed'):
            summary['warnings'] = summary.get('warnings', [])
            summary['warnings'].append({
                'type': 'smart_xpath_coverage_low',
                'ratio': selector_precheck['ratio'],
                'threshold': selector_precheck['threshold'],
                'message': (f'smart XPath 使用率 {selector_precheck["ratio"]:.0%}'
                            f' < 强制阈值 {selector_precheck["threshold"]:.0%}，'
                            f'修复脚本时必须使用 page-elements.json 中的 smart XPath'),
            })

    summary_path = report_dir / f'exec_summary_{timestamp}.json'
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    print(f'  摘要文件: {summary_path}')

    # ── 视频压缩（如果启用了视频录制） ──────────────────────
    if args.video:
        run_video_compression(dirs)

    # ── 打印最终报告 ────────────────────────────────────────
    print('\n' + '=' * 60)
    print('执行摘要')
    print('=' * 60)
    print(f'  运行时间戳: {timestamp}')
    print(f'  总用例数: {summary["total"]}')
    print(f'  通过: {summary["passed"]}')
    print(f'  失败: {summary["failed"]}')
    print(f'  错误: {summary["error"]}')
    print(f'  跳过: {summary.get("skipped", 0)}')
    print(f'  通过率: {summary["pass_rate"]}')
    print(f'  执行时长: {summary["execution_time"]["duration_seconds"]:.1f} 秒')
    print(f'  本轮截图: {summary.get("current_run_screenshots", 0)}  (目录累计: {summary.get("dir_total_screenshot_count", 0)})')
    print(f'  本轮视频: {summary.get("current_run_videos", 0)}  (目录累计: {summary.get("dir_total_video_count", 0)})')
    if args.max_retries > 0 and retry_info['retry_count'] > 0:
        print(f'  重试轮次: {retry_info["retry_count"]}')
        print(f'  重试通过: {len(retry_info["retried_cases"])} 个用例')
    print(f'\n  产物文件命名（统一时间戳 {timestamp}）:')
    for art_name, art_path in summary.get('artifacts', {}).items():
        print(f'    {art_name}: {Path(art_path).name}')
    print('=' * 60)

    # 输出摘要路径（供 Agent 解析）
    print(str(summary_path))

    # ── 自动生成 HTML 报告（硬闭环） ──────────────────────────
    # 默认跳过中间轮次报告，仅终态或全通过时生成 HTML
    # AQE_SKIP_INTERIM_REPORT=0 可强制每轮都生成
    skip_interim = os.environ.get('AQE_SKIP_INTERIM_REPORT', '1') == '1'
    all_passed = summary.get('failed', 0) + summary.get('error', 0) == 0 and summary.get('total', 0) > 0
    is_terminal = sentinel.get('status') in (
        'budget_exceeded', 'final_review_generated', 'closed',
    ) or all_passed
    report_script = Path(__file__).resolve().parent.parent.parent / \
        'uitest-report-generator' / 'scripts' / 'generate_webui_html_report.py'
    report_html_path = summary.get('artifacts', {}).get('report_html', '')

    if skip_interim and not is_terminal:
        summary['report_generated'] = False
        summary['report_error'] = 'skipped_interim_round'
        print('\n  [报告] AQE_SKIP_INTERIM_REPORT=1 且非终态轮次，跳过 HTML 报告生成')
    elif report_script.exists() and results_path.exists():
        try:
            report_cmd = [
                sys.executable, str(report_script),
                '--results', str(results_path),
                '--output', str(report_html_path),
                '--video-dir', str(dirs['videos']),
                '--workspace', str(workspace),
            ]
            report_result = subprocess.run(
                report_cmd, capture_output=True, text=True, timeout=60,
                encoding='utf-8', errors='replace',
            )
            if report_result.returncode == 0:
                summary['report_generated'] = True
                print(f'\n  [报告] HTML 报告已自动生成: {report_html_path}')
            else:
                summary['report_generated'] = False
                summary['report_error'] = report_result.stderr[:500]
                print(f'\n  [报告] HTML 报告生成失败: {report_result.stderr[:200]}')
        except Exception as e:
            summary['report_generated'] = False
            summary['report_error'] = str(e)
            print(f'\n  [报告] 报告生成异常: {e}')
    else:
        summary['report_generated'] = False
        reason = '报告脚本不存在' if not report_script.exists() else '测试结果文件不存在'
        summary['report_error'] = reason
        print(f'\n  [报告] 跳过自动报告生成: {reason}')

    # 报告状态追加后重写 summary（确保 report_generated 字段持久化）
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8',
    )

    # ── 步骤 6 报告生成提示（fallback：若硬闭环失败，引导 Agent 手动补救）──
    if not summary.get('report_generated'):
        print('\n' + '-' * 60)
        print('[下一步] 自动报告生成未成功，请手动执行步骤 6：生成自定义 HTML 报告')
        print(f'  输入文件: {results_path}')
        report_html = summary.get('artifacts', {}).get('report_html', f'report_{timestamp}.html')
        print(f'  输出 HTML: {report_html}')
        print('  禁止使用 pytest-html 的 report.html 替代，必须调用 generate_webui_html_report.py')
        print('-' * 60)

    # 退出码：与 pytest 保持一致
    sys.exit(0 if pytest_returncode == 0 else 1)


if __name__ == '__main__':
    main()
