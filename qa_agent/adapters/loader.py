"""
Adapter 加载器
"""

from pathlib import Path
from typing import Optional


def load_adapter(project_type: str):
    """
    动态加载 Adapter
    """
    if project_type == 'web':
        from .web import WebAdapter
        return WebAdapter()
    elif project_type == 'backend':
        from .backend import BackendAdapter
        return BackendAdapter()
    elif project_type == 'generic':
        # Phase 2 已实现骨架
        raise NotImplementedError("Generic Adapter 在 Phase 5 完善")
    else:
        raise ValueError(f"未知项目类型: {project_type}")


def auto_detect_adapter(config_path: str = '.qa-agent.yml'):
    """
    自动检测并加载 Adapter
    """
    from ..core.config import load_config

    config = load_config(config_path)

    # 优先级 1: 配置显式指定
    if config.get('project_type'):
        return load_adapter(config['project_type'])

    # 优先级 2: 自动检测
    cwd = Path('.')

    # 检测 Web
    if (cwd / 'package.json').exists():
        from .web import WebAdapter
        adapter = WebAdapter()
        try:
            fingerprint = adapter.detect()
            print(f"[Adapter] 检测到项目类型: {fingerprint.project_type}")
            return adapter
        except Exception as e:
            print(f"[Adapter] Web 检测失败: {e}")

    # 检测 Python Backend
    if (cwd / 'pyproject.toml').exists() or (cwd / 'setup.py').exists():
        from .backend import BackendAdapter
        adapter = BackendAdapter()
        try:
            fingerprint = adapter.detect()
            print(f"[Adapter] 检测到项目类型: {fingerprint.project_type}")
            return adapter
        except Exception as e:
            print(f"[Adapter] Backend 检测失败: {e}")

    # 优先级 3: Generic 兜底
    print("⚠️ 无法识别项目类型，使用 Generic Adapter")
    raise NotImplementedError("Generic Adapter 在 Phase 5 完善")
