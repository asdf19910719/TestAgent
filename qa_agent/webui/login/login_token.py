#!/usr/bin/env python3
"""
WebUI Token 注入登录脚本
使用 Playwright 同步 API，通过将 Token 注入到 localStorage 或 sessionStorage
建立已登录的浏览器会话。适用于前后端分离的 SPA 应用（JWT / Bearer Token）。
"""
import argparse
import importlib.util
import json
import os
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


# ── 支持的存储类型 ────────────────────────────────────────────────────
STORAGE_TYPES = ['localStorage', 'sessionStorage']


def inject_token(page, token, storage_type, storage_key):
    """
    通过 page.evaluate() 将 Token 注入到浏览器存储中。

    Args:
        page: Playwright page 对象
        token: Token 值
        storage_type: 存储类型（localStorage / sessionStorage）
        storage_key: 存储键名

    Raises:
        RuntimeError: 注入失败
    """
    # 使用 json.dumps 对值进行安全编码，防止特殊字符（引号、反斜杠等）导致 JS 注入
    safe_key = json.dumps(storage_key)
    safe_token = json.dumps(token)
    safe_type = storage_type  # 来自 choices 白名单，无需转义

    js_code = f"""
    () => {{
        try {{
            window.{safe_type}.setItem({safe_key}, {safe_token});
            const stored = window.{safe_type}.getItem({safe_key});
            return {{
                success: stored !== null,
                stored_length: stored ? stored.length : 0,
                storage_type: {json.dumps(safe_type)},
                storage_key: {safe_key}
            }};
        }} catch (e) {{
            return {{
                success: false,
                error: e.message
            }};
        }}
    }}
    """
    result = page.evaluate(js_code)

    if not result.get('success'):
        error = result.get('error', '未知错误')
        raise RuntimeError(f'Token 注入失败: {error}')

    return result


def read_stored_token(page, storage_type, storage_key):
    """
    读取浏览器存储中的 Token 值（用于验证）。

    Args:
        page: Playwright page 对象
        storage_type: 存储类型
        storage_key: 存储键名

    Returns:
        str or None: 存储中的 Token 值
    """
    js_code = f"() => window.{storage_type}.getItem({json.dumps(storage_key)})"
    return page.evaluate(js_code)


def _extract_page_elements(page):
    """从当前页面提取交互元素，返回元素列表。已委托至共享模块 dom_elements_extractor.py。"""
    return _extractor(page)


def _explore_after_login(page, explore_output, screenshot_dir):
    """
    登录成功后直接在同一浏览器会话中提取页面元素，写入 explore_output 文件。
    省去 explore_page.py 需要重新启动浏览器、加载 state、重新导航的开销。
    """
    print('\n[探测] Token 登录后直接提取页面元素（已节省一次浏览器启动）...')

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
        'source': 'token_login_combined',
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  页面元素已输出: {output_path}')


def verify_session(page, url):
    """
    验证 Token 注入后会话是否有效。
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
        return {'success': True, 'reason': '页面未被重定向到登录页，Token 可能已生效', 'on_target': on_target}

    return {'success': False, 'reason': '无法确认会话状态', 'on_target': False}


def main():
    parser = argparse.ArgumentParser(description='WebUI Token 注入登录')
    parser.add_argument('--url', required=True, help='目标页面 URL')
    parser.add_argument('--token', default=None,
                        help='Token 值（也可通过环境变量 UITEST_TOKEN 传入）')
    parser.add_argument('--storage-type', default='localStorage',
                        choices=STORAGE_TYPES,
                        help='存储类型: localStorage（默认）或 sessionStorage')
    parser.add_argument('--storage-key', default='token',
                        help='存储键名，默认为 "token"')
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
    if not args.token:
        args.token = os.environ.get('UITEST_TOKEN')
    if not args.token:
        parser.error('必须通过 --token 参数或 UITEST_TOKEN 环境变量提供 Token')

    state_output = Path(args.state_output).resolve()
    state_output.parent.mkdir(parents=True, exist_ok=True)

    screenshot_dir = Path(args.screenshot_dir) if args.screenshot_dir else state_output.parent
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    result = {
        'method': 'token',
        'url': args.url,
        'status': 'error',
        'message': '',
        'screenshot': '',
        'state_path': '',
        'current_url': '',
        'storage_type': args.storage_type,
        'storage_key': args.storage_key,
        'timestamp': '',
    }

    print('=' * 60)
    print('WebUI Token 注入登录')
    print('=' * 60)
    print(f'  目标 URL: {args.url}')
    print(f'  存储类型: {args.storage_type}')
    print(f'  存储键名: {args.storage_key}')
    print(f'  Token 长度: {len(args.token)} 字符')

    with sync_playwright() as pw:
        browser = None
        try:
            # ── 启动浏览器 ──────────────────────────────────
            print('\n[1/5] 启动浏览器...')
            _browser_type = _read_session_browser(os.environ.get('WORKSPACE', ''))
            browser = launch_browser(pw, browser_type=_browser_type)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
            )
            context.set_default_timeout(args.timeout)
            page = context.new_page()

            # ── 导航到目标页面 ──────────────────────────────
            # 必须先导航到目标域名，才能操作该域名下的 Storage
            print(f'[2/5] 导航到目标页面: {args.url}')
            page.goto(args.url, wait_until='domcontentloaded')
            # 企业 SPA 常有持续轮询/WebSocket，networkidle 可能永不触发，只给 5s
            try:
                page.wait_for_load_state('networkidle', timeout=5000)
            except PlaywrightTimeout:
                print('  注意: 等待网络空闲超时（SPA 轮询中），继续执行')

            print(f'  页面加载完成，当前 URL: {page.url}')

            # ── 注入 Token ──────────────────────────────────
            print(f'[3/5] 注入 Token 到 {args.storage_type}...')
            inject_result = inject_token(
                page, args.token, args.storage_type, args.storage_key
            )
            print(f'  Token 注入成功')
            print(f'    存储类型: {inject_result["storage_type"]}')
            print(f'    存储键名: {inject_result["storage_key"]}')
            print(f'    存储长度: {inject_result["stored_length"]} 字符')

            # 验证 Token 是否正确写入
            stored_value = read_stored_token(page, args.storage_type, args.storage_key)
            if stored_value == args.token:
                print('  Token 写入验证通过')
            else:
                print('  警告: Token 写入验证不一致')

            # ── 刷新页面使 Token 生效 ──────────────────────
            print('[4/5] 刷新页面使 Token 生效...')
            page.reload(wait_until='domcontentloaded')
            # 企业 SPA 常有持续轮询/WebSocket，networkidle 可能永不触发，只给 5s
            try:
                page.wait_for_load_state('networkidle', timeout=5000)
            except PlaywrightTimeout:
                print('  注意: 刷新后等待网络空闲超时（SPA 轮询中），继续验证')

            # 某些 SPA 应用在 Token 设置后需要等待路由完成
            page.wait_for_timeout(1000)

            # ── 验证会话 ────────────────────────────────────
            print('[5/5] 验证登录状态...')
            verification = verify_session(page, args.url)
            print(f'  验证结果: {"成功" if verification["success"] else "失败"}')
            print(f'  判断依据: {verification["reason"]}')
            print(f'  当前 URL: {page.url}')

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

            # 截图（full_page=False 避免 SPA 轮询导致渲染超时，timeout=10s）
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            screenshot_path = screenshot_dir / f'token_login_{timestamp}.png'
            try:
                page.screenshot(path=str(screenshot_path), full_page=False, timeout=10000)
                print(f'  截图已保存: {screenshot_path}')
            except Exception as e:
                print(f'  警告: 截图失败，已跳过: {e}')

            if verification['success']:
                # 保存浏览器状态
                # 注意: storage_state 只保存 cookie 和 localStorage
                # 对于 sessionStorage 的 Token，需要在后续操作中重新注入
                context.storage_state(path=str(state_output))

                # 如果使用 sessionStorage，额外记录 Token 信息以便后续恢复
                if args.storage_type == 'sessionStorage':
                    state_data = json.loads(state_output.read_text(encoding='utf-8'))
                    state_data['_sessionStorage'] = {
                        args.storage_key: args.token,
                    }
                    state_output.write_text(
                        json.dumps(state_data, ensure_ascii=False, indent=2),
                        encoding='utf-8'
                    )
                    print('  注意: sessionStorage Token 已额外记录到状态文件中')

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
                            method='token',
                            details={
                                'storage_type': args.storage_type,
                                'storage_key': args.storage_key,
                            },
                            recipes_dir=_recipes_dir,
                        )
                        print(f'  登录配方已保存: {_rp}')
                    except Exception as _e:
                        print(f'  警告: 保存登录配方失败: {_e}')

                # 合并页面探测（与 login_password.py / login_cookie.py 的 --explore-output 行为一致）
                if args.explore_output:
                    _explore_after_login(page, args.explore_output, screenshot_dir)
            else:
                result.update({
                    'status': 'failed',
                    'message': verification['reason'],
                    'screenshot': str(screenshot_path),
                    'current_url': page.url,
                })

        except RuntimeError as e:
            error_msg = str(e)
            print(f'\n  错误: {error_msg}')
            result['message'] = error_msg

        except Exception as e:
            error_msg = f'Token 注入过程发生错误: {type(e).__name__}: {str(e)}'
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
