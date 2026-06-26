"""
Init wizard: 引导式初始化 /qa init（P2-1）
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List

from .config import save_config


class InitWizard:
    """引导式初始化向导"""

    def __init__(self, cwd: Path = Path('.')):
        self.cwd = cwd

    def run(self, project_type: Optional[str] = None) -> Dict[str, Any]:
        """
        执行初始化流程

        Returns:
            {
                'status': 'success' | 'cancelled',
                'config_draft': Dict[str, Any],
                'detected': Dict[str, Any]
            }
        """
        print("\n[Agent] 检测到这是首次使用 QA Agent。正在初始化...\n")

        # 步骤 1: 扫描项目
        detected = self._scan_project()
        self._print_detected(detected)

        # 步骤 2: 生成配置草稿
        config_draft = self._generate_config_draft(detected, project_type)

        # 步骤 3: 创建目录结构
        self._create_directories()

        # 步骤 4: 写配置文件
        config_path = self.cwd / '.qa-agent.yml'
        save_config(config_draft, str(config_path))
        print(f"\n[Agent] 已生成 {config_path}\n")

        # 步骤 5: 检测已有测试
        orphan_tests = self._detect_existing_tests(detected)
        if orphan_tests:
            self._write_orphan_tests(orphan_tests)

        # 步骤 6: 检测需求文档
        requirements = self._discover_requirements()
        if requirements:
            print(f"[Agent] 检测到需求文档：{requirements['primary'] or '（未找到）'}")
        else:
            print("[Agent] ⚠️ 未检测到需求文档（将在首次执行时触发反向梳理）")

        # 步骤 7: 引导下一步
        self._print_next_steps()

        return {
            'status': 'success',
            'config_draft': config_draft,
            'detected': detected
        }

    def _scan_project(self) -> Dict[str, Any]:
        """
        扫描项目文件识别类型和框架
        """
        detected = {
            'project_type': None,
            'language': None,
            'frameworks': {},
            'test_dirs': [],
            'has_git': (self.cwd / '.git').exists()
        }

        # 检测 Flutter
        if (self.cwd / 'pubspec.yaml').exists():
            detected['project_type'] = 'mobile'
            detected['language'] = 'dart'
            detected['frameworks']['unit'] = 'flutter_test'
            detected['frameworks']['integration'] = 'integration_test'

        # 检测 Android 原生（含多模块）
        elif ((self.cwd / 'build.gradle').exists() or
              (self.cwd / 'build.gradle.kts').exists() or
              (self.cwd / 'app' / 'build.gradle').exists() or
              (self.cwd / 'app' / 'build.gradle.kts').exists()):
            detected['project_type'] = 'mobile'
            detected['language'] = 'kotlin' if list(self.cwd.rglob('*.kt'))[:1] else 'java'
            detected['frameworks']['unit'] = 'junit'

        # 检测 iOS
        elif list(self.cwd.glob('*.xcodeproj')) or (self.cwd / 'Package.swift').exists():
            detected['project_type'] = 'mobile'
            detected['language'] = 'swift'
            detected['frameworks']['unit'] = 'xctest'

        # 检测 Web / React Native（共享 package.json）
        elif (self.cwd / 'package.json').exists():
            try:
                import json
                pkg = json.loads((self.cwd / 'package.json').read_text(encoding='utf-8'))
                deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}

                if 'react-native' in deps:
                    detected['project_type'] = 'mobile'
                    detected['language'] = 'typescript' if (self.cwd / 'tsconfig.json').exists() else 'javascript'
                    detected['frameworks']['unit'] = 'jest' if 'jest' in deps else 'unknown'
                    if 'detox' in deps:
                        detected['frameworks']['e2e'] = 'detox'
                else:
                    detected['project_type'] = 'web'
                    detected['language'] = 'typescript' if (self.cwd / 'tsconfig.json').exists() else 'javascript'
                    if 'vitest' in deps:
                        detected['frameworks']['unit'] = 'vitest'
                    if 'jest' in deps:
                        detected['frameworks']['unit'] = 'jest'
                    if 'playwright' in deps or '@playwright/test' in deps:
                        detected['frameworks']['e2e'] = 'playwright'
            except Exception:
                detected['project_type'] = 'web'

        # 检测 Python 项目
        elif (self.cwd / 'pyproject.toml').exists() or (self.cwd / 'setup.py').exists():
            detected['project_type'] = 'backend'
            detected['language'] = 'python'
            detected['frameworks']['unit'] = 'pytest'

        # 检测 Rust 项目
        elif (self.cwd / 'Cargo.toml').exists():
            detected['project_type'] = 'backend'
            detected['language'] = 'rust'
            detected['frameworks']['unit'] = 'cargo'

        # 检测 Go 项目
        elif (self.cwd / 'go.mod').exists():
            detected['project_type'] = 'backend'
            detected['language'] = 'go'
            detected['frameworks']['unit'] = 'go test'

        # 检测测试目录
        for test_dir in ['tests', 'test', '__tests__', 'e2e', 'specs',
                         'app/src/test', 'app/src/androidTest',  # Android
                         'integration_test',                       # Flutter
                         'Tests']:                                 # iOS
            if (self.cwd / test_dir).exists():
                detected['test_dirs'].append(test_dir)

        return detected

    def _print_detected(self, detected: Dict[str, Any]) -> None:
        """
        打印检测结果
        """
        print("[Agent] 扫描项目...")

        if detected['project_type']:
            print(f"  ✓ 检测到项目类型: {detected['project_type']}")
        if detected['language']:
            print(f"  ✓ 检测到语言: {detected['language']}")
        for key, value in detected['frameworks'].items():
            print(f"  ✓ 检测到 {key} 框架: {value}")
        if detected['test_dirs']:
            print(f"  ✓ 检测到测试目录: {', '.join(detected['test_dirs'])}")
        if not detected['has_git']:
            print("  ⚠️ 未检测到 git（建议初始化 git 仓库以使用影响面分析）")

    def _generate_config_draft(
        self,
        detected: Dict[str, Any],
        project_type_override: Optional[str]
    ) -> Dict[str, Any]:
        """
        生成配置草稿
        """
        config = {
            'project_type': project_type_override or detected['project_type'] or 'generic',
            'language': detected['language'] or 'unknown',
            'frameworks': detected['frameworks'],
            'impact_analysis': 'codegraph' if detected['has_git'] else 'local'
        }

        # CodeGraph MCP 工具前缀（列表，按优先级尝试）
        # 用户首次接入时会作为草稿出现在 .qa-agent.yml，可手动调整顺序
        config['codegraph'] = {
            'mcp_tool_prefixes': ['mcp__codegraph'],
        }

        # Generic 项目需要手动配置测试命令
        if config['project_type'] == 'generic':
            config['test_command'] = '# TODO: 填写测试命令（如 cargo test / make test）'

        return config

    def _create_directories(self) -> None:
        """
        创建 qa/ 目录结构
        """
        dirs = [
            'qa/cases',
            'qa/bugs',
            'qa/run',
            'qa/feedback',
            'qa/signoff'
        ]
        for d in dirs:
            (self.cwd / d).mkdir(parents=True, exist_ok=True)

        print("[Agent] 已创建 qa/ 目录结构")

    def _detect_existing_tests(self, detected: Dict[str, Any]) -> List[str]:
        """
        检测已有测试文件
        """
        test_files = []
        for test_dir in detected['test_dirs']:
            test_path = self.cwd / test_dir
            if test_path.exists():
                # 简化：只列目录，不递归
                test_files.extend([str(f.relative_to(self.cwd)) for f in test_path.rglob('*.spec.*')])
                test_files.extend([str(f.relative_to(self.cwd)) for f in test_path.rglob('test_*.py')])

        return test_files[:20]  # 最多列 20 个

    def _write_orphan_tests(self, test_files: List[str]) -> None:
        """
        记录现有测试为 orphan
        """
        content = f"""# Orphan Tests

以下是检测到的现有测试文件（共 {len(test_files)} 个）。

你可以选择：
a) 逐个映射为用例（在 qa/cases/ 下生成对应 YAML，automation.file 指向现有测试）
b) 直接基于需求生成新用例库
c) 稍后处理

## 现有测试

{''.join(f'- {f}' + chr(10) for f in test_files)}
"""
        (self.cwd / 'qa' / 'orphan_tests.md').write_text(content, encoding='utf-8')
        print(f"[Agent] 已登记 {len(test_files)} 个现有测试为 orphan（qa/orphan_tests.md）")

    def _discover_requirements(self) -> Optional[Dict[str, Any]]:
        """
        需求文档自动发现（使用完整发现算法）
        """
        from .requirement_discovery import discover_requirements

        result = discover_requirements({}, cwd=self.cwd)

        if result.get('source') == 'reverse_engineered':
            return None

        # 返回主文档
        if result.get('primary'):
            return {
                'primary': result['primary'],
                'design': result.get('design'),
                'specs_count': len(result.get('specs', [])),
                'all_docs_count': len(result.get('all_docs', []))
            }
        elif result.get('all_docs'):
            return {
                'primary': result['all_docs'][0],
                'all_docs_count': len(result['all_docs'])
            }

        return None

    def _print_next_steps(self) -> None:
        """
        打印下一步建议
        """
        print("\n[Agent] 下一步建议：")
        print("  /qa feature 用户登录    # 生成第一个 feature 的测试")
        print("  /qa status              # 查看当前测试覆盖状态")
        print("\n是否立即运行一次完整项目扫描（L2）以建立用例库？(yes / no / 稍后)：")
        # Phase 1.4 CLI 实现真实交互
