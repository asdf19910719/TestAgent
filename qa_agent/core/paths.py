"""
产物路径约束（迁移借鉴自 oec-ai-infra 的产物路径约束机制）

集中定义 TestAgent 所有产物的规范路径，提供：
- 路径常量（用例 / 执行记录 / 缺陷 / 报告 / 移动端测试）
- 路径校验（生成产物前检查目标路径是否落在约定结构内）
- 路径解析（按 feature/case 拼接规范路径）

背景：之前产物路径散落在各模块字符串字面量里（qa/cases、qa/run、
app/src/androidTest 等），无单一事实来源，容易写到约定外位置。
本模块统一管理，Adapter/Engine 生成产物前调用 validate_output_path 校验。
"""

from pathlib import Path
from typing import Dict, List, Optional


# ============================================================
# 规范产物目录结构（单一事实来源）
# ============================================================

# QA Agent 产物根（相对项目根）
QA_ROOT = 'qa'

# 各类产物的规范子目录
QA_PATHS = {
    'cases': f'{QA_ROOT}/cases',           # 用例 YAML（按 feature 分子目录）
    'run': f'{QA_ROOT}/run',               # 执行记录（last.json/baseline.json/history.jsonl/selection.md）
    'bugs': f'{QA_ROOT}/bugs',             # 缺陷 YAML
    'reports': f'{QA_ROOT}/reports',       # 测试报告（HTML/JSON/markdown）
    'maestro_flows': f'{QA_ROOT}/maestro_flows',  # Maestro UI flow YAML
    'signoff': f'{QA_ROOT}/signoff',       # 反向梳理签字
}

# 执行记录的具体文件
RUN_FILES = {
    'last': f'{QA_PATHS["run"]}/last.json',
    'baseline': f'{QA_PATHS["run"]}/baseline.json',
    'history': f'{QA_PATHS["run"]}/history.jsonl',
    'selection': f'{QA_PATHS["run"]}/selection.md',
    'main_flows': f'{QA_PATHS["run"]}/main_flows.md',
    'coverage_warning': f'{QA_PATHS["run"]}/coverage_warning.json',
    'coverage_matrix': f'{QA_PATHS["run"]}/coverage_matrix.md',
}

# 移动端测试代码路径（项目源码树内，按测试类型分源集）
MOBILE_TEST_PATHS = {
    'android_instrumented': 'app/src/androidTest/kotlin',  # Espresso/UiAutomator
    'android_unit': 'app/src/test/kotlin',                 # Robolectric/JUnit
    'ios': 'Tests',                                        # XCTest
    'flutter_integration': 'integration_test',
    'flutter_unit': 'test',
    'rn_e2e': 'e2e',
    'rn_unit': '__tests__',
}

# 允许写入产物的根前缀白名单（校验用）
ALLOWED_OUTPUT_PREFIXES = [
    QA_ROOT,           # qa/ 下所有
    'app/src/test',    # Android/通用单元测试源集
    'app/src/androidTest',  # Android instrumented 源集
    'Tests',           # iOS
    'integration_test',  # Flutter
    'test',            # Flutter unit / 通用
    'e2e',             # RN E2E
    '__tests__',       # RN unit
    'tests',           # 通用测试目录
]


def case_dir(feature_id: str) -> str:
    """用例目录：qa/cases/<feature_id>/"""
    return f'{QA_PATHS["cases"]}/{feature_id}'


def case_file(feature_id: str, case_id: str) -> str:
    """单个用例文件：qa/cases/<feature_id>/<case_id>.yml"""
    return f'{case_dir(feature_id)}/{case_id}.yml'


def bug_file(bug_id: str) -> str:
    """缺陷文件：qa/bugs/<bug_id>.yml"""
    return f'{QA_PATHS["bugs"]}/{bug_id}.yml'


def report_file(run_id: str, fmt: str = 'html') -> str:
    """报告文件：qa/reports/<run_id>.<fmt>"""
    ext = {'html': 'html', 'json': 'json', 'markdown': 'md'}.get(fmt, fmt)
    return f'{QA_PATHS["reports"]}/{run_id}.{ext}'


def validate_output_path(path: str, cwd: Optional[Path] = None) -> Dict[str, any]:
    """
    校验产物路径是否落在约定结构内（防止产物散落到工作区任意位置）

    Args:
        path: 待写入的产物路径（相对项目根 或 绝对路径）
        cwd: 项目根（默认当前目录）

    Returns:
        {
            'ok': bool,
            'reason': str,          # ok=False 时说明
            'normalized': str,      # 规范化后的相对路径
            'matched_prefix': str,  # 命中的白名单前缀
        }
    """
    cwd = cwd or Path('.')
    p = Path(path)

    # 绝对路径 → 转成相对项目根
    if p.is_absolute():
        try:
            rel = p.relative_to(cwd.resolve())
            rel_str = str(rel).replace('\\', '/')
        except ValueError:
            return {
                'ok': False,
                'reason': f'路径在项目根之外: {path}',
                'normalized': str(p).replace('\\', '/'),
                'matched_prefix': None,
            }
    else:
        rel_str = str(p).replace('\\', '/')

    # 校验是否命中白名单前缀
    for prefix in ALLOWED_OUTPUT_PREFIXES:
        if rel_str == prefix or rel_str.startswith(prefix + '/'):
            return {
                'ok': True,
                'reason': '',
                'normalized': rel_str,
                'matched_prefix': prefix,
            }

    return {
        'ok': False,
        'reason': (
            f'路径未落在约定产物结构内: {rel_str}\n'
            f'    允许的前缀: {", ".join(ALLOWED_OUTPUT_PREFIXES)}'
        ),
        'normalized': rel_str,
        'matched_prefix': None,
    }


def ensure_qa_dirs(cwd: Optional[Path] = None) -> List[str]:
    """
    创建所有规范 QA 产物目录（幂等）

    Returns: 创建/确认的目录列表
    """
    cwd = cwd or Path('.')
    created = []
    for key, rel in QA_PATHS.items():
        d = cwd / rel
        d.mkdir(parents=True, exist_ok=True)
        created.append(str(rel))
    return created
