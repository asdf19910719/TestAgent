#!/usr/bin/env python3
"""
AI智能分析结果更新工具
用于将AI的分析结果追加到HTML测试报告中
"""

import json
import sys
import os

# 添加脚本目录到路径
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from report_template_fixed import generate_fixed_report


def update_report_with_analysis(test_results_json_path: str, analysis_result: dict):
    """
    使用AI分析结果更新HTML报告

    Args:
        test_results_json_path: 测试结果JSON文件路径
        analysis_result: AI分析结果字典，格式：
            {
                "summary": "分析摘要",
                "failure_analysis": [
                    {
                        "category": "失败分类",
                        "test_cases": ["用例1", "用例2"],
                        "root_cause": "根本原因",
                        "evidence": "证据",
                        "suggestions": ["建议1", "建议2"]
                    }
                ],
                "endpoints_info": {
                    "total_endpoints": 5,
                    "tested_endpoints": 5,
                    "coverage": 100.0
                }
            }
    """
    # 读取测试结果
    with open(test_results_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 兼容两种JSON结构：test_results 或 test_cases
    if 'test_results' in data:
        test_results = data
    elif 'test_cases' in data:
        test_results = {'test_cases': data['test_cases']}
    else:
        raise ValueError("JSON文件中未找到 test_results 或 test_cases 字段")

    # 获取报告路径（如果没有则推断）
    if 'report_path' in data:
        report_path = data['report_path']
    else:
        # 从JSON文件名推断报告路径
        # test_results_20260304_150628.json -> report_20260304_150628.html
        json_dir = os.path.dirname(test_results_json_path)
        json_filename = os.path.basename(test_results_json_path)
        timestamp = json_filename.replace('test_results_', '').replace('.json', '')
        report_path = os.path.join(json_dir, f'report_{timestamp}.html')


    # 合并接口覆盖度信息
    if 'endpoints_info' not in analysis_result:
        analysis_result['endpoints_info'] = data.get('endpoints_info', {})

    # 标记分析已完成
    analysis_result['status'] = 'completed'

    # 重新生成包含分析结果的HTML报告
    generate_fixed_report(test_results, report_path, analysis_result)

    print(f"✅ HTML报告已更新: {report_path}")
    print(f"   - 接口覆盖度: {analysis_result['endpoints_info'].get('coverage', 0)}%")
    print(f"   - 智能分析: 已完成")

    return report_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python update_report_with_ai_analysis.py <test_results_json_path>")
        print("示例: python update_report_with_ai_analysis.py test_results_20260304_150628.json")
        sys.exit(1)

    test_results_path = sys.argv[1]

    # 示例分析结果（实际使用时由AI生成）
    example_analysis = {
        "summary": "测试通过率 79.8%，主要失败原因为业务逻辑校验",
        "failure_analysis": [
            {
                "category": "业务逻辑校验",
                "test_cases": ["test_add_normal"],
                "root_cause": "项目下已存在该配置类型",
                "evidence": "响应: {\"code\":\"1\",\"message\":\"项目下已存在该配置类型\"}",
                "suggestions": [
                    "使用唯一的配置类型值",
                    "在测试前清理已存在的配置"
                ]
            }
        ]
    }

    update_report_with_analysis(test_results_path, example_analysis)
