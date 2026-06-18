"""
WebUI 自动化测试工具包（移植自 oec-infra webui-test-unified）

核心组件：
1. login: 登录处理（密码/Cookie/Token + 配方复用）
2. explorer: DOM 探索 + Smart XPath 生成
3. executor: 批量执行器 + Sentinel 预算守卫
4. reporter: 专业 HTML/JSON 报告生成
5. validators: 脚本深度校验（永真断言/空 try/except）

集成到 WebAdapter 使用，替代原有的简单骨架生成。
"""

__all__ = []

# 产物目录规范
WEBUI_SESSION_DIR = 'qa/webui/session'
WEBUI_SHARED_DIR = 'qa/webui/shared_assets'
