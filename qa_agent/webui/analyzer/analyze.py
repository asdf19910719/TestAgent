#!/usr/bin/env python3
"""web-uitest-frontend-analyzer 总控入口.

用法（Mac/Linux）：
    .venv/bin/python scripts/analyze.py \
      --frontend-repo /path/to/vue-project \
      --test-urls /planManage /planManage/operateAdd \
      --output .aqe-output/webui-session/analysis/frontend_knowledge.json

用法（Windows）：
    .venv\\Scripts\\python.exe assets\\skills\\web-uitest-frontend-analyzer\\scripts\\analyze.py ^
      --frontend-repo C:\\path\\to\\repo --test-urls /planManage --output xx.json

输入：
- --frontend-repo: vue 项目根目录（必需）
- --test-urls: 多个测试 URL（路径片段，可含 query；自动剥离微前端基座前缀）
- --base-prefix: 可选，要剥离的微前端基座前缀（如 /cloud-work/cyxt/tm）
- --max-depth: 入口组件追溯深度上限（默认 3）
- --output: 输出 JSON 文件

输出 frontend_knowledge.json schema 详见 references/output-schema.md.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

# 让本文件作为脚本运行时也能 import parsers/extractors
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

try:
    # 作为包导入（qa_agent.webui.analyzer.analyze）
    from .parsers.vue_router_parser import parse_vue_router
    from .parsers.vue2_component_parser import parse_vue_component
    from .extractors.component_knowledge import (
        extract_component_knowledge,
    )
except ImportError:
    # 作为脚本直接运行（python analyze.py）
    from parsers.vue_router_parser import parse_vue_router  # noqa: E402
    from parsers.vue2_component_parser import parse_vue_component  # noqa: E402
    from extractors.component_knowledge import (  # noqa: E402
        extract_component_knowledge,
    )


SCHEMA_VERSION = "0.1"


def _check_package_json_for_framework(pkg: Path) -> tuple[str, str]:
    """从单个 package.json 检测框架，返回 (framework, version) 或 ('unknown', '')."""
    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ("unknown", "")
    deps = {**(data.get("dependencies") or {}),
            **(data.get("devDependencies") or {})}
    if "vue" in deps:
        version = deps["vue"]
        clean = version.lstrip("^~>=<")
        major = clean.split(".")[0] if clean else ""
        if major == "2":
            return ("vue2", clean)
        if major == "3":
            return ("vue3", clean)
        return ("vue", clean)
    if "react" in deps:
        return ("react", deps["react"].lstrip("^~>=<"))
    return ("unknown", "")


def detect_framework(repo: Path) -> tuple[str, str, Optional[Path]]:
    """读 package.json 检测框架.

    返回 (framework_name, framework_version, effective_repo_path)
    - effective_repo_path: 实际检测到框架的项目根目录（monorepo 时为子项目路径）
      若为 None 表示直接使用传入的 repo

    支持 monorepo：若根 package.json 无框架依赖，向下搜索子目录的
    package.json，优先选含 vue 的子项目。返回子项目路径供后续路由解析使用。
    """
    pkg = repo / "package.json"
    if not pkg.exists():
        return ("unknown", "", None)
    # 先检查根 package.json
    result = _check_package_json_for_framework(pkg)
    if result[0] != "unknown":
        return (result[0], result[1], None)
    # Monorepo fallback：搜索子目录（排除 node_modules），优先选 Vue 项目
    candidates: list[tuple[str, str, Path]] = []
    for sub_pkg in sorted(repo.rglob("package.json")):
        if sub_pkg == pkg:
            continue
        if "node_modules" in sub_pkg.parts:
            continue
        try:
            rel_parts = sub_pkg.relative_to(repo).parts
        except ValueError:
            continue
        if len(rel_parts) > 4:
            continue
        sub_result = _check_package_json_for_framework(sub_pkg)
        if sub_result[0] != "unknown":
            candidates.append((sub_result[0], sub_result[1], sub_pkg))
    if not candidates:
        return ("unknown", "", None)
    # 优先选 vue2 > vue3 > vue > react
    priority = {"vue2": 0, "vue3": 1, "vue": 2, "react": 3}
    candidates.sort(key=lambda c: priority.get(c[0], 99))
    best = candidates[0]
    sub_project_root = best[2].parent
    print(
        f"[analyze] monorepo 检测：根 package.json 无框架依赖，"
        f"从子项目 {best[2].relative_to(repo)} 检测到 {best[0]} {best[1]}"
        f"（共发现 {len(candidates)} 个子项目含框架依赖）",
        file=sys.stderr,
    )
    return (best[0], best[1], sub_project_root)


def get_repo_commit(repo: Path) -> str:
    """获取 repo 当前 commit hash（用于产物追溯）."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def normalize_test_url(url: str, base_prefix: str = "") -> str:
    """规范化测试 URL：剥离 host / query / 微前端基座前缀，得到路由 path."""
    # 剥离 query
    if "?" in url:
        url = url.split("?", 1)[0]
    # 剥离 hash
    if "#" in url:
        url = url.split("#", 1)[0]
    # 剥离 protocol+host
    if "://" in url:
        url = "/" + url.split("/", 3)[-1] if "/" in url.split("://", 1)[1] else "/"
    # 剥离基座前缀
    if base_prefix and url.startswith(base_prefix):
        url = url[len(base_prefix):]
    if not url.startswith("/"):
        url = "/" + url
    return url


def _route_url(route) -> str:
    """统一读取路由 path（Route 对象或 dict）."""
    url = route.url if hasattr(route, "url") else route["url"]
    url = (url or "/").strip()
    if not url.startswith("/"):
        url = "/" + url
    return url


def _route_to_dict(route) -> dict:
    return route if isinstance(route, dict) else route.to_dict()


def infer_base_prefix(norm_url: str, routes: list) -> str:
    """未传 --base-prefix 时，用已知路由后缀反推微前端基座前缀."""
    norm = norm_url.rstrip("/") or "/"
    if norm == "/":
        return ""
    best = ""
    for r in routes:
        r_url = _route_url(r).rstrip("/") or "/"
        if r_url in ("/", "") or len(r_url) < 2:
            continue
        if norm == r_url:
            continue
        if not norm.endswith(r_url) or len(r_url) < 2:
            continue
        prefix = norm[: -len(r_url)]
        if not prefix.startswith("/"):
            continue
        if len(prefix) > len(best):
            best = prefix
    return best.rstrip("/") if best and best != "/" else ""


def _normalize_route_path(path: str) -> str:
    p = (path or "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/"


def _url_suffix_matches(target: str, route_path: str) -> bool:
    """target 以 route_path 为路径后缀（边界安全）."""
    t = _normalize_route_path(target)
    r = _normalize_route_path(route_path)
    if r == "/" or len(r) < 2:
        return False
    if t == r:
        return True
    if not t.endswith(r) or len(r) < 2:
        return False
    prefix = t[: -len(r)]
    return not prefix or prefix.startswith("/")


def find_route_for_url(routes: list, target_url: str) -> Optional[dict]:
    """在路由列表中找精确匹配的 route.

    v0.1: 仅做精确匹配，不做 silent 前缀 fallback（防止把
    /planManage/unknown 误关联到 /planManage 的入口组件，污染下游决策）。
    嵌套子路由 v0.1 不展开（详见 has_unparsed_children 标记）。
    """
    norm_url = target_url.rstrip("/") or "/"
    for r in routes:
        r_url = (r.url if hasattr(r, "url") else r["url"]).rstrip("/") or "/"
        if r_url == norm_url:
            return r if isinstance(r, dict) else r.to_dict()
    return None


def find_routes_under_prefix(routes: list, target_url: str) -> list[dict]:
    """辅助函数：找 target_url 前缀下的所有路由（用于诊断/warning 信息）.

    严格不作匹配兜底用，仅用于 warnings 中提示用户"你的 URL 没找到，但
    我们发现这些前缀路由可能相关"。
    """
    norm_url = target_url.rstrip("/") or "/"
    candidates = []
    for r in routes:
        r_url = (r.url if hasattr(r, "url") else r["url"]).rstrip("/") or "/"
        if (norm_url.startswith(r_url + "/") and r_url != "/") or (
                r_url.startswith(norm_url + "/")):
            candidates.append(r if isinstance(r, dict) else r.to_dict())
    return candidates


def find_sibling_routes(routes: list, target_url: str) -> list[dict]:
    """找以 target_url 为前缀的所有子路由（含 target_url 自己）.

    动机（解决用户场景）：用户提示词通常只给入口 URL（如 /planManage），
    但业务测试常常会跳转到子页（/planManage/operateAdd / /edit / /detail）。
    本函数让 frontend-analyzer 自动覆盖这些子路由的入口组件，避免
    case-analyst 写"创建测试方案"用例时拿不到 operateAdd 的字段信息。

    匹配规则：
    - 精确匹配 target_url 自己
    - 以 target_url + "/" 开头的所有路由（前缀子路由）
    - 不返回前缀下的 children 嵌套路由（has_unparsed_children=True 的会单独 warning）

    注意：根路由 "/" 是特殊情况，不会触发"全表追溯"——根路由仅匹配自己。
    """
    norm_url = target_url.rstrip("/") or "/"
    siblings: list[dict] = []
    seen_urls = set()
    for r in routes:
        r_url = (r.url if hasattr(r, "url") else r["url"]).rstrip("/") or "/"
        if r_url in seen_urls:
            continue
        # 精确匹配
        if r_url == norm_url:
            siblings.append(r if isinstance(r, dict) else r.to_dict())
            seen_urls.add(r_url)
            continue
        # 前缀子路由（norm_url 不是 / 时才扩展，避免根路由污染）
        if norm_url != "/" and r_url.startswith(norm_url + "/"):
            siblings.append(r if isinstance(r, dict) else r.to_dict())
            seen_urls.add(r_url)
    return siblings


def _merge_route_dicts(groups: list[list[dict]]) -> list[dict]:
    """合并多组路由 dict，按 url 去重."""
    merged: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        for r in group:
            u = _normalize_route_path(r.get("url") or "/")
            if u in seen:
                continue
            seen.add(u)
            merged.append(r)
    return merged


def find_routes_relaxed(routes: list, target_url: str) -> tuple[list[dict], str]:
    """宽松路由匹配：strict → suffix → last-segment.

    返回 (匹配到的路由列表, match_mode)。
    match_mode: strict | suffix | segment | segment_ambiguous | none
    """
    strict = find_sibling_routes(routes, target_url)
    if strict:
        return strict, "strict"

    norm = _normalize_route_path(target_url)
    target_segments = [s for s in norm.split("/") if s]

    # 后缀匹配：/cloud-work/cyxt/tm/reportManage → /reportManage
    suffix_bases: list[str] = []
    for r in routes:
        r_url = _route_url(r)
        if _url_suffix_matches(norm, r_url):
            suffix_bases.append(r_url.rstrip("/") or "/")
    if suffix_bases:
        groups = [find_sibling_routes(routes, base) for base in suffix_bases]
        groups = [g for g in groups if g]
        if groups:
            return _merge_route_dicts(groups), "suffix"

    # 末段匹配：.../reportManage 与路由末段相同
    if target_segments:
        last = target_segments[-1].lower()
        seg_hits: list[dict] = []
        for r in routes:
            r_url = _route_url(r)
            segs = [s for s in r_url.split("/") if s]
            if segs and segs[-1].lower() == last:
                seg_hits.append(_route_to_dict(r))
        if len(seg_hits) == 1:
            base = _normalize_route_path(seg_hits[0].get("url") or "/")
            expanded = find_sibling_routes(routes, base)
            return expanded or seg_hits, "segment"
        if seg_hits:
            return _merge_route_dicts([seg_hits]), "segment_ambiguous"

    return [], "none"


def url_matches_route_relaxed(norm_url: str, route_path: str) -> bool:
    """判断规范化 URL 是否与某条路由相关（用于 relevant_routes 预筛选）."""
    nu = _normalize_route_path(norm_url)
    rp = _normalize_route_path(route_path)
    if rp == nu:
        return True
    if nu != "/" and rp.startswith(nu + "/"):
        return True
    if rp != "/" and nu.startswith(rp + "/"):
        return True
    if _url_suffix_matches(nu, rp):
        return True
    nu_segs = [s for s in nu.split("/") if s]
    rp_segs = [s for s in rp.split("/") if s]
    return bool(nu_segs and rp_segs and nu_segs[-1].lower() == rp_segs[-1].lower())


def collect_component_files(entry_file: Path, repo: Path,
                            max_depth: int = 3,
                            visited: Optional[set[str]] = None,
                            depth: int = 0) -> list[Path]:
    """从入口组件递归收集子组件文件（最多 max_depth 层）."""
    if visited is None:
        visited = set()
    if depth >= max_depth:
        return []
    rel = str(entry_file.resolve())
    if rel in visited:
        return []
    visited.add(rel)
    if not entry_file.exists() or not entry_file.is_file():
        return []
    files = [entry_file]
    parsed = parse_vue_component(entry_file, repo)
    # 通过 imports 找子组件文件路径
    for imp in parsed.script_imports:
        path = imp.from_path
        # 仅追溯 . 或 @/ 开头的本地组件
        if not (path.startswith(".") or path.startswith("@/")):
            continue
        # alias 解析（简化：@ → src）
        if path.startswith("@/"):
            resolved_path = "src/" + path[2:]
            candidate = (repo / resolved_path).resolve()
        else:
            candidate = (entry_file.parent / path).resolve()
        # 补后缀
        target: Optional[Path] = None
        for suffix in ["", ".vue", ".js", ".ts", "/index.vue", "/index.js"]:
            cand = Path(str(candidate) + suffix)
            if cand.exists() and cand.is_file() and cand.suffix in (".vue",):
                target = cand
                break
        if target:
            files.extend(collect_component_files(
                target, repo, max_depth, visited, depth + 1,
            ))
    return files


def _find_best_monorepo_subproject(repo: Path, test_urls: list[str],
                                    base_prefix: str) -> Optional[Path]:
    """在 monorepo 中找到与 test_urls 最匹配的 Vue 子项目.

    策略：遍历所有含 vue 依赖的子项目，对每个子项目执行路由发现，
    选出能匹配最多 test_urls 的子项目。若无法通过路由匹配区分，
    选路由数量最多的子项目。
    """
    pkg = repo / "package.json"
    if not pkg.exists():
        return None
    root_result = _check_package_json_for_framework(pkg)
    if root_result[0] != "unknown":
        return None

    vue_subprojects: list[Path] = []
    for sub_pkg in sorted(repo.rglob("package.json")):
        if sub_pkg == pkg or "node_modules" in sub_pkg.parts:
            continue
        try:
            rel_parts = sub_pkg.relative_to(repo).parts
        except ValueError:
            continue
        if len(rel_parts) > 4:
            continue
        sub_result = _check_package_json_for_framework(sub_pkg)
        if sub_result[0] in ("vue2", "vue3"):
            vue_subprojects.append(sub_pkg.parent)

    if not vue_subprojects:
        return None
    if len(vue_subprojects) == 1:
        return vue_subprojects[0]

    # 用路由匹配评分：哪个子项目的路由能命中最多 test_urls（含宽松匹配）
    best_project: Optional[Path] = None
    best_score = -1
    best_route_count = 0
    for sub_root in vue_subprojects:
        routes = parse_vue_router(sub_root)
        score = 0
        for raw in test_urls:
            nu = normalize_test_url(raw, base_prefix)
            if not base_prefix:
                inferred = infer_base_prefix(nu, routes)
                if inferred:
                    nu = normalize_test_url(raw, inferred)
            matched, _mode = find_routes_relaxed(routes, nu)
            if matched:
                score += 1
        if score > best_score or (score == best_score and len(routes) > best_route_count):
            best_score = score
            best_route_count = len(routes)
            best_project = sub_root
    return best_project


def _slim_component(comp: dict) -> dict:
    """精简组件知识，去掉空值和大模型断言生成不需要的噪声字段."""
    result: dict = {}
    # form_fields: 只保留有值的字段
    fields = comp.get("form_fields", [])
    if fields:
        slim_fields = []
        for f in fields:
            sf: dict = {}
            if f.get("label"):
                sf["label"] = f["label"]
            if f.get("type") and f["type"] != "unknown":
                sf["type"] = f["type"]
            if f.get("required"):
                sf["required"] = True
            if f.get("placeholder"):
                sf["placeholder"] = f["placeholder"]
            if f.get("v_model"):
                sf["v_model"] = f["v_model"]
            if f.get("v_if"):
                sf["v_if"] = f["v_if"]
            if f.get("v_show"):
                sf["v_show"] = f["v_show"]
            if f.get("max_length"):
                sf["max_length"] = f["max_length"]
            dlg = f.get("dialog_context", {})
            if dlg.get("in_dialog"):
                sf["in_dialog"] = True
                if dlg.get("visibility_binding"):
                    sf["dialog_visibility"] = dlg["visibility_binding"]
            if f.get("selector_hint_unverified"):
                sf["selector_hint"] = f["selector_hint_unverified"]
            if f.get("label_source"):
                sf["label_source"] = f["label_source"]
            if f.get("type") in ("section", "toggle", "config_column"):
                sf["type"] = f["type"]
            if sf:
                slim_fields.append(sf)
        if slim_fields:
            result["form_fields"] = slim_fields

    # buttons: 只保留有文本或有 handler 的
    buttons = comp.get("buttons", [])
    if buttons:
        slim_btns = []
        for b in buttons:
            sb: dict = {}
            if b.get("text"):
                sb["text"] = b["text"]
            if b.get("type"):
                sb["type"] = b["type"]
            if b.get("handler_method"):
                sb["handler"] = b["handler_method"]
            elif b.get("handler"):
                sb["handler"] = b["handler"]
            if b.get("disabled_when"):
                sb["disabled_when"] = b["disabled_when"]
            if b.get("loading_when"):
                sb["loading_when"] = b["loading_when"]
            if b.get("v_if"):
                sb["v_if"] = b["v_if"]
            if b.get("ui_role"):
                sb["ui_role"] = b["ui_role"]
            if b.get("in_dropdown"):
                sb["in_dropdown"] = True
            dlg = b.get("dialog_context", {})
            if dlg.get("in_dialog"):
                sb["in_dialog"] = True
            if sb:
                slim_btns.append(sb)
        if slim_btns:
            result["buttons"] = slim_btns

    page_tabs = comp.get("page_tabs", [])
    if page_tabs:
        result["page_tabs"] = [
            {k: t[k] for k in ("label", "name", "lazy", "source") if t.get(k)}
            for t in page_tabs
        ]

    confirms = comp.get("confirm_dialogs", [])
    if confirms:
        result["confirm_dialogs"] = [
            {
                k: c[k]
                for k in ("message", "title", "confirm_button", "cancel_button")
                if c.get(k)
            }
            for c in confirms[:8]
        ]

    custom_forms = comp.get("custom_form_components", [])
    if custom_forms:
        result["custom_form_components"] = custom_forms

    # api_calls: 保持精简
    apis = comp.get("api_calls", [])
    if apis:
        slim_apis = []
        for a in apis:
            sa: dict = {"method": a.get("method_name", "")}
            if a.get("import_from"):
                sa["from"] = a["import_from"]
            slim_apis.append(sa)
        result["api_calls"] = slim_apis

    # state_machine: 只保留有条件的
    states = comp.get("state_machine", [])
    if states:
        slim_states = []
        for s in states:
            ss: dict = {"condition": s.get("condition", "")}
            if s.get("affects_text"):
                ss["affects"] = s["affects_text"]
            if s.get("directive") == "v-show":
                ss["directive"] = "v-show"
            slim_states.append(ss)
        result["state_conditions"] = slim_states

    # child_components: 仅列名字
    children = comp.get("child_components", [])
    if children:
        result["child_components"] = children

    # warnings 提升到顶层由 build_knowledge 处理，这里不重复
    return result


def _short_component_path(path: str) -> str:
    p = (path or "").replace("\\", "/")
    if "/views/" in p:
        return p.split("/views/", 1)[-1]
    return p.rsplit("/", 1)[-1] if p else ""


def build_element_index(components: dict, routes: list) -> dict:
    """扁平化索引，供大模型按需求做语义交叉引用（非需求专用解析）."""
    route_rows: list[dict] = []
    for r in routes:
        meta = r.get("meta") or {}
        route_rows.append({
            "url": r.get("url"),
            "name": r.get("name"),
            "menu_title": meta.get("name") if isinstance(meta, dict) else None,
            "component": _short_component_path(r.get("component_file") or ""),
        })

    buttons: list[dict] = []
    menu_actions: list[dict] = []
    fields: list[dict] = []
    sections: list[dict] = []
    tabs: list[dict] = []
    confirms: list[dict] = []
    required_fields: list[dict] = []
    seen_btn: set[tuple[str, str, str]] = set()
    seen_menu: set[tuple[str, str]] = set()
    seen_fld: set[tuple[str, str]] = set()
    seen_tab: set[tuple[str, str]] = set()

    for comp_path, comp in components.items():
        comp_short = _short_component_path(comp_path)
        for btn in comp.get("buttons") or []:
            text = (btn.get("text") or "").strip()
            if not text or "{{" in text:
                continue
            is_menu = btn.get("ui_role") == "menu_action" or btn.get("in_dropdown")
            if is_menu:
                mkey = (text, comp_short)
                if mkey in seen_menu:
                    continue
                seen_menu.add(mkey)
                mrow: dict = {"text": text, "component": comp_short}
                if btn.get("handler"):
                    mrow["handler"] = btn["handler"]
                if btn.get("v_if"):
                    mrow["v_if"] = str(btn["v_if"])[:80]
                menu_actions.append(mrow)
                continue
            key = (text, str(btn.get("handler", "")), comp_short)
            if key in seen_btn:
                continue
            seen_btn.add(key)
            row: dict = {"text": text, "component": comp_short}
            if btn.get("handler"):
                row["handler"] = btn["handler"]
            if btn.get("type"):
                row["type"] = btn["type"]
            if btn.get("in_dialog"):
                row["in_dialog"] = True
            if btn.get("disabled_when"):
                row["disabled_when"] = str(btn["disabled_when"])[:120]
            buttons.append(row)

        for tab in comp.get("page_tabs") or []:
            label = (tab.get("label") or "").strip()
            if not label:
                continue
            tkey = (label, comp_short)
            if tkey in seen_tab:
                continue
            seen_tab.add(tkey)
            trow: dict = {"label": label, "component": comp_short}
            if tab.get("lazy"):
                trow["lazy"] = True
            if tab.get("name"):
                trow["name"] = tab["name"]
            tabs.append(trow)

        for dlg in comp.get("confirm_dialogs") or []:
            msg = (dlg.get("message") or "")[:120]
            if msg:
                confirms.append({
                    "message": msg,
                    "confirm_button": dlg.get("confirm_button", "确定"),
                    "component": comp_short,
                })

        for fld in comp.get("form_fields") or []:
            label = (fld.get("label") or "").strip().rstrip("：:")
            if not label:
                continue
            fkey = (label, comp_short)
            if fkey in seen_fld:
                continue
            seen_fld.add(fkey)
            ftype = fld.get("type", "")
            if ftype == "section":
                sections.append({
                    "label": label,
                    "component": comp_short,
                    "v_if": str(fld.get("v_if", ""))[:80] or None,
                })
                continue
            row = {
                "label": label,
                "type": ftype,
                "component": comp_short,
            }
            if fld.get("required"):
                row["required"] = True
            if fld.get("in_dialog"):
                row["in_dialog"] = True
            if fld.get("placeholder"):
                row["placeholder"] = fld["placeholder"]
            if fld.get("label_source"):
                row["label_source"] = fld["label_source"]
            hint = fld.get("selector_hint") or fld.get("selector_hint_unverified")
            if hint:
                row["selector_hint"] = str(hint)[:100]
            fields.append(row)
            if fld.get("required"):
                required_fields.append(row)

    return {
        "routes": route_rows,
        "buttons": buttons,
        "menu_actions": menu_actions,
        "page_tabs": tabs,
        "section_headings": sections,
        "confirm_dialogs": confirms,
        "form_fields": fields,
        "required_fields": required_fields,
        "stats": {
            "route_count": len(route_rows),
            "button_count": len(buttons),
            "menu_action_count": len(menu_actions),
            "tab_count": len(tabs),
            "section_count": len(sections),
            "confirm_dialog_count": len(confirms),
            "field_count": len(fields),
            "required_field_count": len(required_fields),
        },
    }


def build_static_scan_summary(knowledge: dict, max_chars: int = 2800) -> str:
    """程序化生成结构化静态扫描摘要（通用，按路由分组）."""
    if knowledge.get("error"):
        return ""
    routes = knowledge.get("routes") or []
    idx = knowledge.get("element_index") or {}
    stats = idx.get("stats") or {}
    lines: list[str] = [
        "[附录·静态扫描摘要 — 机器生成，仅供元素定位；用户需求优先]",
        (
            f"框架: {knowledge.get('framework')} {knowledge.get('framework_version')} "
            f"| 相关路由 {stats.get('route_count', len(routes))} 条 "
            f"| 按钮 {stats.get('button_count', 0)} "
            f"| 菜单项 {stats.get('menu_action_count', 0)} "
            f"| Tab {stats.get('tab_count', 0)} "
            f"| 区块标题 {stats.get('section_count', 0)} "
            f"| 表单字段 {stats.get('field_count', 0)} "
            f"| 必填 {stats.get('required_field_count', 0)} "
            f"| 确认框 {stats.get('confirm_dialog_count', 0)}"
        ),
        "",
    ]

    # 按路由入口组件聚合
    comp_by_route: dict[str, dict] = {}
    components = knowledge.get("components") or {}
    for r in routes:
        url = r.get("url") or "/"
        entry = _short_component_path(r.get("component_file") or "")
        if not entry:
            continue
        comp_by_route[url] = {
            "menu_title": (r.get("meta") or {}).get("name"),
            "entry": entry,
            "url": url,
        }

    def _items_for_route(entry: str) -> dict:
        """收集入口组件及其子组件（from_routes 含该 url）上的元素."""
        url = next((u for u, m in comp_by_route.items() if m["entry"] == entry), "")
        related_paths = [
            p for p, c in components.items()
            if url in (c.get("from_routes") or [])
            or _short_component_path(p) == entry
        ]
        agg: dict = {
            "buttons": [], "menu_actions": [], "tabs": [],
            "sections": [], "fields": [], "dialogs": [],
        }
        seen: dict[str, set] = {k: set() for k in agg}
        for p in related_paths:
            c = components[p]
            short = _short_component_path(p)
            for b in c.get("buttons") or []:
                t = (b.get("text") or "").strip()
                if not t or "{{" in t:
                    continue
                if b.get("ui_role") == "menu_action" or b.get("in_dropdown"):
                    if t in seen["menu_actions"]:
                        continue
                    seen["menu_actions"].add(t)
                    agg["menu_actions"].append(_fmt_btn(b, short))
                else:
                    if t in seen["buttons"]:
                        continue
                    seen["buttons"].add(t)
                    agg["buttons"].append(_fmt_btn(b, short))
            for tab in c.get("page_tabs") or []:
                lb = tab.get("label", "")
                if lb and lb not in seen["tabs"]:
                    seen["tabs"].add(lb)
                    lazy = " [lazy]" if tab.get("lazy") else ""
                    agg["tabs"].append(f"{lb}{lazy}")
            for f in c.get("form_fields") or []:
                lb = (f.get("label") or "").strip()
                if not lb or lb in seen["fields"]:
                    continue
                if f.get("type") == "section":
                    if lb not in seen["sections"]:
                        seen["sections"].add(lb)
                        agg["sections"].append(lb)
                else:
                    seen["fields"].add(lb)
                    agg["fields"].append(_fmt_field(f, short))
            for d in c.get("confirm_dialogs") or []:
                msg = (d.get("message") or "")[:60]
                if msg and msg not in seen["dialogs"]:
                    seen["dialogs"].add(msg)
                    cb = d.get("confirm_button", "确定")
                    agg["dialogs"].append(f"「{msg}…」→确认「{cb}」")
        return agg

    for url in sorted(comp_by_route.keys(), key=lambda u: (u.count("/"), u)):
        meta = comp_by_route[url]
        title = meta.get("menu_title") or meta["entry"]
        lines.append(f"## {url}（{title}）")
        items = _items_for_route(meta["entry"])
        if items["buttons"]:
            lines.append(f"  按钮: {' | '.join(items['buttons'][:12])}")
        if items["menu_actions"]:
            lines.append(
                f"  下拉菜单: {' | '.join(items['menu_actions'][:10])} "
                f"(须先展开「…」)"
            )
        if items["tabs"]:
            lines.append(f"  页签: {' → '.join(items['tabs'][:10])}")
        if items["sections"]:
            lines.append(f"  区块: {' | '.join(items['sections'][:8])}")
        if items["fields"]:
            lines.append(f"  字段: {' | '.join(items['fields'][:14])}")
        if items["dialogs"]:
            lines.append(f"  确认框: {'; '.join(items['dialogs'][:4])}")
        lines.append("")

    warns = knowledge.get("warnings") or []
    if warns:
        lines.append("【扫描告警】")
        for w in warns[:6]:
            lines.append(f"  - {w[:160]}")
        if len(warns) > 6:
            lines.append(f"  …共 {len(warns)} 条，见 warnings")

    lines.append(
        "【说明】带空格按钮文案须精确匹配；in_dialog 字段须先打开弹窗；"
        "lazy Tab 须先切换页签；菜单项不在 element_index.buttons 中。"
    )
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n…(已截断)"
    return text


def _fmt_btn(b: dict, _comp: str) -> str:
    t = b.get("text", "")
    suffix = ""
    if b.get("in_dialog"):
        suffix += "[弹窗]"
    if b.get("disabled_when"):
        suffix += "[条件禁用]"
    if b.get("v_if"):
        suffix += "[v-if]"
    return f"{t}{suffix}"


def _fmt_field(f: dict, comp: str) -> str:
    lb = f.get("label", "")
    if f.get("required"):
        lb += "*"
    if f.get("in_dialog"):
        lb += "[弹窗]"
    if f.get("v_if"):
        lb += "[条件]"
    if f.get("type") == "config_column":
        lb += "[配置列]"
    return lb


def build_requirement_summary_interface() -> dict:
    """定义轨道 B 大模型如何基于扫描结果生成需求相关附录（契约，非业务解析规则）."""
    return {
        "version": "0.1",
        "consumer": (
            "web-uitest-runner Step 0 轨道 B：优先使用顶层 static_scan_summary；"
            "若需结合需求过滤，可 Read element_index 并覆写/增补附录"
        ),
        "constraints": {
            "max_appendix_chars": 2800,
            "embed_full_components_in_prompt": False,
            "user_requirement_is_source_of_truth": True,
        },
        "inputs": {
            "requirement_text": "用户 R 模式需求全文或 S 模式操作指令原文（由轨道 B 提供）",
            "element_index": "本文件 element_index 节（优先检索）",
            "components": "按步骤需要时下钻 components[路径] 核对细节",
        },
        "procedure": [
            "从 requirement_text 按原文语义拆成有序步骤（禁止套用固定业务关键词表或示例场景硬编码）",
            "逐步在 element_index 中语义匹配；必要时读 components 核对 handler、required、disabled_when",
            "每步标注 match_status（见 match_status_legend），写出定位线索",
            "摘录与需求步骤相关的必填项、弹窗依赖、权限/禁用条件；汇总 gap 与 conflict",
            "按 appendix_template 输出纯文本，字数≤max_appendix_chars",
        ],
        "match_status_legend": {
            "confirmed": "✓已确认",
            "partial": "△部分",
            "not_found": "?未覆盖",
            "conflict": "⚠冲突",
        },
        "appendix_template": (
            "[附录·静态扫描摘要 — 优先级最低，仅供元素定位参考，"
            "不影响需求理解和用例设计]\n"
            "框架: {framework} {version} | 相关路由{n_routes}条 | 入口: {entry_components}\n"
            "需求-扫描对照表（按需求步骤，以需求为准）：\n"
            "（表格：步 | 需求要点 | 状态 | 定位线索 | 备注）\n"
            "需求相关必填/权限摘录: …\n"
            "冲突: … | 未覆盖: …\n"
            "完整扫描: {session_dir}/analysis/frontend_knowledge.json"
        ),
        "anti_patterns": [
            "仅一行 pipe：已确认: A|B|C / 未覆盖: X",
            "将完整 components 或 element_index 粘贴进 task-description",
            "罗列与当前需求无关的大量控件",
            "因扫描结果改写用户需求或删减断言",
        ],
    }


def build_knowledge(repo: Path, test_urls: list[str], base_prefix: str,
                    max_depth: int, routes_only: bool = False) -> dict:
    """主流程：构建 frontend_knowledge.json 的内容."""
    framework, version, effective_repo = detect_framework(repo)
    if effective_repo is not None:
        # Monorepo：尝试智能选择与 test_urls 最匹配的子项目
        best_sub = _find_best_monorepo_subproject(repo, test_urls, base_prefix)
        if best_sub is not None:
            effective_repo = best_sub
        print(
            f"[analyze] monorepo 模式：使用子项目 {effective_repo} 作为实际分析根目录",
            file=sys.stderr,
        )
        repo = effective_repo
    if framework not in ("vue2", "vue3"):
        pkg = repo / "package.json"
        hint_deps = ""
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                all_deps = list({**(data.get("dependencies") or {}),
                                 **(data.get("devDependencies") or {})}.keys())[:10]
                hint_deps = f" 根 package.json 实际 deps(前10): {all_deps}"
            except Exception:  # noqa: BLE001
                hint_deps = " 根 package.json 解析失败"
        else:
            hint_deps = " 根目录下无 package.json"
        return {
            "schema_version": SCHEMA_VERSION,
            "framework": framework,
            "framework_version": version,
            "frontend_repo": str(repo.resolve()),
            "error": (
                f"v0.1 仅支持 Vue 2 项目，检测到 framework={framework} version={version}。"
                f"{hint_deps}。"
                f"提示：--frontend-repo 必须指向含 vue 依赖的项目根目录"
                f"（monorepo 需指向具体子项目，如 utp-vue/test-tm）"
            ),
        }
    if framework == "vue3":
        return {
            "schema_version": SCHEMA_VERSION,
            "framework": framework,
            "framework_version": version,
            "error": "Vue 3 支持在 v0.2 计划中（请暂用 v0.1 处理 Vue 2 项目）",
        }
    # 解析路由
    routes = parse_vue_router(repo)
    all_routes_dict = [r.to_dict() for r in routes]

    # ── 路由精简：只输出与 test_urls 相关的路由，去掉噪声字段 ──
    relevant_routes: list[dict] = []
    relevant_urls: set[str] = set()
    norm_urls = []
    for u in test_urls:
        nu = normalize_test_url(u, base_prefix)
        if not base_prefix:
            inferred = infer_base_prefix(nu, routes)
            if inferred:
                nu = normalize_test_url(u, inferred)
        norm_urls.append(nu)
    for r_dict in all_routes_dict:
        r_url = (r_dict.get("url") or "/").rstrip("/") or "/"
        for nu in norm_urls:
            if url_matches_route_relaxed(nu, r_url):
                if r_url not in relevant_urls:
                    slim = {
                        "url": r_dict["url"],
                        "component_file": r_dict.get("component_file"),
                        "name": r_dict.get("name"),
                        "meta": r_dict.get("meta") or {},
                    }
                    if r_dict.get("has_unparsed_children"):
                        slim["has_unparsed_children"] = True
                    relevant_routes.append(slim)
                    relevant_urls.add(r_url)
                break

    knowledge = {
        "schema_version": SCHEMA_VERSION,
        "framework": framework,
        "framework_version": version,
        "frontend_repo": str(repo.resolve()),
        "frontend_repo_commit": get_repo_commit(repo),
        "analyzed_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "base_prefix": base_prefix,
        "test_urls": test_urls,
        "total_routes": len(all_routes_dict),
        "relevant_route_count": len(relevant_routes),
        "routes": relevant_routes,
        "components": {},
        "warnings": [],
    }
    if routes_only:
        return knowledge
    # 对每个 test_url 找入口组件并自动追溯同前缀子路由的所有组件
    knowledge["matched_routes"] = []
    knowledge["inferred_base_prefixes"] = {}
    for raw_url in test_urls:
        norm_url = normalize_test_url(raw_url, base_prefix)
        effective_prefix = base_prefix
        if not base_prefix:
            inferred = infer_base_prefix(norm_url, routes)
            if inferred:
                effective_prefix = inferred
                norm_url = normalize_test_url(raw_url, inferred)
                knowledge["inferred_base_prefixes"][raw_url] = inferred
        siblings, match_mode = find_routes_relaxed(routes, norm_url)
        if not siblings:
            candidates = find_routes_under_prefix(routes, norm_url)
            hint = ""
            if candidates:
                cand_urls = [c.get("url") for c in candidates[:5]]
                hint = (
                    f" 可能相关的路由（仅供参考）：{cand_urls}"
                )
            knowledge["warnings"].append(
                f"路由未匹配到组件：{raw_url}（规范化为 {norm_url}）。"
                f"已尝试精确/后缀/末段匹配。若仍失败，可检查 --base-prefix"
                f"（当前 effective={effective_prefix or '(未设置)'}）、"
                f"嵌套 children 或动态菜单。{hint}"
            )
            continue
        if match_mode != "strict":
            knowledge["warnings"].append(
                f"路由宽松匹配：{raw_url} → {norm_url}（mode={match_mode}，"
                f"已关联 {len(siblings)} 条路由；若不准可显式传 --base-prefix）"
            )
        sibling_urls = [s["url"] for s in siblings]
        knowledge["matched_routes"].append({
            "input_url": raw_url,
            "normalized": norm_url,
            "match_mode": match_mode,
            "effective_base_prefix": effective_prefix,
            "matched_route_count": len(siblings),
            "matched_urls": sibling_urls,
        })
        for route in siblings:
            r_url = route.get("url")
            has_children = route.get("has_unparsed_children", False)
            if has_children:
                knowledge["warnings"].append(
                    f"路由 {r_url} 是嵌套父路由，v0.1 不展开 children。"
                    f"如果测试目标是其某个子路由（如 {r_url}/sub），需要等 v0.2 支持"
                )
            entry_file = route.get("component_file")
            if not entry_file:
                knowledge["warnings"].append(
                    f"路由 {r_url} 无法解析 component 文件路径（可能是 redirect 路由或 component 引用未识别）"
                )
                continue
            entry_path = repo / entry_file
            files = collect_component_files(entry_path, repo, max_depth=max_depth)
            for f in files:
                try:
                    rel = str(f.resolve().relative_to(repo.resolve()))
                except ValueError:
                    rel = str(f)
                if rel in knowledge["components"]:
                    continue
                parsed = parse_vue_component(f, repo)
                raw_knowledge = extract_component_knowledge(parsed, repo)
                for w in raw_knowledge.get("warnings", []):
                    knowledge["warnings"].append(f"[{rel}] {w}")
                comp_knowledge = _slim_component(raw_knowledge)
                comp_knowledge["from_routes"] = [r_url]
                knowledge["components"][rel] = comp_knowledge
            for f in files:
                try:
                    rel = str(f.resolve().relative_to(repo.resolve()))
                except ValueError:
                    rel = str(f)
                comp = knowledge["components"].get(rel)
                if comp and r_url not in comp.get("from_routes", []):
                    comp.setdefault("from_routes", []).append(r_url)
    if knowledge.get("components") and not knowledge.get("error"):
        knowledge["element_index"] = build_element_index(
            knowledge["components"],
            knowledge["routes"],
        )
        knowledge["requirement_summary_interface"] = (
            build_requirement_summary_interface()
        )
        knowledge["static_scan_summary"] = build_static_scan_summary(knowledge)
    return knowledge


def main() -> int:
    parser = argparse.ArgumentParser(description="web-uitest-frontend-analyzer 总控")
    parser.add_argument("--frontend-repo", required=True, type=Path,
                        help="vue 项目根目录")
    parser.add_argument("--test-urls", nargs="+", required=True,
                        help="测试 URL 列表（可含 host/query，自动规范化）")
    parser.add_argument("--base-prefix", default="",
                        help="微前端基座前缀（自动剥离）")
    parser.add_argument("--max-depth", type=int, default=3,
                        help="入口组件追溯深度上限")
    parser.add_argument("--output", required=True, type=Path,
                        help="输出 JSON 文件路径")
    args = parser.parse_args()
    repo = args.frontend_repo.resolve()
    if not repo.exists():
        print(f"[analyze] frontend-repo 不存在：{repo}", file=sys.stderr)
        return 2
    print(f"[analyze] 分析 {repo}（{len(args.test_urls)} 个 URL，max-depth={args.max_depth}）")
    knowledge = build_knowledge(
        repo=repo,
        test_urls=list(args.test_urls),
        base_prefix=args.base_prefix,
        max_depth=args.max_depth,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    n_components = len(knowledge.get("components", {}))
    n_warnings = len(knowledge.get("warnings", []))
    print(f"[analyze] ✓ 写入 {args.output}")
    print(f"[analyze]   - framework: {knowledge.get('framework')} {knowledge.get('framework_version')}")
    print(f"[analyze]   - 总路由数: {knowledge.get('total_routes', 0)}（相关: {knowledge.get('relevant_route_count', '?')}）")
    print(f"[analyze]   - 提取组件数: {n_components}")
    print(f"[analyze]   - warnings: {n_warnings}")
    summary_len = len(knowledge.get("static_scan_summary") or "")
    if summary_len:
        print(f"[analyze]   - static_scan_summary: {summary_len} chars")
    if "error" in knowledge:
        print(f"[analyze]   - ERROR: {knowledge['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
