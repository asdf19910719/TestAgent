"""
覆盖率分析器（第二阶段，借鉴 oec api-coverage-analyzer 的内核，语言无关重写）

设计原则（与 oec 的区别）：
- 只复用两个通用内核：JaCoCo XML 解析 + Gap 分类
- 不耦合 Spring/MyBatis/Controller（oec 的 4916 行里大量是平台特有逻辑）
- 语言无关：JaCoCo 是标准格式，Kotlin/Java/Android 都产出同样的 XML

核心能力：
- 解析 JaCoCo XML → 行/分支覆盖率 + 未覆盖行清单
- Gap 分类：exception / boundary / main_path / defensive
- 与 impact_analysis 协同：变更范围内的覆盖缺口 → 建议补用例
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple


# Gap 类型常量
GAP_EXCEPTION = 'exception'      # 异常抛出路径
GAP_BOUNDARY = 'boundary'        # 边界校验
GAP_DEFENSIVE = 'defensive'      # 防御性代码（catch 块）
GAP_MAIN_PATH = 'main_path'      # 主流程


@dataclass
class ClassCoverage:
    """单个类的覆盖数据"""
    class_name: str
    source_file: Optional[str] = None
    covered_lines: Set[int] = field(default_factory=set)
    missed_lines: Set[int] = field(default_factory=set)
    branch_covered: int = 0
    branch_missed: int = 0

    @property
    def line_total(self) -> int:
        return len(self.covered_lines) + len(self.missed_lines)

    @property
    def line_rate(self) -> float:
        return round(len(self.covered_lines) / self.line_total * 100, 1) if self.line_total else 0.0


@dataclass
class CoverageReport:
    """整体覆盖报告"""
    classes: Dict[str, ClassCoverage] = field(default_factory=dict)
    line_covered: int = 0
    line_missed: int = 0
    branch_covered: int = 0
    branch_missed: int = 0

    @property
    def line_rate(self) -> float:
        total = self.line_covered + self.line_missed
        return round(self.line_covered / total * 100, 1) if total else 0.0

    @property
    def branch_rate(self) -> float:
        total = self.branch_covered + self.branch_missed
        return round(self.branch_covered / total * 100, 1) if total else 0.0


@dataclass
class Gap:
    """一处未覆盖缺口"""
    class_name: str
    line_num: int
    code: str = ''           # 源码行内容（若可读）
    kind: str = GAP_MAIN_PATH


def parse_jacoco_xml(xml_path: str) -> CoverageReport:
    """
    解析 JaCoCo XML 报告（语言无关，标准格式）

    JaCoCo XML 结构：
      <report><package><class name="..."><method line="..."/></class>
        <sourcefile name="..."><line nr="N" ci="X" mi="Y" cb="A" mb="B"/></sourcefile>
      </package></report>
    - ci (covered instructions) > 0 → 该行被执行
    - mb/cb (missed/covered branches) → 分支覆盖
    """
    report = CoverageReport()
    p = Path(xml_path)
    if not p.is_file():
        raise FileNotFoundError(f"JaCoCo XML 不存在: {xml_path}")

    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        raise ValueError(f"JaCoCo XML 解析失败: {e}")

    root = tree.getroot()

    for pkg in root.iter('package'):
        # 建立 sourcefile name → 行覆盖映射
        sf_lines: Dict[str, List[ET.Element]] = {}
        for sf in pkg.iter('sourcefile'):
            sf_lines[sf.get('name', '')] = list(sf.iter('line'))

        for cls_elem in pkg.iter('class'):
            class_name = cls_elem.get('name', '').replace('/', '.')
            source_file = cls_elem.get('sourcefilename')
            cov = ClassCoverage(class_name=class_name, source_file=source_file)

            for line_elem in sf_lines.get(source_file or '', []):
                nr = int(line_elem.get('nr', '0'))
                ci = int(line_elem.get('ci', '0'))
                mb = int(line_elem.get('mb', '0'))
                cb = int(line_elem.get('cb', '0'))

                if ci > 0:
                    cov.covered_lines.add(nr)
                    report.line_covered += 1
                else:
                    cov.missed_lines.add(nr)
                    report.line_missed += 1

                cov.branch_covered += cb
                cov.branch_missed += mb
                report.branch_covered += cb
                report.branch_missed += mb

            if cov.line_total > 0:
                report.classes[class_name] = cov

    return report


def classify_gap(code: str) -> str:
    """
    Gap 分类（借鉴 oec，语言无关，只看未覆盖行本身）

    Returns: exception | boundary | defensive | main_path
    """
    if not code or not code.strip():
        return GAP_MAIN_PATH

    lower = code.lower()

    # 异常抛出（Java/Kotlin throw, Python raise）
    if 'throw new' in lower or re.search(r'\bthrow\b', lower) or re.search(r'\braise\b', lower):
        return GAP_EXCEPTION

    # 防御性代码：catch 块 / 错误日志
    if re.search(r'\bcatch\s*\(', lower) or re.search(r'\bexcept\b', lower):
        return GAP_DEFENSIVE
    if re.search(r'log(ger)?\.(error|warn)|printstacktrace|\.set\w*error', lower):
        return GAP_DEFENSIVE

    # 边界校验（比较 / null / 空判断）—— 不用 [^)]* 以免被嵌套括号(如 size())截断
    boundary = [
        r'\bif\b.*[<>]',                        # if + 比较运算符（含 list.size() > 0）
        r'\bif\b.*(==|!=)\s*null',              # if + null 判断
        r'\b(isempty|isblank|isnullorempty)\b', # 空判断
        r'\b(require|check)\s*\(',              # Kotlin require/check 守卫
    ]
    for pat in boundary:
        if re.search(pat, lower):
            return GAP_BOUNDARY

    return GAP_MAIN_PATH


def _read_source_line(source_roots: List[str], class_name: str, line_num: int) -> str:
    """尝试从源码读取指定行（用于 Gap 分类）。读不到返回空串。"""
    # class_name: com.x.Foo → com/x/Foo.kt|.java
    rel = class_name.replace('.', '/')
    # 去掉内部类后缀（Foo$Bar → Foo）
    rel = rel.split('$')[0]
    for root in source_roots:
        for ext in ('.kt', '.java'):
            candidate = Path(root) / f'{rel}{ext}'
            if candidate.is_file():
                try:
                    lines = candidate.read_text(encoding='utf-8', errors='ignore').splitlines()
                    if 1 <= line_num <= len(lines):
                        return lines[line_num - 1].strip()
                except OSError:
                    pass
    return ''


def extract_gaps(report: CoverageReport, source_roots: Optional[List[str]] = None) -> List[Gap]:
    """
    从覆盖报告提取所有未覆盖缺口，并分类

    Args:
        report: parse_jacoco_xml 的结果
        source_roots: 源码根目录列表（如 ['app/src/main/kotlin']），用于读源码分类
    """
    source_roots = source_roots or []
    gaps: List[Gap] = []
    for cls in report.classes.values():
        for line_num in sorted(cls.missed_lines):
            code = _read_source_line(source_roots, cls.class_name, line_num) if source_roots else ''
            gaps.append(Gap(
                class_name=cls.class_name,
                line_num=line_num,
                code=code,
                kind=classify_gap(code),
            ))
    return gaps


def analyze_coverage(xml_path: str, source_roots: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    覆盖率分析主入口

    Returns:
        {
            'line_rate': float, 'branch_rate': float,
            'line_covered': int, 'line_missed': int,
            'gaps': [{class_name, line_num, code, kind}, ...],
            'gap_summary': {exception: n, boundary: n, main_path: n, defensive: n},
            'class_count': int,
        }
    """
    report = parse_jacoco_xml(xml_path)
    gaps = extract_gaps(report, source_roots)

    gap_summary = {GAP_EXCEPTION: 0, GAP_BOUNDARY: 0, GAP_MAIN_PATH: 0, GAP_DEFENSIVE: 0}
    for g in gaps:
        gap_summary[g.kind] = gap_summary.get(g.kind, 0) + 1

    return {
        'line_rate': report.line_rate,
        'branch_rate': report.branch_rate,
        'line_covered': report.line_covered,
        'line_missed': report.line_missed,
        'class_count': len(report.classes),
        'gaps': [
            {'class_name': g.class_name, 'line_num': g.line_num, 'code': g.code, 'kind': g.kind}
            for g in gaps
        ],
        'gap_summary': gap_summary,
    }

