#!/usr/bin/env python3
"""Vue 2 SFC（Single File Component）解析器.

设计原则：
- 用标准库 html.parser（无新依赖）解析 <template> 部分
- 用正则 + 简单文本扫描解析 <script> 部分
- 输出原始 AST-like 数据结构，由 extractors 二次加工
- 跨平台（pathlib + sys.platform 守卫）

输入：
- vue 文件路径

输出：
- ParsedComponent：含 raw template tags、script imports、methods 名等
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


# ──────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────

@dataclass
class TemplateTag:
    """template 中一个标签的扁平记录."""
    tag: str  # 标签名（如 el-input、el-button、planDetail）
    attrs: dict[str, str] = field(default_factory=dict)  # 属性 key→value
    text: str = ""  # 标签内 text 内容（去除子标签后的纯文本，简化处理）
    parent_chain: list[str] = field(default_factory=list)  # 父标签链
    line: int = 0  # 起始行号


@dataclass
class ScriptImport:
    name: str  # 导入名（默认导入名 / 命名空间名）
    from_path: str  # from 'xxx'
    is_namespace: bool = False  # import * as X
    is_named: bool = False  # import { x, y }
    named_items: list[str] = field(default_factory=list)


@dataclass
class ParsedComponent:
    file_path: str  # 相对 repo 的路径
    template_tags: list[TemplateTag] = field(default_factory=list)
    script_imports: list[ScriptImport] = field(default_factory=list)
    method_names: list[str] = field(default_factory=list)
    data_keys: list[str] = field(default_factory=list)
    has_rules: bool = False  # data 里有 rules 字段
    rules_raw: str = ""  # rules 字段原始内容（用于 form_extractor 提取 required）
    component_imports: list[str] = field(default_factory=list)  # 子组件名（被 components 引用）
    raw_script: str = ""  # 完整 script 部分原文（供 fallback 使用）

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "template_tags": [
                {"tag": t.tag, "attrs": t.attrs, "text": t.text,
                 "parent_chain": t.parent_chain, "line": t.line}
                for t in self.template_tags
            ],
            "script_imports": [asdict(i) for i in self.script_imports],
            "method_names": self.method_names,
            "data_keys": self.data_keys,
            "has_rules": self.has_rules,
            "component_imports": self.component_imports,
        }


# ──────────────────────────────────────────────────────────────
# SFC 拆分（template / script / style）
# ──────────────────────────────────────────────────────────────

_TEMPLATE_OPEN_RE = re.compile(
    r"<template\b[^>]*>", re.IGNORECASE,
)
_TEMPLATE_CLOSE_RE = re.compile(
    r"</template\s*>", re.IGNORECASE,
)
_SCRIPT_RE = re.compile(
    r"<script[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE,
)


def split_sfc(content: str) -> tuple[str, str]:
    """拆分 vue SFC 为 (template, script) 两部分.

    BUG #7 修复：vue 2.6+ 的命名插槽语法（如 `<template #title>`、
    `<template v-slot:label>`）会让原"非贪婪正则匹配"提前在第一个内层
    `</template>` 处截断 → 顶层 template 内容大量丢失（实证：utp-vue
    的 CreateTestPlanImplementReview/index.vue 199 行模板被截到 1878 字符，
    el-form-item 全丢）。

    新实现：用 tag-depth 跟踪正确找到顶层 `</template>` 闭合：
      1. 找文件顶层第一个 `<template ...>`（vue SFC 一定是顶层 root tag）
      2. 从该位置逐字符扫描，跟踪 `<template>` / `</template>` 配对
      3. depth 回到 0 时找到顶层闭合，截取中间内容
      4. 跳过字符串字面量内的 `<template>` 标记（保险起见）
      5. 跳过 HTML 注释 `<!-- ... -->`
    """
    open_match = _TEMPLATE_OPEN_RE.search(content)
    if not open_match:
        template = ""
    else:
        body_start = open_match.end()
        n = len(content)
        depth = 1
        i = body_start
        in_string: Optional[str] = None
        body_end = -1
        while i < n and depth > 0:
            c = content[i]
            # 字符串字面量（template 内的属性值如 placeholder="..."）
            if in_string:
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == in_string:
                    in_string = None
                i += 1
                continue
            if c in ("'", '"'):
                in_string = c
                i += 1
                continue
            # HTML 注释 <!-- ... -->
            if (c == "<" and i + 3 < n
                    and content[i:i + 4] == "<!--"):
                end_pos = content.find("-->", i + 4)
                if end_pos == -1:
                    break
                i = end_pos + 3
                continue
            # </template> 闭合
            if c == "<" and i + 1 < n and content[i + 1] == "/":
                close_match = _TEMPLATE_CLOSE_RE.match(content, i)
                if close_match:
                    depth -= 1
                    if depth == 0:
                        body_end = i
                        break
                    i = close_match.end()
                    continue
            # <template ...> 嵌套打开
            if c == "<" and i + 8 < n:
                open_inner = _TEMPLATE_OPEN_RE.match(content, i)
                if open_inner:
                    depth += 1
                    i = open_inner.end()
                    continue
            i += 1
        template = content[body_start:body_end] if body_end > 0 else ""
    script_match = _SCRIPT_RE.search(content)
    script = script_match.group(1) if script_match else ""
    return template, script


# ──────────────────────────────────────────────────────────────
# template 解析（基于 html.parser）
# ──────────────────────────────────────────────────────────────

class _VueTemplateParser(HTMLParser):
    """容错 HTML/Vue template 解析器.

    设计：
    - 收集所有 starttag（含 v-/@/: 属性）
    - 维护父标签栈，记录 parent_chain
    - 简化处理：text 仅记录每个标签直接 children 里的文本（不递归）
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[TemplateTag] = []
        self._stack: list[TemplateTag] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attr_dict = {}
        for k, v in attrs:
            if v is None:
                v = ""
            attr_dict[k] = v
        parent_chain = [t.tag for t in self._stack]
        line = (self.getpos() or (0, 0))[0]
        node = TemplateTag(
            tag=tag, attrs=attr_dict, parent_chain=parent_chain, line=line,
        )
        self.tags.append(node)
        # 自闭合标签（input/img/br 等）不入栈；vue 自定义组件可能用 /> 关闭
        # html.parser 对 <x /> 也走 handle_starttag + 不会有 endtag
        # 简化：所有标签都入栈，end 时 pop
        self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        # 弹栈到匹配的 tag（容错：跳过未配对的）
        while self._stack:
            top = self._stack.pop()
            if top.tag == tag:
                break

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        attr_dict = {}
        for k, v in attrs:
            if v is None:
                v = ""
            attr_dict[k] = v
        parent_chain = [t.tag for t in self._stack]
        line = (self.getpos() or (0, 0))[0]
        node = TemplateTag(
            tag=tag, attrs=attr_dict, parent_chain=parent_chain, line=line,
        )
        self.tags.append(node)

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text and self._stack:
            # 累加到当前栈顶标签的 text 字段
            top = self._stack[-1]
            if top.text:
                top.text += " " + text
            else:
                top.text = text


def parse_template(template_str: str) -> list[TemplateTag]:
    """解析 template 部分，返回扁平化标签列表."""
    if not template_str.strip():
        return []
    parser = _VueTemplateParser()
    try:
        parser.feed(template_str)
        parser.close()
    except Exception:  # noqa: BLE001
        # html.parser 对某些 vue 模板可能容错失败，返回已解析部分
        pass
    return parser.tags


# ──────────────────────────────────────────────────────────────
# script 解析
# ──────────────────────────────────────────────────────────────

# import xxx from 'yyy'
_IMPORT_DEFAULT_RE = re.compile(
    r"""import\s+(\w+)\s+from\s+['"]([^'"]+)['"]"""
)
# import * as xxx from 'yyy'
_IMPORT_NAMESPACE_RE = re.compile(
    r"""import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"]"""
)
# import { a, b, c } from 'yyy'
_IMPORT_NAMED_RE = re.compile(
    r"""import\s+\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]"""
)
# methods: { foo() {...}, async bar() {...}, foo: function() {...} }
_METHODS_BLOCK_RE = re.compile(
    r"""methods\s*:\s*\{""", re.MULTILINE,
)
# data() { return { ... } }
_DATA_BLOCK_RE = re.compile(
    r"""(?:data\s*\(\s*\)\s*\{|data\s*:\s*function\s*\(\s*\)\s*\{)""",
)
# components: { Foo, Bar: BarComponent }
_COMPONENTS_BLOCK_RE = re.compile(
    r"""components\s*:\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}""",
)


def _strip_js_comments(code: str) -> str:
    """剥离 // 行注释 + /* */ 块注释，保留字符串字面量内容.

    用于 _extract_data_keys 等对源码做"顶层 key 分割"的场景：注释会
    干扰 segment 开头的 key 正则匹配（如 `\\n// 附件信息\\nrules:` 会让
    re.match `^['"]?(\\w+)\\s*:` 失败）。
    """
    out = []
    i, n = 0, len(code)
    in_string: Optional[str] = None
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
                # 行注释：跳到换行（保留换行本身，不破坏行号/分隔）
                j = code.find("\n", i)
                if j == -1:
                    break
                i = j
                continue
            if nxt == "*":
                # 块注释：跳到 */
                j = code.find("*/", i + 2)
                if j == -1:
                    break
                i = j + 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _balanced_block(code: str, start_idx: int) -> tuple[int, int]:
    """从 start_idx 找下一个 { 后做括号配对，返回 (开始内容 idx, 结束 idx)."""
    n = len(code)
    i = start_idx
    while i < n and code[i] != "{":
        i += 1
    if i >= n:
        return -1, -1
    depth = 1
    j = i + 1
    in_string: Optional[str] = None
    while j < n and depth > 0:
        c = code[j]
        if in_string:
            if c == "\\" and j + 1 < n:
                j += 2
                continue
            if c == in_string:
                in_string = None
            j += 1
            continue
        if c in ("'", '"', "`"):
            in_string = c
            j += 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1, j
        j += 1
    return -1, -1


_RESERVED_KEYWORDS = {
    "if", "for", "while", "return", "function", "async", "await",
    "switch", "case", "default", "try", "catch", "finally", "throw",
    "do", "in", "of", "let", "const", "var", "new", "delete", "typeof",
    "void", "instanceof", "this",
}


def _extract_method_names(script: str) -> list[str]:
    """从 methods: { ... } 块中只在顶层提取方法定义名.

    严格规则：
    - 在 methods 体内跟踪 brace/paren/bracket depth
    - depth == 0 时识别 `name(` 或 `async name(` 或 `name: function(` 或
      `name: (...)=> ` 等"方法定义"模式
    - 跳过函数体内的调用（如 Promise.resolve / arr.map）
    """
    names: list[str] = []
    in_string: Optional[str]
    for m in _METHODS_BLOCK_RE.finditer(script):
        start, end = _balanced_block(script, m.end() - 1)
        if start < 0:
            continue
        body = script[start:end]
        n = len(body)
        i = 0
        depth_brace = 0
        depth_paren = 0
        depth_bracket = 0
        in_string = None
        in_line_comment = False
        in_block_comment = False
        # 顶层方法扫描：在 depth_brace == 0 时识别 ident(
        while i < n:
            c = body[i]
            # 字符串
            if in_string:
                if c == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c == in_string:
                    in_string = None
                i += 1
                continue
            # 行注释
            if in_line_comment:
                if c == "\n":
                    in_line_comment = False
                i += 1
                continue
            # 块注释
            if in_block_comment:
                if c == "*" and i + 1 < n and body[i + 1] == "/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            # 进入字符串
            if c in ("'", '"', "`"):
                in_string = c
                i += 1
                continue
            # 进入注释
            if c == "/" and i + 1 < n:
                if body[i + 1] == "/":
                    in_line_comment = True
                    i += 2
                    continue
                if body[i + 1] == "*":
                    in_block_comment = True
                    i += 2
                    continue
            # 括号深度
            if c == "(":
                depth_paren += 1
                i += 1
                continue
            if c == ")":
                depth_paren -= 1
                i += 1
                continue
            if c == "[":
                depth_bracket += 1
                i += 1
                continue
            if c == "]":
                depth_bracket -= 1
                i += 1
                continue
            if c == "{":
                depth_brace += 1
                i += 1
                continue
            if c == "}":
                depth_brace -= 1
                i += 1
                continue
            # 仅在顶层（depth_brace==0、depth_paren==0、depth_bracket==0）识别方法名
            if (depth_brace == 0 and depth_paren == 0
                    and depth_bracket == 0 and (c.isalpha() or c == "_")):
                # 抓 identifier
                j = i
                while j < n and (body[j].isalnum() or body[j] == "_"):
                    j += 1
                ident = body[i:j]
                # 跳过空白
                k = j
                while k < n and body[k] in " \t":
                    k += 1
                if (ident not in _RESERVED_KEYWORDS
                        and k < n and body[k] in ("(", ":")):
                    # name( ... )
                    if body[k] == "(":
                        # 跳过参数列表
                        depth = 1
                        kk = k + 1
                        while kk < n and depth > 0:
                            cc = body[kk]
                            if cc == "(":
                                depth += 1
                            elif cc == ")":
                                depth -= 1
                            kk += 1
                        # 后面应该是 { 表示是方法定义
                        kkk = kk
                        while kkk < n and body[kkk] in " \t\r\n":
                            kkk += 1
                        if kkk < n and body[kkk] == "{":
                            if ident not in names:
                                names.append(ident)
                            i = kkk
                            continue
                    # name: function( ... ) 或 name: () => / name: (...) =>
                    if body[k] == ":":
                        rest = body[k + 1:k + 100].lstrip()
                        if rest.startswith("function") or "=>" in rest[:80]:
                            # 简单判断：跟着 function 或 是箭头函数
                            # async 前缀 — name: async () =>
                            if (rest.startswith("function")
                                or re.match(r"""(async\s+)?\(?[\w,\s]*\)?\s*=>""",
                                            rest)):
                                if ident not in names:
                                    names.append(ident)
                                i = k + 1
                                continue
                # async name(  形式
                if ident == "async":
                    # 后面应紧跟 identifier(
                    rest = body[k:k + 80]
                    am = re.match(r"""(\w+)\s*\(""", rest)
                    if am and am.group(1) not in _RESERVED_KEYWORDS:
                        if am.group(1) not in names:
                            names.append(am.group(1))
                # 整体推进
                i = j
                continue
            i += 1
    return names


def _extract_data_keys(script: str) -> tuple[list[str], bool, str]:
    """从 data() { return { ... } } 中提取顶层字段名 + rules 块原文."""
    keys: list[str] = []
    has_rules = False
    rules_raw = ""
    m = _DATA_BLOCK_RE.search(script)
    if not m:
        return keys, has_rules, rules_raw
    start, end = _balanced_block(script, m.end() - 1)
    if start < 0:
        return keys, has_rules, rules_raw
    body = script[start:end]
    # 找 return { ... }
    return_m = re.search(r"""return\s*\{""", body)
    if not return_m:
        return keys, has_rules, rules_raw
    rs, re_ = _balanced_block(body, return_m.end() - 1)
    if rs < 0:
        return keys, has_rules, rules_raw
    return_body = body[rs:re_]
    # BUG #6 修复：剥离行/块注释，否则带前导注释的 key（如 `// 附件信息\nrules: {...}`）
    # 会被 `^['"]?(\w+)['"]?\s*:` 正则匹配失败而跳过
    return_body = _strip_js_comments(return_body)
    # 简化：抓顶层 key:（仅识别非缩进或定 1 层缩进的）
    # 实用做法：用平衡括号 + 简易分隔扫描
    depth_paren = 0
    depth_brace = 0
    depth_bracket = 0
    in_string: Optional[str] = None
    n = len(return_body)
    i = 0
    last_top_pos = 0
    top_segments: list[str] = []
    while i < n:
        c = return_body[i]
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
        if c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif c == "[":
            depth_bracket += 1
        elif c == "]":
            depth_bracket -= 1
        elif (c == "," and depth_paren == 0
              and depth_brace == 0 and depth_bracket == 0):
            top_segments.append(return_body[last_top_pos:i])
            last_top_pos = i + 1
        i += 1
    if last_top_pos < n:
        top_segments.append(return_body[last_top_pos:])
    for seg in top_segments:
        seg = seg.strip()
        if not seg:
            continue
        # 匹配 'name', "name", name 后面跟 :
        km = re.match(r"""^['"]?(\w+)['"]?\s*:""", seg)
        if km:
            key = km.group(1)
            keys.append(key)
            if key == "rules":
                has_rules = True
                rules_raw = seg[km.end():].strip()
        # 不带值的简写 { foo }
        elif re.match(r"""^\w+\s*$""", seg) or re.match(r"""^\w+\s*,?$""", seg):
            keys.append(seg.strip(","))
    return keys, has_rules, rules_raw


def _extract_component_names(script: str) -> list[str]:
    """从 components: { Foo, Bar } 中提取子组件名."""
    names: list[str] = []
    m = _COMPONENTS_BLOCK_RE.search(script)
    if not m:
        return names
    body = m.group(1)
    # 简化：抓 \w+ ，可以是 "Foo" 也可以是 "Foo: Bar"
    for mm in re.finditer(r"""(\w+)\s*(?::\s*\w+)?""", body):
        name = mm.group(1)
        if name and name not in names:
            names.append(name)
    return names


def parse_script(script: str) -> tuple[list[ScriptImport], list[str], list[str], bool, str, list[str]]:
    """解析 script 部分，返回:
    (imports, method_names, data_keys, has_rules, rules_raw, component_imports)
    """
    imports: list[ScriptImport] = []
    seen_imports: set[tuple[str, str]] = set()
    # 命名空间 import (优先匹配，后续 default 会跳过)
    for m in _IMPORT_NAMESPACE_RE.finditer(script):
        key = (m.group(1), m.group(2))
        if key in seen_imports:
            continue
        seen_imports.add(key)
        imports.append(ScriptImport(
            name=m.group(1), from_path=m.group(2), is_namespace=True,
        ))
    # 默认 import
    for m in _IMPORT_DEFAULT_RE.finditer(script):
        # 跳过命名空间形式（前面已含 *）
        snippet = script[max(0, m.start() - 30):m.start()]
        if "* as" in snippet[-15:]:
            continue
        # 跳过命名 import 形式 "import { x } from"
        if "{" in script[m.start():m.start() + 30]:
            continue
        key = (m.group(1), m.group(2))
        if key in seen_imports:
            continue
        seen_imports.add(key)
        imports.append(ScriptImport(name=m.group(1), from_path=m.group(2)))
    # 命名 import { a, b }
    for m in _IMPORT_NAMED_RE.finditer(script):
        items = [it.strip().split(" as ")[-1].strip()
                 for it in m.group(1).split(",") if it.strip()]
        path = m.group(2)
        # 用第一个 named item 作为 representative name
        repr_name = items[0] if items else "_"
        key = (repr_name, path)
        if key in seen_imports:
            continue
        seen_imports.add(key)
        imports.append(ScriptImport(
            name=repr_name, from_path=path, is_named=True, named_items=items,
        ))
    methods = _extract_method_names(script)
    data_keys, has_rules, rules_raw = _extract_data_keys(script)
    components = _extract_component_names(script)
    return imports, methods, data_keys, has_rules, rules_raw, components


# ──────────────────────────────────────────────────────────────
# 主接口
# ──────────────────────────────────────────────────────────────

def parse_vue_component(file_path: Path,
                        repo_path: Optional[Path] = None) -> ParsedComponent:
    """解析单个 .vue 文件."""
    file_path = Path(file_path)
    if not file_path.exists():
        return ParsedComponent(file_path=str(file_path))
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return ParsedComponent(file_path=str(file_path))
    template, script = split_sfc(content)
    template_tags = parse_template(template)
    imports, methods, data_keys, has_rules, rules_raw, comp_imports = (
        parse_script(script)
    )
    if repo_path:
        try:
            rel_path = str(file_path.resolve().relative_to(
                Path(repo_path).resolve()))
        except ValueError:
            rel_path = str(file_path)
    else:
        rel_path = str(file_path)
    return ParsedComponent(
        file_path=rel_path,
        template_tags=template_tags,
        script_imports=imports,
        method_names=methods,
        data_keys=data_keys,
        has_rules=has_rules,
        rules_raw=rules_raw,
        component_imports=comp_imports,
        raw_script=script,
    )


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Vue 2 SFC 解析器")
    parser.add_argument("--file", required=True, type=Path,
                        help=".vue 文件路径")
    parser.add_argument("--repo", type=Path, default=None,
                        help="项目根目录（用于相对路径输出）")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    parsed = parse_vue_component(args.file, args.repo)
    text = json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"[vue-component-parser] 写入 {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
