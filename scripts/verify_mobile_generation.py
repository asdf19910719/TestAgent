#!/usr/bin/env python3
"""
实战验证:用改进后的 Mobile Adapter 为 ClawBoxClient 生成测试代码
"""
import sys
from pathlib import Path

# 确保能导入 qa_agent
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import yaml
from qa_agent.core.models import TestCase, TestLevel, TestPurpose, Priority
from qa_agent.adapters.mobile.adapter import MobileAdapter


def main():
    # ClawBoxClient 项目路径
    claw_project = Path('D:/AndroidProject/ClawBoxClient')

    # 读取 TC-CONTACT-001
    case_yml = claw_project / 'qa/cases/contact/TC-CONTACT-001.yml'
    print(f"读取用例: {case_yml}")

    data = yaml.safe_load(case_yml.read_text(encoding='utf-8'))

    case = TestCase(
        id=data['id'],
        title=data['title'],
        feature_id=data.get('feature_id', 'F-CONTACT-SYNC'),
        level=TestLevel(data['level']),
        purpose=TestPurpose(data['purpose']),
        priority=Priority(data['priority']),
        preconditions=data.get('preconditions', []),
        steps=data.get('steps', []),
        expected=data.get('expected', []),
        assertions=data.get('assertions', []),
        state='active'
    )

    print(f"用例 ID: {case.id}")
    print(f"标题: {case.title}")
    print(f"层级: {case.level.value}")
    print(f"断言数: {len(case.assertions)}")
    print()

    # 初始化 Adapter
    adapter = MobileAdapter(claw_project)

    print("开始生成测试代码...")
    result_path = adapter.generate(case)

    print(f"\n✅ 生成完成: {result_path}")
    print()

    # 验证生成的文件
    result_file = claw_project / result_path
    if result_file.exists():
        content = result_file.read_text(encoding='utf-8')
        lines = content.split('\n')

        print(f"文件大小: {len(content)} 字符, {len(lines)} 行")
        print()
        print("=" * 80)
        print("生成的测试代码(前 80 行):")
        print("=" * 80)

        for i, line in enumerate(lines[:80], 1):
            print(f"{i:3d} | {line}")

        if len(lines) > 80:
            print(f"\n... 还有 {len(lines) - 80} 行 ...")

        # 统计关键信息
        print()
        print("=" * 80)
        print("代码分析:")
        print("=" * 80)
        print(f"- 包含 'assertEquals': {content.count('assertEquals')} 处")
        print(f"- 包含 'ContentResolver': {content.count('ContentResolver')} 处")
        print(f"- 包含 'cursor.use': {content.count('cursor.use')} 处")
        print(f"- 包含 'assertLogContains': {content.count('assertLogContains')} 处")
        print(f"- 包含 'TODO': {content.count('TODO')} 处")

    else:
        print(f"❌ 错误: 文件未生成到预期位置")


if __name__ == '__main__':
    main()
