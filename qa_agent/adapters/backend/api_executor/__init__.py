"""
API Test Executor（移植自 oec-infra api-test-executor）

核心功能：
1. 智能执行器：pytest + 401 鉴权处理 + 实时进度展示
2. 智能分析引擎：7 大失败分类（网络/HTTP/参数/响应/认证/脚本/环境）
3. 脚本自动修复：检测到脚本错误自动修复重试
4. 专业 HTML 报告：紫色渐变统计栏、卡片式布局、搜索过滤、饼图统计
5. pytest 插件：捕获每个接口的请求/响应详情

集成到 Backend Adapter 使用，替代原有的简单 pytest 执行逻辑。
"""

from pathlib import Path

__all__ = []

# 配置常量
DEFAULT_REPORT_DIR = 'qa/backend/reports'
CONFTEST_PLUGIN_PATH = Path(__file__).parent / 'conftest_plugin.py'
