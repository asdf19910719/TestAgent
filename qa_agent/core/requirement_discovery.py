"""
需求文档自动发现算法（P0-1）
"""

from pathlib import Path
from typing import Dict, Any, Optional, List


REQUIREMENTS_SEARCH_PATHS = [
    'docs/requirements.md',
    'docs/acceptance_criteria.md',
    'specs/*/spec.md',
    'specs/*/acceptance.feature',
    'features/*.feature',
    '.bmad/output/*.md',
    'REQUIREMENTS.md',
    'PRD.md',
]


def discover_requirements(config: Dict[str, Any], cwd: Path = Path('.')) -> Dict[str, Any]:
    """
    需求文档自动发现（主规范 §12.1）

    Returns:
        {
            'primary': str | None,
            'acceptance': str | None,
            'specs': List[str],
            'bdd': List[str],
            'source': 'explicit' | 'convention' | 'reverse_engineered'
        }
    """
    # 优先级 1: 显式配置
    if 'requirements' in config:
        explicit = config['requirements']
        validated = validate_explicit_paths(explicit, cwd)
        if validated['primary'] is not None:
            return {**validated, 'source': 'explicit'}

    # 优先级 2: 约定路径自动扫描
    found = scan_convention_paths(cwd)
    if found['primary'] or found['specs'] or found['bdd']:
        return {**found, 'source': 'convention'}

    # 优先级 3: 反向梳理兜底（Phase 3 实现）
    print("[需求发现] 未找到需求文档，将在首次执行时触发反向梳理")
    return {
        'primary': None,
        'acceptance': None,
        'specs': [],
        'bdd': [],
        'source': 'reverse_engineered'
    }


def validate_explicit_paths(explicit: Dict[str, Any], cwd: Path) -> Dict[str, Any]:
    """
    验证显式配置的路径
    """
    result = {
        'primary': None,
        'acceptance': None,
        'specs': [],
        'bdd': []
    }

    if 'primary' in explicit:
        path = cwd / explicit['primary']
        if path.exists():
            result['primary'] = str(path)

    if 'acceptance' in explicit:
        path = cwd / explicit['acceptance']
        if path.exists():
            result['acceptance'] = str(path)

    if 'spec_kit_dir' in explicit:
        spec_dir = cwd / explicit['spec_kit_dir']
        if spec_dir.exists():
            result['specs'] = [str(p) for p in spec_dir.rglob('*.md')]

    if 'bdd_dir' in explicit:
        bdd_dir = cwd / explicit['bdd_dir']
        if bdd_dir.exists():
            result['bdd'] = [str(p) for p in bdd_dir.rglob('*.feature')]

    return result


def scan_convention_paths(cwd: Path) -> Dict[str, Any]:
    """
    按约定路径扫描
    """
    result = {
        'primary': None,
        'acceptance': None,
        'specs': [],
        'bdd': []
    }

    # 主需求文档（找到第一个就停止）
    for pattern in ['docs/requirements.md', 'REQUIREMENTS.md', 'PRD.md', '.bmad/output/*.md']:
        if '*' in pattern:
            matches = list(cwd.glob(pattern))
            if matches:
                result['primary'] = str(matches[0])
                break
        else:
            path = cwd / pattern
            if path.exists():
                result['primary'] = str(path)
                break

    # 验收标准
    for pattern in ['docs/acceptance_criteria.md']:
        path = cwd / pattern
        if path.exists():
            result['acceptance'] = str(path)
            break

    # Spec-kit / BDD
    specs_dir = cwd / 'specs'
    if specs_dir.exists():
        result['specs'] = [str(p) for p in specs_dir.rglob('*.md')]

    features_dir = cwd / 'features'
    if features_dir.exists():
        result['bdd'] = [str(p) for p in features_dir.rglob('*.feature')]

    # README 章节扫描（Phase 3 实现）
    readme = cwd / 'README.md'
    if readme.exists() and not result['primary']:
        # Phase 3: 提取 Requirements 章节
        pass

    return result


def handle_missing_requirements(mode: str) -> str:
    """
    主规范 §12.1 表格的代码实现
    """
    if mode in ['L0', 'L4']:
        print("⚠️ 需求文档缺失，但 L0/L4 模式下不阻断")
        return 'continue'
    elif mode in ['L1', 'L2']:
        print("⚠️ 需求文档缺失，进入增量补用例模式（不强制需求覆盖）")
        return 'continue'
    elif mode == 'L3':
        raise RuntimeError("L3 强制要求需求文档存在")
    else:
        return 'continue'
