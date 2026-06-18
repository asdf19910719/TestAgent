#!/usr/bin/env python3
"""
登录状态有效性校验脚本（含配方查找）

三层校验逻辑：
  1. 文件存在 + JSON 可解析
  2. 认证数据存在（cookies / origins[localStorage] / _sessionStorage）
  3. 域名匹配（--target-url 指定时，校验状态是否属于当前目标系统）
  4. TTL 未过期（基于文件修改时间）

当状态无效时，自动在 --recipes-dir 中查找可用的登录配方，
附加到输出 JSON 的 recipe 字段，供 Agent 决策是否使用配方回放登录。

使用方式：
    python validate_login_state.py \
      --state-file qa/webui/shared_assets/ui-elements/login-state.json \
      --target-url https://app.example.com/page \
      --recipes-dir qa/webui/shared_assets/login-recipes

退出码：
    0 = 状态有效，可复用（Agent 跳过登录步骤）
    1 = 状态无效或已过期（检查输出 JSON 的 recipe 字段决定下一步）
"""
import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

_RECIPE_MOD = None
_recipe_path = Path(__file__).resolve().parent / 'login_recipe_manager.py'
if _recipe_path.exists():
    _spec = importlib.util.spec_from_file_location('login_recipe_manager', _recipe_path)
    _RECIPE_MOD = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_RECIPE_MOD)


def _domain_matches(cookie_domain, target_host):
    """
    判断 cookie domain 是否匹配目标 host。
    - ".example.com" 匹配 "app.example.com" 和 "example.com"
    - "app.example.com" 只匹配 "app.example.com"
    """
    if not cookie_domain or not target_host:
        return False
    cookie_domain = cookie_domain.lower().lstrip('.')
    target_host = target_host.lower()
    return target_host == cookie_domain or target_host.endswith('.' + cookie_domain)


def _check_playwright_format(state):
    """
    校验 login-state.json 是否为 Playwright storage_state() 标准格式。
    标准格式必须包含 cookies 数组（每项含 name/value/domain）和 origins 数组。
    Returns: (valid: bool, reason: str)
    """
    if not isinstance(state, dict):
        return False, '状态文件内容不是 JSON 对象'

    cookies = state.get('cookies')
    if cookies is None:
        return False, '缺少 cookies 字段（非 Playwright storage_state 格式）'
    if not isinstance(cookies, list):
        return False, f'cookies 字段不是数组（类型: {type(cookies).__name__}）'

    for i, cookie in enumerate(cookies):
        if not isinstance(cookie, dict):
            return False, f'cookies[{i}] 不是对象'
        for required_key in ('name', 'value', 'domain'):
            if required_key not in cookie:
                return False, f'cookies[{i}] 缺少必需字段 "{required_key}"'

    if 'origins' not in state:
        return False, '缺少 origins 字段（非 Playwright storage_state 格式）'
    if not isinstance(state['origins'], list):
        return False, f'origins 字段不是数组（类型: {type(state["origins"]).__name__}）'

    return True, 'Playwright storage_state 格式校验通过'


def _has_auth_data(state):
    """
    检查状态文件中是否包含有效认证数据。
    修复缺口 3：不仅检查 cookies，还检查 localStorage (origins) 和 _sessionStorage。
    """
    has_cookies = bool(state.get('cookies'))
    has_local_storage = False
    for origin in state.get('origins', []):
        if origin.get('localStorage'):
            has_local_storage = True
            break
    has_session_storage = bool(state.get('_sessionStorage'))
    return has_cookies or has_local_storage or has_session_storage


def _auth_data_summary(state):
    """返回认证数据的摘要描述。"""
    parts = []
    cookies = state.get('cookies', [])
    if cookies:
        parts.append(f'{len(cookies)} 条 cookie')
    for origin in state.get('origins', []):
        ls = origin.get('localStorage', [])
        if ls:
            parts.append(f'{len(ls)} 条 localStorage ({origin.get("origin", "?")})')
    if state.get('_sessionStorage'):
        parts.append(f'{len(state["_sessionStorage"])} 条 sessionStorage')
    return '、'.join(parts) if parts else '无认证数据'


def validate(state_file, ttl_hours, target_url=None):
    """
    校验 login-state.json 是否有效。

    Args:
        state_file: login-state.json 的路径
        ttl_hours: 有效期（小时），默认 8 小时
        target_url: 目标 URL（可选），用于域名匹配校验

    Returns:
        dict: {'valid': bool, 'reason': str, 'expires_in_minutes': int, ...}
    """
    path = Path(state_file)

    if not path.exists():
        return {'valid': False, 'reason': f'文件不存在: {state_file}', 'expires_in_minutes': 0}

    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        return {'valid': False, 'reason': f'文件解析失败: {e}', 'expires_in_minutes': 0}

    fmt_valid, fmt_reason = _check_playwright_format(state)
    if not fmt_valid:
        return {'valid': False, 'reason': f'格式校验失败: {fmt_reason}', 'expires_in_minutes': 0,
                'format_error': True}

    if not _has_auth_data(state):
        return {'valid': False, 'reason': '状态文件中不含任何认证数据（cookie/localStorage/sessionStorage 均为空）',
                'expires_in_minutes': 0}

    # 域名匹配校验：防止跨系统串用
    if target_url:
        target_host = urlparse(target_url).hostname
        if target_host:
            cookies = state.get('cookies', [])
            domain_match = False
            if cookies:
                for cookie in cookies:
                    if _domain_matches(cookie.get('domain', ''), target_host):
                        domain_match = True
                        break
            else:
                # 无 cookies 时检查 origins 的 origin 字段是否匹配
                for origin in state.get('origins', []):
                    origin_host = urlparse(origin.get('origin', '')).hostname
                    if origin_host and (origin_host == target_host or
                                        target_host.endswith('.' + origin_host) or
                                        origin_host.endswith('.' + target_host)):
                        domain_match = True
                        break
                if not domain_match and state.get('_sessionStorage'):
                    domain_match = True  # sessionStorage 无 domain 信息，信任

            if not domain_match:
                cookie_domains = list({c.get('domain', '') for c in cookies})
                return {
                    'valid': False,
                    'reason': f'状态文件不属于目标系统（目标: {target_host}，'
                              f'state 中的域: {cookie_domains}）',
                    'expires_in_minutes': 0,
                    'domain_mismatch': True,
                }

    # TTL 校验
    mtime = path.stat().st_mtime
    mtime_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    age_seconds = (now - mtime_dt).total_seconds()
    ttl_seconds = ttl_hours * 3600
    remaining_seconds = ttl_seconds - age_seconds

    if remaining_seconds <= 0:
        age_minutes = int(age_seconds / 60)
        return {
            'valid': False,
            'reason': f'登录状态已过期（文件已 {age_minutes} 分钟，TTL={ttl_hours} 小时）',
            'expires_in_minutes': 0,
        }

    expires_in_minutes = int(remaining_seconds / 60)
    summary = _auth_data_summary(state)
    return {
        'valid': True,
        'reason': f'登录状态有效（还有约 {expires_in_minutes} 分钟过期，{summary}）',
        'expires_in_minutes': expires_in_minutes,
        'auth_summary': summary,
        'state_file': str(path.resolve()),
    }


def _find_recipe(entry_url, recipes_dir, method=None):
    """查找配方（如果配方管理器可用）。"""
    if not _RECIPE_MOD or not recipes_dir:
        return None
    recipes_path = Path(recipes_dir)
    if not recipes_path.exists():
        return None
    return _RECIPE_MOD.find_recipe(entry_url, recipes_dir, method)


def main():
    parser = argparse.ArgumentParser(description='校验 login-state.json 是否仍然有效（含配方查找）')
    parser.add_argument('--state-file', '--state', required=True,
                        help='login-state.json 路径，通常为 qa/webui/shared_assets/ui-elements/login-state.json')
    parser.add_argument('--ttl-hours', type=int, default=8,
                        help='有效期（小时），默认 8 小时。超过此时长则认为需要重新登录。')
    parser.add_argument('--target-url', default=None,
                        help='目标 URL。指定后会校验状态文件的 cookie domain 是否匹配目标系统，'
                             '防止不同系统的登录状态互相串用。')
    parser.add_argument('--recipes-dir', default=None,
                        help='登录配方目录（默认不查找）。状态无效时自动查找配方并附加到输出。')
    parser.add_argument('--method', default=None,
                        choices=['password', 'cookie', 'token'],
                        help='指定登录方式（可选），精确匹配配方')
    args = parser.parse_args()

    result = validate(args.state_file, args.ttl_hours, args.target_url)
    result['checked_at'] = datetime.now().isoformat()

    # 状态无效时查找配方
    if not result['valid'] and args.recipes_dir and args.target_url:
        recipe = _find_recipe(args.target_url, args.recipes_dir, args.method)
        if recipe:
            # 脱敏 recipe details，仅保留非敏感字段
            _RECIPE_ALLOWED_FIELDS = {
                'method', 'domain_key', 'success_count', 'username_placeholder',
                'password_placeholder', 'url_field', 'target_url', 'login_path',
                'entry_selector', 'username_selector', 'password_selector',
                'login_selector', 'verify_url', 'cookie_filter',
            }
            details = recipe.get('details', {})
            sanitized = {
                k: v for k, v in details.items()
                if k in _RECIPE_ALLOWED_FIELDS
            }
            result['recipe'] = {
                'found': True,
                'file': recipe.get('_recipe_file', ''),
                'method': recipe.get('method', ''),
                'domain_key': recipe.get('domain_key', ''),
                'success_count': recipe.get('success_count', 0),
                'details': sanitized,
            }
            result['recipe_hint'] = (
                f'找到登录配方（方式: {recipe["method"]}，'
                f'成功次数: {recipe.get("success_count", 0)}），'
                f'可使用配方参数快速登录'
            )
        else:
            result['recipe'] = {'found': False}

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result['valid']:
        print(f'\n✅ 登录状态有效，可跳过登录步骤。{result["reason"]}', file=sys.stderr)
        sys.exit(0)
    else:
        msg = f'⚠️  需要重新登录。{result["reason"]}'
        if result.get('recipe_hint'):
            msg += f'\n💡 {result["recipe_hint"]}'
        print(f'\n{msg}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
