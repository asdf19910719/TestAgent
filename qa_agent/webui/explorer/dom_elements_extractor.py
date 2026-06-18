"""
公共 DOM 交互元素提取模块

提供统一的 page.evaluate JS 模板，供以下脚本共享：
- uitest-page-explorer/scripts/explore_page.py
- uitest-login-handler/scripts/login_password.py
- uitest-login-handler/scripts/login_cookie.py
- uitest-login-handler/scripts/login_token.py

选择器规则（统一为宽兼容版本）：
- 按钮：button, [role="button"], a.btn, input[type="submit"], input[type="button"]
- 输入框：input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea
- 选择框：select, [role="combobox"]
- 链接：a[href]
"""

# 统一的元素提取 JS 模板
ELEMENTS_EXTRACT_JS = '''() => {
    const results = [];
    let id = 0;

    function isVisible(el) {
        if (el.offsetParent !== null) return true;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    function getSelectors(el) {
        const selectors = [];
        const testId = el.getAttribute('data-testid') || el.getAttribute('data-test');
        if (testId) {
            selectors.push({strategy: 'data-testid', value: `[data-testid="${testId}"]`, priority: 1});
        }
        if (el.id) {
            selectors.push({strategy: 'css', value: '#' + el.id, priority: 1});
        }
        const role = el.getAttribute('role') || el.tagName.toLowerCase();
        const ariaLabel = el.getAttribute('aria-label') || el.innerText?.trim().substring(0, 30);
        if (ariaLabel) {
            selectors.push({strategy: 'role', value: `role=${role}[name="${ariaLabel}"]`, priority: 2});
        }
        const labelFor = el.id ? document.querySelector(`label[for="${el.id}"]`) : null;
        if (labelFor) {
            selectors.push({strategy: 'label', value: `label:has-text("${labelFor.textContent.trim()}")`, priority: 3});
        }
        const placeholder = el.getAttribute('placeholder');
        if (placeholder) {
            selectors.push({strategy: 'placeholder', value: `[placeholder="${placeholder}"]`, priority: 4});
        }
        if (el.name) {
            selectors.push({strategy: 'css', value: `[name="${el.name}"]`, priority: 4});
        }
        const text = el.innerText?.trim().substring(0, 50);
        if (text && text.length <= 30) {
            selectors.push({strategy: 'text', value: `text=${text}`, priority: 5});
        }
        const tag = el.tagName.toLowerCase();
        const classes = Array.from(el.classList || []).filter(c => !c.startsWith('css-')).slice(0, 2).join('.');
        if (classes) {
            selectors.push({strategy: 'css', value: `${tag}.${classes}`, priority: 6});
        }
        return selectors;
    }

    function extractFrom(root, iframePrefix) {
        const pfx = iframePrefix || '';
        root.querySelectorAll('button, [role="button"], a.btn, input[type="submit"], input[type="button"]').forEach(el => {
            if (!isVisible(el)) return;
            const text = el.innerText?.trim() || el.value || el.getAttribute('aria-label') || '';
            if (!text && !el.id && !el.name) return;
            results.push({
                id: `elem_${++id}`, type: 'button', text: text,
                selectors: getSelectors(el),
                attributes: {disabled: el.disabled || false, visible: true},
                iframe: pfx || undefined
            });
        });
        root.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea').forEach(el => {
            if (!isVisible(el)) return;
            results.push({
                id: `elem_${++id}`, type: 'input',
                text: el.placeholder || el.name || '',
                input_type: el.type || 'text',
                selectors: getSelectors(el),
                attributes: {required: el.required || false, disabled: el.disabled || false, visible: true},
                iframe: pfx || undefined
            });
        });
        root.querySelectorAll('select, [role="combobox"]').forEach(el => {
            if (!isVisible(el)) return;
            const options = el.tagName === 'SELECT'
                ? Array.from(el.options).map(o => o.text).slice(0, 10) : [];
            results.push({
                id: `elem_${++id}`, type: 'select',
                text: el.name || '', options: options,
                selectors: getSelectors(el),
                attributes: {required: el.required || false, visible: true},
                iframe: pfx || undefined
            });
        });
        root.querySelectorAll('a[href]').forEach(el => {
            if (!isVisible(el)) return;
            const text = el.innerText?.trim();
            if (!text || text.length > 50) return;
            results.push({
                id: `elem_${++id}`, type: 'link',
                text: text, href: el.href,
                selectors: getSelectors(el),
                attributes: {visible: true},
                iframe: pfx || undefined
            });
        });
    }

    extractFrom(document, '');

    document.querySelectorAll('iframe').forEach((iframe, idx) => {
        try {
            const doc = iframe.contentDocument;
            if (!doc) return;
            extractFrom(doc, `iframe[${idx}]`);
        } catch(e) {}
    });

    return results;
}'''


def extract_page_elements(page) -> list:
    """
    从页面 DOM 提取关键交互元素的便捷函数。

    Args:
        page: Playwright page 对象

    Returns:
        list: 交互元素列表，包含 type/text/selectors/attributes 等字段
    """
    return page.evaluate(ELEMENTS_EXTRACT_JS)


# ── 公共浏览器启动工具 ─────────────────────────────────────────────
import json as _json
import os as _os
from pathlib import Path as _Path


def _read_session_browser(workspace):
    """从 session-context.json 读取 browser 字段，返回 'chromium' 或 'chrome'。"""
    if not workspace:
        return 'chromium'
    pointer = _Path(workspace) / 'qa/webui' / 'current_session.json'
    if pointer.exists():
        try:
            sb = _json.loads(pointer.read_text(encoding='utf-8')).get('sessionBase', '')
            if sb:
                ctx_path = _Path(workspace) / sb / 'session-context.json'
                if ctx_path.exists():
                    return _json.loads(ctx_path.read_text(encoding='utf-8')).get('browser', 'chromium')
        except (ValueError, OSError):
            pass
    ctx_fallback = _Path(workspace) / 'qa/webui' / 'webui-session' / 'session-context.json'
    if ctx_fallback.exists():
        try:
            return _json.loads(ctx_fallback.read_text(encoding='utf-8')).get('browser', 'chromium')
        except (ValueError, OSError):
            pass
    return 'chromium'


def launch_browser(pw, browser_type='chromium', headless=None, **extra_launch_args):
    """
    统一的浏览器启动函数，从 session-context.json 读取浏览器类型。

    Playwright 统一走 pw.chromium launcher；当 browser_type=='chrome' 时通过 channel='chrome' 切换。
    headless 默认由 FORCE_HEADED 环境变量控制。

    Args:
        pw: sync_playwright() 上下文对象
        browser_type: 'chromium' 或 'chrome'
        headless: 是否无头模式（None=由环境变量决定）
        **extra_launch_args: 传递给 launch() 的额外参数

    Returns:
        Browser 实例
    """
    if headless is None:
        headless = _os.environ.get('FORCE_HEADED') != '1'
    launch_args = {'headless': headless, **extra_launch_args}
    if browser_type == 'chrome':
        launch_args['channel'] = 'chrome'
    return pw.chromium.launch(**launch_args)
