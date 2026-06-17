"""
终端 UI 工具：彩色输出、进度条、智能下一步提示
"""

import sys
from typing import List, Dict, Any


class Colors:
    """ANSI 颜色代码"""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    GRAY = '\033[90m'

    @classmethod
    def is_supported(cls) -> bool:
        """检测终端是否支持彩色"""
        if not sys.stdout.isatty():
            return False
        # Windows 10+ 原生支持 ANSI
        if sys.platform == 'win32':
            import os
            return os.environ.get('TERM') is not None or os.environ.get('WT_SESSION') is not None
        return True


def _supports_color() -> bool:
    return Colors.is_supported()


def color(text: str, color_code: str) -> str:
    """着色文本（终端不支持时返回原文）"""
    if not _supports_color():
        return text
    return f"{color_code}{text}{Colors.RESET}"


def green(text: str) -> str:
    return color(text, Colors.GREEN)


def red(text: str) -> str:
    return color(text, Colors.RED)


def yellow(text: str) -> str:
    return color(text, Colors.YELLOW)


def cyan(text: str) -> str:
    return color(text, Colors.CYAN)


def bold(text: str) -> str:
    return color(text, Colors.BOLD)


def dim(text: str) -> str:
    return color(text, Colors.DIM)


def gray(text: str) -> str:
    return color(text, Colors.GRAY)


# ============== 智能下一步提示（P2-3） ==============

def print_pass_summary(mode: str, stats: Dict[str, Any], duration: float = 0):
    """
    PASS 时的智能下一步提示
    """
    print(f"\n{green('✅')} {bold(mode)} 完成：测试通过")
    print(f"\n执行统计：")
    print(f"  总数 {stats.get('total', 0)} / 通过 {green(str(stats.get('pass', 0)))} / 失败 {stats.get('fail', 0)}")
    if duration:
        print(f"  耗时：{duration:.1f} 秒")

    print(f"\n{bold('建议下一步：')}")
    if mode == 'L0':
        print(f"  {green('✓')} 继续开发 → 完成功能后运行 {cyan('/qa feature <name>')}")
    elif mode == 'L1':
        print(f"  {green('✓')} 继续开发其他功能 → 完成后运行 {cyan('/qa feature <name>')}")
        print(f"  {green('✓')} 模块开发完成 → 运行 {cyan('/qa module <name>')} 验证模块完整性")
        print(f"  {green('✓')} 准备发版 → 运行 {cyan('/qa release')} 进入发版质量门")
    elif mode == 'L2':
        print(f"  {green('✓')} 准备发版 → 运行 {cyan('/qa release')} 进入发版质量门")
        print(f"  {green('✓')} 继续下一模块 → 运行 {cyan('/qa feature <name>')}")
    elif mode == 'L3':
        print(f"  {green('✓')} 可发版 → 完整质量门已通过")
        print(f"  {dim('提示：仅 L3 PASS 才是合法发版凭据')}")
    elif mode == 'L4':
        print(f"  {green('✓')} 缺陷已修复 → 继续开发")
        print(f"  {green('✓')} 发版前再跑一次 → {cyan('/qa release')}")

    print(f"\n详细报告：{cyan('qa/final_test_report.md')}")


def print_fail_summary(mode: str, stats: Dict[str, Any], failures: List[Dict[str, Any]]):
    """
    FAIL 时的智能下一步提示
    """
    print(f"\n{red('❌')} {bold(mode)} 失败：存在 {len(failures)} 个问题")
    print(f"\n执行统计：")
    print(f"  总数 {stats.get('total', 0)} / 通过 {stats.get('pass', 0)} / 失败 {red(str(stats.get('fail', 0)))}")

    print(f"\n{bold('失败用例：')}")
    for f in failures[:5]:
        bug_id = f.get('bug_id', 'BUG-???')
        case_id = f.get('case_id', 'TC-???')
        severity = f.get('severity', 'medium')
        msg = f.get('message', '')[:80]
        severity_color = red if severity in ('blocker', 'high') else yellow
        print(f"  - {severity_color(bug_id)}: {msg} ({case_id})")

    if len(failures) > 5:
        print(f"  ... 还有 {len(failures) - 5} 个失败用例")

    print(f"\n{bold('建议操作：')}")
    print(f"  1. 查看缺陷详情：{cyan('qa/bugs/<BUG-ID>.yml')}")
    print(f"  2. 修复代码后运行：{cyan('/qa retry')} 重跑相同范围")
    if failures:
        first_bug = failures[0].get('bug_id', 'BUG-???')
        print(f"  3. 单独验证某个 bug：{cyan(f'/qa bugfix {first_bug}')}")
    print(f"  4. 需要调试时：查看 {cyan('qa/run/last.json')} 完整执行细节")


def print_blocked_summary(mode: str, reason: str, suggestions: List[str] = None):
    """
    BLOCKED 时的智能下一步提示
    """
    print(f"\n{yellow('⚠️ ')} {bold(mode)} 阻塞：{reason}")

    if suggestions:
        print(f"\n{bold('建议操作：')}")
        for i, s in enumerate(suggestions, 1):
            print(f"  {i}. {s}")
    else:
        print(f"\n{bold('建议操作：')}")
        print(f"  1. 检查环境（依赖、配置、网络）")
        print(f"  2. 修复阻塞原因")
        print(f"  3. 运行 {cyan('/qa resume')} 从中断处继续")


# ============== 进度条 ==============

class ProgressBar:
    """简单的终端进度条"""

    def __init__(self, total: int, label: str = "", width: int = 40):
        self.total = total
        self.current = 0
        self.label = label
        self.width = width

    def update(self, n: int = 1):
        """步进"""
        self.current = min(self.current + n, self.total)
        self._render()

    def set(self, value: int):
        """设置当前值"""
        self.current = min(value, self.total)
        self._render()

    def finish(self):
        """完成"""
        self.current = self.total
        self._render()
        print()  # 换行

    def _render(self):
        if not sys.stdout.isatty():
            return  # 非 TTY 不显示进度条

        if self.total == 0:
            percent = 100
        else:
            percent = int(self.current * 100 / self.total)

        filled = int(self.width * self.current / self.total) if self.total > 0 else self.width
        bar = '█' * filled + '░' * (self.width - filled)

        line = f"\r{self.label} [{green(bar)}] {percent}% ({self.current}/{self.total})"
        sys.stdout.write(line)
        sys.stdout.flush()


# ============== 表格输出 ==============

def print_table(headers: List[str], rows: List[List[str]], widths: List[int] = None):
    """简单的表格输出"""
    if not rows:
        return

    if widths is None:
        widths = [max(len(h), max(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]

    # 表头
    header_line = ' | '.join(bold(h.ljust(widths[i])) for i, h in enumerate(headers))
    print(header_line)
    print('-' * (sum(widths) + 3 * (len(headers) - 1)))

    # 行
    for row in rows:
        row_line = ' | '.join(str(row[i]).ljust(widths[i]) for i in range(len(headers)))
        print(row_line)
