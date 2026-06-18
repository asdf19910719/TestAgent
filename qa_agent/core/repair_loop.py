"""
Repair Loop 配置管理模块

统一管理 repair_loop 相关配置，提供给各个 Adapter 和执行器使用。

三种模式：
- manual: 手动修复（不自动重试）
- auto-dev: 开发模式（适度重试，快速反馈）
- auto-fixer: 自动修复模式（积极重试，生产环境）
"""

from typing import Dict, Any
from pathlib import Path


class RepairLoopConfig:
    """Repair Loop 配置封装"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        repair_loop_cfg = config.get('repair_loop', {})

        # 读取配置
        self.mode = repair_loop_cfg.get('mode', 'manual')
        self.per_case_attempts = repair_loop_cfg.get('per_case_attempts', 3)
        self.total_rounds = repair_loop_cfg.get('total_rounds', 5)

    @property
    def enabled(self) -> bool:
        """是否启用自动修复"""
        return self.mode in ('auto-dev', 'auto-fixer')

    @property
    def max_retries_per_case(self) -> int:
        """
        单个用例最多重试次数

        映射规则：
        - manual: 0（不重试）
        - auto-dev: per_case_attempts（默认 3）
        - auto-fixer: per_case_attempts（默认 3）
        """
        if self.mode == 'manual':
            return 0
        return self.per_case_attempts

    @property
    def max_execution_rounds(self) -> int:
        """
        执行最多轮数（整体预算）

        映射规则：
        - manual: 1（不重试）
        - auto-dev: total_rounds（默认 5）
        - auto-fixer: total_rounds（默认 5）
        """
        if self.mode == 'manual':
            return 1
        return self.total_rounds

    @property
    def script_auto_fix_enabled(self) -> bool:
        """脚本错误是否自动修复"""
        # 只有 auto-fixer 模式才启用脚本自动修复
        return self.mode == 'auto-fixer'

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典（用于日志/状态）"""
        return {
            'mode': self.mode,
            'per_case_attempts': self.per_case_attempts,
            'total_rounds': self.total_rounds,
            'enabled': self.enabled,
            'max_retries_per_case': self.max_retries_per_case,
            'max_execution_rounds': self.max_execution_rounds,
            'script_auto_fix_enabled': self.script_auto_fix_enabled,
        }


def get_repair_loop_config(config: Dict[str, Any]) -> RepairLoopConfig:
    """
    获取 repair_loop 配置实例

    Args:
        config: 完整配置字典（来自 load_config()）

    Returns:
        RepairLoopConfig 实例
    """
    return RepairLoopConfig(config)


# 向后兼容：提供常量形式的默认值
DEFAULT_REPAIR_LOOP = {
    'mode': 'manual',
    'per_case_attempts': 3,
    'total_rounds': 5
}
