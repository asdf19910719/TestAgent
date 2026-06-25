"""
Maestro 执行器: 调用 Maestro CLI 执行 flow,解析结果

依赖:
- Maestro CLI (npm install -g @maestro/cli 或 brew install maestro)
- adb 连接的设备

执行模式:
- 本地设备: maestro test flow.yaml --device <id>
- 多设备并行: 未来扩展
"""

import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional


class MaestroExecutor:
    """Maestro flow 执行器"""

    def __init__(self, maestro_cli: str = 'maestro'):
        """
        Args:
            maestro_cli: Maestro CLI 命令路径(默认 'maestro',从 PATH 查找)
        """
        self.cli = maestro_cli

    def check_available(self) -> bool:
        """检查 Maestro CLI 是否可用"""
        try:
            result = subprocess.run(
                [self.cli, '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def list_devices(self) -> list:
        """列出可用设备(通过 adb)"""
        try:
            result = subprocess.run(
                ['adb', 'devices'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return []

            # 解析 adb devices 输出
            lines = result.stdout.strip().split('\n')[1:]  # 跳过表头
            devices = []
            for line in lines:
                if '\tdevice' in line:
                    device_id = line.split('\t')[0]
                    devices.append(device_id)
            return devices
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

    def run_flow(
        self,
        flow_path: Path,
        device_id: Optional[str] = None,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        执行 Maestro flow

        Args:
            flow_path: .yaml flow 文件路径
            device_id: 设备 ID(可选,不指定则用第一个可用设备)
            timeout: 超时秒数

        Returns:
            {
                'success': bool,
                'duration': float,  # 秒
                'output': str,      # 原始输出
                'error': str,       # 错误信息(如有)
                'passed_steps': int,
                'failed_steps': int
            }
        """
        if not flow_path.exists():
            return {
                'success': False,
                'error': f'Flow 文件不存在: {flow_path}',
                'output': '',
                'duration': 0,
                'passed_steps': 0,
                'failed_steps': 0
            }

        # 构建命令
        cmd = [self.cli, 'test', str(flow_path)]
        if device_id:
            cmd.extend(['--device', device_id])

        # 执行
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=flow_path.parent  # 在 flow 目录下执行(Maestro 的相对路径规则)
            )

            # 解析输出
            output = result.stdout + result.stderr
            success = result.returncode == 0

            # 简化解析(Maestro 输出格式可能变化,这里做基本提取)
            passed, failed = self._parse_maestro_output(output)

            return {
                'success': success,
                'output': output,
                'error': result.stderr if not success else '',
                'duration': 0,  # Maestro CLI 不直接返回时长,需从输出解析
                'passed_steps': passed,
                'failed_steps': failed
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': f'执行超时({timeout}s)',
                'output': '',
                'duration': timeout,
                'passed_steps': 0,
                'failed_steps': 0
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'output': '',
                'duration': 0,
                'passed_steps': 0,
                'failed_steps': 0
            }

    def _parse_maestro_output(self, output: str) -> tuple:
        """
        解析 Maestro 输出,提取通过/失败步骤数

        Maestro 输出示例:
        ✅ Step 1: launchApp
        ✅ Step 2: tapOn "同步"
        ❌ Step 3: assertVisible "结果"
        ...
        """
        passed = output.count('✅')
        failed = output.count('❌')
        return (passed, failed)
