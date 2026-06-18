"""
Configuration loader
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional


DEFAULT_CONFIG = {
    'project_type': None,
    'language': None,
    'frameworks': {},
    'impact_analysis': 'gitnexus',
    'mode_limits': {
        'L0': 10,
        'L1': 80,
        'L2': 500,
        'L3': -1,
        'L4': 20
    },
    'repair_loop': {
        'mode': 'manual',
        'per_case_attempts': 3,
        'total_rounds': 5
    },
    'nonfunctional': {
        'dependency_audit': {'enabled': True, 'modes': ['L3']},
        'static_security': {'enabled': True, 'modes': ['L3']},
        'dynamic_security_scan': {'enabled': False, 'modes': ['L3']},
        'performance': {'enabled': False, 'modes': ['L3']},
        'compatibility': {'enabled': False, 'modes': ['L3']}
    },
    'mutation': {
        'enabled': 'auto',
        'scope': 'diff',
        'enabled_modes': ['L3'],
        'on_tool_missing': 'skip'
    },
    'roles': {
        'designer_runner_model': 'claude-opus-4-7',
        'gatekeeper_model': 'claude-haiku-4-5',
        'gatekeeper_model_l3': 'claude-opus-4-7',
        'gatekeeper_skip_llm_for': ['L0', 'L4'],
        'gatekeeper_cache': True
    },
    'webui': {
        # WebUI E2E 增强器配置（移植自 oec-infra webui-test-unified）
        'e2e_enhancer': {
            'enabled': 'auto',  # auto=自动检测 | always=强制启用 | never=禁用
            'trigger_levels': ['system', 'acceptance'],  # 哪些级别自动启用
            'target_url': None,  # 默认目标 URL（可覆盖）
            'credentials': None,  # 默认登录凭据 {'username': '...', 'password': '...'}
            'fallback_on_login_failure': True,  # 登录失败时回退到普通骨架
        }
    },
    'gitnexus': {
        # MCP 工具前缀（列表，按优先级依次尝试）
        'mcp_tool_prefixes': ['mcp__gitnexus', 'mcp__gitnexus22'],
        'upstream_depth': {
            'L0': 2,
            'L1': 3,
            'L2': 3,
            'L3': -1,
            'L4': 3
        }
    },
    # E2E 测试环境自动启动配置
    'dev_server': {
        'command': None,       # 如: 'npm run dev' / 'pnpm dev' / 'make serve'
        'port': None,          # 如: 3000 / 5173 / 8080
        'ready_timeout': 30,   # 等待就绪超时（秒）
        'ready_check': None,   # 就绪检查 URL，如 'http://localhost:3000'
    },
    'services': [],            # 额外依赖服务，如:
    # - {name: 'llm-backend', command: 'python server.py', port: 8000}
    # - {name: 'db', command: 'docker-compose up -d postgres', port: 5432}
    'impact_fallback': 'prompt'
}


def load_config(config_path: str = '.qa-agent.yml') -> Dict[str, Any]:
    """
    加载项目配置，合并默认值
    """
    config = DEFAULT_CONFIG.copy()

    path = Path(config_path)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}

        # 深度合并
        config = deep_merge(config, user_config)

    return config


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    深度合并两个字典
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def save_config(config: Dict[str, Any], config_path: str = '.qa-agent.yml') -> None:
    """
    保存配置到文件
    """
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
