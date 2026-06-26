#!/usr/bin/env python3
"""通用 UI 表面元素提取：弥补 el-form-item / el-button 之外的控件形态.

覆盖：
- el-dropdown-item（行内「更多」菜单）
- h3/h4 区块标题（自定义表单项容器）
- el-tab-pane 静态 label / 外链 tab.config.js 的 tabList
- JS 配置中的 label 列（tableForm* 的 configList）
- script 中 $confirm / MessageBox 确认文案
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# 常见自定义表单项组件（非 el-form-item）
_TABLE_FORM_TAGS = frozenset({
    "tableform", "tableformrequired", "tableformdetails",
    "tableformrequireddetails", "tablelayout", "tablelayoutdetails",
})


def extract_dropdown_actions(parsed: Any) -> list[dict]:
    """提取 el-dropdown-item 文案（视为 menu_action）."""
    actions: list[dict] = []
    tags = parsed.template_tags
    for i, t in enumerate(tags):
        if t.tag != "el-dropdown-item":
            continue
        text = _clean_visible_text(t.text)
        if not text:
            continue
        handler = ""
        for k, v in t.attrs.items():
            if k.startswith("@click") or k.startswith("v-on:click"):
                handler = v
                break
        disabled = t.attrs.get(":disabled", t.attrs.get("disabled", ""))
        v_if = t.attrs.get("v-if", t.attrs.get("v-show", ""))
        in_dropdown = "el-dropdown" in t.parent_chain
        actions.append({
            "text": text,
            "tag": "el-dropdown-item",
            "handler": handler,
            "handler_method": _extract_method_from_handler(handler),
            "disabled_when": disabled,
            "v_if": v_if,
            "in_dropdown": in_dropdown,
            "selector_hint_unverified": f"text={text}",
        })
    return actions


def extract_section_headings(parsed: Any) -> list[dict]:
    """h2/h3/h4 等区块标题 → section 类型字段（用于 Tab 内非标准表单）."""
    fields: list[dict] = []
    seen: set[str] = set()
    for t in parsed.template_tags:
        if t.tag not in ("h2", "h3", "h4"):
            continue
        label = _clean_visible_text(t.text)
        if not label or label in seen:
            continue
        seen.add(label)
        v_if = t.attrs.get("v-if", t.attrs.get("v-show", ""))
        fields.append({
            "label": label,
            "type": "section",
            "required": False,
            "v_if": v_if,
            "label_source": "heading",
            "selector_hint_unverified": f"role=heading[name='{label}']",
        })
    return fields


def extract_checkbox_labels(parsed: Any) -> list[dict]:
    """el-checkbox 可见文案 → toggle 类型."""
    fields: list[dict] = []
    seen: set[str] = set()
    for t in parsed.template_tags:
        if t.tag != "el-checkbox":
            continue
        label = _clean_visible_text(t.text)
        if not label or label in seen:
            continue
        seen.add(label)
        fields.append({
            "label": label,
            "type": "toggle",
            "required": False,
            "v_model": t.attrs.get("v-model", t.attrs.get(":model", "")),
            "disabled_when": t.attrs.get(":disabled", t.attrs.get("disabled", "")),
            "label_source": "checkbox",
        })
    return fields


def extract_static_tab_panes(parsed: Any) -> list[dict]:
    """模板内静态 el-tab-pane 的 label/name."""
    tabs: list[dict] = []
    seen: set[str] = set()
    for t in parsed.template_tags:
        if t.tag != "el-tab-pane":
            continue
        label = t.attrs.get("label", "")
        name = t.attrs.get("name", "")
        lazy = t.attrs.get(":lazy", t.attrs.get("lazy", ""))
        if not label and not name:
            continue
        key = label or name
        if key in seen:
            continue
        seen.add(key)
        entry: dict = {"label": label or name, "name": name or label}
        if lazy:
            entry["lazy"] = True
        tabs.append(entry)
    return tabs


def extract_confirm_dialogs(parsed: Any) -> list[dict]:
    """从 script 提取 $confirm / MessageBox 文案."""
    raw = getattr(parsed, "raw_script", "") or ""
    if not raw:
        return []
    dialogs: list[dict] = []
    seen: set[str] = set()
    # this.$confirm("msg", "title", { confirmButtonText: "确定" })
    pattern = re.compile(
        r"""\$confirm\s*\(\s*"""
        r"""["'`]([^"'`]+)["'`]"""
        r"""(?:\s*,\s*["'`]([^"'`]*?)["'`])?"""
        r"""(?:\s*,\s*\{([^}]*)\})?""",
        re.DOTALL,
    )
    for m in pattern.finditer(raw):
        msg = m.group(1).strip()
        title = (m.group(2) or "提示").strip()
        opts = m.group(3) or ""
        confirm_btn = _extract_option_string(opts, "confirmButtonText") or "确定"
        cancel_btn = _extract_option_string(opts, "cancelButtonText") or "取消"
        key = msg[:80]
        if key in seen:
            continue
        seen.add(key)
        dialogs.append({
            "message": msg[:200],
            "title": title[:80],
            "confirm_button": confirm_btn,
            "cancel_button": cancel_btn,
            "trigger_hint": "script:$confirm",
        })
    return dialogs


def resolve_import_path(from_path: str, vue_file: Path, repo: Path) -> Path | None:
    """将 vue script import 路径解析为仓库内文件."""
    fp = from_path.strip().strip("'\"")
    if fp.startswith("@/"):
        candidate = repo / "src" / fp[2:]
    elif fp.startswith("."):
        candidate = (vue_file.parent / fp).resolve()
    else:
        return None
    for suffix in ("", ".js", ".ts", ".vue"):
        p = Path(str(candidate) + suffix)
        if p.is_file():
            return p
    return None


def parse_js_label_exports(js_content: str) -> dict[str, list[dict]]:
    """从 JS 文件提取 export const X = [{ label: '...' }, ...] 中的 label 条目."""
    result: dict[str, list[dict]] = {}
    # export const tabList = [ ... ];
    blocks = re.finditer(
        r"export\s+const\s+(\w+)\s*=\s*\[",
        js_content,
    )
    for bm in blocks:
        name = bm.group(1)
        start = bm.end() - 1
        chunk = _extract_balanced_bracket(js_content, start)
        if not chunk:
            continue
        entries: list[dict] = []
        # tabList: label + name
        if name.lower().endswith("list") or "tab" in name.lower():
            for lm in re.finditer(
                r"label\s*:\s*['\"]([^'\"]+)['\"]",
                chunk,
            ):
                entries.append({"label": lm.group(1), "from_export": name})
            for nm in re.finditer(
                r"name\s*:\s*['\"]([^'\"]+)['\"]",
                chunk,
            ):
                # 仅 Tab 配置：name 常为组件名
                val = nm.group(1)
                if val.startswith("Tab") or val.startswith("tab"):
                    entries.append({"name": val, "from_export": name})
        else:
            for lm in re.finditer(
                r"label\s*:\s*['\"]([^'\"]+)['\"]",
                chunk,
            ):
                entries.append({"label": lm.group(1), "from_export": name})
        if entries:
            result[name] = entries
    return result


def extract_config_fields_from_imports(
    parsed: Any,
    vue_file: Path,
    repo: Path,
) -> list[dict]:
    """解析 import 的 .js 配置（如 tab.config.js）中的 label 列."""
    fields: list[dict] = []
    seen: set[str] = set()
    for imp in getattr(parsed, "script_imports", []) or []:
        fp = imp.from_path
        if not fp:
            continue
        is_config = (
            fp.endswith(".js")
            or fp.endswith(".ts")
            or "config" in fp.lower()
            or any(
                x in (imp.named_items or [])
                for x in ("allCloumnList", "funcCloumnList", "tabList")
            )
        )
        if not is_config:
            continue
        resolved = resolve_import_path(fp, vue_file, repo)
        if not resolved:
            continue
        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError:
            continue
        exports = parse_js_label_exports(content)
        # 仅解析本 vue 文件实际 import 的 export，避免整文件上千 label 灌入
        import_names: list[str] = list(imp.named_items or [])
        if imp.name and imp.name not in import_names:
            import_names.append(imp.name)
        if not import_names:
            import_names = [
                n for n in exports
                if "list" in n.lower() or "column" in n.lower()
            ][:4]
        for export_name in import_names:
            entries = exports.get(export_name, [])
            for ent in entries:
                label = ent.get("label", "")
                if not label or label in seen:
                    continue
                seen.add(label)
                fields.append({
                    "label": label,
                    "type": "config_column",
                    "required": False,
                    "label_source": f"js:{export_name}",
                    "config_file": str(
                        resolved.relative_to(repo.resolve())
                    ).replace("\\", "/"),
                })
    return fields


def extract_page_tabs_from_imports(
    parsed: Any,
    vue_file: Path,
    repo: Path,
) -> list[dict]:
    """从 tabList 等 export 解析页面级 Tab（planDetail 动态 Tab）."""
    tabs: list[dict] = []
    seen: set[str] = set()
    for imp in getattr(parsed, "script_imports", []) or []:
        wants = (
            imp.name == "tabList"
            or "tabList" in (imp.named_items or [])
            or "tab.config" in (imp.from_path or "").lower()
        )
        if not wants:
            continue
        resolved = resolve_import_path(imp.from_path, vue_file, repo)
        if not resolved:
            continue
        try:
            content = resolved.read_text(encoding="utf-8")
        except OSError:
            continue
        exports = parse_js_label_exports(content)
        tab_entries = exports.get("tabList", [])
        for ent in tab_entries:
            label = ent.get("label", "")
            if not label or label in seen:
                continue
            seen.add(label)
            tabs.append({
                "label": label,
                "name": ent.get("name", ""),
                "source": "tabList",
                "config_file": str(
                    resolved.relative_to(repo.resolve())
                ).replace("\\", "/"),
                "lazy": True,
            })
    return tabs


def detect_table_form_usage(parsed: Any) -> list[str]:
    """记录使用了自定义表格表单组件（提示需结合 config 字段）."""
    found: list[str] = []
    for t in parsed.template_tags:
        tag_lower = t.tag.lower()
        if tag_lower in _TABLE_FORM_TAGS and t.tag not in found:
            found.append(t.tag)
    return found


def enrich_component_knowledge(
    parsed: Any,
    knowledge: dict,
    repo: Path | None = None,
) -> dict:
    """合并通用 UI 表面信息到 component knowledge dict."""
    vue_path = Path(getattr(parsed, "file_path", "") or "")
    repo_path = repo or Path(".")

    dropdowns = extract_dropdown_actions(parsed)
    sections = extract_section_headings(parsed)
    checkboxes = extract_checkbox_labels(parsed)
    static_tabs = extract_static_tab_panes(parsed)
    confirms = extract_confirm_dialogs(parsed)
    table_forms = detect_table_form_usage(parsed)

    config_fields: list[dict] = []
    page_tabs: list[dict] = []
    if repo and vue_path.name:
        abs_vue = repo_path / vue_path if not vue_path.is_absolute() else vue_path
        if abs_vue.is_file():
            config_fields = extract_config_fields_from_imports(
                parsed, abs_vue, repo_path,
            )
            page_tabs = extract_page_tabs_from_imports(
                parsed, abs_vue, repo_path,
            )

    # 合并 form_fields
    all_fields = list(knowledge.get("form_fields") or [])
    for batch in (sections, checkboxes, config_fields):
        all_fields.extend(batch)
    if all_fields:
        knowledge["form_fields"] = all_fields

    # 合并 buttons（dropdown 作为 menu_action）
    all_buttons = list(knowledge.get("buttons") or [])
    for d in dropdowns:
        entry = dict(d)
        entry["ui_role"] = "menu_action"
        all_buttons.append(entry)
    if all_buttons:
        knowledge["buttons"] = all_buttons

    if static_tabs or page_tabs:
        knowledge["page_tabs"] = static_tabs + page_tabs
    if confirms:
        knowledge["confirm_dialogs"] = confirms
    if table_forms:
        knowledge["custom_form_components"] = table_forms

    warnings = list(knowledge.get("warnings") or [])
    if table_forms and not config_fields:
        warnings.append(
            f"检测到自定义表单项组件 {table_forms}，但未从 import 解析到 "
            f"config 列 label；请确认是否存在外部 .js 配置"
        )
    if page_tabs:
        warnings.append(
            f"页面 Tab 来自 JS 配置（共 {len(page_tabs)} 个），"
            f"自动化需先 click Tab（lazy 加载）再操作 Tab 内字段"
        )
    knowledge["warnings"] = warnings
    return knowledge


def _clean_visible_text(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t


def _extract_method_from_handler(handler: str) -> str:
    if not handler:
        return ""
    m = re.match(r"""^\s*(\w+)""", handler)
    return m.group(1) if m else ""


def _extract_option_string(opts: str, key: str) -> str:
    m = re.search(rf"""{key}\s*:\s*['"]([^'"]+)['"]""", opts)
    return m.group(1) if m else ""


def _extract_balanced_bracket(text: str, start: int) -> str:
    """从 text[start]=='[' 起提取平衡方括号段."""
    if start >= len(text) or text[start] != "[":
        return ""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""
