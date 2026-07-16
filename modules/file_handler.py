import io
import os
import re
import tempfile
import json
import urllib.request

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import Fit

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

from .state import BookmarkNode


def read_pdf_outlines(file_path):
    with open(file_path, "rb") as f:
        bytes_data = f.read()
    reader = PdfReader(io.BytesIO(bytes_data))
    outline = reader.outline

    def parse_outline_list(outline_list):
        nodes = []
        last_node = None
        for item in outline_list:
            if isinstance(item, list):
                if last_node:
                    last_node.children.extend(parse_outline_list(item))
                    for child in last_node.children:
                        child.parent = last_node
            else:
                try:
                    page_num = reader.get_destination_page_number(item)
                except Exception:
                    page_num = 0
                title = item.get("/Title", "Untitled")
                if isinstance(title, bytes):
                    title = title.decode("utf-8", errors="ignore")
                title = str(title).replace("\x00", "").strip()

                node = BookmarkNode(title, page_num)
                nodes.append(node)
                last_node = node
        return nodes

    return parse_outline_list(outline) if outline else [], len(reader.pages)


def save_outlines_to_writer(writer, nodes, parent=None):
    if not writer.pages:
        return
    for node in nodes:
        page_idx = max(0, min(node.page_number, len(writer.pages) - 1))
        item = writer.add_outline_item(
            title=node.title,
            page_number=page_idx,
            parent=parent
        )
        if node.children:
            save_outlines_to_writer(writer, node.children, parent=item)


def save_pdf_with_bookmarks(input_path, output_path, model):
    with open(input_path, "rb") as f:
        input_bytes = f.read()
    reader = PdfReader(io.BytesIO(input_bytes))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)

    if not writer.pages:
        raise ValueError("No pages were cloned from the source PDF.")

    if "/Outlines" in writer._root_object:
        del writer._root_object["/Outlines"]

    save_outlines_to_writer(writer, model.roots)
    writer.page_mode = "/UseOutlines"

    temp_dir = os.path.dirname(output_path) or "."
    temp_fd, temp_path = tempfile.mkstemp(dir=temp_dir, suffix=".pdf")
    try:
        with os.fdopen(temp_fd, "wb") as f:
            writer.write(f)
        if os.path.exists(output_path):
            os.remove(output_path)
        os.replace(temp_path, output_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise e


def generate_and_insert_toc(input_pdf_path, output_pdf_path, model, config):
    if not HAS_REPORTLAB:
        raise ImportError("ReportLab is not installed.")

    flat_list = []
    def flatten(nodes_list, level=0):
        for node in nodes_list:
            flat_list.append((node.title, node.page_number, level))
            flatten(node.children, level + 1)
    flatten(model.roots)

    if not flat_list:
        raise ValueError("Outline tree is empty. Add bookmarks before generating a TOC.")

    margin = config.get("margins", 54)
    line_height = config.get("line_height", 22)
    font_name = config.get("font_name", "Helvetica")
    title_text = config.get("title", "Table of Contents")
    dot_char = config.get("dot_leader", ".")
    auto_shift = config.get("auto_shift", True)
    insert_pos = config.get("page_offset", 0)
    theme_hex = config.get("theme_color", "#1A73E8")

    width, height = letter
    y_start = height - 100
    y_min = margin + 50
    items_per_page = int((y_start - y_min) / line_height)

    num_toc_pages = (len(flat_list) + items_per_page - 1) // items_per_page

    temp_toc_file = tempfile.mktemp(suffix=".pdf")
    c = canvas.Canvas(temp_toc_file, pagesize=letter)
    theme_color = HexColor(theme_hex)

    def draw_toc_header(canvas_obj, p_num):
        canvas_obj.setFillColor(theme_color)
        canvas_obj.rect(0, height - 8, width, 8, fill=1, stroke=0)

        canvas_obj.setFont(f"{font_name}-Bold", 24)
        canvas_obj.setFillColor(theme_color)
        canvas_obj.drawString(margin, height - 54, title_text)

        canvas_obj.setStrokeColor(theme_color)
        canvas_obj.setLineWidth(1.5)
        canvas_obj.line(margin, height - 62, width - margin, height - 62)

        canvas_obj.setFont(font_name, 9)
        canvas_obj.setFillColor(HexColor("#888888"))
        canvas_obj.drawRightString(width - margin, 36, f"Page {p_num} of {num_toc_pages}")

    y = y_start
    current_toc_page = 1
    draw_toc_header(c, current_toc_page)

    link_rects = []

    for title, original_target, level in flat_list:
        if y < y_min:
            c.showPage()
            current_toc_page += 1
            y = y_start
            draw_toc_header(c, current_toc_page)

        indent = margin + (level * 18)

        display_page = original_target
        if auto_shift and original_target >= insert_pos:
            display_page += num_toc_pages

        is_root = (level == 0)
        f_size = 11 if is_root else 9.5
        c.setFont(f"{font_name}-Bold" if is_root else font_name, f_size)
        c.setFillColor(HexColor("#111111") if is_root else HexColor("#444444"))

        c.drawString(indent, y, title)
        title_w = c.stringWidth(title)

        page_str = str(display_page + 1)
        page_w = c.stringWidth(page_str)
        c.drawRightString(width - margin, y, page_str)

        dots_start = indent + title_w + 6
        dots_end = width - margin - page_w - 6
        if dots_end > dots_start and dot_char:
            c.setFont(font_name, 9)
            c.setFillColor(HexColor("#CCCCCC"))
            dot_unit = dot_char + " "
            unit_w = c.stringWidth(dot_unit)
            num_units = max(0, int((dots_end - dots_start) / unit_w))
            dots_str = dot_unit * num_units
            c.drawString(dots_start, y, dots_str)

        rect = (margin - 5, y - 2, width - margin + 5, y + f_size + 2)
        link_rects.append((current_toc_page - 1, rect, display_page))

        y -= line_height

    c.save()

    with open(input_pdf_path, "rb") as f:
        orig_bytes = f.read()
    reader_orig = PdfReader(io.BytesIO(orig_bytes))
    reader_toc = PdfReader(temp_toc_file)
    writer = PdfWriter()

    orig_pages = list(reader_orig.pages)
    pre_pages = orig_pages[:insert_pos]
    post_pages = orig_pages[insert_pos:]

    for page in pre_pages:
        writer.add_page(page)

    for page in reader_toc.pages:
        writer.add_page(page)

    for page in post_pages:
        writer.add_page(page)

    expected_page_count = len(pre_pages) + len(reader_toc.pages) + len(post_pages)
    if len(writer.pages) != expected_page_count:
        raise ValueError(f"Page count mismatch: expected {expected_page_count}, got {len(writer.pages)}.")

    for toc_p, rect, target_p in link_rects:
        actual_writer_idx = insert_pos + toc_p
        link_anno = Link(
            rect=rect,
            target_page_index=target_p,
            fit=Fit.fit()
        )
        writer.add_annotation(page_number=actual_writer_idx, annotation=link_anno)

    def clone_and_shift(nodes_list):
        cloned = []
        for node in nodes_list:
            p = node.page_number
            if auto_shift and p >= insert_pos:
                p += num_toc_pages

            new_node = BookmarkNode(node.title, p)
            new_node.children = clone_and_shift(node.children)
            cloned.append(new_node)
        return cloned

    shifted_roots = clone_and_shift(model.roots)

    toc_bookmark = BookmarkNode(title_text, insert_pos)
    shifted_roots.insert(0, toc_bookmark)

    save_outlines_to_writer(writer, shifted_roots)
    writer.page_mode = "/UseOutlines"

    temp_dir = os.path.dirname(output_pdf_path) or "."
    temp_fd, temp_path = tempfile.mkstemp(dir=temp_dir, suffix=".pdf")
    try:
        with os.fdopen(temp_fd, "wb") as f:
            writer.write(f)
        if os.path.exists(output_pdf_path):
            os.remove(output_pdf_path)
        os.replace(temp_path, output_pdf_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise e

    try:
        os.remove(temp_toc_file)
    except Exception:
        pass

    return num_toc_pages, shifted_roots


def parse_text_toc(text):
    lines = text.splitlines()
    roots = []
    stack = []

    for line in lines:
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        md_match = re.match(r'^(#+)\s*(.*)', stripped)
        if md_match:
            indent = (len(md_match.group(1)) - 1) * 4
            stripped = md_match.group(2).strip()

        match = re.search(r'(.*?)\s*[-.@:_]*\s*(\d+)$', stripped)
        if match:
            title = match.group(1).strip()
            title = re.sub(r'[\s\.]+$', '', title).strip()
            page = int(match.group(2))
        else:
            title = stripped
            page = 1

        node = BookmarkNode(title, max(0, page - 1))

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if not stack:
            roots.append(node)
        else:
            parent_node = stack[-1][1]
            parent_node.add_child(node)

        stack.append((indent, node))

    return roots


def export_toc_to_text(nodes, level=0):
    lines = []
    for node in nodes:
        indent = "    " * level
        lines.append(f"{indent}{node.title} - {node.page_number + 1}")
        if node.children:
            lines.append(export_toc_to_text(node.children, level + 1))
    return "\n".join(lines)


def auto_detect_bookmarks_heuristics(pdf_path):
    with open(pdf_path, "rb") as f:
        bytes_data = f.read()
    reader = PdfReader(io.BytesIO(bytes_data))
    detected_nodes = []

    numbered_pattern = re.compile(r'^\s*(\d+(?:\.\d+)*)\s+([A-Z].*)')
    named_pattern = re.compile(
        r'^\s*(Chapter|Section|Part|Appendix|Unit|Introduction|Conclusion|Abstract|Summary|Background|Methodology|Results|Discussion|References)'
        r'(?:\s+(\d+(?:\.\d+)*))?'
        r'(?:\s*[:\-]?\s*(.+))?$',
        re.IGNORECASE
    )

    line_counts = {}
    pages_text = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        pages_text.append(lines)
        for line in lines:
            line_counts[line] = line_counts.get(line, 0) + 1

    seen = set()
    for page_idx, lines in enumerate(pages_text):
        for line in lines:
            if line_counts.get(line, 0) > 2:
                continue
            if line.isdigit():
                continue

            m_named = named_pattern.match(line)
            if m_named:
                category = m_named.group(1).title()
                num = m_named.group(2) or ""
                subtitle = (m_named.group(3) or "").strip()
                if num:
                    full_title = f"{category} {num}"
                    if subtitle:
                        full_title += f": {subtitle}"
                else:
                    full_title = category
                    if subtitle:
                        full_title += f": {subtitle}"
                dedup_key = (full_title.lower(), page_idx)
                if dedup_key not in seen and len(full_title) <= 100:
                    seen.add(dedup_key)
                    detected_nodes.append(BookmarkNode(full_title, page_idx))
                continue

            m_numbered = numbered_pattern.match(line)
            if m_numbered:
                num = m_numbered.group(1)
                title = m_numbered.group(2).strip()
                full_title = f"{num} {title}"
                dedup_key = (full_title.lower(), page_idx)
                if dedup_key not in seen and len(title) > 2 and len(full_title) <= 100:
                    seen.add(dedup_key)
                    detected_nodes.append(BookmarkNode(full_title, page_idx))
                continue

            if line.isupper() and 4 <= len(line) <= 60 and not re.match(r'^[^a-zA-Z]+$', line):
                titled = line.title()
                dedup_key = (titled.lower(), page_idx)
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    detected_nodes.append(BookmarkNode(titled, page_idx))
                continue

    roots = []
    stack = []

    def get_level(title):
        m = re.match(r'^\s*(\d+(\.\d+)*)', title)
        if m:
            parts = m.group(1).split('.')
            return len(parts)
        low = title.lower()
        if low.startswith('chapter'):
            return 1
        if low.startswith('section'):
            return 2
        if low.startswith('part'):
            return 1
        if low.startswith('appendix'):
            return 1
        if low.startswith('unit'):
            return 2
        return 1

    for node in detected_nodes:
        level = get_level(node.title)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1][1].add_child(node)
        stack.append((level, node))

    return roots


def auto_detect_bookmarks_semantics(pdf_path):
    with open(pdf_path, "rb") as f:
        bytes_data = f.read()
    reader = PdfReader(io.BytesIO(bytes_data))
    detected_nodes = []

    semantic_keywords = {
        "introduction", "conclusion", "summary", "methodology", "discussion",
        "abstract", "overview", "background", "results", "analysis",
        "references", "appendix", "foreword", "preface", "acknowledgement",
        "index", "outline", "bibliography", "objectives", "aims",
        "materials", "methods", "future work", "evaluation", "implementation",
        "chapter", "section", "part", "unit"
    }

    line_counts = {}
    pages_text = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        pages_text.append(lines)
        for line in lines:
            line_counts[line] = line_counts.get(line, 0) + 1

    seen = set()
    for page_idx, lines in enumerate(pages_text):
        for line in lines:
            if line_counts.get(line, 0) > 2:
                continue
            if line.isdigit() or len(line) < 3 or len(line) > 80:
                continue

            score = 0

            if line[-1] in ['.', '?', '!', ';', ',']:
                score -= 3

            if line.isupper():
                score += 3
            elif line.istitle():
                score += 2

            if re.match(r'^\s*(\d+|[IVXLCDM]+|[A-Z])\s*[\.\-\:]', line, re.IGNORECASE):
                score += 4

            words = set(re.findall(r'\b\w+\b', line.lower()))
            if words.intersection(semantic_keywords):
                score += 5

            if len(line) < 40:
                score += 1

            if score >= 3:
                dedup_key = (line.lower(), page_idx)
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    detected_nodes.append(BookmarkNode(line, page_idx))

    roots = []
    stack = []

    def get_level(title):
        m = re.match(r'^\s*(\d+(\.\d+)*)', title)
        if m:
            parts = m.group(1).split('.')
            return len(parts)
        low = title.lower()
        if low.startswith('chapter'):
            return 1
        if low.startswith('section'):
            return 2
        if low.startswith('part'):
            return 1
        if low.startswith('appendix'):
            return 1
        if low.startswith('unit'):
            return 2
        return 1

    for node in detected_nodes:
        level = get_level(node.title)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1][1].add_child(node)
        stack.append((level, node))

    return roots


def auto_detect_bookmarks_nlp(pdf_path, api_key, model="gemini-2.5-flash"):
    with open(pdf_path, "rb") as f:
        bytes_data = f.read()
    reader = PdfReader(io.BytesIO(bytes_data))

    document_pages = []
    for page_idx, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            document_pages.append(f"--- Page {page_idx + 1} ---\n" + "\n".join(lines))

    full_text_corpus = "\n\n".join(document_pages)

    if len(full_text_corpus) > 200000:
        full_text_corpus = full_text_corpus[:200000] + "\n\n[TRUNCATED DUE TO SIZE]"

    prompt_text = (
        "You are an expert document indexing assistant. Your job is to analyze the following document text and "
        "detect main structures (Chapters, Sections, Parts, and sub-sections) to construct a Table of Contents.\n"
        "Rules:\n"
        "1. Respond ONLY with a standard Markdown-formatted list using indented asterisks (e.g. * Chapter 1 - Page 1)\n"
        "2. Each entry MUST strictly end with ' - Page X' where X is the exact 1-indexed page number matching the page headers in the text.\n"
        "3. Preserve nested hierarchies using 4-space indentation.\n"
        "4. Do NOT output any markdown tags (like ```markdown), explanation text, introduction, or notes. Output ONLY the list.\n\n"
        "Here is the document text:\n\n" + full_text_corpus
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{
            "parts": [{"text": prompt_text}]
        }]
    }

    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            res_data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(f"Gemini API request failed: {str(e)}")

    if "candidates" not in res_data or not res_data["candidates"]:
        raise RuntimeError("Gemini API returned no candidates. The document may be too large or the API key may be invalid.")

    candidate = res_data["candidates"][0]
    if "content" not in candidate or "parts" not in candidate["content"]:
        raise RuntimeError("Gemini API returned an unexpected response format.")

    parts = candidate["content"]["parts"]
    if not parts or "text" not in parts[0]:
        raise RuntimeError("Gemini API returned empty content.")

    candidate_text = parts[0]["text"]
    if not candidate_text.strip():
        raise RuntimeError("Gemini API returned empty text. No headings could be detected.")

    roots = []
    stack = []
    seen = set()

    for line in candidate_text.splitlines():
        line_strip = line.strip()
        if not line_strip or not (line_strip.startswith('*') or line_strip.startswith('-') or line_strip.startswith('+')):
            continue

        leading_spaces = len(line) - len(line.lstrip())

        title_content = re.sub(r'^[\*\-\+]\s*', '', line_strip).strip()

        match = re.search(r'(.*?)\s*[-\u2013\u2014]\s*(?:Page\s*)?(\d+)\s*$', title_content, re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            page = int(match.group(2))
        else:
            match_fallback = re.search(r'(.*?)\s*(?:Page\s*)?(\d+)\s*$', title_content, re.IGNORECASE)
            if match_fallback:
                title = match_fallback.group(1).strip()
                page = int(match_fallback.group(2))
            else:
                title = title_content
                page = 1

        dedup_key = (title.lower(), page)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        node = BookmarkNode(title, max(0, page - 1))

        while stack and stack[-1][0] >= leading_spaces:
            stack.pop()

        if not stack:
            roots.append(node)
        else:
            parent_node = stack[-1][1]
            parent_node.add_child(node)

        stack.append((leading_spaces, node))

    return roots
