#!/usr/bin/env python3
"""
WebUI 用户名密码登录脚本
使用 Playwright 同步 API 执行表单填写方式的登录操作。
支持自动识别登录表单元素，也可手动指定选择器。
登录成功后保存浏览器状态（cookie + localStorage）。
"""
import argparse
import importlib.util
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# 共享 DOM 元素提取模块（统一选择器规则）
_extractor_dir = Path(__file__).parent.parent / 'uitest-page-explorer' / 'scripts'
if str(_extractor_dir) not in [str(p) for p in sys.path]:
    sys.path.insert(0, str(_extractor_dir))
from dom_elements_extractor import extract_page_elements as _extractor, launch_browser, _read_session_browser

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# 可选导入：登录配方管理器（缺失时优雅降级）
_RECIPE_MOD = None
_recipe_path = Path(__file__).resolve().parent / 'login_recipe_manager.py'
if _recipe_path.exists():
    _spec = importlib.util.spec_from_file_location('login_recipe_manager', _recipe_path)
    _RECIPE_MOD = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_RECIPE_MOD)


# ── 常量定义 ──────────────────────────────────────────────────────────

# 用于自动识别用户名输入框的选择器（按优先级排列）
USERNAME_SELECTORS = [
    'input[type="text"][name*="user" i]',
    'input[type="text"][name*="account" i]',
    'input[type="text"][name*="login" i]',
    'input[type="email"]',
    'input[type="text"][placeholder*="用户" i]',
    'input[type="text"][placeholder*="账号" i]',
    'input[type="text"][placeholder*="user" i]',
    'input[type="text"][placeholder*="email" i]',
    'input[type="text"][id*="user" i]',
    'input[type="text"][id*="account" i]',
    'input[type="text"][id*="login" i]',
    'input[type="text"]',
    'input:not([type])[name*="user" i]',
    'input:not([type])',
]

# 用于自动识别密码输入框的选择器
PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[type="password"][name*="pass" i]',
    'input[type="password"][name*="pwd" i]',
]

# 用于自动识别提交按钮的选择器
SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("登录")',
    'button:has-text("登 录")',
    'button:has-text("Sign in")',
    'button:has-text("Login")',
    'button:has-text("Log in")',
    'a:has-text("登录")',
    'button.login-btn',
    'button.submit-btn',
    'button[class*="login" i]',
    'button[class*="submit" i]',
]

# 判断 URL path 中是否包含登录相关路径的关键词
# 注意：不含 'sso'，因为 SSO 门户首页（如 sso.company.com/home）不是登录页
LOGIN_URL_KEYWORDS = ['login', 'signin', 'sign-in', 'sign_in', 'auth/login', 'auth/signin']

# 用于在非登录表单页（如首页、过期重定向页）查找登录入口按钮/链接的选择器
# 点击这些元素后会跳转到真正含输入框的登录表单页
# 使用场景：多步 SSO（初始重定向到首页 → 点击"登录"按钮 → 才到真正的登录表单）
LOGIN_ENTRY_SELECTORS = [
    'button:has-text("登录")',
    'button:has-text("去登录")',
    'button:has-text("立即登录")',
    'button:has-text("请登录")',
    'button:has-text("Login")',
    'button:has-text("Sign in")',
    'a:has-text("登录")',
    'a:has-text("去登录")',
    'a:has-text("立即登录")',
    'a:has-text("Login")',
    'a:has-text("Sign in")',
    'a[href*="login" i]',
    'a[href*="signin" i]',
    '.login-btn',
    '.btn-login',
    '[class*="login-btn" i]',
    '[data-action="login"]',
    'header a:has-text("登录")',
    'nav a:has-text("登录")',
    '[class*="header"] a:has-text("登录")',
    '[class*="nav"] button:has-text("登录")',
    'header button:has-text("登录")',
    'nav button:has-text("Login")',
    '[class*="user-login" i]',
    '[class*="login-entry" i]',
    '[class*="login-box" i]',
    '[class*="user-auth" i] :has-text("登录")',
    '[class*="user-auth" i] :has-text("登 录")',
    'header [class*="right" i] :has-text("登录")',
    'header [class*="right" i] :has-text("登 录")',
]

_ENTRY_EXTENDED_START_IDX = 23

SCRIPT_HARD_TIMEOUT_S = int(os.environ.get('LOGIN_SCRIPT_TIMEOUT', '600'))


def find_and_click_login_entry(page):
    """
    在非登录表单页（如首页、过期重定向页）查找登录入口按钮/链接并点击。
    适用于"多步 SSO"场景：初始重定向到首页 → 点击登录入口 → 跳转到真正的登录表单页。

    Args:
        page: Playwright page 对象

    Returns:
        bool: 是否找到并点击了登录入口
    """
    for idx, selector in enumerate(LOGIN_ENTRY_SELECTORS):
        try:
            element = page.locator(selector).first
            _timeout = 500 if idx >= _ENTRY_EXTENDED_START_IDX else 150
            if element.is_visible(timeout=_timeout):
                print(f'  发现登录入口: {selector}')
                element.click()
                return True
        except Exception:
            continue
    return False


def find_login_entry_fuzzy(page):
    """
    限定范围的文本搜索兜底。仅在导航区域查找短文本的登录入口，
    防止误命中"登录日志"、"登录记录"等业务元素。
    """
    nav_scopes = ['header', 'nav', '[class*="toolbar"]', '[class*="topbar"]', '[class*="header"]']
    login_texts = ['登录', '登 录', 'Sign in', 'Login']

    page.evaluate('window.scrollTo(0,0)')
    page.wait_for_timeout(500)

    for scope_sel in nav_scopes:
        scope = page.locator(scope_sel).first
        try:
            if not scope.is_visible(timeout=300):
                continue
        except Exception:
            continue
        for text in login_texts:
            for tag in ['a', 'button', 'div', 'span']:
                try:
                    candidate = scope.locator(f'{tag}:has-text("{text}")').first
                    if candidate.is_visible(timeout=150):
                        inner = candidate.inner_text(timeout=500).strip()
                        if len(inner) <= 6:
                            print(f'  [fuzzy] 发现登录入口: {scope_sel} > {tag}:has-text("{text}") -> "{inner}"')
                            candidate.click()
                            return True
                except Exception:
                    continue
    return False


def _collect_visible_elements_summary(page, max_count=5):
    """
    采集当前页面前 N 个可见交互元素的摘要（tag + text + href），
    用于登录入口查找全部失败时输出诊断信息。
    """
    try:
        summary = page.evaluate('''(maxCount) => {
            const selectors = 'a, button, input, select, [role="button"], [onclick]';
            const elements = document.querySelectorAll(selectors);
            const result = [];
            for (const el of elements) {
                if (result.length >= maxCount) break;
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                result.push({
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || el.value || '').trim().substring(0, 30),
                    href: (el.href || '').substring(0, 80),
                    type: el.type || '',
                });
            }
            return result;
        }''', max_count)
        return summary
    except Exception:
        return []


def wait_url_stable(page, timeout_s=15, poll_interval=0.8, stable_count_needed=3):
    """
    等待页面 URL 连续稳定若干次，用于处理多级跳转链。
    URL 连续 stable_count_needed 次未变化（约 stable_count_needed * poll_interval 秒），
    即认为当前跳转链已结束。

    Args:
        page: Playwright page 对象
        timeout_s: 最长等待秒数
        poll_interval: 轮询间隔秒数
        stable_count_needed: 需要连续稳定的次数

    Returns:
        str: 稳定后的 URL
    """
    import time as _time
    deadline = _time.time() + timeout_s
    last_url = page.url
    stable_count = 0
    while _time.time() < deadline:
        _time.sleep(poll_interval)
        cur_url = page.url
        if cur_url == last_url:
            stable_count += 1
            if stable_count >= stable_count_needed:
                break
        else:
            print(f'  检测到跳转: {cur_url}')
            stable_count = 0
            last_url = cur_url
    return page.url


def auto_detect_selector(page, candidates, description):
    """
    自动检测页面上匹配的元素选择器。
    按照候选列表的优先级依次查找，返回第一个可见且可用的元素对应的选择器。

    Args:
        page: Playwright page 对象
        candidates: 候选选择器列表
        description: 元素描述（用于日志输出）

    Returns:
        匹配的选择器字符串，未找到则返回 None
    """
    for selector in candidates:
        try:
            element = page.locator(selector).first
            if element.is_visible(timeout=150):
                print(f'  自动识别{description}: {selector}')
                return selector
        except Exception:
            continue
    return None


def verify_login_success(page, original_url):
    """
    验证登录是否成功。
    采用多种策略综合判断：URL 变化、登录表单消失、退出按钮出现。

    Args:
        page: Playwright page 对象
        original_url: 登录前的 URL

    Returns:
        dict: {'success': bool, 'reason': str}
    """
    current_url = page.url

    # 策略1: 检查 URL 是否发生变化（不再包含登录关键词）
    original_has_login = any(kw in original_url.lower() for kw in LOGIN_URL_KEYWORDS)
    current_has_login = any(kw in current_url.lower() for kw in LOGIN_URL_KEYWORDS)
    if original_has_login and not current_has_login:
        return {'success': True, 'reason': 'URL 已变化，不再包含登录路径关键词'}

    if current_url != original_url:
        return {'success': True, 'reason': f'URL 已变化: {original_url} -> {current_url}'}

    # 策略2: 检查登录表单是否消失
    try:
        password_visible = page.locator('input[type="password"]').first.is_visible(timeout=2000)
        if not password_visible:
            return {'success': True, 'reason': '登录表单已消失（密码框不可见）'}
    except Exception:
        return {'success': True, 'reason': '登录表单已消失（密码框元素不存在）'}

    # 策略3: 检查是否出现退出/注销按钮
    logout_selectors = [
        ':text("退出")', ':text("注销")', ':text("Logout")',
        ':text("Sign out")', ':text("Log out")',
        '[class*="logout" i]', '[class*="user-info" i]', '[class*="avatar" i]',
    ]
    for sel in logout_selectors:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                return {'success': True, 'reason': f'检测到已登录标识: {sel}'}
        except Exception:
            continue

    # 策略4: 检查页面是否有错误提示（常见登录失败特征）
    error_selectors = [
        ':text("密码错误")', ':text("用户名或密码")', ':text("incorrect")',
        ':text("invalid")', ':text("failed")', '.error-message', '.alert-danger',
    ]
    for sel in error_selectors:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                return {'success': False, 'reason': f'检测到错误提示: {sel}'}
        except Exception:
            continue

    return {'success': False, 'reason': '无法确认登录状态，URL 未变化且登录表单仍然可见'}


def take_screenshot(page, output_dir, prefix='login'):
    """
    截取当前页面截图并保存。
    对有持续 WebSocket/轮询的 SPA 友好：
    - 先尝试 full_page=False（仅视口，速度快）加 10s 超时
    - 失败时降级为同样的 full_page=False 但宽松地只打印警告，不抛出异常

    Args:
        page: Playwright page 对象
        output_dir: 截图保存目录
        prefix: 文件名前缀

    Returns:
        截图文件路径字符串，失败时返回空字符串
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    screenshot_path = output_dir / f'{prefix}_{timestamp}.png'
    try:
        # full_page=False：只截视口，避免 SPA 滚动渲染耗时；timeout=10s
        page.screenshot(path=str(screenshot_path), full_page=False, timeout=10000)
        return str(screenshot_path)
    except Exception as e:
        print(f'  警告: 截图失败（{prefix}），已跳过: {e}')
        return ''


def _extract_page_elements(page):
    """
    在当前 page 上执行 DOM 元素提取，返回元素列表。
    已委托至共享模块 dom_elements_extractor.py，统一选择器规则。
    """
    return _extractor(page)


def verify_target_reachable(page, target_url, timeout_ms=15000):
    """
    URL 可达性验证：登录后能否到达目标页面（不被 SSO 重定向走）。
    使用前缀匹配而非严格相等，适配 SPA 路由跳转（如 /plan -> /plan/list）。
    """
    page.goto(target_url, wait_until='domcontentloaded', timeout=timeout_ms)
    try:
        page.wait_for_load_state('networkidle', timeout=15000)
    except Exception:
        pass

    target_parsed = urlparse(target_url)
    current_parsed = urlparse(page.url)

    if current_parsed.hostname != target_parsed.hostname:
        return False, f'host 不一致: 目标 {target_parsed.hostname}, 实际 {current_parsed.hostname}'

    target_path = target_parsed.path.rstrip('/')
    current_path = current_parsed.path.rstrip('/')
    if current_path == target_path or current_path.startswith(target_path + '/'):
        return True, 'URL 可达，路径匹配'

    sso_patterns = ['/login', '/sso', '/cas', '/signin', '/sign-in', '/auth']
    if any(pat in current_path.lower() for pat in sso_patterns):
        return False, f'被重定向到 SSO/登录页: {page.url}'

    return True, f'host 一致但路径不同（可能是业务内跳转）: {current_path}'


def _build_next_actions(args):
    """构建登录失败时的结构化下一步建议。"""
    actions = [
        {'action': 'check_screenshot',
         'path': 'login_nav_result_*.png / login_after_entry_*.png',
         'description': '查看截图确认当前页面是否为登录表单'},
        {'action': 'retry_with_selectors',
         'description': '手动指定选择器重试',
         'command': (f'.venv/bin/python {__file__} --url "{args.url}" '
                     f'--username "{args.username}" --password "***" '
                     f'--state-output "{args.state_output}" '
                     f'--username-selector "<选择器>" --password-selector "<选择器>" '
                     f'--submit-selector "<选择器>"')},
        {'action': 'use_cookie_login', 'description': '改用 Cookie 注入方式登录'},
        {'action': 'abort', 'description': '终止测试，向用户报告登录失败'},
    ]
    return actions


def _save_login_recipe(args, current_url, username_sel, password_sel, submit_sel,
                       entry_selector_used, entry_attempts):
    """登录成功后保存配方到 recipes_dir（如果配方管理器可用）。"""
    if not _RECIPE_MOD:
        return
    recipes_dir = args.recipes_dir
    if not recipes_dir:
        # 尝试从 state_output 路径推导默认位置
        state_parent = Path(args.state_output).resolve().parent.parent
        recipes_dir = str(state_parent / 'qa/webui' / 'shared_assets' / 'login-recipes')
    try:
        details = {
            'selectors': {
                'username': username_sel,
                'password': password_sel,
                'submit': submit_sel,
            },
            'sso_flow': {
                'needs_entry_click': entry_selector_used is not None,
                'entry_selector': entry_selector_used,
                'entry_attempts': entry_attempts,
            },
        }
        path = _RECIPE_MOD.save_recipe(
            entry_url=args.url,
            login_url=current_url,
            method='password',
            details=details,
            recipes_dir=recipes_dir,
        )
        print(f'  登录配方已保存: {path}')
    except Exception as e:
        print(f'  警告: 保存登录配方失败（不影响登录结果）: {e}')


def _explore_after_login(page, explore_output, screenshot_dir):
    """
    登录成功后直接在同一浏览器会话中提取页面元素，写入 explore_output 文件。
    省去 explore_page.py 需要重新启动浏览器、加载 state、重新导航的开销。

    Args:
        page: 已完成登录并停留在业务页的 Playwright page 对象
        explore_output: 输出 page-elements.json 的路径
        screenshot_dir: 截图保存目录
    """
    import json as _json
    print('\n[探测] 登录后直接提取页面元素（已节省一次浏览器启动）...')

    # 等待页面 DOM 稳定
    try:
        page.wait_for_load_state('domcontentloaded', timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(500)

    # 截图
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    screenshot_path_str = ''
    try:
        ss_path = Path(screenshot_dir) / f'explore_{ts}.png'
        try:
            page.screenshot(path=str(ss_path), full_page=True, timeout=10000)
        except Exception:
            # SPA 降级：full_page=False
            page.screenshot(path=str(ss_path), full_page=False, timeout=5000)
        screenshot_path_str = str(ss_path)
        print(f'  探测截图: {ss_path}')
    except Exception as e:
        print(f'  警告: 探测截图失败: {e}')

    # 提取元素
    try:
        elements = _extract_page_elements(page)
        print(f'  提取到 {len(elements)} 个交互元素')
    except Exception as e:
        print(f'  警告: 元素提取失败: {e}')
        elements = []

    output_path = Path(explore_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        'url': page.url,
        'title': page.title(),
        'screenshot': screenshot_path_str,
        'timestamp': datetime.now().isoformat(),
        'elements_count': len(elements),
        'elements': elements,
        'source': 'login_combined',
    }
    output_path.write_text(_json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  页面元素已输出: {output_path}')


def main():
    parser = argparse.ArgumentParser(description='WebUI 用户名密码登录')
    parser.add_argument('--url', required=True, help='登录页面 URL')
    parser.add_argument('--username', default=None,
                        help='用户名（也可通过环境变量 UITEST_USERNAME 传入）')
    parser.add_argument('--password', default=None,
                        help='密码（也可通过环境变量 UITEST_PASSWORD 传入）')
    parser.add_argument('--username-selector', default=None,
                        help='用户名输入框选择器（可选，自动识别）')
    parser.add_argument('--password-selector', default=None,
                        help='密码输入框选择器（可选，自动识别）')
    parser.add_argument('--submit-selector', default=None,
                        help='提交按钮选择器（可选，自动识别）')
    parser.add_argument('--state-output', required=True,
                        help='浏览器状态保存路径（JSON 文件）')
    parser.add_argument('--screenshot-dir', default=None,
                        help='截图保存目录（可选）')
    parser.add_argument('--explore-output', default=None,
                        help='（可选）登录成功后直接提取页面元素并输出到此路径（page-elements.json），'
                             '省去 explore_page.py 单独启动浏览器的开销')
    parser.add_argument('--entry-selector', default=None,
                        help='SSO 入口按钮选择器（配方回放时由 Agent 传入，跳过通用入口探索）')
    parser.add_argument('--recipes-dir', default=None,
                        help='登录配方存储目录（默认 qa/webui/shared_assets/login-recipes）。'
                             '登录成功后自动保存配方，下次可直接传入已知选择器快速登录')
    parser.add_argument('--headless', action='store_true', default=True,
                        help='无头模式运行（默认开启，强制生效）')
    # --no-headless 已废弃：Agent 禁止传入此参数，脚本层面也不再接受
    # 如需有头调试，请手动设置环境变量 FORCE_HEADED=1
    parser.add_argument('--timeout', type=int, default=30000,
                        help='操作超时时间（毫秒），默认 30000')
    args = parser.parse_args()

    # 凭据优先级：命令行参数 > 环境变量
    if not args.username:
        args.username = os.environ.get('UITEST_USERNAME')
    if not args.password:
        args.password = os.environ.get('UITEST_PASSWORD')
    if not args.username or not args.password:
        parser.error('必须通过 --username/--password 参数或 UITEST_USERNAME/UITEST_PASSWORD 环境变量提供凭据')

    # 确保状态输出目录存在
    state_output = Path(args.state_output).resolve()
    state_output.parent.mkdir(parents=True, exist_ok=True)

    # 截图目录
    screenshot_dir = Path(args.screenshot_dir) if args.screenshot_dir else state_output.parent
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    result = {
        'method': 'password',
        'url': args.url,
        'status': 'error',
        'message': '',
        'screenshot': '',
        'state_path': '',
        'current_url': '',
        'timestamp': '',
    }

    # 进程级硬超时：防止脚本被反复调用时无限挂起（跨平台兼容）
    _browser_ref = [None]

    def _hard_timeout():
        timeout_result = {
            'method': 'password', 'url': args.url, 'status': 'error',
            'message': f'登录脚本执行超时（{SCRIPT_HARD_TIMEOUT_S}秒）',
            'screenshot': '', 'state_path': '', 'current_url': '',
            'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'next_actions': [{'action': 'abort', 'description': '脚本超时，请检查网络或目标系统可用性'}],
        }
        result_path = state_output.parent / 'login-result.json'
        try:
            result_path.write_text(json.dumps(timeout_result, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass
        print(f'\n[TIMEOUT] 登录脚本执行超过 {SCRIPT_HARD_TIMEOUT_S} 秒硬超时，强制退出')
        try:
            if _browser_ref[0]:
                _browser_ref[0].close()
        except Exception:
            pass
        os._exit(2)

    _timer = threading.Timer(SCRIPT_HARD_TIMEOUT_S, _hard_timeout)
    _timer.daemon = True
    _timer.start()

    print('=' * 60)
    print('WebUI 用户名密码登录')
    print('=' * 60)
    print(f'  目标 URL: {args.url}')
    print(f'  用户名: {args.username}')
    print(f'  无头模式: True (强制)')
    print(f'  硬超时: {SCRIPT_HARD_TIMEOUT_S}s')

    with sync_playwright() as pw:
        browser = None
        try:
            # ── 启动浏览器 ──────────────────────────────────
            print('\n[1/6] 启动浏览器...')
            _browser_type = _read_session_browser(getattr(args, 'workspace', None) or os.environ.get('WORKSPACE', ''))
            browser = launch_browser(pw, browser_type=_browser_type)
            _browser_ref[0] = browser
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
            )
            context.set_default_timeout(args.timeout)
            page = context.new_page()

            # ── 导航到登录页 ────────────────────────────────
            print(f'[2/6] 导航到登录页: {args.url}')
            page.goto(args.url, wait_until='domcontentloaded')
            # SSO 场景下初始页会跳转到 SSO 登录域，给足等待时间但设上限
            try:
                page.wait_for_load_state('networkidle', timeout=15000)
            except PlaywrightTimeout:
                print('  注意: 初始页 networkidle 等待超时，继续尝试（SSO 重定向中可能仍有请求）')
            original_url = page.url
            print(f'  页面加载完成，当前 URL: {original_url}')
            # 导航后立即截图，供后续诊断或手动指定选择器时参考
            nav_screenshot = take_screenshot(page, screenshot_dir, 'login_nav_result')
            print(f'  导航截图: {nav_screenshot}')

            # ── 多步 SSO 入口发现 ──────────────────────────
            # 有些 SSO 流程不会直接跳到登录表单，而是先到首页/过期页，
            # 需要点击"登录"入口按钮后才进入真正的登录表单页。
            # 最多尝试 2 次入口点击（防止极端情况下的无限循环）。
            _used_entry_selector = None  # 记录实际使用的入口选择器（供配方保存）
            _entry_attempts_used = 0
            print('[3/6] 识别登录表单元素（含多步 SSO 入口发现）...')
            for _entry_attempt in range(3):  # 最多尝试 3 轮（0=直接找, 1=点入口后找, 2=再次点入口后找）
                _has_password = False
                try:
                    _has_password = page.locator('input[type="password"]').first.is_visible(timeout=2000)
                except Exception:
                    pass

                if _has_password:
                    print(f'  已检测到密码输入框（第 {_entry_attempt + 1} 轮）')
                    break

                if _entry_attempt == 2:
                    # 已尝试 2 次入口点击仍未出现表单，继续往下走（依赖后续选择器检测报错）
                    print('  警告: 多次点击入口后仍未检测到密码框，继续尝试识别表单元素...')
                    break

                print(f'  未检测到密码输入框，尝试查找登录入口按钮（第 {_entry_attempt + 1} 次）...')

                # 配方回放：优先使用 --entry-selector 指定的已知入口选择器
                entry_clicked = False
                if args.entry_selector and _entry_attempt == 0:
                    try:
                        el = page.locator(args.entry_selector).first
                        if el.is_visible(timeout=2000):
                            el.click()
                            entry_clicked = True
                            _used_entry_selector = args.entry_selector
                            print(f'  使用配方入口选择器: {args.entry_selector}')
                    except Exception:
                        print(f'  配方入口选择器失效，回退到通用探索')

                if not entry_clicked:
                    entry_clicked = find_and_click_login_entry(page)

                if not entry_clicked:
                    entry_clicked = find_login_entry_fuzzy(page)

                if not entry_clicked:
                    print('  未找到登录入口按钮，可能已在登录表单页或不需要点击入口')
                    break

                _entry_attempts_used = _entry_attempt + 1
                # 记录通用探索命中的选择器（配方未指定时）
                if not _used_entry_selector:
                    for sel in LOGIN_ENTRY_SELECTORS:
                        try:
                            if page.locator(sel).first.is_visible(timeout=150):
                                _used_entry_selector = sel
                                break
                        except Exception:
                            continue

                # 点击入口后等待跳转链稳定
                print('  已点击登录入口，等待跳转链完成...')
                wait_url_stable(page, timeout_s=15)
                try:
                    page.wait_for_load_state('networkidle', timeout=10000)
                except PlaywrightTimeout:
                    pass
                entry_screenshot = take_screenshot(page, screenshot_dir, f'login_after_entry_{_entry_attempt + 1}')
                print(f'  点击入口后截图: {entry_screenshot}，当前 URL: {page.url}')

            # 用户名输入框
            username_sel = args.username_selector
            if not username_sel:
                username_sel = auto_detect_selector(page, USERNAME_SELECTORS, '用户名输入框')
            if not username_sel:
                elem_summary = _collect_visible_elements_summary(page)
                summary_lines = []
                for i, el in enumerate(elem_summary):
                    summary_lines.append(f'    [{i+1}] <{el["tag"]}> text="{el["text"]}" href="{el["href"]}"')
                summary_text = '\n'.join(summary_lines) if summary_lines else '    （无可见交互元素）'
                raise RuntimeError(
                    '无法识别用户名输入框。\n'
                    '排查建议：\n'
                    '  1. 查看截图 login_nav_result_*.png 和 login_after_entry_*.png，确认当前页面是否为登录表单\n'
                    '  2. 如果登录表单已存在，使用 --username-selector 手动传入选择器\n'
                    '  3. 如果页面需要更多操作才能到达登录表单，请检查 SSO 流程\n'
                    f'  当前页面 URL: {page.url}\n'
                    f'  当前页面可见交互元素（前 {len(elem_summary)} 个）:\n{summary_text}'
                )

            # 密码输入框
            password_sel = args.password_selector
            if not password_sel:
                password_sel = auto_detect_selector(page, PASSWORD_SELECTORS, '密码输入框')
            if not password_sel:
                raise RuntimeError(
                    '无法识别密码输入框。\n'
                    '排查建议：查看截图确认页面结构，使用 --password-selector 手动传入选择器'
                )

            # 提交按钮
            submit_sel = args.submit_selector
            if not submit_sel:
                submit_sel = auto_detect_selector(page, SUBMIT_SELECTORS, '提交按钮')
            if not submit_sel:
                raise RuntimeError(
                    '无法识别提交按钮。\n'
                    '排查建议：查看截图确认按钮文字，使用 --submit-selector 手动传入选择器'
                )

            print(f'  用户名选择器: {username_sel}')
            print(f'  密码选择器: {password_sel}')
            print(f'  提交按钮选择器: {submit_sel}')

            # ── 填写表单并提交 ──────────────────────────────
            print('[4/6] 填写登录表单...')
            # 清空已有内容后填写
            page.locator(username_sel).first.click()
            page.locator(username_sel).first.fill(args.username)
            print(f'  已填写用户名: {args.username}')

            page.locator(password_sel).first.click()
            page.locator(password_sel).first.fill(args.password)
            print('  已填写密码: ***')

            # 截图：填写表单后、提交前
            pre_submit_screenshot = take_screenshot(page, screenshot_dir, 'login_pre_submit')
            print(f'  提交前截图: {pre_submit_screenshot}')

            print('[5/6] 提交登录表单...')
            # SSO 登录通常经过多段跳转：业务系统 → SSO 鉴权 → 回跳业务系统
            # 不能只等第一次 navigation，需要等待最终落地页稳定
            page.locator(submit_sel).first.click()
            print('  登录按钮已点击，等待 SSO 跳转链完成...')
            wait_url_stable(page, timeout_s=args.timeout / 1000)
            print(f'  跳转链结束，当前 URL: {page.url}')

            # 等待页面最终稳定（SSO 回跳后业务页可能还有异步请求）
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except PlaywrightTimeout:
                print('  注意: 等待网络空闲超时，继续验证')

            # ── 验证登录结果 ──────────────────────────────
            print('[6/6] 验证登录结果...')
            verification = verify_login_success(page, original_url)
            print(f'  验证结果: {"成功" if verification["success"] else "失败"}')
            print(f'  判断依据: {verification["reason"]}')
            print(f'  当前 URL: {page.url}')

            # 截图：登录后
            post_login_screenshot = take_screenshot(page, screenshot_dir, 'login_result')
            print(f'  登录结果截图: {post_login_screenshot}')

            if verification['success']:
                # URL 可达性二次验证：确认登录后能真正到达目标业务页
                reachable, reach_reason = verify_target_reachable(page, args.url)
                print(f'  目标页可达性: {"通过" if reachable else "未通过"} — {reach_reason}')
                if not reachable:
                    verification = {'success': False, 'reason': f'登录表单验证通过但目标页不可达: {reach_reason}'}

            if verification['success']:
                # 保存浏览器状态
                context.storage_state(path=str(state_output))
                print(f'\n  浏览器状态已保存: {state_output}')

                result.update({
                    'status': 'success',
                    'message': verification['reason'],
                    'screenshot': post_login_screenshot,
                    'state_path': str(state_output),
                    'current_url': page.url,
                })

                # ── 保存登录配方（L2 缓存） ──────────────────
                _save_login_recipe(
                    args, page.url,
                    username_sel, password_sel, submit_sel,
                    _used_entry_selector, _entry_attempts_used,
                )

                # 可选：登录成功后立即提取页面元素，省去 explore_page.py 独立启动浏览器的开销
                if args.explore_output:
                    _explore_after_login(page, args.explore_output, screenshot_dir)
                    result['explore_output'] = args.explore_output
            else:
                result.update({
                    'status': 'failed',
                    'message': verification['reason'],
                    'screenshot': post_login_screenshot,
                    'current_url': page.url,
                })

        except Exception as e:
            error_msg = f'登录过程发生错误: {type(e).__name__}: {str(e)}'
            print(f'\n  错误: {error_msg}')
            result.update({
                'status': 'error',
                'message': error_msg,
                'next_actions': _build_next_actions(args),
            })

        finally:
            if browser:
                browser.close()

    # 写入时间戳
    result['timestamp'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    # 输出 JSON 结果
    print('\n' + '=' * 60)
    print('登录结果:')
    print('=' * 60)
    result_json = json.dumps(result, ensure_ascii=False, indent=2)
    print(result_json)

    # 如果状态保存路径的父目录存在，也保存一份结果 JSON
    result_path = state_output.parent / 'login-result.json'
    result_path.write_text(result_json, encoding='utf-8')

    _timer.cancel()
    sys.exit(0 if result['status'] == 'success' else 1)


if __name__ == '__main__':
    main()
