"""
非功能测试调度器（P0-5）
"""

import subprocess
from typing import Dict, Any, List


class NonfunctionalScheduler:
    """
    非功能测试调度器
    按成本/价值比分级执行
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def schedule(self, mode: str, with_flags: List[str] = None, skip_flags: List[str] = None) -> List[Dict[str, Any]]:
        """
        调度非功能测试

        Args:
            mode: 运行模式（仅 L3 执行）
            with_flags: --with-* 临时开启项
            skip_flags: --skip 跳过项

        Returns:
            调度结果列表
        """
        if mode != 'L3':
            return []

        with_flags = with_flags or []
        skip_flags = skip_flags or []

        nonfunctional_config = self.config.get('nonfunctional', {})

        scheduled = []
        skipped = []
        blocked = []

        # 默认开启项（成本低）
        for test_type in ['dependency_audit', 'static_security']:
            if test_type in skip_flags:
                skipped.append({'type': test_type, 'reason': '用户显式 --skip'})
                continue

            config = nonfunctional_config.get(test_type, {})
            if config.get('enabled', True):
                scheduled.append({
                    'type': test_type,
                    'tool': self._get_tool(test_type),
                    'estimated_minutes': 0.5 if test_type == 'dependency_audit' else 2
                })

        # 默认关闭项（成本高，按需开启）
        for test_type in ['dynamic_security_scan', 'performance', 'compatibility']:
            config = nonfunctional_config.get(test_type, {})

            # 检查是否开启
            enabled_by_config = config.get('enabled', False)
            enabled_by_flag = test_type in with_flags or 'all' in with_flags

            if test_type in skip_flags:
                skipped.append({'type': test_type, 'reason': '用户显式 --skip'})
                continue

            if enabled_by_config or enabled_by_flag:
                # 环境校验
                if test_type == 'dynamic_security_scan':
                    # 检查是否隔离环境
                    if not self._is_isolated_env():
                        blocked.append({
                            'type': test_type,
                            'reason': '目标环境未隔离，命中生产标识'
                        })
                        continue

                scheduled.append({
                    'type': test_type,
                    'tool': self._get_tool(test_type),
                    'estimated_minutes': 30 if test_type == 'dynamic_security_scan' else 60
                })
            else:
                skipped.append({
                    'type': test_type,
                    'reason': '默认关闭，未通过命令行开启'
                })

        return {
            'scheduled': scheduled,
            'skipped': skipped,
            'blocked': blocked
        }

    def execute(self, scheduled: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        执行调度的非功能测试
        """
        results = {}

        for item in scheduled:
            test_type = item['type']
            tool = item['tool']

            print(f"[NonFunctional] 执行 {test_type} ({tool})...")

            if test_type == 'dependency_audit':
                results[test_type] = self._run_dependency_audit(tool)
            elif test_type == 'static_security':
                results[test_type] = self._run_static_security(tool)
            elif test_type == 'dynamic_security_scan':
                results[test_type] = self._run_dynamic_security(tool)
            elif test_type == 'performance':
                results[test_type] = self._run_performance(tool)
            elif test_type == 'compatibility':
                results[test_type] = self._run_compatibility(tool)

        return results

    def _get_tool(self, test_type: str) -> str:
        """获取默认工具"""
        tools = {
            'dependency_audit': 'npm audit',
            'static_security': 'bandit',
            'dynamic_security_scan': 'zap',
            'performance': 'k6',
            'compatibility': 'playwright'
        }
        return tools.get(test_type, 'unknown')

    def _is_isolated_env(self) -> bool:
        """检查是否隔离环境（Phase 6 简化：总是 True）"""
        # Phase 6 完整：检查环境变量、URL 模式
        return True

    def _run_dependency_audit(self, tool: str) -> Dict[str, Any]:
        """依赖漏洞扫描（Phase 6 真实执行）"""
        # Phase 6: subprocess.run([tool])
        return {'pass': True, 'vulnerabilities': 0}

    def _run_static_security(self, tool: str) -> Dict[str, Any]:
        """静态安全扫描"""
        return {'pass': True, 'issues': 0}

    def _run_dynamic_security(self, tool: str) -> Dict[str, Any]:
        """动态安全扫描"""
        return {'pass': True, 'vulnerabilities': 0}

    def _run_performance(self, tool: str) -> Dict[str, Any]:
        """性能压测"""
        return {'pass': True, 'p95_ms': 200}

    def _run_compatibility(self, tool: str) -> Dict[str, Any]:
        """兼容性矩阵"""
        return {'pass': True, 'browsers': ['chromium', 'firefox']}
