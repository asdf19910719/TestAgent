#!/usr/bin/env python3
"""
登录配方(Recipe)管理器

将登录成功时的关键参数持久化为结构化"配方"文件，
cookie/token 过期后直接回放配方完成登录，无需重新探索页面。

三层复用优先级：
  L1  认证状态缓存  (login-state.json, cookie/localStorage/sessionStorage)
  L2  登录配方回放  (login-recipes/*.json, 本模块管理)
  L3  全自动登录    (自动识别选择器，首次登录或配方失效时)

缓存键：entry_host + login_host + auth_method
存储位置：qa/webui/shared_assets/login-recipes/{domain_key}.json

使用方式：
    # 查找配方
    python login_recipe_manager.py --action find --entry-url https://app.example.com/page
    # 列出所有配方
    python login_recipe_manager.py --action list --recipes-dir qa/webui/shared_assets/login-recipes
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


RECIPE_VERSION = '1.0'


def _extract_host_port(url):
    """从 URL 提取 host:port（标准端口省略）。"""
    parsed = urlparse(url)
    host = parsed.hostname or ''
    port = parsed.port
    if port and port not in (80, 443):
        return f'{host}_{port}'
    return host


def _sanitize_for_filename(s):
    """将字符串转换为安全的文件名片段。"""
    return re.sub(r'[^\w.\-]', '_', s)


def compute_domain_key(entry_url, login_url=None, method='password'):
    """
    计算配方的复合缓存键。

    Args:
        entry_url: 入口 URL（用户提供的目标页面）
        login_url: 实际登录页 URL（SSO 跳转后的地址，首次可能未知）
        method: 登录方式 (password / cookie / token)

    Returns:
        str: 形如 "app.example.com__sso.example.com__password" 的缓存键
    """
    entry_host = _extract_host_port(entry_url)
    parts = [entry_host]

    if login_url:
        login_host = _extract_host_port(login_url)
        if login_host and login_host != entry_host:
            parts.append(login_host)
        else:
            parts.append('direct')
    else:
        parts.append('unknown')

    parts.append(method)
    return '__'.join(parts)


def recipe_filename(domain_key):
    """生成配方文件名。"""
    return _sanitize_for_filename(domain_key) + '.json'


def save_recipe(entry_url, login_url, method, details, recipes_dir):
    """
    保存登录配方。

    Args:
        entry_url: 入口 URL
        login_url: 实际登录页 URL（SSO 跳转后）
        method: 登录方式 (password / cookie / token)
        details: 方法特定的详情字典
            password: {selectors: {username, password, submit}, sso_flow: {...}}
            cookie: {cookie_domain: str}
            token: {storage_type: str, storage_key: str}
        recipes_dir: 配方存储目录路径

    Returns:
        Path: 保存的配方文件路径
    """
    recipes_dir = Path(recipes_dir)
    recipes_dir.mkdir(parents=True, exist_ok=True)

    key = compute_domain_key(entry_url, login_url, method)
    filepath = recipes_dir / recipe_filename(key)

    now_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    existing = None
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding='utf-8'))
        except Exception:
            pass

    recipe = {
        'version': RECIPE_VERSION,
        'domain_key': key,
        'entry_host': _extract_host_port(entry_url),
        'entry_origin': _build_origin(entry_url),
        'login_host': _extract_host_port(login_url) if login_url else None,
        'login_origin': _build_origin(login_url) if login_url else None,
        'method': method,
        'details': details,
        'created_at': existing['created_at'] if existing else now_iso,
        'updated_at': now_iso,
        'last_used_at': now_iso,
        'success_count': (existing.get('success_count', 0) + 1) if existing else 1,
    }

    filepath.write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return filepath


def _build_origin(url):
    """构建 origin (scheme://host[:port])。"""
    if not url:
        return None
    parsed = urlparse(url)
    origin = f'{parsed.scheme}://{parsed.hostname}'
    if parsed.port and parsed.port not in (80, 443):
        origin += f':{parsed.port}'
    return origin


def find_recipe(entry_url, recipes_dir, method=None):
    """
    按入口 URL 查找匹配的配方。

    查找策略：
    1. 精确匹配：entry_host + method
    2. 宽松匹配：仅 entry_host（忽略 method 和 login_host）

    Args:
        entry_url: 入口 URL
        recipes_dir: 配方存储目录
        method: 可选，指定登录方式过滤

    Returns:
        dict or None: 配方内容，未找到返回 None
    """
    recipes_dir = Path(recipes_dir)
    if not recipes_dir.exists():
        return None

    entry_host = _extract_host_port(entry_url)
    if not entry_host:
        return None

    best_match = None
    best_score = -1

    for f in recipes_dir.glob('*.json'):
        try:
            recipe = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue

        if recipe.get('entry_host') != entry_host:
            continue

        score = 0
        if method and recipe.get('method') == method:
            score += 10
        elif method and recipe.get('method') != method:
            continue

        score += recipe.get('success_count', 0)

        if score > best_score:
            best_score = score
            best_match = recipe
            best_match['_recipe_file'] = str(f)

    return best_match


def update_recipe_usage(recipe_path):
    """
    更新配方的使用统计（last_used_at 和 success_count）。

    Args:
        recipe_path: 配方文件路径
    """
    path = Path(recipe_path)
    if not path.exists():
        return

    try:
        recipe = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return

    recipe['last_used_at'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    recipe['success_count'] = recipe.get('success_count', 0) + 1

    path.write_text(
        json.dumps(recipe, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def list_recipes(recipes_dir):
    """
    列出所有配方摘要。

    Returns:
        list[dict]: 配方摘要列表
    """
    recipes_dir = Path(recipes_dir)
    if not recipes_dir.exists():
        return []

    summaries = []
    for f in sorted(recipes_dir.glob('*.json')):
        try:
            recipe = json.loads(f.read_text(encoding='utf-8'))
            summaries.append({
                'file': str(f),
                'domain_key': recipe.get('domain_key', ''),
                'method': recipe.get('method', ''),
                'entry_host': recipe.get('entry_host', ''),
                'login_host': recipe.get('login_host', ''),
                'success_count': recipe.get('success_count', 0),
                'last_used_at': recipe.get('last_used_at', ''),
            })
        except Exception:
            continue

    return summaries


def main():
    parser = argparse.ArgumentParser(description='登录配方管理器')
    parser.add_argument('--action', required=True, choices=['find', 'list'],
                        help='操作：find=查找配方, list=列出所有配方')
    parser.add_argument('--entry-url', default=None,
                        help='入口 URL（find 时必填）')
    parser.add_argument('--method', default=None,
                        choices=['password', 'cookie', 'token'],
                        help='登录方式过滤（可选）')
    parser.add_argument('--recipes-dir',
                        default='qa/webui/shared_assets/login-recipes',
                        help='配方存储目录（默认 qa/webui/shared_assets/login-recipes）')
    args = parser.parse_args()

    if args.action == 'find':
        if not args.entry_url:
            parser.error('find 操作需要 --entry-url 参数')
        recipe = find_recipe(args.entry_url, args.recipes_dir, args.method)
        if recipe:
            print(json.dumps(recipe, ensure_ascii=False, indent=2))
            sys.exit(0)
        else:
            print(json.dumps({'found': False, 'entry_url': args.entry_url},
                              ensure_ascii=False, indent=2))
            sys.exit(1)

    elif args.action == 'list':
        summaries = list_recipes(args.recipes_dir)
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
        sys.exit(0)


if __name__ == '__main__':
    main()
