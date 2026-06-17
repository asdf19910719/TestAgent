"""
端到端集成测试：Subagent 工具链完整流程
验证 prepare → execute → judge 命令组合可用
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def test_project(tmp_path, monkeypatch):
    """准备一个最小可测项目"""
    monkeypatch.chdir(tmp_path)

    def _git(*args):
        """运行 git 命令（修复 Windows + Python 3.14 subprocess 句柄问题）"""
        return subprocess.run(
            ['git'] + list(args),
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

    # git 初始化
    _git('init')
    _git('config', 'user.name', 'Test')
    _git('config', 'user.email', 'test@example.com')

    # 最小源码
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'app.py').write_text('def hello(): return "hello"\n')

    # pyproject.toml 让 Backend Adapter 识别
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.poetry]\nname = "demo"\nversion = "0.1.0"\n'
    )

    # 初始 commit
    _git('add', '.')
    _git('commit', '-m', 'init')

    # 制造一个变更并第二次 commit（确保 HEAD~1 有效）
    (tmp_path / 'src' / 'app.py').write_text('def hello(): return "hi"\n')
    _git('add', '.')
    _git('commit', '-m', 'change')

    # 配置 .qa-agent.yml
    (tmp_path / '.qa-agent.yml').write_text(
        'project_type: backend\nlanguage: python\nimpact_analysis: local\n'
    )

    return tmp_path


def _extract_json(output: str) -> dict:
    """从 CLI 输出中提取 JSON 对象（顶级，行首 `{` 开始的多行 JSON）"""
    lines = output.splitlines()
    # 找到第一个行首是 `{` 的位置
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith('{'):
            start_idx = i
            break

    if start_idx < 0:
        raise ValueError(f"未找到 JSON 起始：\n{output}")

    # 从 start_idx 开始，找匹配的 `}`（计数法）
    json_lines = []
    depth = 0
    for line in lines[start_idx:]:
        json_lines.append(line)
        depth += line.count('{') - line.count('}')
        if depth == 0:
            break

    return json.loads('\n'.join(json_lines))


def _run_qa(*args, cwd=None):
    """调用 qa CLI（用 python -m）"""
    cmd = ['python', '-m', 'qa_agent.cli.main'] + list(args)
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'

    # 把项目根加到 PYTHONPATH，让 subprocess 能找到 qa_agent 模块
    repo_root = str(Path(__file__).parent.parent.parent)
    existing_path = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f"{repo_root};{existing_path}" if os.name == 'nt' else f"{repo_root}:{existing_path}"

    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
        encoding='utf-8',
        errors='replace'
    )
    return result


class TestSubagentToolchain:
    """端到端：prepare → execute → judge 工具链"""

    def test_prepare_outputs_valid_json(self, test_project):
        """prepare 命令输出有效 JSON 给 subagent 解析"""
        result = _run_qa(
            'prepare', '--mode', 'L0', '--scope', 'sanity', '--impact', 'local',
            cwd=test_project
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"

        data = _extract_json(result.stdout)
        assert 'run_id' in data
        assert data['mode'] == 'L0'
        assert data['scope'] == 'sanity'
        assert data['impact_mode'] == 'local'
        assert (test_project / 'qa' / 'run' / 'selection.md').exists()
        assert (test_project / 'qa' / 'run' / 'last.json').exists()

    def test_resolve_bugfix_with_natural_language(self, test_project):
        """resolve-bugfix 支持自然语言描述（创建新 bug）"""
        result = _run_qa(
            'resolve-bugfix', '--ref', '登录后界面卡死，无法继续操作',
            cwd=test_project
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"

        data = _extract_json(result.stdout)
        assert data['bug_id'].startswith('BUG-')
        assert data['created'] is True
        # 文件确实创建
        assert (test_project / 'qa' / 'bugs' / f"{data['bug_id']}.yml").exists()

    def test_resolve_bugfix_with_bug_id(self, test_project):
        """resolve-bugfix 支持 BUG-XXX 引用（已存在）"""
        # 先创建一个 bug
        result1 = _run_qa(
            'resolve-bugfix', '--ref', '某个真实 bug',
            cwd=test_project
        )
        assert result1.returncode == 0
        bug_id = _extract_json(result1.stdout)['bug_id']

        # 用 bug_id 引用
        result2 = _run_qa(
            'resolve-bugfix', '--ref', bug_id,
            cwd=test_project
        )
        assert result2.returncode == 0

        data = _extract_json(result2.stdout)
        assert data['bug_id'] == bug_id
        assert data['created'] is False

    def test_status_shows_empty_state(self, test_project):
        """status 命令在空项目下显示合理输出"""
        result = _run_qa('status', cwd=test_project)
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert '用例库' in result.stdout or 'Cases' in result.stdout

    def test_judge_l0_outputs_verdict(self, test_project):
        """judge L0 输出有效 verdict JSON"""
        # 先 prepare
        _run_qa(
            'prepare', '--mode', 'L0', '--scope', 'sanity', '--impact', 'local',
            cwd=test_project
        )

        # judge
        result = _run_qa('judge', '--mode', 'L0', cwd=test_project)
        assert result.returncode == 0, f"stderr: {result.stderr}"

        verdict = _extract_json(result.stdout)
        assert 'verdict' in verdict
        assert verdict['verdict'] in ('PASS', 'CONDITIONAL PASS', 'FAIL', 'BLOCKED')


class TestClaudeCodeExtension:
    """验证 Claude Code 扩展文件存在 + 格式合法"""

    def test_slash_command_exists(self):
        """/qa slash command 文件存在"""
        repo_root = Path(__file__).parent.parent.parent
        cmd_file = repo_root / '.claude' / 'commands' / 'qa.md'
        assert cmd_file.exists()

        content = cmd_file.read_text(encoding='utf-8')
        assert content.startswith('---')
        assert 'description:' in content
        assert '/qa' in content

    def test_test_engineer_subagent_exists(self):
        """qa-test-engineer subagent 文件存在"""
        repo_root = Path(__file__).parent.parent.parent
        agent_file = repo_root / '.claude' / 'agents' / 'qa-test-engineer.md'
        assert agent_file.exists()

        content = agent_file.read_text(encoding='utf-8')
        assert 'name: qa-test-engineer' in content
        assert 'tools:' in content

    def test_gatekeeper_subagent_exists(self):
        """qa-gatekeeper subagent 文件存在"""
        repo_root = Path(__file__).parent.parent.parent
        agent_file = repo_root / '.claude' / 'agents' / 'qa-gatekeeper.md'
        assert agent_file.exists()

        content = agent_file.read_text(encoding='utf-8')
        assert 'name: qa-gatekeeper' in content
        assert 'tools:' in content
        # 红线必须存在
        assert '独立' in content or 'independent' in content.lower()
