"""
通用需求文档解析器核心模块
支持 PDF、DOC/DOCX、TXT、MD 等多种格式
支持从 DOCX/PDF 中提取嵌入图片
依赖按需加载，仅在处理对应格式时才需要安装
"""
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
V_NS = "{urn:schemas-microsoft-com:vml}"

# 按需加载：仅在对应格式分支中使用
try:
    import docx  # type: ignore[reportMissingImports]
    from docx import Document  # type: ignore[reportMissingImports]
except ImportError:
    docx = None

try:
    import mammoth  # type: ignore[reportMissingImports]
    from markdownify import markdownify as md  # type: ignore[reportMissingImports]
except ImportError:
    mammoth = None

try:
    import pdfplumber  # type: ignore[reportMissingImports]
except ImportError:
    pdfplumber = None

try:
    import fitz  # type: ignore[reportMissingImports]  # PyMuPDF
except ImportError:
    fitz = None


class _DocxImageExtractor:
    """
    在按文档顺序遍历 DOCX 时收集图片。
    确保图片编号 [图片N] 与磁盘上 image_N.{ext} 严格按"在文档中出现的顺序"对应，
    而不是按 docx 内部 rels 字典的存储顺序。
    """

    def __init__(self, rels):
        self.rels = rels
        self.images: List[Dict] = []
        self.rid_to_index: Dict[str, int] = {}
        self.img_dir: Optional[Path] = None
        self._context_window: List[str] = []

    def update_context(self, text: str) -> None:
        if not text:
            return
        cleaned = text.strip()
        if not cleaned:
            return
        self._context_window.append(cleaned)
        if len(self._context_window) > 5:
            self._context_window.pop(0)

    def _current_context(self) -> str:
        return " | ".join(self._context_window[-3:])

    def consume_drawing(self, drawing_element) -> Optional[str]:
        rid = self._find_blip_rid(drawing_element)
        return self._save_or_reuse(rid) if rid else None

    def consume_pict(self, pict_element) -> Optional[str]:
        rid = self._find_imagedata_rid(pict_element)
        return self._save_or_reuse(rid) if rid else None

    @staticmethod
    def _find_blip_rid(drawing_element) -> Optional[str]:
        for blip in drawing_element.iter(f"{A_NS}blip"):
            rid = blip.get(f"{R_NS}embed") or blip.get(f"{R_NS}link")
            if rid:
                return rid
        return None

    @staticmethod
    def _find_imagedata_rid(pict_element) -> Optional[str]:
        for imagedata in pict_element.iter(f"{V_NS}imagedata"):
            rid = imagedata.get(f"{R_NS}id")
            if rid:
                return rid
        return None

    def _save_or_reuse(self, rid: str) -> Optional[str]:
        # 同一张图被复用：返回相同占位符，不重复写盘
        if rid in self.rid_to_index:
            return f"[图片{self.rid_to_index[rid]}]"

        if rid not in self.rels:
            return None
        rel = self.rels[rid]
        if "image" not in str(getattr(rel, "reltype", "")):
            return None

        try:
            img_part = rel.target_part
            img_bytes = img_part.blob

            target_ref = str(getattr(rel, "target_ref", ""))
            ext = Path(target_ref).suffix.lower() if target_ref else ".png"
            if ext not in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp"):
                ext = ".png"

            if self.img_dir is None:
                self.img_dir = Path(tempfile.mkdtemp(prefix="aqe_req_images_"))

            idx = len(self.images) + 1
            filename = f"image_{idx}{ext}"
            img_path = self.img_dir / filename
            with open(img_path, "wb") as f:
                f.write(img_bytes)

            self.images.append({
                "index": idx,
                "placeholder": f"[图片{idx}]",
                "path": str(img_path),
                "filename": filename,
                "size_bytes": len(img_bytes),
                "context": self._current_context(),
            })
            self.rid_to_index[rid] = idx
            return f"[图片{idx}]"
        except Exception as e:
            print(f"警告: 提取图片失败 (rId={rid}): {e}", file=sys.stderr)
            return None

    def cleanup_if_empty(self) -> None:
        if self.img_dir and not self.images:
            try:
                self.img_dir.rmdir()
            except OSError:
                pass


class RequirementParser:
    """统一需求文档解析器"""

    SUPPORTED_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt', '.md', '.markdown', '.rst'}

    def parse(
        self,
        file_path: Optional[str] = None,
        text: Optional[str] = None,
        mode: Literal["fast", "precise", "auto"] = "auto"
    ) -> Dict:
        """
        解析需求文档或文本

        Args:
            file_path: 文件路径（与 text 二选一）
            text: 直接文本输入（与 file_path 二选一）
            mode: DOCX 解析模式
                - fast: 纯文本提取（~50ms）
                - precise: 保留格式转 Markdown（~500ms）
                - auto: 根据文档复杂度自动选择

        Returns:
            {
                "content": "解析后的文本（图片位置用 [图片N] 占位符）",
                "images": [
                    {
                        "index": 1,
                        "placeholder": "[图片1]",
                        "path": "/tmp/xxx/image_1.jpeg",
                        "filename": "image_1.jpeg",
                        "size_bytes": 47206,
                        "context": "界面参考\n[图片1]\n操作流程"
                    }
                ],
                "source": "文件路径或'直接输入'",
                "source_type": "file" | "text",
                "format": "pdf" | "docx" | "txt" | "md" | "text",
                "metadata": {
                    "parse_time_ms": 45,
                    "content_length": 1234,
                    "image_count": 1
                }
            }
        """
        start_time = time.time()

        if file_path:
            result = self._parse_file(file_path, mode)
        elif text:
            result = self._parse_text(text)
        else:
            raise ValueError("必须提供 file_path 或 text 参数")

        # 确保 images 字段存在
        if "images" not in result:
            result["images"] = []

        result["metadata"]["parse_time_ms"] = int((time.time() - start_time) * 1000)
        result["metadata"]["content_length"] = len(result["content"])
        result["metadata"]["image_count"] = len(result["images"])

        if len(result["content"].strip()) < 10:
            result["metadata"]["warning"] = "内容过短，可能解析异常"

        return result

    def _parse_file(self, file_path: str, mode: str) -> Dict:
        """按文件类型分派解析"""
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = path.suffix.lower()

        if ext in ('.doc', '.docx'):
            return self._parse_docx(file_path, mode)
        elif ext == '.pdf':
            return self._parse_pdf(file_path)
        elif ext in ('.txt', '.md', '.markdown', '.rst'):
            return self._parse_text_file(file_path)
        else:
            return self._parse_text_file(file_path)

    # ── DOCX 解析 ──────────────────────────────────────────────

    def _parse_docx(self, file_path: str, mode: str) -> Dict:
        """解析 DOC/DOCX 文件。图片占位符 [图片N] 严格按"在文档中出现的顺序"插入到正文对应位置。"""
        if not docx:
            raise ImportError("请安装: pip install python-docx")

        if mode == "auto":
            mode = self._detect_docx_mode(file_path)

        if mode == "precise" and mammoth:
            try:
                return self._parse_docx_precise(file_path)
            except Exception as e:
                fallback = self._parse_docx_fast(file_path)
                fallback["metadata"]["fallback_reason"] = (
                    f"精确模式解析失败（{e}），已降级为快速模式"
                )
                return fallback

        result = self._parse_docx_fast(file_path)
        if mode == "precise" and not mammoth:
            result["metadata"]["fallback_reason"] = "mammoth 未安装，已降级为快速模式"
        return result

    def _detect_docx_mode(self, file_path: str) -> str:
        """检测 DOCX 文档复杂度，决定使用快速还是精确模式"""
        try:
            doc = Document(file_path)
            has_images = any(
                "image" in str(getattr(rel, 'reltype', ''))
                for rel in doc.part.rels.values()
            )
            has_tables = len(doc.tables) > 0
            return "precise" if (has_images or has_tables) else "fast"
        except Exception:
            return "fast"

    def _parse_docx_fast(self, file_path: str) -> Dict:
        """快速模式：按文档顺序遍历正文，将内联图片就地替换为 [图片N] 占位符。"""
        doc = Document(file_path)
        extractor = _DocxImageExtractor(doc.part.rels)

        para_map = {id(p._element): p for p in doc.paragraphs}
        table_map = {id(t._tbl): t for t in doc.tables}

        parts: List[str] = []
        for element in doc.element.body:
            tag = element.tag.split('}')[-1] if '}' in element.tag else element.tag
            if tag == 'p':
                para = para_map.get(id(element))
                if para is not None:
                    formatted = self._paragraph_to_markdown(para, extractor)
                else:
                    raw = element.text or ""
                    formatted = raw.strip()
                if formatted:
                    parts.append(formatted)
            elif tag == 'tbl':
                table = table_map.get(id(element))
                if table is not None:
                    md_table = self._table_to_markdown(table, extractor)
                    if md_table.strip():
                        parts.append(md_table)

        text = "\n\n".join(parts)

        # 兜底：如果发现 rels 里还有正文未引用的图片（罕见，例如位于 header/footer），
        # 追加到末尾以免完全丢失
        unreferenced = self._collect_unreferenced_images(doc, extractor)
        if unreferenced:
            text += "\n\n" + "\n\n".join(unreferenced)

        extractor.cleanup_if_empty()

        return {
            "content": text,
            "images": extractor.images,
            "source": file_path,
            "source_type": "file",
            "format": "docx",
            "metadata": {
                "mode": "fast",
                "has_tables": len(doc.tables) > 0,
                "table_count": len(doc.tables),
            },
        }

    @staticmethod
    def _get_heading_level(para) -> int:
        """从段落获取标题级别，兼容多种 Word 文档格式"""
        if para.style and para.style.name:
            name = para.style.name.lower()
            if name.startswith("heading"):
                try:
                    return int(name.replace("heading", "").strip())
                except ValueError:
                    pass

        nsmap = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

        outline_els = para._element.findall(f'.//{W_NS}outlineLvl', nsmap)
        if outline_els:
            try:
                return int(outline_els[0].get(f'{W_NS}val')) + 1
            except (ValueError, TypeError):
                pass

        style_els = para._element.findall(f'.//{W_NS}pStyle', nsmap)
        if style_els:
            style_id = style_els[0].get(f'{W_NS}val', '')
            if style_id.isdigit() and 1 <= int(style_id) <= 9:
                return int(style_id)

        return 0

    def _paragraph_to_markdown(self, para, extractor: Optional[_DocxImageExtractor] = None) -> str:
        """将段落转为 Markdown，保留标题层级、加粗/斜体，并按位置插入 [图片N] 占位符。"""
        heading_level = self._get_heading_level(para)

        parts: List[str] = []
        for child in para._element:
            tag = child.tag
            if tag == f"{W_NS}r":
                parts.append(self._render_run(child, heading_level, extractor))
            elif tag == f"{W_NS}hyperlink":
                for sub_run in child.iterfind(f"{W_NS}r"):
                    parts.append(self._render_run(sub_run, heading_level, extractor))

        text = "".join(parts).strip()
        if not text:
            return ""

        # 用当前段落（去除图片占位符后）的纯文本更新 extractor 上下文窗口
        if extractor is not None:
            plain = re.sub(r"\[图片\d+\]", "", text).strip()
            if plain:
                extractor.update_context(plain)

        if heading_level > 0:
            return f"{'#' * heading_level} {text}"
        return text

    @staticmethod
    def _render_run(run_element, heading_level: int, extractor: Optional[_DocxImageExtractor]) -> str:
        """渲染一个 <w:r>，按子元素出现顺序输出文字/格式与 [图片N] 占位符。"""
        rpr = run_element.find(f"{W_NS}rPr")
        is_bold = False
        is_italic = False
        if rpr is not None:
            b_el = rpr.find(f"{W_NS}b")
            i_el = rpr.find(f"{W_NS}i")
            # <w:b/> 默认开启；只有 w:val="0"/"false" 才表示关闭
            if b_el is not None and b_el.get(f"{W_NS}val", "1") not in ("0", "false"):
                is_bold = True
            if i_el is not None and i_el.get(f"{W_NS}val", "1") not in ("0", "false"):
                is_italic = True

        output: List[str] = []
        text_buffer: List[str] = []

        def flush_text() -> None:
            if not text_buffer:
                return
            text = "".join(text_buffer)
            text_buffer.clear()
            if not text:
                return
            if heading_level > 0:
                output.append(text)
            elif is_bold and is_italic:
                output.append(f"***{text}***")
            elif is_bold:
                output.append(f"**{text}**")
            elif is_italic:
                output.append(f"*{text}*")
            else:
                output.append(text)

        for child in run_element:
            tag = child.tag
            if tag == f"{W_NS}t":
                text_buffer.append(child.text or "")
            elif tag == f"{W_NS}br":
                text_buffer.append("\n")
            elif tag == f"{W_NS}tab":
                text_buffer.append("\t")
            elif tag == f"{W_NS}drawing":
                flush_text()
                if extractor is not None:
                    placeholder = extractor.consume_drawing(child)
                    if placeholder:
                        output.append(placeholder)
            elif tag == f"{W_NS}pict":
                flush_text()
                if extractor is not None:
                    placeholder = extractor.consume_pict(child)
                    if placeholder:
                        output.append(placeholder)

        flush_text()
        return "".join(output)

    def _table_to_markdown(self, table, extractor: Optional[_DocxImageExtractor] = None) -> str:
        """将表格转为 Markdown，单元格内图片同样按位置替换为 [图片N]。"""
        rows: List[List[str]] = []
        for row in table.rows:
            cells: List[str] = []
            for cell in row.cells:
                cell_parts: List[str] = []
                for para in cell.paragraphs:
                    rendered = self._paragraph_to_markdown(para, extractor)
                    rendered = re.sub(r"^#+\s+", "", rendered)
                    if rendered:
                        cell_parts.append(rendered)
                cell_text = " ".join(cell_parts).replace("\n", " ").strip()
                cells.append(cell_text)
            rows.append(cells)

        if not rows:
            return ""

        col_count = max(len(r) for r in rows)
        for r in rows:
            while len(r) < col_count:
                r.append("")

        lines = ["| " + " | ".join(rows[0]) + " |",
                 "| " + " | ".join(["---"] * col_count) + " |"]
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def _collect_unreferenced_images(self, doc, extractor: _DocxImageExtractor) -> List[str]:
        """处理正文遍历中未引用到的图片（极少见，如位于 header/footer/批注中）。"""
        unreferenced_placeholders: List[str] = []
        for rid, rel in doc.part.rels.items():
            if "image" not in str(getattr(rel, "reltype", "")):
                continue
            if rid in extractor.rid_to_index:
                continue
            placeholder = extractor._save_or_reuse(rid)
            if placeholder:
                unreferenced_placeholders.append(placeholder)
        return unreferenced_placeholders

    def _parse_docx_precise(self, file_path: str) -> Dict:
        """精确模式：先按文档顺序收集图片（确保编号一致），再由 mammoth 输出 markdown，
        最后把 markdown 中的 base64 图片按序替换为 [图片N]。"""
        doc = Document(file_path)
        extractor = _DocxImageExtractor(doc.part.rels)
        self._enumerate_docx_images_in_order(doc, extractor)

        with open(file_path, "rb") as f:
            result = mammoth.convert_to_html(f)
            html = result.value
            markdown = md(html)

        markdown = self._replace_base64_with_placeholders(markdown, extractor.images)

        extractor.cleanup_if_empty()

        return {
            "content": markdown,
            "images": extractor.images,
            "source": file_path,
            "source_type": "file",
            "format": "docx",
            "metadata": {"mode": "precise"},
        }

    def _enumerate_docx_images_in_order(self, doc, extractor: _DocxImageExtractor) -> None:
        """按文档顺序遍历 body，依次保存每张图片。仅为了得到与 mammoth 输出一致的图片编号。"""
        para_map = {id(p._element): p for p in doc.paragraphs}
        table_map = {id(t._tbl): t for t in doc.tables}

        def visit_paragraph(element) -> None:
            para = para_map.get(id(element))
            if para is not None and para.text:
                extractor.update_context(para.text)
            for drawing in element.iter(f"{W_NS}drawing"):
                extractor.consume_drawing(drawing)
            for pict in element.iter(f"{W_NS}pict"):
                extractor.consume_pict(pict)

        for element in doc.element.body:
            tag = element.tag.split('}')[-1] if '}' in element.tag else element.tag
            if tag == 'p':
                visit_paragraph(element)
            elif tag == 'tbl':
                table = table_map.get(id(element))
                if table is None:
                    continue
                for row in table.rows:
                    for cell in row.cells:
                        for cell_para in cell.paragraphs:
                            visit_paragraph(cell_para._element)

        # 同样兜底拾取未引用的图片
        self._collect_unreferenced_images(doc, extractor)

    def _replace_base64_with_placeholders(self, content: str, images: List[Dict]) -> str:
        """将 markdown 中的 base64 图片 ![...](data:image/...) 按出现顺序替换为 [图片N]。
        因为 extractor.images 已经按文档顺序编号、mammoth 也按文档顺序输出图片，所以
        第 N 个 base64 image 与磁盘上的 image_N.{ext} 一一对应。"""
        pattern = r'!\[[^\]]*\]\(data:image/[^)]+\)'
        matches = list(re.finditer(pattern, content))

        if matches:
            for i, match in enumerate(reversed(matches)):
                img_idx = len(matches) - i
                if img_idx <= len(images):
                    content = (
                        content[:match.start()]
                        + f"[图片{img_idx}]"
                        + content[match.end():]
                    )
            return content

        # 没有 base64 图片但 extractor 抓到了图（极少见，例如 mammoth 不内联）：兜底追加
        for img in images:
            if img["placeholder"] not in content:
                content += f"\n\n{img['placeholder']}"
        return content

    # ── PDF 解析 ───────────────────────────────────────────────

    def _parse_pdf(self, file_path: str) -> Dict:
        """解析 PDF。优先使用 PyMuPDF（fitz）按阅读顺序交错输出文字块与 [图片N] 占位符；
        若 PyMuPDF 不可用则退回 pdfplumber 仅提取文字。"""
        if fitz:
            return self._parse_pdf_with_fitz(file_path)
        if pdfplumber:
            return self._parse_pdf_text_only(file_path)
        raise ImportError("请安装: pip install PyMuPDF 或 pdfplumber")

    def _parse_pdf_with_fitz(self, file_path: str) -> Dict:
        """使用 PyMuPDF 一次性提取文字 + 图片，按 block 的 y/x 坐标交错排列。"""
        images: List[Dict] = []
        img_dir: Optional[Path] = None
        pages_content: List[str] = []
        page_count = 0

        pdf_doc = fitz.open(file_path)
        try:
            page_count = len(pdf_doc)
            for page_num, page in enumerate(pdf_doc):
                page_dict = page.get_text("dict")
                blocks = page_dict.get("blocks", [])
                # 按 (y, x) 排序，模拟人类的"从上到下、从左到右"阅读顺序
                blocks.sort(key=lambda b: (
                    round(b.get("bbox", [0, 0, 0, 0])[1], 1),
                    round(b.get("bbox", [0, 0, 0, 0])[0], 1),
                ))

                # 预收集文字块用于"取图片附近文字"作为 context
                text_blocks_with_y: List[Tuple[float, str]] = []
                for blk in blocks:
                    if blk.get("type") == 0:
                        t = self._extract_pdf_block_text(blk)
                        if t:
                            text_blocks_with_y.append((blk["bbox"][1], t))

                page_parts: List[str] = []
                for block in blocks:
                    btype = block.get("type")
                    if btype == 0:
                        t = self._extract_pdf_block_text(block)
                        if t:
                            page_parts.append(t)
                    elif btype == 1:
                        width = block.get("width", 0)
                        height = block.get("height", 0)
                        img_bytes = block.get("image")
                        if not img_bytes or width < 50 or height < 50:
                            continue

                        if img_dir is None:
                            img_dir = Path(tempfile.mkdtemp(prefix="aqe_req_images_"))

                        idx = len(images) + 1
                        ext = (block.get("ext") or "png").lower()
                        filename = f"image_{idx}.{ext}"
                        img_path = img_dir / filename
                        try:
                            with open(img_path, "wb") as f:
                                f.write(img_bytes)
                        except Exception as e:
                            print(
                                f"警告: 写入 PDF 图片失败 (page={page_num}, idx={idx}): {e}",
                                file=sys.stderr,
                            )
                            continue

                        img_y = block.get("bbox", [0, 0, 0, 0])[1]
                        context = self._nearest_pdf_text(text_blocks_with_y, img_y)
                        if not context:
                            context = f"PDF 第{page_num + 1}页"

                        images.append({
                            "index": idx,
                            "placeholder": f"[图片{idx}]",
                            "path": str(img_path),
                            "filename": filename,
                            "size_bytes": len(img_bytes),
                            "context": context,
                        })
                        page_parts.append(f"[图片{idx}]")

                if page_parts:
                    pages_content.append("\n\n".join(page_parts))
        finally:
            pdf_doc.close()

        if img_dir and not images:
            try:
                img_dir.rmdir()
            except OSError:
                pass

        return {
            "content": "\n\n".join(pages_content),
            "images": images,
            "source": file_path,
            "source_type": "file",
            "format": "pdf",
            "metadata": {"page_count": page_count},
        }

    def _parse_pdf_text_only(self, file_path: str) -> Dict:
        """fallback：仅 pdfplumber 可用时，按页提取文字、不提图片。"""
        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            pages = []
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages.append(page_text)
            text = "\n\n".join(pages)

        return {
            "content": text,
            "images": [],
            "source": file_path,
            "source_type": "file",
            "format": "pdf",
            "metadata": {
                "page_count": page_count,
                "fallback_reason": "PyMuPDF 未安装，PDF 图片未提取",
            },
        }

    @staticmethod
    def _extract_pdf_block_text(block: Dict) -> str:
        """从一个 PyMuPDF text block 中拼出纯文本（保留行内换行）。"""
        lines = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            line_text = "".join(span.get("text", "") for span in spans)
            if line_text:
                lines.append(line_text)
        return "\n".join(lines).strip()

    @staticmethod
    def _nearest_pdf_text(text_blocks_with_y: List[Tuple[float, str]], image_y: float,
                          max_blocks: int = 3, max_chars: int = 200) -> str:
        """找出离图片 y 坐标最近的若干段文字作为上下文。"""
        if not text_blocks_with_y:
            return ""
        sorted_blocks = sorted(text_blocks_with_y, key=lambda item: abs(item[0] - image_y))
        snippets = [t for _, t in sorted_blocks[:max_blocks]]
        joined = " | ".join(snippets)
        return joined[:max_chars]

    # ── 文本文件解析 ───────────────────────────────────────────

    def _parse_text_file(self, file_path: str) -> Dict:
        """解析文本文件（TXT、MD 等），自动检测 [图片N] 占位符和本地图片"""
        path = Path(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()

        images = self._detect_local_images(path.parent, text)

        return {
            "content": text,
            "images": images,
            "source": file_path,
            "source_type": "file",
            "format": path.suffix.lstrip('.') or "txt",
            "metadata": {}
        }

    def _detect_local_images(self, base_dir: Path, content: str) -> List[Dict]:
        """
        检测文本中的 [图片N] 占位符，查找对应的本地图片文件。
        支持两种来源：
        1. images_manifest.json（由 fetch-requirement 生成）
        2. images/ 目录下的 image_N.{ext} 文件（按命名约定匹配）
        """
        placeholders = re.findall(r'\[图片(\d+)\]', content)
        if not placeholders:
            return []

        indices = sorted(set(int(n) for n in placeholders))

        # 优先使用 manifest（包含完整的元数据）
        manifest_path = base_dir / "images_manifest.json"
        if manifest_path.exists():
            try:
                import json
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                images = []
                for entry in manifest:
                    idx = entry.get("index")
                    local_path = entry.get("local_path")
                    if idx not in indices or not local_path:
                        continue
                    abs_path = base_dir / local_path
                    if abs_path.exists():
                        images.append({
                            "index": idx,
                            "placeholder": f"[图片{idx}]",
                            "path": str(abs_path),
                            "filename": abs_path.name,
                            "size_bytes": abs_path.stat().st_size,
                            "context": self._find_placeholder_context(content, idx),
                        })
                return images
            except Exception:
                pass

        # 兜底：在 images/ 目录下按命名约定查找
        images_dir = base_dir / "images"
        if not images_dir.is_dir():
            return []

        images = []
        for idx in indices:
            matched = list(images_dir.glob(f"image_{idx}.*"))
            if matched:
                img_path = matched[0]
                images.append({
                    "index": idx,
                    "placeholder": f"[图片{idx}]",
                    "path": str(img_path),
                    "filename": img_path.name,
                    "size_bytes": img_path.stat().st_size,
                    "context": self._find_placeholder_context(content, idx),
                })

        return images

    @staticmethod
    def _find_placeholder_context(content: str, index: int) -> str:
        """提取 [图片N] 占位符前后的文字作为上下文（保留占位符本身以标记位置）"""
        pattern = re.compile(rf'\[图片{index}\]')
        match = pattern.search(content)
        if not match:
            return ""

        start = max(0, match.start() - 200)
        end = min(len(content), match.end() + 100)
        surrounding = content[start:end]

        lines = [l.strip() for l in surrounding.split('\n') if l.strip()]
        return '\n'.join(lines[-5:]) if lines else ""

    # ── 直接文本输入 ───────────────────────────────────────────

    def _parse_text(self, text: str) -> Dict:
        """处理直接文本输入"""
        return {
            "content": text,
            "source": "直接输入",
            "source_type": "text",
            "format": "text",
            "metadata": {}
        }

    # ── 临时文件清理 ───────────────────────────────────────────

    @staticmethod
    def cleanup_images(images: List[Dict]):
        """清理提取的临时图片文件。在 AI 分析完图片内容后调用。"""
        import shutil
        dirs_to_remove = set()
        for img in images:
            img_path = Path(img["path"])
            if img_path.exists():
                dirs_to_remove.add(img_path.parent)
                img_path.unlink()
        for d in dirs_to_remove:
            try:
                d.rmdir()
            except OSError:
                pass


def parse_requirement(file_path: str = None, text: str = None, mode: str = "auto") -> str:
    """便捷函数：返回解析后的文本内容"""
    parser = RequirementParser()
    result = parser.parse(file_path=file_path, text=text, mode=mode)
    return result["content"]
