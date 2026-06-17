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
    elif project_type == 'mobile':
        from .mobile import MobileAdapter
        return MobileAdapter()
    elif project_type == 'generic':
        from .generic import GenericAdapter
        from ..core.config import load_config
        return GenericAdapter(config=load_config())
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

    cwd = Path('.')

    # 优先级 2: 自动检测移动端（Flutter / RN / Android / iOS）
    mobile_indicators = [
        cwd / 'pubspec.yaml',                          # Flutter
        cwd / 'app' / 'build.gradle',                  # Android（多模块）
        cwd / 'app' / 'build.gradle.kts',
        cwd / 'build.gradle',                          # Android（单模块）
    ]
    if any(p.exists() for p in mobile_indicators):
        from .mobile import MobileAdapter
        adapter = MobileAdapter()
        try:
            fingerprint = adapter.detect()
            print(f"[Adapter] 检测到项目类型: {fingerprint.project_type}")
            return adapter
        except Exception as e:
            print(f"[Adapter] Mobile 检测失败: {e}")

    # iOS 项目
    if list(cwd.glob('*.xcodeproj')) or (cwd / 'Package.swift').exists():
        from .mobile import MobileAdapter
        return MobileAdapter()

    # Web 项目
    if (cwd / 'package.json').exists():
        # 优先看是否含 react-native（移动端）
        try:
            import json
            pkg = json.loads((cwd / 'package.json').read_text(encoding='utf-8'))
            deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
            if 'react-native' in deps:
                from .mobile import MobileAdapter
                return MobileAdapter()
        except Exception:
            pass

        from .web import WebAdapter
        adapter = WebAdapter()
        try:
            fingerprint = adapter.detect()
            print(f"[Adapter] 检测到项目类型: {fingerprint.project_type}")
            return adapter
        except Exception as e:
            print(f"[Adapter] Web 检测失败: {e}")

    # Python Backend
    if (cwd / 'pyproject.toml').exists() or (cwd / 'setup.py').exists():
        from .backend import BackendAdapter
        adapter = BackendAdapter()
        try:
            fingerprint = adapter.detect()
            print(f"[Adapter] 检测到项目类型: {fingerprint.project_type}")
            return adapter
        except Exception as e:
            print(f"[Adapter] Backend 检测失败: {e}")

    # Go / Rust 也归为 Backend
    if (cwd / 'go.mod').exists() or (cwd / 'Cargo.toml').exists():
        from .backend import BackendAdapter
        return BackendAdapter()

    # 优先级 3: Generic 兜底
    print("⚠️ 无法识别项目类型，使用 Generic Adapter（请在 .qa-agent.yml 配置 commands）")
    from .generic import GenericAdapter
    return GenericAdapter(config=config)
