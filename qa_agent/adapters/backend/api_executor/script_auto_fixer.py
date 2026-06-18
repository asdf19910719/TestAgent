"""
脚本自动修复模块（Script Auto-Fixer）

功能：
1. 检测测试脚本执行失败的错误类型
2. 根据错误类型自动生成修复补丁
3. 应用补丁并重新执行（最多重试 N 次）

支持修复的错误类型：
- SyntaxError: 语法错误（缩进、括号、冒号）
- ImportError/ModuleNotFoundError: 导入错误
- NameError: 变量未定义
- AttributeError: 属性不存在
- TypeError: 参数类型/数量错误
- AssertionError: 断言写法错误（期望值不对）

设计原则：
- 只修复测试脚本问题，不修复被测代码的 bug
- 每个错误最多重试 1 次
- 修复前备份原文件
- 记录修复历史（用于经验积累）
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


# 错误分类体系
ERROR_CATEGORIES = {
    'syntax_error': {
        'patterns': [
            r'SyntaxError:\s*(.+)',
            r'IndentationError:\s*(.+)',
        ],
        'fixable': True,
        'description': '语法错误',
    },
    'import_error': {
        'patterns': [
            r'ImportError:\s*(.+)',
            r'ModuleNotFoundError:\s*(.+)',
        ],
        'fixable': True,
        'description': '导入错误',
    },
    'name_error': {
        'patterns': [
            r"NameError:\s*name '(\w+)' is not defined",
        ],
        'fixable': True,
        'description': '变量未定义',
    },
    'attribute_error': {
        'patterns': [
            r"AttributeError:\s*(.+)",
        ],
        'fixable': True,
        'description': '属性不存在',
    },
    'type_error': {
        'patterns': [
            r'TypeError:\s*(.+)',
        ],
        'fixable': True,
        'description': '类型错误',
    },
    'assertion_error': {
        'patterns': [
            r'AssertionError:\s*(.*)',
            r'assert .+ == .+',
        ],
        'fixable': False,
        'description': '断言失败（可能是被测代码 bug，不自动修复）',
    },
    'connection_error': {
        'patterns': [
            r'ConnectionError:\s*(.+)',
            r'ConnectionRefusedError:\s*(.+)',
            r'requests\.exceptions\.ConnectionError',
        ],
        'fixable': False,
        'description': '连接错误（环境问题，不自动修复）',
    },
    'timeout_error': {
        'patterns': [
            r'TimeoutError:\s*(.+)',
            r'ReadTimeout:\s*(.+)',
        ],
        'fixable': False,
        'description': '超时错误（环境问题，不自动修复）',
    },
}


# 常见修复规则（基于模式匹配）
FIX_RULES = [
    {
        'name': 'missing_import_requests',
        'detect': r"NameError: name 'requests' is not defined",
        'fix_type': 'prepend_import',
        'fix_value': 'import requests',
    },
    {
        'name': 'missing_import_json',
        'detect': r"NameError: name 'json' is not defined",
        'fix_type': 'prepend_import',
        'fix_value': 'import json',
    },
    {
        'name': 'missing_import_pytest',
        'detect': r"NameError: name 'pytest' is not defined",
        'fix_type': 'prepend_import',
        'fix_value': 'import pytest',
    },
    {
        'name': 'missing_import_os',
        'detect': r"NameError: name 'os' is not defined",
        'fix_type': 'prepend_import',
        'fix_value': 'import os',
    },
    {
        'name': 'response_json_method',
        'detect': r"TypeError: 'dict' object is not callable",
        'fix_type': 'replace_in_file',
        'detect_code': r'\.json\(\)',
        'fix_value': '.json()',
        'description': 'response.json() 已经是 dict，不需要再调用',
    },
    {
        'name': 'assert_status_code',
        'detect': r"AttributeError: 'Response' object has no attribute 'status'",
        'fix_type': 'replace_in_file',
        'detect_code': r'response\.status\b(?!_code)',
        'fix_value': 'response.status_code',
    },
    {
        'name': 'missing_base_url',
        'detect': r"MissingSchema: Invalid URL.*No scheme supplied",
        'fix_type': 'add_base_url',
        'description': 'URL 缺少协议前缀',
    },
]


class ScriptAutoFixer:
    """测试脚本自动修复器"""

    def __init__(self, workspace: Path, config: Dict[str, Any] = None):
        self.workspace = workspace
        self.config = config or {}

        # 从 repair_loop 配置读取重试次数
        from qa_agent.core.repair_loop import get_repair_loop_config
        try:
            repair_cfg = get_repair_loop_config(self.config)
            self.max_retries = repair_cfg.max_retries_per_case
            self.auto_fix_enabled = repair_cfg.script_auto_fix_enabled
            print(f"[AutoFixer] repair_loop.mode={repair_cfg.mode}, "
                  f"max_retries={self.max_retries}, "
                  f"auto_fix_enabled={self.auto_fix_enabled}")
        except Exception:
            # 降级：从 backend 配置读取（向后兼容）
            self.max_retries = self.config.get('backend', {}).get('max_retry_on_script_error', 1)
            self.auto_fix_enabled = self.config.get('backend', {}).get('auto_fix_script_errors', True)

        self.fix_history: List[Dict[str, Any]] = []
        self.history_file = workspace / 'qa' / 'backend' / 'fix_history.jsonl'

    def analyze_failure(self, stderr: str, stdout: str) -> Dict[str, Any]:
        """
        分析测试失败原因

        Returns:
            {
                'category': str,        # 错误分类
                'fixable': bool,        # 是否可自动修复
                'error_message': str,   # 错误信息
                'file_path': str,       # 出错文件
                'line_number': int,     # 出错行号
                'suggested_fix': str,   # 建议修复方式
            }
        """
        combined_output = stderr + '\n' + stdout

        # 提取文件路径和行号
        file_path, line_number = self._extract_location(combined_output)

        # 分类错误
        category = 'unknown'
        error_message = ''
        fixable = False

        for cat_name, cat_info in ERROR_CATEGORIES.items():
            for pattern in cat_info['patterns']:
                match = re.search(pattern, combined_output)
                if match:
                    category = cat_name
                    error_message = match.group(0)
                    fixable = cat_info['fixable']
                    break
            if category != 'unknown':
                break

        # 查找匹配的修复规则
        suggested_fix = None
        if fixable:
            suggested_fix = self._find_fix_rule(combined_output)

        return {
            'category': category,
            'fixable': fixable,
            'error_message': error_message,
            'file_path': file_path,
            'line_number': line_number,
            'suggested_fix': suggested_fix,
        }

    def attempt_fix(self, test_file: str, analysis: Dict[str, Any]) -> bool:
        """
        尝试修复测试脚本

        Returns:
            True = 修复成功（文件已修改），False = 无法修复
        """
        if not analysis.get('fixable') or not analysis.get('suggested_fix'):
            return False

        file_path = Path(analysis.get('file_path') or test_file)
        if not file_path.exists():
            return False

        fix_rule = analysis['suggested_fix']
        fix_type = fix_rule.get('fix_type')

        # 备份原文件
        backup_path = file_path.with_suffix('.py.bak')
        shutil.copy2(file_path, backup_path)

        try:
            content = file_path.read_text(encoding='utf-8')
            fixed = False

            if fix_type == 'prepend_import':
                import_line = fix_rule['fix_value']
                if import_line not in content:
                    content = import_line + '\n' + content
                    fixed = True

            elif fix_type == 'replace_in_file':
                detect_code = fix_rule.get('detect_code', '')
                fix_value = fix_rule.get('fix_value', '')
                if detect_code and re.search(detect_code, content):
                    content = re.sub(detect_code, fix_value, content)
                    fixed = True

            elif fix_type == 'add_base_url':
                # 检查是否有裸路径 URL
                bare_url_pattern = r"requests\.\w+\(['\"](?!/)"
                if re.search(bare_url_pattern, content):
                    # 在文件开头添加 BASE_URL
                    base_url_line = "import os\nBASE_URL = os.environ.get('BASE_URL', 'http://localhost:3000')\n"
                    if 'BASE_URL' not in content:
                        content = base_url_line + content
                        # 替换裸路径
                        content = re.sub(
                            r"requests\.(\w+)\('(/[^']+)'",
                            r"requests.\1(BASE_URL + '\2'",
                            content
                        )
                        fixed = True

            if fixed:
                file_path.write_text(content, encoding='utf-8')
                self._record_fix(file_path, fix_rule, analysis)
                print(f"[AutoFixer] Applied fix: {fix_rule.get('name', 'unknown')} on {file_path}")
                return True
            else:
                # 没有实际修改，恢复备份
                backup_path.unlink(missing_ok=True)
                return False

        except Exception as e:
            # 修复失败，恢复备份
            if backup_path.exists():
                shutil.copy2(backup_path, file_path)
            print(f"[AutoFixer] Fix failed: {e}")
            return False

    def run_with_auto_fix(self, test_dir: str, report_dir: str) -> Dict[str, Any]:
        """
        执行测试并在脚本错误时自动修复重试

        Returns:
            {
                'exit_code': int,
                'attempts': int,
                'fixes_applied': List[str],
                'final_result_file': str,
            }
        """
        # 如果未启用自动修复，直接执行一次
        if not self.auto_fix_enabled:
            print("[AutoFixer] auto_fix_enabled=False, 执行测试不重试")
            cmd = [
                sys.executable,
                '-m', 'qa_agent.adapters.backend.api_executor.enhanced_execute_with_auth',
                '--test-dir', test_dir,
                '--report-dir', report_dir,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(self.workspace), timeout=600
            )
            # 查找结果文件
            report_path = Path(report_dir)
            json_files = sorted(report_path.glob('test_results_*.json'), reverse=True)
            return {
                'exit_code': result.returncode,
                'attempts': 1,
                'fixes_applied': [],
                'final_result_file': str(json_files[0]) if json_files else '',
                'stdout': result.stdout,
                'stderr': result.stderr,
            }

        # 启用自动修复：循环重试
        attempts = 0
        fixes_applied = []

        while attempts <= self.max_retries:
            attempts += 1
            print(f"[AutoFixer] Attempt {attempts}/{self.max_retries + 1}")

            # 执行测试
            cmd = [
                sys.executable,
                '-m', 'qa_agent.adapters.backend.api_executor.enhanced_execute_with_auth',
                '--test-dir', test_dir,
                '--report-dir', report_dir,
            ]

            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=str(self.workspace), timeout=600
            )

            # 成功
            if result.returncode == 0:
                break

            # 失败：分析原因
            analysis = self.analyze_failure(result.stderr, result.stdout)
            print(f"[AutoFixer] Failure category: {analysis['category']} "
                  f"(fixable={analysis['fixable']})")

            # 不可修复或已达最大重试次数
            if not analysis['fixable'] or attempts > self.max_retries:
                break

            # 尝试修复
            fixed = self.attempt_fix(test_dir, analysis)
            if fixed:
                fix_name = analysis['suggested_fix'].get('name', 'unknown')
                fixes_applied.append(fix_name)
                print(f"[AutoFixer] Fix applied: {fix_name}, retrying...")
            else:
                print(f"[AutoFixer] Cannot auto-fix, stopping.")
                break

        # 查找最新结果文件
        report_path = Path(report_dir)
        json_files = sorted(report_path.glob('test_results_*.json'), reverse=True)
        final_result_file = str(json_files[0]) if json_files else ''

        return {
            'exit_code': result.returncode,
            'attempts': attempts,
            'fixes_applied': fixes_applied,
            'final_result_file': final_result_file,
            'stdout': result.stdout,
            'stderr': result.stderr,
        }

    def _extract_location(self, output: str) -> Tuple[str, int]:
        """从错误输出中提取文件路径和行号"""
        # Python traceback 格式: File "path/to/file.py", line 42
        match = re.search(r'File "([^"]+)", line (\d+)', output)
        if match:
            return match.group(1), int(match.group(2))

        # pytest 格式: path/to/file.py:42: SyntaxError
        match = re.search(r'([^\s:]+\.py):(\d+):', output)
        if match:
            return match.group(1), int(match.group(2))

        return '', 0

    def _find_fix_rule(self, output: str) -> Optional[Dict[str, Any]]:
        """查找匹配的修复规则"""
        for rule in FIX_RULES:
            if re.search(rule['detect'], output):
                return rule
        return None

    def _record_fix(self, file_path: Path, fix_rule: Dict, analysis: Dict):
        """记录修复历史"""
        record = {
            'timestamp': datetime.now().isoformat(),
            'file': str(file_path),
            'category': analysis['category'],
            'error_message': analysis['error_message'],
            'fix_name': fix_rule.get('name', 'unknown'),
            'fix_type': fix_rule.get('fix_type', 'unknown'),
        }
        self.fix_history.append(record)

        # 追加到历史文件
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')


def main():
    """CLI 入口"""
    import argparse

    parser = argparse.ArgumentParser(description="测试脚本自动修复执行器")
    parser.add_argument("--test-dir", required=True, help="测试脚本目录或文件")
    parser.add_argument("--report-dir", default=None, help="报告输出目录")
    parser.add_argument("--max-retries", type=int, default=1, help="最大重试次数")
    parser.add_argument("--workspace", default='.', help="工作目录")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    report_dir = args.report_dir or str(workspace / 'qa' / 'backend' / 'reports')

    fixer = ScriptAutoFixer(
        workspace=workspace,
        config={'max_retry_on_script_error': args.max_retries}
    )

    result = fixer.run_with_auto_fix(args.test_dir, report_dir)

    print(f"\n{'=' * 60}")
    print(f"[AutoFixer] Result:")
    print(f"  Exit code: {result['exit_code']}")
    print(f"  Attempts: {result['attempts']}")
    print(f"  Fixes applied: {result['fixes_applied'] or 'none'}")
    print(f"  Result file: {result['final_result_file']}")
    print(f"{'=' * 60}")

    sys.exit(result['exit_code'])


if __name__ == '__main__':
    main()
