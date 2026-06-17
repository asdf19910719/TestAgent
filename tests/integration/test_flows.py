"""
集成测试：完整 L1/L4/L0 流程端到端
"""

import pytest
from pathlib import Path
import tempfile
import os

from qa_agent.core.engine import Engine
from qa_agent.core.types import Mode


class TestIntegration:
    """端到端集成测试"""

    def test_l1_feature_flow(self, tmp_path):
        """测试 L1 完整流程"""
        # 准备测试环境
        os.chdir(tmp_path)
        self._setup_test_repo(tmp_path)

        # 创建配置
        config_path = tmp_path / '.qa-agent.yml'
        config_path.write_text('impact_analysis: local\n')

        # 运行 L1
        engine = Engine(str(config_path))
        result = engine.run(Mode.L1, scope='test_feature', command='/qa feature test')

        # 验证结果
        assert result['status'] == 'completed'
        assert result['verdict'] in ('PASS', 'FAIL', 'CONDITIONAL PASS')
        assert (tmp_path / 'qa' / 'run' / 'last.json').exists()
        assert (tmp_path / 'qa' / 'run' / 'selection.md').exists()
        assert (tmp_path / 'qa' / 'final_test_report.md').exists()

    def test_l4_bugfix_flow(self, tmp_path):
        """测试 L4 完整流程"""
        os.chdir(tmp_path)
        self._setup_test_repo(tmp_path)

        config_path = tmp_path / '.qa-agent.yml'
        config_path.write_text('impact_analysis: local\n')

        engine = Engine(str(config_path))
        result = engine.run(Mode.L4, scope='BUG-001', command='/qa bugfix BUG-001')

        assert result['status'] == 'completed'
        assert result['verdict'] in ('PASS', 'FAIL')

    def test_l0_spot_flow(self, tmp_path):
        """测试 L0 快速流程"""
        os.chdir(tmp_path)
        self._setup_test_repo(tmp_path)

        config_path = tmp_path / '.qa-agent.yml'
        config_path.write_text('impact_analysis: local\n')

        engine = Engine(str(config_path))
        result = engine.run(Mode.L0, scope='spot', command='/qa L0')

        assert result['status'] == 'completed'
        # L0 应该很快
        assert result['execution']['total'] <= 10

    def _setup_test_repo(self, path: Path):
        """设置测试仓库"""
        # 初始化 git
        import subprocess
        subprocess.run(['git', 'init'], cwd=path, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=path, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=path, capture_output=True)

        # 创建初始文件
        (path / 'src').mkdir()
        (path / 'src' / 'test.py').write_text('def test(): pass\n')
        subprocess.run(['git', 'add', '.'], cwd=path, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=path, capture_output=True)

        # 创建变更
        (path / 'src' / 'test.py').write_text('def test(): return True\n')

        # 创建 qa 目录
        (path / 'qa' / 'cases').mkdir(parents=True)
