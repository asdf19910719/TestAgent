#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一版 HTML 测试报告模板
视觉风格参照 references/test_report_template.html：
  - 紫色渐变统计栏、卡片式用例布局、emoji 区块标题、结构化断言展示
增强功能：
  - 搜索过滤：按状态/分类/关键词筛选
  - 折叠展开：每条用例详情可独立展开/折叠
  - 请求体展示：展示 JSON request body
  - 响应头突出展示：独立区块展示完整响应头
  - 饼图统计：通过/失败/错误比例可视化
  - 用例分类标签：[正常] [边界值] [空值] [类型错误] 等
"""

import json
import os
import re
from datetime import datetime
from html import escape


def _esc(val):
    """HTML 转义"""
    if val is None:
        return ''
    return escape(str(val))


def _format_json(obj):
    """安全格式化 JSON，失败则原样返回"""
    if obj is None:
        return '(无)'
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            return escape(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            return escape(obj) if obj else '(无)'
    try:
        return escape(json.dumps(obj, ensure_ascii=False, indent=2))
    except Exception:
        return escape(str(obj))


def _render_headers_block(headers: dict) -> str:
    """渲染请求头/响应头为 HTML（JSON 格式化）"""
    if not headers:
        return '<span class="empty-hint">(无)</span>'
    try:
        return '<pre>' + escape(json.dumps(headers, ensure_ascii=False, indent=2)) + '</pre>'
    except Exception:
        rows = []
        for k, v in headers.items():
            rows.append(f'{_esc(k)}: {_esc(v)}')
        return '<pre>' + '\n'.join(rows) + '</pre>'


def _extract_category(description: str) -> str:
    """从描述中提取用例分类标签，如 [正常] [边界值] 等"""
    if description.startswith('[') and ']' in description:
        category = description[1:description.index(']')]
        # 将所有场景测试统一归类为"场景"
        if category.startswith('场景'):
            return '场景'
        return category
    return ''


def _extract_endpoint_title(source_file: str, cases: list) -> str:
    """从文件名或用例信息提取接口标题（用于单接口分组的 Level 1 标题）

    例如：test_api_post_review_addAdvice.py → POST /review/addAdvice
    如果从文件名无法提取，则使用第一个用例的 HTTP 方法 + URL 路径
    """
    if source_file:
        # 去掉 test_api_ 前缀和 .py 后缀
        name = source_file
        if name.startswith('test_api_'):
            name = name[len('test_api_'):]
        if name.endswith('.py'):
            name = name[:-3]

        # 尝试提取 HTTP 方法（首段可能是 get/post/put/delete/patch）
        parts = name.split('_', 1)
        method_candidates = {'get', 'post', 'put', 'delete', 'patch'}
        if len(parts) >= 2 and parts[0].lower() in method_candidates:
            method = parts[0].upper()
            # 将剩余的下划线路径转为 / 分隔，保留驼峰
            path_parts = parts[1].split('_')
            path = '/' + '/'.join(path_parts)
            return f'{method} {path}'

    # 兜底：使用第一个用例的 HTTP 信息
    if cases:
        first = cases[0]
        method = first.get('method', '')
        url = first.get('url', '')
        if url and '://' in url:
            # 提取路径部分
            after_scheme = url.split('://', 1)[1]
            path = '/' + after_scheme.split('/', 1)[1] if '/' in after_scheme else '/'
        elif url:
            path = url
        else:
            path = ''
        if method and path:
            return f'{method} {path}'

    return source_file or '未知接口'


def _render_auxiliary_timeline(aux_steps: list, case_idx: int, sub_idx: int) -> str:
    """渲染操作时序区块（前置/主请求/后置步骤）

    Args:
        aux_steps: 辅助步骤列表，每个步骤含 role('pre'/'main'/'post') 字段
        case_idx: 用例分组索引
        sub_idx: 用例在分组内的索引
    """
    total = len(aux_steps)
    parts = []

    for step_idx, step in enumerate(aux_steps):
        role = step.get('role', 'pre')
        step_type = step.get('step_type', 'http')
        duration_ms = step.get('execution_time', 0)
        step_id = f'{case_idx}-{sub_idx}-{role}{step_idx}'

        # 角色标签
        role_labels = {'pre': '前置', 'main': '主请求', 'post': '后置'}
        role_css = {'pre': 'pre', 'main': 'main', 'post': 'post'}
        role_label = role_labels.get(role, '前置')
        role_class = role_css.get(role, 'pre')
        step_css_class = f'{role_class}-step' if role != 'main' else 'main-step'

        if step_type == 'db':
            # DB 查询步骤
            sql = _format_json(step.get('sql'))
            sql_params = _format_json(step.get('sql_params'))
            result_preview = _format_json(step.get('result_preview', []))
            result_count = step.get('result_count', 0)
            rowcount = step.get('rowcount')
            sc_text = _esc(step.get('status_code', 'OK'))
            sc_class = 'sc-ok' if str(sc_text).upper() == 'OK' else 'sc-err'

            # 从 SQL 中提取简短描述
            raw_sql = step.get('sql', '') or ''
            sql_short = raw_sql[:60].replace('\n', ' ')
            if len(raw_sql) > 60:
                sql_short += '...'

            detail_html = f'''
                <div class="step-section">
                    <h5>🗄️ 数据库查询</h5>
                    <div class="step-info-box">
                        <p><strong>操作:</strong> DB Query</p>
                        <p><strong>耗时:</strong> {duration_ms:.2f} ms</p>
                        <p><strong>返回条数:</strong> {result_count}</p>
                        <p><strong>rowcount:</strong> {_esc(rowcount)}</p>
                        <p><strong>SQL:</strong></p>
                        <pre>{sql}</pre>
                        <p><strong>SQL 参数:</strong></p>
                        <pre>{sql_params}</pre>
                        <p><strong>结果预览:</strong></p>
                        <pre>{result_preview}</pre>
                    </div>
                </div>'''

            parts.append(f'''
            <div class="scenario-step {step_css_class}">
                <div class="step-header" onclick="toggleStep('{step_id}')">
                    <span class="step-icon" id="step-icon-{step_id}">&#9654;</span>
                    <span class="aux-step-tag {role_class}">{role_label}</span>
                    <strong>{_esc(sql_short)}</strong>
                    <span class="method-tag" style="background:#7c3aed;">DB</span>
                    <span class="sc-badge {sc_class}">{sc_text}</span>
                    <span class="step-duration">({duration_ms:.2f}ms)</span>
                </div>
                <div class="step-body" id="step-detail-{step_id}" style="display:none;">
                    {detail_html}
                </div>
            </div>''')
        else:
            # HTTP 步骤
            method = _esc(step.get('method', ''))
            url = _esc(step.get('url', ''))
            status_code = step.get('status_code', '')
            sc_class = 'sc-ok' if str(status_code).startswith('2') else 'sc-err'
            req_headers_html = _render_headers_block(step.get('headers', {}))
            resp_headers_html = _render_headers_block(step.get('response_headers', {}))
            params_html = _format_json(step.get('params'))
            body_html = _format_json(step.get('request_body'))
            resp_body_html = _format_json(step.get('response_body', ''))

            # 从 URL 提取路径用于显示
            raw_url = step.get('url', '')
            if '://' in raw_url:
                after = raw_url.split('://', 1)[1]
                path_display = '/' + after.split('/', 1)[1] if '/' in after else '/'
            else:
                path_display = raw_url

            # 主请求显示状态 badge
            status_badge = ''
            if role == 'main':
                status_badge = '<span class="step-status-badge passed">✓</span>'

            detail_html = f'''
                <div class="step-section">
                    <h5>📤 请求信息</h5>
                    <div class="step-info-box">
                        <p><strong>方法:</strong> <span class="method-tag method-{method.lower()}">{method}</span></p>
                        <p><strong>URL:</strong> <span class="url-text">{url}</span></p>
                        <p><strong>请求头:</strong></p>
                        {req_headers_html}
                        <p><strong>查询参数:</strong></p>
                        <pre>{params_html}</pre>
                        <p><strong>请求体:</strong></p>
                        <pre>{body_html}</pre>
                    </div>
                </div>
                <div class="step-section">
                    <h5>📥 响应信息</h5>
                    <div class="step-info-box">
                        <p><strong>状态码:</strong> <span class="sc-badge {sc_class}">{status_code}</span></p>
                        <p><strong>耗时:</strong> {duration_ms:.2f} ms</p>
                        <p><strong>响应体:</strong></p>
                        <pre>{resp_body_html}</pre>
                    </div>
                </div>
                <div class="step-section">
                    <h5>📋 响应头</h5>
                    <div class="step-info-box" style="background: #f3f0ff; border: 1px solid #d1c4e9; border-left: 4px solid #7c4dff;">
                        {resp_headers_html}
                    </div>
                </div>'''

            # 步骤标题: 简短描述
            step_title = f'{method} {_esc(path_display)}'

            parts.append(f'''
            <div class="scenario-step {step_css_class}">
                <div class="step-header" onclick="toggleStep('{step_id}')">
                    <span class="step-icon" id="step-icon-{step_id}">&#9654;</span>
                    <span class="aux-step-tag {role_class}">{role_label}</span>
                    <strong>{step_title}</strong>
                    <span class="method-tag method-{method.lower()}">{method}</span>
                    <span class="sc-badge {sc_class}">{status_code}</span>
                    {status_badge}
                    <span class="step-duration">({duration_ms:.2f}ms)</span>
                </div>
                <div class="step-body" id="step-detail-{step_id}" style="display:none;">
                    {detail_html}
                </div>
            </div>''')

    return f'''
                <div class="step-section">
                    <h5>🔗 操作时序 <span style="font-weight:normal;color:#999;font-size:12px;">(共 {total} 步)</span></h5>
                    <div class="scenario-steps-container">
                        {''.join(parts)}
                    </div>
                </div>'''


def _render_api_test_case_row(case: dict, case_idx: int, sub_idx: int) -> str:
    """渲染单接口测试的一条用例为可展开行（3层结构中的 Level 2 + Level 3）

    Level 2: 用例标题行（类型标签 + 描述 + 状态）
    Level 3: 展开后的请求/响应详情
    """
    status = case.get('status', 'ERROR')
    status_lower = status.lower()
    name = _esc(case.get('name', ''))
    desc = _esc(case.get('description', ''))
    display_name = desc if desc else name
    category = _extract_category(case.get('description', ''))
    exec_time = case.get('execution_time', 0)

    url = _esc(case.get('url', ''))
    http_method = _esc(case.get('method', ''))
    status_code = case.get('status_code', '')

    req_headers_html = _render_headers_block(case.get('headers', {}))
    resp_headers_html = _render_headers_block(case.get('response_headers', {}))
    params_html = _format_json(case.get('params'))
    body_html = _format_json(case.get('request_body'))
    resp_body_html = _format_json(case.get('response_body', ''))

    # 断言
    assertions = case.get('assertions', [])
    assertions_html = ''
    if assertions:
        rows = []
        for a in assertions:
            a_status = a.get('status', 'passed')
            if a_status == 'passed':
                a_cls = 'passed'
                badge_text = 'PASSED'
            elif a_status == 'skipped':
                a_cls = 'skipped'
                badge_text = 'SKIPPED'
            else:
                a_cls = 'failed'
                badge_text = 'FAILED'
            expr = _esc(a.get('expression', ''))
            rows.append(f'''
                    <div class="assertion {a_cls}">
                        <div>
                            <strong>{expr}</strong>
                        </div>
                        <span style="font-weight: bold;">{badge_text}</span>
                    </div>''')
        assertions_html = ''.join(rows)
    else:
        assertions_html = '<p class="empty-hint">(未提取到断言语句)</p>'

    # 期望 vs 实际
    comparisons = case.get('failure_comparisons', [])
    comparison_html = ''
    if comparisons:
        comp_lines = []
        for c_line in comparisons:
            comp_lines.append(f'<small>{_esc(c_line)}</small><br>')
        comparison_html = f'''
                    <div class="assertion failed" style="margin-top: 8px;">
                        <div>
                            <strong>期望值 vs 实际值</strong><br>
                            {''.join(comp_lines)}
                        </div>
                    </div>'''

    # 错误信息
    error_html = ''
    if case.get('error_message'):
        error_html = f'''
                <div class="step-section">
                    <h5>❌ 错误详情</h5>
                    <div class="step-info-box" style="background: #fff3f3; border-color: #ffcdd2; border-left: 4px solid #dc3545;">
                        <pre style="background: #fff0f0; color: #b71c1c;">{_esc(case["error_message"][:3000])}</pre>
                    </div>
                </div>'''

    sc_class = 'sc-ok' if str(status_code).startswith('2') else 'sc-err'
    step_id = f'{case_idx}-{sub_idx}'

    # 状态 badge
    if status_lower == 'passed':
        step_status_badge = '<span class="step-status-badge passed">✓ PASSED</span>'
    elif status_lower == 'failed':
        step_status_badge = '<span class="step-status-badge failed">✗ FAILED</span>'
    elif status_lower == 'skipped':
        step_status_badge = '<span class="step-status-badge skipped">⊘ SKIPPED</span>'
    else:
        step_status_badge = f'<span class="step-status-badge failed">✗ {status}</span>'

    category_badge = ''
    method_badge = f'<span class="method-tag method-{http_method.lower()}">{http_method}</span>' if http_method else ''

    # 检测是否有辅助步骤（前置 DB 查询 / 前置 HTTP 创建 / 后置 HTTP 清理）
    auxiliary_steps = case.get('auxiliary_steps', [])
    if auxiliary_steps:
        # 渲染操作时序替代标准的请求/响应展示
        timeline_html = _render_auxiliary_timeline(auxiliary_steps, case_idx, sub_idx)
        body_content = f'''
                {timeline_html}
                <div class="step-section">
                    <h5>✅ 断言结果</h5>
                    {assertions_html}
                    {comparison_html}
                </div>
                {error_html}'''
    else:
        # 标准布局：请求 → 响应 → 响应头 → 断言
        body_content = f'''
                <div class="step-section">
                    <h5>📤 请求信息</h5>
                    <div class="step-info-box">
                        <p><strong>方法:</strong> <span class="method-tag method-{http_method.lower()}">{http_method}</span></p>
                        <p><strong>URL:</strong> <span class="url-text">{url}</span></p>
                        <p><strong>请求头:</strong></p>
                        {req_headers_html}
                        <p><strong>查询参数:</strong></p>
                        <pre>{params_html}</pre>
                        <p><strong>请求体:</strong></p>
                        <pre>{body_html}</pre>
                    </div>
                </div>
                <div class="step-section">
                    <h5>📥 响应信息</h5>
                    <div class="step-info-box">
                        <p><strong>状态码:</strong> <span class="sc-badge {sc_class}">{status_code}</span></p>
                        <p><strong>耗时:</strong> {exec_time:.2f} ms</p>
                        <p><strong>响应体:</strong></p>
                        <pre>{resp_body_html}</pre>
                    </div>
                </div>
                <div class="step-section">
                    <h5>📋 响应头</h5>
                    <div class="step-info-box" style="background: #f3f0ff; border: 1px solid #d1c4e9; border-left: 4px solid #7c4dff;">
                        {resp_headers_html}
                    </div>
                </div>
                <div class="step-section">
                    <h5>✅ 断言结果</h5>
                    {assertions_html}
                    {comparison_html}
                </div>
                {error_html}'''

    return f'''
        <div class="scenario-step">
            <div class="step-header" onclick="toggleStep('{step_id}')">
                <span class="step-icon" id="step-icon-{step_id}">&#9654;</span>
                <strong>{display_name}</strong>
                {category_badge}
                {method_badge}
                <span class="sc-badge {sc_class}">{status_code}</span>
                {step_status_badge}
                <span class="step-duration">({exec_time:.2f}ms)</span>
            </div>
            <div class="step-body" id="step-detail-{step_id}" style="display:none;">
                {body_content}
            </div>
        </div>'''


def _render_scenario_steps(steps: list, case_idx: int) -> str:
    """渲染场景测试的步骤列表（三层结构的第二层和第三层）"""
    if not steps:
        return '<p class="empty-hint">(无步骤信息)</p>'

    steps_html_parts = []
    for step in steps:
        step_num = step.get('step_number', 0)
        step_type = step.get('step_type', 'http')
        method = _esc(step.get('method', 'GET'))
        url = _esc(step.get('url', ''))
        path = _esc(step.get('path', ''))
        # 优先使用 step dict 中的 step_name（class-based 场景合并后会填充方法 docstring）
        step_name_raw = step.get('step_name', '')
        step_name = step_name_raw if step_name_raw and step_name_raw != f'Step {step_num}' else f'Step {step_num}'
        status_code = step.get('status_code', '')
        duration_ms = step.get('duration_ms', 0)
        request_headers = _render_headers_block(step.get('headers', {}))
        request_params = _format_json(step.get('params', None))
        response_body = _format_json(step.get('response_body', ''))
        response_headers = _render_headers_block(step.get('response_headers', {}))
        request_body = _format_json(step.get('request_body', {}))
        sql = _format_json(step.get('sql'))
        sql_params = _format_json(step.get('sql_params'))
        result_preview = _format_json(step.get('result_preview', []))
        result_count = step.get('result_count', 0)
        rowcount = step.get('rowcount', None)

        sc_class = 'sc-ok' if str(status_code).startswith('2') or str(status_code).upper() == 'OK' else 'sc-err'
        step_id = f'{case_idx}-{step_num}'

        step_assertions = step.get('assertions', [])
        assertions_html = ''
        step_has_failed = False
        step_has_skipped = False
        if step_assertions:
            # 检查是否有失败或跳过的断言
            step_has_failed = any(a.get('status', 'passed') == 'failed' for a in step_assertions)
            step_has_skipped = any(a.get('status', 'passed') == 'skipped' for a in step_assertions)
            rows = []
            for a in step_assertions:
                a_status = a.get('status', 'passed')
                # 根据断言状态设置样式类和显示文本
                if a_status == 'passed':
                    a_cls = 'passed'
                    badge_text = 'PASSED'
                elif a_status == 'skipped':
                    a_cls = 'skipped'
                    badge_text = 'SKIPPED'
                else:
                    a_cls = 'failed'
                    badge_text = 'FAILED'
                expr = _esc(a.get('expression', ''))
                rows.append(f'''
                    <div class="assertion {a_cls}">
                        <div>
                            <strong>{expr}</strong>
                        </div>
                        <span style="font-weight: bold;">{badge_text}</span>
                    </div>''')
            assertions_html = f'''
                <div class="step-section">
                    <h5>✅ 断言结果</h5>
                    {''.join(rows)}
                </div>'''

        step_status_badge = ''
        if step_assertions:
            if step_has_failed:
                step_status_badge = '<span class="step-status-badge failed">✗ FAILED</span>'
            elif step_has_skipped:
                step_status_badge = '<span class="step-status-badge skipped">⊘ SKIPPED</span>'
            else:
                step_status_badge = '<span class="step-status-badge passed">✓ PASSED</span>'

        if step_type == 'db':
            step_detail_html = f'''
                <div class="step-section">
                    <h5>🗄️ 数据库查询</h5>
                    <div class="step-info-box">
                        <p><strong>操作:</strong> DB Query</p>
                        <p><strong>耗时:</strong> {duration_ms:.2f} ms</p>
                        <p><strong>返回条数:</strong> {result_count}</p>
                        <p><strong>rowcount:</strong> {_esc(rowcount)}</p>
                        <p><strong>SQL:</strong></p>
                        <pre>{sql}</pre>
                        <p><strong>SQL 参数:</strong></p>
                        <pre>{sql_params}</pre>
                        <p><strong>结果预览:</strong></p>
                        <pre>{result_preview}</pre>
                    </div>
                </div>
                {assertions_html}
            '''
            badge = '<span class="method-tag" style="background:#7c3aed;">DB</span>'
            path_badge = '<span class="step-path">DB Query</span>'
        else:
            step_detail_html = f'''
                <div class="step-section">
                    <h5>📤 请求信息</h5>
                    <div class="step-info-box">
                        <p><strong>方法:</strong> <span class="method-tag method-{method.lower()}">{method}</span></p>
                        <p><strong>URL:</strong> <span class="url-text">{url}</span></p>
                        <p><strong>路径:</strong> {path}</p>
                        <p><strong>请求头:</strong></p>
                        {request_headers}
                        <p><strong>查询参数:</strong></p>
                        <pre>{request_params}</pre>
                        <p><strong>请求体:</strong></p>
                        <pre>{request_body}</pre>
                    </div>
                </div>
                <div class="step-section">
                    <h5>📥 响应信息</h5>
                    <div class="step-info-box">
                        <p><strong>状态码:</strong> <span class="sc-badge {sc_class}">{status_code}</span></p>
                        <p><strong>耗时:</strong> {duration_ms:.2f} ms</p>
                        <p><strong>响应体:</strong></p>
                        <pre>{response_body}</pre>
                    </div>
                </div>
                <div class="step-section">
                    <h5>📋 响应头</h5>
                    <div class="step-info-box">
                        {response_headers}
                    </div>
                </div>
                {assertions_html}
            '''
            badge = f'<span class="method-tag method-{method.lower()}">{method}</span>'
            path_badge = f'<span class="step-path">{path}</span>'

        step_html = f'''
        <div class="scenario-step">
            <div class="step-header" onclick="toggleStep('{step_id}')">
                <span class="step-icon" id="step-icon-{step_id}">&#9654;</span>
                <strong>{step_name}</strong>
                {badge}
                {path_badge}
                <span class="sc-badge {sc_class}">{status_code}</span>
                {step_status_badge}
                <span class="step-duration">({duration_ms:.2f}ms)</span>
            </div>
            <div class="step-body" id="step-detail-{step_id}" style="display:none;">
                {step_detail_html}
            </div>
        </div>'''
        steps_html_parts.append(step_html)

    return '\n'.join(steps_html_parts)


def generate_fixed_report(test_results, output_path, analysis_result=None):
    """
    生成统一版 HTML 测试报告（参照 references/test_report_template.html 视觉风格）

    Args:
        test_results (dict): 测试结果数据 {"test_cases": [...]}
        output_path (str): 输出文件路径
        analysis_result (dict): 智能分析结果（可选）
    """
    cases = test_results.get('test_cases', [])
    total = len(cases)
    passed = sum(1 for c in cases if c.get('status') == 'PASSED')
    failed = sum(1 for c in cases if c.get('status') == 'FAILED')
    error = sum(1 for c in cases if c.get('status') == 'ERROR')
    skipped = sum(1 for c in cases if c.get('status') == 'SKIPPED')
    pass_rate = f'{passed / total * 100:.1f}' if total else '0.0'

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 提取接口覆盖度和智能分析数据
    coverage_data = {}
    failure_analysis = {}
    if analysis_result:
        # 支持新的数据结构：endpoints_info
        if 'endpoints_info' in analysis_result:
            endpoints_info = analysis_result['endpoints_info']
            coverage_data = {
                'tested_count': endpoints_info.get('tested_endpoints', 0),
                'total_count': endpoints_info.get('total_endpoints', 0),
                'coverage_rate': endpoints_info.get('coverage', 0)
            }
        else:
            # 兼容旧的数据结构
            coverage_data = analysis_result.get('coverage', {})

        failure_analysis = analysis_result.get('failures', {})


    # ---- 构建用例 HTML（支持单接口按文件分组的三层结构） ----
    # 先按 source_file 分组，test_api_* 文件内的用例将渲染为三层结构
    from collections import OrderedDict

    # 构建有序分组：保持用例在 JSON 中的原始出现顺序
    file_groups = OrderedDict()  # source_file -> [case, ...]
    ungrouped = []  # 无法分组的用例（场景测试或无 source_file）

    for case in cases:
        source_file = case.get('source_file', '')
        is_scenario = case.get('is_scenario', False)

        # 场景测试不分组，保持原有渲染逻辑
        if is_scenario:
            ungrouped.append(('scenario', case))
        elif source_file and source_file.startswith('test_api_'):
            if source_file not in file_groups:
                file_groups[source_file] = []
            file_groups[source_file].append(case)
        else:
            ungrouped.append(('single', case))

    # 构建渲染序列：按原始出现顺序交错渲染分组和非分组用例
    # 为了保持顺序，记录每个 source_file 第一次出现的位置
    render_order = []  # (type, data) 其中 type='group'|'scenario'|'single'
    seen_files = set()

    for case in cases:
        source_file = case.get('source_file', '')
        is_scenario = case.get('is_scenario', False)

        if is_scenario:
            render_order.append(('scenario', case))
        elif source_file and source_file.startswith('test_api_'):
            if source_file not in seen_files:
                seen_files.add(source_file)
                render_order.append(('group', source_file))
            # 分组内的用例在 group 时统一渲染，此处跳过
        else:
            render_order.append(('single', case))

    cases_html_parts = []
    global_idx = 0  # 全局索引，用于唯一 ID

    for render_type, data in render_order:
        if render_type == 'group':
            # ---- 单接口分组：三层结构 ----
            source_file = data
            group_cases = file_groups[source_file]
            group_passed = sum(1 for c in group_cases if c.get('status') == 'PASSED')
            group_failed = sum(1 for c in group_cases if c.get('status') == 'FAILED')
            group_error = sum(1 for c in group_cases if c.get('status') == 'ERROR')
            group_skipped = sum(1 for c in group_cases if c.get('status') == 'SKIPPED')
            group_total = len(group_cases)
            group_time = sum(c.get('execution_time', 0) for c in group_cases)

            # 综合状态
            if group_failed > 0 or group_error > 0:
                group_status = 'FAILED'
            elif group_passed > 0:
                group_status = 'PASSED'
            elif group_skipped > 0:
                group_status = 'SKIPPED'
            else:
                group_status = 'PASSED'
            group_status_lower = group_status.lower()

            # Level 1 标题
            endpoint_title = _extract_endpoint_title(source_file, group_cases)

            # 渲染 Level 2 + Level 3 的所有用例行
            sub_rows = []
            for sub_idx, sub_case in enumerate(group_cases):
                sub_rows.append(_render_api_test_case_row(sub_case, global_idx, sub_idx))

            # 用例计数摘要
            count_summary_parts = [f'共 {group_total} 条']
            if group_passed > 0:
                count_summary_parts.append(f'<span style="color:#155724;">{group_passed} 通过</span>')
            if group_failed > 0:
                count_summary_parts.append(f'<span style="color:#721c24;">{group_failed} 失败</span>')
            if group_error > 0:
                count_summary_parts.append(f'<span style="color:#856404;">{group_error} 错误</span>')
            if group_skipped > 0:
                count_summary_parts.append(f'<span style="color:#856404;">{group_skipped} 跳过</span>')
            count_summary = ' / '.join(count_summary_parts)

            case_html = f'''
        <div class="test-case api-endpoint-group" data-status="{group_status_lower}" data-type="endpoint" data-name="{_esc(source_file)}" id="case-{global_idx}">
            <div class="test-header" onclick="toggleDetail({global_idx})">
                <div class="test-header-left">
                    <span class="expand-icon" id="icon-{global_idx}">&#9654;</span>
                    <h3>🔌 {_esc(endpoint_title)}</h3>
                    <span class="endpoint-file-tag">{_esc(source_file)}</span>
                    <span class="endpoint-count-tag">{count_summary}</span>
                </div>
                <span class="status {group_status_lower}">{group_status}</span>
            </div>
            <div class="test-body" id="detail-{global_idx}" style="display:none;">
                <p class="timestamp">总执行耗时: {group_time:.2f} ms</p>

                <div class="section">
                    <h4>📋 测试用例</h4>
                    <div class="scenario-steps-container">
                        {''.join(sub_rows)}
                    </div>
                </div>
            </div>
        </div>'''
            cases_html_parts.append(case_html)
            global_idx += 1

        elif render_type == 'scenario':
            # ---- 场景测试：显示场景编号和完整信息 ----
            case = data
            idx = global_idx
            status = case.get('status', 'ERROR')
            status_lower = status.lower()
            name = _esc(case.get('name', ''))
            raw_desc = case.get('description', '')
            exec_time = case.get('execution_time', 0)
            scenario_steps = case.get('scenario_steps', [])

            # 从描述中提取场景编号（如"场景 1: xxx"）
            scene_number_display = ''
            scene_match = re.search(r'场景\s*(\d+)', raw_desc)
            if scene_match:
                scene_number_display = f'场景{scene_match.group(1)}'
            else:
                source_file_raw = case.get('source_file', '')
                scene_file_match = re.search(r'test_scenario_(\d+)', source_file_raw)
                if scene_file_match:
                    scene_number_display = f'场景{scene_file_match.group(1)}'

            source_file = _esc(case.get('source_file', ''))

            # 场景标题：取描述第一行作为标题，剩余行作为副标题
            desc_lines = [l.strip() for l in raw_desc.strip().splitlines() if l.strip()]
            scene_title = _esc(desc_lines[0]) if desc_lines else name
            scene_subtitle_lines = desc_lines[1:] if len(desc_lines) > 1 else []
            scene_subtitle_html = ''
            if scene_subtitle_lines:
                subtitle_parts = ' &nbsp;|&nbsp; '.join(_esc(l) for l in scene_subtitle_lines)
                scene_subtitle_html = f'<div style="font-size:12px;color:#666;margin-top:2px;padding-left:28px;">{subtitle_parts}</div>'

            # 场景编号标签
            scene_badge = f'<span class="category-tag" style="background:#764ba2;color:#fff;">{scene_number_display}</span>' if scene_number_display else ''
            # 文件名标签（和单接口一致）
            file_badge = f'<span class="endpoint-file-tag">{source_file}</span>' if source_file else ''

            error_html = ''
            if case.get('error_message'):
                error_html = f'''
                <div class="section">
                    <h4>❌ 错误详情</h4>
                    <div class="info-box error-box">
                        <pre>{_esc(case["error_message"][:3000])}</pre>
                    </div>
                </div>'''

            steps_html = _render_scenario_steps(scenario_steps, idx)
            case_html = f'''
        <div class="test-case scenario-test" data-status="{status_lower}" data-type="scenario" data-name="{name}" data-source-file="{source_file}" id="case-{idx}">
            <div class="test-header" onclick="toggleDetail({idx})">
                <div class="test-header-left">
                    <span class="expand-icon" id="icon-{idx}">&#9654;</span>
                    <h3>🎬 {scene_title}</h3>
                    {scene_badge}
                    {file_badge}
                </div>
                <span class="status {status_lower}">{status}</span>
            </div>
            {scene_subtitle_html}
            <div class="test-body" id="detail-{idx}" style="display:none;">
                <p class="timestamp">总执行耗时: {exec_time:.2f} ms</p>

                <div class="section">
                    <h4>📋 场景步骤</h4>
                    <div class="scenario-steps-container">
                        {steps_html}
                    </div>
                </div>

                {error_html}
            </div>
        </div>'''
            cases_html_parts.append(case_html)
            global_idx += 1

        else:
            # ---- 普通单接口测试（无 source_file 或非 test_api_ 前缀）：原有结构 ----
            case = data
            idx = global_idx
            status = case.get('status', 'ERROR')
            status_lower = status.lower()
            name = _esc(case.get('name', ''))
            desc = _esc(case.get('description', ''))
            display_name = desc if desc else name
            exec_time = case.get('execution_time', 0)

            url = _esc(case.get('url', ''))
            http_method = _esc(case.get('method', ''))
            status_code = case.get('status_code', '')

            req_headers_html = _render_headers_block(case.get('headers', {}))
            resp_headers_html = _render_headers_block(case.get('response_headers', {}))
            params_html = _format_json(case.get('params'))
            body_html = _format_json(case.get('request_body'))
            resp_body_html = _format_json(case.get('response_body', ''))

            assertions = case.get('assertions', [])
            assertions_html = ''
            if assertions:
                rows = []
                for a in assertions:
                    a_status = a.get('status', 'passed')
                    if a_status == 'passed':
                        a_cls = 'passed'
                        badge_text = 'PASSED'
                    elif a_status == 'skipped':
                        a_cls = 'skipped'
                        badge_text = 'SKIPPED'
                    else:
                        a_cls = 'failed'
                        badge_text = 'FAILED'
                    expr = _esc(a.get('expression', ''))
                    rows.append(f'''
                    <div class="assertion {a_cls}">
                        <div>
                            <strong>{expr}</strong>
                        </div>
                        <span style="font-weight: bold;">{badge_text}</span>
                    </div>''')
                assertions_html = ''.join(rows)
            else:
                assertions_html = '<p class="empty-hint">(未提取到断言语句)</p>'

            comparisons = case.get('failure_comparisons', [])
            comparison_html = ''
            if comparisons:
                comp_lines = []
                for c_line in comparisons:
                    comp_lines.append(f'<small>{_esc(c_line)}</small><br>')
                comparison_html = f'''
                    <div class="assertion failed" style="margin-top: 8px;">
                        <div>
                            <strong>期望值 vs 实际值</strong><br>
                            {''.join(comp_lines)}
                        </div>
                    </div>'''

            error_html = ''
            if case.get('error_message'):
                error_html = f'''
                <div class="section">
                    <h4>❌ 错误详情</h4>
                    <div class="info-box error-box">
                        <pre>{_esc(case["error_message"][:3000])}</pre>
                    </div>
                </div>'''

            case_html = f'''
        <div class="test-case" data-status="{status_lower}" data-type="endpoint" data-name="{name}" id="case-{idx}">
            <div class="test-header" onclick="toggleDetail({idx})">
                <div class="test-header-left">
                    <span class="expand-icon" id="icon-{idx}">&#9654;</span>
                    <h3>{display_name}</h3>
                </div>
                <span class="status {status_lower}">{status}</span>
            </div>
            <div class="test-body" id="detail-{idx}" style="display:none;">
                <p class="timestamp">执行耗时: {exec_time:.2f} ms</p>

                <div class="section">
                    <h4>📤 请求信息</h4>
                    <div class="info-box">
                        <p><strong>方法:</strong> <span class="method-tag method-{http_method.lower()}">{http_method}</span></p>
                        <p><strong>URL:</strong> <span class="url-text">{url}</span></p>
                        <p><strong>请求头:</strong></p>
                        {req_headers_html}
                        <p><strong>查询参数:</strong></p>
                        <pre>{params_html}</pre>
                        <p><strong>请求体:</strong></p>
                        <pre>{body_html}</pre>
                    </div>
                </div>

                <div class="section">
                    <h4>📥 响应信息</h4>
                    <div class="info-box">
                        <p><strong>状态码:</strong> <span class="sc-badge sc-{('ok' if str(status_code).startswith('2') else 'err')}">{status_code}</span></p>
                        <p><strong>执行耗时:</strong> {exec_time:.2f} ms</p>
                        <p><strong>响应体:</strong></p>
                        <pre>{resp_body_html}</pre>
                    </div>
                </div>

                <div class="section">
                    <h4>📋 响应头</h4>
                    <div class="info-box resp-header-box">
                        {resp_headers_html}
                    </div>
                </div>

                <div class="section">
                    <h4>✅ 断言结果</h4>
                    {assertions_html}
                    {comparison_html}
                </div>

                {error_html}
            </div>
        </div>'''
            cases_html_parts.append(case_html)
            global_idx += 1

    test_cases_html = '\n'.join(cases_html_parts)

    # 类型过滤按钮（固定：单接口 / 场景）
    has_endpoints = any(
        (not c.get('is_scenario', False)) for c in cases
    )
    has_scenarios = any(
        c.get('is_scenario', False) for c in cases
    )
    type_btns_parts = []
    if has_endpoints:
        type_btns_parts.append('<button class="cat-btn" onclick="filterByType(\'endpoint\', this)">单接口</button>')
    if has_scenarios:
        type_btns_parts.append('<button class="cat-btn" onclick="filterByType(\'scenario\', this)">场景</button>')

    cat_buttons = ''
    if len(type_btns_parts) > 1:
        cat_buttons = f'''
        <div class="category-bar">
            <span class="cat-label">用例分类：</span>
            {''.join(type_btns_parts)}
        </div>'''

    # ---- 饼图 SVG ----
    def _pie_arc(cx, cy, r, start_angle, end_angle, color):
        import math
        if abs(end_angle - start_angle) < 0.01:
            return ''
        if abs(end_angle - start_angle - 360) < 0.01:
            return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}" />'
        large = 1 if (end_angle - start_angle) > 180 else 0
        sx = cx + r * math.cos(math.radians(start_angle - 90))
        sy = cy + r * math.sin(math.radians(start_angle - 90))
        ex = cx + r * math.cos(math.radians(end_angle - 90))
        ey = cy + r * math.sin(math.radians(end_angle - 90))
        return (
            f'<path d="M{cx},{cy} L{sx:.2f},{sy:.2f} '
            f'A{r},{r} 0 {large},1 {ex:.2f},{ey:.2f} Z" fill="{color}" />'
        )

    pie_svg = ''
    if total > 0:
        arcs_list = []
        cur = 0
        for count, color in [(passed, '#90EE90'), (failed, '#FFB6C1'), (error, '#FFD700'), (skipped, '#87CEEB')]:
            if count > 0:
                sweep = count / total * 360
                arcs_list.append(_pie_arc(50, 50, 45, cur, cur + sweep, color))
                cur += sweep
        pie_svg = f'<svg width="100" height="100" viewBox="0 0 100 100">{"".join(arcs_list)}</svg>'

    # 准备接口覆盖度HTML
    coverage_html = ''
    if coverage_data:
        tested_count = coverage_data.get('tested_count', 0)
        total_count = coverage_data.get('total_count', 0)
        coverage_rate = coverage_data.get('coverage_rate', 0)

        # 应测接口数为 0 时，不展示应测接口数、实测接口数、接口覆盖率三项
        if total_count > 0:
            coverage_html = f'''
            <div class="summary-item">
                <div class="number" style="color: #FF6B6B;">{total_count}</div>
                <div class="label">应测接口数</div>
            </div>
            <div class="summary-item">
                <div class="number" style="color: #FF6B6B;">{tested_count}</div>
                <div class="label">实测接口数</div>
            </div>
            <div class="summary-item">
                <div class="number" style="color: #FF6B6B;">{coverage_rate:.0f}%</div>
                <div class="label">接口覆盖率</div>
            </div>
        '''

    # 准备智能分析HTML
    analysis_html = ''
    if analysis_result:
        status = analysis_result.get('status', 'completed')
        
        if status == 'pending':
            # 隐藏占位符，等分析完成后由 update_report_with_ai_analysis 重新生成报告时才显示
            message = analysis_result.get('message', '智能分析进行中，请稍候...')
            analysis_html = f'''
        <div class="analysis-section" style="display: none;">
            <div class="analysis-header">
                <h3>📊 测试结果智能分析</h3>
            </div>
            <div class="analysis-content" style="padding: 20px; text-align: center; color: #666;">
                <p style="font-size: 16px;">⏳ {_esc(message)}</p>
            </div>
        </div>
        '''
        elif 'failure_analysis' in analysis_result:
            # 新的数据结构：failure_analysis
            failure_list = analysis_result.get('failure_analysis', [])
            summary = analysis_result.get('summary', '')
            
            problems_html = ''
            if summary:
                problems_html += f'<div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 20px;"><strong>📋 分析摘要：</strong>{_esc(summary)}</div>'
            
            for failure in failure_list:
                category = _esc(failure.get('category', '未分类'))
                subcategory = _esc(failure.get('subcategory', ''))
                root_cause = _esc(failure.get('root_cause', ''))
                evidence = _esc(failure.get('evidence', ''))
                impact_level = failure.get('impact_level', 'medium')
                is_test_issue = failure.get('is_test_issue', False)
                is_code_issue = failure.get('is_code_issue', False)
                test_cases = failure.get('test_cases', [])
                suggestions = failure.get('suggestions', [])
                
                severity_color = {'critical': '#dc3545', 'high': '#ff6b6b', 'medium': '#ffc107', 'low': '#28a745'}.get(impact_level, '#ffc107')
                issue_type = '🧪 测试脚本问题' if is_test_issue else ('🐛 代码缺陷' if is_code_issue else '❓ 待确认')

                affected_cases_html = ''
                if test_cases:
                    affected_cases_html = '<br><strong>影响的用例：</strong><ul style="margin: 5px 0;">'
                    for tc in test_cases[:10]:
                        affected_cases_html += f'<li>{_esc(tc)}</li>'
                    if len(test_cases) > 10:
                        affected_cases_html += f'<li>... 还有 {len(test_cases) - 10} 个用例</li>'
                    affected_cases_html += '</ul>'
                
                suggestions_html = ''
                if suggestions:
                    suggestions_html = '<br><strong>💡 修复建议：</strong><ol style="margin: 5px 0;">'
                    for sug in suggestions:
                        suggestions_html += f'<li>{_esc(sug)}</li>'
                    suggestions_html += '</ol>'
                
                problems_html += f'''
                <div style="background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid {severity_color};">
                    <h4 style="color: {severity_color}; margin-top: 0;">
                        ⚠️ {category}{(' - ' + subcategory) if subcategory else ''}
                        <span style="font-size: 12px; margin-left: 10px; color: #666;">{issue_type}</span>
                    </h4>
                    <p><strong>🔍 根本原因：</strong>{root_cause}</p>
                    {f'<p><strong>📝 证据：</strong><code style="background: #f5f5f5; padding: 2px 6px; border-radius: 3px;">{evidence}</code></p>' if evidence else ''}
                    {affected_cases_html}
                    {suggestions_html}
                </div>
                '''
            
            analysis_html = f'''
        <div class="analysis-section">
            <div class="analysis-header" onclick="toggleAnalysis()">
                <h3>📊 测试结果智能分析</h3>
                <span class="analysis-toggle" id="analysisToggle">▼</span>
            </div>
            <div class="analysis-content" id="analysisContent">
                {problems_html if problems_html else '<p>未发现明显问题</p>'}
            </div>
        </div>
        '''
        else:
            # 兼容旧的数据结构：intelligent_insights
            intelligent_insights = analysis_result.get('intelligent_insights', {})
            problems = intelligent_insights.get('problems', [])
            suggestions = intelligent_insights.get('suggestions', [])

            if problems or suggestions:
            # 生成问题分类HTML
                problems_html = ''
                for problem in problems:
                    severity_color = {'high': '#dc3545', 'medium': '#ffc107', 'low': '#28a745'}.get(problem.get('severity', 'medium'), '#ffc107')
                    affected_endpoints_html = ''
                    if problem.get('affected_endpoints'):
                        affected_endpoints_html = '<br><strong>影响的接口：</strong><ul>'
                        for endpoint in problem['affected_endpoints'][:5]:
                            affected_endpoints_html += f'<li>{_esc(endpoint)}</li>'
                        if len(problem['affected_endpoints']) > 5:
                            affected_endpoints_html += f'<li>... 还有 {len(problem["affected_endpoints"]) - 5} 个接口</li>'
                        affected_endpoints_html += '</ul>'

                    # 源码分析证据
                    source_evidence_html = ''
                    if problem.get('source_evidence'):
                        source_evidence_html = '<br><strong>📝 源码分析：</strong><ul style="background: #f8f9fa; padding: 10px; border-radius: 4px; margin-top: 10px;">'
                        for evidence in problem['source_evidence']:
                            source_evidence_html += f'<li>{_esc(evidence)}</li>'
                        source_evidence_html += '</ul>'

                    problems_html += f'''
                    <div class="problem-category">
                        <h4 style="color: {severity_color};">⚠️ {_esc(problem.get('title', ''))}</h4>
                        <p><strong>问题描述：</strong>{_esc(problem.get('description', ''))}</p>
                        <p><strong>根本原因：</strong>{_esc(problem.get('root_cause', ''))}</p>
                        <p><strong>影响：</strong>{_esc(problem.get('impact', ''))}</p>
                        {affected_endpoints_html}
                        {source_evidence_html}
                    </div>
                    '''

                # 生成改进建议HTML
                suggestions_html = ''
                for suggestion in suggestions:
                    priority_badge = {'high': '🔴 高优先级', 'medium': '🟡 中优先级', 'low': '🟢 低优先级'}.get(suggestion.get('priority', 'medium'), '🟡 中优先级')
                    actions_html = '<ol>'
                    for action in suggestion.get('actions', []):
                        actions_html += f'<li>{_esc(action)}</li>'
                    actions_html += '</ol>'

                    affected_endpoints_html = ''
                    if suggestion.get('affected_endpoints'):
                        affected_endpoints_html = '<br><strong>涉及接口：</strong><ul>'
                        for endpoint in suggestion['affected_endpoints'][:5]:
                            affected_endpoints_html += f'<li>{_esc(endpoint)}</li>'
                        if len(suggestion['affected_endpoints']) > 5:
                            affected_endpoints_html += f'<li>... 还有 {len(suggestion["affected_endpoints"]) - 5} 个接口</li>'
                        affected_endpoints_html += '</ul>'

                    suggestions_html += f'''
                    <div class="suggestion-box">
                        <h4>💡 {_esc(suggestion.get('title', ''))} <span style="font-size: 12px; margin-left: 10px;">{priority_badge}</span></h4>
                        <p><strong>改进措施：</strong></p>
                        {actions_html}
                        {affected_endpoints_html}
                    </div>
                    '''

                analysis_html = f'''
            <div class="analysis-section">
                <div class="analysis-header" onclick="toggleAnalysis()">
                    <h3>📊 测试结果智能分析</h3>
                    <span class="analysis-toggle" id="analysisToggle">▼</span>
                </div>
                <div class="analysis-content" id="analysisContent">
                    <h4>🔍 发现的问题</h4>
                    {problems_html if problems_html else '<p>未发现明显问题</p>'}
                    <h4>💡 改进建议</h4>
                    {suggestions_html if suggestions_html else '<p>暂无改进建议</p>'}
                </div>
            </div>
            '''

    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>接口测试报告</title>
    <style>
        body {{
            font-family: 'Microsoft YaHei', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #4CAF50;
            padding-bottom: 15px;
            font-size: 24px;
        }}
        .timestamp {{
            color: #666;
            font-size: 12px;
            margin-bottom: 10px;
        }}

        /* ===== 统计区（紫色渐变） ===== */
        .summary {{
            display: flex;
            justify-content: space-around;
            align-items: center;
            margin: 30px 0;
            padding: 25px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 10px;
            color: white;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .summary-item {{
            text-align: center;
            min-width: 80px;
        }}
        .summary-item .number {{
            font-size: 36px;
            font-weight: bold;
            margin: 10px 0;
        }}
        .summary-item .label {{
            font-size: 14px;
            opacity: 0.9;
        }}
        .summary .pie-chart {{
            flex-shrink: 0;
        }}

        /* ===== 工具栏 ===== */
        .toolbar {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 15px;
            padding: 12px 0;
            border-bottom: 1px solid #eee;
        }}
        .search-box {{
            flex: 1;
            min-width: 180px;
            padding: 8px 14px;
            border: 1px solid #ddd;
            border-radius: 20px;
            font-size: 13px;
            outline: none;
            transition: border-color .2s;
        }}
        .search-box:focus {{ border-color: #667eea; }}
        .filter-btn {{
            padding: 6px 16px;
            border: 1px solid #ddd;
            border-radius: 20px;
            background: #fff;
            cursor: pointer;
            font-size: 13px;
            transition: all .15s;
        }}
        .filter-btn:hover {{ background: #f5f5f5; }}
        .filter-btn.active {{ background: #667eea; color: #fff; border-color: #667eea; }}
        .action-btn {{
            padding: 6px 14px;
            border: 1px solid #ddd;
            border-radius: 6px;
            background: #fff;
            cursor: pointer;
            font-size: 12px;
        }}
        .action-btn:hover {{ background: #f5f5f5; }}
        .result-count {{ font-size: 12px; color: #999; white-space: nowrap; }}

        /* ===== 分类栏 ===== */
        .category-bar {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 15px;
        }}
        .cat-label {{ font-size: 13px; color: #888; }}
        .cat-btn {{
            padding: 4px 14px;
            border: 1px solid #e0e0e0;
            border-radius: 16px;
            background: #fafafa;
            cursor: pointer;
            font-size: 12px;
            transition: all .15s;
        }}
        .cat-btn:hover {{ background: #ede7f6; }}
        .cat-btn.active {{ background: #764ba2; color: #fff; border-color: #764ba2; }}

        /* ===== 测试用例卡片 ===== */
        .test-case {{
            margin: 20px 0;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            overflow: hidden;
            transition: box-shadow .2s;
        }}
        .test-case:hover {{ box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
        .test-header {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e0e0e0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            user-select: none;
        }}
        .test-header:hover {{ background: #f0f0f0; }}
        .test-header-left {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}
        .test-header h3 {{
            margin: 0;
            color: #333;
            font-size: 15px;
        }}
        .expand-icon {{
            font-size: 11px;
            color: #999;
            transition: transform .2s;
            display: inline-block;
        }}
        .expand-icon.open {{ transform: rotate(90deg); }}
        .category-tag {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 600;
            background: #ede7f6;
            color: #5e35b1;
        }}

        /* 状态胶囊（参照参考模板） */
        .status {{
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: bold;
        }}
        .status.passed {{ background: #d4edda; color: #155724; }}
        .status.failed {{ background: #f8d7da; color: #721c24; }}
        .status.error {{ background: #fff3cd; color: #856404; }}
        .status.skipped {{ background: #fff3cd; color: #856404; }}

        /* ===== 用例详情 ===== */
        .test-body {{ padding: 20px; }}
        .test-body > p {{ margin: 4px 0; font-size: 13px; }}
        .section {{ margin: 18px 0; }}
        .section h4 {{
            color: #555;
            margin-bottom: 10px;
            font-size: 14px;
            padding-bottom: 5px;
            border-bottom: 1px solid #f0f0f0;
        }}
        .info-box {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            font-family: 'Courier New', Consolas, monospace;
            font-size: 13px;
            overflow-x: auto;
        }}
        .info-box p {{ margin: 6px 0; font-family: 'Microsoft YaHei', Arial, sans-serif; }}
        .info-box pre {{
            background: #f0f0f0;
            padding: 10px;
            border-radius: 4px;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 300px;
            overflow-y: auto;
            margin: 6px 0;
        }}
        .url-text {{ color: #1565c0; word-break: break-all; }}
        .method-tag {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            color: #fff;
            background: #607d8b;
        }}
        .method-get {{ background: #43a047; }}
        .method-post {{ background: #1e88e5; }}
        .method-put {{ background: #fb8c00; }}
        .method-delete {{ background: #e53935; }}
        .method-patch {{ background: #8e24aa; }}
        .sc-badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 14px;
        }}
        .sc-ok {{ background: #d4edda; color: #155724; }}
        .sc-err {{ background: #f8d7da; color: #721c24; }}
        .empty-hint {{ color: #bbb; font-style: italic; font-size: 12px; }}

        /* ===== 响应头高亮区块 ===== */
        .resp-header-box {{
            background: #f3f0ff;
            border: 1px solid #d1c4e9;
            border-left: 4px solid #7c4dff;
        }}
        .resp-header-box pre {{
            background: #ede7f6;
        }}

        /* ===== 断言（参照参考模板样式） ===== */
        .assertion {{
            padding: 10px 15px;
            margin: 5px 0;
            border-radius: 5px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .assertion.passed {{
            background: #d4edda;
            border-left: 4px solid #28a745;
        }}
        .assertion.failed {{
            background: #f8d7da;
            border-left: 4px solid #dc3545;
        }}
        .assertion.skipped {{
            background: #fff3cd;
            border-left: 4px solid #ffc107;
        }}
        .assertion strong {{
            font-size: 13px;
            word-break: break-all;
        }}
        .assertion small {{
            color: #555;
            font-size: 12px;
        }}
        .assertion > span {{
            white-space: nowrap;
            margin-left: 12px;
        }}

        /* ===== 错误区块 ===== */
        .error-box {{
            background: #fff3f3;
            border: 1px solid #ffcdd2;
            border-left: 4px solid #dc3545;
        }}
        .error-box pre {{
            background: #fff0f0;
            color: #b71c1c;
            max-height: 200px;
        }}

        /* ===== 底部 ===== */
        .report-footer {{
            text-align: center;
            padding: 20px 0 5px;
            color: #bbb;
            font-size: 12px;
            border-top: 1px solid #eee;
            margin-top: 30px;
        }}

        /* ===== 单接口分组样式 ===== */
        .api-endpoint-group {{
            border-left: 4px solid #1e88e5;
        }}
        .api-endpoint-group .test-header {{
            background: #e3f2fd;
        }}
        .api-endpoint-group .test-header:hover {{
            background: #bbdefb;
        }}
        .endpoint-file-tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            background: #e8eaf6;
            color: #3949ab;
            font-family: 'Courier New', monospace;
        }}
        .endpoint-count-tag {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 10px;
            font-size: 11px;
            background: #f5f5f5;
            color: #666;
            margin-left: 5px;
        }}

        /* ===== 场景测试样式 ===== */
        .scenario-test {{
            border-left: 4px solid #9c27b0;
        }}
        /* 🎬 图标已在 Python 渲染时写入 h3 内容，无需 CSS ::before 重复添加 */
        .scenario-steps-container {{
            margin-top: 15px;
        }}
        .scenario-step {{
            margin-bottom: 15px;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            background: #fafafa;
        }}
        .step-header {{
            padding: 12px 15px;
            background: #f5f5f5;
            border-bottom: 1px solid #e0e0e0;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            transition: background .2s;
        }}
        .step-header:hover {{
            background: #eeeeee;
        }}
        .step-icon {{
            display: inline-block;
            transition: transform .2s;
            font-size: 12px;
            color: #666;
        }}
        .step-icon.expanded {{
            transform: rotate(90deg);
        }}
        .step-path {{
            color: #666;
            font-size: 13px;
            font-family: 'Courier New', monospace;
        }}
        .step-duration {{
            color: #999;
            font-size: 12px;
            margin-left: auto;
        }}
        .step-status-badge {{
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
            margin-left: 8px;
        }}
        .step-status-badge.passed {{
            background: #d4edda;
            color: #155724;
        }}
        .step-status-badge.failed {{
            background: #f8d7da;
            color: #721c24;
        }}
        .step-status-badge.skipped {{
            background: #fff3cd;
            color: #856404;
        }}
        .step-body {{
            padding: 15px;
            background: white;
        }}
        .step-section {{
            margin-bottom: 15px;
        }}
        .step-section h5 {{
            margin: 0 0 8px 0;
            font-size: 14px;
            color: #555;
        }}
        .step-info-box {{
            background: #f9f9f9;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #e8e8e8;
        }}
        .step-info-box p {{
            margin: 6px 0;
            font-size: 13px;
        }}
        .step-info-box pre {{
            background: #fff;
            padding: 10px;
            border-radius: 4px;
            border: 1px solid #e0e0e0;
            font-size: 12px;
            max-height: 200px;
            overflow: auto;
        }}

        /* ===== 操作时序（辅助步骤：前置/主请求/后置）样式 ===== */
        .aux-step-tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 0.5px;
            flex-shrink: 0;
        }}
        .aux-step-tag.pre {{
            background: #fff3e0;
            color: #e65100;
            border: 1px solid #ffcc80;
        }}
        .aux-step-tag.main {{
            background: #e8f5e9;
            color: #2e7d32;
            border: 1px solid #81c784;
        }}
        .aux-step-tag.post {{
            background: #e3f2fd;
            color: #1565c0;
            border: 1px solid #90caf9;
        }}
        .scenario-step.main-step {{
            border-left: 3px solid #4CAF50;
            background: #f1f8e9;
        }}
        .scenario-step.main-step > .step-header {{
            background: #e8f5e9;
        }}
        .scenario-step.main-step > .step-header:hover {{
            background: #dcedc8;
        }}
        .scenario-step.pre-step {{
            border-left: 3px solid #ff9800;
        }}
        .scenario-step.pre-step > .step-header {{
            background: #fff8e1;
        }}
        .scenario-step.pre-step > .step-header:hover {{
            background: #ffecb3;
        }}
        .scenario-step.post-step {{
            border-left: 3px solid #42a5f5;
        }}
        .scenario-step.post-step > .step-header {{
            background: #e3f2fd;
        }}
        .scenario-step.post-step > .step-header:hover {{
            background: #bbdefb;
        }}

        /* ===== 智能分析区域 ===== */
        .analysis-section {{
            margin: 30px 0;
            padding: 0;
            background: #f9f9f9;
            border-radius: 10px;
            border: 1px solid #e0e0e0;
            overflow: hidden;
        }}
        .analysis-header {{
            padding: 15px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: space-between;
            transition: background 0.3s;
        }}
        .analysis-header:hover {{
            background: linear-gradient(135deg, #5568d3 0%, #653a8b 100%);
        }}
        .analysis-header h3 {{
            color: white;
            font-size: 18px;
            margin: 0;
        }}
        .analysis-toggle {{
            font-size: 20px;
            transition: transform 0.3s;
        }}
        .analysis-toggle.expanded {{
            transform: rotate(180deg);
        }}
        .analysis-content {{
            background: white;
            padding: 20px;
            display: none;
        }}
        .analysis-content.show {{
            display: block;
        }}
        .analysis-section h4 {{
            color: #555;
            font-size: 15px;
            margin: 15px 0 10px 0;
        }}
        .analysis-content ul {{
            margin: 10px 0;
            padding-left: 20px;
        }}
        .analysis-content li {{
            margin: 8px 0;
            line-height: 1.6;
        }}
        .problem-category {{
            margin: 20px 0;
            padding: 15px;
            background: #fff3cd;
            border-left: 4px solid #ffc107;
            border-radius: 4px;
        }}
        .problem-category h4 {{
            color: #856404;
            margin-top: 0;
        }}
        .suggestion-box {{
            margin: 15px 0;
            padding: 15px;
            background: #d1ecf1;
            border-left: 4px solid #17a2b8;
            border-radius: 4px;
        }}
        .suggestion-box h4 {{
            color: #0c5460;
            margin-top: 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 接口测试报告</h1>
        <p class="timestamp">生成时间: {now_str}</p>

        <div class="summary">
            {coverage_html}
            <div class="summary-item">
                <div class="number">{total}</div>
                <div class="label">总测试数</div>
            </div>
            <div class="summary-item">
                <div class="number" style="color: #90EE90;">{passed}</div>
                <div class="label">通过</div>
            </div>
            <div class="summary-item">
                <div class="number" style="color: #FFB6C1;">{failed}</div>
                <div class="label">失败</div>
            </div>
            <div class="summary-item">
                <div class="number" style="color: #FFD700;">{error}</div>
                <div class="label">错误</div>
            </div>
            <div class="summary-item">
                <div class="number" style="color: #87CEEB;">{skipped}</div>
                <div class="label">跳过</div>
            </div>
            <div class="summary-item">
                <div class="number">{pass_rate}%</div>
                <div class="label">通过率</div>
            </div>
            <div class="summary-item pie-chart">
                {pie_svg}
            </div>
        </div>

        {analysis_html}

        <div class="toolbar">
            <input type="text" class="search-box" id="searchBox" placeholder="搜索用例名称或描述..." oninput="applyFilters()">
            <button class="filter-btn active" onclick="setStatusFilter('all', this)">全部</button>
            <button class="filter-btn" onclick="setStatusFilter('passed', this)">通过</button>
            <button class="filter-btn" onclick="setStatusFilter('failed', this)">失败</button>
            <button class="filter-btn" onclick="setStatusFilter('error', this)">错误</button>
            <button class="filter-btn" onclick="setStatusFilter('skipped', this)">跳过</button>
            <button class="action-btn" onclick="expandAll()">全部展开</button>
            <button class="action-btn" onclick="collapseAll()">全部折叠</button>
            <span class="result-count" id="resultCount"></span>
        </div>

        {cat_buttons}

        <h2 style="margin-top: 10px; margin-bottom: 5px; color: #333; font-size: 18px;">测试详情</h2>

        <div id="testCasesList">
{test_cases_html}
        </div>

        <div class="report-footer">
            interface-test-case-generator &middot; {now_str}
        </div>
    </div>

    <script>
    var currentStatusFilter = 'all';
    var currentTypeFilter = '';

    function toggleAnalysis() {{
        var content = document.getElementById('analysisContent');
        var toggle = document.getElementById('analysisToggle');
        if (content.classList.contains('show')) {{
            content.classList.remove('show');
            toggle.classList.remove('expanded');
        }} else {{
            content.classList.add('show');
            toggle.classList.add('expanded');
        }}
    }}

    function toggleDetail(idx) {{
        var d = document.getElementById('detail-' + idx);
        var icon = document.getElementById('icon-' + idx);
        if (d.style.display === 'none') {{
            d.style.display = 'block';
            icon.classList.add('open');
        }} else {{
            d.style.display = 'none';
            icon.classList.remove('open');
        }}
    }}

    function expandAll() {{
        document.querySelectorAll('.test-body').forEach(function(d) {{ d.style.display = 'block'; }});
        document.querySelectorAll('.expand-icon').forEach(function(i) {{ i.classList.add('open'); }});
    }}

    function collapseAll() {{
        document.querySelectorAll('.test-body').forEach(function(d) {{ d.style.display = 'none'; }});
        document.querySelectorAll('.expand-icon').forEach(function(i) {{ i.classList.remove('open'); }});
    }}

    function setStatusFilter(status, btn) {{
        currentStatusFilter = status;
        document.querySelectorAll('.filter-btn').forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
        applyFilters();
    }}

    function filterByType(type, btn) {{
        var btns = document.querySelectorAll('.cat-btn');
        btns.forEach(function(b) {{ b.classList.remove('active'); }});
        if (currentTypeFilter === type) {{
            currentTypeFilter = '';
        }} else {{
            currentTypeFilter = type;
            btn.classList.add('active');
        }}
        applyFilters();
    }}

    function applyFilters() {{
        var keyword = document.getElementById('searchBox').value.toLowerCase();
        var cases = document.querySelectorAll('.test-case');
        var visible = 0;
        cases.forEach(function(c) {{
            var s = c.dataset.status;
            var t = c.dataset.type || '';
            var n = c.dataset.name;
            var desc = c.querySelector('.test-body > p') ? c.querySelector('.test-body > p').textContent : '';
            var matchStatus = (currentStatusFilter === 'all' || s === currentStatusFilter);
            var matchType = (!currentTypeFilter || t === currentTypeFilter);
            var matchKw = (!keyword || n.toLowerCase().indexOf(keyword) >= 0 || desc.toLowerCase().indexOf(keyword) >= 0);
            if (matchStatus && matchType && matchKw) {{
                c.style.display = '';
                visible++;
            }} else {{
                c.style.display = 'none';
            }}
        }});
        document.getElementById('resultCount').textContent = visible + ' / ' + cases.length;
    }}

    applyFilters();

    // 场景步骤展开/折叠
    function toggleStep(stepNum) {{
        var detail = document.getElementById('step-detail-' + stepNum);
        var icon = document.getElementById('step-icon-' + stepNum);
        if (detail.style.display === 'none') {{
            detail.style.display = 'block';
            icon.classList.add('expanded');
        }} else {{
            detail.style.display = 'none';
            icon.classList.remove('expanded');
        }}
    }}
    </script>
</body>
</html>'''

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return output_path
