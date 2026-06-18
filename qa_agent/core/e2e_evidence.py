"""
E2E 执行证据检查模块

防止 AI "假 E2E"：标记 E2E PASS 但实际只做了静态检查。
检查真实浏览器操作证据：日志关键词、截图、视频。
"""

from pathlib import Path
from typing import Dict, Any, Tuple


# 浏览器操作证据关键词
BROWSER_INDICATORS = [
    'Browser launched',
    'chromium.launch',
    'firefox.launch',
    'webkit.launch',
    'page.goto',
    'page.click',
    'page.fill',
    'page.type',
    'page.locator',
    'page.waitFor',
    'page.screenshot',
    'browser.newPage',
    'page.evaluate',
]

# 静态检查特征（不算真正的 E2E）
STATIC_CHECK_INDICATORS = [
    'fs.existsSync',
    'fs.readFileSync',
    '.includes(',
    'indexOf(',
    'assert(exists(',
]


def check_e2e_execution_evidence(
    case_id: str,
    workspace: Path = Path('.')
) -> Tuple[bool, str]:
    """
    检查 E2E 用例是否有真实执行证据

    Args:
        case_id: 用例 ID
        workspace: 工作目录

    Returns:
        (has_evidence: bool, details: str)
    """
    run_dir = workspace / 'qa' / 'run'
    log_file = run_dir / f"{case_id}.log"

    evidence_items = []

    # 1. 检查日志文件
    if log_file.exists():
        try:
            log_content = log_file.read_text(encoding='utf-8', errors='ignore')

            # 检查浏览器操作证据
            browser_found = []
            for indicator in BROWSER_INDICATORS:
                if indicator in log_content:
                    browser_found.append(indicator)

            if browser_found:
                evidence_items.append(f"日志包含浏览器操作: {', '.join(browser_found[:3])}")
            else:
                # 检查是否是静态检查
                static_found = []
                for indicator in STATIC_CHECK_INDICATORS:
                    if indicator in log_content:
                        static_found.append(indicator)

                if static_found:
                    return False, f"日志仅包含静态检查: {', '.join(static_found[:3])}（不是真正的 E2E）"
                else:
                    return False, "日志无浏览器操作证据"

        except Exception as e:
            return False, f"日志读取失败: {e}"
    else:
        # 日志不存在，检查其他证据
        pass

    # 2. 检查截图
    screenshots_dir = run_dir / 'screenshots'
    if screenshots_dir.exists():
        screenshots = list(screenshots_dir.glob(f"{case_id}*.png")) + \
                     list(screenshots_dir.glob(f"{case_id}*.jpg"))
        if screenshots:
            evidence_items.append(f"截图: {len(screenshots)} 张")

    # 3. 检查视频
    videos_dir = run_dir / 'videos'
    if videos_dir.exists():
        videos = list(videos_dir.glob(f"{case_id}*.webm")) + \
                list(videos_dir.glob(f"{case_id}*.mp4"))
        if videos:
            evidence_items.append(f"视频: {len(videos)} 个")

    # 4. 检查 Playwright trace
    traces_dir = run_dir / 'traces'
    if traces_dir.exists():
        traces = list(traces_dir.glob(f"{case_id}*.zip"))
        if traces:
            evidence_items.append(f"Playwright trace: {len(traces)} 个")

    if evidence_items:
        return True, " | ".join(evidence_items)
    else:
        return False, "无任何 E2E 执行证据（无日志/截图/视频/trace）"


def check_all_e2e_cases(
    workspace: Path = Path('.')
) -> Dict[str, Any]:
    """
    检查所有标记为 E2E 的用例的执行证据

    Returns:
        {
            'total': 10,
            'with_evidence': 8,
            'without_evidence': 2,
            'cases_without_evidence': [
                {'case_id': 'TC-E2E-001', 'reason': '...'},
                ...
            ]
        }
    """
    from qa_agent.core.state_manager import StateManager

    state_mgr = StateManager()
    last_run = state_mgr.load_last_run()

    if not last_run:
        return {'total': 0, 'with_evidence': 0, 'without_evidence': 0, 'cases_without_evidence': []}

    # 读取 selection 中的用例
    selection = last_run.get('selection', {})
    case_ids = selection.get('case_ids', [])

    # 过滤出 E2E 级别用例（需要读取 YAML）
    e2e_cases = []
    for case_id in case_ids:
        # 简化：假设 case_id 中含 'e2e' / 'system' / 'acceptance' 的是 E2E
        # 真实实现应读取 YAML 确认 level
        if any(keyword in case_id.lower() for keyword in ['e2e', 'system', 'acceptance']):
            e2e_cases.append(case_id)

    # 检查每个 E2E 用例
    without_evidence = []
    with_evidence_count = 0

    for case_id in e2e_cases:
        has_evidence, details = check_e2e_execution_evidence(case_id, workspace)
        if has_evidence:
            with_evidence_count += 1
        else:
            without_evidence.append({
                'case_id': case_id,
                'reason': details,
            })

    return {
        'total': len(e2e_cases),
        'with_evidence': with_evidence_count,
        'without_evidence': len(without_evidence),
        'cases_without_evidence': without_evidence,
    }
