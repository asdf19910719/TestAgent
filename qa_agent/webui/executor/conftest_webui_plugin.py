#!/usr/bin/env python3
"""
WebUI 测试 pytest 插件
通过 pytest hook 机制采集 Playwright 测试的执行数据：
- 每个用例的通过/失败状态、耗时、错误信息
- 失败时自动截图
- 步骤信息记录
- 会话结束时将结果写入 JSON 文件

使用方式：
1. 通过环境变量 TEST_RESULTS_PATH 指定结果输出路径
2. 通过环境变量 SCREENSHOT_DIR 指定截图目录
3. 通过环境变量 VIDEO_DIR 指定视频目录
4. pytest 自动加载本文件作为 conftest 插件
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

# 将 uitest-visual-assist/scripts 加入 sys.path，供 visual_diagnosis / visual_assert 导入
_VISUAL_ASSIST_DIR = str(Path(__file__).resolve().parent.parent.parent / 'uitest-visual-assist' / 'scripts')
if _VISUAL_ASSIST_DIR not in sys.path:
    sys.path.insert(0, _VISUAL_ASSIST_DIR)

_SESSION_BASE_DEFAULT = 'qa/webui/session'


def _resolve_session_base(workspace):
    """通过根指针获取当前会话的 sessionBase，降级时自动跟随动态路径。"""
    if not workspace:
        return _SESSION_BASE_DEFAULT
    pointer = os.path.join(workspace, 'qa/webui', 'current_session.json')
    if os.path.isfile(pointer):
        try:
            with open(pointer, encoding='utf-8') as f:
                data = json.load(f)
            sb = data.get('sessionBase', '')
            if sb:
                return sb
        except (json.JSONDecodeError, OSError):
            pass
    return _SESSION_BASE_DEFAULT


if sys.platform == 'win32':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


# ── 全局状态 ──────────────────────────────────────────────────────────

_test_results = []
_current_steps = []
_session_start_time = None
_test_start_times = {}
_test_end_times = {}

# preflight readiness gate — 三态缓存：unchecked → passed / failed(reason)
_readiness_checked = False
_readiness_skip_reason = ''


def _readiness_screenshot(page, label='readiness_failure'):
    """readiness gate 失败时尝试截图，仅对有效 HTTP(S) 页面截图。"""
    try:
        url = page.url
        if not url or url == 'about:blank' or not url.startswith('http'):
            return
        ss_dir = os.environ.get('SCREENSHOT_DIR', '')
        if not ss_dir:
            return
        Path(ss_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        ss_path = Path(ss_dir) / f'{label}_{ts}.png'
        page.screenshot(path=str(ss_path), full_page=False, timeout=8000)
        print(f'  [readiness] 截图已保存: {ss_path}')
    except Exception as e:
        print(f'  [readiness] 截图失败: {e}')


# ── 失败诊断增强（P1-1） ───────────────────────────────────────────

def _build_fix_guidance(page, error_message, failure_classification):
    """
    基于失败信息、page-elements.json 和当前页面状态构建修复建议。
    优先复用探索阶段的 page-elements.json（避免全 DOM 遍历），
    同时标注数据来源供 Agent 判断可信度。
    """
    import re as _re
    guidance = {'suggestions': [], 'source': '', 'context': {}}

    try:
        guidance['context']['current_url'] = page.url
    except Exception:
        pass

    # 提取失败选择器
    failed_selector = ''
    sel_match = _re.search(r'locator\(["\'](.+?)["\']\)', error_message)
    if not sel_match:
        sel_match = _re.search(r'selector\s*[=:]\s*["\'](.+?)["\']', error_message)
    if sel_match:
        failed_selector = sel_match.group(1)
        guidance['failed_selector'] = failed_selector

    # 尝试从 page-elements.json 查找相似元素
    pe_path = os.environ.get('PAGE_ELEMENTS_PATH', '')
    if not pe_path:
        workspace = os.environ.get('WORKSPACE', '')
        if workspace:
            candidate = Path(workspace) / _resolve_session_base(workspace) / 'artifacts' / 'page-elements.json'
            if candidate.exists():
                pe_path = str(candidate)

    if pe_path and Path(pe_path).exists() and failed_selector:
        try:
            pe_data = json.loads(Path(pe_path).read_text(encoding='utf-8'))
            elements = pe_data.get('elements', [])
            is_smart_xpath_source = pe_data.get('element_source') == 'smart_xpath'
            similar = []
            sel_lower = failed_selector.lower()
            for el in elements[:200]:
                el_text = json.dumps(el, ensure_ascii=False)[:500]
                if any(part in el_text.lower() for part in sel_lower.split('/')[:3] if len(part) > 2):
                    similar.append({k: v for k, v in el.items() if k in ('tag', 'text', 'smart_xpath', 'selector', 'role')})
                    if len(similar) >= 3:
                        break
            if similar:
                guidance['similar_elements'] = similar
                guidance['source'] = 'page-elements.json (exploration phase, may be stale)'
                guidance['suggestions'].append(f'page-elements.json 中发现 {len(similar)} 个相似元素，可替换选择器')

            # 当失败选择器不是 xpath 且 page-elements 提供了 smart XPath 时，
            # 直接给出可替换的 smart XPath，供 LLM 修复时强制使用
            failed_is_css = 'xpath=' not in failed_selector
            if failed_is_css and is_smart_xpath_source:
                recommended_xpath = ''
                for el in similar:
                    sx = el.get('smart_xpath', '')
                    if sx:
                        recommended_xpath = sx
                        break
                if not recommended_xpath:
                    for el in elements[:200]:
                        sx = el.get('smart_xpath', '')
                        if not sx:
                            continue
                        el_text_lower = (el.get('text', '') or '').lower()
                        el_placeholder = ''
                        for sel in el.get('selectors', []):
                            if sel.get('strategy') == 'placeholder':
                                el_placeholder = sel.get('value', '').lower()
                        if (el_text_lower and el_text_lower in sel_lower) or \
                           (el_placeholder and el_placeholder in sel_lower):
                            recommended_xpath = sx
                            break
                if recommended_xpath:
                    guidance['recommended_xpath'] = recommended_xpath
                    guidance['suggestions'].insert(0,
                        f'⛔ 必须将裸 CSS 选择器替换为 smart XPath: '
                        f'page.locator("xpath={recommended_xpath}")')
                elif is_smart_xpath_source:
                    guidance['suggestions'].insert(0,
                        '⛔ 失败选择器为裸 CSS，必须从 page-elements.json 查找对应元素的 '
                        'smart_xpath 字段替换，禁止继续使用 CSS 选择器')
        except Exception:
            pass

    # 分类相关建议
    cls_suggestions = {
        'strict_mode': '改用 page-elements.json 中经唯一性验证的 smart XPath',
        'intercepted_click': '元素被弹窗/浮层遮挡，先关闭遮挡层或使用 resilient_click fixture 自动降级',
        'spa_timing': '页面加载/渲染超时，增加 wait_for_selector 或 wait_for_load_state',
        'hidden_element': '元素不可见或在视口外，使用 scroll_into_view_if_needed()',
        'authentication': '登录态失效，需重新登录',
        'automation_gap': 'Canvas/WebGL 等无 DOM 子结构控件，须使用 uitest-visual-assist '
                          '（canvas_locate + page.mouse.click）走坐标定位方案',
        'canvas_interaction': 'Canvas 交互失败，检查 uitest-visual-assist 视觉能力是否可用；'
                              '使用 canvas_helpers.check_canvas_present 确认元素存在，'
                              '再通过 canvas_vision.canvas_locate 获取坐标后操作',
    }
    if failure_classification in cls_suggestions:
        guidance['suggestions'].append(cls_suggestions[failure_classification])

    if not guidance['source']:
        guidance['source'] = 'error message analysis'

    return guidance


# ── 失败分类 ─────────────────────────────────────────────────────────

def _classify_failure(error_msg: str) -> str:
    """根据错误信息对失败做一级分类（辅助信号，不驱动高风险控制流）。"""
    if not error_msg:
        return 'unknown'
    msg = error_msg
    if 'ModuleNotFoundError' in msg or 'No module named' in msg:
        return 'environment'
    if 'about:blank' in msg:
        return 'navigation_failure'
    if '401' in msg or '403' in msg or 'login' in msg.lower() or 'redirect to login' in msg.lower():
        return 'authentication'
    if 'resolved to' in msg and 'elements' in msg:
        return 'strict_mode'
    if 'intercepts pointer events' in msg:
        return 'intercepted_click'
    if 'not visible' in msg or 'outside viewport' in msg:
        return 'hidden_element'
    if 'Timeout' in msg or 'timeout' in msg.lower():
        return 'spa_timing'
    if 'canvas' in msg.lower() or 'canvas_locate' in msg or 'canvas_click' in msg:
        return 'canvas_interaction'
    return 'assertion'


# ── 跳过原因分类 ─────────────────────────────────────────────────────────

def _classify_skip_reason(reason: str) -> str:
    """对 skip reason 做一级分类，返回 block_reason。"""
    if not reason:
        return 'unknown'
    r = reason.lower()
    if 'environment_failure' in r:
        return 'environment_failure'
    if any(kw in r for kw in ['不可用', '未找到', '无可用', '无可处理',
                                '列表为空', '没有数据', '不存在']):
        return 'blocked_data'
    if any(kw in r for kw in ['canvas', '无法定位内部', '无法自动化',
                                '拖拽框选', '多选框']):
        return 'automation_gap'
    if any(kw in r for kw in ['modulenotfounderror', 'no module',
                                'unrecognized arguments', '参数错误']):
        return 'harness_issue'
    if any(kw in r for kw in ['安全', '不可逆', '破坏性']):
        return 'safety_skip'
    return 'unknown'


# ── 步骤定位推断 ──────────────────────────────────────────────────────

def _infer_failure_step_index(error_message: str, test_file_path: str):
    """
    通过 traceback 行号 + 源码 '# 步骤 N:' 注释推断失败所在步骤。

    优先取测试函数体（test_* 函数）的帧行号，而非 helper 内最深帧，
    以便和步骤注释正确映射。
    """
    result = {'failure_step_index': None, 'failure_step_text': None, 'total_steps': 0}
    if not error_message or not test_file_path:
        return result

    test_path = Path(test_file_path)
    if not test_path.exists():
        return result

    try:
        source_lines = test_path.read_text(encoding='utf-8').splitlines()
    except Exception:
        return result

    step_map = []
    for line_no, line in enumerate(source_lines, 1):
        stripped = line.strip()
        if re.match(r'^#\s*步骤\s*\d+', stripped):
            step_map.append((line_no, stripped))
    result['total_steps'] = len(step_map)
    if not step_map:
        return result

    test_file_name = test_path.name
    candidate_line = None

    for raw_line in error_message.splitlines():
        raw_line = raw_line.strip()
        if test_file_name not in raw_line:
            continue
        m = re.search(rf'{re.escape(test_file_name)}:(\d+)', raw_line)
        if not m:
            continue
        line_no = int(m.group(1))
        fn_line_text = source_lines[line_no - 1].strip() if line_no <= len(source_lines) else ''
        if fn_line_text.startswith('def test_') or re.match(r'^def test_', fn_line_text):
            continue
        is_in_test_fn = False
        for i in range(line_no - 1, -1, -1):
            if source_lines[i].strip().startswith('def test_'):
                is_in_test_fn = True
                break
            if source_lines[i].strip().startswith('def ') and not source_lines[i].strip().startswith('def test_'):
                break
        if is_in_test_fn:
            candidate_line = line_no
            break
        if candidate_line is None:
            candidate_line = line_no

    if candidate_line is None:
        return result

    matched_step = None
    for idx, (step_line, step_text) in enumerate(step_map):
        if step_line <= candidate_line:
            matched_step = (idx + 1, step_text)
        else:
            break
    if matched_step:
        result['failure_step_index'] = matched_step[0]
        result['failure_step_text'] = matched_step[1]

    return result


# ── Pytest Fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope='session')
def browser_type_launch_args(browser_type_launch_args):
    """
    Playwright 浏览器启动参数（继承覆写模式）。
    强制无头模式：忽略 HEADLESS 环境变量，始终使用 headless=True。
    唯一例外：环境变量 FORCE_HEADED=1（供人工调试使用）。
    """
    headless = os.environ.get('FORCE_HEADED') != '1'
    browser_type_launch_args['headless'] = headless
    return browser_type_launch_args


@pytest.fixture(scope='session')
def browser_context_args(browser_context_args):
    """
    Playwright 浏览器上下文参数（继承覆写模式）。
    接收 pytest-playwright 的默认 browser_context_args，在其基础上扩展：
    - 视口尺寸、区域设置
    - 视频录制
    - 登录状态恢复（storage_state）
    - 全用例截图（通过环境变量控制）
    """
    browser_context_args['locale'] = 'zh-CN'

    try:
        vw = int(os.environ.get('VIEWPORT_WIDTH', '1920'))
    except (ValueError, TypeError):
        vw = 1920
    try:
        vh = int(os.environ.get('VIEWPORT_HEIGHT', '1080'))
    except (ValueError, TypeError):
        vh = 1080
    browser_context_args['viewport'] = {'width': vw, 'height': vh}

    # 强制 DPI 缩放因子为 1，确保 headless 模式下录屏/截图分辨率
    # 与配置视口完全一致（避免 Retina/HiDPI 屏幕导致实际像素翻倍）
    browser_context_args['device_scale_factor'] = 1

    # 视频录制
    if os.environ.get('VIDEO_ENABLED', '0') == '1':
        video_dir = os.environ.get('VIDEO_DIR', '')
        if video_dir:
            Path(video_dir).mkdir(parents=True, exist_ok=True)
            browser_context_args['record_video_dir'] = video_dir
            browser_context_args['record_video_size'] = {'width': vw, 'height': vh}

    # 登录状态恢复（含格式校验）
    login_state = os.environ.get('LOGIN_STATE_PATH', '')
    if login_state and Path(login_state).exists():
        _state_valid = True
        try:
            _state_data = json.loads(Path(login_state).read_text(encoding='utf-8'))
            if not isinstance(_state_data, dict):
                print(f'[LOGIN_STATE] 格式不合法，已跳过加载: 内容不是 JSON 对象')
                _state_valid = False
            elif not isinstance(_state_data.get('cookies'), list):
                print(f'[LOGIN_STATE] 格式不合法，已跳过加载: 缺少 cookies 数组（非 Playwright storage_state 格式）')
                _state_valid = False
            elif 'origins' not in _state_data:
                print(f'[LOGIN_STATE] 格式不合法，已跳过加载: 缺少 origins 字段（非 Playwright storage_state 格式）')
                _state_valid = False
        except Exception as _e:
            print(f'[LOGIN_STATE] 格式不合法，已跳过加载: JSON 解析失败 ({_e})')
            _state_valid = False
        if _state_valid:
            browser_context_args['storage_state'] = login_state

    return browser_context_args


@pytest.fixture
def step_recorder():
    """
    步骤记录器 fixture。
    测试用例可通过该 fixture 记录操作步骤信息。

    使用示例：
        def test_login(page, step_recorder):
            step_recorder("导航到登录页", "navigate")
            page.goto("https://example.com/login")
    """
    steps = []

    def record(description, action_type='action', selector='', value=''):
        step_info = {
            'step_no': len(steps) + 1,
            'description': description,
            'action_type': action_type,
            'selector': selector,
            'value': value,
            'timestamp': datetime.now().astimezone().isoformat(),
        }
        steps.append(step_info)
        return step_info

    record._steps = steps
    return record


@pytest.fixture
def visual_verify(page):
    """场景 B：视觉交叉验证 fixture。P0/P1 用例在函数参数中声明即可使用。

    不匹配时 warnings.warn + pytest.xfail（不阻断其他用例）。
    视觉不可用时静默无操作。
    """
    def _verify(description: str):
        try:
            from visual_assert import visual_verify_impl
            matched, reason = visual_verify_impl(page, description)
            if not matched:
                import warnings
                warnings.warn(
                    f"[视觉验证不匹配] {description} (reason: {reason})",
                    stacklevel=2,
                )
                pytest.xfail(f"视觉验证不匹配: {reason}")
        except ImportError:
            pass
    return _verify


_click_downgrade_events = []


@pytest.fixture
def resilient_click():
    """三级 click 降级 fixture：L1 正常 → L2 force → L3 JS evaluate。

    用法：level = resilient_click(locator) 或 resilient_click(locator, timeout=3000)
    返回值为 'L1'/'L2'/'L3'，L2/L3 成功时自动记录降级事件供 Agent 分析。
    """
    _DOWNGRADE_KEYWORDS = ('not visible', 'intercepts pointer', 'outside viewport',
                           'element is not stable', 'not attached')

    def _click(locator, timeout=5000):
        # L1: 标准 Playwright click（actionability 全检查）
        try:
            locator.click(timeout=timeout)
            return 'L1'
        except Exception as e1:
            err_msg = str(e1)
            if not any(kw in err_msg.lower() for kw in _DOWNGRADE_KEYWORDS):
                raise
            l1_error = err_msg
        # L2: force click（跳过遮挡检查）
        try:
            locator.click(force=True, timeout=min(timeout, 3000))
            import warnings
            warnings.warn(
                f'[click-downgrade] L2 force=True 成功（原始错误: {l1_error[:120]}）',
                stacklevel=2,
            )
            _click_downgrade_events.append({
                'level': 'L2', 'error': l1_error[:200],
                'timestamp': datetime.now().astimezone().isoformat(),
            })
            return 'L2'
        except Exception:
            pass
        # L3: JS evaluate（最后手段）
        try:
            locator.evaluate('el => el.click()')
            import warnings
            warnings.warn(
                f'[click-downgrade] L3 JS evaluate 成功（原始错误: {l1_error[:120]}），建议修复选择器',
                stacklevel=2,
            )
            _click_downgrade_events.append({
                'level': 'L3', 'error': l1_error[:200],
                'timestamp': datetime.now().astimezone().isoformat(),
            })
            return 'L3'
        except Exception as e3:
            raise type(e3)(f'三级 click 均失败 (L1: {l1_error[:100]}): {e3}') from e3
    return _click


@pytest.fixture(autouse=True)
def _cleanup_before_test(page):
    """
    每个测试前清理遗留弹窗/浮层（P1-5），
    通过 fixture 依赖确保在 readiness gate 之前执行。
    """
    try:
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        for close_sel in ['.el-dialog__close', '.el-message-box__close',
                          '.el-notification__closeBtn', '.el-popover']:
            try:
                btn = page.locator(f'{close_sel}:visible').first
                if btn.is_visible(timeout=200):
                    btn.click()
                    page.wait_for_timeout(300)
            except Exception:
                pass
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _preflight_readiness_gate(_cleanup_before_test, page):
    """
    首条用例执行前做一次环境 readiness 校验（三态缓存）。

    状态转换：unchecked → passed（后续用例直接放行）
                        → failed（后续用例直接 skip，不重复 goto）

    fixture 自己先导航到 TARGET_URL，避免在测试尚未导航时误判 about:blank。
    通过参数依赖 _cleanup_before_test 保证弹窗清理先执行。

    开关：WEBUI_READINESS_GATE=0 可显式关闭（不做 preflight 导航和检查）。
    默认启用（=1 或未设置）。
    """
    global _readiness_checked, _readiness_skip_reason
    if _readiness_checked:
        if _readiness_skip_reason:
            pytest.skip(_readiness_skip_reason)
        return

    _readiness_checked = True

    # login-state mtime 安全网（P0-3）
    login_state_path = os.environ.get('LOGIN_STATE_PATH', '')
    session_ctx_path = os.environ.get('SESSION_CONTEXT_PATH', '')
    if login_state_path and Path(login_state_path).exists() and session_ctx_path and Path(session_ctx_path).exists():
        try:
            ls_mtime = Path(login_state_path).stat().st_mtime
            ctx_data = json.loads(Path(session_ctx_path).read_text(encoding='utf-8'))
            from datetime import datetime as _dt, timezone as _tz
            created_str = ctx_data.get('createdAt', '')
            if not created_str:
                raise ValueError('createdAt field is empty')
            _dt_obj = _dt.fromisoformat(created_str.replace('Z', '+00:00'))
            if _dt_obj.tzinfo is None:
                _dt_obj = _dt_obj.replace(tzinfo=_tz.utc)
            created_at = _dt_obj.timestamp()
            login_duration_min = (ls_mtime - created_at) / 60
            if login_duration_min > 10:
                print(f'[WARN] 登录阶段耗时 {login_duration_min:.1f} 分钟（> 10 分钟），可能存在登录循环')
        except Exception:
            pass

    if os.environ.get('WEBUI_READINESS_GATE', '1') == '0':
        return

    target_url = os.environ.get('TARGET_URL', '')
    if not target_url:
        return

    try:
        page.goto(target_url, wait_until='load', timeout=30000)
    except Exception as e:
        _readiness_skip_reason = (
            f'ENVIRONMENT_FAILURE: navigation to {target_url} failed: {e}\n'
            f'[RECOVERY] 建议: 检查网络连通性和目标 URL 可用性，'
            f'或重新执行登录流程刷新 login-state.json')
        _readiness_screenshot(page, 'readiness_nav_fail')
        pytest.skip(_readiness_skip_reason)

    url = page.url
    if url == 'about:blank' or not url.startswith('http'):
        _readiness_skip_reason = (
            f'ENVIRONMENT_FAILURE: page is about:blank after navigation to {target_url}\n'
            f'[RECOVERY] 建议: login-state.json 可能已过期或格式不正确，'
            f'请重新执行 uitest-login-handler 刷新登录态')
        pytest.skip(_readiness_skip_reason)

    # P2-1: URL 重定向检测 + SSO 特征检测
    from urllib.parse import urlparse as _urlparse
    target_parsed = _urlparse(target_url)
    current_parsed = _urlparse(url)
    sso_patterns = ['/login', '/sso', '/cas', '/signin', '/sign-in', '/auth']
    if any(seg in current_parsed.path.lower() for seg in sso_patterns):
        _readiness_skip_reason = (
            f'ENVIRONMENT_FAILURE: redirected to login/SSO page ({url})\n'
            f'[RECOVERY] 建议: 登录态已失效（cookie/token 过期），'
            f'请重新执行 uitest-login-handler 并更新 login-state.json')
        _readiness_screenshot(page, 'readiness_sso_redirect')
        pytest.skip(_readiness_skip_reason)

    if current_parsed.hostname != target_parsed.hostname:
        _readiness_skip_reason = (
            f'ENVIRONMENT_FAILURE: redirected to different host '
            f'(target: {target_parsed.hostname}, actual: {current_parsed.hostname})\n'
            f'[RECOVERY] 建议: 登录态可能指向错误域名，请重新登录')
        _readiness_screenshot(page, 'readiness_host_mismatch')
        pytest.skip(_readiness_skip_reason)

    target_path = target_parsed.path.rstrip('/')
    current_path = current_parsed.path.rstrip('/')
    if target_path and current_path != target_path and not current_path.startswith(target_path + '/'):
        _readiness_skip_reason = (
            f'ENVIRONMENT_FAILURE: URL path mismatch '
            f'(target: {target_path}, actual: {current_path})\n'
            f'[RECOVERY] 建议: 页面跳转到非预期路径，请检查 TARGET_URL 设置或重新登录')
        _readiness_screenshot(page, 'readiness_path_mismatch')
        pytest.skip(_readiness_skip_reason)

    readiness_selector = os.environ.get('READINESS_SELECTOR', '')
    if readiness_selector:
        try:
            page.locator(readiness_selector).first.wait_for(state='visible', timeout=15000)
        except Exception:
            _readiness_skip_reason = (
                f'ENVIRONMENT_FAILURE: readiness selector not found: {readiness_selector}\n'
                f'[RECOVERY] 建议: 页面元素未加载完成，检查目标 URL 是否正确或重新登录')
            _readiness_screenshot(page, 'readiness_selector_miss')
            pytest.skip(_readiness_skip_reason)
    else:
        # SPA 轮询等待：load 事件后 SPA 框架仍需异步渲染，
        # 在 SPA_WAIT_MS 窗口内每 500ms 检测一次可交互元素，
        # 一旦发现 >= 1 个立即通过，无需等满全部时间
        try:
            spa_wait = int(os.environ.get('SPA_WAIT_MS', '5000'))
        except (ValueError, TypeError):
            spa_wait = 5000
        if spa_wait < 0:
            spa_wait = 0
        _poll_interval = 500
        _elapsed = 0
        count = 0
        _interactive_sel = 'button:visible, a[href]:visible, input:visible, select:visible, textarea:visible'
        while True:
            try:
                count = page.locator(_interactive_sel).count()
            except Exception:
                count = 0
            if count >= 1:
                break
            if _elapsed >= spa_wait:
                break
            page.wait_for_timeout(_poll_interval)
            _elapsed += _poll_interval
        if count < 1:
            _readiness_skip_reason = (
                f'ENVIRONMENT_FAILURE: no visible interactive elements found (polled {_elapsed}ms)\n'
                '[RECOVERY] 建议: 页面无可交互元素，可能未正确加载或登录态已失效，'
                '请重新执行 uitest-login-handler')
            _readiness_screenshot(page, 'readiness_no_elements')
            pytest.skip(_readiness_skip_reason)


# ── Pytest Hooks ─────────────────────────────────────────────────────

def pytest_sessionstart(session):
    """
    测试会话开始时的钩子。
    记录会话开始时间，初始化全局状态。
    """
    global _session_start_time, _test_results
    _session_start_time = time.time()
    _test_results = []
    print('\n[conftest_webui_plugin] 测试会话已启动')


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    测试用例执行报告钩子（核心）。
    在测试的 setup / call / teardown 各阶段采集数据。

    - setup 阶段: 记录开始时间
    - call 阶段: 采集执行结果、截图（失败时）、步骤信息
    - teardown 阶段: 采集视频路径
    """
    outcome = yield
    report = outcome.get_result()

    # setup 阶段：记录用例开始时间（独立计时）
    if report.when == 'setup':
        _test_start_times[item.nodeid] = time.time()

    # 只在 call 阶段（实际测试执行）处理主要逻辑
    if report.when == 'call':
        test_name = item.name
        test_nodeid = item.nodeid

        # 记录结束时间
        end_t = time.time()
        _test_end_times[test_nodeid] = end_t

        # 优先用自己的计时（避免 report.duration 为 0 的问题）
        start_t = _test_start_times.get(test_nodeid)
        if start_t:
            duration_ms = round((end_t - start_t) * 1000, 2)
        else:
            duration_ms = round(report.duration * 1000, 2)

        # 确定测试状态
        if report.passed:
            status = 'PASSED'
        elif report.failed:
            status = 'FAILED'
        elif report.skipped:
            status = 'SKIPPED'
        else:
            status = 'ERROR'

        # 提取错误信息
        error_message = ''
        if report.failed:
            if report.longrepr:
                error_message = str(report.longrepr)
                # 截取错误信息（避免过长）
                if len(error_message) > 2000:
                    error_message = error_message[:2000] + '\n... (已截断)'

        # 分层截图策略：通过用例截最终状态；失败用例截详细（full_page）
        screenshots = []
        always_screenshot = os.environ.get('SCREENSHOT_ALWAYS', '1') == '1'
        should_screenshot = always_screenshot or status in ('FAILED', 'ERROR')
        if should_screenshot and os.environ.get('SCREENSHOT_ON_FAILURE', '1') == '1':
            use_full_page = status in ('FAILED', 'ERROR')
            screenshot_path = _take_screenshot(
                item, test_name, status, full_page=use_full_page)
            if screenshot_path:
                screenshots.append(screenshot_path)

        # 获取步骤信息
        steps = []
        if hasattr(item, 'funcargs') and 'step_recorder' in item.funcargs:
            recorder = item.funcargs['step_recorder']
            if hasattr(recorder, '_steps'):
                steps = recorder._steps

        # 获取视频路径（转为相对路径，避免报告中出现双层目录）
        video_path = ''
        if hasattr(item, 'funcargs') and 'page' in item.funcargs:
            try:
                page = item.funcargs['page']
                if page.video:
                    raw_video = Path(str(page.video.path()))
                    # 尝试转为相对于工作空间的路径
                    workspace = os.environ.get('WORKSPACE', '')
                    if workspace:
                        try:
                            video_path = str(raw_video.relative_to(workspace))
                        except ValueError:
                            video_path = str(raw_video)
                    else:
                        video_path = str(raw_video)
            except Exception:
                pass

        # 失败时采集结构化页面状态（URL、弹窗、可见按钮等）
        page_context = {}
        if status in ('FAILED', 'ERROR', 'SKIPPED') and hasattr(item, 'funcargs') and 'page' in item.funcargs:
            try:
                pg = item.funcargs['page']
                page_context = pg.evaluate('''() => {
                    const dialogs = document.querySelectorAll(
                        '[role="dialog"]:not([style*="display: none"]):not([style*="display:none"]), '
                        + '.el-dialog:not([style*="display: none"]):not([style*="display:none"]), '
                        + '.ant-modal:not([style*="display: none"]):not([style*="display:none"])'
                    );
                    const buttons = [...document.querySelectorAll('button:not([style*="display: none"])')];
                    const visibleBtns = buttons.filter(b => b.offsetParent !== null)
                        .map(b => b.textContent.trim()).filter(Boolean);
                    return {
                        url: location.href,
                        title: document.title,
                        has_visible_dialog: dialogs.length > 0,
                        visible_dialog_titles: [...dialogs].map(d => {
                            const h = d.querySelector(
                                '.el-dialog__title, .ant-modal-title, [class*="dialog"] [class*="title"]'
                            );
                            return h ? h.textContent.trim() : '';
                        }).filter(Boolean),
                        visible_buttons: visibleBtns.slice(0, 20),
                        visible_placeholders: [...document.querySelectorAll('[placeholder]')]
                            .filter(el => el.offsetParent !== null)
                            .map(el => el.getAttribute('placeholder'))
                            .slice(0, 20),
                    };
                }''')
            except Exception:
                page_context = {'error': 'page context capture failed'}

        # 截图路径也转为相对路径
        rel_screenshots = []
        workspace = os.environ.get('WORKSPACE', '')
        for sp in screenshots:
            if workspace:
                try:
                    rel_screenshots.append(str(Path(sp).relative_to(workspace)))
                except ValueError:
                    rel_screenshots.append(sp)
            else:
                rel_screenshots.append(sp)

        # 提取 docstring 作为中文描述
        description = ''
        if hasattr(item, 'function') and item.function.__doc__:
            description = item.function.__doc__.strip()

        # 提取 pytest marker 中的优先级（取最高，即 P 数字最小的）
        priority = ''
        for marker in item.iter_markers():
            mk = marker.name.upper()
            if mk in ('P0', 'P1', 'P2', 'P3', 'P4'):
                if not priority or mk < priority:
                    priority = mk

        # 构建测试结果
        # 同时输出别名字段以兼容下游多种消费者：
        #   name / case_name — 缺陷分析和评审脚本使用 case_name
        #   nodeid / node_id — 重试合并脚本使用 node_id
        #   duration_ms — 统一时长字段（毫秒）；duration_display — 人可读格式
        # 失败分类 & 步骤定位 & 修复建议（P0-3 + P1-1）
        failure_classification = ''
        step_info = {}
        fix_guidance = {}
        if status in ('FAILED', 'ERROR') and error_message:
            failure_classification = _classify_failure(error_message)
            test_file = os.environ.get('TEST_FILE', '')
            if not test_file:
                workspace = os.environ.get('WORKSPACE', '')
                if workspace:
                    candidate = Path(workspace) / _resolve_session_base(workspace) / 'artifacts' / 'test_webui.py'
                    if candidate.exists():
                        test_file = str(candidate)
            step_info = _infer_failure_step_index(error_message, test_file)
            if hasattr(item, 'funcargs') and 'page' in item.funcargs:
                try:
                    fix_guidance = _build_fix_guidance(
                        item.funcargs['page'], error_message, failure_classification)
                except Exception:
                    fix_guidance = {'error': 'fix guidance generation failed'}

        skip_reason = ''
        if status == 'SKIPPED' and report.longrepr:
            if isinstance(report.longrepr, tuple) and len(report.longrepr) >= 3:
                skip_reason = str(report.longrepr[2])
            else:
                skip_reason = str(report.longrepr)
        block_reason = _classify_skip_reason(skip_reason) if status == 'SKIPPED' else ''

        # ── 场景 A：失败时视觉诊断（仅 FAILED/ERROR 触发，通过用例零开销）──
        vision_diagnosis = {}
        if status in ('FAILED', 'ERROR') and rel_screenshots:
            try:
                from visual_diagnosis import diagnose_failure
                _ss_path = Path(rel_screenshots[0])
                if not _ss_path.is_absolute():
                    _ws = os.environ.get('WORKSPACE', '')
                    if _ws:
                        _ss_path = Path(_ws) / _ss_path
                if _ss_path.exists():
                    screenshot_data = _ss_path.read_bytes()
                    vision_diagnosis = diagnose_failure(
                        screenshot_data, error_message, page_context,
                        test_description=description,
                    )
                    if vision_diagnosis.get('visual_classification'):
                        vision_diagnosis['fallback_classification'] = failure_classification
                        failure_classification = vision_diagnosis['visual_classification']
            except Exception:
                pass

        test_result = {
            'name': test_name,
            'case_name': test_name,
            'nodeid': test_nodeid,
            'node_id': test_nodeid,
            'description': description,
            'status': status,
            'duration_ms': duration_ms,
            'duration_display': f'{duration_ms / 1000:.2f}s' if duration_ms >= 1000 else f'{duration_ms:.0f}ms',
            'priority': priority or 'P3',
            'error_message': error_message,
            'block_reason': block_reason,
            'failure_classification': failure_classification,
            'failure_step_index': step_info.get('failure_step_index'),
            'failure_step_text': step_info.get('failure_step_text'),
            'total_steps': step_info.get('total_steps', 0),
            'fix_guidance': fix_guidance,
            'vision_diagnosis': vision_diagnosis,
            'screenshots': rel_screenshots,
            'video': video_path,
            'steps': steps,
            'page_context': page_context,
            'timestamp': datetime.now().astimezone().isoformat(),
        }

        _test_results.append(test_result)

        status_icon = {'PASSED': '[通过]', 'FAILED': '[失败]', 'ERROR': '[错误]', 'SKIPPED': '[跳过]'}
        extra = f' [block_reason={block_reason}]' if block_reason else ''
        print(f'  {status_icon.get(status, "[?]")} {test_name} ({duration_ms}ms){extra}')
        if error_message:
            first_line = error_message.split('\n')[0]
            print(f'    错误: {first_line[:100]}')
            if failure_classification:
                print(f'    分类: {failure_classification}')
            if step_info.get('failure_step_index'):
                print(f'    失败步骤: {step_info["failure_step_text"]}')

    elif report.when == 'setup' and report.skipped:
        reason = ''
        if report.longrepr and isinstance(report.longrepr, tuple) and len(report.longrepr) >= 3:
            reason = str(report.longrepr[2])
        elif report.longrepr:
            reason = str(report.longrepr)
        is_env_failure = 'ENVIRONMENT_FAILURE' in reason
        block_reason = _classify_skip_reason(reason)

        description = ''
        if hasattr(item, 'function') and item.function.__doc__:
            description = item.function.__doc__.strip()

        # 提取 pytest marker 中的优先级（取最高，即 P 数字最小的）
        priority = ''
        for marker in item.iter_markers():
            mk = marker.name.upper()
            if mk in ('P0', 'P1', 'P2', 'P3', 'P4'):
                if not priority or mk < priority:
                    priority = mk

        # 尝试采集 page_context（setup-skipped 时 page 可能仍可用）
        page_context = {}
        if hasattr(item, 'funcargs') and 'page' in item.funcargs:
            try:
                pg = item.funcargs['page']
                page_context = pg.evaluate('''() => ({
                    url: location.href,
                    title: document.title,
                    has_visible_dialog: document.querySelectorAll(
                        '[role="dialog"]:not([style*="display: none"])').length > 0,
                    visible_buttons: [...document.querySelectorAll('button')]
                        .filter(b => b.offsetParent !== null)
                        .map(b => b.textContent.trim()).filter(Boolean).slice(0, 20),
                })''')
            except Exception:
                page_context = {'error': 'page not available for skipped test'}

        test_result = {
            'name': item.name,
            'case_name': item.name,
            'nodeid': item.nodeid,
            'node_id': item.nodeid,
            'description': description,
            'status': 'SKIPPED',
            'duration_ms': 0,
            'duration_display': '0ms',
            'priority': priority or 'P3',
            'error_message': reason,
            'block_reason': block_reason,
            'failure_classification': 'environment_failure' if is_env_failure else block_reason,
            'failure_step_index': None,
            'failure_step_text': None,
            'total_steps': 0,
            'screenshots': [],
            'video': '',
            'steps': [],
            'page_context': page_context,
            'timestamp': datetime.now().astimezone().isoformat(),
        }
        _test_results.append(test_result)
        tag = '[环境异常]' if is_env_failure else '[跳过]'
        print(f'  {tag} {item.name}: {reason[:100]} [block_reason={block_reason}]')

    elif report.when == 'setup' and report.failed:
        # setup 阶段失败 — 也提取 docstring
        description = ''
        if hasattr(item, 'function') and item.function.__doc__:
            description = item.function.__doc__.strip()
        setup_duration_ms = round(report.duration * 1000, 2)
        test_result = {
            'name': item.name,
            'case_name': item.name,
            'nodeid': item.nodeid,
            'node_id': item.nodeid,
            'description': description,
            'status': 'ERROR',
            'duration_ms': setup_duration_ms,
            'duration_display': f'{setup_duration_ms / 1000:.2f}s' if setup_duration_ms >= 1000 else f'{setup_duration_ms:.0f}ms',
            'priority': 'P3',
            'error_message': f'Setup 阶段失败: {str(report.longrepr)[:500]}',
            'screenshots': [],
            'video': '',
            'steps': [],
            'timestamp': datetime.now().astimezone().isoformat(),
        }
        _test_results.append(test_result)
        print(f'  [错误] {item.name} (setup 失败)')


_RETRYABLE_ERRORS = (
    'execution context was destroyed',
    'frame was detached',
    'page was closed',
    'target closed',
    'connection closed',
)


def _take_screenshot(item, test_name, status='FAILED', full_page=False):
    """
    截取页面截图。
    分层策略：通过用例截当前视口；失败用例截全页面（full_page=True）。
    对浏览器瞬态错误自动重试一次。

    Args:
        item: pytest item 对象
        test_name: 测试用例名称
        status: 用例状态，用于文件名标识
        full_page: 是否截取全页面（失败用例建议 True）

    Returns:
        str: 截图文件路径，失败时返回空字符串
    """
    screenshot_dir = os.environ.get('SCREENSHOT_DIR', '')
    if not screenshot_dir:
        return ''

    Path(screenshot_dir).mkdir(parents=True, exist_ok=True)

    try:
        if hasattr(item, 'funcargs') and 'page' in item.funcargs:
            page = item.funcargs['page']
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in test_name)
            status_tag = status.lower()
            filename = f'{safe_name}_{status_tag}_{timestamp}.png'
            screenshot_path = Path(screenshot_dir) / filename

            max_attempts = 2
            for attempt in range(max_attempts):
                try:
                    page.screenshot(path=str(screenshot_path),
                                    full_page=full_page, timeout=10000)
                    print(f'    截图已保存: {screenshot_path}')
                    return str(screenshot_path)
                except Exception as e:
                    err_msg = str(e).lower()
                    is_retryable = any(r in err_msg for r in _RETRYABLE_ERRORS)
                    if is_retryable and attempt < max_attempts - 1:
                        import time
                        time.sleep(0.5)
                        continue
                    try:
                        page.screenshot(path=str(screenshot_path),
                                        full_page=False, timeout=5000)
                        print(f'    截图已保存(降级): {screenshot_path}')
                        return str(screenshot_path)
                    except Exception as inner_e:
                        print(f'    警告: 截图失败: {inner_e}')
                        return ''
    except Exception as e:
        print(f'    警告: 截图失败: {e}')

    return ''


def _rename_videos():
    """
    将 Playwright 生成的随机 hash 命名视频文件重命名为可读格式。

    命名格式：{用例ID或函数名}_{时间戳}.webm
    示例：tcjh_0068_20260312143000.webm、test_create_task_20260312143000.webm

    命名优先级：
    1. 从 docstring 中提取用例 ID（如 "CSV用例 tcjh_0068：xxx" → tcjh_0068_20260312143000.webm）
    2. 回退到函数名（如 test_batch_reference → test_batch_reference_20260312143000.webm）

    时间戳取自 VIDEO_DIR 文件夹名（与本次测试执行时间一致），
    若取不到则使用当前时间生成。

    重命名后同步更新 _test_results 中的 video 路径。
    """
    global _test_results

    workspace = os.environ.get('WORKSPACE', '')

    # 从 VIDEO_DIR 文件夹名提取时间戳，保持与执行时间一致
    video_dir_env = os.environ.get('VIDEO_DIR', '')
    run_ts = ''
    if video_dir_env:
        run_ts = Path(video_dir_env).name  # e.g. "20260312143000"
    if not run_ts or not run_ts.isdigit():
        run_ts = datetime.now().strftime('%Y%m%d%H%M%S')

    # 用于从 docstring 中提取用例 ID 的正则
    # 匹配格式: "CSV用例 xxx：" 或 "CSV用例 xxx:" 或 "用例ID: xxx"
    case_id_patterns = [
        re.compile(r'CSV用例\s+(\S+?)[\s：:]'),
        re.compile(r'用例ID[\s：:]\s*(\S+)'),
        re.compile(r'case_id[\s：:]\s*(\S+)', re.IGNORECASE),
    ]

    for result in _test_results:
        video_path_str = result.get('video', '')
        if not video_path_str:
            continue

        video_path = Path(video_path_str)
        # 如果是相对路径，基于 workspace 解析
        if not video_path.is_absolute() and workspace:
            video_path = Path(workspace) / video_path

        if not video_path.exists():
            continue

        # 尝试从 docstring 提取用例 ID
        case_id = ''
        description = result.get('description', '')
        if description:
            for pattern in case_id_patterns:
                match = pattern.search(description)
                if match:
                    case_id = match.group(1)
                    break

        # 构建文件名：{用例ID或函数名}_{时间戳}.webm
        if case_id:
            safe_id = ''.join(c if c.isalnum() or c in '-_' else '_' for c in case_id)
            new_name = f'{safe_id}_{run_ts}.webm'
        else:
            test_name = result.get('name', 'unknown')
            safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in test_name)
            new_name = f'{safe_name}_{run_ts}.webm'

        new_path = video_path.parent / new_name

        # 避免重名冲突（同一次执行中同名用例多次出现）
        base_stem = new_name.rsplit('.', 1)[0]
        counter = 1
        while new_path.exists() and new_path != video_path:
            new_name = f'{base_stem}_{counter}.webm'
            new_path = video_path.parent / new_name
            counter += 1

        try:
            video_path.rename(new_path)
            # 更新结果中的路径（保持与原始路径相同的格式：绝对或相对）
            if Path(video_path_str).is_absolute():
                result['video'] = str(new_path)
            else:
                # 保持相对路径格式
                if workspace:
                    try:
                        result['video'] = str(new_path.relative_to(workspace))
                    except ValueError:
                        result['video'] = str(new_path)
                else:
                    result['video'] = str(new_path)
            print(f'  视频已重命名: {video_path.name} -> {new_name}')
        except Exception as e:
            print(f'  警告: 视频重命名失败 {video_path.name}: {e}')


def _probe_webm_dimensions(test_results, workspace):
    """Extract pixel dimensions from the first available WebM video.

    Structurally traverses the EBML/Matroska container hierarchy:
      Segment > Tracks > TrackEntry > Video > PixelWidth / PixelHeight
    Returns {'width': int, 'height': int} or None on failure.
    """
    # Matroska element IDs (big-endian bytes)
    _ID_SEGMENT    = b'\x18\x53\x80\x67'
    _ID_TRACKS     = b'\x16\x54\xae\x6b'
    _ID_TRACK_ENTRY = b'\xae'
    _ID_TRACK_TYPE = b'\x83'
    _ID_VIDEO      = b'\xe0'
    _ID_PIXEL_W    = b'\xb0'
    _ID_PIXEL_H    = b'\xba'
    _TRACK_TYPE_VIDEO = 1

    def _read_vint(data, offset):
        if offset >= len(data):
            return None, 0
        first = data[offset]
        if first == 0:
            return None, 0
        length = 1
        mask = 0x80
        while mask and not (first & mask):
            length += 1
            mask >>= 1
        if offset + length > len(data):
            return None, 0
        val = first & (mask - 1)
        for i in range(1, length):
            val = (val << 8) | data[offset + i]
        return val, length

    def _read_element_id(data, offset):
        if offset >= len(data):
            return None, 0
        first = data[offset]
        if first == 0:
            return None, 0
        length = 1
        mask = 0x80
        while mask and not (first & mask):
            length += 1
            mask >>= 1
        if offset + length > len(data):
            return None, 0
        return data[offset:offset + length], length

    def _iter_children(data, start, end):
        """Yield (element_id_bytes, content_start, content_end) within a range."""
        i = start
        buf_end = min(end, len(data))
        while i < buf_end - 2:
            eid, eid_len = _read_element_id(data, i)
            if eid is None or eid_len == 0:
                return
            size_raw, size_len = _read_vint(data, i + eid_len)
            if size_raw is None or size_len == 0:
                return
            content_start = i + eid_len + size_len
            all_ones = (1 << (7 * size_len)) - 1
            if size_raw == all_ones:
                yield eid, content_start, buf_end
                return
            content_end = content_start + size_raw
            yield eid, content_start, content_end
            i = content_end

    def _parse_uint(data, start, end):
        length = end - start
        if length < 1 or length > 4 or end > len(data):
            return None
        return int.from_bytes(data[start:end], 'big')

    def _extract_from_video(data, start, end):
        width = height = None
        for eid, cs, ce in _iter_children(data, start, end):
            if eid == _ID_PIXEL_W:
                width = _parse_uint(data, cs, ce)
            elif eid == _ID_PIXEL_H:
                height = _parse_uint(data, cs, ce)
            if width and height:
                return {'width': width, 'height': height}
        return None

    def _extract_from_track_entry(data, start, end):
        is_video = False
        video_range = None
        for eid, cs, ce in _iter_children(data, start, end):
            if eid == _ID_TRACK_TYPE:
                is_video = (_parse_uint(data, cs, ce) == _TRACK_TYPE_VIDEO)
            elif eid == _ID_VIDEO:
                video_range = (cs, ce)
        if is_video and video_range:
            return _extract_from_video(data, *video_range)
        return None

    def _extract_from_buffer(data):
        for eid, cs, ce in _iter_children(data, 0, len(data)):
            if eid != _ID_SEGMENT:
                continue
            for s_eid, s_cs, s_ce in _iter_children(data, cs, ce):
                if s_eid != _ID_TRACKS:
                    continue
                for t_eid, t_cs, t_ce in _iter_children(data, s_cs, s_ce):
                    if t_eid == _ID_TRACK_ENTRY:
                        result = _extract_from_track_entry(data, t_cs, t_ce)
                        if result:
                            return result
        return None

    for tr in test_results:
        vp = tr.get('video', '')
        if not vp:
            continue
        vpath = Path(vp)
        if not vpath.is_absolute() and workspace:
            vpath = Path(workspace) / vp.replace('\\', '/')
        if vpath.exists() and vpath.suffix.lower() == '.webm':
            try:
                with open(vpath, 'rb') as f:
                    chunk = f.read(16384)
                result = _extract_from_buffer(chunk)
                if result:
                    return result
            except Exception:
                pass
    return None


def pytest_sessionfinish(session, exitstatus):
    """
    测试会话结束时的钩子。
    重命名视频文件后将所有测试结果写入 JSON 文件。
    """
    global _test_results, _session_start_time

    results_path = os.environ.get('TEST_RESULTS_PATH', '')
    if not results_path:
        print('[conftest_webui_plugin] 警告: TEST_RESULTS_PATH 未设置，跳过结果写入')
        return

    # 重命名视频文件为可读格式
    _rename_videos()

    # 计算会话总时长
    session_duration = time.time() - _session_start_time if _session_start_time else 0

    # 读取环境相关变量（供报告生成器使用）
    vw = os.environ.get('VIEWPORT_WIDTH', '1920')
    vh = os.environ.get('VIEWPORT_HEIGHT', '1080')
    import platform as _platform

    workspace = os.environ.get('WORKSPACE', '')

    # Read actual screenshot size from first available PNG (IHDR chunk, no deps)
    observed_screenshot_size = None
    for tr in _test_results:
        for sp in tr.get('screenshots', []):
            sp_path = Path(sp)
            if not sp_path.is_absolute() and workspace:
                sp_path = Path(workspace) / sp.replace('\\', '/')
            if sp_path.exists() and sp_path.suffix.lower() == '.png':
                try:
                    with open(sp_path, 'rb') as f:
                        header = f.read(24)
                    if len(header) >= 24 and header[:8] == b'\x89PNG\r\n\x1a\n':
                        import struct
                        w_px = struct.unpack('>I', header[16:20])[0]
                        h_px = struct.unpack('>I', header[20:24])[0]
                        observed_screenshot_size = {'width': w_px, 'height': h_px}
                except Exception:
                    pass
            if observed_screenshot_size:
                break
        if observed_screenshot_size:
            break

    # Read actual video size from first available WebM (EBML/Matroska)
    observed_video_size = _probe_webm_dimensions(_test_results, workspace)

    results_data = {
        '_producer': 'conftest_webui_plugin',
        'schema_version': '1.0',
        'test_cases': _test_results,
        'click_downgrade_events': _click_downgrade_events if _click_downgrade_events else None,
        'session_info': {
            'total_duration_ms': round(session_duration * 1000, 2),
            'total_duration_display': f'{session_duration:.1f}s',
            'total_duration_seconds': round(session_duration, 2),
            'exit_status': exitstatus,
            'total_tests': len(_test_results),
            'passed': sum(1 for r in _test_results if r['status'] == 'PASSED'),
            'failed': sum(1 for r in _test_results if r['status'] == 'FAILED'),
            'error': sum(1 for r in _test_results if r['status'] == 'ERROR'),
            'skipped': sum(1 for r in _test_results if r['status'] == 'SKIPPED'),
            'timestamp': datetime.now().astimezone().isoformat(),
            'browser': os.environ.get('BROWSER_TYPE', 'chromium'),
            'target_url': os.environ.get('TARGET_URL', ''),
            'configured_viewport': {'width': int(vw), 'height': int(vh)},
            'viewport': {'width': int(vw), 'height': int(vh)},
            'observed_screenshot_size': observed_screenshot_size,
            'observed_video_size': observed_video_size,
            'platform': _platform.platform(),
        },
    }

    # 写入文件
    results_file = Path(results_path)
    results_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        results_file.write_text(
            json.dumps(results_data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        print(f'\n[conftest_webui_plugin] 测试结果已写入: {results_file}')
        print(f'  总用例: {results_data["session_info"]["total_tests"]}')
        print(f'  通过: {results_data["session_info"]["passed"]}')
        print(f'  失败: {results_data["session_info"]["failed"]}')
        print(f'  错误: {results_data["session_info"]["error"]}')
        print(f'  跳过: {results_data["session_info"]["skipped"]}')
    except Exception as e:
        print(f'[conftest_webui_plugin] 错误: 结果写入失败: {e}')
