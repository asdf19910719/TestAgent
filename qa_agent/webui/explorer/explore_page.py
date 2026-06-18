#!/usr/bin/env python3
"""
页面探测脚本 — 支持多阶段交互式探测
使用 Playwright 访问目标页面，截图，提取关键交互元素，生成选择器策略。

三层探测：
  1. 基础层：内联 JS 快速提取按钮/输入框/链接等 → page-elements.json
  2. 交互层（可选）：执行 --actions 定义的交互序列（点击按钮、打开弹窗、选择选项），
     在每个 capture 点做 DOM 快照，合并所有阶段的元素
  3. 深度层：dom_exporter_all_in_one.js + dom_tree_simplifier.py
     → dom_export.json / dom_simplified.json / dom_interactive_elements.json

--actions JSON 格式：
  [
    {"action": "goto", "url": "https://example.com/other-tab"},
    {"action": "click", "selector": "button:has-text('创建')"},
    {"action": "wait", "ms": 2000},
    {"action": "capture", "name": "dialog_open"},
    {"action": "fill", "selector": "input[name='title']", "value": "test"},
    {"action": "click", "selector": "input[placeholder='请选择报告类型']"},
    {"action": "wait", "ms": 500},
    {"action": "click", "selector": "text='版本发布报告'"},
    {"action": "capture", "name": "form_expanded"}
  ]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print('错误: 请先安装 playwright（python -m pip install playwright）')
    raise SystemExit(1)

DOM_SCRIPTS_DIR = Path(__file__).parent / 'dom'
DOM_EXPORTER_JS = DOM_SCRIPTS_DIR / 'dom_exporter_all_in_one.js'

# 公共 DOM 元素提取（与 login 脚本共享同一实现）
from dom_elements_extractor import extract_page_elements, ELEMENTS_EXTRACT_JS


def extract_elements(page):
    """
    从页面 DOM 提取关键交互元素。
    已迁移至公共模块 dom_elements_extractor.py，此处保留作向后兼容别名。
    """
    return extract_page_elements(page)


_LOGIN_URL_KEYWORDS = ('/login', '/signin', '/sso/', '/auth/', '/cas/')
_LOGIN_INDICATORS = ('input[type="password"]', 'input[name="password"]')


def _detect_unauthenticated(page) -> str | None:
    """Return a reason string if the page appears to be an unauthenticated/login page."""
    current = page.url.lower()
    for kw in _LOGIN_URL_KEYWORDS:
        if kw in current:
            return f'当前 URL ({page.url}) 包含登录关键词 "{kw}"'
    for sel in _LOGIN_INDICATORS:
        try:
            if page.locator(sel).count() > 0:
                return f'页面包含密码输入框 ({sel})，疑似处于登录页'
        except Exception:
            pass
    return None


def _take_page_screenshot(page, screenshot_dir, name):
    """截取页面截图，full_page 失败时回退到仅视口。"""
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f'{name}_{ts}.png'
    path = Path(screenshot_dir) / filename
    try:
        page.screenshot(path=str(path), full_page=True, timeout=10000)
    except Exception:
        try:
            page.screenshot(path=str(path), full_page=False, timeout=5000)
        except Exception as e:
            print(f'警告: 截图失败({name}): {e}')
            return None
    print(f'截图: {path}')
    return str(path)


def _execute_action(page, action_def):
    """
    执行单个交互动作。支持的 action 类型：
    - click / fill / select_text / press / wait / hover / goto
    - wait_for_field: 轮询等待字段 visible+enabled（级联场景）
    - capture: （由调用方处理，这里不执行）
    """
    act = action_def.get('action', '')
    selector = action_def.get('selector', '')
    value = action_def.get('value', '')
    text = action_def.get('text', '')
    timeout = action_def.get('timeout', 5000)

    try:
        if act == 'click':
            loc = page.locator(selector).first
            try:
                loc.click(timeout=timeout)
            except Exception:
                loc.click(timeout=timeout, force=True)
        elif act == 'fill':
            page.locator(selector).first.fill(value, timeout=timeout)
        elif act == 'select_text':
            page.locator(selector).first.click(timeout=timeout)
            try:
                page.wait_for_load_state('domcontentloaded', timeout=2000)
            except Exception:
                page.wait_for_timeout(300)
            option_selectors = [
                f'[role="option"]:has-text("{text}")',
                f'li:has-text("{text}")',
                f'.el-select-dropdown__item:has-text("{text}")',
            ]
            clicked = False
            for opt_sel in option_selectors:
                try:
                    page.locator(opt_sel).first.click(timeout=3000)
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                page.get_by_text(text, exact=False).first.click(timeout=timeout)
            page.keyboard.press('Escape')
        elif act == 'press':
            page.keyboard.press(value or text)
        elif act == 'wait':
            ms = action_def.get('ms', 1000)
            page.wait_for_timeout(ms)
        elif act == 'hover':
            page.locator(selector).first.hover(timeout=timeout)
        elif act == 'wait_for_field':
            poll_interval = action_def.get('poll_ms', 500)
            max_wait = timeout
            elapsed = 0
            loc = page.locator(selector).first
            while elapsed < max_wait:
                try:
                    if loc.is_visible() and loc.is_enabled():
                        break
                except Exception:
                    pass
                page.wait_for_timeout(poll_interval)
                elapsed += poll_interval
            else:
                print(f'  警告: wait_for_field({selector}) 超时 {max_wait}ms')
                return False
        elif act == 'goto':
            url = action_def.get('url', '')
            if not url:
                print(f'  警告: goto 动作缺少 url 参数，跳过')
                return False
            page.goto(url, wait_until='domcontentloaded', timeout=timeout)
            try:
                page.wait_for_load_state('networkidle', timeout=3000)
            except Exception:
                pass
        elif act == 'capture':
            pass
        else:
            print(f'  警告: 未知动作 {act}，跳过')
            return False
    except Exception as e:
        print(f'  警告: 动作 {act}({selector}) 失败: {e}')
        return False
    return True


def _capture_page_state(page):
    """捕获当前页面状态快照（含字段级 readiness），用于前后对比检测状态变化。"""
    state = {
        'url': page.url,
        'title': '',
    }
    try:
        state['title'] = page.title()
    except Exception:
        pass
    try:
        counts = page.evaluate('''() => {
            const inputs = document.querySelectorAll(
                'input:not([type="hidden"]), textarea, select, [role="combobox"]'
            );
            const dialogs = document.querySelectorAll(
                '[role="dialog"]:not([style*="display: none"]):not([style*="display:none"]), '
                + '.el-dialog:not([style*="display: none"]):not([style*="display:none"]), '
                + '.ant-modal:not([style*="display: none"]):not([style*="display:none"])'
            );
            const iframes = document.querySelectorAll('iframe');

            let disabled_fields = 0;
            let selects_with_options = 0;
            let total_options = 0;
            let filled_fields = 0;
            inputs.forEach(el => {
                if (el.disabled || el.getAttribute('disabled') !== null) disabled_fields++;
                const tag = el.tagName.toLowerCase();
                if (tag === 'select' && el.options && el.options.length > 1) {
                    selects_with_options++;
                    total_options += el.options.length;
                }
                if ((tag === 'input' || tag === 'textarea') && el.value && el.value.trim()) {
                    filled_fields++;
                } else if (tag === 'select' && el.selectedIndex > 0) {
                    filled_fields++;
                }
            });
            document.querySelectorAll('[role="combobox"]').forEach(el => {
                const listId = el.getAttribute('aria-controls') || el.getAttribute('list');
                if (listId) {
                    const listEl = document.getElementById(listId);
                    if (listEl && listEl.children.length > 0) {
                        selects_with_options++;
                        total_options += listEl.children.length;
                    }
                }
            });

            return {
                form_fields: inputs.length,
                visible_dialogs: dialogs.length,
                iframes: iframes.length,
                disabled_fields: disabled_fields,
                selects_with_options: selects_with_options,
                total_options: total_options,
                filled_fields: filled_fields,
            };
        }''')
        state.update(counts)
    except Exception:
        state.update({
            'form_fields': 0, 'visible_dialogs': 0, 'iframes': 0,
            'disabled_fields': 0, 'selects_with_options': 0, 'total_options': 0, 'filled_fields': 0,
        })
    return state


def _detect_state_changes(before, after):
    """对比两个页面状态快照，返回检测到的变化列表（含字段级信号）。"""
    changes = []
    if before['url'] != after['url']:
        changes.append('url_change')
    if before['title'] != after['title']:
        changes.append('title_change')
    dialog_diff = after.get('visible_dialogs', 0) - before.get('visible_dialogs', 0)
    if dialog_diff > 0:
        changes.append('dialog_appear')
    elif dialog_diff < 0:
        changes.append('dialog_close')
    field_diff = after.get('form_fields', 0) - before.get('form_fields', 0)
    if field_diff >= 3:
        changes.append('form_expand')
    elif field_diff <= -3:
        changes.append('form_shrink')
    elif field_diff > 0:
        changes.append('field_appear')
    iframe_diff = after.get('iframes', 0) - before.get('iframes', 0)
    if iframe_diff != 0:
        changes.append('iframe_change')

    disabled_before = before.get('disabled_fields', 0)
    disabled_after = after.get('disabled_fields', 0)
    if disabled_before > disabled_after and disabled_before > 0:
        changes.append('field_enable')

    opts_before = after.get('selects_with_options', 0) - before.get('selects_with_options', 0)
    total_opts_diff = after.get('total_options', 0) - before.get('total_options', 0)
    if opts_before > 0 or total_opts_diff >= 3:
        changes.append('options_loaded')

    filled_before = before.get('filled_fields', 0)
    filled_after = after.get('filled_fields', 0)
    if filled_after > filled_before:
        changes.append('field_prefilled')

    return changes


def _diff_elements(prev_elements, curr_elements):
    """计算两个元素集合的差异，返回新增元素的文本摘要列表。"""
    prev_keys = set()
    for e in prev_elements:
        prev_keys.add((e.get('type', ''), e.get('text', '')))
    new_texts = []
    for e in curr_elements:
        key = (e.get('type', ''), e.get('text', ''))
        if key not in prev_keys and e.get('text', '').strip():
            label = e.get('text', '').strip()
            if len(label) > 30:
                label = label[:30] + '...'
            new_texts.append(label)
    return new_texts[:15]


def _compute_exploration_confidence(stages):
    """
    计算探索置信度（0.0 ~ 1.0）。
    权重侧重于关键状态变化是否被覆盖，含字段级信号（级联场景）。
    """
    if not stages:
        return 0.0

    score = 0.0
    total_elements = sum(s.get('elements_count', 0) for s in stages)
    all_changes = [c for s in stages for c in s.get('state_changes', [])]
    has_dialog = 'dialog_appear' in all_changes
    has_url_change = 'url_change' in all_changes
    has_form_expand = 'form_expand' in all_changes
    has_field_appear = 'field_appear' in all_changes
    has_field_enable = 'field_enable' in all_changes
    has_options_loaded = 'options_loaded' in all_changes
    none_only_stages = sum(
        1 for s in stages if s.get('state_changes', ['none']) == ['none']
    )
    stages_with_new_elements = sum(
        1 for s in stages if len(s.get('new_elements_summary', [])) > 0
    )

    score += min(len(stages) * 0.12, 0.36)

    if has_dialog:
        score += 0.15
    if has_url_change:
        score += 0.15
    if has_form_expand:
        score += 0.10

    cascade_signals = sum([has_field_appear, has_field_enable, has_options_loaded])
    score += min(cascade_signals * 0.05, 0.10)

    if len(stages) > 1 and stages_with_new_elements > 0:
        discovery_ratio = stages_with_new_elements / len(stages)
        score += min(discovery_ratio * 0.15, 0.15)

    if total_elements >= 20:
        score += 0.05
    elif total_elements >= 10:
        score += 0.03

    if len(stages) > 1 and none_only_stages > len(stages) * 0.5:
        score -= 0.10

    return max(0.0, min(score, 1.0))


def _run_interactive_exploration(page, actions, screenshot_dir, extract_fn):
    """
    执行多阶段交互式探测（含状态变化检测）。
    在每个 capture 点提取 DOM 元素、截图、检测状态变化，
    并同步提取当前 DOM 状态的 smart XPath。
    返回 (stages, accumulated_dom_interactive)。
    """
    stages = []
    dom_ie_accumulated = []
    prev_state = _capture_page_state(page)
    prev_elements = []
    auto_capture_count = 0
    AUTO_CAPTURE_MAX = 3

    def _do_capture(name):
        nonlocal prev_state, prev_elements
        # 等待 DOM 稳定再做快照
        try:
            page.wait_for_load_state('domcontentloaded', timeout=2000)
        except Exception:
            page.wait_for_timeout(300)
        curr_state = _capture_page_state(page)
        state_changes = _detect_state_changes(prev_state, curr_state)

        print(f'[交互探测] 阶段 {name}: 提取 DOM...')
        elems = extract_fn(page)
        shot = _take_page_screenshot(page, screenshot_dir, f'explore_{name}')

        # 在当前页面状态提取 smart XPath（绑定到此刻的 DOM）
        ie_list = _extract_dom_interactive(page, stage_name=name)
        dom_ie_accumulated.extend(ie_list)

        new_elem_texts = _diff_elements(prev_elements, elems)

        # ── 场景 C：探索阶段视觉辅助（AQE_VISION_EXPLORE=0 可关闭）──
        vision_analysis = {}
        if shot and os.environ.get('AQE_VISION_EXPLORE', '1') != '0':
            try:
                _va_dir = str(Path(__file__).resolve().parent.parent.parent / 'uitest-visual-assist' / 'scripts')
                if _va_dir not in sys.path:
                    sys.path.insert(0, _va_dir)
                from vision_detect import detect_vision_capability
                from vision_client import VisionClient
                vc = detect_vision_capability()
                if vc.get('available'):
                    client = VisionClient()
                    img_bytes = Path(shot).read_bytes()
                    _explore_prompt = (
                        '分析这个Web页面截图，返回 JSON：'
                        '{"page_type": "列表页|表单页|详情页|仪表盘|登录页|其他",'
                        ' "key_regions": [{"name": "...", "description": "...", "has_dynamic_content": true}],'
                        ' "canvas_detected": false,'
                        ' "visual_complexity": "low|medium|high",'
                        ' "suggestions": ["..."]}'
                    )
                    result = client.query_image_sync(img_bytes, _explore_prompt)
                    if isinstance(result, dict):
                        vision_analysis = result
                    elif isinstance(result, str):
                        vision_analysis = {'raw_response': result}
            except Exception as e:
                logging.getLogger(__name__).debug("视觉分析跳过: %s", e)

        stage_info = {
            'name': name,
            'elements_count': len(elems),
            'elements': elems,
            'screenshot': shot,
            'url': curr_state['url'],
            'state_changes': state_changes if state_changes else ['none'],
            'new_elements_summary': new_elem_texts,
            'vision_analysis': vision_analysis,
            'field_snapshot': {
                'form_fields': curr_state.get('form_fields', 0),
                'disabled_fields': curr_state.get('disabled_fields', 0),
                'selects_with_options': curr_state.get('selects_with_options', 0),
                'total_options': curr_state.get('total_options', 0),
            },
        }
        stages.append(stage_info)

        change_desc = ', '.join(state_changes) if state_changes else '无变化'
        new_desc = f', 新增元素: {len(new_elem_texts)}' if new_elem_texts else ''
        cascade_desc = ''
        cascade_signals = [c for c in state_changes if c in ('field_appear', 'field_enable', 'options_loaded')]
        if cascade_signals:
            cascade_desc = f', 级联信号: {"+".join(cascade_signals)}'
        print(f'[交互探测] 阶段 {name}: {len(elems)} 个元素, 状态变化: {change_desc}{new_desc}{cascade_desc}')

        prev_state = curr_state
        prev_elements = elems
        return state_changes

    for i, action_def in enumerate(actions):
        act = action_def.get('action', '')
        if act == 'capture':
            name = action_def.get('name', f'stage_{len(stages)}')
            _do_capture(name)
        else:
            desc = action_def.get('selector', action_def.get('text', ''))
            print(f'[交互探测] 执行: {act} {desc}')
            success = _execute_action(page, action_def)
            if not success:
                print(f'[交互探测] 警告: 动作失败，后续 capture 可能不准确')
                continue

            # B-3: dialog_appear 自动 capture（收敛版）
            # click 和 press（如 Enter 提交）可能触发弹窗；fill 单独不触发
            if act in ('click', 'press') and auto_capture_count < AUTO_CAPTURE_MAX:
                upcoming_has_capture = any(
                    a.get('action') == 'capture'
                    for a in actions[i+1:min(i+4, len(actions))]
                )
                if not upcoming_has_capture:
                    # 等待潜在弹窗或页面变化稳定
                    try:
                        page.wait_for_load_state('domcontentloaded', timeout=3000)
                    except Exception:
                        page.wait_for_timeout(500)
                    post_state = _capture_page_state(page)
                    post_changes = _detect_state_changes(prev_state, post_state)
                    if 'dialog_appear' in post_changes:
                        auto_capture_count += 1
                        auto_name = f'auto_dialog_{auto_capture_count}'
                        print(f'[自动补捕] 检测到 dialog_appear，自动 capture: {auto_name}')
                        _do_capture(auto_name)

    return stages, dom_ie_accumulated


def main():
    parser = argparse.ArgumentParser(description='WebUI 页面探测')
    parser.add_argument('--url', required=True, help='目标页面 URL')
    parser.add_argument('--state', '--state-file', default=None, help='浏览器状态文件路径（已登录状态）')
    parser.add_argument('--screenshot-dir', default='.', help='截图保存目录')
    parser.add_argument('--output', '--output-dir', '--output-file', required=True, help='输出 JSON 文件路径')
    parser.add_argument('--browser', default='chromium', choices=['chromium', 'chrome'],
                        help='浏览器类型')
    parser.add_argument('--headless', action='store_true', default=True,
                        help='无头模式')
    parser.add_argument('--actions', default=None,
                        help='多阶段交互探测动作序列（JSON 文件路径或 JSON 字符串）')
    args = parser.parse_args()

    screenshot_dir = Path(args.screenshot_dir)
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 解析 actions
    actions = None
    if args.actions:
        actions_input = args.actions.strip()
        if actions_input.startswith('['):
            try:
                actions = json.loads(actions_input)
            except json.JSONDecodeError as e:
                print(f'警告: --actions JSON 解析失败({e})，跳过交互探测')
        else:
            actions_path = Path(actions_input)
            if actions_path.exists():
                try:
                    actions = json.loads(actions_path.read_text(encoding='utf-8'))
                except (json.JSONDecodeError, OSError) as e:
                    print(f'警告: --actions 文件解析失败({e})，跳过交互探测')
            else:
                print(f'警告: --actions 文件不存在({actions_input})，跳过交互探测')

    with sync_playwright() as p:
        import os as _os
        _headless = _os.environ.get('FORCE_HEADED') != '1'
        launch_args = {'headless': _headless}
        if args.browser == 'chrome':
            launch_args['channel'] = 'chrome'
        browser = p.chromium.launch(**launch_args)

        context_args = {'viewport': {'width': 1920, 'height': 1080}}
        if args.state and Path(args.state).exists():
            context_args['storage_state'] = args.state
            print(f'使用已有登录状态: {args.state}')

        context = browser.new_context(**context_args)
        page = context.new_page()

        print(f'访问页面: {args.url}')
        page.goto(args.url, wait_until='domcontentloaded', timeout=30000)
        try:
            page.wait_for_load_state('networkidle', timeout=3000)
        except Exception:
            pass

        _unauth_reason = _detect_unauthenticated(page)
        if _unauth_reason:
            has_state = bool(args.state and Path(args.state).exists())
            if not has_state:
                print(f'错误: 页面疑似未登录 — {_unauth_reason}')
                print(f'  --state 参数未提供或文件不存在，请先执行登录（uitest-login-handler）再探索')
                _take_page_screenshot(page, screenshot_dir, 'explore_unauthenticated')
                browser.close()
                sys.exit(1)
            else:
                print(f'警告: 页面疑似未登录 — {_unauth_reason}（已提供 --state，login-state 可能已过期）')

        # ── 阶段 0：静态提取（入口页） ──
        screenshot_path = _take_page_screenshot(page, screenshot_dir, 'explore_initial')

        print('提取页面元素（入口页）...')
        elements = extract_elements(page)
        print(f'提取到 {len(elements)} 个交互元素')

        # 在入口页状态提取 smart XPath（绑定到当前 DOM 状态）
        accumulated_dom_ie = _extract_dom_interactive(page, stage_name='initial')

        all_stages = [{
            'name': 'initial',
            'elements_count': len(elements),
            'elements': elements,
            'screenshot': screenshot_path,
            'url': page.url,
            'state_changes': ['entry_page'],
            'new_elements_summary': [],
        }]

        # ── 阶段 1-N：交互式探测（如果提供了 --actions） ──
        if actions:
            print(f'\n[交互探测] 开始执行 {len(actions)} 个动作...')
            interaction_stages, stage_dom_ie = _run_interactive_exploration(
                page, actions, screenshot_dir, extract_elements
            )
            all_stages.extend(interaction_stages)
            accumulated_dom_ie.extend(stage_dom_ie)
            print(f'[交互探测] 完成，共 {len(interaction_stages)} 个捕获阶段')

        # 合并所有阶段的元素（去重：按 text+type 去重，保留后阶段的）
        merged_elements = []
        seen_keys = set()
        for stage in reversed(all_stages):
            for elem in stage.get('elements', []):
                key = (elem.get('type', ''), elem.get('text', ''), str(elem.get('selectors', '')))
                if key not in seen_keys:
                    seen_keys.add(key)
                    merged_elements.append(elem)
        merged_elements.reverse()

        # 重新编号
        for i, elem in enumerate(merged_elements, 1):
            elem['id'] = f'elem_{i}'

        # 构建输出
        result = {
            'url': page.url,
            'title': page.title(),
            'screenshot': screenshot_path,
            'timestamp': datetime.now().isoformat(),
            'elements_count': len(merged_elements),
            'elements': merged_elements,
        }
        if len(all_stages) > 1:
            result['exploration_stages'] = []
            for s in all_stages:
                stage_meta = {
                    'name': s['name'],
                    'elements_count': s['elements_count'],
                    'screenshot': s.get('screenshot'),
                }
                if 'url' in s:
                    stage_meta['url'] = s['url']
                if 'state_changes' in s:
                    stage_meta['state_changes'] = s['state_changes']
                if 'new_elements_summary' in s:
                    stage_meta['new_elements_summary'] = s['new_elements_summary']
                if 'field_snapshot' in s:
                    stage_meta['field_snapshot'] = s['field_snapshot']
                if s.get('vision_analysis'):
                    stage_meta['vision_analysis'] = s['vision_analysis']
                result['exploration_stages'].append(stage_meta)

        # ── 探索置信度计算 ──────────────────────────────────────
        confidence = _compute_exploration_confidence(all_stages)
        result['exploration_confidence'] = round(confidence, 2)

        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'输出: {output_path} (合并 {len(all_stages)} 个阶段，共 {len(merged_elements)} 个元素, 置信度: {confidence:.0%})')

        # ── 深度 DOM 导出（合并所有阶段的 smart XPath） ──
        dom_output_dir = output_path.parent
        _run_deep_dom_export(page, dom_output_dir,
                             accumulated_elements=accumulated_dom_ie)

        # ── 将 smart XPath 写入 page-elements.json ──
        _merge_smart_xpath_into_page_elements(output_path, dom_output_dir)

        context.close()
        browser.close()

    print(str(output_path))


def _ensure_dom_exporter_injected(page, _cache={}):
    """
    确保 dom_exporter_all_in_one.js 已注入当前页面。
    SPA 内不跳转不需要重复注入；跨页面导航后需要重新注入。
    返回 True 表示注入成功/已存在，False 表示不可用。
    """
    if not DOM_EXPORTER_JS.exists():
        return False
    try:
        already = page.evaluate('typeof exportDOMTreeWithXPath === "function"')
        if already:
            return True
    except Exception:
        pass
    js_code = DOM_EXPORTER_JS.read_text(encoding='utf-8')
    try:
        page.evaluate(js_code)
        return True
    except Exception as e:
        print(f'警告: dom_exporter JS 注入失败({e})')
        return False


def _extract_dom_interactive(page, stage_name=''):
    """
    在当前页面状态下提取可交互元素（含 smart XPath）。
    轻量调用：注入 JS → 导出 → 精简 → 提取交互元素 → 返回 list。
    不写磁盘，适合在每个 capture 点调用。
    """
    if not _ensure_dom_exporter_injected(page):
        return []

    try:
        if str(DOM_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(DOM_SCRIPTS_DIR))
        from dom_tree_simplifier import DOMTreeSimplifier
        from playwright_dom_export import extract_interactive_elements
    except ImportError as e:
        print(f'警告: 导入依赖失败({e})，跳过 smart XPath 提取')
        return []

    try:
        raw_result = page.evaluate('''
            async () => {
                return await exportDOMTreeWithXPath("export", {
                    enableXPath: true,
                    needDownload: false,
                    debug: false,
                    checkViewport: true,
                    viewportRatio: 0.05,
                    checkCoverage: false,
                    checkOverflow: true,
                    onlyVisible: true,
                });
            }
        ''')
    except Exception as e:
        print(f'警告: DOM 导出执行失败({e})')
        return []

    if not raw_result:
        return []

    simplifier = DOMTreeSimplifier(
        truncate_text_length=150,
        filter_non_text_content=False,
        visible_only=True,
        node_size_threshold=4,
    )
    simplified = simplifier.simplify_dom_tree(raw_result, output_format='tree')
    interactive = extract_interactive_elements(simplified)
    tag = f' [{stage_name}]' if stage_name else ''
    print(f'[smart XPath]{tag} 当前页面状态提取到 {len(interactive)} 个可交互元素')
    return interactive


def _run_deep_dom_export(page, output_dir: Path, accumulated_elements=None):
    """
    完整深度 DOM 导出：生成 dom_export.json / dom_simplified.json /
    dom_interactive_elements.json。

    如果 accumulated_elements 不为空，将其与当前页面的元素合并（按 xpath 去重，
    后者覆盖前者），确保多阶段探索的所有元素都有 smart XPath。
    """
    if not DOM_EXPORTER_JS.exists():
        print(f'警告: DOM 导出脚本不存在({DOM_EXPORTER_JS})，跳过深度导出')
        return

    try:
        if str(DOM_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(DOM_SCRIPTS_DIR))
        from dom_tree_simplifier import DOMTreeSimplifier
        from playwright_dom_export import extract_interactive_elements
    except ImportError as e:
        print(f'警告: 无法导入依赖({e})，跳过深度导出')
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    if not _ensure_dom_exporter_injected(page):
        return

    print('[深度DOM] 导出 DOM 树和 XPath...')
    try:
        raw_result = page.evaluate('''
            async () => {
                return await exportDOMTreeWithXPath("export", {
                    enableXPath: true,
                    needDownload: false,
                    debug: false,
                    checkViewport: true,
                    viewportRatio: 0.05,
                    checkCoverage: false,
                    checkOverflow: true,
                    onlyVisible: true,
                });
            }
        ''')
    except Exception as e:
        print(f'警告: DOM 导出执行失败({e})，跳过深度导出')
        return

    if not raw_result:
        print('警告: DOM 导出返回空结果，跳过后续精简')
        return

    raw_path = output_dir / 'dom_export.json'
    raw_path.write_text(json.dumps(raw_result, ensure_ascii=False, indent=2), encoding='utf-8')
    raw_xpath_count = len(raw_result.get('mockIdToXPath', {}))
    print(f'[深度DOM] 阶段1 完成: dom_export.json ({raw_xpath_count} 个元素)')

    simplifier = DOMTreeSimplifier(
        truncate_text_length=150,
        filter_non_text_content=False,
        visible_only=True,
        node_size_threshold=4,
    )
    simplified = simplifier.simplify_dom_tree(raw_result, output_format='tree')
    simplified_path = output_dir / 'dom_simplified.json'
    simplified_path.write_text(json.dumps(simplified, ensure_ascii=False, indent=2), encoding='utf-8')
    simplified_count = len(simplified.get('mockIdToXPath', {}))
    print(f'[深度DOM] 阶段2 完成: dom_simplified.json ({simplified_count} 个元素)')

    current_interactive = extract_interactive_elements(simplified)

    # 合并多阶段累积的元素：按 xpath 去重，当前阶段（最新状态）优先
    all_elements = {}
    if accumulated_elements:
        for ie in accumulated_elements:
            xp = ie.get('xpath', '')
            if xp:
                all_elements[xp] = ie
    for ie in current_interactive:
        xp = ie.get('xpath', '')
        if xp:
            all_elements[xp] = ie
    merged_list = list(all_elements.values())

    interactive_path = output_dir / 'dom_interactive_elements.json'
    interactive_path.write_text(json.dumps({
        'url': page.url,
        'total_interactive_elements': len(merged_list),
        'pipeline': 'js_export → python_simplify → extract (multi-stage)',
        'elements': merged_list,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    prev_only = len(accumulated_elements or [])
    curr_only = len(current_interactive)
    print(f'[深度DOM] 阶段3 完成: dom_interactive_elements.json '
          f'(累积 {prev_only} + 当前 {curr_only} → 去重后 {len(merged_list)} 个可交互元素)')


def _merge_smart_xpath_into_page_elements(page_elements_path: Path, dom_output_dir: Path):
    """
    用 dom_interactive_elements.json 的元素直接替换 page-elements.json 的元素列表。

    dom_interactive_elements.json 中的每个元素已经携带经过唯一性验证的 smart XPath，
    它就是元素的唯一标识，不需要做任何"匹配"。

    保留 page-elements.json 的元数据（url, title, timestamp, exploration_stages,
    exploration_confidence 等），只替换 elements 数组。

    Schema 契约（element_source='smart_xpath' 时）：
    - 主字段：id, type, text, smart_xpath, selectors, attributes, rect, element_source
    - 兼容字段：input_type（仅 input/textarea 有值）, options（select 为 None 表示数据源不提供）
    - mock_id：来自 DOM 导出的内部标识
    """
    dom_ie_path = dom_output_dir / 'dom_interactive_elements.json'
    if not dom_ie_path.exists():
        return

    try:
        pe_data = json.loads(page_elements_path.read_text(encoding='utf-8'))
        dom_ie_data = json.loads(dom_ie_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'[smart XPath] 读取文件失败: {e}')
        return

    ie_list = dom_ie_data.get('elements', [])
    if not ie_list:
        return

    old_count = pe_data.get('elements_count', 0)
    new_elements = []
    for i, ie in enumerate(ie_list, 1):
        xpath = ie.get('xpath', '')
        if not xpath:
            continue

        tag = ie.get('tag', '')
        dom_type_attr = ie.get('type', '')
        if tag in ('button', 'a'):
            elem_type = 'button'
            input_type = None
        elif tag in ('input', 'textarea'):
            elem_type = 'input'
            input_type = dom_type_attr or 'text'
        elif tag in ('select',) or ie.get('role') == 'combobox':
            elem_type = 'select'
            input_type = None
        else:
            elem_type = 'button' if 'BUTTON' in dom_type_attr else 'input' if 'FORM' in dom_type_attr else 'link'
            input_type = None

        iframe_chain = ie.get('iframe_chain') or []
        selectors = [{
            'strategy': 'xpath',
            'value': xpath,
            'priority': 0,
            'in_iframe': ie.get('in_iframe', False),
            'iframe_chain': iframe_chain,
        }]
        placeholder = ie.get('placeholder', '')
        if placeholder:
            selectors.append({'strategy': 'placeholder', 'value': f'[placeholder="{placeholder}"]', 'priority': 4})
        html_id = ie.get('id', '')
        if html_id:
            selectors.append({'strategy': 'css', 'value': f'#{html_id}', 'priority': 1})

        elem = {
            'id': f'elem_{i}',
            'type': elem_type,
            'text': (ie.get('text', '') or '').strip()[:100],
            'smart_xpath': xpath,
            'selectors': selectors,
            'attributes': {
                'visible': True,
                'tag': tag,
                'role': ie.get('role', ''),
                'class': ie.get('class', ''),
                'name': ie.get('name', ''),
                'placeholder': placeholder,
            },
            'rect': ie.get('rect', {}),
            'mock_id': ie.get('mock_id', '') or f'sx_{hashlib.md5(xpath.encode()).hexdigest()[:8]}',
        }
        if elem_type == 'input':
            elem['input_type'] = input_type
        if elem_type == 'select':
            elem['options'] = None
        new_elements.append(elem)

    pe_data['elements'] = new_elements
    pe_data['elements_count'] = len(new_elements)
    pe_data['element_source'] = 'smart_xpath'

    page_elements_path.write_text(
        json.dumps(pe_data, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'[smart XPath] page-elements.json 元素已替换: {old_count} → {len(new_elements)} (源: dom_interactive_elements.json)')


if __name__ == '__main__':
    main()
