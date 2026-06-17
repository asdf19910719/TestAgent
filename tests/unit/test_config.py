"""
测试配置加载和合并
"""

import pytest
import tempfile
import yaml
from pathlib import Path

from qa_agent.core.config import load_config, deep_merge, save_config, DEFAULT_CONFIG


class TestConfig:
    """测试配置系统"""

    def test_load_default_config_when_file_not_exists(self):
        """文件不存在时返回默认配置"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'nonexistent.yml'
            config = load_config(str(config_path))

            assert config['impact_analysis'] == 'gitnexus'
            assert config['mode_limits']['L0'] == 10
            assert config['repair_loop']['mode'] == 'manual'

    def test_deep_merge(self):
        """测试深度合并"""
        base = {
            'a': 1,
            'b': {'c': 2, 'd': 3},
            'e': [1, 2]
        }

        override = {
            'b': {'c': 99, 'f': 4},
            'g': 5
        }

        result = deep_merge(base, override)

        assert result['a'] == 1
        assert result['b']['c'] == 99
        assert result['b']['d'] == 3
        assert result['b']['f'] == 4
        assert result['g'] == 5

    def test_save_and_load_config(self):
        """测试保存和加载配置"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'test.yml'

            config = {
                'project_type': 'web',
                'language': 'typescript',
                'frameworks': {'unit': 'vitest'}
            }

            save_config(config, str(config_path))
            loaded = load_config(str(config_path))

            assert loaded['project_type'] == 'web'
            assert loaded['language'] == 'typescript'
            assert loaded['frameworks']['unit'] == 'vitest'
            # 默认值也应该合并进来
            assert loaded['impact_analysis'] == 'gitnexus'

    def test_user_config_overrides_default(self):
        """用户配置应该覆盖默认值"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / 'test.yml'

            user_config = {
                'impact_analysis': 'local',
                'mode_limits': {'L0': 20}
            }

            with open(config_path, 'w') as f:
                yaml.dump(user_config, f)

            loaded = load_config(str(config_path))

            assert loaded['impact_analysis'] == 'local'
            assert loaded['mode_limits']['L0'] == 20
            assert loaded['mode_limits']['L1'] == 80  # 默认值保留
