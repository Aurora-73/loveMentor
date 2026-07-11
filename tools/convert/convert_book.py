r"""递归批量转换书籍为 Markdown。

支持格式：.pdf .doc .docx .epub .txt .html .htm
默认保留源文件（加 --delete 删除源文件）。
已存在同名 .md 时跳过。

用法:
    python tools/batch_convert_books.py <目录> [--exclude <名1> <名2> ...] [--delete]
    python tools/batch_convert_books.py <文件>

示例:
    python tools/batch_convert_books.py "docs\百度网盘\[REDACTED]\泡妞231本" --exclude "D 红丸米格道" "E the rational male" "K X"
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
import re
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
    import win32com.client
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
    ".doc": None,  # 需要特殊处理
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


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="递归批量转换书籍为 Markdown")
    parser.add_argument("target", help="目标目录或文件")
    parser.add_argument("--exclude", nargs="*", default=[], help="要排除的目录名")
    parser.add_argument("--delete", action="store_true", help="转换后删除源文件")
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

    print(f"找到 {len(files)} 个文件待转换\n")

    ok, fail, skip = 0, 0, 0
    for i, filepath in enumerate(files, 1):
        name = os.path.basename(filepath)
        size_kb = os.path.getsize(filepath) // 1024
        print(f"[{i}/{len(files)}] {name} ({size_kb} KB) ... ", end="", flush=True)
        try:
            if process_file(filepath, args.delete):
                md_size = os.path.getsize(os.path.splitext(filepath)[0] + ".md")
                print(f"OK ({md_size // 1024} KB)")
                ok += 1
            else:
                print("SKIP (扫描版/需OCR)")
                skip += 1
        except Exception as e:
            print(f"ERROR: {e}")
            fail += 1

    print(f"\n完成: {ok} 成功, {skip} 跳过(需OCR), {fail} 失败, 共 {len(files)} 个")


if __name__ == "__main__":
    main()
