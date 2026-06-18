#!/usr/bin/env python3
"""
WebUI Cookie 注入登录脚本
使用 Playwright 同步 API，通过注入 Cookie 建立已登录的浏览器会话。
支持从 JSON 数组、浏览器原始格式（name=value; name=value）或文件读取 Cookie 数据。
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# 共享 DOM 元素提取模块（统一选择器规则）
_extractor_dir = Path(__file__).parent.parent / 'uitest-page-explorer' / 'scripts'
if str(_extractor_dir) not in [str(p) for p in sys.path]:
    sys.path.insert(0, str(_extractor_dir))
from dom_elements_extractor import extract_page_elements as _extractor, launch_browser, _read_session_browser

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

_RECIPE_MOD = None
_recipe_path = Path(__file__).resolve().parent / 'login_recipe_manager.py'
if _recipe_path.exists():
    _spec = importlib.util.spec_from_file_location('login_recipe_manager', _recipe_path)
    _RECIPE_MOD = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_RECIPE_MOD)


def _derive_cookie_domain(target_url):
    """从 URL 推导 Cookie domain，正确处理 IP 地址。"""
    if not target_url:
        return None
    parsed = urlparse(target_url)
    host = parsed.hostname or ''
    if not host:
        return None
    # IP 地址（IPv4 或 IPv6）直接使用完整 host
    if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', host) or ':' in host:
        return host
    parts = host.split('.')
    if len(parts) >= 2:
        return '.' + '.'.join(parts[-2:])
    return host


def _parse_browser_cookie_string(raw_str, target_url=None):
    """
    解析浏览器 DevTools 复制出来的原始 Cookie 字符串。
    格式：name1=value1; name2=value2; name3=value3

    Args:
        raw_str: 浏览器格式的 Cookie 字符串
        target_url: 目标 URL，用于推导 domain（可选）

    Returns:
        list: Cookie 字典列表
    """
    domain = _derive_cookie_domain(target_url)

    cookies = []
    for pair in raw_str.split(';'):
        pair = pair.strip()
        if not pair:
            continue
        eq_idx = pair.find('=')
        if eq_idx <= 0:
            continue
        name = pair[:eq_idx].strip()
        value = pair[eq_idx + 1:].strip()
        entry = {'name': name, 'value': value, 'path': '/'}
        if domain:
            entry['domain'] = domain
        cookies.append(entry)
    return cookies


def _looks_like_browser_cookie_string(s):
    """判断字符串是否是浏览器原始 Cookie 格式（name=value 或 name=value; name=value）。"""
    if not s or s.startswith(('[', '{')):
        return False
    # 至少包含一个 name=value 对（单条 cookie 无分号也识别）
    return bool(re.match(r'^[A-Za-z0-9_.-]+=.+', s))


def load_cookies(cookies_input, target_url=None):
    """
    加载 Cookie 数据。
    支持三种输入格式（自动识别）：
    1. 浏览器原始格式（name=value; name=value）— 用户从 DevTools 直接复制
    2. JSON 数组字符串（[{"name":"...","value":"...","domain":"..."}]）
    3. JSON 文件路径

    Args:
        cookies_input: Cookie 字符串或文件路径
        target_url: 目标 URL，浏览器格式时用于推导 domain

    Returns:
        list: Cookie 字典列表
    """
    stripped = cookies_input.strip()

    # ── 格式 1：浏览器原始格式（name=value; name=value）────────
    if _looks_like_browser_cookie_string(stripped):
        print('  从浏览器原始格式解析 Cookie（name=value; name=value）')
        cookies = _parse_browser_cookie_string(stripped, target_url)
        if not cookies:
            raise ValueError('浏览器格式 Cookie 解析结果为空')
        print(f'  自动解析为 {len(cookies)} 条 Cookie（domain 从 URL 推导）')
        return _normalize_cookies(cookies, target_url)

    # ── 格式 2：JSON 字符串 ────────────────────────────────────
    looks_like_json = stripped.startswith(('[', '{'))

    if looks_like_json:
        print('  从 JSON 字符串解析 Cookie')
        cookies = json.loads(stripped)
        return _normalize_cookies(cookies, target_url)

    # ── 格式 3：文件路径 / 其他 ───────────────────────────────
    try:
        cookie_path = Path(cookies_input)
        file_exists = False
        try:
            file_exists = cookie_path.exists() and cookie_path.is_file()
        except OSError:
            pass
        if file_exists:
            print(f'  从文件加载 Cookie: {cookie_path}')
            raw = cookie_path.read_text(encoding='utf-8')
            raw_stripped = raw.strip()
            if _looks_like_browser_cookie_string(raw_stripped):
                cookies = _parse_browser_cookie_string(raw_stripped, target_url)
                return _normalize_cookies(cookies, target_url)
            cookies = json.loads(raw)
            return _normalize_cookies(cookies, target_url)
        else:
            # 最后尝试当作 JSON 字符串解析
            try:
                print('  从 JSON 字符串解析 Cookie')
                cookies = json.loads(cookies_input)
                return _normalize_cookies(cookies, target_url)
            except json.JSONDecodeError:
                # 也可能是浏览器格式的单条 cookie（无分号，前面被跳过了）
                # 或者是不存在的文件路径
                raise ValueError(
                    f'无法解析 Cookie 输入：既不是有效的 JSON，也不是有效的文件路径。'
                    f' 输入前 80 字符: {cookies_input[:80]}...'
                )
    except OSError:
        print('  从 JSON 字符串解析 Cookie（路径检测跳过：字符串过长）')
        cookies = json.loads(cookies_input)
        return _normalize_cookies(cookies, target_url)


def _normalize_cookies(cookies, target_url=None):
    """标准化 Cookie 列表，确保每项都有 name/value/domain。"""
    if not isinstance(cookies, list):
        raise ValueError('Cookie 必须是数组格式')

    fallback_domain = _derive_cookie_domain(target_url)

    normalized = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise ValueError(f'Cookie 项必须是字典格式，实际为: {type(cookie).__name__}')
        if 'name' not in cookie or 'value' not in cookie:
            raise ValueError(f'Cookie 项缺少必要字段 name 或 value: {cookie}')

        entry = {
            'name': cookie['name'],
            'value': str(cookie['value']),
        }

        if 'domain' in cookie:
            entry['domain'] = cookie['domain']
        if 'path' in cookie:
            entry['path'] = cookie['path']
        else:
            entry['path'] = '/'

        if 'url' in cookie:
            entry['url'] = cookie['url']
        if 'secure' in cookie:
            entry['secure'] = bool(cookie['secure'])
        if 'httpOnly' in cookie:
            entry['httpOnly'] = bool(cookie['httpOnly'])
        if 'sameSite' in cookie:
            entry['sameSite'] = cookie['sameSite']
        if 'expires' in cookie:
            entry['expires'] = cookie['expires']

        # 没有 domain 也没有 url → 从 target_url 推导
        if 'domain' not in entry and 'url' not in entry:
            if fallback_domain:
                entry['domain'] = fallback_domain
                print(f'    Cookie "{cookie["name"]}" 缺少 domain，已从 URL 推导: {fallback_domain}')
            else:
                raise ValueError(
                    f'Cookie "{cookie["name"]}" 缺少 domain 或 url 字段，'
                    '且未提供 --url 参数无法推导'
                )

        normalized.append(entry)

    return normalized


def _extract_page_elements(page):
    """从当前页面提取交互元素，返回元素列表。已委托至共享模块 dom_elements_extractor.py。"""
    return _extractor(page)


def _explore_after_login(page, explore_output, screenshot_dir):
    """
    登录成功后直接在同一浏览器会话中提取页面元素，写入 explore_output 文件。
    省去 explore_page.py 需要重新启动浏览器、加载 state、重新导航的开销。
    """
    print('\n[探测] Cookie 登录后直接提取页面元素（已节省一次浏览器启动）...')

    try:
        page.wait_for_load_state('domcontentloaded', timeout=10000)
    except Exception:
        pass
    try:
        page.wait_for_load_state('networkidle', timeout=3000)
    except Exception:
        pass

    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    screenshot_path_str = ''
    try:
        ss_path = Path(screenshot_dir) / f'explore_{ts}.png'
        try:
            page.screenshot(path=str(ss_path), full_page=True, timeout=10000)
        except Exception:
            page.screenshot(path=str(ss_path), full_page=False, timeout=5000)
        screenshot_path_str = str(ss_path)
        print(f'  探测截图: {ss_path}')
    except Exception as e:
        print(f'  警告: 探测截图失败: {e}')

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
        'source': 'cookie_login_combined',
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  页面元素已输出: {output_path}')


def verify_session(page, url):
    """
    验证 Cookie 注入后会话是否有效。
    通过多种策略判断当前页面是否处于已登录状态。

    Args:
        page: Playwright page 对象
        url: 目标 URL

    Returns:
        dict: {'success': bool, 'reason': str, 'on_target': bool}
    """
    current_url = page.url
    parsed = urlparse(current_url)
    url_path = (parsed.path or '').lower()
    url_query = (parsed.query or '').lower()

    login_path_keywords = ['login', 'signin', 'sign-in', 'sign_in', 'auth/login', 'auth/signin']
    is_on_login_page = any(kw in url_path or kw in url_query for kw in login_path_keywords)

    target_parsed = urlparse(url)
    on_target = (parsed.hostname == target_parsed.hostname
                 and parsed.path.rstrip('/') == target_parsed.path.rstrip('/'))

    if is_on_login_page:
        return {'success': False, 'reason': f'页面被重定向到登录页: {current_url}', 'on_target': False}

    try:
        has_password_input = page.locator('input[type="password"]').first.is_visible(timeout=2000)
        if has_password_input:
            return {'success': False, 'reason': '页面上存在密码输入框，可能未成功登录', 'on_target': False}
    except Exception:
        pass

    logged_in_selectors = [
        ':text("退出")', ':text("注销")', ':text("Logout")',
        ':text("Sign out")', ':text("Log out")',
        '[class*="user-info" i]', '[class*="avatar" i]',
        '[class*="profile" i]', '[class*="username" i]',
    ]
    for sel in logged_in_selectors:
        try:
            if page.locator(sel).first.is_visible(timeout=500):
                return {'success': True, 'reason': f'检测到已登录标识: {sel}', 'on_target': on_target}
        except Exception:
            continue

    if not is_on_login_page:
        return {'success': True, 'reason': '页面未被重定向到登录页，且无登录表单', 'on_target': on_target}

    return {'success': False, 'reason': '无法确认会话状态', 'on_target': False}


def main():
    parser = argparse.ArgumentParser(description='WebUI Cookie 注入登录')
    parser.add_argument('--url', required=True, help='目标页面 URL')
    parser.add_argument('--cookies', default=None,
                        help='Cookie 数据（JSON 字符串或 JSON 文件路径，也可通过环境变量 UITEST_COOKIES 传入）')
    parser.add_argument('--state-output', required=True,
                        help='浏览器状态保存路径（JSON 文件）')
    parser.add_argument('--screenshot-dir', default=None,
                        help='截图保存目录（可选）')
    parser.add_argument('--explore-output', default=None,
                        help='（可选）登录成功后直接提取页面元素并输出到此路径（page-elements.json），'
                             '省去 explore_page.py 单独启动浏览器的开销')
    parser.add_argument('--recipes-dir', default=None,
                        help='登录配方存储目录。登录成功后自动保存配方')
    parser.add_argument('--headless', action='store_true', default=True,
                        help='无头模式运行（默认开启，强制生效）')
    # --no-headless 已废弃：Agent 禁止传入此参数，脚本层面也不再接受
    # 如需有头调试，请手动设置环境变量 FORCE_HEADED=1
    parser.add_argument('--timeout', type=int, default=30000,
                        help='操作超时时间（毫秒），默认 30000')
    args = parser.parse_args()

    # 凭据优先级：命令行参数 > 环境变量
    if not args.cookies:
        args.cookies = os.environ.get('UITEST_COOKIES')
    if not args.cookies:
        parser.error('必须通过 --cookies 参数或 UITEST_COOKIES 环境变量提供 Cookie')

    state_output = Path(args.state_output).resolve()
    state_output.parent.mkdir(parents=True, exist_ok=True)

    screenshot_dir = Path(args.screenshot_dir) if args.screenshot_dir else state_output.parent
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    result = {
        'method': 'cookie',
        'url': args.url,
        'status': 'error',
        'message': '',
        'screenshot': '',
        'state_path': '',
        'current_url': '',
        'cookies_count': 0,
        'timestamp': '',
    }

    print('=' * 60)
    print('WebUI Cookie 注入登录')
    print('=' * 60)
    print(f'  目标 URL: {args.url}')

    with sync_playwright() as pw:
        browser = None
        try:
            # ── 解析 Cookie ─────────────────────────────────
            print('\n[1/5] 解析 Cookie 数据...')
            cookies = load_cookies(args.cookies, target_url=args.url)
            print(f'  成功解析 {len(cookies)} 条 Cookie')
            for c in cookies:
                domain = c.get('domain', c.get('url', '未知'))
                print(f'    - {c["name"]}: {c["value"][:20]}... (域: {domain})')
            result['cookies_count'] = len(cookies)

            # ── 启动浏览器 ──────────────────────────────────
            print('\n[2/5] 启动浏览器...')
            _browser_type = _read_session_browser(os.environ.get('WORKSPACE', ''))
            browser = launch_browser(pw, browser_type=_browser_type)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
            )
            context.set_default_timeout(args.timeout)
            page = context.new_page()

            # ── 先导航到目标页面（确保域名匹配） ────────────
            print(f'[3/5] 导航到目标页面: {args.url}')
            page.goto(args.url, wait_until='domcontentloaded')
            # 企业 SPA 常有持续轮询/WebSocket，networkidle 可能永不触发，只给 5s
            try:
                page.wait_for_load_state('networkidle', timeout=5000)
            except PlaywrightTimeout:
                print('  注意: 等待网络空闲超时（SPA 轮询中），继续执行')

            # ── 注入 Cookie ─────────────────────────────────
            print('[4/5] 注入 Cookie...')
            context.add_cookies(cookies)
            print(f'  已注入 {len(cookies)} 条 Cookie')

            # 刷新页面使 Cookie 生效
            print('  刷新页面...')
            page.reload(wait_until='domcontentloaded')
            try:
                page.wait_for_load_state('networkidle', timeout=5000)
            except PlaywrightTimeout:
                print('  注意: 刷新后等待网络空闲超时（SPA 轮询中），继续验证')

            # ── 验证会话 ────────────────────────────────────
            print('[5/5] 验证登录状态...')
            verification = verify_session(page, args.url)
            print(f'  验证结果: {"成功" if verification["success"] else "失败"}')
            print(f'  判断依据: {verification["reason"]}')
            print(f'  当前 URL: {page.url}')

            # ── SSO 门户重定向修正 ─────────────────────────
            # Cookie 注入后 SSO 可能将浏览器重定向到门户首页而非目标页。
            # 如果登录成功但不在目标页，再导航一次到目标 URL。
            if verification['success'] and not verification.get('on_target', True):
                print(f'  登录成功但未在目标页（SSO 门户重定向），重新导航到: {args.url}')
                page.goto(args.url, wait_until='domcontentloaded')
                try:
                    page.wait_for_load_state('networkidle', timeout=5000)
                except PlaywrightTimeout:
                    pass
                re_verify = verify_session(page, args.url)
                if re_verify['success']:
                    verification = re_verify
                    print(f'  重定向后验证: 成功 | 当前 URL: {page.url}')
                else:
                    print(f'  重定向后验证: 失败 | {re_verify["reason"]}')
                    verification = re_verify

            # ── SSO 门户 URL 重试 ──────────────────────────
            # 某些 SSO 需要先在门户页（根路径或 /home）激活会话，
            # 直接打开子应用 URL 注入 Cookie 会失败。
            if not verification['success']:
                parsed_target = urlparse(args.url)
                portal_paths = ['/', '/home', '/portal']
                portal_base = f'{parsed_target.scheme}://{parsed_target.hostname}'
                if parsed_target.port and parsed_target.port not in (80, 443):
                    portal_base += f':{parsed_target.port}'

                for portal_path in portal_paths:
                    portal_url = portal_base + portal_path
                    if portal_url.rstrip('/') == args.url.rstrip('/'):
                        continue
                    print(f'  [SSO 重试] 尝试从门户页激活会话: {portal_url}')
                    try:
                        page.goto(portal_url, wait_until='domcontentloaded', timeout=15000)
                        try:
                            page.wait_for_load_state('networkidle', timeout=5000)
                        except PlaywrightTimeout:
                            pass
                        page.goto(args.url, wait_until='domcontentloaded', timeout=15000)
                        try:
                            page.wait_for_load_state('networkidle', timeout=5000)
                        except PlaywrightTimeout:
                            pass
                        retry_verify = verify_session(page, args.url)
                        if retry_verify['success']:
                            verification = retry_verify
                            print(f'  [SSO 重试] 成功! 门户页: {portal_url} | 当前 URL: {page.url}')
                            break
                    except Exception as e:
                        print(f'  [SSO 重试] {portal_url} 失败: {e}')
                        continue

            # 截图（full_page=False 避免 SPA 轮询导致渲染超时，timeout=10s）
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            screenshot_path = screenshot_dir / f'cookie_login_{timestamp}.png'
            try:
                page.screenshot(path=str(screenshot_path), full_page=False, timeout=10000)
                print(f'  截图已保存: {screenshot_path}')
            except Exception as e:
                print(f'  警告: 截图失败，已跳过: {e}')

            if verification['success']:
                # 保存浏览器状态
                context.storage_state(path=str(state_output))
                print(f'\n  浏览器状态已保存: {state_output}')

                result.update({
                    'status': 'success',
                    'message': verification['reason'],
                    'screenshot': str(screenshot_path),
                    'state_path': str(state_output),
                    'current_url': page.url,
                })

                # 保存登录配方
                if _RECIPE_MOD:
                    _recipes_dir = args.recipes_dir
                    if not _recipes_dir:
                        _recipes_dir = str(Path(args.state_output).resolve().parent.parent / 'login-recipes')
                    try:
                        _rp = _RECIPE_MOD.save_recipe(
                            entry_url=args.url, login_url=page.url,
                            method='cookie',
                            details={'cookie_domain': _derive_cookie_domain(args.url)},
                            recipes_dir=_recipes_dir,
                        )
                        print(f'  登录配方已保存: {_rp}')
                    except Exception as _e:
                        print(f'  警告: 保存登录配方失败: {_e}')

                # 合并页面探测（与 login_password.py 的 --explore-output 行为一致）
                if args.explore_output:
                    _explore_after_login(page, args.explore_output, screenshot_dir)
            else:
                result.update({
                    'status': 'failed',
                    'message': verification['reason'],
                    'screenshot': str(screenshot_path),
                    'current_url': page.url,
                })

        except json.JSONDecodeError as e:
            error_msg = f'Cookie JSON 解析失败: {str(e)}'
            print(f'\n  错误: {error_msg}')
            result['message'] = error_msg

        except ValueError as e:
            error_msg = f'Cookie 格式校验失败: {str(e)}'
            print(f'\n  错误: {error_msg}')
            result['message'] = error_msg

        except Exception as e:
            error_msg = f'Cookie 注入过程发生错误: {type(e).__name__}: {str(e)}'
            print(f'\n  错误: {error_msg}')
            result['message'] = error_msg

        finally:
            if browser:
                browser.close()

    result['timestamp'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    print('\n' + '=' * 60)
    print('登录结果:')
    print('=' * 60)
    result_json = json.dumps(result, ensure_ascii=False, indent=2)
    print(result_json)

    # 保存结果文件
    result_path = state_output.parent / 'login-result.json'
    result_path.write_text(result_json, encoding='utf-8')

    sys.exit(0 if result['status'] == 'success' else 1)


if __name__ == '__main__':
    main()
