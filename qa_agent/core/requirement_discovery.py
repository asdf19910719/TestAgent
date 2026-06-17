"""
需求文档自动发现算法（P0-1）

支持多种工作流框架的产出目录：
- BMAD: .bmad/output/
- spec-kit: specs/
- ai-docs: ai-docs/（通用 AI 工作流框架）
- 通用: docs/、PRD.md、REQUIREMENTS.md
"""

from pathlib import Path
from typing import Dict, Any, Optional, List


# 需求文档搜索路径（按优先级从高到低）
REQUIREMENTS_SEARCH_PATHS = [
    # 显式命名的需求文档（最常见）
    'docs/requirements.md',
    'docs/acceptance_criteria.md',
    'docs/prd.md',
    'docs/PRD.md',

    # AI 工作流框架产出
    'ai-docs/requirements.md',          # ai-docs 通用框架
    'ai-docs/design.md',
    'ai-docs/spec.md',
    'ai-docs/PRD.md',
    'ai-docs/*.md',                      # 兜底：ai-docs 下所有 md
    '.bmad/output/*.md',                 # BMAD 框架
    'specs/*/spec.md',                   # spec-kit 框架
    'specs/*/acceptance.feature',
    'features/*.feature',                # BDD

    # 项目根
    'REQUIREMENTS.md',
    'PRD.md',
    'SPEC.md',
    'DESIGN.md',
]


# 设计文档搜索路径（按优先级）
DESIGN_DOC_SEARCH_PATHS = [
    'docs/design.md',
    'docs/architecture.md',
    'ai-docs/design.md',
    'ai-docs/architecture.md',
    'ai-docs/技术方案.md',
    'DESIGN.md',
    'ARCHITECTURE.md',
]


def discover_requirements(config: Dict[str, Any], cwd: Path = Path('.')) -> Dict[str, Any]:
    """
    需求文档自动发现（主规范 §12.1）

    Returns:
        {
            'primary': str | None,
            'acceptance': str | None,
            'design': str | None,
            'specs': List[str],
            'bdd': List[str],
            'all_docs': List[str],   # ai-docs/ 等目录下的所有文档
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
    if found['primary'] or found['specs'] or found['bdd'] or found['all_docs']:
        return {**found, 'source': 'convention'}

    # 优先级 3: 反向梳理兜底
    print("[需求发现] 未找到需求文档，将在首次执行时触发反向梳理")
    return {
        'primary': None,
        'acceptance': None,
        'design': None,
        'specs': [],
        'bdd': [],
        'all_docs': [],
        'source': 'reverse_engineered'
    }


def validate_explicit_paths(explicit: Dict[str, Any], cwd: Path) -> Dict[str, Any]:
    """
    验证显式配置的路径
    """
    result = {
        'primary': None,
        'acceptance': None,
        'design': None,
        'specs': [],
        'bdd': [],
        'all_docs': []
    }

    if 'primary' in explicit:
        path = cwd / explicit['primary']
        if path.exists():
            result['primary'] = str(path)

    if 'acceptance' in explicit:
        path = cwd / explicit['acceptance']
        if path.exists():
            result['acceptance'] = str(path)

    if 'design' in explicit:
        path = cwd / explicit['design']
        if path.exists():
            result['design'] = str(path)

    if 'spec_kit_dir' in explicit:
        spec_dir = cwd / explicit['spec_kit_dir']
        if spec_dir.exists():
            result['specs'] = [str(p) for p in spec_dir.rglob('*.md')]

    if 'bdd_dir' in explicit:
        bdd_dir = cwd / explicit['bdd_dir']
        if bdd_dir.exists():
            result['bdd'] = [str(p) for p in bdd_dir.rglob('*.feature')]

    if 'ai_docs_dir' in explicit:
        ai_dir = cwd / explicit['ai_docs_dir']
        if ai_dir.exists():
            result['all_docs'] = [str(p) for p in ai_dir.rglob('*.md')]

    return result


def scan_convention_paths(cwd: Path) -> Dict[str, Any]:
    """
    按约定路径扫描

    支持的框架/约定：
    - BMAD: .bmad/output/
    - spec-kit: specs/
    - ai-docs: ai-docs/
    - 通用 docs/
    """
    result = {
        'primary': None,
        'acceptance': None,
        'design': None,
        'specs': [],
        'bdd': [],
        'all_docs': []
    }

    # 主需求文档（按优先级搜索）
    for pattern in REQUIREMENTS_SEARCH_PATHS:
        if result['primary']:
            break

        if '*' in pattern:
            matches = list(cwd.glob(pattern))
            if matches:
                # 优先选择文件名包含 requirements/prd/spec 的
                priority_match = None
                for m in matches:
                    name_lower = m.name.lower()
                    if any(kw in name_lower for kw in ['requirement', 'prd', 'spec']):
                        priority_match = m
                        break
                result['primary'] = str(priority_match or matches[0])
        else:
            path = cwd / pattern
            if path.exists():
                result['primary'] = str(path)

    # 设计文档
    for pattern in DESIGN_DOC_SEARCH_PATHS:
        path = cwd / pattern
        if path.exists():
            result['design'] = str(path)
            break

    # 验收标准
    for pattern in ['docs/acceptance_criteria.md', 'ai-docs/acceptance_criteria.md',
                    'ai-docs/验收标准.md', 'ACCEPTANCE.md']:
        path = cwd / pattern
        if path.exists():
            result['acceptance'] = str(path)
            break

    # Spec-kit
    specs_dir = cwd / 'specs'
    if specs_dir.exists():
        result['specs'] = [str(p) for p in specs_dir.rglob('*.md')]

    # BDD
    features_dir = cwd / 'features'
    if features_dir.exists():
        result['bdd'] = [str(p) for p in features_dir.rglob('*.feature')]

    # AI-docs 目录下的所有文档（提供完整上下文给 subagent）
    ai_docs_dir = cwd / 'ai-docs'
    if ai_docs_dir.exists():
        result['all_docs'] = [str(p) for p in ai_docs_dir.rglob('*.md')]

    # .bmad/output 目录下的所有文档
    bmad_dir = cwd / '.bmad' / 'output'
    if bmad_dir.exists():
        result['all_docs'].extend([str(p) for p in bmad_dir.rglob('*.md')])

    # docs 目录下的所有文档（如果未在 primary 中匹配）
    docs_dir = cwd / 'docs'
    if docs_dir.exists() and not result['all_docs']:
        result['all_docs'] = [str(p) for p in docs_dir.rglob('*.md')]

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

