"""
Kotlin 生成代码静态结构校验器

无需 JDK/Android SDK，纯静态检查生成的 Kotlin 测试代码的结构正确性，
拦截最常见的编译阻塞类 bug（实证驱动：这些都是实战中真撞到过的）：

- 同作用域 val 重复声明（如 val resolver / val cursor 多次）
- import 缺前缀（裸类名当 import）
- 花括号/圆括号不配平
- @AI-FILL / TODO 残留（标 implemented 却没填完）
- 空测试方法体（只有注释没有断言）

定位：这是 Adapter 生成后、Designer 填充后都可调用的"编译前自检"，
对应 Gatekeeper 硬规则 9（填充完整性）的机器化前置。
"""

import re
from typing import List, Dict, Any


class KotlinStructureValidator:
    """Kotlin 测试代码静态结构校验"""

    def validate(self, content: str) -> Dict[str, Any]:
        """
        校验 Kotlin 代码结构

        Returns:
            {
                'ok': bool,
                'errors': [str],     # 编译阻塞级问题
                'warnings': [str],   # 建议修复但不阻塞
            }
        """
        errors: List[str] = []
        warnings: List[str] = []

        self._check_braces(content, errors)
        self._check_parens(content, errors)
        self._check_import_prefix(content, errors)
        self._check_duplicate_val_in_method(content, errors)
        self._check_aifill_residue(content, warnings)
        self._check_empty_test_body(content, warnings)

        return {
            'ok': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
        }

    def _strip_comments_strings(self, content: str) -> str:
        """移除注释和字符串字面量，避免误判括号/关键字"""
        # 移除行注释
        no_line = re.sub(r'//[^\n]*', '', content)
        # 移除块注释
        no_block = re.sub(r'/\*.*?\*/', '', no_line, flags=re.DOTALL)
        # 移除字符串字面量(简化：双引号，含转义)
        no_str = re.sub(r'"(?:\\.|[^"\\])*"', '""', no_block)
        return no_str

    def _check_braces(self, content: str, errors: List[str]) -> None:
        code = self._strip_comments_strings(content)
        opens = code.count('{')
        closes = code.count('}')
        if opens != closes:
            errors.append(f"花括号不配平: {{ x{opens} vs }} x{closes}")

    def _check_parens(self, content: str, errors: List[str]) -> None:
        code = self._strip_comments_strings(content)
        opens = code.count('(')
        closes = code.count(')')
        if opens != closes:
            errors.append(f"圆括号不配平: ( x{opens} vs ) x{closes}")

    def _check_import_prefix(self, content: str, errors: List[str]) -> None:
        """检查 import 段是否有裸类名(缺 import 关键字)"""
        # import 段通常在文件头部 package 之后、第一个 /** 或 class 之前
        lines = content.split('\n')
        in_header = True
        for ln in lines:
            stripped = ln.strip()
            if not stripped:
                continue
            if stripped.startswith('package ') or stripped.startswith('import '):
                continue
            if stripped.startswith('/**') or stripped.startswith('@') or stripped.startswith('class ') or stripped.startswith('object '):
                break
            # 头部出现的非 package/import/注释行，且像个全限定类名 → 疑似裸 import
            if in_header and re.match(r'^[a-z][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)+$', stripped):
                errors.append(f"疑似缺 import 前缀的裸类名: '{stripped}'")

    def _check_duplicate_val_in_method(self, content: str, errors: List[str]) -> None:
        """
        检查同一方法体内 val/var 重复声明(Kotlin 不允许)

        策略：对每个 fun 方法体，只保留「方法体直接作用域」的字符
        (剔除所有嵌套 {...} 块，如 run{}/use{}/if{} 内的局部 val)，
        再统计直接作用域的 val/var 名称。run{} 内的同名 cursor 不算冲突。
        """
        from collections import Counter
        code = self._strip_comments_strings(content)

        for m in re.finditer(r'\bfun\s+\w+\s*\([^)]*\)[^{]*\{', code):
            start = m.end()  # 方法体第一个 { 之后
            depth = 1
            i = start
            direct_chars: List[str] = []
            while i < len(code) and depth > 0:
                ch = code[i]
                if ch == '{':
                    depth += 1
                    i += 1
                    continue
                if ch == '}':
                    depth -= 1
                    i += 1
                    continue
                # 只收集方法体直接层(depth==1)的字符，嵌套块内的跳过
                if depth == 1:
                    direct_chars.append(ch)
                i += 1

            direct_text = ''.join(direct_chars)
            names = re.findall(r'\b(?:val|var)\s+(\w+)\b', direct_text)
            for name, cnt in Counter(names).items():
                if cnt > 1:
                    errors.append(f"方法体内 val/var '{name}' 重复声明 {cnt} 次(Kotlin 不允许)")

    def _check_aifill_residue(self, content: str, warnings: List[str]) -> None:
        """检查 @AI-FILL / TODO 残留"""
        aifill = len(re.findall(r'@AI-FILL', content))
        todo = len(re.findall(r'\bTODO\b', content))
        if aifill > 0:
            warnings.append(f"残留 {aifill} 处 @AI-FILL(未完成填充，不应标 implemented)")
        if todo > 0:
            warnings.append(f"残留 {todo} 处 TODO(可能未完成)")

    def _check_empty_test_body(self, content: str, warnings: List[str]) -> None:
        """检查 @Test 方法是否有断言"""
        # 找 @Test fun ... { ... } 块，看是否含 assert
        for m in re.finditer(r'@Test[^{]*fun\s+(\w+)\s*\([^)]*\)[^{]*\{', content):
            name = m.group(1)
            start = m.end()
            depth = 1
            i = start
            while i < len(content) and depth > 0:
                if content[i] == '{':
                    depth += 1
                elif content[i] == '}':
                    depth -= 1
                i += 1
            body = content[start:i]
            if not re.search(r'\bassert\w*\(', body):
                warnings.append(f"测试方法 '{name}' 无断言(可能是空骨架)")
