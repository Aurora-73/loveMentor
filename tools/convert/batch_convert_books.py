r"""递归批量转换书籍为 Markdown。

支持格式：.pdf .doc .docx .epub .txt .html .htm .ppt .pptx
默认保留源文件（加 --delete 删除源文件）。
已存在同名 .md 时跳过。
转换失败的任意格式文件均自动打包为 ocr_needed_<时间戳>.zip，内含 ocr_manifest.json 记录映射。
0 字节文件直接删除，不尝试转换。

用法:
    python tools/convert/batch_convert_books.py <目录> [--exclude <名1> <名2> ...] [--delete] [--workers N]
    python tools/convert/batch_convert_books.py <文件>

示例:
    python tools/convert/batch_convert_books.py "docs\百度网盘\[REDACTED]\泡妞231本" --exclude "D 红丸米格道" "E the rational male" "K X"
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import tempfile
import zipfile
import shutil
import stat
import concurrent.futures
import json
import re
import time
from datetime import datetime
from html.parser import HTMLParser

# ─────────────────────────── PDF → MD ───────────────────────────

def convert_pdf(pdf_path: str, md_path: str) -> bool:
    """Convert PDF without OCR. Returns False for scanned PDFs (no embedded text)."""
    try:
        import pymupdf4llm
        from pymupdf4llm.helpers.document_layout import OCRMode

        md_text = pymupdf4llm.to_markdown(
            pdf_path,
            write_images=False,
            image_path=None,
            page_chunks=False,
            use_ocr=OCRMode.NEVER,
        )
        if not md_text or len(md_text.strip()) < 10:
            return False
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        return True
    except Exception:
        return False


def convert_pdf_with_ocr(pdf_path: str, md_path: str) -> bool:
    """Convert PDF with OCR enabled. For mixed (text+image) PDFs."""
    try:
        import pymupdf4llm
        from pymupdf4llm.helpers.document_layout import OCRMode

        md_text = pymupdf4llm.to_markdown(
            pdf_path,
            write_images=False,
            image_path=None,
            page_chunks=False,
            use_ocr=OCRMode.ON_ALL_PAGES,
        )
        if not md_text or len(md_text.strip()) < 10:
            return False
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        return True
    except Exception:
        return False


# ─────────────────────────── DOC/DOCX → MD ───────────────────────────

def convert_docx(docx_path: str, md_path: str) -> bool:
    try:
        from docx import Document
        doc = Document(docx_path)
        lines: list[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                lines.append("")
                continue
            style_name = (para.style.name or "").lower() if para.style else ""
            if style_name.startswith("heading"):
                try:
                    level = int(style_name.replace("heading", "").strip())
                except ValueError:
                    level = 1
                level = min(max(level, 1), 6)
                lines.append(f"{'#' * level} {text}")
            elif style_name.startswith("list"):
                lines.append(f"- {text}")
            else:
                lines.append(text)
        for table in doc.tables:
            if lines and lines[-1] != "":
                lines.append("")
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    cell_text = " ".join(
                        para.text.strip() for para in cell.paragraphs if para.text.strip()
                    )
                    cells.append(cell_text)
                row_text = " | ".join(c for c in cells if c)
                if row_text:
                    lines.append(row_text)
        content = "\n".join(lines).strip()
        if not content:
            return False
        with open(md_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content + "\n")
        return True
    except Exception:
        return False


def convert_doc_via_word(doc_path: str, tmp_dir: str) -> str | None:
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(doc_path)
        tmp_docx = os.path.join(
            tmp_dir, os.path.splitext(os.path.basename(doc_path))[0] + ".docx"
        )
        doc.SaveAs2(tmp_docx, FileFormat=16)
        doc.Close()
        return tmp_docx
    except Exception:
        return None
    finally:
        word.Quit()
        pythoncom.CoUninitialize()


# ─────────────────────────── EPUB → MD ───────────────────────────

class _HTMLToMD(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.lines.append("\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.lines.append("\n")
        elif tag == "br":
            self.lines.append("\n")
        elif tag == "li":
            self.lines.append("\n- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li"):
            self.lines.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.lines.append(data)

    def get_markdown(self) -> str:
        text = "".join(self.lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def convert_epub(epub_path: str, md_path: str) -> bool:
    try:
        with zipfile.ZipFile(epub_path) as z:
            html_files = sorted(
                [n for n in z.namelist() if n.endswith(".html") and "Text" in n],
                key=lambda x: x,
            )
            if not html_files:
                html_files = sorted(
                    [n for n in z.namelist() if n.endswith((".html", ".xhtml", ".htm"))],
                    key=lambda x: x,
                )
            if not html_files:
                return False
            parts: list[str] = []
            for hf in html_files:
                with z.open(hf) as f:
                    raw = f.read()
                    try:
                        content = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        content = raw.decode("gb18030", errors="replace")
                    parser = _HTMLToMD()
                    parser.feed(content)
                    md = parser.get_markdown()
                    if md.strip():
                        parts.append(md)
            result = "\n\n---\n\n".join(parts)
            if len(result) < 50:
                return False
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(result)
            return True
    except Exception:
        return False


# ─────────────────────────── PPT/PPTX → MD ───────────────────────────

def convert_pptx(pptx_path: str, md_path: str) -> bool:
    """Convert PPTX to Markdown by extracting text from slides (pure Python)."""
    try:
        from pptx import Presentation
        prs = Presentation(pptx_path)
        lines: list[str] = []
        for i, slide in enumerate(prs.slides, 1):
            lines.append(f"\n## Slide {i}\n")
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = para.text.strip()
                        if text:
                            lines.append(text + "\n\n")
        content = "".join(lines).strip()
        if not content:
            return False
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(content + "\n")
        return True
    except ImportError:
        return False
    except Exception:
        return False


def convert_ppt_via_powerpoint(ppt_path: str, tmp_dir: str) -> str | None:
    """Convert .ppt to .pptx using PowerPoint COM (win32com)."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return None
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    powerpoint = win32com.client.Dispatch("PowerPoint.Application")
    powerpoint.Visible = False
    try:
        presentation = powerpoint.Presentations.Open(ppt_path)
        tmp_pptx = os.path.join(
            tmp_dir, os.path.splitext(os.path.basename(ppt_path))[0] + ".pptx"
        )
        presentation.SaveAs(tmp_pptx, 24)  # 24 = ppSaveAsOpenXMLPresentation
        presentation.Close()
        return tmp_pptx
    except Exception:
        return None
    finally:
        powerpoint.Quit()
        pythoncom.CoUninitialize()


# ─────────────────────────── TXT/HTML → MD ───────────────────────────

def convert_txt(filepath: str, md_path: str) -> bool:
    for enc in ("utf-8", "gb18030", "utf-16", "big5"):
        try:
            with open(filepath, "r", encoding=enc) as f:
                content = f.read()
            if content.strip():
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(content)
                return True
        except (UnicodeDecodeError, OSError):
            continue
    return False


def convert_html(filepath: str, md_path: str) -> bool:
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
        for enc in ("utf-8", "gb18030"):
            try:
                content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                content = raw.decode("utf-8", errors="replace")
        parser = _HTMLToMD()
        parser.feed(content)
        md = parser.get_markdown()
        if len(md) < 10:
            return False
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
        return True
    except Exception:
        return False


# ─────────────────────────── 主逻辑 ───────────────────────────

CONVERTERS = {
    ".pdf": convert_pdf,
    ".docx": convert_docx,
    ".doc": None,  # 需要特殊处理（Word COM → .docx）
    ".pptx": convert_pptx,
    ".ppt": None,  # 需要特殊处理（PowerPoint COM → .pptx）
    ".epub": convert_epub,
    ".txt": convert_txt,
    ".html": convert_html,
    ".htm": convert_html,
}


def collect_files(root: str, extensions: set[str], excludes: set[str]) -> list[str]:
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 过滤排除目录
        rel_dir = os.path.relpath(dirpath, root)
        parts = rel_dir.split(os.sep)
        if any(p in excludes for p in parts):
            continue
        # 原地修改 dirnames 以阻止递归进排除目录
        dirnames[:] = [d for d in dirnames if d not in excludes]

        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in extensions:
                md_path = os.path.splitext(os.path.join(dirpath, name))[0] + ".md"
                if os.path.exists(md_path):
                    continue
                results.append(os.path.join(dirpath, name))
    return sorted(results)


def process_file(filepath: str, delete_source: bool) -> bool:
    ext = os.path.splitext(filepath)[1].lower()
    md_path = os.path.splitext(filepath)[0] + ".md"

    if ext == ".doc":
        tmp_dir = tempfile.mkdtemp(prefix="doc2md_")
        try:
            tmp_docx = convert_doc_via_word(filepath, tmp_dir)
            if tmp_docx is None:
                return False
            ok = convert_docx(tmp_docx, md_path)
            if ok and delete_source:
                os.chmod(filepath, stat.S_IWRITE)
                os.remove(filepath)
            return ok
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if ext == ".ppt":
        tmp_dir = tempfile.mkdtemp(prefix="ppt2md_")
        try:
            tmp_pptx = convert_ppt_via_powerpoint(filepath, tmp_dir)
            if tmp_pptx is None:
                return False
            ok = convert_pptx(tmp_pptx, md_path)
            if ok and delete_source:
                os.chmod(filepath, stat.S_IWRITE)
                os.remove(filepath)
            return ok
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    converter = CONVERTERS.get(ext)
    if converter is None:
        return False

    ok = converter(filepath, md_path)
    if ok and delete_source:
        try:
            os.remove(filepath)
        except OSError:
            pass
    return ok


def _unique_zip_name(filepath: str, existing: set[str]) -> str:
    """生成 ZIP 内唯一文件名（同名文件自动加后缀）。"""
    name = os.path.basename(filepath)
    if name not in existing:
        existing.add(name)
        return name
    stem, ext = os.path.splitext(name)
    counter = 1
    while f"{stem}_{counter}{ext}" in existing:
        counter += 1
    unique = f"{stem}_{counter}{ext}"
    existing.add(unique)
    return unique


def _process_one(filepath: str, delete_source: bool) -> dict:
    """处理单个文件，返回结果 dict（不打印输出）。"""
    try:
        ext = os.path.splitext(filepath)[1].lower()

        # PDF 一律跳过，直接打包
        if ext == '.pdf':
            return {"status": "ocr", "filepath": filepath}

        if os.path.getsize(filepath) == 0:
            os.remove(filepath)
            return {"status": "zero", "filepath": filepath}

        ok = process_file(filepath, delete_source)
        if ok:
            md_size = os.path.getsize(os.path.splitext(filepath)[0] + ".md")
            return {"status": "ok", "filepath": filepath, "detail": md_size // 1024}

        # 非 PDF 失败 → 打包
        return {"status": "ocr", "filepath": filepath}
    except Exception as e:
        return {"status": "error", "filepath": filepath, "detail": str(e)}


def _print_result(result: dict, index: int, total: int, start_time: float = 0):
    """打印单个文件处理结果。"""
    filepath = result["filepath"]
    name = os.path.basename(filepath)
    status = result["status"]
    # 显示输出 .md 的大小（源文件可能已被 --delete 删除）
    md_path = os.path.splitext(filepath)[0] + ".md"
    size_kb = os.path.getsize(md_path) // 1024 if os.path.exists(md_path) else 0

    elapsed = time.time() - start_time if start_time else 0
    if index > 0 and elapsed > 0 and total > 1:
        eta = elapsed / index * (total - index)
        time_str = f"  [{int(elapsed//60)}m{int(elapsed%60)}s<{int(eta//60)}m{int(eta%60)}s]"
    else:
        time_str = ""

    prefix = f"[{index}/{total}] {name} ({size_kb} KB){time_str} ... "

    if status == "ok":
        print(f"{prefix}OK ({result['detail']} KB)")
    elif status == "ocr_converted":
        print(f"{prefix}OCR转MD ({result['detail']} KB, 保留源文件)")
    elif status == "zero":
        print(f"{prefix}0字节 (已删除)")
    elif status == "ocr":
        print(f"{prefix}需OCR (将打包至压缩包)")
    elif status == "error":
        print(f"{prefix}ERROR: {result['detail']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="递归批量转换书籍为 Markdown")
    parser.add_argument("target", help="目标目录或文件")
    parser.add_argument("--exclude", nargs="*", default=[], help="要排除的目录名")
    parser.add_argument("--delete", action="store_true", help="转换后删除源文件")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1), help=f"并发数（默认 CPU 核数: {min(8, os.cpu_count() or 1)}，>1 启用并发处理）")
    args = parser.parse_args()

    target = os.path.abspath(args.target)
    excludes = set(args.exclude)

    if os.path.isfile(target):
        files = [target]
    elif os.path.isdir(target):
        print(f"扫描目录: {target}")
        if excludes:
            print(f"排除目录: {', '.join(excludes)}")
        files = collect_files(target, set(CONVERTERS.keys()), excludes)
    else:
        print(f"路径不存在: {target}")
        sys.exit(1)

    if not files:
        print("没有找到需要转换的文件（可能已全部转换完成）")
        sys.exit(0)

    # 按文件大小排序，小的先转
    files.sort(key=lambda f: os.path.getsize(f))

    print(f"找到 {len(files)} 个文件待转换（并发数 {args.workers}）\n")

    results: list[dict] = []
    start_time = time.time()

    if args.workers <= 1:
        try:
            for i, fp in enumerate(files, 1):
                result = _process_one(fp, args.delete)
                _print_result(result, i, len(files), start_time)
                results.append(result)
        except KeyboardInterrupt:
            print("\n收到中断信号，正在退出...")
            sys.exit(130)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        executor = ThreadPoolExecutor(max_workers=args.workers)
        fut_map = {executor.submit(_process_one, fp, args.delete): fp for fp in files}
        done = 0
        try:
            for future in as_completed(fut_map):
                done += 1
                result = future.result()
                _print_result(result, done, len(files), start_time)
                results.append(result)
        except KeyboardInterrupt:
            print("\n收到中断信号，正在退出...")
            executor.shutdown(wait=False, cancel_futures=True)
            sys.exit(130)
        executor.shutdown(wait=True)
        # 恢复原始文件顺序
        order = {fp: i for i, fp in enumerate(files)}
        results.sort(key=lambda r: order.get(r["filepath"], 0))

    # 汇总结果
    ok = sum(1 for r in results if r["status"] == "ok")
    ocr_converted = sum(1 for r in results if r["status"] == "ocr_converted")
    zero = sum(1 for r in results if r["status"] == "zero")
    fail = sum(1 for r in results if r["status"] == "error")
    ocr_needed = [r["filepath"] for r in results if r["status"] == "ocr"]

    # 打包需要 OCR 的文件
    if ocr_needed:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"ocr_needed_{timestamp}.zip"
        out_dir = target if os.path.isdir(target) else os.path.dirname(target)
        zip_path = os.path.join(out_dir, zip_filename)

        used_names: set[str] = set()
        manifest: list[dict[str, str]] = []
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fp in ocr_needed:
                zname = _unique_zip_name(fp, used_names)
                zf.write(fp, zname)
                manifest.append({
                    "zip_name": zname,
                    "original_path": os.path.abspath(fp),
                })
            zf.writestr("ocr_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f"\n需OCR文件已打包: {zip_path} ({len(ocr_needed)} 个文件)")

        # --delete 时，打包完成后删除源文件
        if args.delete:
            deleted_ocr = 0
            for fp in ocr_needed:
                try:
                    os.chmod(fp, stat.S_IWRITE)
                    os.remove(fp)
                    deleted_ocr += 1
                except OSError:
                    pass
            print(f"已删除 {deleted_ocr} 个源文件")

    print(f"\n完成: {ok} 成功, {ocr_converted} OCR转MD(保留源文件), {zero} 个0字节(已删除), {len(ocr_needed)} 纯扫描件(已打包), {fail} 失败, 共 {len(files)} 个")


if __name__ == "__main__":
    main()
