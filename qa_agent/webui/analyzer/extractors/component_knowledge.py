#!/usr/bin/env python3
"""框架无关提取器：从 ParsedComponent 中提取 form/button/api/state 信息.

设计：
- 输入：ParsedComponent（来自 vue2_component_parser 或将来的 react_component_parser）
- 输出：标准化字典，作为 frontend_knowledge.json 的 components 节点

支持的提取维度：
- form_fields: el-form-item + el-input/select/textarea/date-picker
- buttons: el-button + a + button (通用)
- api_calls: 从 namespace import 推断（@/api/* 入口）
- state_machine: v-if / v-show 条件
"""
from __future__ import annotations

import re
import sys
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


# Element UI input-类组件（用于推断 field type）
_ELEMENT_INPUT_COMPONENTS = {
    "el-input": "input",
    "el-input-number": "number",
    "el-select": "select",
    "el-cascader": "cascader",
    "el-date-picker": "date-picker",
    "el-time-picker": "time-picker",
    "el-checkbox": "checkbox",
    "el-checkbox-group": "checkbox-group",
    "el-radio": "radio",
    "el-radio-group": "radio-group",
    "el-switch": "switch",
    "el-rate": "rate",
    "el-slider": "slider",
    "el-upload": "upload",
    "el-color-picker": "color-picker",
    "el-autocomplete": "autocomplete",
    "el-transfer": "transfer",
}


def extract_form_fields(parsed: Any) -> list[dict]:
    """从 parsed component 中提取 form 字段.

    策略：
    - 找所有 el-form-item（含 label / prop / v-if）
    - 在其 children 链中找第一个 input-类组件（el-input / el-select / ...）
    - 自定义组件（如 IterationSelect）保留组件名作为 type
    - 解析 rules 块的 required（朴素正则匹配）
    """
    tags = parsed.template_tags
    rules_raw = parsed.rules_raw or ""
    # 解析 rules 中 required: true 的 prop 名
    required_props = _extract_required_props_from_rules(rules_raw)

    fields: list[dict] = []
    # 找所有 el-form-item，其 parent_chain 包含 el-form
    for i, t in enumerate(tags):
        if t.tag != "el-form-item":
            continue
        if "el-form" not in t.parent_chain:
            continue
        label = t.attrs.get("label", "")
        prop = t.attrs.get("prop", "")
        v_if = t.attrs.get("v-if", "")
        v_show = t.attrs.get("v-show", "")
        label_source = "attribute" if label else ""
        # 找直接子标签（parent_chain 末尾是 el-form-item 的）
        # 简化：在 i+1 之后找直到下一个同级 el-form-item
        input_tag = None
        input_attrs = {}
        slot_label_text = ""
        for j in range(i + 1, len(tags)):
            child = tags[j]
            # 不在当前 el-form-item 子树内 → break
            if "el-form-item" not in child.parent_chain:
                break
            # 找到下一个 el-form-item 不计入
            if child.tag == "el-form-item":
                break
            # R-P1-1：识别 slot label —— Vue 2.6+ <template #label> /
            # <template v-slot:label> / <template slot="label">
            if not label and child.tag == "template" and _is_label_slot(child.attrs):
                slot_label_text = _collect_slot_text(child, tags, j)
                continue
            # 仅当 parent_chain 包含本 el-form-item 时才算（简化：当前所有都算，
            # 因为我们按 i 顺序往后扫）
            if child.tag in _ELEMENT_INPUT_COMPONENTS or _is_custom_input(child.tag):
                input_tag = child.tag
                input_attrs = child.attrs
                break
        # R-P1-1：当 attrs.label 为空时，使用 slot 提取的 label
        if not label and slot_label_text:
            label = slot_label_text
            label_source = "slot"
        # 类型推断
        if input_tag in _ELEMENT_INPUT_COMPONENTS:
            field_type = _ELEMENT_INPUT_COMPONENTS[input_tag]
            # BUG #3 修复：el-input type="textarea" 应识别为 textarea
            if input_tag == "el-input" and input_attrs.get("type") == "textarea":
                field_type = "textarea"
        elif input_tag:
            field_type = f"custom:{input_tag}"
        else:
            field_type = "unknown"
        # 抽 placeholder / max_length / disabled 等
        placeholder = input_attrs.get("placeholder", "") if input_attrs else ""
        v_model = input_attrs.get("v-model", "") if input_attrs else ""
        max_length = input_attrs.get("maxlength", "") if input_attrs else ""
        # 拼 selector hint（agent 可直接用）
        # BUG #6 修复：标 _unverified 后缀，明确不能直接当 selector 用
        selector_hint = _build_selector_hint(input_tag, label, placeholder, field_type)
        # BUG #4 修复：dialog 上下文 — 任何祖先含 el-dialog/el-drawer 标记
        dialog_context = _detect_dialog_context(t, tags, i)
        fields.append({
            "label": label,
            "label_source": label_source,  # R-P1-1: "attribute" | "slot" | ""
            "prop": prop,
            "type": field_type,
            "required": prop in required_props,
            "placeholder": placeholder,
            "max_length": max_length,
            "v_model": v_model,
            "v_if": v_if,
            "v_show": v_show,
            "dialog_context": dialog_context,
            "selector_hint_unverified": selector_hint,
        })
    return fields


def _is_label_slot(attrs: dict) -> bool:
    """识别一个 <template> 标签是否属于 form-item 的 label slot。

    支持三种 Vue 语法：
      - Vue 2.6+ shorthand:  <template #label>
      - Vue 2.6+ full:       <template v-slot:label>
      - Vue <2.6 legacy:     <template slot="label">

    html.parser 对 `#label` 这种非标准属性会保留键名，值为空字符串。
    """
    if not attrs:
        return False
    # shorthand: 任意键以 # 开头且 == "#label"
    if "#label" in attrs:
        return True
    # v-slot:label / v-slot:label.modifier
    for k in attrs.keys():
        if k.startswith("v-slot:label"):
            return True
    # legacy: slot="label"
    if attrs.get("slot", "") == "label":
        return True
    return False


def _collect_slot_text(slot_tag, all_tags, slot_idx: int) -> str:
    """收集 slot 子树内所有文本节点，拼成 label 字符串。

    策略：
      - 收集 slot template 自身 + 所有其子标签（parent_chain 含 'template'）的 text
      - 装饰用的 *、＊、✱、★ 等必填标记字符在最后一步统一清理（不靠 tag 黑名单）
      - 折叠空白
    """
    parts: list[str] = []
    if slot_tag.text:
        parts.append(slot_tag.text)
    n = len(all_tags)
    for k in range(slot_idx + 1, n):
        child = all_tags[k]
        if "template" not in child.parent_chain:
            break
        if child.text:
            parts.append(child.text)
    raw = " ".join(parts).strip()
    cleaned = re.sub(r"[\*\u2731\uff0a\u2605]+", "", raw).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _detect_dialog_context(form_item_tag, all_tags, idx) -> dict:
    """检测 form-item 是否在 dialog/drawer/popover 内（影响可见性）.

    返回 {"in_dialog": bool, "dialog_tag": str, "visibility_binding": str}。
    visibility_binding 是 :visible.sync / v-model 等 dialog 显示控制变量。
    """
    parent_chain = form_item_tag.parent_chain or []
    dialog_tags = {"el-dialog", "el-drawer", "el-popover", "el-popconfirm"}
    in_dialog_tag = next((t for t in parent_chain if t in dialog_tags), "")
    if not in_dialog_tag:
        return {"in_dialog": False, "dialog_tag": "", "visibility_binding": ""}
    # 找祖先 dialog 标签的 :visible.sync 或 v-model 属性
    visibility = ""
    for t in all_tags[:idx]:
        if t.tag == in_dialog_tag:
            visibility = (
                t.attrs.get(":visible.sync")
                or t.attrs.get(":visible")
                or t.attrs.get("v-model")
                or t.attrs.get("v-model:visible")
                or ""
            )
            break
    return {
        "in_dialog": True,
        "dialog_tag": in_dialog_tag,
        "visibility_binding": visibility,
    }


def _is_custom_input(tag: str) -> bool:
    """识别自定义 input 类组件（约定：包含 Select / Picker / Input 等）."""
    if not tag or tag.startswith("el-"):
        return False
    pattern = re.compile(
        r"""(?i)(select|picker|input|upload|autocomplete|transfer|cascader|radio|checkbox)"""
    )
    return bool(pattern.search(tag))


def _extract_required_props_from_rules(rules_raw: str) -> set[str]:
    """从 rules: { name: [{required: true, ...}] } 文本中提取 required 字段名.

    朴素策略：找形如 `name: [...required...]` 的项。
    """
    if not rules_raw:
        return set()
    required: set[str] = set()
    # 匹配 (name) : [ {含 required: true} ]
    # 简化：找 'key: [' 然后看其 array 内是否含 required: true
    pattern = re.compile(
        r"""['"]?(\w+)['"]?\s*:\s*\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]""",
        re.MULTILINE,
    )
    for m in pattern.finditer(rules_raw):
        name = m.group(1)
        body = m.group(2)
        if re.search(r"""required\s*:\s*true""", body):
            required.add(name)
    return required


def is_rules_external_reference(rules_raw: str) -> bool:
    """检测 rules 字段是否是外部 import 的对象引用（无法静态分析 required）.

    例如 `rules: planRules`、`rules: this.$rules`、`rules: createRules()`。
    判据：rules_raw 不含 `[` 也不含 `{`（说明不是 inline 数组/对象）。
    """
    if not rules_raw:
        return False
    cleaned = rules_raw.strip().rstrip(",").rstrip()
    return "[" not in cleaned and "{" not in cleaned


def _build_selector_hint(input_tag: str, label: str, placeholder: str,
                         field_type: str = "") -> str:
    """根据输入组件类型 + label/placeholder 生成 Playwright selector 推断.

    ⚠️ 重要：这是【未经页面验证】的推断 selector，count 可能 > 1。
    case-analyst 应仅作为 hint 给 smart_action 的 anchor 匹配做参考，
    不能直接当唯一 selector 使用（详见 SKILL.md 反模式 §3 索引 xpath 脆弱）。
    """
    if not input_tag:
        return ""
    # BUG #3 修复：textarea 用 textarea 标签
    primary_html_tag = "textarea" if field_type == "textarea" else "input"
    if placeholder:
        if input_tag in ("el-input", "el-input-number"):
            return f"{primary_html_tag}[placeholder=\"{placeholder}\"]"
        if input_tag == "el-select":
            return (
                f"//div[contains(@class,'el-form-item') and contains(.,'{label}')]"
                f"//input[@placeholder=\"{placeholder}\"]"
            )
        if input_tag == "el-date-picker":
            return f"input[placeholder=\"{placeholder}\"]"
    if label:
        return (
            f"//div[contains(@class,'el-form-item') and contains(.,'{label}')]"
            f"//{primary_html_tag}"
        )
    return ""


# ──────────────────────────────────────────────────────────────
# Buttons
# ──────────────────────────────────────────────────────────────

def extract_buttons(parsed: Any) -> list[dict]:
    """从 template 中提取所有按钮（el-button / button / a tag with @click）."""
    tags = parsed.template_tags
    buttons: list[dict] = []
    for i, t in enumerate(tags):
        if t.tag in ("el-button", "button") or (
                t.tag == "a" and any(k.startswith("@click") for k in t.attrs)):
            text = t.text.strip()
            handler = ""
            for k, v in t.attrs.items():
                if k.startswith("@click") or k.startswith("v-on:click"):
                    handler = v
                    break
            disabled = t.attrs.get("disabled", t.attrs.get(":disabled", ""))
            loading = t.attrs.get(":loading", t.attrs.get("loading", ""))
            type_ = t.attrs.get("type", "")
            size = t.attrs.get("size", "")
            v_if = t.attrs.get("v-if", "")
            # BUG #4 修复：button 也补 dialog 上下文
            dialog_context = _detect_dialog_context(t, tags, i)
            buttons.append({
                "text": text,
                "tag": t.tag,
                "handler": handler,
                "handler_method": _extract_method_from_handler(handler),
                "disabled_when": disabled,
                "loading_when": loading,
                "type": type_,
                "size": size,
                "v_if": v_if,
                "dialog_context": dialog_context,
                "selector_hint_unverified": (
                    f"button:has-text('{text}')" if text else ""
                ),
            })
    return buttons


def _extract_method_from_handler(handler: str) -> str:
    """从 @click="handleSave('0')" 中抽出 handleSave 方法名."""
    if not handler:
        return ""
    m = re.match(r"""^\s*(\w+)""", handler)
    return m.group(1) if m else ""


# ──────────────────────────────────────────────────────────────
# API calls
# ──────────────────────────────────────────────────────────────

def extract_api_calls(parsed: Any) -> list[dict]:
    """从 script imports + raw_script 中推断 API 调用.

    策略：
    - import * as XxxAPI from '@/api/yyy' → 候选 API 命名空间
    - import { foo, bar } from '@/api/yyy' → 候选 API 函数
    - 在 raw_script 中搜索 XxxAPI.method( 模式
    """
    api_calls: list[dict] = []
    raw_script = parsed.raw_script or ""
    seen: set[str] = set()
    for imp in parsed.script_imports:
        if "/api/" not in imp.from_path and "api/" not in imp.from_path:
            continue
        if imp.is_namespace:
            # 找 XxxAPI.methodName( 模式
            pattern = re.compile(
                rf"""\b{re.escape(imp.name)}\.(\w+)\s*\("""
            )
            for m in pattern.finditer(raw_script):
                key = (imp.name, m.group(1))
                if key in seen:
                    continue
                seen.add(key)
                api_calls.append({
                    "method_name": m.group(1),
                    "import_namespace": imp.name,
                    "import_from": imp.from_path,
                })
        elif imp.is_named:
            for item in imp.named_items:
                # 找 item( 模式
                pattern = re.compile(rf"""\b{re.escape(item)}\s*\(""")
                if pattern.search(raw_script):
                    key = ("", item)
                    if key in seen:
                        continue
                    seen.add(key)
                    api_calls.append({
                        "method_name": item,
                        "import_namespace": "",
                        "import_from": imp.from_path,
                    })
    return api_calls


# ──────────────────────────────────────────────────────────────
# State machine（v-if / v-show 条件）
# ──────────────────────────────────────────────────────────────

def extract_state_machine(parsed: Any) -> list[dict]:
    """从 v-if/v-show 条件 + 标签内 text 推断状态机."""
    states: list[dict] = []
    seen_conditions: set[str] = set()
    for t in parsed.template_tags:
        v_if = t.attrs.get("v-if") or t.attrs.get("v-show", "")
        if not v_if or v_if in seen_conditions:
            continue
        seen_conditions.add(v_if)
        # 标签 text + 子按钮文本
        affected_text = t.text.strip()
        # 标签类型 + text 描述
        states.append({
            "condition": v_if,
            "affects_tag": t.tag,
            "affects_text": affected_text[:100] if affected_text else "",
            "directive": "v-if" if "v-if" in t.attrs else "v-show",
        })
    return states


# ──────────────────────────────────────────────────────────────
# 主接口
# ──────────────────────────────────────────────────────────────

def extract_component_knowledge(parsed: Any, repo: Any = None) -> dict:
    """主入口：从 ParsedComponent 提取所有维度的测试知识."""
    try:
        from .ui_surface_extractor import enrich_component_knowledge
    except ImportError:
        from extractors.ui_surface_extractor import enrich_component_knowledge  # noqa: E402

    warnings: list[str] = []
    rules_raw = getattr(parsed, "rules_raw", "") or ""
    if is_rules_external_reference(rules_raw):
        warnings.append(
            f"rules 是外部对象引用（{rules_raw[:50]!r}），v0.1 无法静态解析 "
            f"required 字段。所有 form_fields 的 required 都将标 False；"
            f"case-analyst 应通过其他证据（需求文档/UI 探索）补全 required 信息"
        )
    base = {
        "file_path": parsed.file_path,
        "form_fields": extract_form_fields(parsed),
        "buttons": extract_buttons(parsed),
        "api_calls": extract_api_calls(parsed),
        "state_machine": extract_state_machine(parsed),
        "method_names": parsed.method_names,
        "child_components": parsed.component_imports,
        "warnings": warnings,
    }
    repo_path = None
    if repo is not None:
        from pathlib import Path
        repo_path = Path(repo) if not isinstance(repo, Path) else repo
    return enrich_component_knowledge(parsed, base, repo_path)
