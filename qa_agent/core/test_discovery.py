"""
测试发现模块（Test Discovery）

扫描项目中已有的测试文件，自动分级并纳入覆盖评估。
解决 L3 质量逃逸问题：YAML 外的测试不受 Gatekeeper 管辖。

测试分级：
- static_check: 文件存在/符号检查（权重 0.2）
- unit: 函数级单元测试（权重 0.6）
- integration: 多模块集成测试（权重 0.8）
- e2e: 真实浏览器/用户行为验证（权重 1.0）
"""

import re
from pathlib import Path
from typing import Dict, Any, List, Tuple


# 测试文件匹配模式
TEST_FILE_PATTERNS = [
    '**/*.spec.ts',
    '**/*.spec.js',
    '**/*.spec.mjs',
    '**/*.test.ts',
    '**/*.test.js',
    '**/*.test.mjs',
    '**/*.test.tsx',
    '**/*.spec.tsx',
    '**/test_*.py',
    '**/*_test.py',
    '**/*_test.go',
    '**/verify-*.mjs',
    '**/verify-*.js',
]

# 排除目录
EXCLUDE_DIRS = {
    'node_modules', '.git', 'dist', 'build', '.next',
    '__pycache__', '.pytest_cache', 'coverage',
    '.aqe-output', 'qa/webui',
}

# 测试级别权重
TEST_LEVEL_WEIGHTS = {
    'static_check': 0.2,
    'unit': 0.6,
    'integration': 0.8,
    'e2e': 1.0,
}

# E2E 检测关键词（文件内容中出现 → 判定为 E2E）
E2E_INDICATORS = [
    'playwright', 'chromium', 'firefox', 'webkit',
    'page.click', 'page.fill', 'page.goto',
    'page.locator', 'page.waitFor',
    'browser.newPage', 'browser.launch',
    'puppeteer', 'cypress',
    'webdriver', 'selenium',
]

# 静态检查检测关键词（文件内容中出现且不含 E2E 关键词 → 判定为静态检查）
STATIC_CHECK_INDICATORS = [
    'fs.existsSync',
    'fs.readFileSync',
    '.includes(',
    'file.indexOf',
]


def discover_tests(project_dir: Path) -> List[Dict[str, Any]]:
    """
    扫描项目中已有的测试文件

    Returns:
        [
            {
                'file': 'webapp/scripts/verify-v33.mjs',
                'level': 'static_check',
                'weight': 0.2,
                'managed': False,  # 是否已在 qa/cases/*.yml 中管理
                'framework': 'node',
            },
            ...
        ]
    """
    tests = []
    seen_files = set()

    for pattern in TEST_FILE_PATTERNS:
        for file_path in project_dir.glob(pattern):
            # 排除目录
            if any(excl in file_path.parts for excl in EXCLUDE_DIRS):
                continue

            rel_path = str(file_path.relative_to(project_dir))
            if rel_path in seen_files:
                continue
            seen_files.add(rel_path)

            # 分级
            level = classify_test_file(file_path)
            weight = TEST_LEVEL_WEIGHTS.get(level, 0.6)

            # 检测框架
            framework = detect_framework(file_path)

            tests.append({
                'file': rel_path,
                'level': level,
                'weight': weight,
                'managed': False,
                'framework': framework,
            })

    return tests


def classify_test_file(file_path: Path) -> str:
    """
    根据文件内容分类测试级别

    分类逻辑：
    1. 包含 E2E 关键词 → 'e2e'
    2. 仅包含静态检查关键词 → 'static_check'
    3. 文件名含 'integration' → 'integration'
    4. 其他 → 'unit'
    """
    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        content_lower = content.lower()
    except Exception:
        return 'unit'

    # 检测 E2E
    for indicator in E2E_INDICATORS:
        if indicator.lower() in content_lower:
            return 'e2e'

    # 检测静态检查
    has_static = any(ind in content for ind in STATIC_CHECK_INDICATORS)
    has_no_runtime = 'import ' not in content or (
        'assert' in content_lower and 'page' not in content_lower
    )
    if has_static and has_no_runtime:
        return 'static_check'

    # 检测集成测试（文件名/路径含 integration）
    if 'integration' in str(file_path).lower():
        return 'integration'

    return 'unit'


def detect_framework(file_path: Path) -> str:
    """检测测试框架"""
    suffix = file_path.suffix
    name = file_path.name

    if suffix in ('.mjs', '.js', '.ts', '.tsx'):
        return 'node'
    elif suffix == '.py':
        return 'pytest'
    elif suffix == '.go':
        return 'go'
    return 'unknown'


def compute_coverage_stats(tests: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    计算覆盖统计（加权）

    Returns:
        {
            'total_files': 47,
            'by_level': {'static_check': 33, 'unit': 8, 'e2e': 6},
            'raw_coverage': 47,
            'weighted_coverage': 33*0.2 + 8*0.6 + 6*1.0 = 17.4,
            'effective_coverage_ratio': 17.4 / 47 = 0.37,
        }
    """
    by_level = {}
    for t in tests:
        level = t['level']
        by_level[level] = by_level.get(level, 0) + 1

    raw = len(tests)
    weighted = sum(
        by_level.get(level, 0) * weight
        for level, weight in TEST_LEVEL_WEIGHTS.items()
    )

    return {
        'total_files': raw,
        'by_level': by_level,
        'raw_coverage': raw,
        'weighted_coverage': round(weighted, 1),
        'effective_coverage_ratio': round(weighted / raw, 2) if raw > 0 else 0,
    }


def check_l3_coverage_adequacy(
    project_dir: Path,
    yaml_cases_count: int,
    tests: List[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    检查 L3 用例覆盖是否充分

    判定规则：
    1. YAML 用例数 ≥ max(模块数 × 3, 已有测试文件数 × 0.5, 20)
    2. 必须有至少 1 个 E2E 级别测试被执行
    3. 静态检查不能占比超过 70%

    Returns:
        (adequate: bool, reason: str)
    """
    if tests is None:
        tests = discover_tests(project_dir)

    total_test_files = len(tests)
    stats = compute_coverage_stats(tests)

    # 估算模块数（通过 src/ 目录下的子目录数）
    module_count = _estimate_module_count(project_dir)

    # 规则 1：用例规模
    min_required = max(module_count * 3, int(total_test_files * 0.5), 20)
    if yaml_cases_count < min_required:
        return False, (
            f"L3 用例规模不足：当前 {yaml_cases_count} 条，"
            f"要求 ≥ {min_required} 条"
            f"（模块数={module_count}, 已有测试文件={total_test_files}）"
        )

    # 规则 2：必须有 E2E
    e2e_count = stats['by_level'].get('e2e', 0)
    if e2e_count == 0 and total_test_files > 10:
        return False, "L3 无 E2E 级别测试，无法验证用户主流程"

    # 规则 3：静态检查不能占比超过 70%
    static_count = stats['by_level'].get('static_check', 0)
    if total_test_files > 0 and static_count / total_test_files > 0.7:
        return False, (
            f"静态检查占比过高：{static_count}/{total_test_files} = "
            f"{static_count * 100 // total_test_files}%，需补充行为验证测试"
        )

    return True, "覆盖充分"


def _estimate_module_count(project_dir: Path) -> int:
    """估算项目模块数"""
    candidates = [
        project_dir / 'src',
        project_dir / 'app',
        project_dir / 'lib',
        project_dir / 'packages',
        project_dir / 'webapp' / 'src',
    ]

    for src_dir in candidates:
        if src_dir.exists():
            dirs = [d for d in src_dir.iterdir() if d.is_dir()
                    and not d.name.startswith('.')]
            if dirs:
                return len(dirs)

    return 5  # 默认最小值
