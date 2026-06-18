#!/usr/bin/env python3
"""
WebUI 自动化测试 HTML 报告生成器（核心脚本）

功能说明：
- 读取 conftest_webui_plugin.py 输出的 test_results_*.json 文件
- 生成单文件自包含 HTML 报告（所有 CSS/JS 内联，无外部依赖）
- 包含统计面板、SVG 饼图、环境信息、用例卡片、搜索过滤等交互功能
- 所有用户数据经 html.escape 转义，防止 XSS

使用方式：
    python generate_webui_html_report.py \
        --results qa/webui/session/execution/test_results_20240101.json \
        --output qa/webui/session/execution/report_20240101.html \
        --title "WebUI 自动化测试报告"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from datetime import datetime
from html import escape
from pathlib import Path, PurePosixPath


# ── 报告版本号 ──────────────────────────────────────────────────────
REPORT_VERSION = "webui-report-generator v1.0.0"


def _normalize_path_str(path_str: str) -> str:
    """将 Windows 反斜杠路径统一转为 POSIX 正斜杠，兼容旧 JSON 产物。"""
    return path_str.replace('\\', '/')


def _make_portable_href(media_path: Path, report_path: Path | None) -> str:
    """
    生成可移植的 href：优先相对于报告文件的相对路径，对特殊字符做 URL 编码。
    当 report_path 未知或无法计算相对路径时，回退到绝对路径。
    """
    if report_path is not None:
        try:
            rel = os.path.relpath(str(media_path), str(report_path.parent))
            parts = PurePosixPath(rel.replace('\\', '/'))
            return urllib.parse.quote(str(parts), safe='/:@!$&\'()*+,;=-._~')
        except (ValueError, TypeError):
            pass
    return urllib.parse.quote(str(media_path).replace('\\', '/'), safe='/:@!$&\'()*+,;=-._~')


def _build_css() -> str:
    """
    构建报告的内联 CSS 样式。
    使用 CSS 变量便于主题定制，采用现代卡片式布局。
    """
    return """
    <style>
        /* ── CSS 变量（主题色） ── */
        :root {
            --color-primary: #1e3a5f;
            --color-primary-light: #2c5282;
            --color-accent: #3b82f6;
            --color-accent-light: #60a5fa;
            --color-bg: #f8fafc;
            --color-card: #ffffff;
            --color-text: #1e293b;
            --color-text-light: #64748b;
            --color-text-muted: #94a3b8;
            --color-border: #e2e8f0;
            --color-border-light: #f1f5f9;
            --color-passed: #22c55e;
            --color-passed-bg: #f0fdf4;
            --color-passed-border: #bbf7d0;
            --color-failed: #ef4444;
            --color-failed-bg: #fef2f2;
            --color-failed-border: #fecaca;
            --color-error: #f59e0b;
            --color-error-bg: #fffbeb;
            --color-error-border: #fde68a;
            --color-skipped: #94a3b8;
            --color-skipped-bg: #f8fafc;
            --radius: 12px;
            --radius-sm: 8px;
            --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
            --shadow: 0 1px 3px rgba(0,0,0,0.1), 0 1px 2px rgba(0,0,0,0.06);
            --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);
            --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05);
            --transition: all 0.2s ease;
        }

        /* ── 全局重置与基础样式 ── */
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                         "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif;
            background: var(--color-bg);
            color: var(--color-text);
            line-height: 1.6;
            -webkit-font-smoothing: antialiased;
        }

        /* ── 页头 ── */
        .report-header {
            background: linear-gradient(135deg, #0f172a 0%, var(--color-primary) 50%, var(--color-primary-light) 100%);
            color: #ffffff;
            padding: 48px 40px 40px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        .report-header::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: radial-gradient(circle at 20% 50%, rgba(59,130,246,0.15) 0%, transparent 50%),
                        radial-gradient(circle at 80% 50%, rgba(99,102,241,0.1) 0%, transparent 50%);
            pointer-events: none;
        }
        .report-header h1 {
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 8px;
            letter-spacing: -0.5px;
            position: relative;
        }
        .report-header .subtitle {
            font-size: 14px;
            opacity: 0.7;
            position: relative;
            font-weight: 400;
        }

        /* ── 主容器 ── */
        .container {
            max-width: 1200px;
            margin: -24px auto 0;
            padding: 0 24px 24px;
            position: relative;
            z-index: 1;
        }

        /* ── 统计面板 ── */
        .stats-dashboard {
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }
        .stat-card {
            flex: 1;
            min-width: 140px;
            background: var(--color-card);
            border-radius: var(--radius);
            padding: 24px 20px;
            text-align: center;
            box-shadow: var(--shadow);
            transition: var(--transition);
            border: 1px solid var(--color-border-light);
            position: relative;
            overflow: hidden;
        }
        .stat-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: var(--color-border);
        }
        .stat-card:hover {
            box-shadow: var(--shadow-lg);
            transform: translateY(-3px);
        }
        .stat-card.total::before { background: var(--color-accent); }
        .stat-card.passed::before { background: var(--color-passed); }
        .stat-card.failed::before { background: var(--color-failed); }
        .stat-card.error::before { background: var(--color-error); }
        .stat-card.skipped::before { background: var(--color-skipped); }
        .stat-card .number {
            font-size: 40px;
            font-weight: 800;
            line-height: 1.1;
            letter-spacing: -1px;
        }
        .stat-card.total .number { color: var(--color-accent); }
        .stat-card.passed .number { color: var(--color-passed); }
        .stat-card.failed .number { color: var(--color-failed); }
        .stat-card.error .number { color: var(--color-error); }
        .stat-card.skipped .number { color: var(--color-skipped); }
        .stat-card .label {
            font-size: 12px;
            color: var(--color-text-muted);
            margin-top: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
        }

        /* ── 通过率与饼图区域 ── */
        .pass-rate-section {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 40px;
            background: var(--color-card);
            border-radius: var(--radius);
            padding: 32px;
            margin-bottom: 20px;
            box-shadow: var(--shadow);
            border: 1px solid var(--color-border-light);
        }
        .pass-rate-text { text-align: center; }
        .pass-rate-text .rate {
            font-size: 56px;
            font-weight: 800;
            background: linear-gradient(135deg, var(--color-accent), #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -2px;
        }
        .pass-rate-text .rate-label {
            font-size: 13px;
            color: var(--color-text-muted);
            font-weight: 500;
        }
        .pie-chart-container {
            width: 160px;
            height: 160px;
        }

        /* ── 环境信息条 ── */
        .env-bar {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            background: var(--color-card);
            border-radius: var(--radius);
            padding: 16px 20px;
            margin-bottom: 20px;
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--color-border-light);
            font-size: 13px;
        }
        .env-item {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 12px;
            border-radius: 20px;
            background: var(--color-bg);
            color: var(--color-text-light);
            border: 1px solid var(--color-border);
        }
        .env-item .env-label {
            font-weight: 600;
            color: var(--color-text);
        }

        /* ── 工具栏 ── */
        .toolbar {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: center;
            margin-bottom: 20px;
            background: var(--color-card);
            border-radius: var(--radius);
            padding: 14px 20px;
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--color-border-light);
            position: sticky;
            top: 0;
            z-index: 10;
        }
        .search-box {
            flex: 1;
            min-width: 200px;
            padding: 8px 16px;
            border: 1px solid var(--color-border);
            border-radius: 20px;
            font-size: 14px;
            outline: none;
            transition: var(--transition);
            background: var(--color-bg);
        }
        .search-box:focus {
            border-color: var(--color-accent);
            box-shadow: 0 0 0 3px rgba(59,130,246,0.12);
            background: #fff;
        }
        .filter-btn {
            padding: 6px 16px;
            border: 1px solid var(--color-border);
            border-radius: 20px;
            background: #fff;
            cursor: pointer;
            font-size: 13px;
            transition: var(--transition);
            font-weight: 500;
        }
        .filter-btn:hover {
            background: var(--color-bg);
            border-color: var(--color-accent);
            color: var(--color-accent);
        }
        .filter-btn.active {
            background: var(--color-accent);
            color: #fff;
            border-color: var(--color-accent);
        }
        .action-btn {
            padding: 6px 16px;
            border: 1px solid var(--color-border);
            border-radius: 20px;
            background: #fff;
            cursor: pointer;
            font-size: 13px;
            transition: var(--transition);
            font-weight: 500;
        }
        .action-btn:first-of-type { margin-left: auto; }
        .action-btn:hover {
            background: var(--color-primary);
            color: #fff;
            border-color: var(--color-primary);
        }

        /* ── 用例卡片 ── */
        .case-card {
            background: var(--color-card);
            border-radius: var(--radius);
            margin-bottom: 10px;
            box-shadow: var(--shadow-sm);
            overflow: hidden;
            transition: var(--transition);
            border: 1px solid var(--color-border-light);
            border-left: 4px solid var(--color-border);
        }
        .case-card:hover {
            box-shadow: var(--shadow-md);
            border-color: var(--color-border);
        }
        .case-card.status-PASSED { border-left-color: var(--color-passed); }
        .case-card.status-FAILED { border-left-color: var(--color-failed); }
        .case-card.status-ERROR { border-left-color: var(--color-error); }
        .case-card.status-SKIPPED { border-left-color: var(--color-skipped); }

        .case-header {
            display: flex;
            align-items: center;
            padding: 14px 20px;
            cursor: pointer;
            user-select: none;
            gap: 12px;
        }
        .case-header:hover { background: var(--color-border-light); }

        .status-badge {
            display: inline-flex;
            align-items: center;
            padding: 3px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            color: #fff;
            white-space: nowrap;
            letter-spacing: 0.3px;
        }
        .badge-PASSED { background: var(--color-passed); }
        .badge-FAILED { background: var(--color-failed); }
        .badge-ERROR { background: var(--color-error); }
        .badge-SKIPPED { background: var(--color-skipped); }

        .case-name {
            flex: 1;
            font-size: 14px;
            font-weight: 500;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            color: var(--color-text);
        }
        .case-duration {
            font-size: 13px;
            color: var(--color-text-muted);
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
            font-weight: 500;
        }
        .expand-icon {
            font-size: 10px;
            color: var(--color-text-muted);
            transition: transform 0.25s ease;
            width: 20px;
            text-align: center;
        }
        .case-card.expanded .expand-icon {
            transform: rotate(90deg);
        }

        /* ── 用例详情（可折叠） ── */
        .case-body {
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.4s ease;
        }
        .case-card.expanded .case-body {
            max-height: 8000px;
        }
        .case-body-inner {
            padding: 16px 20px 20px;
            border-top: 1px solid var(--color-border-light);
            background: var(--color-bg);
        }

        /* ── 步骤时间线 ── */
        .steps-section { margin-top: 12px; }
        .steps-section h4 {
            font-size: 13px;
            margin-bottom: 12px;
            color: var(--color-text-light);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .step-timeline {
            list-style: none;
            padding-left: 0;
            position: relative;
        }
        .step-timeline::before {
            content: '';
            position: absolute;
            left: 11px;
            top: 4px;
            bottom: 4px;
            width: 2px;
            background: linear-gradient(to bottom, var(--color-accent-light), var(--color-border));
            border-radius: 1px;
        }
        .step-item {
            position: relative;
            padding-left: 36px;
            padding-bottom: 10px;
            font-size: 13px;
            color: var(--color-text);
        }
        .step-item::before {
            content: '';
            position: absolute;
            left: 6px;
            top: 6px;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #fff;
            border: 2.5px solid var(--color-accent);
        }
        .step-no {
            font-weight: 700;
            color: var(--color-accent);
            margin-right: 6px;
            font-size: 12px;
        }

        /* ── 截图区域 ── */
        .screenshots-section { margin-top: 16px; }
        .screenshots-section h4 {
            font-size: 13px;
            margin-bottom: 8px;
            color: var(--color-text-light);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .screenshot-placeholder {
            display: inline-block;
            background: #fff;
            border: 1px dashed var(--color-border);
            border-radius: var(--radius-sm);
            padding: 8px 12px;
            font-size: 12px;
            color: var(--color-text-muted);
            margin: 4px 4px 4px 0;
        }
        .screenshot-item img {
            max-width: 100%;
            border-radius: var(--radius-sm);
            border: 1px solid var(--color-border);
            margin: 4px 0;
            cursor: zoom-in;
            transition: var(--transition);
        }
        .screenshot-item img:hover {
            box-shadow: var(--shadow-lg);
            transform: scale(1.01);
        }

        /* ── 截图灯箱 ── */
        .lightbox-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.85);
            z-index: 9999;
            cursor: zoom-out;
            align-items: center;
            justify-content: center;
            padding: 40px;
            backdrop-filter: blur(4px);
        }
        .lightbox-overlay.active { display: flex; }
        .lightbox-overlay img {
            max-width: 95%;
            max-height: 95vh;
            border-radius: var(--radius);
            box-shadow: 0 25px 50px rgba(0,0,0,0.4);
        }

        /* ── 错误详情 ── */
        .error-section { margin-top: 16px; }
        .error-section h4 {
            font-size: 13px;
            margin-bottom: 8px;
            color: var(--color-failed);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .error-box {
            background: var(--color-failed-bg);
            border: 1px solid var(--color-failed-border);
            border-radius: var(--radius-sm);
            padding: 16px;
            font-family: "SF Mono", "Cascadia Code", "Fira Code", Consolas, monospace;
            font-size: 12px;
            line-height: 1.6;
            white-space: pre-wrap;
            word-break: break-all;
            max-height: 400px;
            overflow-y: auto;
            color: #991b1b;
        }

        /* ── 视频播放器 ── */
        .video-section { margin-top: 16px; }
        .video-section h4 {
            font-size: 13px;
            margin-bottom: 8px;
            color: var(--color-text-light);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .video-player {
            width: 100%;
            max-height: 600px;
            border-radius: var(--radius-sm);
            border: 1px solid var(--color-border);
            background: #000;
            object-fit: contain;
        }
        .video-link {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            color: var(--color-accent);
            text-decoration: none;
            font-size: 13px;
            padding: 6px 14px;
            border-radius: 20px;
            background: rgba(59,130,246,0.08);
            transition: var(--transition);
            font-weight: 500;
        }
        .video-link:hover {
            background: rgba(59,130,246,0.15);
            text-decoration: none;
        }

        /* ── 缺陷摘要 ── */
        .defect-summary-section {
            margin: 20px 0;
            padding: 20px 24px;
            background: var(--color-failed-bg);
            border: 1px solid var(--color-failed-border);
            border-radius: var(--radius);
        }
        .defect-summary-section h3 {
            margin: 0 0 16px;
            color: #991b1b;
            font-size: 16px;
            font-weight: 700;
        }
        .defect-category { margin-bottom: 12px; }
        .defect-type {
            font-weight: 600;
            color: #b91c1c;
            font-size: 14px;
            margin-bottom: 6px;
        }
        .defect-cases {
            list-style: none;
            padding-left: 16px;
        }
        .defect-cases li {
            padding: 4px 0;
            font-size: 13px;
            color: var(--color-text);
            border-bottom: 1px solid rgba(239,68,68,0.1);
        }
        .defect-cases li:last-child { border-bottom: none; }
        .defect-cases code {
            font-size: 11px;
            color: #991b1b;
            background: rgba(239,68,68,0.06);
            padding: 1px 6px;
            border-radius: 3px;
            word-break: break-all;
        }

        /* ── 所有录屏汇总 ── */
        .all-videos-section {
            margin-top: 32px;
            padding: 24px;
            background: var(--color-card);
            border-radius: var(--radius);
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--color-border-light);
        }
        .all-videos-section h3 {
            margin: 0 0 16px 0;
            font-size: 16px;
            color: var(--color-text);
            font-weight: 700;
        }
        .all-videos-list {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
            gap: 16px;
        }
        .all-video-item {
            border-radius: var(--radius-sm);
            background: var(--color-bg);
            font-size: 13px;
            transition: var(--transition);
            border: 1px solid var(--color-border-light);
            overflow: hidden;
        }
        .all-video-item:hover {
            border-color: var(--color-border);
            box-shadow: var(--shadow);
        }
        .all-video-item video {
            width: 100%;
            max-height: 280px;
            object-fit: contain;
            background: #000;
            display: block;
        }
        .all-video-meta {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
        }
        .all-video-index {
            color: var(--color-text-muted);
            min-width: 20px;
            text-align: right;
            font-weight: 600;
            font-size: 12px;
        }
        .all-video-size {
            color: var(--color-text-muted);
            margin-left: auto;
            white-space: nowrap;
            font-size: 12px;
        }

        /* ── 页脚 ── */
        .report-footer {
            text-align: center;
            padding: 32px 24px;
            color: var(--color-text-muted);
            font-size: 12px;
            margin-top: 40px;
        }
        .report-footer .divider {
            width: 40px;
            height: 2px;
            background: var(--color-border);
            margin: 0 auto 16px;
            border-radius: 1px;
        }

        /* ── 响应式适配 ── */
        @media (max-width: 768px) {
            .container { padding: 0 12px 12px; margin-top: -16px; }
            .report-header { padding: 32px 20px 28px; }
            .report-header h1 { font-size: 24px; }
            .stats-dashboard { gap: 8px; }
            .stat-card { min-width: 100px; padding: 16px 12px; }
            .stat-card .number { font-size: 28px; }
            .pass-rate-section { flex-direction: column; gap: 16px; padding: 24px; }
            .pass-rate-text .rate { font-size: 40px; }
            .toolbar { flex-direction: column; position: static; }
            .search-box { min-width: auto; width: 100%; }
            .action-btn:first-of-type { margin-left: 0; }
        }
    </style>
    """


def _build_js() -> str:
    """
    构建报告的内联 JavaScript。
    实现搜索过滤、状态过滤、展开/折叠等交互功能。
    """
    return """
    <script>
        // ── 搜索过滤功能（300ms debounce） ──
        var _filterTimer = null;
        function filterCases() {
            var keyword = document.getElementById('searchInput').value.toLowerCase();
            var activeFilter = document.querySelector('.filter-btn.active');
            var statusFilter = activeFilter ? activeFilter.getAttribute('data-status') : 'all';
            var cards = document.querySelectorAll('.case-card');

            cards.forEach(function(card) {
                var name = card.getAttribute('data-name').toLowerCase();
                var status = card.getAttribute('data-status');
                var matchKeyword = !keyword || name.indexOf(keyword) !== -1;
                var matchStatus = statusFilter === 'all' || status === statusFilter;
                card.style.display = (matchKeyword && matchStatus) ? 'block' : 'none';
            });

            updateVisibleCount();
        }
        function filterCasesDebounced() {
            clearTimeout(_filterTimer);
            _filterTimer = setTimeout(filterCases, 300);
        }

        // ── 状态过滤按钮 ──
        function setStatusFilter(btn) {
            document.querySelectorAll('.filter-btn').forEach(function(b) {
                b.classList.remove('active');
            });
            btn.classList.add('active');
            filterCases();
        }

        // ── 展开/折叠单个用例 ──
        function toggleCase(header) {
            var card = header.closest('.case-card');
            card.classList.toggle('expanded');
        }

        // ── 展开全部 ──
        function expandAll() {
            document.querySelectorAll('.case-card').forEach(function(card) {
                if (card.style.display !== 'none') {
                    card.classList.add('expanded');
                }
            });
        }

        // ── 折叠全部 ──
        function collapseAll() {
            document.querySelectorAll('.case-card').forEach(function(card) {
                card.classList.remove('expanded');
            });
        }

        // ── 更新可见用例计数 ──
        function updateVisibleCount() {
            var cards = document.querySelectorAll('.case-card');
            var visible = 0;
            cards.forEach(function(card) {
                if (card.style.display !== 'none') visible++;
            });
            var counter = document.getElementById('visibleCount');
            if (counter) {
                counter.textContent = '显示 ' + visible + ' / ' + cards.length + ' 条';
            }
        }

        // ── 截图灯箱 ──
        function openLightbox(src) {
            var overlay = document.getElementById('lightboxOverlay');
            var img = document.getElementById('lightboxImg');
            img.src = src;
            overlay.classList.add('active');
        }
        function closeLightbox() {
            document.getElementById('lightboxOverlay').classList.remove('active');
        }

        // ── 页面加载完成后初始化 ──
        document.addEventListener('DOMContentLoaded', function() {
            updateVisibleCount();
            // 事件代理：在容器级别监听截图点击，避免为每张图绑定事件
            document.addEventListener('click', function(e) {
                var img = e.target.closest('.screenshot-item img');
                if (img) { openLightbox(img.src); }
            });
            // 搜索框使用 debounce 版本
            var searchInput = document.getElementById('searchInput');
            if (searchInput) {
                searchInput.removeAttribute('oninput');
                searchInput.addEventListener('input', filterCasesDebounced);
            }
        });
    </script>
    """


def _build_svg_pie_chart(passed: int, failed: int, error: int, skipped: int) -> str:
    """
    生成 SVG 饼图，展示各状态的占比分布。

    Args:
        passed: 通过用例数
        failed: 失败用例数
        error: 错误用例数
        skipped: 跳过用例数

    Returns:
        str: SVG 标签字符串
    """
    total = passed + failed + error + skipped
    if total == 0:
        # 无数据时显示灰色圆
        return (
            '<svg viewBox="0 0 160 160" xmlns="http://www.w3.org/2000/svg">'
            '<circle cx="80" cy="80" r="70" fill="#e0e4e8"/>'
            '<text x="80" y="85" text-anchor="middle" font-size="14" fill="#999">暂无数据</text>'
            '</svg>'
        )

    # 各状态颜色配置
    segments = [
        (passed, "#52c41a", "通过"),
        (failed, "#ff4d4f", "失败"),
        (error, "#fa8c16", "错误"),
        (skipped, "#8c8c8c", "跳过"),
    ]

    svg_parts = [
        '<svg viewBox="0 0 160 160" xmlns="http://www.w3.org/2000/svg">',
    ]

    # 使用 stroke-dasharray 绘制环形饼图
    cx, cy, r = 80, 80, 60
    circumference = 2 * 3.14159265 * r
    offset = 0

    for count, color, _label in segments:
        if count <= 0:
            continue
        ratio = count / total
        dash_length = ratio * circumference
        gap_length = circumference - dash_length
        svg_parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{color}" stroke-width="24" '
            f'stroke-dasharray="{dash_length:.2f} {gap_length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash_length

    # 中心白色圆 + 通过率文字
    pass_rate = (passed / total * 100) if total > 0 else 0
    svg_parts.append(f'<circle cx="{cx}" cy="{cy}" r="44" fill="white"/>')
    svg_parts.append(
        f'<text x="{cx}" y="{cy - 4}" text-anchor="middle" '
        f'font-size="18" font-weight="700" fill="#333">{pass_rate:.1f}%</text>'
    )
    svg_parts.append(
        f'<text x="{cx}" y="{cy + 16}" text-anchor="middle" '
        f'font-size="11" fill="#999">通过率</text>'
    )
    svg_parts.append('</svg>')

    return '\n'.join(svg_parts)


def _render_steps(steps: list) -> str:
    """
    渲染用例的步骤时间线 HTML。

    Args:
        steps: 步骤信息列表，每个步骤包含 step_no, description 等字段

    Returns:
        str: 步骤时间线的 HTML 片段
    """
    if not steps:
        return ''

    items = []
    for step in steps:
        step_no = step.get('step_no', '')
        # 兼容 conftest 格式（description）和 v1 格式（action）
        desc = str(step.get('description', '') or step.get('action', '') or '')
        # 兼容 conftest 格式（action_type）和 v1 格式（target/status）
        detail_parts = []
        action_type = step.get('action_type', '')
        target = step.get('target', '')
        if action_type:
            detail_parts.append(action_type)
        if target and target not in ('', 'TARGET_URL'):
            detail_parts.append(target[:60])
        detail_str = ' | '.join(detail_parts)
        detail = f' <span style="color:#999;">({escape(detail_str)})</span>' if detail_str else ''
        items.append(
            f'<li class="step-item">'
            f'<span class="step-no">#{step_no}</span>{escape(desc)}{detail}'
            f'</li>'
        )

    return (
        '<div class="steps-section">'
        '<h4>操作步骤</h4>'
        '<ol class="step-timeline">'
        + ''.join(items) +
        '</ol></div>'
    )


def _render_screenshots(screenshots: list, workspace: str = '') -> str:
    """
    渲染截图区域 HTML。
    直接将截图文件读取为 base64 内嵌到 HTML 中，生成自包含的报告。

    Args:
        screenshots: 截图路径列表（可以是绝对路径或相对于工作空间的相对路径）
        workspace: 工作空间根路径，用于解析相对路径

    Returns:
        str: 截图区域的 HTML 片段
    """
    import base64 as _b64

    if not screenshots:
        return ''

    items = []
    for path_str in screenshots:
        normalized = _normalize_path_str(path_str)
        img_path = Path(normalized)
        if not img_path.is_absolute() and workspace:
            img_path = Path(workspace) / normalized
        if not img_path.is_absolute():
            img_path = Path.cwd() / normalized

        if img_path.exists() and img_path.is_file():
            try:
                data = img_path.read_bytes()
                suffix = img_path.suffix.lower()
                mime = {'.png': 'image/png', '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg', '.webp': 'image/webp',
                        '.gif': 'image/gif'}.get(suffix, 'image/png')
                b64 = _b64.b64encode(data).decode('ascii')
                items.append(
                    f'<div class="screenshot-item">'
                    f'<img src="data:{mime};base64,{b64}" '
                    f'alt="{escape(img_path.name)}" '
                    f'style="max-width:100%;border:1px solid #ddd;border-radius:4px;margin:4px 0;" '
                    f'loading="lazy" />'
                    f'<div style="font-size:12px;color:#999;">{escape(img_path.name)}</div>'
                    f'</div>'
                )
            except Exception:
                safe_path = escape(str(path_str))
                items.append(f'<span class="screenshot-placeholder">[截图读取失败: {safe_path}]</span>')
        else:
            safe_path = escape(str(path_str))
            items.append(f'<span class="screenshot-placeholder">[截图文件未找到: {safe_path}]</span>')

    return (
        '<div class="screenshots-section">'
        '<h4>截图</h4>'
        + ''.join(items) +
        '</div>'
    )


def _render_error(error_message: str) -> str:
    """
    渲染错误详情 HTML。

    Args:
        error_message: 错误信息文本

    Returns:
        str: 错误详情的 HTML 片段
    """
    if not error_message:
        return ''

    return (
        '<div class="error-section">'
        '<h4>错误详情</h4>'
        f'<div class="error-box">{escape(error_message)}</div>'
        '</div>'
    )


def _render_video(video_path: str, case_name: str = '', case_desc: str = '',
                   workspace: str = '', report_path: Path | None = None) -> str:
    """
    渲染内嵌视频播放器 HTML（<video controls>）。
    显示用例 ID（从描述中提取）和视频文件名，方便用户对照查看。
    生成相对于报告文件的可移植 href。

    Args:
        video_path: 视频文件路径（可能是 workspace-relative 路径）
        case_name: 用例函数名（如 test_batch_reference）
        case_desc: 用例描述/docstring（如 "CSV用例 tcjh_0068：xxx"）
        workspace: 工作空间根路径，用于将相对路径解析为绝对路径
        report_path: 输出 HTML 报告的文件路径，用于计算相对 href

    Returns:
        str: 视频链接的 HTML 片段
    """
    if not video_path:
        return ''

    normalized = _normalize_path_str(video_path)
    resolved = Path(normalized)
    if not resolved.is_absolute() and workspace:
        resolved = Path(workspace) / normalized
    if not resolved.is_absolute():
        resolved = Path.cwd() / normalized
    href = _make_portable_href(resolved, report_path)
    safe_href = escape(href)
    video_filename = escape(Path(normalized).name)

    # 尝试从描述中提取用例 ID
    import re as _re
    case_id = ''
    if case_desc:
        for pattern in [
            _re.compile(r'CSV用例\s+(\S+?)[\s：:]'),
            _re.compile(r'用例ID[\s：:]\s*(\S+)'),
        ]:
            match = pattern.search(case_desc)
            if match:
                case_id = match.group(1)
                break

    label = f'用例 {escape(case_id)} 录屏' if case_id else f'测试录屏'

    return (
        '<div class="video-section">'
        f'<h4>{label}</h4>'
        f'<video class="video-player" controls preload="metadata">'
        f'<source src="{safe_href}" type="video/webm">'
        f'您的浏览器不支持 video 标签。'
        f'<a class="video-link" href="{safe_href}" target="_blank">&#9654; {video_filename}</a>'
        f'</video>'
        f'<div style="font-size:12px;color:#999;margin-top:4px;">{video_filename}</div>'
        '</div>'
    )


def _render_all_videos(video_dir: str | None, test_cases: list | None = None,
                        report_path: Path | None = None) -> str:
    """
    扫描视频目录，渲染所有 .webm 文件列表。
    如果提供了 test_cases，会尝试将视频文件名与用例 ID/名称关联。

    Args:
        video_dir: 视频目录路径，为 None 时返回空字符串
        test_cases: 测试用例列表，用于关联视频与用例

    Returns:
        str: 包含所有录屏链接的 HTML 片段
    """
    if not video_dir:
        return ''

    video_path = Path(video_dir)
    if not video_path.is_dir():
        return ''

    def _safe_mtime(f):
        try:
            return f.stat().st_mtime
        except OSError:
            return 0
    video_files = sorted(
        (f for f in video_path.glob('*.webm')
         if f.name != 'tmp.webm' and f.stat().st_size > 0),
        key=_safe_mtime,
    )
    if not video_files:
        return ''

    # 构建视频文件名到用例描述的映射
    video_case_map = {}
    if test_cases:
        for tc in test_cases:
            video = tc.get('video', '')
            if video:
                video_name = Path(video).name
                desc = tc.get('description', '') or tc.get('name', '')
                status = tc.get('status', '')
                video_case_map[video_name] = {'desc': desc, 'status': status}

    items_html = []
    for idx, vf in enumerate(video_files, 1):
        href = _make_portable_href(vf, report_path)
        safe_href = escape(href)
        safe_name = escape(vf.name)
        size_kb = vf.stat().st_size / 1024
        if size_kb >= 1024:
            size_str = f'{size_kb / 1024:.1f} MB'
        else:
            size_str = f'{size_kb:.0f} KB'

        case_info = video_case_map.get(vf.name, {})
        case_desc = case_info.get('desc', '')
        case_status = case_info.get('status', '')

        status_html = ''
        if case_status:
            badge_class = f'badge-{escape(case_status)}'
            status_label = _status_label(case_status)
            status_html = f'<span class="status-badge {badge_class}" style="font-size:10px;padding:1px 6px;">{escape(status_label)}</span>'

        desc_html = ''
        if case_desc:
            short_desc = case_desc[:60] + ('...' if len(case_desc) > 60 else '')
            desc_html = f'<span style="color:#666;font-size:12px;margin-left:4px;">{escape(short_desc)}</span>'

        items_html.append(
            f'<div class="all-video-item">'
            f'<video controls preload="metadata">'
            f'<source src="{safe_href}" type="video/webm">'
            f'</video>'
            f'<div class="all-video-meta">'
            f'<span class="all-video-index">{idx}</span>'
            f'{status_html}'
            f'<a class="video-link" href="{safe_href}" target="_blank">{safe_name}</a>'
            f'{desc_html}'
            f'<span class="all-video-size">{escape(size_str)}</span>'
            f'</div>'
            f'</div>'
        )

    return (
        '<div class="all-videos-section">'
        f'<h3>所有测试录屏（共 {len(video_files)} 个）</h3>'
        '<div class="all-videos-list">'
        + '\n'.join(items_html)
        + '</div></div>'
    )


def _format_duration(duration_ms: float) -> str:
    """
    格式化耗时显示。

    Args:
        duration_ms: 毫秒数

    Returns:
        str: 格式化后的耗时字符串，如 "1.23s" 或 "456ms"
    """
    if duration_ms >= 1000:
        return f"{duration_ms / 1000:.2f}s"
    return f"{duration_ms:.0f}ms"


def _status_label(status: str) -> str:
    """
    将状态码转换为中文标签。

    Args:
        status: 状态码（PASSED/FAILED/ERROR/SKIPPED）

    Returns:
        str: 中文标签
    """
    mapping = {
        'PASSED': '通过',
        'FAILED': '失败',
        'ERROR': '错误',
        'SKIPPED': '跳过',
    }
    return mapping.get(status, status)


def _render_defect_summary(test_cases: list) -> str:
    """
    渲染失败用例缺陷摘要区域。
    对所有失败/错误用例提取错误类型和关键信息，生成分类摘要。

    Args:
        test_cases: 测试用例结果列表

    Returns:
        str: 缺陷摘要的 HTML 片段，无失败用例时返回空字符串
    """
    failed_cases = [tc for tc in test_cases if tc.get('status') in ('FAILED', 'ERROR')]
    if not failed_cases:
        return ''

    # 按错误类型分类
    error_categories = {}
    for tc in failed_cases:
        err = tc.get('error_message', '') or '未知错误'
        # 优先使用中文描述
        name = tc.get('description') or tc.get('title') or tc.get('name') or tc.get('case_id') or '未知用例'

        # 提取错误类型（取第一个有意义的异常类型行）
        err_type = '其他错误'
        for line in err.split('\n'):
            line = line.strip()
            if not line:
                continue
            # 常见 Playwright/pytest 错误模式
            if 'TimeoutError' in line or 'Timeout' in line:
                err_type = '超时错误（元素定位或页面加载超时）'
                break
            elif 'AssertionError' in line or 'assert' in line.lower() or 'expect' in line.lower():
                err_type = '断言失败（预期结果不匹配）'
                break
            elif 'ElementNotFound' in line or 'not found' in line.lower() or 'no element' in line.lower():
                err_type = '元素未找到（选择器失效）'
                break
            elif 'Error' in line and '(' in line:
                # 提取 ErrorType: message 格式
                err_type = line[:120]
                break

        if err_type not in error_categories:
            error_categories[err_type] = []
        # 取错误的前两行作为摘要
        brief = '\n'.join(err.split('\n')[:2])[:200]
        error_categories[err_type].append((name, brief))

    # 渲染 HTML
    items_html = []
    for err_type, cases in error_categories.items():
        case_list = ''.join(
            f'<li><strong>{escape(name)}</strong>: <code>{escape(brief)}</code></li>'
            for name, brief in cases
        )
        items_html.append(
            f'<div class="defect-category">'
            f'<div class="defect-type">{escape(err_type)}（{len(cases)} 个用例）</div>'
            f'<ul class="defect-cases">{case_list}</ul>'
            f'</div>'
        )

    return (
        '<div class="defect-summary-section">'
        f'<h3>缺陷摘要（{len(failed_cases)} 个失败用例）</h3>'
        + ''.join(items_html)
        + '</div>'
    )


def render_html_report(results: dict, title: str = "WebUI 自动化测试报告",
                       video_dir: str | None = None, workspace: str = '',
                       report_path: Path | None = None) -> str:
    """
    根据测试结果数据渲染完整的 HTML 报告。

    Args:
        results: 测试结果字典，包含 test_cases 和 session_info
        title: 报告标题
        video_dir: 视频目录路径，提供时在报告底部列出所有录屏文件
        workspace: 工作空间根路径，用于解析截图的相对路径
        report_path: 输出 HTML 文件路径，用于生成可移植的相对视频 href

    Returns:
        str: 完整的 HTML 报告字符串
    """
    # ── 提取数据 ──
    test_cases = results.get('test_cases', [])
    # 兼容两种输入格式：原始 test_results（session_info）和 JSON 报告（metadata）
    session_info = results.get('session_info', {})
    metadata = results.get('metadata', {})

    # ── 标准化状态码为大写（兼容 JSON 报告的小写格式） ──
    for tc in test_cases:
        raw_status = tc.get('status', '')
        tc['status'] = raw_status.upper() if raw_status else 'SKIPPED'

    # ── 统计计算 ──
    total = len(test_cases)
    passed = sum(1 for tc in test_cases if tc.get('status') == 'PASSED')
    failed = sum(1 for tc in test_cases if tc.get('status') == 'FAILED')
    error = sum(1 for tc in test_cases if tc.get('status') == 'ERROR')
    skipped = sum(1 for tc in test_cases if tc.get('status') == 'SKIPPED')
    pass_rate = (passed / total * 100) if total > 0 else 0

    # ── 环境信息（优先 session_info，回退 metadata） ──
    browser = escape(str(
        session_info.get('browser') or metadata.get('browser') or '未知'))
    target_url = escape(str(
        session_info.get('target_url') or metadata.get('target_url') or '未知'))
    configured_vp = (session_info.get('configured_viewport')
                      or session_info.get('viewport')
                      or metadata.get('viewport') or {})
    cfg_w = configured_vp.get('width', '?')
    cfg_h = configured_vp.get('height', '?')
    viewport_str = escape(f'{cfg_w}x{cfg_h}')
    observed_ss = session_info.get('observed_screenshot_size')
    observed_vs = session_info.get('observed_video_size')
    ss_match = None
    vs_match = None
    if observed_ss and configured_vp:
        obs_sw, obs_sh = observed_ss.get('width'), observed_ss.get('height')
        ss_match = (cfg_w == obs_sw and cfg_h == obs_sh)
    if observed_vs and configured_vp:
        obs_vw, obs_vh = observed_vs.get('width'), observed_vs.get('height')
        vs_match = (cfg_w == obs_vw and cfg_h == obs_vh)
    parts = []
    if observed_ss:
        obs_sw, obs_sh = observed_ss.get('width'), observed_ss.get('height')
        if ss_match:
            parts.append(f'截图: {obs_sw}x{obs_sh} ✓')
        else:
            parts.append(f'截图: {obs_sw}x{obs_sh} ⚠ 不一致')
    if observed_vs:
        obs_vw, obs_vh = observed_vs.get('width'), observed_vs.get('height')
        if vs_match:
            parts.append(f'录屏: {obs_vw}x{obs_vh} ✓')
        else:
            parts.append(f'录屏: {obs_vw}x{obs_vh} ⚠ 不一致')
    if parts:
        viewport_str += escape(f' (配置) | 实测 {" / ".join(parts)}')
    elif ss_match is True and vs_match is True:
        viewport_str += escape(' (已验证)')
    elif ss_match is True and vs_match is None:
        viewport_str += escape(' (截图已验证)')
    platform = escape(str(
        session_info.get('platform') or metadata.get('platform') or '未知'))
    timestamp = escape(str(
        session_info.get('timestamp') or metadata.get('timestamp') or datetime.now().isoformat()))

    # ── 生成报告时间 ──
    gen_time = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')

    # ── SVG 饼图 ──
    pie_chart = _build_svg_pie_chart(passed, failed, error, skipped)

    # ── 用例卡片 HTML ──
    case_cards_html = []
    for idx, tc in enumerate(test_cases):
        # 兼容 conftest 格式（name/description）和 v1 格式（case_id/title）
        tc_name_raw = tc.get('name') or tc.get('case_id') or f'用例_{idx + 1}'
        tc_desc_raw = tc.get('description') or tc.get('title') or ''
        tc_name = escape(str(tc_name_raw))
        tc_desc = escape(str(tc_desc_raw))
        # 优先展示中文 docstring 描述，无描述时回退到函数名
        tc_display = tc_desc if tc_desc else tc_name
        # 搜索过滤同时匹配函数名和描述
        tc_search = f"{tc_name} {tc_desc}"
        tc_status = tc.get('status', 'SKIPPED')
        tc_duration = float(tc.get('duration_ms') or 0)
        tc_steps = tc.get('steps', [])
        tc_screenshots = tc.get('screenshots', [])
        tc_error = tc.get('error_message', '')
        tc_video = tc.get('video', '')

        # 步骤、截图、错误、视频各区域
        steps_html = _render_steps(tc_steps)
        screenshots_html = _render_screenshots(tc_screenshots, workspace=workspace)
        error_html = _render_error(tc_error)
        video_html = _render_video(tc_video, case_name=tc_name, case_desc=tc_desc,
                                   workspace=workspace, report_path=report_path)

        card = f"""
        <div class="case-card status-{escape(tc_status)}"
             data-name="{escape(tc_search)}"
             data-status="{escape(tc_status)}">
            <div class="case-header" onclick="toggleCase(this)">
                <span class="status-badge badge-{escape(tc_status)}">
                    {escape(_status_label(tc_status))}
                </span>
                <span class="case-name" title="{tc_display}">{tc_display}</span>
                <span class="case-duration">{escape(_format_duration(tc_duration))}</span>
                <span class="expand-icon">&#9654;</span>
            </div>
            <div class="case-body">
                <div class="case-body-inner">
                    {steps_html}
                    {screenshots_html}
                    {error_html}
                    {video_html}
                </div>
            </div>
        </div>
        """
        case_cards_html.append(card)

    # ── 计算总耗时 ──
    total_duration_s = session_info.get('total_duration_seconds', 0)
    if total_duration_s:
        duration_display = f"{total_duration_s:.1f} 秒"
    else:
        # 从用例耗时累加
        total_ms = sum(tc.get('duration_ms', 0) for tc in test_cases)
        duration_display = _format_duration(total_ms)

    # ── 组装完整 HTML ──
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
    {_build_css()}
</head>
<body>
    <!-- ── 页头 ── -->
    <div class="report-header">
        <h1>{escape(title)}</h1>
        <div class="subtitle">生成时间: {escape(gen_time)} | 总耗时: {escape(duration_display)}</div>
    </div>

    <div class="container">
        <!-- ── 统计面板 ── -->
        <div class="stats-dashboard">
            <div class="stat-card total">
                <div class="number">{total}</div>
                <div class="label">总用例数</div>
            </div>
            <div class="stat-card passed">
                <div class="number">{passed}</div>
                <div class="label">通过</div>
            </div>
            <div class="stat-card failed">
                <div class="number">{failed}</div>
                <div class="label">失败</div>
            </div>
            <div class="stat-card error">
                <div class="number">{error}</div>
                <div class="label">错误</div>
            </div>
            <div class="stat-card skipped">
                <div class="number">{skipped}</div>
                <div class="label">跳过</div>
            </div>
        </div>

        <!-- ── 通过率 + 饼图 ── -->
        <div class="pass-rate-section">
            <div class="pass-rate-text">
                <div class="rate">{pass_rate:.1f}%</div>
                <div class="rate-label">用例通过率</div>
            </div>
            <div class="pie-chart-container">
                {pie_chart}
            </div>
        </div>

        <!-- ── 环境信息条 ── -->
        <div class="env-bar">
            <div class="env-item">
                <span class="env-label">浏览器:</span>
                <span>{browser}</span>
            </div>
            <div class="env-item">
                <span class="env-label">目标 URL:</span>
                <span>{target_url}</span>
            </div>
            <div class="env-item">
                <span class="env-label">视口:</span>
                <span>{viewport_str}</span>
            </div>
            <div class="env-item">
                <span class="env-label">操作系统:</span>
                <span>{platform}</span>
            </div>
            <div class="env-item">
                <span class="env-label">执行时间:</span>
                <span>{timestamp}</span>
            </div>
        </div>

        {_render_defect_summary(test_cases)}

        <!-- ── 工具栏 ── -->
        <div class="toolbar">
            <input type="text" id="searchInput" class="search-box"
                   placeholder="搜索用例名称...">
            <button class="filter-btn active" data-status="all"
                    onclick="setStatusFilter(this)">全部 ({total})</button>
            <button class="filter-btn" data-status="PASSED"
                    onclick="setStatusFilter(this)">通过 ({passed})</button>
            <button class="filter-btn" data-status="FAILED"
                    onclick="setStatusFilter(this)">失败 ({failed})</button>
            <button class="filter-btn" data-status="ERROR"
                    onclick="setStatusFilter(this)">错误 ({error})</button>
            <span id="visibleCount" style="font-size:13px;color:#999;"></span>
            <button class="action-btn" onclick="expandAll()">展开全部</button>
            <button class="action-btn" onclick="collapseAll()">折叠全部</button>
        </div>

        <!-- ── 用例卡片列表 ── -->
        <div class="case-list">
            {''.join(case_cards_html)}
        </div>

        {_render_all_videos(video_dir, test_cases=test_cases, report_path=report_path)}
    </div>

    <!-- ── 页脚 ── -->
    <div class="report-footer">
        <div class="divider"></div>
        {escape(REPORT_VERSION)} | {escape(gen_time)}<br>
        WebUI 自动化测试平台
    </div>

    <!-- ── 截图灯箱 ── -->
    <div class="lightbox-overlay" id="lightboxOverlay" onclick="closeLightbox()">
        <img id="lightboxImg" src="" alt="截图预览" />
    </div>

    {_build_js()}
</body>
</html>"""

    return html


def main():
    """
    命令行入口。
    解析参数并生成 HTML 报告文件。
    """
    parser = argparse.ArgumentParser(
        description='WebUI 自动化测试 HTML 报告生成器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
    python generate_webui_html_report.py \\
        --results test_results_20240101.json \\
        --output report_20240101.html \\
        --title "WebUI 回归测试报告"
        """
    )
    parser.add_argument(
        '--results', required=True,
        help='测试结果 JSON 文件路径（conftest_webui_plugin.py 输出的 test_results_*.json）'
    )
    parser.add_argument(
        '--output', required=True,
        help='输出 HTML 报告文件路径'
    )
    parser.add_argument(
        '--title', default='WebUI 自动化测试报告',
        help='报告标题（默认: WebUI 自动化测试报告）'
    )
    parser.add_argument(
        '--video-dir', default=None,
        help='视频目录路径，提供时在报告底部列出所有录屏文件'
    )
    parser.add_argument(
        '--workspace', default='',
        help='工作空间根路径，用于解析截图的相对路径'
    )
    args = parser.parse_args()

    # 读取测试结果 JSON
    results_path = Path(args.results)
    if not results_path.exists():
        print(f'错误: 测试结果文件不存在: {results_path}', file=sys.stderr)
        sys.exit(1)

    try:
        results_data = json.loads(results_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        print(f'错误: 测试结果 JSON 解析失败: {e}', file=sys.stderr)
        sys.exit(1)

    # 自动推断 workspace（如果未指定，从结果文件路径向上查找）
    workspace = args.workspace
    if not workspace:
        # 优先查找包含 qa/webui/session* 结构的项目根
        candidate = results_path.resolve().parent
        while candidate != candidate.parent:
            aqe_dir = candidate / 'qa/webui'
            if aqe_dir.is_dir():
                has_session = any(
                    d.name.startswith('webui-session')
                    for d in aqe_dir.iterdir() if d.is_dir()
                )
                if has_session:
                    workspace = str(candidate)
                    break
            candidate = candidate.parent

    output_path = Path(args.output).resolve()

    html_content = render_html_report(
        results_data, title=args.title, video_dir=args.video_dir,
        workspace=workspace, report_path=output_path,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding='utf-8')

    print(f'HTML 报告已生成: {output_path}')
    print(f'  用例总数: {len(results_data.get("test_cases", []))}')
    print(str(output_path))


if __name__ == '__main__':
    main()
