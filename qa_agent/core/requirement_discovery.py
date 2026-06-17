"""
需求文档自动发现算法（P0-1）

支持多种工作流框架的产出目录：
- BMAD: .bmad/output/
- spec-kit: specs/
- ai-docs: ai-docs/（工业级 AI 工作流，支持分类子目录）
- 通用: docs/、PRD.md、REQUIREMENTS.md

**ai-docs 分类子目录支持**：
- ai-docs/prd/*.md → 需求文档
- ai-docs/architecture/*.md → 设计文档
- ai-docs/apis/*.md → API 文档
- ai-docs/requirements/*.md → 需求（其他框架用名）
- ai-docs/design/*.md → 设计（其他框架用名）

**汇总文件优先**：
- *-all.md（如 prd-all.md, api-all.md）
- *-overview.md（如 architecture-overview.md）
- 含 "总" / "全量" / "汇总" 的中文文档名
"""

from pathlib import Path
from typing import Dict, Any, Optional, List


# 汇总文件识别关键词（优先级最高）
AGGREGATE_KEYWORDS = [
    'all', 'overview', 'summary', 'index',
    '总', '全量', '汇总', '概览', '索引'
]


# 需求文档搜索路径（按优先级从高到低）
REQUIREMENTS_SEARCH_PATHS = [
    # 显式命名的需求文档（最常见）
    'docs/requirements.md',
    'docs/acceptance_criteria.md',
    'docs/prd.md',
    'docs/PRD.md',

    # AI 工作流框架产出（分类子目录）
    'ai-docs/prd/*.md',                      # ClawBoxClient 风格
    'ai-docs/requirements/*.md',
    'ai-docs/需求/*.md',
    'ai-docs/PRD/*.md',
    'ai-docs/specs/*.md',

    # AI 工作流框架产出（根目录）
    'ai-docs/requirements.md',
    'ai-docs/prd.md',
    'ai-docs/PRD.md',
    'ai-docs/spec.md',
    'ai-docs/*.md',                          # 兜底：ai-docs 根下所有 md

    # 其他框架
    '.bmad/output/*.md',                     # BMAD 框架
    'specs/*/spec.md',                       # spec-kit 框架
    'specs/*/acceptance.feature',
    'features/*.feature',                    # BDD

    # 项目根
    'REQUIREMENTS.md',
    'PRD.md',
    'SPEC.md',
]


# 设计文档搜索路径（按优先级）
DESIGN_DOC_SEARCH_PATHS = [
    # AI 工作流框架（分类子目录）
    'ai-docs/architecture/*.md',             # ClawBoxClient 风格
    'ai-docs/design/*.md',
    'ai-docs/设计/*.md',
    'ai-docs/架构/*.md',

    # 通用 docs
    'docs/design.md',
    'docs/architecture.md',
    'docs/technical-design.md',

    # AI 工作流框架（根目录）
    'ai-docs/design.md',
    'ai-docs/architecture.md',
    'ai-docs/技术方案.md',

    # 项目根
    'DESIGN.md',
    'ARCHITECTURE.md',
]


# API 文档搜索路径
API_DOC_SEARCH_PATHS = [
    'ai-docs/apis/*.md',
    'ai-docs/api/*.md',
    'ai-docs/接口/*.md',
    'docs/api.md',
    'docs/api-design.md',
    'API.md',
]


def discover_requirements(config: Dict[str, Any], cwd: Path = Path('.')) -> Dict[str, Any]:
    """
    需求文档自动发现（主规范 §12.1）

    Returns:
        {
            'primary': str | None,
            'acceptance': str | None,
            'design': str | None,
            'api': str | None,
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
        'api': None,
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
        'api': None,
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

    if 'api' in explicit:
        path = cwd / explicit['api']
        if path.exists():
            result['api'] = str(path)

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
    - ai-docs: ai-docs/（支持分类子目录 + 汇总文件优先）
    - 通用 docs/
    """
    result = {
        'primary': None,
        'acceptance': None,
        'design': None,
        'api': None,
        'specs': [],
        'bdd': [],
        'all_docs': []
    }

    # 主需求文档（按优先级搜索，汇总文件优先）
    primary_candidates = []
    for pattern in REQUIREMENTS_SEARCH_PATHS:
        if result['primary']:
            break

        if '*' in pattern:
            matches = list(cwd.glob(pattern))
            primary_candidates.extend(matches)
        else:
            path = cwd / pattern
            if path.exists():
                primary_candidates.append(path)

    # 从候选中优先选择汇总文件
    if primary_candidates:
        result['primary'] = str(_select_aggregate_file(primary_candidates))

    # 设计文档（汇总优先）
    design_candidates = []
    for pattern in DESIGN_DOC_SEARCH_PATHS:
        if '*' in pattern:
            design_candidates.extend(cwd.glob(pattern))
        else:
            path = cwd / pattern
            if path.exists():
                design_candidates.append(path)

    if design_candidates:
        result['design'] = str(_select_aggregate_file(design_candidates))

    # API 文档（汇总优先）
    api_candidates = []
    for pattern in API_DOC_SEARCH_PATHS:
        if '*' in pattern:
            api_candidates.extend(cwd.glob(pattern))
        else:
            path = cwd / pattern
            if path.exists():
                api_candidates.append(path)

    if api_candidates:
        result['api'] = str(_select_aggregate_file(api_candidates))

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


def _select_aggregate_file(candidates: List[Path]) -> Path:
    """
    从候选文件中选择汇总文件，如果没有则选第一个

    汇总文件特征：
    - 文件名含 all / overview / summary / index
    - 文件名含中文 总 / 全量 / 汇总 / 概览
    - 文件名含 requirements / prd（需求关键词）
    """
    if not candidates:
        raise ValueError("候选列表为空")

    # 优先级 1: 汇总关键词
    for candidate in candidates:
        name_lower = candidate.name.lower()
        if any(kw in name_lower for kw in AGGREGATE_KEYWORDS):
            return candidate

    # 优先级 2: 需求关键词（prd / requirements）
    for candidate in candidates:
        name_lower = candidate.name.lower()
        if any(kw in name_lower for kw in ['requirement', 'prd', 'spec', '需求']):
            return candidate

    # 优先级 3: 最短路径（最接近根的）
    candidates_sorted = sorted(candidates, key=lambda p: len(p.parts))
    return candidates_sorted[0]


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


# ============================================================
# 动态路径支持：用户在 /qa feature 时指定目录，自动分类文档
# ============================================================


# 文档类型启发式分类关键词
DOC_CLASSIFY_KEYWORDS = {
    'acceptance': [
        # 英文
        'acceptance', 'criteria', 'gherkin', 'feature-file',
        # 中文（acceptance 最先匹配，避免 '验收' 被 requirement 抢走）
        '验收',
    ],
    'api': [
        # 英文
        'api', 'endpoint', 'rest', 'graphql', 'rpc', 'contract',
        'openapi', 'swagger', 'protocol',
        # 中文
        '接口', '协议', '契约',
    ],
    'design': [
        # 英文
        'design', 'architecture', 'arch', 'tech', 'technical',
        'data-model', 'class-diagram', 'sequence', 'flow',
        'domain', 'capability', 'logical', 'physical',
        # 中文
        '设计', '架构', '技术方案', '数据模型', '类图', '流程', '领域',
    ],
    'requirement': [
        # 英文
        'requirement', 'req', 'prd', 'spec', 'user-story', 'story',
        'feature', 'epic', 'backlog',
        # 中文
        '需求', '规格', '故事', '产品需求', '功能',
    ],
}


# 排除的文件名关键词（明显不是需求/设计的）
EXCLUDE_KEYWORDS = [
    'readme', 'changelog', 'license', 'todo', 'history',
    'meeting', 'minutes', 'log', 'note', 'draft', 'wip',
    '会议', '记录', '草稿', '历史',
]


def discover_from_directory(directory: str, cwd: Path = Path('.')) -> Dict[str, Any]:
    """
    从用户指定目录中发现并分类文档

    支持用户在 `/qa feature 短信绑定 --docs <directory>` 时使用：
    - 自动扫描目录下所有 .md 文档
    - 根据文件名启发式分类为：需求 / 设计 / API / 验收 / 其他
    - 优先汇总文件（*-all.md / *-overview.md）

    Args:
        directory: 目录路径（可以是相对路径或绝对路径）
        cwd: 当前工作目录

    Returns:
        {
            'primary': str | None,        # 主需求文档
            'design': str | None,         # 主设计文档
            'api': str | None,            # 主 API 文档
            'acceptance': str | None,     # 验收标准
            'specs': List[str],           # 所有需求文档
            'all_designs': List[str],     # 所有设计文档
            'all_apis': List[str],        # 所有 API 文档
            'all_docs': List[str],        # 目录下所有 md
            'unclassified': List[str],    # 无法分类的文档
            'source': 'dynamic',
            'directory': str
        }
    """
    # 解析路径
    target_dir = Path(directory)
    if not target_dir.is_absolute():
        target_dir = cwd / directory

    # 兼容 Windows 反斜杠路径
    target_dir = Path(str(target_dir).replace('\\', '/'))

    if not target_dir.exists():
        return {
            'primary': None,
            'design': None,
            'api': None,
            'acceptance': None,
            'specs': [],
            'all_designs': [],
            'all_apis': [],
            'all_docs': [],
            'unclassified': [],
            'source': 'dynamic',
            'directory': str(target_dir),
            'error': f'目录不存在: {target_dir}'
        }

    # 扫描所有 md 文档（含子目录）
    all_md_files = list(target_dir.rglob('*.md'))

    # 分类
    classified = {
        'requirement': [],
        'design': [],
        'api': [],
        'acceptance': [],
        'unclassified': []
    }

    for md_file in all_md_files:
        category = classify_document(md_file)
        classified[category].append(md_file)

    # 在每个分类中选择主文档（汇总优先）
    primary = _select_aggregate_file(classified['requirement']) if classified['requirement'] else None
    design = _select_aggregate_file(classified['design']) if classified['design'] else None
    api = _select_aggregate_file(classified['api']) if classified['api'] else None
    acceptance = _select_aggregate_file(classified['acceptance']) if classified['acceptance'] else None

    # 如果没找到需求文档但有未分类文档，把未分类的当作潜在需求
    if not primary and classified['unclassified']:
        primary = _select_aggregate_file(classified['unclassified'])

    return {
        'primary': str(primary) if primary else None,
        'design': str(design) if design else None,
        'api': str(api) if api else None,
        'acceptance': str(acceptance) if acceptance else None,
        'specs': [str(p) for p in classified['requirement']],
        'all_designs': [str(p) for p in classified['design']],
        'all_apis': [str(p) for p in classified['api']],
        'all_docs': [str(p) for p in all_md_files],
        'unclassified': [str(p) for p in classified['unclassified']],
        'source': 'dynamic',
        'directory': str(target_dir)
    }


def classify_document(path: Path) -> str:
    """
    根据文件名启发式分类文档

    Returns:
        'requirement' | 'design' | 'api' | 'acceptance' | 'unclassified'
    """
    name_lower = path.stem.lower()
    parent_lower = path.parent.name.lower()

    # 第一优先级：父目录名
    if parent_lower in ('prd', 'requirements', 'requirement', 'specs', 'spec',
                         '需求', '产品需求'):
        return 'requirement'
    if parent_lower in ('design', 'architecture', 'arch', 'designs',
                         '设计', '架构'):
        return 'design'
    if parent_lower in ('api', 'apis', 'contracts', 'endpoints', '接口'):
        return 'api'
    if parent_lower in ('acceptance', 'testing', 'verification', '验收', '测试'):
        return 'acceptance'

    # 排除明显非需求/设计的文件
    if any(kw in name_lower for kw in EXCLUDE_KEYWORDS):
        return 'unclassified'

    # 按文件名匹配关键词
    for category, keywords in DOC_CLASSIFY_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return category

    return 'unclassified'


def merge_discovery_results(
    auto_result: Dict[str, Any],
    dynamic_result: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    合并自动发现和动态路径结果，动态优先

    用户既配置了 .qa-agent.yml，又通过命令行指定了目录时使用
    """
    if not dynamic_result:
        return auto_result

    # 动态结果优先
    merged = dict(auto_result)

    for key in ['primary', 'design', 'api', 'acceptance']:
        if dynamic_result.get(key):
            merged[key] = dynamic_result[key]

    # 合并文档列表
    for key in ['specs', 'all_docs']:
        if dynamic_result.get(key):
            merged[key] = list(set(merged.get(key, []) + dynamic_result[key]))

    if 'all_designs' in dynamic_result:
        merged['all_designs'] = dynamic_result['all_designs']
    if 'all_apis' in dynamic_result:
        merged['all_apis'] = dynamic_result['all_apis']
    if 'unclassified' in dynamic_result:
        merged['unclassified'] = dynamic_result['unclassified']

    merged['source'] = 'dynamic'
    merged['directory'] = dynamic_result.get('directory')

    return merged


