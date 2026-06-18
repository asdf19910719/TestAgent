#!/usr/bin/env python3
"""
元素提取与选择器策略生成脚本
基于 explore_page.py 的输出，生成 selector-strategy.json。
"""
import argparse
import json
from pathlib import Path


def analyze_selector_quality(elements):
    """分析元素选择器质量，推荐最佳策略"""
    strategy_counts = {}
    for elem in elements:
        for sel in elem.get('selectors', []):
            strategy = sel['strategy']
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

    total = len(elements) if elements else 1
    # 按覆盖率排序
    coverage = {s: c / total for s, c in strategy_counts.items()}
    return coverage


def build_page_strategy(elements, page_name=''):
    """为页面构建选择器策略"""
    coverage = analyze_selector_quality(elements)

    # 选择覆盖率最高且优先级最高的策略
    preferred = 'css'  # 默认
    best_score = 0
    priority_weight = {
        'xpath': 8, 'data-testid': 7, 'role': 6, 'label': 5,
        'placeholder': 4, 'text': 3, 'css': 2,
    }
    for strategy, rate in coverage.items():
        weight = priority_weight.get(strategy, 0)
        score = rate * weight
        if score > best_score:
            best_score = score
            preferred = strategy

    reasons = {
        'xpath': '页面使用 smart XPath 定位，经过唯一性验证，稳定性最佳',
        'data-testid': '页面使用了 data-testid 属性，稳定性最佳',
        'role': '页面 ARIA 角色标注完善，语义化选择器可用',
        'label': '表单元素 label 关联完善',
        'placeholder': '输入框 placeholder 覆盖率高',
        'text': '页面文本标识清晰',
        'css': '使用 CSS 类名选择器',
    }

    return {
        'preferred': preferred,
        'reason': reasons.get(preferred, ''),
        'coverage': coverage,
    }


def main():
    parser = argparse.ArgumentParser(description='生成选择器策略')
    parser.add_argument('--page-elements', required=True, help='page-elements.json 路径')
    parser.add_argument('--output', required=True, help='输出 selector-strategy.json 路径')
    args = parser.parse_args()

    elements_path = Path(args.page_elements)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not elements_path.exists():
        print(f'错误: 文件不存在: {elements_path}')
        return

    data = json.loads(elements_path.read_text(encoding='utf-8'))
    elements = data.get('elements', [])

    page_name = data.get('title', 'default')
    page_strategy = build_page_strategy(elements, page_name)

    result = {
        'default_strategy': 'robust',
        'fallback_chain': [
            'xpath', 'data-testid', 'role', 'label', 'placeholder', 'text', 'css'
        ],
        'page_strategies': {
            page_name: page_strategy,
        },
    }

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'选择器策略已生成: {output_path}')
    print(str(output_path))


if __name__ == '__main__':
    main()
