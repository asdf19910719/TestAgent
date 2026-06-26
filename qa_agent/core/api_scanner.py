"""
Spring MVC 接口扫描器（backlog A1，借鉴 oec api-scanner 源码模式重写）

设计原则（与 oec 的区别）：
- 不依赖编译产物（JAR/class），只解析 Java 源码（源码模式）
- 正则解析而非完整 AST，零新增重依赖（符合 TestAgent 轻依赖定位）
- 输出对齐现有消费端 enhanced_execute_with_auth.py 期望的 {'apis': [...]} 结构

提取能力：
- @RestController / @Controller 类
- 类级 @RequestMapping 基路径
- 方法级 @GetMapping/@PostMapping/@PutMapping/@DeleteMapping/@PatchMapping/@RequestMapping
- 组合成完整路径 + HTTP 方法 + handler 方法名

限制（源码模式固有）：
- 不解析外部依赖类型的请求体/响应体字段（需 class/JAR 模式才能拿全）
- 复杂 SpEL / 常量路径不展开
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


# HTTP 方法注解 → method 映射
_MAPPING_ANNOTATIONS = {
    'GetMapping': 'GET',
    'PostMapping': 'POST',
    'PutMapping': 'PUT',
    'DeleteMapping': 'DELETE',
    'PatchMapping': 'PATCH',
}

# 类级控制器注解
_CONTROLLER_RE = re.compile(r'@(RestController|Controller)\b')

# 类级 @RequestMapping 基路径
_CLASS_REQUEST_MAPPING_RE = re.compile(
    r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\']'
)

# 方法级映射注解（含路径），如 @GetMapping("/x") / @PostMapping(value="/y")
_METHOD_MAPPING_RE = re.compile(
    r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*'
    r'(?:\(\s*(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']*)["\'])?'
)

# @RequestMapping 方法级（需从 method= 推断 HTTP 动词）
_METHOD_REQUEST_MAPPING_RE = re.compile(
    r'@RequestMapping\s*\(([^)]*)\)'
)

# 方法签名（紧跟注解后的 public/返回类型 方法名(...)）
_METHOD_NAME_RE = re.compile(
    r'(?:public|protected|private)?\s+[\w<>\[\],\s.?]+?\s+(\w+)\s*\('
)


def _normalize_path(base: str, sub: str) -> str:
    """拼接类级 base 路径 + 方法级 sub 路径，规范化斜杠"""
    base = (base or '').strip()
    sub = (sub or '').strip()
    parts = []
    for seg in (base, sub):
        if not seg:
            continue
        parts.append(seg.strip('/'))
    path = '/' + '/'.join(p for p in parts if p)
    return path if path != '/' or (base == '/' or sub == '/') else (path or '/')


def _extract_request_mapping_method(args: str) -> List[str]:
    """从 @RequestMapping(method=RequestMethod.GET) 提取 HTTP 方法，默认全方法"""
    methods = re.findall(r'RequestMethod\.(\w+)', args)
    return methods if methods else ['GET']  # 无 method 默认 GET（保守）


def _extract_request_mapping_path(args: str) -> str:
    """从 @RequestMapping 参数提取路径"""
    m = re.search(r'(?:value\s*=\s*|path\s*=\s*)?["\']([^"\']*)["\']', args)
    return m.group(1) if m else ''


def scan_java_file(file_path: Path, source_root: Path) -> List[Dict[str, Any]]:
    """扫描单个 Java 文件，提取接口定义"""
    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return []

    # 必须是控制器类
    if not _CONTROLLER_RE.search(content):
        return []

    # 类名
    class_m = re.search(r'\b(?:public\s+)?class\s+(\w+)', content)
    class_name = class_m.group(1) if class_m else file_path.stem

    # 类级基路径
    base_path = ''
    cls_rm = _CLASS_REQUEST_MAPPING_RE.search(content)
    if cls_rm:
        base_path = cls_rm.group(1)

    apis: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # 找 class 声明行号：类级注解(@RequestMapping/@RestController)在它之前，
    # 方法级映射注解在它之后。借此避免类级 @RequestMapping 被当成方法级重复计入。
    class_decl_line = 0
    for idx, ln in enumerate(lines):
        if re.search(r'\b(?:public\s+)?class\s+\w+', ln):
            class_decl_line = idx
            break

    for i, line in enumerate(lines):
        # 跳过 class 声明之前的行（类级注解区），只扫方法级映射
        if i <= class_decl_line:
            continue
        # 方法级 @XxxMapping
        mm = _METHOD_MAPPING_RE.search(line)
        rmm = _METHOD_REQUEST_MAPPING_RE.search(line)

        http_methods: List[str] = []
        sub_path = ''

        if mm:
            http_methods = [_MAPPING_ANNOTATIONS[mm.group(1)]]
            sub_path = mm.group(2) or ''
        elif rmm:
            args = rmm.group(1)
            http_methods = _extract_request_mapping_method(args)
            sub_path = _extract_request_mapping_path(args)
        else:
            continue

        # 向下找方法名（跳过其他注解行）
        handler = None
        for j in range(i + 1, min(i + 6, len(lines))):
            nm = _METHOD_NAME_RE.search(lines[j])
            if nm and nm.group(1) not in ('if', 'for', 'while', 'switch'):
                handler = nm.group(1)
                break

        full_path = _normalize_path(base_path, sub_path)
        for hm in http_methods:
            apis.append({
                'method': hm,
                'path': full_path,
                'class': class_name,
                'handler': handler or '?',
                'source_file': str(file_path.relative_to(source_root)).replace('\\', '/'),
            })

    return apis


def scan_spring_apis(source_root: str) -> Dict[str, Any]:
    """
    扫描 Spring MVC 源码目录，提取所有接口

    Returns:
        {
            'apis': [{method, path, class, handler, source_file}, ...],
            'total': int,
            'controllers': int,
            'source_root': str,
        }
    """
    root = Path(source_root)
    if not root.exists():
        raise FileNotFoundError(f"源码目录不存在: {source_root}")

    all_apis: List[Dict[str, Any]] = []
    controller_files = set()

    for java_file in root.rglob('*.java'):
        file_apis = scan_java_file(java_file, root)
        if file_apis:
            controller_files.add(str(java_file))
            all_apis.extend(file_apis)

    return {
        'apis': all_apis,
        'total': len(all_apis),
        'controllers': len(controller_files),
        'source_root': str(root),
    }
