#!/usr/bin/env python3
"""
截图 Base64 内联嵌入工具

功能说明：
- 扫描 HTML 报告中的截图引用（占位符和 img src 属性）
- 读取对应的截图图片文件，转换为 base64 编码
- 将占位符替换为内联 <img> 标签（data URI）
- 将相对路径的 img src 替换为 base64 data URI
- 生成自包含的单文件 HTML 报告（无外部图片依赖）

支持的占位符格式：
- [截图: path/to/screenshot.png]
- <img src="path/to/screenshot.png">

使用方式：
    python embed_screenshots_base64.py \\
        --html report_20240101.html \\
        --screenshot-dir qa/webui/session/execution/screenshots/ \\
        --output report_20240101_embedded.html
"""
from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path
from typing import Optional, Tuple


# ── 支持的图片格式及对应 MIME 类型 ────────────────────────────────
IMAGE_MIME_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
}


def _get_mime_type(file_path: str) -> str:
    """
    根据文件扩展名获取 MIME 类型。

    Args:
        file_path: 文件路径

    Returns:
        str: MIME 类型字符串，默认为 image/png
    """
    ext = Path(file_path).suffix.lower()
    return IMAGE_MIME_TYPES.get(ext, 'image/png')


def _read_image_as_base64(image_path: Path) -> str:
    """
    读取图片文件并转换为 base64 编码字符串。

    Args:
        image_path: 图片文件的 Path 对象

    Returns:
        str: base64 编码字符串

    Raises:
        FileNotFoundError: 图片文件不存在
        IOError: 读取文件失败
    """
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def _resolve_image_path(ref_path: str, screenshot_dir: Path) -> Optional[Path]:
    """
    解析截图引用路径，尝试多种方式定位实际图片文件。

    搜索策略（按优先级）：
    1. 作为绝对路径直接使用
    2. 相对于截图目录
    3. 仅取文件名，在截图目录中查找

    Args:
        ref_path: 截图引用路径字符串
        screenshot_dir: 截图目录的 Path 对象

    Returns:
        Path | None: 找到的图片文件路径，未找到返回 None
    """
    ref_path = ref_path.strip()

    # 策略 1：绝对路径
    abs_path = Path(ref_path)
    if abs_path.is_absolute() and abs_path.exists():
        return abs_path

    # 策略 2：相对于截图目录
    relative_path = screenshot_dir / ref_path
    if relative_path.exists():
        return relative_path

    # 策略 3：仅使用文件名在截图目录中查找
    filename = Path(ref_path).name
    filename_path = screenshot_dir / filename
    if filename_path.exists():
        return filename_path

    return None


def _build_img_tag(base64_data: str, mime_type: str, alt_text: str = "截图") -> str:
    """
    构建内联 base64 图片的 <img> 标签。

    Args:
        base64_data: 图片的 base64 编码数据
        mime_type: 图片 MIME 类型
        alt_text: 替代文本

    Returns:
        str: 完整的 <img> HTML 标签
    """
    return (
        f'<img src="data:{mime_type};base64,{base64_data}" '
        f'alt="{alt_text}" '
        f'class="screenshot-img" '
        f'style="max-width:100%;border-radius:4px;border:1px solid #e0e4e8;'
        f'margin:4px 0;cursor:pointer;" '
        f'onclick="window.open(this.src)">'
    )


def _build_not_found_placeholder(ref_path: str) -> str:
    """
    构建截图未找到时的占位提示。

    Args:
        ref_path: 原始截图引用路径

    Returns:
        str: 占位提示 HTML
    """
    return (
        f'<span style="display:inline-block;background:#fff2f0;border:1px dashed #ffccc7;'
        f'border-radius:4px;padding:8px 12px;font-size:12px;color:#a8071a;margin:4px 0;">'
        f'[截图未找到: {ref_path}]</span>'
    )


def embed_screenshots(html_content: str, screenshot_dir: Path,
                      max_image_size: int = 500 * 1024,
                      max_total_size: int = 10 * 1024 * 1024,
                      max_count: int = 50) -> Tuple[str, dict]:
    """
    扫描 HTML 内容并嵌入截图为 base64 data URI，受阈值控制。

    阈值保护：
    - max_image_size: 单图上限（默认 500KB），超阈值保留外链
    - max_total_size: 总嵌入上限（默认 10MB），达上限后后续截图保留外链
    - max_count: 最大嵌入数量（默认 50），达上限后后续截图保留外链

    处理两种引用格式：
    1. 占位符: [截图: path/to/image.png]
    2. img 标签: <img src="path/to/image.png">（非 data: 和 http 开头的路径）

    Args:
        html_content: 原始 HTML 字符串
        screenshot_dir: 截图文件所在目录
        max_image_size: 单图上限（字节），默认 500KB
        max_total_size: 总嵌入上限（字节），默认 10MB
        max_count: 最大嵌入数量，默认 50

    Returns:
        tuple: (处理后的 HTML 字符串, 统计信息字典)
    """
    stats = {
        'total_refs': 0,       # 发现的截图引用总数
        'embedded': 0,         # 成功嵌入的截图数
        'not_found': 0,        # 未找到的截图数
        'errors': 0,           # 处理出错的截图数
        'total_size_bytes': 0, # 嵌入的图片总大小（原始字节数）
        'skipped_size': 0,     # 因单图过大跳过的数量
        'skipped_total': 0,    # 因总大小超限跳过的数量
        'skipped_count': 0,    # 因数量超限跳过的数量
    }

    def _should_embed(image_file: Path) -> bool:
        """Check whether this image can be embedded under current thresholds."""
        if stats['embedded'] >= max_count:
            stats['skipped_count'] += 1
            return False
        if image_file.stat().st_size > max_image_size:
            stats['skipped_size'] += 1
            return False
        if stats['total_size_bytes'] + image_file.stat().st_size > max_total_size:
            stats['skipped_total'] += 1
            return False
        return True

    def _build_img_tag_with_link(ref_path: str, base64_data: str,
                                 mime_type: str, alt_text: str = "截图") -> str:
        """构建内联图片或降级为外链提示的 <img> 标签。"""
        return _build_img_tag(base64_data, mime_type, alt_text)

    def _build_link_img_tag(ref_path: str, mime_type: str,
                            alt_text: str = "截图") -> str:
        """构建保留外链的 <img> 标签（降级模式）。"""
        return (
            f'<img src="{ref_path}" '
            f'alt="{alt_text}" '
            f'class="screenshot-img" '
            f'style="max-width:100%;border-radius:4px;border:1px solid #e0e4e8;'
            f'margin:4px 0;cursor:pointer;" '
            f'onclick="window.open(this.src)">'
        )

    # Capture in closure for reuse across all replace functions
    _threshold_state = {'exceeded': False}

    def _try_embed(ref_path: str, image_file: Path,
                   stats: dict, mime_type: str, alt_text: str,
                   keep_link: bool = False) -> str:
        """尝试嵌入截图，超阈值时降级为外链。"""
        if not keep_link and _should_embed(image_file):
            base64_data = _read_image_as_base64(image_file)
            stats['embedded'] += 1
            stats['total_size_bytes'] += image_file.stat().st_size
            return _build_img_tag(base64_data, mime_type, alt_text=alt_text)
        else:
            # 降级：保留外链引用
            return _build_link_img_tag(ref_path, mime_type, alt_text=alt_text)

    # ── 处理占位符格式: [截图: path] ──
    # 匹配 <span class="screenshot-placeholder">[截图: xxx]</span> 整段
    placeholder_pattern = re.compile(
        r'<span[^>]*class="screenshot-placeholder"[^>]*>'
        r'\[截图:\s*([^\]]+)\]'
        r'</span>'
    )

    def replace_placeholder(match):
        ref_path = match.group(1).strip()
        stats['total_refs'] += 1

        image_file = _resolve_image_path(ref_path, screenshot_dir)
        if image_file is None:
            stats['not_found'] += 1
            return _build_not_found_placeholder(ref_path)

        try:
            mime_type = _get_mime_type(str(image_file))
            result = _try_embed(ref_path, image_file, stats, mime_type,
                                alt_text=f"截图: {ref_path}")
            return result
        except Exception as e:
            stats['errors'] += 1
            print(f'  警告: 处理截图失败 [{ref_path}]: {e}', file=sys.stderr)
            return _build_not_found_placeholder(f"{ref_path} (读取失败)")

    html_content = placeholder_pattern.sub(replace_placeholder, html_content)

    # ── 处理纯文本占位符（未被 span 包裹的情况） ──
    text_placeholder_pattern = re.compile(r'\[截图:\s*([^\]]+)\]')

    def replace_text_placeholder(match):
        ref_path = match.group(1).strip()
        stats['total_refs'] += 1

        image_file = _resolve_image_path(ref_path, screenshot_dir)
        if image_file is None:
            stats['not_found'] += 1
            return _build_not_found_placeholder(ref_path)

        try:
            mime_type = _get_mime_type(str(image_file))
            return _try_embed(ref_path, image_file, stats, mime_type,
                              alt_text=f"截图: {ref_path}")
        except Exception as e:
            stats['errors'] += 1
            print(f'  警告: 处理截图失败 [{ref_path}]: {e}', file=sys.stderr)
            return _build_not_found_placeholder(f"{ref_path} (读取失败)")

    html_content = text_placeholder_pattern.sub(replace_text_placeholder, html_content)

    # ── 处理 img src 属性（相对路径） ──
    # 匹配非 data: 和非 http(s): 开头的 img src
    img_src_pattern = re.compile(
        r'(<img\b[^>]*\bsrc=")([^"]+)("[^>]*>)',
        re.IGNORECASE,
    )

    def replace_img_src(match):
        prefix = match.group(1)
        src_path = match.group(2)
        suffix = match.group(3)

        # 跳过已经是 data URI 或网络 URL 的图片
        if src_path.startswith('data:') or src_path.startswith('http'):
            return match.group(0)

        stats['total_refs'] += 1

        image_file = _resolve_image_path(src_path, screenshot_dir)
        if image_file is None:
            stats['not_found'] += 1
            return match.group(0)  # 保持原样

        try:
            mime_type = _get_mime_type(str(image_file))
            if _should_embed(image_file):
                base64_data = _read_image_as_base64(image_file)
                stats['embedded'] += 1
                stats['total_size_bytes'] += image_file.stat().st_size
                return f'{prefix}data:{mime_type};base64,{base64_data}{suffix}'
            else:
                # 保留外链，不转为 data URI
                return match.group(0)
        except Exception as e:
            stats['errors'] += 1
            print(f'  警告: 处理图片失败 [{src_path}]: {e}', file=sys.stderr)
            return match.group(0)  # 保持原样

    html_content = img_src_pattern.sub(replace_img_src, html_content)

    return html_content, stats


def main():
    """
    命令行入口。
    扫描 HTML 报告中的截图引用并嵌入为 base64 data URI。
    """
    parser = argparse.ArgumentParser(
        description='截图 Base64 内联嵌入工具 - 将截图图片转为 base64 嵌入 HTML 报告',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
    # 嵌入截图并覆盖原文件
    python embed_screenshots_base64.py \\
        --html report_20240101.html \\
        --screenshot-dir webui-session/execution/screenshots/

    # 嵌入截图并输出到新文件
    python embed_screenshots_base64.py \\
        --html report_20240101.html \\
        --screenshot-dir webui-session/execution/screenshots/ \\
        --output report_20240101_embedded.html
        """
    )
    parser.add_argument(
        '--html', required=True,
        help='输入 HTML 报告文件路径'
    )
    parser.add_argument(
        '--screenshot-dir', required=True,
        help='截图文件所在目录路径'
    )
    parser.add_argument(
        '--output', default=None,
        help='输出 HTML 文件路径（默认覆盖输入文件）'
    )
    parser.add_argument(
        '--max-image-size', type=int, default=500 * 1024,
        help='单图嵌入大小上限（字节），默认 500KB'
    )
    parser.add_argument(
        '--max-total-size', type=int, default=10 * 1024 * 1024,
        help='总嵌入大小上限（字节），默认 10MB'
    )
    parser.add_argument(
        '--max-count', type=int, default=50,
        help='最大嵌入截图数量，默认 50'
    )
    args = parser.parse_args()

    # 验证输入文件
    html_path = Path(args.html)
    if not html_path.exists():
        print(f'错误: HTML 文件不存在: {html_path}', file=sys.stderr)
        sys.exit(1)

    # 验证截图目录
    screenshot_dir = Path(args.screenshot_dir)
    if not screenshot_dir.exists():
        print(f'警告: 截图目录不存在: {screenshot_dir}', file=sys.stderr)
        print('将继续处理，但截图可能无法嵌入。')
        # 仍然继续，因为有些截图可能使用绝对路径
    elif not screenshot_dir.is_dir():
        print(f'错误: 截图路径不是目录: {screenshot_dir}', file=sys.stderr)
        sys.exit(1)

    # 确定输出路径（默认覆盖输入文件）
    output_path = Path(args.output) if args.output else html_path

    # 读取 HTML 内容
    try:
        html_content = html_path.read_text(encoding='utf-8')
    except Exception as e:
        print(f'错误: 读取 HTML 文件失败: {e}', file=sys.stderr)
        sys.exit(1)

    print(f'正在处理 HTML 报告: {html_path}')
    print(f'截图目录: {screenshot_dir}')

    # 执行截图嵌入
    embedded_html, stats = embed_screenshots(
        html_content, screenshot_dir,
        max_image_size=args.max_image_size,
        max_total_size=args.max_total_size,
        max_count=args.max_count,
    )

    # 写入输出文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text(embedded_html, encoding='utf-8')
    except Exception as e:
        print(f'错误: 写入输出文件失败: {e}', file=sys.stderr)
        sys.exit(1)

    # 打印处理统计
    print(f'\n截图嵌入完成:')
    print(f'  发现截图引用: {stats["total_refs"]} 个')
    print(f'  成功嵌入: {stats["embedded"]} 个')
    print(f'  未找到: {stats["not_found"]} 个')
    print(f'  处理出错: {stats["errors"]} 个')
    if stats.get('skipped_size', 0) > 0:
        print(f'  跳过（单图过大）: {stats["skipped_size"]} 个')
    if stats.get('skipped_total', 0) > 0:
        print(f'  跳过（总大小超限）: {stats["skipped_total"]} 个')
    if stats.get('skipped_count', 0) > 0:
        print(f'  跳过（数量超限）: {stats["skipped_count"]} 个')

    if stats['total_size_bytes'] > 0:
        size_mb = stats['total_size_bytes'] / (1024 * 1024)
        print(f'  图片总大小: {size_mb:.2f} MB')

    print(f'\n输出文件: {output_path}')
    print(str(output_path))


if __name__ == '__main__':
    main()
