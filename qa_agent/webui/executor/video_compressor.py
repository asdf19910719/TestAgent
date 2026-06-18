#!/usr/bin/env python3
"""
WebUI 测试视频压缩工具
对 Playwright 录制的 WebM 视频进行压缩，支持不同质量等级。
优先使用 ffmpeg 进行高效压缩（CRF 模式），如果 ffmpeg 不可用则执行简单复制。

支持批量处理指定目录下的所有 .webm 文件，并输出压缩统计摘要。

使用方式:
  python video_compressor.py --input-dir ./videos --output-dir ./compressed --quality medium
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── 质量等级对应的 CRF 值 ────────────────────────────────────
# CRF (Constant Rate Factor): 值越小质量越高、文件越大
QUALITY_CRF_MAP = {
    "low": 35,      # 低质量，高压缩比，适合归档或节省空间
    "medium": 28,   # 中等质量，平衡压缩比和画质（默认）
    "high": 23,     # 高质量，低压缩比，保留更多细节
}

# 质量等级中文描述
QUALITY_LABELS = {
    "low": "低质量 (CRF=35)",
    "medium": "中等质量 (CRF=28)",
    "high": "高质量 (CRF=23)",
}


def check_ffmpeg():
    """
    检测系统是否安装了 ffmpeg。

    Returns:
        str or None: ffmpeg 可执行文件路径，未安装返回 None
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        try:
            result = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True, encoding='utf-8', errors='replace',
                timeout=5,
            )
            if result.returncode == 0:
                # 提取版本信息的第一行
                version_line = result.stdout.split("\n")[0]
                print(f"  检测到 ffmpeg: {version_line}")
                return ffmpeg_path
        except Exception:
            pass

    return None


def get_file_size_bytes(file_path):
    """
    获取文件大小（字节）。

    Args:
        file_path: 文件路径

    Returns:
        int: 文件大小（字节）
    """
    return os.path.getsize(file_path)


def format_size(size_bytes):
    """
    格式化文件大小为人类可读的字符串。

    Args:
        size_bytes: 文件大小（字节）

    Returns:
        str: 格式化后的大小字符串
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def compress_with_ffmpeg(ffmpeg_path, input_file, output_file, crf_value):
    """
    使用 ffmpeg 对 WebM 视频进行快速压缩。
    优先用 VP8（比 VP9 快 3-5 倍且与 .webm 兼容），VP8 失败时回退到 VP9 最快档。

    Args:
        ffmpeg_path: ffmpeg 可执行文件路径
        input_file: 输入视频文件路径
        output_file: 输出视频文件路径
        crf_value: CRF 值（0-63，值越小质量越高）

    Returns:
        dict: {'success': bool, 'message': str}
    """
    candidates = [
        ("VP8", [
            ffmpeg_path,
            "-i", str(input_file),
            "-c:v", "libvpx",
            "-crf", str(crf_value),
            "-b:v", "2M",
            "-cpu-used", "8",
            "-deadline", "realtime",
            "-an", "-y",
            str(output_file),
        ]),
        ("VP9-fast", [
            ffmpeg_path,
            "-i", str(input_file),
            "-c:v", "libvpx-vp9",
            "-crf", str(crf_value),
            "-b:v", "0",
            "-cpu-used", "8",
            "-deadline", "realtime",
            "-row-mt", "1",
            "-an", "-y",
            str(output_file),
        ]),
    ]

    last_error = ""
    for label, cmd in candidates:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=90,
            )
            if result.returncode == 0:
                return {"success": True, "message": f"ffmpeg {label} CRF={crf_value} 压缩成功"}
            error_lines = result.stderr.strip().split("\n")[-3:]
            last_error = " ".join(line.strip() for line in error_lines)
        except subprocess.TimeoutExpired:
            last_error = f"{label} 压缩超时"
        except Exception as e:
            last_error = f"{label} 异常: {e}"

    return {"success": False, "message": f"ffmpeg 压缩失败: {last_error[:200]}"}


def fallback_copy(input_file, output_file):
    """
    降级方案：当 ffmpeg 不可用时，直接复制文件。

    Args:
        input_file: 输入文件路径
        output_file: 输出文件路径

    Returns:
        dict: {'success': bool, 'message': str}
    """
    try:
        shutil.copy2(str(input_file), str(output_file))
        return {"success": True, "message": "ffmpeg 不可用，已执行文件复制（未压缩）"}
    except Exception as e:
        return {"success": False, "message": f"文件复制失败: {str(e)}"}


def process_single_video(ffmpeg_path, input_file, output_dir, crf_value):
    """
    处理单个视频文件：压缩或复制。

    Args:
        ffmpeg_path: ffmpeg 路径（None 表示不可用）
        input_file: 输入视频文件路径
        output_dir: 输出目录
        crf_value: CRF 值

    Returns:
        dict: 处理结果，包含原始大小、压缩后大小、压缩比等
    """
    input_path = Path(input_file)
    output_path = Path(output_dir) / input_path.name

    original_size = get_file_size_bytes(input_path)

    result = {
        "file_name": input_path.name,
        "input": str(input_path),
        "output": str(output_path),
        "original_size": original_size,
        "original_size_display": format_size(original_size),
        "compressed_size": 0,
        "compressed_size_display": "0 B",
        "compression_ratio": "0%",
        "saved_bytes": 0,
        "success": False,
        "message": "",
    }

    # 判断输入和输出是否在同一目录，如果是则使用临时文件
    same_dir = input_path.parent.resolve() == Path(output_dir).resolve()
    if same_dir:
        temp_output = input_path.with_suffix(".tmp.webm")
    else:
        temp_output = output_path

    # 执行压缩或复制
    if ffmpeg_path:
        compress_result = compress_with_ffmpeg(ffmpeg_path, input_path, temp_output, crf_value)
    else:
        compress_result = fallback_copy(input_path, temp_output)

    result["success"] = compress_result["success"]
    result["message"] = compress_result["message"]

    if compress_result["success"] and temp_output.exists():
        compressed_size = get_file_size_bytes(temp_output)
        result["compressed_size"] = compressed_size
        result["compressed_size_display"] = format_size(compressed_size)

        if original_size > 0:
            ratio = (1 - compressed_size / original_size) * 100
            result["compression_ratio"] = f"{ratio:.1f}%"
            result["saved_bytes"] = original_size - compressed_size

        # 如果输出在同一目录，用临时文件替换原文件
        if same_dir and temp_output != output_path:
            try:
                temp_output.replace(input_path)
                result["output"] = str(input_path)
            except Exception as e:
                result["message"] += f" (替换原文件失败: {e})"

    return result


def scan_webm_files(input_dir):
    """
    扫描目录中的所有 .webm 视频文件。

    Args:
        input_dir: 输入目录路径

    Returns:
        list: 排序后的 .webm 文件路径列表
    """
    return sorted(Path(input_dir).glob("*.webm"))


def build_summary_json(results, quality, ffmpeg_available):
    """
    构建压缩统计摘要 JSON。

    Args:
        results: 所有文件的处理结果列表
        quality: 质量等级
        ffmpeg_available: ffmpeg 是否可用

    Returns:
        dict: 统计摘要数据
    """
    total_original = sum(r["original_size"] for r in results)
    total_compressed = sum(r["compressed_size"] for r in results)
    success_count = sum(1 for r in results if r["success"])

    if total_original > 0:
        overall_ratio = (1 - total_compressed / total_original) * 100
    else:
        overall_ratio = 0.0

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "quality": quality,
        "crf_value": QUALITY_CRF_MAP.get(quality, 28),
        "ffmpeg_available": ffmpeg_available,
        "total_files": len(results),
        "success_count": success_count,
        "failed_count": len(results) - success_count,
        "total_original_size": total_original,
        "total_original_size_display": format_size(total_original),
        "total_compressed_size": total_compressed,
        "total_compressed_size_display": format_size(total_compressed),
        "overall_compression_ratio": f"{overall_ratio:.1f}%",
        "total_saved": total_original - total_compressed,
        "total_saved_display": format_size(max(0, total_original - total_compressed)),
        "files": results,
    }

    return summary


def main():
    """主函数：解析参数、扫描文件、执行压缩、输出统计。"""
    parser = argparse.ArgumentParser(
        description="WebUI 测试视频压缩工具 - 对 Playwright 录制的 WebM 视频进行压缩"
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="输入视频目录路径（包含 .webm 文件）",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="压缩输出目录路径（默认: 与输入目录相同，原地压缩）",
    )
    parser.add_argument(
        "--quality",
        default="medium",
        choices=["low", "medium", "high"],
        help="压缩质量等级（默认: medium）。low=高压缩/低质量, medium=平衡, high=低压缩/高质量",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else input_dir

    # 验证输入目录
    if not input_dir.exists():
        print(f"错误: 输入目录不存在: {input_dir}")
        sys.exit(1)

    if not input_dir.is_dir():
        print(f"错误: 输入路径不是目录: {input_dir}")
        sys.exit(1)

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 获取 CRF 值
    crf_value = QUALITY_CRF_MAP[args.quality]

    print("=" * 60)
    print("WebUI 测试视频压缩工具")
    print("=" * 60)
    print(f"  输入目录: {input_dir}")
    print(f"  输出目录: {output_dir}")
    print(f"  压缩质量: {QUALITY_LABELS[args.quality]}")
    print(f"  CRF 值: {crf_value}")

    # ── 扫描 .webm 文件 ────────────────────────────────────────
    print(f"\n[1/3] 扫描视频文件...")
    webm_files = scan_webm_files(input_dir)

    if not webm_files:
        print("  未找到 .webm 视频文件，无需处理。")
        sys.exit(0)

    total_original_size = sum(get_file_size_bytes(f) for f in webm_files)
    print(f"  发现 {len(webm_files)} 个 .webm 文件")
    print(f"  原始总大小: {format_size(total_original_size)}")

    # ── 检测 ffmpeg ────────────────────────────────────────────
    print(f"\n[2/3] 检测压缩工具...")
    ffmpeg_path = check_ffmpeg()
    ffmpeg_available = ffmpeg_path is not None

    if not ffmpeg_available:
        print("  警告: 未检测到 ffmpeg，将执行文件复制（不进行实际压缩）")
        print("  提示: 安装 ffmpeg 以获得视频压缩功能:")
        print("    macOS:   brew install ffmpeg")
        print("    Ubuntu:  sudo apt install ffmpeg")
        print("    Windows: https://ffmpeg.org/download.html")

    # ── 逐一处理视频文件 ───────────────────────────────────────
    print(f"\n[3/3] 处理视频文件...")
    results = []

    for i, video_file in enumerate(webm_files, 1):
        file_size = format_size(get_file_size_bytes(video_file))
        print(f"\n  [{i}/{len(webm_files)}] {video_file.name} ({file_size})")

        result = process_single_video(ffmpeg_path, video_file, output_dir, crf_value)
        results.append(result)

        if result["success"]:
            print(f"    压缩后: {result['compressed_size_display']}")
            print(f"    压缩率: {result['compression_ratio']}")
            print(f"    状态: {result['message']}")
        else:
            print(f"    失败: {result['message']}")

    # ── 生成统计摘要 ────────────────────────────────────────────
    summary = build_summary_json(results, args.quality, ffmpeg_available)

    # 写入摘要 JSON 文件
    summary_path = output_dir / "compression-summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ── 打印最终报告 ────────────────────────────────────────────
    success_count = summary["success_count"]
    failed_count = summary["failed_count"]

    print("\n" + "=" * 60)
    print("压缩报告")
    print("=" * 60)
    print(f"  处理文件数: {len(results)}")
    print(f"  成功: {success_count}")
    print(f"  失败: {failed_count}")
    print(f"  压缩质量: {QUALITY_LABELS[args.quality]}")
    print(f"  ffmpeg 可用: {'是' if ffmpeg_available else '否'}")
    print(f"  原始总大小: {summary['total_original_size_display']}")
    print(f"  压缩后总大小: {summary['total_compressed_size_display']}")
    print(f"  总压缩率: {summary['overall_compression_ratio']}")
    print(f"  节省空间: {summary['total_saved_display']}")
    print(f"  统计摘要: {summary_path}")
    print("=" * 60)

    # 输出摘要路径供 Agent 解析
    print(str(summary_path))

    # 全部成功退出码为 0，否则为 1
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
