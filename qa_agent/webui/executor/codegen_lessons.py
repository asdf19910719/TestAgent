#!/usr/bin/env python3
"""
Codegen Lessons 存储层 — 域名隔离的经验积累 CRUD API。

存储结构：
  {workspace}/qa/webui/shared_assets/lessons/
    index.json                    # 全局索引（域名→lesson 文件映射）
    {domain_hash}.lessons.json    # 单域名经验文件

单域名存储上限 100 条，超出时淘汰最旧（last_hit 最早）的条目。
供 Agent 在步骤 4（脚本生成）前读取，步骤 5（修复循环）后写入。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

MAX_LESSONS_PER_DOMAIN = 100
LESSONS_DIR_NAME = 'lessons'

if sys.platform == 'win32':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def _domain_hash(domain: str) -> str:
    return hashlib.md5(domain.encode('utf-8')).hexdigest()[:12]


def _lessons_dir(workspace: str) -> Path:
    return Path(workspace) / 'qa/webui' / 'shared_assets' / LESSONS_DIR_NAME


def _index_path(workspace: str) -> Path:
    return _lessons_dir(workspace) / 'index.json'


def _domain_file(workspace: str, domain: str) -> Path:
    return _lessons_dir(workspace) / f'{_domain_hash(domain)}.lessons.json'


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_json(path: Path, data: dict):
    """原子写入 JSON：先写临时文件再 rename，防止并发写损坏。"""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, ensure_ascii=False, indent=2)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        Path(tmp).replace(path)
    except OSError:
        path.write_text(content, encoding='utf-8')


def _extract_domain(target_url: str) -> str:
    if not target_url:
        return 'unknown'
    parsed = urlparse(target_url)
    return parsed.hostname or 'unknown'


def _ensure_index(workspace: str, domain: str) -> dict:
    idx = _read_json(_index_path(workspace))
    if 'domains' not in idx:
        idx['domains'] = {}
    if domain not in idx['domains']:
        idx['domains'][domain] = {
            'file': f'{_domain_hash(domain)}.lessons.json',
            'count': 0,
            'created_at': datetime.now().astimezone().isoformat(),
        }
        _write_json(_index_path(workspace), idx)
    return idx


# ── Public API ────────────────────────────────────────────────────────


def list_domains(workspace: str) -> list[str]:
    """返回已有经验的所有域名列表。"""
    idx = _read_json(_index_path(workspace))
    return list(idx.get('domains', {}).keys())


def read_lessons(workspace: str, target_url: str,
                 scope: Optional[str] = None) -> list[dict]:
    """读取指定域名的 lessons，可选按 scope（页面/模块）过滤。

    Args:
        workspace: 工作空间根路径
        target_url: 被测 URL（自动提取域名）
        scope: 可选过滤条件（如 '登录页'、'列表页'），模糊匹配 lesson.scope

    Returns:
        按 last_hit 降序排列的 lesson 列表
    """
    domain = _extract_domain(target_url)
    data = _read_json(_domain_file(workspace, domain))
    lessons = data.get('lessons', [])

    if scope:
        scope_lower = scope.lower()
        lessons = [l for l in lessons if scope_lower in l.get('scope', '').lower()]

    lessons.sort(key=lambda x: x.get('last_hit', ''), reverse=True)
    return lessons


def add_lesson(workspace: str, target_url: str, lesson: dict) -> dict:
    """新增一条 lesson，自动去重（按 scope + pattern 匹配）、淘汰超限条目。

    lesson 结构：
    {
        "scope": "列表页/表格操作",
        "pattern": "el-loading-mask 拦截点击",
        "root_cause": "表格数据重新加载时 loading 覆盖在表格上",
        "fix": "操作前 wait_for_selector('.el-loading-mask', state='hidden')",
        "severity": "high|medium|low",
        "source": "auto|manual"
    }

    Returns:
        写入后的完整 lesson（含 id、时间戳）
    """
    domain = _extract_domain(target_url)
    _ensure_index(workspace, domain)

    fpath = _domain_file(workspace, domain)
    data = _read_json(fpath)
    if 'domain' not in data:
        data['domain'] = domain
        data['lessons'] = []

    lessons = data['lessons']
    now = datetime.now().astimezone().isoformat()

    # 去重：scope + pattern 完全相同视为重复，更新 hit 计数
    for existing in lessons:
        if (existing.get('scope', '').strip() == lesson.get('scope', '').strip()
                and existing.get('pattern', '').strip() == lesson.get('pattern', '').strip()):
            existing['hit_count'] = existing.get('hit_count', 1) + 1
            existing['last_hit'] = now
            if lesson.get('fix'):
                existing['fix'] = lesson['fix']
            _write_json(fpath, data)
            _sync_index_count(workspace, domain, len(lessons))
            return existing

    # 新增
    import uuid as _uuid
    short_id = _uuid.uuid4().hex[:8]
    confidence = lesson.get('confidence', 'medium')
    lesson_entry = {
        'id': f'L_{short_id}',
        'scope': lesson.get('scope', ''),
        'pattern': lesson.get('pattern', ''),
        'root_cause': lesson.get('root_cause', ''),
        'fix': lesson.get('fix', ''),
        'severity': lesson.get('severity', 'medium'),
        'confidence': confidence,
        'source': lesson.get('source', 'auto'),
        'hit_count': 1,
        'created_at': now,
        'last_hit': now,
        'stale': False,
    }
    lessons.append(lesson_entry)

    # 超限淘汰：低置信度 + 低命中 + 最早创建优先淘汰
    if len(lessons) > MAX_LESSONS_PER_DOMAIN:
        _conf_order = {'low': 0, 'medium': 1, 'high': 2}
        lessons.sort(key=lambda x: (
            _conf_order.get(x.get('confidence', 'medium'), 1),
            x.get('hit_count', 1),
            x.get('created_at', ''),
        ))
        lessons[:] = lessons[-MAX_LESSONS_PER_DOMAIN:]

    data['lessons'] = lessons
    _write_json(fpath, data)
    _sync_index_count(workspace, domain, len(lessons))
    return lesson_entry


def mark_stale(workspace: str, target_url: str, lesson_id: str):
    """将指定 lesson 标记为过时（stale），不删除，由审核者决定是否保留。"""
    domain = _extract_domain(target_url)
    fpath = _domain_file(workspace, domain)
    data = _read_json(fpath)
    for lesson in data.get('lessons', []):
        if lesson.get('id') == lesson_id:
            lesson['stale'] = True
            lesson['stale_marked_at'] = datetime.now().astimezone().isoformat()
            _write_json(fpath, data)
            return True
    return False


def remove_lesson(workspace: str, target_url: str, lesson_id: str) -> bool:
    """删除指定 lesson。"""
    domain = _extract_domain(target_url)
    fpath = _domain_file(workspace, domain)
    data = _read_json(fpath)
    lessons = data.get('lessons', [])
    before = len(lessons)
    data['lessons'] = [l for l in lessons if l.get('id') != lesson_id]
    if len(data['lessons']) < before:
        _write_json(fpath, data)
        _sync_index_count(workspace, domain, len(data['lessons']))
        return True
    return False


def get_lessons_for_prompt(workspace: str, target_url: str,
                           max_items: int = 30) -> str:
    """生成适合注入 LLM prompt 的经验摘要文本。

    分层过滤：
      1. 仅非 stale 条目
      2. 按 severity（high > medium > low）+ hit_count 排序
      3. 截取前 max_items 条
    """
    lessons = read_lessons(workspace, target_url)
    active = [l for l in lessons if not l.get('stale')]

    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    conf_order = {'high': 0, 'medium': 1, 'low': 2}
    active.sort(key=lambda x: (
        conf_order.get(x.get('confidence', 'medium'), 1),
        severity_order.get(x.get('severity', 'medium'), 1),
        -x.get('hit_count', 1),
    ))
    selected = active[:max_items]

    if not selected:
        return ''

    domain = _extract_domain(target_url)
    lines = [f'## 已知经验（域名: {domain}，共 {len(selected)} 条）\n']
    for l in selected:
        lines.append(f'- **[{l.get("scope", "")}]** {l.get("pattern", "")}')
        if l.get('root_cause'):
            lines.append(f'  根因: {l["root_cause"]}')
        if l.get('fix'):
            lines.append(f'  修复: {l["fix"]}')
    return '\n'.join(lines)


def _sync_index_count(workspace: str, domain: str, count: int):
    idx = _read_json(_index_path(workspace))
    if 'domains' in idx and domain in idx['domains']:
        idx['domains'][domain]['count'] = count
        idx['domains'][domain]['updated_at'] = datetime.now().astimezone().isoformat()
        _write_json(_index_path(workspace), idx)


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    """CLI 入口：支持 list / read / add / stale / remove / prompt 子命令。"""
    import argparse
    parser = argparse.ArgumentParser(description='Codegen Lessons CRUD')
    parser.add_argument('--workspace', required=True)
    sub = parser.add_subparsers(dest='cmd')

    sub.add_parser('list')

    p_read = sub.add_parser('read')
    p_read.add_argument('--url', required=True)
    p_read.add_argument('--scope', default=None)

    p_add = sub.add_parser('add')
    p_add.add_argument('--url', required=True)
    p_add.add_argument('--lesson-json', required=True,
                       help='lesson JSON 字符串或文件路径')

    p_stale = sub.add_parser('stale')
    p_stale.add_argument('--url', required=True)
    p_stale.add_argument('--id', required=True)

    p_rm = sub.add_parser('remove')
    p_rm.add_argument('--url', required=True)
    p_rm.add_argument('--id', required=True)

    p_prompt = sub.add_parser('prompt')
    p_prompt.add_argument('--url', required=True)
    p_prompt.add_argument('--max', type=int, default=30)

    args = parser.parse_args()
    ws = str(Path(args.workspace).resolve())

    if args.cmd == 'list':
        domains = list_domains(ws)
        print(json.dumps(domains, ensure_ascii=False))

    elif args.cmd == 'read':
        lessons = read_lessons(ws, args.url, scope=args.scope)
        print(json.dumps(lessons, ensure_ascii=False, indent=2))

    elif args.cmd == 'add':
        lesson_input = args.lesson_json.strip()
        if lesson_input.startswith('{'):
            lesson = json.loads(lesson_input)
        else:
            lesson = json.loads(Path(lesson_input).read_text(encoding='utf-8'))
        result = add_lesson(ws, args.url, lesson)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == 'stale':
        ok = mark_stale(ws, args.url, args.id)
        print('OK' if ok else 'NOT_FOUND')

    elif args.cmd == 'remove':
        ok = remove_lesson(ws, args.url, args.id)
        print('OK' if ok else 'NOT_FOUND')

    elif args.cmd == 'prompt':
        text = get_lessons_for_prompt(ws, args.url, max_items=args.max)
        print(text)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
