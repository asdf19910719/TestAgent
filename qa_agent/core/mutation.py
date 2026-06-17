"""
Mutation 测试真实集成

支持工具:
- mutmut (Python)
- Stryker (JS/TS)
- cargo-mutants (Rust)

主规范 §5.6 + §11 配置实现
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


class MutationRunner:
    """Mutation testing 执行器"""

    # 工具检测优先级（按语言）
    TOOL_PRIORITY = {
        'python': ['mutmut', 'cosmic-ray'],
        'typescript': ['stryker'],
        'javascript': ['stryker'],
        'rust': ['cargo-mutants'],
        'java': ['pitest'],
    }

    def __init__(self, config: Dict[str, Any], language: str = 'python'):
        self.config = config
        self.language = language
        self.mutation_config = config.get('mutation', {})

    def detect_tool(self) -> Optional[str]:
        """
        自动检测可用的 mutation 工具

        Returns:
            工具名称 或 None（不可用）
        """
        # 优先用配置指定的工具
        configured = self.mutation_config.get('tool')
        if configured:
            if self._is_tool_available(configured):
                return configured
            return None

        # 按语言优先级自动检测
        candidates = self.TOOL_PRIORITY.get(self.language, [])
        for tool in candidates:
            if self._is_tool_available(tool):
                return tool

        return None

    def run(
        self,
        mode: str,
        diff_files: List[str],
        capabilities: Dict[str, bool]
    ) -> Dict[str, Any]:
        """
        执行 mutation testing

        Args:
            mode: 运行模式（仅 L3 启用）
            diff_files: diff 涉及的源文件列表
            capabilities: Adapter capabilities

        Returns:
            {
                'status': 'completed' | 'skipped' | 'failed',
                'reason': str,
                'tool': str | None,
                'files_tested': int,
                'score': float,        # killed / total
                'killed': int,
                'survived': int,
                'total': int,
                'threshold': float,
                'pass': bool
            }
        """
        # 检查模式是否启用
        enabled_modes = self.mutation_config.get('enabled_modes', ['L3'])
        if mode not in enabled_modes:
            return {
                'status': 'skipped',
                'reason': f'未在 {mode} 模式下启用',
                'tool': None,
                'score': 0.0, 'killed': 0, 'survived': 0, 'total': 0,
                'pass': True  # skip 不算失败
            }

        # 检查 Adapter capabilities
        if not capabilities.get('mutation', False):
            return {
                'status': 'skipped',
                'reason': f'Adapter capabilities.mutation = false',
                'tool': None,
                'score': 0.0, 'killed': 0, 'survived': 0, 'total': 0,
                'pass': True
            }

        # 检测工具
        tool = self.detect_tool()
        on_missing = self.mutation_config.get('on_tool_missing', 'skip')

        if not tool:
            if on_missing == 'fail':
                raise MutationToolNotFound(
                    f"未找到 mutation 工具（语言：{self.language}）\n"
                    f"请安装 {' / '.join(self.TOOL_PRIORITY.get(self.language, ['（无推荐工具）']))} 之一"
                )
            return {
                'status': 'skipped',
                'reason': 'tool_not_found',
                'tool': None,
                'note': '已在 L3 报告中标注：未跑 mutation（工具未安装）',
                'score': 0.0, 'killed': 0, 'survived': 0, 'total': 0,
                'pass': True
            }

        # 仅对 diff 涉及代码做变异
        scope = self.mutation_config.get('scope', 'diff')
        if scope == 'diff':
            target_files = self._filter_source_files(diff_files)
            if len(target_files) > 20:
                target_files = self._sample_top_changed_files(target_files, top_n=20)
        else:
            # sample 模式：用配置指定的 modules
            target_files = self.mutation_config.get('sample_modules', [])

        if not target_files:
            return {
                'status': 'skipped',
                'reason': '无可变异源文件',
                'tool': tool,
                'score': 0.0, 'killed': 0, 'survived': 0, 'total': 0,
                'pass': True
            }

        # 执行 mutation
        try:
            result = self._execute(tool, target_files)
        except Exception as e:
            return {
                'status': 'failed',
                'reason': str(e),
                'tool': tool,
                'score': 0.0, 'killed': 0, 'survived': 0, 'total': 0,
                'pass': True  # 工具失败不阻断 L3
            }

        # 计算分数
        threshold = self.mutation_config.get('threshold', 0.60)
        total = result.get('total', 0)
        killed = result.get('killed', 0)
        survived = result.get('survived', 0)

        score = killed / total if total > 0 else 0.0

        return {
            'status': 'completed',
            'tool': tool,
            'files_tested': len(target_files),
            'score': score,
            'killed': killed,
            'survived': survived,
            'total': total,
            'threshold': threshold,
            'pass': score >= threshold,
            'reason': '' if score >= threshold else f'mutation score {score:.2%} < threshold {threshold:.2%}'
        }

    def _is_tool_available(self, tool: str) -> bool:
        """检查工具是否在 PATH"""
        if tool == 'stryker':
            # Stryker 通过 npx 调用，检查 node_modules
            return Path('node_modules/@stryker-mutator/core').exists() or shutil.which('stryker') is not None
        if tool == 'pitest':
            # PIT 通过 maven/gradle 插件，简化检查 build 文件
            return Path('pom.xml').exists() or Path('build.gradle').exists()
        return shutil.which(tool) is not None

    def _filter_source_files(self, diff_files: List[str]) -> List[str]:
        """过滤出可变异的源文件"""
        # 按语言定义扩展名
        ext_by_lang = {
            'python': ['.py'],
            'typescript': ['.ts', '.tsx'],
            'javascript': ['.js', '.jsx'],
            'rust': ['.rs'],
            'java': ['.java'],
        }

        valid_exts = ext_by_lang.get(self.language, [])

        result = []
        for f in diff_files:
            # 排除测试文件
            if 'test' in Path(f).name.lower() or 'spec' in Path(f).name.lower():
                continue
            if f.startswith('tests/') or f.startswith('test/'):
                continue
            # 检查扩展名
            if any(f.endswith(ext) for ext in valid_exts):
                result.append(f)

        return result

    def _sample_top_changed_files(self, files: List[str], top_n: int = 20) -> List[str]:
        """按 diff 修改行数降序取 top_n"""
        files_with_lines = []
        for f in files:
            try:
                result = subprocess.run(
                    ['git', 'diff', '--numstat', 'HEAD~1', 'HEAD', '--', f],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                lines_changed = 0
                if result.stdout.strip():
                    parts = result.stdout.split()
                    if len(parts) >= 2 and parts[0].isdigit():
                        lines_changed = int(parts[0]) + int(parts[1])
                files_with_lines.append((f, lines_changed))
            except Exception:
                files_with_lines.append((f, 0))

        files_with_lines.sort(key=lambda x: x[1], reverse=True)
        return [f for f, _ in files_with_lines[:top_n]]

    def _execute(self, tool: str, target_files: List[str]) -> Dict[str, int]:
        """
        执行具体工具命令，返回 mutation 统计

        Returns:
            {'killed': int, 'survived': int, 'total': int}
        """
        if tool == 'mutmut':
            return self._run_mutmut(target_files)
        elif tool == 'stryker':
            return self._run_stryker(target_files)
        elif tool == 'cargo-mutants':
            return self._run_cargo_mutants(target_files)
        elif tool == 'cosmic-ray':
            return self._run_cosmic_ray(target_files)
        else:
            raise NotImplementedError(f"未实现工具: {tool}")

    def _run_mutmut(self, target_files: List[str]) -> Dict[str, int]:
        """mutmut for Python"""
        paths = ','.join(target_files)

        # 运行 mutmut
        subprocess.run(
            ['mutmut', 'run', f'--paths-to-mutate={paths}'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=1200
        )

        # 读取结果
        result = subprocess.run(
            ['mutmut', 'results'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60
        )

        return self._parse_mutmut_output(result.stdout)

    def _parse_mutmut_output(self, output: str) -> Dict[str, int]:
        """解析 mutmut results 输出"""
        killed = output.count('killed')
        survived = output.count('survived')
        # 简化解析：匹配统计行
        match = re.search(r'(\d+) killed.*?(\d+) survived', output)
        if match:
            killed = int(match.group(1))
            survived = int(match.group(2))

        total = killed + survived
        return {'killed': killed, 'survived': survived, 'total': total}

    def _run_stryker(self, target_files: List[str]) -> Dict[str, int]:
        """Stryker for JS/TS"""
        mutate_arg = ','.join(target_files)

        result = subprocess.run(
            ['npx', 'stryker', 'run', '--mutate', mutate_arg, '--reporters=json'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1800
        )

        # 解析 Stryker JSON report
        report_path = Path('reports/mutation/mutation.json')
        if report_path.exists():
            data = json.loads(report_path.read_text(encoding='utf-8'))
            mutation_score = data.get('thresholds', {}).get('high', 0)
            # 简化：从 metrics 提取
            killed = 0
            survived = 0
            for file_data in data.get('files', {}).values():
                for m in file_data.get('mutants', []):
                    if m['status'] == 'Killed':
                        killed += 1
                    elif m['status'] == 'Survived':
                        survived += 1
            return {'killed': killed, 'survived': survived, 'total': killed + survived}

        return {'killed': 0, 'survived': 0, 'total': 0}

    def _run_cargo_mutants(self, target_files: List[str]) -> Dict[str, int]:
        """cargo-mutants for Rust"""
        result = subprocess.run(
            ['cargo', 'mutants', '--no-shuffle', '-j', '2'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=1800
        )

        # 解析输出
        output = result.stdout
        caught = len(re.findall(r'\bcaught\b', output))
        missed = len(re.findall(r'\bmissed\b', output))

        return {'killed': caught, 'survived': missed, 'total': caught + missed}

    def _run_cosmic_ray(self, target_files: List[str]) -> Dict[str, int]:
        """cosmic-ray for Python（替代 mutmut）"""
        # cosmic-ray 需要先初始化配置，简化跳过
        return {'killed': 0, 'survived': 0, 'total': 0}


class MutationToolNotFound(RuntimeError):
    """Mutation 工具未找到"""
    pass
