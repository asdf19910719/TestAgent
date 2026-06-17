"""
Bug 引用解析算法（P2-2）
"""

import re
from typing import Optional, List
from pathlib import Path

from .types import Bug


def resolve_bugfix_target(user_input: str, qa_dir: Path = Path('qa')) -> Optional[Bug]:
    """
    解析 /qa bugfix <reference> 的引用参数

    支持：
    - BUG-XXX (精确匹配)
    - TC-XXX-NNN (用例 ID，反查关联 bug)
    - #123 (issue 编号)
    - 关键词 (< 30 字符，模糊匹配)
    - 自然语言描述 (创建新 bug)

    Returns:
        Bug 对象，或 None（需要创建）
    """
    user_input = user_input.strip()

    # 优先级 1: BUG-XXX
    if re.match(r'^BUG-\d+$', user_input):
        return load_bug_by_id(user_input, qa_dir)

    # 优先级 2: TC-XXX-NNN (Phase 3 实现用例反查)
    if re.match(r'^TC-[A-Z]+-\d+$', user_input):
        print(f"[Bug引用] 用例 ID 反查 bug（Phase 3 实现）")
        return None

    # 优先级 3: #NNN (Phase 3 实现 issue 关联)
    if re.match(r'^#\d+$', user_input):
        print(f"[Bug引用] Issue 编号查询（Phase 3 实现）")
        return None

    # 优先级 4: 短关键词
    if len(user_input) < 30 and not re.search(r'[。.!?！？]', user_input):
        matches = fuzzy_search_bugs(user_input, qa_dir)
        if matches:
            if len(matches) == 1:
                return matches[0]
            else:
                print(f"[Bug引用] 找到 {len(matches)} 个匹配，请选择：")
                for i, bug in enumerate(matches[:5], 1):
                    print(f"  {i}. {bug.id}: {bug.title}")
                return matches[0]  # Phase 2 简化：返回第一个

    # 优先级 5: 自然语言描述 - 返回 None 表示需要创建
    return None


def load_bug_by_id(bug_id: str, qa_dir: Path) -> Optional[Bug]:
    """
    从 qa/bugs/<id>.yml 加载 Bug
    """
    from .yaml_serializer import BugSerializer
    return BugSerializer.load_by_id(bug_id, qa_dir)


def fuzzy_search_bugs(keyword: str, qa_dir: Path) -> List[Bug]:
    """
    模糊匹配 bug 标题和 repro_steps
    """
    from .yaml_serializer import BugSerializer

    all_bugs = BugSerializer.load_all(qa_dir, state_filter='open')

    matches = []
    keyword_lower = keyword.lower()

    for bug in all_bugs:
        score = 0
        if keyword_lower in bug.title.lower():
            score += 10
        if any(keyword_lower in step.lower() for step in bug.repro_steps):
            score += 5

        if score > 0:
            matches.append((bug, score))

    matches.sort(key=lambda x: x[1], reverse=True)
    return [bug for bug, _ in matches[:5]]


def create_bug_from_description(description: str, qa_dir: Path = Path('qa')) -> Bug:
    """
    从自然语言描述创建新 bug 记录
    """
    from datetime import datetime
    from .yaml_serializer import BugSerializer

    bug_id = BugSerializer.next_bug_id(qa_dir)

    # 从描述提取标题（取前 80 字符）
    title = description[:80] if len(description) > 80 else description

    bug = Bug(
        id=bug_id,
        title=title,
        state='open',
        severity='medium',
        priority='P2',
        related_cases=[],
        related_requirements=[],
        feature_id='',
        repro_steps=[description],
        expected='',
        actual='',
        created_at=datetime.now().isoformat(),
        created_by='user_via_qa_bugfix'
    )

    # 持久化
    filepath = BugSerializer.save(bug, qa_dir)

    print(f"[Bug引用] 已创建新 bug 记录：{bug_id} → {filepath}")

    return bug
