#!/usr/bin/env python3
"""vue-router 3.x（Vue 2 配套）配置解析器.

设计原则：
- 不用 tree-sitter（依赖重 + macOS/Linux/Windows 安装兼容性差）
- 用正则 + 简单状态机解析（vue-router 配置足够规范）
- 跨平台兼容（pathlib + sys.platform 守卫）
- Python 3.9+

输入：
- repo_path: vue 项目根目录（含 package.json + src/router/）

输出：
- list[Route]：扁平化的路由列表，每个 Route 含 url/component_file/name/meta

支持的路由模式（参考 utp-vue/test-tm 实证）：
1. 主入口 src/router/index.js 含 require.context 动态聚合 modules/*.routes.js
2. menu.routes.js 含一级菜单路由（嵌套 children）
3. modules/*.routes.js 含二/三级路由
4. component 字段：
   - `() => import('@/views/x.vue')`
   - `() => import(/* webpackChunkName: "x" */ '@/views/x.vue')`
   - 直接 import 的组件变量名
5. @ alias 解析为 src/（标准 vue-cli 配置）
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Windows UTF-8 防护
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


@dataclass
class Route:
    """单条路由记录（扁平化后）."""
    url: str  # 完整 URL 路径（含父路由前缀）
    component_file: Optional[str]  # 相对项目根的组件文件路径，None 表示无法解析
    name: Optional[str] = None
    meta: dict = field(default_factory=dict)
    source_file: Optional[str] = None  # 路由定义所在文件（相对 repo）
    parent_path: Optional[str] = None  # 嵌套路由的父路径
    has_unparsed_children: bool = False  # v0.1 不展开嵌套 children，标记给消费方
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────
# 路由文件发现
# ──────────────────────────────────────────────────────────────

def discover_router_files(repo_path: Path) -> list[Path]:
    """发现所有 vue-router 配置文件.

    优先级：
    1. src/router/index.js（主入口，可能不含 routes 但含 require.context 聚合）
    2. src/router/menu.routes.js（一级菜单）
    3. src/router/modules/*.routes.js（模块路由）
    4. fallback: 全 src 下扫 *routes*.js

    返回：按上述优先级排序的文件列表（已去重）
    """
    repo_path = Path(repo_path)
    if not repo_path.exists():
        return []
    router_dir = repo_path / "src" / "router"
    files: list[Path] = []
    if router_dir.exists():
        # 一级 .js 文件
        for f in sorted(router_dir.glob("*.js")):
            if f.is_file():
                files.append(f)
        # modules 目录
        modules_dir = router_dir / "modules"
        if modules_dir.exists():
            for f in sorted(modules_dir.glob("*.routes.js")):
                if f.is_file():
                    files.append(f)
    # fallback：全 src 下找
    if not files:
        src_dir = repo_path / "src"
        if src_dir.exists():
            for f in sorted(src_dir.rglob("*routes*.js")):
                if f.is_file() and "node_modules" not in str(f):
                    files.append(f)
    # 去重
    seen = set()
    deduped = []
    for f in files:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            deduped.append(f)
    return deduped


# ──────────────────────────────────────────────────────────────
# 路由配置正则解析
# ──────────────────────────────────────────────────────────────

# 匹配 path: 'xxx' 或 path: "xxx"（捕获引号内内容）
_PATH_RE = re.compile(r"""path\s*:\s*['"]([^'"]+)['"]""")

# 匹配 name: 'xxx' 或 name: "xxx"
_NAME_RE = re.compile(r"""name\s*:\s*['"]([^'"]+)['"]""")

# 匹配 component: () => import('@/path/file.vue') 形式
# 兼容含 webpackChunkName 注释的写法
_COMPONENT_IMPORT_RE = re.compile(
    r"""component\s*:\s*\(\s*\)\s*=>\s*import\s*\("""
    r"""\s*(?:/\*[^*]*\*/\s*)?"""  # 可选 webpackChunkName 注释
    r"""['"]([^'"]+)['"]"""
)

# 匹配 component: ComponentName 形式（直接引用）
_COMPONENT_NAME_RE = re.compile(r"""component\s*:\s*([A-Z]\w+)\s*[,\}]""")

# 匹配 import ComponentName from 'path' 或 require('path')
_IMPORT_RE = re.compile(
    r"""import\s+(\w+)\s+from\s+['"]([^'"]+)['"]"""
)

# 匹配 children: [ ... ] — 用于嵌套路由
_CHILDREN_START_RE = re.compile(r"""children\s*:\s*\[""")
# 匹配 children 字段（任意形式）
_CHILDREN_FIELD_RE = re.compile(r"""\bchildren\s*:""")


def _join_route_path(parent_path: str, child_path: str) -> str:
    """拼接父子路由 path（children 常为相对路径如 list、reportManage）."""
    parent = (parent_path or "").strip()
    child = (child_path or "").strip()
    if not child:
        return _normalize_url_path(parent)
    if child.startswith("/"):
        return _normalize_url_path(child)
    if not parent or parent == "/":
        return _normalize_url_path("/" + child.lstrip("/"))
    return _normalize_url_path(parent.rstrip("/") + "/" + child.lstrip("/"))


def _normalize_url_path(path: str) -> str:
    p = (path or "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    # 合并重复斜杠
    while "//" in p:
        p = p.replace("//", "/")
    return p.rstrip("/") or "/"


def _resolve_alias(import_path: str, alias_map: dict[str, str]) -> str:
    """解析 webpack alias（@/x → src/x）.

    alias_map: {'@': 'src', '~': 'src', ...}
    返回：相对 repo 根的路径（含 .vue / .js 后缀如果有）
    """
    for alias, resolved in alias_map.items():
        if import_path.startswith(alias + "/"):
            return resolved + import_path[len(alias):]
        if import_path == alias:
            return resolved
    return import_path


def _resolve_component_file(import_path: str, source_file: Path, repo_path: Path,
                            alias_map: dict[str, str]) -> Optional[str]:
    """解析路由配置中 component import 路径为相对 repo 的真实文件路径.

    支持：
    - @/views/x → src/views/x[.vue][.js][/index.vue]
    - ./relative → 相对 source_file 解析
    - 自动补 .vue / .js / /index.vue 后缀
    """
    if not import_path:
        return None
    # 解析 alias
    resolved = _resolve_alias(import_path, alias_map)
    # 相对路径
    if resolved.startswith("./") or resolved.startswith("../"):
        base = source_file.parent
        candidate = (base / resolved).resolve()
    else:
        candidate = (repo_path / resolved).resolve()
    repo_resolved = repo_path.resolve()

    def _rel(p: Path) -> str:
        # macOS /var → /private/var symlink，两侧需都用 resolve()
        try:
            return str(p.relative_to(repo_resolved))
        except ValueError:
            try:
                return str(p.resolve().relative_to(repo_resolved))
            except ValueError:
                return str(p)

    # 已有后缀
    if candidate.exists() and candidate.is_file():
        return _rel(candidate)
    # 尝试补后缀
    for suffix in [".vue", ".js", ".ts", "/index.vue", "/index.js", "/index.ts"]:
        with_suffix = Path(str(candidate) + suffix)
        if with_suffix.exists() and with_suffix.is_file():
            return _rel(with_suffix)
    return None


def _detect_alias_map(repo_path: Path) -> dict[str, str]:
    """从 vue.config.js / jsconfig.json / webpack.config.js 检测 alias 配置.

    默认 vue-cli 行为：@ → src
    """
    alias_map = {"@": "src"}
    # jsconfig.json
    jsconfig = repo_path / "jsconfig.json"
    if jsconfig.exists():
        try:
            import json
            data = json.loads(jsconfig.read_text(encoding="utf-8"))
            paths = (data.get("compilerOptions") or {}).get("paths") or {}
            for alias_with_star, target_list in paths.items():
                if not target_list:
                    continue
                # @/* 形式
                alias = alias_with_star.rstrip("/*")
                target = target_list[0].rstrip("/*")
                if alias and target:
                    alias_map[alias] = target
        except Exception:  # noqa: BLE001
            pass
    return alias_map


# ──────────────────────────────────────────────────────────────
# 路由 block 提取
# ──────────────────────────────────────────────────────────────

def _strip_comments(code: str) -> str:
    """去除 // 单行注释 + /* */ 块注释（保留 webpackChunkName 形态）.

    简化处理：去 // 行注释 + 多行 /* */ 注释。
    保留字符串字面量内的内容（用简易状态机区分）。
    """
    out = []
    i, n = 0, len(code)
    in_string: Optional[str] = None  # 当前字符串引号字符
    while i < n:
        c = code[i]
        if in_string:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            if c == in_string:
                in_string = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            in_string = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n:
            nxt = code[i + 1]
            if nxt == "/":
                # 单行注释，跳到换行
                j = code.find("\n", i)
                if j == -1:
                    break
                i = j
                continue
            if nxt == "*":
                # 块注释，跳到 */
                j = code.find("*/", i + 2)
                if j == -1:
                    break
                i = j + 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _extract_route_objects(code: str) -> list[str]:
    """从 JS 代码中提取所有顶层路由对象（含 path/component 的 {}）.

    简化策略：用括号匹配找 { ... } 块，过滤含 path: 字段的。
    """
    blocks: list[str] = []
    n = len(code)
    i = 0
    while i < n:
        if code[i] == "{":
            depth = 1
            start = i
            i += 1
            in_string: Optional[str] = None
            while i < n and depth > 0:
                c = code[i]
                if in_string:
                    if c == "\\" and i + 1 < n:
                        i += 2
                        continue
                    if c == in_string:
                        in_string = None
                    i += 1
                    continue
                if c in ("'", '"', "`"):
                    in_string = c
                    i += 1
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        block = code[start:i + 1]
                        if _PATH_RE.search(block):
                            blocks.append(block)
                        i += 1
                        break
                i += 1
        else:
            i += 1
    return blocks


def _extract_child_route_objects(block: str) -> list[str]:
    """从带 children: [...] 的父路由 block 中提取子路由对象文本.

    提取 children 数组内容中的所有 {...} 块，仅保留含 path: 字段的。
    """
    children_match = _CHILDREN_FIELD_RE.search(block)
    if not children_match:
        return []
    # 找 children: 后面的 [
    bracket_start = block.find("[", children_match.end())
    if bracket_start == -1:
        return []
    # bracket 匹配找 ] 结束位置
    depth = 1
    i = bracket_start + 1
    in_string: Optional[str] = None
    while i < len(block) and depth > 0:
        c = block[i]
        if in_string:
            if c == "\\" and i + 1 < len(block):
                i += 2
                continue
            if c == in_string:
                in_string = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            in_string = c
            i += 1
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        i += 1
    children_content = block[bracket_start + 1 : i - 1]

    # 在 children 内容中提取 {...} 块
    child_blocks: list[str] = []
    j = 0
    n = len(children_content)
    while j < n:
        if children_content[j] == "{":
            cdepth = 1
            start = j
            j += 1
            in_str: Optional[str] = None
            while j < n and cdepth > 0:
                c = children_content[j]
                if in_str:
                    if c == "\\" and j + 1 < n:
                        j += 2
                        continue
                    if c == in_str:
                        in_str = None
                    j += 1
                    continue
                if c in ("'", '"', "`"):
                    in_str = c
                    j += 1
                    continue
                if c == "{":
                    cdepth += 1
                elif c == "}":
                    cdepth -= 1
                    if cdepth == 0:
                        cb = children_content[start : j + 1]
                        if _PATH_RE.search(cb):
                            child_blocks.append(cb)
                        j += 1
                        break
                j += 1
        else:
            j += 1
    return child_blocks


def _parse_meta(block: str) -> dict:
    """从路由块中提取 meta 字段（简化：抓 'k': v 形态的 string/bool/number 值）."""
    meta_match = re.search(
        r"""meta\s*:\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}""",
        block,
    )
    if not meta_match:
        return {}
    meta_body = meta_match.group(1)
    meta: dict = {}
    # k: 'v' / k: "v"
    for m in re.finditer(r"""(\w+)\s*:\s*['"]([^'"]+)['"]""", meta_body):
        meta[m.group(1)] = m.group(2)
    # k: true/false
    for m in re.finditer(r"""(\w+)\s*:\s*(true|false)\b""", meta_body):
        meta[m.group(1)] = m.group(2) == "true"
    # k: 数字
    for m in re.finditer(r"""(\w+)\s*:\s*(\d+)\b""", meta_body):
        if m.group(1) not in meta:
            meta[m.group(1)] = int(m.group(2))
    return meta


def parse_router_file(file_path: Path, repo_path: Path,
                      alias_map: Optional[dict[str, str]] = None) -> list[Route]:
    """解析单个路由配置文件，返回扁平化路由列表."""
    file_path = Path(file_path)
    repo_path = Path(repo_path)
    if not file_path.exists():
        return []
    if alias_map is None:
        alias_map = _detect_alias_map(repo_path)
    try:
        code = file_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return []
    code = _strip_comments(code)
    # 找路由对象块
    blocks = _extract_route_objects(code)
    # 同时收集 import 名称 → 路径，用于 component: ComponentName 形式
    import_map: dict[str, str] = {}
    for m in _IMPORT_RE.finditer(code):
        import_map[m.group(1)] = m.group(2)
    routes: list[Route] = []
    for block in blocks:
        path_m = _PATH_RE.search(block)
        if not path_m:
            continue
        path = path_m.group(1)
        has_children = bool(_CHILDREN_FIELD_RE.search(block))
        if has_children:
            children_pos = _CHILDREN_FIELD_RE.search(block).start()
            head = block[:children_pos]
        else:
            head = block

        # 记录父路由自身（component 为 Layout 类包装，has_unparsed_children=True
        # 仅当 children 没有被展开时）
        component_file: Optional[str] = None
        comp_import_m = _COMPONENT_IMPORT_RE.search(head)
        if comp_import_m:
            component_file = _resolve_component_file(
                comp_import_m.group(1), file_path, repo_path, alias_map
            )
        else:
            comp_name_m = _COMPONENT_NAME_RE.search(head)
            if comp_name_m:
                comp_name = comp_name_m.group(1)
                if comp_name in import_map:
                    component_file = _resolve_component_file(
                        import_map[comp_name], file_path, repo_path, alias_map
                    )

        name_m = _NAME_RE.search(head)
        name = name_m.group(1) if name_m else None
        meta = _parse_meta(head)

        try:
            src_file = str(file_path.resolve().relative_to(repo_path.resolve()))
        except ValueError:
            src_file = str(file_path)

        if has_children:
            # 尝试展开 children 内联路由
            child_blocks = _extract_child_route_objects(block)
            if child_blocks:
                # 展开成功：将父路由标记为已展开的包装路由
                routes.append(Route(
                    url=path,
                    component_file=component_file,
                    name=name,
                    meta=meta,
                    source_file=src_file,
                    parent_path=None,
                    has_unparsed_children=False,
                    warnings=[],
                ))
                # 逐个解析子路由
                for cb in child_blocks:
                    child_path_m = _PATH_RE.search(cb)
                    if not child_path_m:
                        continue
                    child_path = _join_route_path(path, child_path_m.group(1))
                    child_name_m = _NAME_RE.search(cb)
                    child_name = child_name_m.group(1) if child_name_m else None
                    child_comp_file: Optional[str] = None
                    child_comp_import_m = _COMPONENT_IMPORT_RE.search(cb)
                    if child_comp_import_m:
                        child_comp_file = _resolve_component_file(
                            child_comp_import_m.group(1), file_path, repo_path, alias_map
                        )
                    else:
                        child_comp_name_m = _COMPONENT_NAME_RE.search(cb)
                        if child_comp_name_m:
                            ccn = child_comp_name_m.group(1)
                            if ccn in import_map:
                                child_comp_file = _resolve_component_file(
                                    import_map[ccn], file_path, repo_path, alias_map
                                )
                    child_meta = _parse_meta(cb)
                    routes.append(Route(
                        url=_normalize_url_path(child_path),
                        component_file=child_comp_file,
                        name=child_name,
                        meta=child_meta,
                        source_file=src_file,
                        parent_path=_normalize_url_path(path),
                        has_unparsed_children=False,
                        warnings=[],
                    ))
                continue  # 已经展开了，跳过末尾的父路由记录
            else:
                # children 是变量引用，无法展开
                inline_children_count = max(0, block.count("path:") - 1)
                count_desc = (
                    f"共 {inline_children_count} 个 inline 子路由"
                    if inline_children_count > 0
                    else "children 是变量引用（数量未知）"
                )
                routes.append(Route(
                    url=path,
                    component_file=component_file,
                    name=name,
                    meta=meta,
                    source_file=src_file,
                    has_unparsed_children=True,
                    warnings=[
                        f"v0.1 not_supported: children 嵌套路由不展开（{count_desc}）。"
                        f"子路由请单独配置或等 v0.2"
                    ],
                ))
                continue

        # 无 children 的路由
        routes.append(Route(
            url=path,
            component_file=component_file,
            name=name,
            meta=meta,
            source_file=src_file,
            has_unparsed_children=False,
            warnings=[],
        ))
    return routes


def parse_vue_router(repo_path: Path) -> list[Route]:
    """主入口：解析整个 vue 项目的路由配置.

    自动发现 src/router/ 下所有 *.routes.js + index.js + menu.routes.js，
    解析后返回扁平化的路由列表。
    """
    repo_path = Path(repo_path)
    files = discover_router_files(repo_path)
    if not files:
        return []
    alias_map = _detect_alias_map(repo_path)
    all_routes: list[Route] = []
    for f in files:
        all_routes.extend(parse_router_file(f, repo_path, alias_map))
    return all_routes


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(description="vue-router 3.x 配置解析器")
    parser.add_argument("--repo", required=True, type=Path,
                        help="vue 项目根目录")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出 JSON 文件（默认 stdout）")
    args = parser.parse_args()
    routes = parse_vue_router(args.repo)
    payload = {
        "schema_version": "0.1",
        "framework": "vue2",
        "repo": str(args.repo),
        "total_routes": len(routes),
        "routes": [r.to_dict() for r in routes],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"[vue-router-parser] 写入 {args.output}（{len(routes)} 个路由）")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
