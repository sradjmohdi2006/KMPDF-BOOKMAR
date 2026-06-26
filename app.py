import wx
import os
import re
import sys
import tempfile
import io
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import Fit

# Try importing reportlab for visual TOC generation
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# =========================================================================
# DATA MODEL
# =========================================================================

class BookmarkNode:
    """Represents a single node in the PDF outline tree."""
    def __init__(self, title, page_number, children=None):
        self.title = title
        self.page_number = page_number  # 0-indexed page number
        self.children = children if children is not None else []
        self.parent = None
        
        for child in self.children:
            child.parent = self

    def add_child(self, child):
        child.parent = self
        self.children.append(child)
        return child

    def insert_child(self, index, child):
        child.parent = self
        self.children.insert(index, child)
        return child

    def remove_child(self, child):
        if child in self.children:
            self.children.remove(child)
            child.parent = None
            return True
        return False

    def clone(self):
        new_node = BookmarkNode(self.title, self.page_number)
        for child in self.children:
            new_node.add_child(child.clone())
        return new_node


class PDFOutlineModel:
    """Manages the outline tree structure and modifications."""
    def __init__(self):
        self.roots = []

    def clear(self):
        self.roots = []

    def add_root(self, node):
        node.parent = None
        self.roots.append(node)
        return node

    def insert_root(self, index, node):
        node.parent = None
        self.roots.insert(index, node)
        return node

    def remove_node(self, node):
        """Removes a node from anywhere in the tree."""
        parent, idx = self.find_parent_and_index(node)
        if idx == -1:
            return False
        if parent is None:
            self.roots.remove(node)
        else:
            parent.remove_child(node)
        return True

    def find_parent_and_index(self, node):
        """Returns (parent_node, index). parent_node is None if it's a root node.
        Returns (None, -1) if the node is not found in the tree."""
        if node in self.roots:
            return None, self.roots.index(node)
            
        def search(nodes):
            for parent in nodes:
                if node in parent.children:
                    return parent, parent.children.index(node)
                res = search(parent.children)
                if res[1] != -1:
                    return res
            return None, -1
            
        return search(self.roots)

    def shift_pages(self, offset, start_page=0):
        """Shifts all page numbers >= start_page by offset."""
        def walk(nodes):
            for node in nodes:
                if node.page_number >= start_page:
                    node.page_number = max(0, node.page_number + offset)
                walk(node.children)
        walk(self.roots)

    # --- Tree Reordering Actions ---

    def move_up(self, node):
        """Swaps the node with its predecessor sibling."""
        parent, idx = self.find_parent_and_index(node)
        if idx <= 0:
            return False  # Already at top or not found
            
        siblings = parent.children if parent else self.roots
        siblings[idx], siblings[idx - 1] = siblings[idx - 1], siblings[idx]
        return True

    def move_down(self, node):
        """Swaps the node with its successor sibling."""
        parent, idx = self.find_parent_and_index(node)
        siblings = parent.children if parent else self.roots
        if idx == -1 or idx >= len(siblings) - 1:
            return False  # Already at bottom or not found
            
        siblings[idx], siblings[idx + 1] = siblings[idx + 1], siblings[idx]
        return True

    def promote(self, node):
        """Moves the node one level up in hierarchy (to become parent's sibling)."""
        parent, idx = self.find_parent_and_index(node)
        if parent is None:
            return False  # Already a root node
            
        grandparent, parent_idx = self.find_parent_and_index(parent)
        parent.remove_child(node)
        
        if grandparent is None:
            self.insert_root(parent_idx + 1, node)
        else:
            grandparent.insert_child(parent_idx + 1, node)
        return True

    def demote(self, node):
        """Moves the node inside its predecessor sibling as a child."""
        parent, idx = self.find_parent_and_index(node)
        siblings = parent.children if parent else self.roots
        if idx <= 0:
            return False  # No predecessor sibling to demote into
            
        predecessor = siblings[idx - 1]
        if parent is None:
            self.roots.remove(node)
        else:
            parent.remove_child(node)
            
        predecessor.add_child(node)
        return True


# =========================================================================
# VECTOR ICON GENERATOR & OWNER-DRAWN BUTTON
# =========================================================================

class VectorIconGenerator:
    """Generates crisp vector bitmaps dynamically to support modern themes."""
    @staticmethod
    def create_bitmap(icon_type, color_hex, size=16):
        bmp = wx.Bitmap(size, size, 32)
        bmp.UseAlpha(True)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(0, 0, 0, 0), wx.BRUSHSTYLE_TRANSPARENT))
        dc.Clear()
        
        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            dc.SelectObject(wx.NullBitmap)
            return bmp
            
        color = wx.Colour(color_hex)
        gc.SetPen(gc.CreatePen(wx.Pen(color, 1)))
        gc.SetBrush(gc.CreateBrush(wx.Brush(color)))
        
        if icon_type == "folder":
            path = gc.CreatePath()
            path.MoveToPoint(1, 3)
            path.AddLineToPoint(6, 3)
            path.AddLineToPoint(8, 5)
            path.AddLineToPoint(14, 5)
            path.AddLineToPoint(14, 13)
            path.AddLineToPoint(1, 13)
            path.CloseSubpath()
            gc.DrawPath(path)
        elif icon_type == "page":
            path = gc.CreatePath()
            path.MoveToPoint(3, 1)
            path.AddLineToPoint(10, 1)
            path.AddLineToPoint(13, 4)
            path.AddLineToPoint(13, 15)
            path.AddLineToPoint(3, 15)
            path.CloseSubpath()
            gc.StrokePath(path)
            # Corner fold
            path2 = gc.CreatePath()
            path2.MoveToPoint(10, 1)
            path2.AddLineToPoint(10, 4)
            path2.AddLineToPoint(13, 4)
            gc.StrokePath(path2)
        elif icon_type == "plus":
            gc.SetPen(gc.CreatePen(wx.Pen(color, 2)))
            gc.StrokeLine(8, 2, 8, 14)
            gc.StrokeLine(2, 8, 14, 8)
        elif icon_type == "minus":
            gc.SetPen(gc.CreatePen(wx.Pen(color, 2)))
            gc.StrokeLine(2, 8, 14, 8)
        elif icon_type == "up":
            path = gc.CreatePath()
            path.MoveToPoint(8, 2)
            path.AddLineToPoint(3, 8)
            path.AddLineToPoint(6, 8)
            path.AddLineToPoint(6, 14)
            path.AddLineToPoint(10, 14)
            path.AddLineToPoint(10, 8)
            path.AddLineToPoint(13, 8)
            path.CloseSubpath()
            gc.DrawPath(path)
        elif icon_type == "down":
            path = gc.CreatePath()
            path.MoveToPoint(8, 14)
            path.AddLineToPoint(3, 8)
            path.AddLineToPoint(6, 8)
            path.AddLineToPoint(6, 2)
            path.AddLineToPoint(10, 2)
            path.AddLineToPoint(10, 8)
            path.AddLineToPoint(13, 8)
            path.CloseSubpath()
            gc.DrawPath(path)
        elif icon_type == "left":
            path = gc.CreatePath()
            path.MoveToPoint(2, 8)
            path.AddLineToPoint(8, 3)
            path.AddLineToPoint(8, 6)
            path.AddLineToPoint(14, 6)
            path.AddLineToPoint(14, 10)
            path.AddLineToPoint(8, 10)
            path.AddLineToPoint(8, 13)
            path.CloseSubpath()
            gc.DrawPath(path)
        elif icon_type == "right":
            path = gc.CreatePath()
            path.MoveToPoint(14, 8)
            path.AddLineToPoint(8, 3)
            path.AddLineToPoint(8, 6)
            path.AddLineToPoint(2, 6)
            path.AddLineToPoint(2, 10)
            path.AddLineToPoint(8, 10)
            path.AddLineToPoint(8, 13)
            path.CloseSubpath()
            gc.DrawPath(path)
        elif icon_type == "theme":
            # Half-filled circle (sun/moon metaphor)
            gc.SetPen(gc.CreatePen(wx.Pen(color, 1)))
            gc.SetBrush(gc.CreateBrush(wx.Brush(color)))
            # Draw semi-circle filled, other side outline
            path = gc.CreatePath()
            path.AddArc(8, 8, 6, 1.57, 4.71, False) # Left half
            path.CloseSubpath()
            gc.DrawPath(path)
            # Draw right outline half
            path2 = gc.CreatePath()
            path2.AddArc(8, 8, 6, 4.71, 1.57, False)
            gc.StrokePath(path2)
            
        dc.SelectObject(wx.NullBitmap)
        return bmp


class ModernButton(wx.Button):
    """ModernButton subclassing wx.Button for full screen reader (NVDA) accessibility."""
    def __init__(self, parent, id=wx.ID_ANY, label="", pos=wx.DefaultPosition, size=wx.DefaultSize, 
                 variant="secondary", icon_type=None, name="ModernButton"):
        super().__init__(parent, id, label, pos, size, name=name)
        self.variant = variant
        self.icon_type = icon_type
        
        # Accessibility settings
        self.SetToolTip(label)
        self.SetName(label)
        self.SetHelpText(label)

    def SetThemeColors(self, primary, bg, text, border):
        if self.variant == "primary":
            self.SetBackgroundColour(wx.Colour(primary))
            self.SetForegroundColour(wx.Colour("#FFFFFF"))
        elif self.variant == "danger":
            self.SetBackgroundColour(wx.Colour("#FCE8E6"))
            self.SetForegroundColour(wx.Colour("#D93025"))
        else:
            self.SetBackgroundColour(wx.Colour(bg))
            self.SetForegroundColour(wx.Colour(text))
            
        if self.icon_type:
            color = self.GetForegroundColour().GetAsString(wx.C2S_HTML_SYNTAX)
            bmp = VectorIconGenerator.create_bitmap(self.icon_type, color, 16)
            self.SetBitmap(bmp)
            self.SetBitmapPosition(wx.LEFT)


# =========================================================================
# PDF & TOC GENERATION LOGIC
# =========================================================================

def read_pdf_outlines(file_path):
    """Loads outline list from PDF, parsing it recursively into BookmarkNodes."""
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
                # Strip null bytes and normalize spacing
                if isinstance(title, bytes):
                    title = title.decode("utf-8", errors="ignore")
                title = str(title).replace("\x00", "").strip()
                
                node = BookmarkNode(title, page_num)
                nodes.append(node)
                last_node = node
        return nodes

    return parse_outline_list(outline) if outline else [], len(reader.pages)


def save_outlines_to_writer(writer, nodes, parent=None):
    """Writes bookmark hierarchy recursively into PdfWriter outline structure."""
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
    """Saves PDF copying original pages and writing the new outline tree."""
    with open(input_path, "rb") as f:
        input_bytes = f.read()
    reader = PdfReader(io.BytesIO(input_bytes))
    writer = PdfWriter()
    
    # Copy pages
    for page in reader.pages:
        writer.add_page(page)
        
    save_outlines_to_writer(writer, model.roots)
    writer.page_mode = "/UseOutlines"
    
    # Write atomically using a temporary file in the same directory
    temp_dir = os.path.dirname(output_path)
    temp_fd, temp_path = tempfile.mkstemp(dir=temp_dir, suffix=".pdf")
    try:
        with os.fdopen(temp_fd, "wb") as f:
            writer.write(f)
        if os.path.exists(output_path):
            os.remove(output_path)
        os.rename(temp_path, output_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise e


def generate_and_insert_toc(input_pdf_path, output_pdf_path, model, config):
    """Generates a custom Table of Contents PDF page, inserts it, and offsets bookmarks."""
    if not HAS_REPORTLAB:
        raise ImportError("ReportLab is not installed.")
        
    # 1. Flatten bookmark tree to list of (title, original_page, level)
    flat_list = []
    def flatten(nodes_list, level=0):
        for node in nodes_list:
            flat_list.append((node.title, node.page_number, level))
            flatten(node.children, level + 1)
    flatten(model.roots)
    
    if not flat_list:
        raise ValueError("Outline tree is empty. Add bookmarks before generating a TOC.")

    # 2. Configure sizes and compute page counts
    margin = config.get("margins", 54)
    line_height = config.get("line_height", 22)
    font_name = config.get("font_name", "Helvetica")
    title_text = config.get("title", "Table of Contents")
    dot_char = config.get("dot_leader", ".")
    auto_shift = config.get("auto_shift", True)
    insert_pos = config.get("page_offset", 0)  # 0-indexed position
    theme_hex = config.get("theme_color", "#1A73E8")

    width, height = letter
    y_start = height - 100
    y_min = margin + 50
    items_per_page = int((y_start - y_min) / line_height)
    
    num_toc_pages = (len(flat_list) + items_per_page - 1) // items_per_page
    
    # 3. Write TOC PDF to temporary file
    temp_toc_file = tempfile.mktemp(suffix=".pdf")
    c = canvas.Canvas(temp_toc_file, pagesize=letter)
    theme_color = HexColor(theme_hex)
    
    def draw_toc_header(canvas_obj, p_num):
        # Premium top bar accent
        canvas_obj.setFillColor(theme_color)
        canvas_obj.rect(0, height - 8, width, 8, fill=1, stroke=0)
        
        # TOC Header
        canvas_obj.setFont(f"{font_name}-Bold", 24)
        canvas_obj.setFillColor(theme_color)
        canvas_obj.drawString(margin, height - 54, title_text)
        
        # Divider Line
        canvas_obj.setStrokeColor(theme_color)
        canvas_obj.setLineWidth(1.5)
        canvas_obj.line(margin, height - 62, width - margin, height - 62)
        
        # Footer page numbers
        canvas_obj.setFont(font_name, 9)
        canvas_obj.setFillColor(HexColor("#888888"))
        canvas_obj.drawRightString(width - margin, 36, f"Page {p_num} of {num_toc_pages}")

    y = y_start
    current_toc_page = 1
    draw_toc_header(c, current_toc_page)
    
    # Track annotations to draw later: list of (toc_page_0indexed, rect, target_page_index)
    link_rects = []
    
    for title, original_target, level in flat_list:
        if y < y_min:
            c.showPage()
            current_toc_page += 1
            y = y_start
            draw_toc_header(c, current_toc_page)
            
        indent = margin + (level * 18)
        
        # Apply page number shift if active
        display_page = original_target
        if auto_shift and original_target >= insert_pos:
            display_page += num_toc_pages
            
        is_root = (level == 0)
        f_size = 11 if is_root else 9.5
        c.setFont(f"{font_name}-Bold" if is_root else font_name, f_size)
        c.setFillColor(HexColor("#111111") if is_root else HexColor("#444444"))
        
        # Draw Title
        c.drawString(indent, y, title)
        title_w = c.stringWidth(title)
        
        # Draw Page
        page_str = str(display_page + 1)
        page_w = c.stringWidth(page_str)
        c.drawRightString(width - margin, y, page_str)
        
        # Draw Dot Leaders
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
            
        # Add clickable rectangular hit area coordinates
        rect = (margin - 5, y - 2, width - margin + 5, y + f_size + 2)
        link_rects.append((current_toc_page - 1, rect, display_page))
        
        y -= line_height
        
    c.save()
    
    # 4. Merge TOC into Original PDF using pypdf
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
        
    # 5. Overlay Clickable Link Annotations on TOC Pages
    for toc_p, rect, target_p in link_rects:
        actual_writer_idx = insert_pos + toc_p
        link_anno = Link(
            rect=rect,
            target_page_index=target_p,
            fit=Fit.fit()
        )
        writer.add_annotation(page_number=actual_writer_idx, annotation=link_anno)
        
    # 6. Shift bookmark values and save tree
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
    
    # Insert Table of Contents itself as the first bookmark pointing to the TOC start page
    toc_bookmark = BookmarkNode(title_text, insert_pos)
    shifted_roots.insert(0, toc_bookmark)
    
    save_outlines_to_writer(writer, shifted_roots)
    writer.page_mode = "/UseOutlines"
    
    # Write atomically using a temporary file in the same directory
    temp_dir = os.path.dirname(output_pdf_path)
    temp_fd, temp_path = tempfile.mkstemp(dir=temp_dir, suffix=".pdf")
    try:
        with os.fdopen(temp_fd, "wb") as f:
            writer.write(f)
        if os.path.exists(output_pdf_path):
            os.remove(output_pdf_path)
        os.rename(temp_path, output_pdf_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise e
        
    # Clean up
    try:
        os.remove(temp_toc_file)
    except Exception:
        pass
        
    return num_toc_pages, shifted_roots


# =========================================================================
# TEXT TOC IMPORT / EXPORT PARSER
# =========================================================================

def parse_text_toc(text):
    """Parses outline strings (Markdown or space-indented) into a BookmarkNode tree."""
    lines = text.splitlines()
    roots = []
    stack = []  # List of (indent_level, node)
    
    for line in lines:
        if not line.strip():
            continue
            
        # Determine indentation level
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        
        # Check if Markdown heading header style: '# Chapter Name'
        md_match = re.match(r'^(#+)\s*(.*)', stripped)
        if md_match:
            # Let Markdown hash count dictate indent (each # equals 4 spaces indent)
            indent = (len(md_match.group(1)) - 1) * 4
            stripped = md_match.group(2).strip()

        # Parse title and page number (expects trailing integer like "Introduction...5" or "Intro - 5")
        # Match a title followed by some separator characters and an ending number
        match = re.search(r'(.*?)\s*[-.@:_]*\s*(\d+)$', stripped)
        if match:
            title = match.group(1).strip()
            # Clean dot leaders or dashes from title end
            title = re.sub(r'[\s\.]+$', '', title).strip()
            page = int(match.group(2))
        else:
            title = stripped
            page = 1  # Default to page 1
            
        node = BookmarkNode(title, max(0, page - 1))
        
        # Re-align stack hierarchy based on indentation
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
    """Exports BookmarkNode tree recursively into clean, readable outline text."""
    lines = []
    for node in nodes:
        indent = "    " * level
        lines.append(f"{indent}{node.title} - {node.page_number + 1}")
        if node.children:
            lines.append(export_toc_to_text(node.children, level + 1))
    return "\n".join(lines)


def auto_detect_bookmarks_heuristics(pdf_path):
    """Scans all pages in the PDF and detects bookmark candidates using heuristics."""
    with open(pdf_path, "rb") as f:
        bytes_data = f.read()
    reader = PdfReader(io.BytesIO(bytes_data))
    detected_nodes = []
    
    # Heuristic regex patterns
    numbered_pattern = re.compile(r'^\s*(\d+(\.\d+)*)\s+([A-Z].*)')
    named_pattern = re.compile(r'^\s*(Chapter|Section|Part|Appendix|Unit)\s+(\w+)\b[:\s]*(.*)', re.IGNORECASE)
    
    # First pass: find frequently occurring header/footer lines to exclude them
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
            
    # Second pass: detect actual headings
    for page_idx, lines in enumerate(pages_text):
        for line in lines:
            if line_counts.get(line, 0) > 2:
                continue
            if line.isdigit():
                continue
                
            m_named = named_pattern.match(line)
            if m_named:
                category = m_named.group(1).title()
                num = m_named.group(2)
                title = m_named.group(3).strip()
                full_title = f"{category} {num}"
                if title:
                    full_title += f": {title}"
                if len(full_title) <= 100:
                    detected_nodes.append(BookmarkNode(full_title, page_idx))
                    continue
                    
            m_numbered = numbered_pattern.match(line)
            if m_numbered:
                num = m_numbered.group(1)
                title = m_numbered.group(3).strip()
                full_title = f"{num} {title}"
                if len(title) > 2 and len(full_title) <= 100:
                    detected_nodes.append(BookmarkNode(full_title, page_idx))
                    continue
                    
            if line.isupper() and 4 <= len(line) <= 60 and not re.match(r'^[^a-zA-Z]+$', line):
                detected_nodes.append(BookmarkNode(line.title(), page_idx))
                continue
                
    # Build a simple hierarchy
    roots = []
    stack = []
    
    def get_level(title):
        m = re.match(r'^\s*(\d+(\.\d+)*)', title)
        if m:
            parts = m.group(1).split('.')
            return len(parts)
        if title.lower().startswith('chapter'):
            return 1
        if title.lower().startswith('section'):
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
    """Scans all pages in the PDF and detects bookmark candidates using semantic scoring."""
    with open(pdf_path, "rb") as f:
        bytes_data = f.read()
    reader = PdfReader(io.BytesIO(bytes_data))
    detected_nodes = []
    
    # Semantic keywords typically found in headings
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
            
    for page_idx, lines in enumerate(pages_text):
        for line in lines:
            if line_counts.get(line, 0) > 2:
                continue
            if line.isdigit() or len(line) < 3 or len(line) > 80:
                continue
                
            score = 0
            
            # Penalize end-of-sentence punctuation
            if line[-1] in ['.', '?', '!', ';', ',']:
                score -= 3
                
            # Formatting indicators
            if line.isupper():
                score += 3
            elif line.istitle():
                score += 2
                
            # Numbered start
            if re.match(r'^\s*(\d+|[IVXLCDM]+|[A-Z])\s*[\.\-\:]', line, re.IGNORECASE):
                score += 4
                
            # Semantic keyword match
            words = set(re.findall(r'\b\w+\b', line.lower()))
            if words.intersection(semantic_keywords):
                score += 5
                
            if len(line) < 40:
                score += 1
                
            if score >= 3:
                detected_nodes.append(BookmarkNode(line, page_idx))
                
    # Build simple hierarchy
    roots = []
    stack = []
    
    def get_level(title):
        m = re.match(r'^\s*(\d+(\.\d+)*)', title)
        if m:
            parts = m.group(1).split('.')
            return len(parts)
        if title.lower().startswith('chapter'):
            return 1
        if title.lower().startswith('section'):
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


# =========================================================================
# MAIN APPLICATION WINDOW
# =========================================================================

# Themes Colors Definition
THEMES = {
    "light": {
        "bg": "#F8F9FA",
        "panel": "#FFFFFF",
        "sidebar": "#F1F3F5",
        "text": "#212529",
        "subtext": "#6C757D",
        "border": "#DEE2E6",
        "primary": "#1A73E8",
        "button_bg": "#E8F0FE",
        "button_text": "#1A73E8",
        "tree_bg": "#FFFFFF",
        "input_bg": "#FFFFFF",
    },
    "dark": {
        "bg": "#121212",
        "panel": "#1E1E1E",
        "sidebar": "#1A1A1A",
        "text": "#E0E0E0",
        "subtext": "#9E9E9E",
        "border": "#2C2C2C",
        "primary": "#66B2FF",
        "button_bg": "#2C2C2C",
        "button_text": "#66B2FF",
        "tree_bg": "#1E1E1E",
        "input_bg": "#2A2A2A",
    }
}

class PDFEditorFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Sleek PDF Outline & TOC Editor", size=(1000, 700))
        
        self.model = PDFOutlineModel()
        self.current_theme = "light"
        self.pdf_path = None
        self.pdf_filename = None
        self.total_pages = 0
        
        self.InitUI()
        self.ApplyTheme(self.current_theme)
        
    def InitUI(self):
        # Create Status Bar
        self.statusbar = self.CreateStatusBar()
        self.statusbar.SetStatusText("Ready. Open a PDF to begin.")
        
        # Menu Bar
        menu_bar = wx.MenuBar()
        
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, "&Open PDF...\tCtrl+O", "Open a PDF file to edit outlines")
        self.save_item = file_menu.Append(wx.ID_SAVE, "&Save PDF\tCtrl+S", "Save changes to current PDF")
        self.save_as_item = file_menu.Append(wx.ID_SAVEAS, "Save PDF &As...\tCtrl+Shift+S", "Save changes to new PDF")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit", "Close the app")
        
        theme_menu = wx.Menu()
        toggle_theme_item = theme_menu.Append(wx.ID_ANY, "&Toggle Light/Dark Mode\tCtrl+T", "Switch app aesthetic theme")
        
        menu_bar.Append(file_menu, "&File")
        menu_bar.Append(theme_menu, "&Theme")
        self.SetMenuBar(menu_bar)
        
        # Bind Menu Events
        self.Bind(wx.EVT_MENU, self.OnOpenPDF, open_item)
        self.Bind(wx.EVT_MENU, self.OnSavePDF, self.save_item)
        self.Bind(wx.EVT_MENU, self.OnSavePDFAs, self.save_as_item)
        self.Bind(wx.EVT_MENU, self.OnClose, exit_item)
        self.Bind(wx.EVT_MENU, self.OnToggleTheme, toggle_theme_item)
        
        # Main Layout using splitter window
        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)
        
        # Left Panel (Tree Outline)
        self.left_panel = wx.Panel(self.splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Tree header/label
        tree_label = wx.StaticText(self.left_panel, label="&PDF Outline bookmarks:")
        font_header = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        # Provide a tooltip for screen readers
        tree_label.SetToolTip("PDF Outline bookmarks")
        tree_label.SetFont(font_header)
        left_sizer.Add(tree_label, 0, wx.ALL, 10)
        
        # Custom TreeCtrl
        self.tree = wx.TreeCtrl(self.left_panel, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_DEFAULT_STYLE)
        self.tree.SetHelpText("PDF Outline bookmarks tree. Use arrow keys to navigate, Enter to select.")
        self.tree.SetName("PDFOutlineTree")

        left_sizer.Add(self.tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.left_panel.SetSizer(left_sizer)
        
        # Setup Icons for Tree
        self.tree_image_list = wx.ImageList(16, 16)
        # We will populate these dynamically when applying theme
        self.icon_pdf_idx = -1
        self.icon_folder_idx = -1
        self.icon_page_idx = -1
        self.tree.SetImageList(self.tree_image_list)
        
        # Right Panel (Settings notebook)
        self.right_panel = wx.Panel(self.splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.notebook = wx.Notebook(self.right_panel)
        
        # -- TAB 1: FILE INFO --
        self.tab_info = wx.Panel(self.notebook)
        info_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.info_title = wx.StaticText(self.tab_info, label="No PDF file loaded.")
        self.info_title.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        info_sizer.Add(self.info_title, 0, wx.ALL, 15)
        
        self.info_details = wx.StaticText(self.tab_info, label="Please select a PDF document to start editing outlines, importing bookmarks, or generating Tables of Contents.")
        self.info_details.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.info_details.Wrap(350)
        info_sizer.Add(self.info_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 15)
        
        # Quick Actions
        action_box = wx.StaticBox(self.tab_info, label="Quick PDF Actions")
        action_sizer = wx.StaticBoxSizer(action_box, wx.VERTICAL)
        
        self.btn_clear_bookmarks = ModernButton(self.tab_info, label="Delete All Bookmarks", variant="danger", icon_type="minus")
        self.btn_save_quick = ModernButton(self.tab_info, label="Save Changes", variant="primary", icon_type="save")
        
        action_sizer.Add(self.btn_clear_bookmarks, 0, wx.EXPAND | wx.ALL, 6)
        action_sizer.Add(self.btn_save_quick, 0, wx.EXPAND | wx.ALL, 6)
        info_sizer.Add(action_sizer, 0, wx.EXPAND | wx.ALL, 15)
        
        self.tab_info.SetSizer(info_sizer)
        
        # -- TAB 2: EDIT OUTLINE --
        self.tab_edit = wx.Panel(self.notebook)
        edit_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Edit Selected Bookmark Section
        edit_sel_box = wx.StaticBox(self.tab_edit, label="Edit Selected Bookmark")
        edit_sel_sizer = wx.StaticBoxSizer(edit_sel_box, wx.VERTICAL)
        
        # Row 1: Title input
        row_title = wx.BoxSizer(wx.HORIZONTAL)
        lbl_title = wx.StaticText(self.tab_edit, label="&Title:", size=(80, -1))
        # Tooltip for screen readers
        lbl_title.SetToolTip("Bookmark title input")
        self.txt_edit_title = wx.TextCtrl(self.tab_edit)
        self.txt_edit_title.SetHelpText("Enter bookmark title")
        self.txt_edit_title.SetName("EditTitleInput")
        row_title.Add(lbl_title, 0, wx.ALIGN_CENTER_VERTICAL)
        row_title.Add(self.txt_edit_title, 1, wx.EXPAND)
        # Associate the label with the text control for accessibility
        self.txt_edit_title.SetLabel("Title input")
        edit_sel_sizer.Add(row_title, 0, wx.EXPAND | wx.ALL, 5)
        
        # Row 2: Page input
        row_page = wx.BoxSizer(wx.HORIZONTAL)
        lbl_page = wx.StaticText(self.tab_edit, label="&Page Target:", size=(80, -1))
        lbl_page.SetToolTip("Target page number for the bookmark")
        self.spin_edit_page = wx.SpinCtrl(self.tab_edit, min=1, max=99999, initial=1)
        self.spin_edit_page.SetHelpText("Enter target page number")
        self.spin_edit_page.SetName("EditPageInput")
        row_page.Add(lbl_page, 0, wx.ALIGN_CENTER_VERTICAL)
        row_page.Add(self.spin_edit_page, 1, wx.EXPAND)
        self.spin_edit_page.SetLabel("Page target input")
        edit_sel_sizer.Add(row_page, 0, wx.EXPAND | wx.ALL, 5)
        
        # Edit action buttons
        edit_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_update_node = ModernButton(self.tab_edit, label="Apply Edit", variant="secondary")
        self.btn_delete_node = ModernButton(self.tab_edit, label="Delete Bookmark", variant="danger", icon_type="minus")
        edit_btn_sizer.Add(self.btn_update_node, 1, wx.EXPAND | wx.RIGHT, 5)
        edit_btn_sizer.Add(self.btn_delete_node, 1, wx.EXPAND | wx.LEFT, 5)
        edit_sel_sizer.Add(edit_btn_sizer, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 10)
        
        edit_sizer.Add(edit_sel_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Reordering Section
        reorder_box = wx.StaticBox(self.tab_edit, label="Reorder / Structure")
        reorder_sizer = wx.StaticBoxSizer(reorder_box, wx.VERTICAL)
        
        reorder_row1 = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_move_up = ModernButton(self.tab_edit, label="Move Up", variant="secondary", icon_type="up")
        self.btn_move_down = ModernButton(self.tab_edit, label="Move Down", variant="secondary", icon_type="down")
        reorder_row1.Add(self.btn_move_up, 1, wx.EXPAND | wx.RIGHT, 5)
        reorder_row1.Add(self.btn_move_down, 1, wx.EXPAND | wx.LEFT, 5)
        
        reorder_row2 = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_promote = ModernButton(self.tab_edit, label="Promote Out", variant="secondary", icon_type="left")
        self.btn_demote = ModernButton(self.tab_edit, label="Demote In", variant="secondary", icon_type="right")
        reorder_row2.Add(self.btn_promote, 1, wx.EXPAND | wx.RIGHT, 5)
        reorder_row2.Add(self.btn_demote, 1, wx.EXPAND | wx.LEFT, 5)
        
        reorder_sizer.Add(reorder_row1, 0, wx.EXPAND | wx.BOTTOM, 6)
        reorder_sizer.Add(reorder_row2, 0, wx.EXPAND, 0)
        
        edit_sizer.Add(reorder_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Add New Bookmark Section
        add_box = wx.StaticBox(self.tab_edit, label="Add New Bookmark")
        add_sizer = wx.StaticBoxSizer(add_box, wx.VERTICAL)
        
        # Row 1: Add Title
        add_row_title = wx.BoxSizer(wx.HORIZONTAL)
        lbl_add_title = wx.StaticText(self.tab_edit, label="&Title:", size=(80, -1))
        lbl_add_title.SetToolTip("Title for new bookmark")
        self.txt_add_title = wx.TextCtrl(self.tab_edit)
        self.txt_add_title.SetHelpText("Enter new bookmark title")
        self.txt_add_title.SetName("AddTitleInput")
        add_row_title.Add(lbl_add_title, 0, wx.ALIGN_CENTER_VERTICAL)
        add_row_title.Add(self.txt_add_title, 1, wx.EXPAND)
        self.txt_add_title.SetLabel("New bookmark title")
        add_sizer.Add(add_row_title, 0, wx.EXPAND | wx.ALL, 5)
        
        # Row 2: Add Page
        add_row_page = wx.BoxSizer(wx.HORIZONTAL)
        lbl_add_page = wx.StaticText(self.tab_edit, label="&Page Target:", size=(80, -1))
        lbl_add_page.SetToolTip("Target page for new bookmark")
        self.spin_add_page = wx.SpinCtrl(self.tab_edit, min=1, max=99999, initial=1)
        self.spin_add_page.SetHelpText("Enter new bookmark target page")
        self.spin_add_page.SetName("AddPageInput")
        add_row_page.Add(lbl_add_page, 0, wx.ALIGN_CENTER_VERTICAL)
        add_row_page.Add(self.spin_add_page, 1, wx.EXPAND)
        self.spin_add_page.SetLabel("New bookmark page")
        add_sizer.Add(add_row_page, 0, wx.EXPAND | wx.ALL, 5)
        
        # Row 3: Add Position Radio box
        self.radio_position = wx.RadioBox(self.tab_edit, label="Position", 
                                          choices=["As Child", "Sibling Before", "Sibling After", "As Root End"],
                                          majorDimension=2, style=wx.RA_SPECIFY_COLS)
        add_sizer.Add(self.radio_position, 0, wx.EXPAND | wx.ALL, 5)
        
        self.btn_add_node = ModernButton(self.tab_edit, label="Add Bookmark Item", variant="primary", icon_type="plus")
        add_sizer.Add(self.btn_add_node, 0, wx.EXPAND | wx.ALL, 5)
        
        edit_sizer.Add(add_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Page shift tool
        shift_box = wx.StaticBox(self.tab_edit, label="Shift Page Numbers")
        shift_sizer = wx.StaticBoxSizer(shift_box, wx.HORIZONTAL)
        lbl_shift = wx.StaticText(self.tab_edit, label="Offset:")
        self.spin_shift_offset = wx.SpinCtrl(self.tab_edit, min=-9999, max=9999, initial=1)
        self.btn_shift = ModernButton(self.tab_edit, label="Shift All", variant="secondary")
        shift_sizer.Add(lbl_shift, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        shift_sizer.Add(self.spin_shift_offset, 1, wx.EXPAND | wx.RIGHT, 10)
        shift_sizer.Add(self.btn_shift, 1, wx.EXPAND)
        
        edit_sizer.Add(shift_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        self.tab_edit.SetSizer(edit_sizer)
        
        # -- TAB 3: TEXT IMPORT/EXPORT --
        self.tab_text = wx.Panel(self.notebook)
        text_sizer = wx.BoxSizer(wx.VERTICAL)
        
        text_desc = wx.StaticText(self.tab_text, label="Paste TOC outline lines here. Format: 'Title - Page' or indent lines to create nested bookmarks. Supports Markdown '#' header titles too.")
        text_desc.Wrap(380)
        text_sizer.Add(text_desc, 0, wx.ALL, 10)
        
        self.txt_toc_bulk = wx.TextCtrl(self.tab_text, style=wx.TE_MULTILINE | wx.TE_DONTWRAP)
        text_sizer.Add(self.txt_toc_bulk, 1, wx.EXPAND | wx.ALL, 10)
        
        btn_text_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_import_text = ModernButton(self.tab_text, label="Import Text TOC", variant="primary")
        self.btn_export_text = ModernButton(self.tab_text, label="Export Bookmarks", variant="secondary")
        btn_text_sizer.Add(self.btn_import_text, 1, wx.EXPAND | wx.RIGHT, 5)
        btn_text_sizer.Add(self.btn_export_text, 1, wx.EXPAND | wx.LEFT, 5)
        text_sizer.Add(btn_text_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        
        self.tab_text.SetSizer(text_sizer)
        
        # -- TAB 4: GENERATE TOC PAGE --
        self.tab_gen_toc = wx.Panel(self.notebook)
        gen_sizer = wx.BoxSizer(wx.VERTICAL)
        
        gen_desc = wx.StaticText(self.tab_gen_toc, label="This creates a Table of Contents PDF page from current bookmarks and merges it directly at the start of your document with clickable page hyperlinks.")
        gen_desc.Wrap(380)
        gen_sizer.Add(gen_desc, 0, wx.ALL, 10)
        
        # Parameters Static Box
        params_box = wx.StaticBox(self.tab_gen_toc, label="TOC Layout & Page Styles")
        params_sizer = wx.StaticBoxSizer(params_box, wx.VERTICAL)
        
        # 1. TOC Title
        t_row = wx.BoxSizer(wx.HORIZONTAL)
        t_lbl = wx.StaticText(self.tab_gen_toc, label="TOC Title:", size=(100, -1))
        self.txt_toc_title = wx.TextCtrl(self.tab_gen_toc)
        self.txt_toc_title.SetValue("Table of Contents")
        t_row.Add(t_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        t_row.Add(self.txt_toc_title, 1, wx.EXPAND)
        params_sizer.Add(t_row, 0, wx.EXPAND | wx.ALL, 4)
        
        # 2. Font Style
        f_row = wx.BoxSizer(wx.HORIZONTAL)
        f_lbl = wx.StaticText(self.tab_gen_toc, label="Font Style:", size=(100, -1))
        self.choice_font = wx.Choice(self.tab_gen_toc, choices=["Helvetica", "Times-Roman", "Courier"])
        self.choice_font.SetSelection(0)
        f_row.Add(f_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        f_row.Add(self.choice_font, 1, wx.EXPAND)
        params_sizer.Add(f_row, 0, wx.EXPAND | wx.ALL, 4)
        
        # 3. Theme Color Selection
        c_row = wx.BoxSizer(wx.HORIZONTAL)
        c_lbl = wx.StaticText(self.tab_gen_toc, label="Theme Accent:", size=(100, -1))
        self.choice_color = wx.Choice(self.tab_gen_toc, choices=["Google Blue", "Teal Emerald", "Deep Charcoal", "Crimson Red", "Royal Purple"])
        self.choice_color.SetSelection(0)
        self.color_map = {
            0: "#1A73E8",  # Blue
            1: "#0F9D58",  # Teal
            2: "#37474F",  # Charcoal
            3: "#D93025",  # Crimson
            4: "#673AB7",  # Purple
        }
        c_row.Add(c_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        c_row.Add(self.choice_color, 1, wx.EXPAND)
        params_sizer.Add(c_row, 0, wx.EXPAND | wx.ALL, 4)
        
        # 4. Dot Leaders choice
        d_row = wx.BoxSizer(wx.HORIZONTAL)
        d_lbl = wx.StaticText(self.tab_gen_toc, label="Dot Leader:", size=(100, -1))
        self.choice_dots = wx.Choice(self.tab_gen_toc, choices=["Dots (. . .)", "Dashes (- - -)", "None"])
        self.choice_dots.SetSelection(0)
        self.dots_map = {0: ".", 1: "-", 2: ""}
        d_row.Add(d_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        d_row.Add(self.choice_dots, 1, wx.EXPAND)
        params_sizer.Add(d_row, 0, wx.EXPAND | wx.ALL, 4)
        
        # 5. Options: Auto-Shift, Add bookmark
        self.chk_auto_shift = wx.CheckBox(self.tab_gen_toc, label="Auto-Shift original bookmark page numbers (+k pages)")
        self.chk_auto_shift.SetValue(True)
        params_sizer.Add(self.chk_auto_shift, 0, wx.EXPAND | wx.ALL, 6)
        
        gen_sizer.Add(params_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        self.btn_gen_toc_page = ModernButton(self.tab_gen_toc, label="Generate & Insert TOC", variant="primary")
        gen_sizer.Add(self.btn_gen_toc_page, 0, wx.EXPAND | wx.ALL, 10)
        
        if not HAS_REPORTLAB:
            self.btn_gen_toc_page.Disable()
            warn_lbl = wx.StaticText(self.tab_gen_toc, label="WARNING: ReportLab library not found. Install it to enable physical Table of Contents generation.")
            warn_lbl.SetForegroundColour(wx.Colour("#D93025"))
            warn_lbl.Wrap(380)
            gen_sizer.Add(warn_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
            
        self.tab_gen_toc.SetSizer(gen_sizer)
        
        # -- TAB 5: AUTO-DETECT BOOKMARKS --
        self.tab_auto_detect = wx.Panel(self.notebook)
        auto_detect_sizer = wx.BoxSizer(wx.VERTICAL)
        
        ad_desc = wx.StaticText(self.tab_auto_detect, label="Automatically discover bookmarks based on headings, numbering structures, and formatting styles across all pages.")
        ad_desc.Wrap(380)
        auto_detect_sizer.Add(ad_desc, 0, wx.ALL, 15)
        
        # Detection Mode Selector
        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_mode = wx.StaticText(self.tab_auto_detect, label="Detection Mode:")
        self.combo_mode = wx.Choice(self.tab_auto_detect, choices=["Heuristics (Pattern-based)", "Semantic (Structure & Keyword)"])
        self.combo_mode.SetSelection(0)
        mode_row.Add(lbl_mode, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        mode_row.Add(self.combo_mode, 1, wx.EXPAND)
        auto_detect_sizer.Add(mode_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 15)
        
        self.btn_run_auto_detect = ModernButton(self.tab_auto_detect, label="Run Auto-Detection", variant="primary", icon_type="plus")
        auto_detect_sizer.Add(self.btn_run_auto_detect, 0, wx.EXPAND | wx.ALL, 15)
        
        self.tab_auto_detect.SetSizer(auto_detect_sizer)
        
        # Add Tabs to Notebook
        self.notebook.AddPage(self.tab_info, "Info")
        self.notebook.AddPage(self.tab_edit, "Edit Bookmarks")
        self.notebook.AddPage(self.tab_text, "Import / Export")
        self.notebook.AddPage(self.tab_gen_toc, "Generate TOC Page")
        self.notebook.AddPage(self.tab_auto_detect, "Auto-Detect")
        
        right_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        self.right_panel.SetSizer(right_sizer)
        
        # Splitter Layout settings
        self.splitter.SplitVertically(self.left_panel, self.right_panel, 350)
        self.splitter.SetMinimumPaneSize(200)
        
        # Event Bindings for Notebook Action buttons
        self.Bind(wx.EVT_TREE_SEL_CHANGED, self.OnTreeSelectionChanged, self.tree)
        self.btn_clear_bookmarks.Bind(wx.EVT_BUTTON, self.OnClearAllBookmarks)
        self.btn_save_quick.Bind(wx.EVT_BUTTON, self.OnSavePDF)
        self.btn_update_node.Bind(wx.EVT_BUTTON, self.OnUpdateSelectedNode)
        self.btn_delete_node.Bind(wx.EVT_BUTTON, self.OnDeleteSelectedNode)
        
        self.btn_move_up.Bind(wx.EVT_BUTTON, self.OnMoveUp)
        self.btn_move_down.Bind(wx.EVT_BUTTON, self.OnMoveDown)
        self.btn_promote.Bind(wx.EVT_BUTTON, self.OnPromote)
        self.btn_demote.Bind(wx.EVT_BUTTON, self.OnDemote)
        
        self.btn_add_node.Bind(wx.EVT_BUTTON, self.OnAddNode)
        self.btn_shift.Bind(wx.EVT_BUTTON, self.OnShiftPages)
        self.btn_import_text.Bind(wx.EVT_BUTTON, self.OnImportTextTOC)
        self.btn_export_text.Bind(wx.EVT_BUTTON, self.OnExportTextTOC)
        self.btn_gen_toc_page.Bind(wx.EVT_BUTTON, self.OnGenerateTOCPage)
        self.btn_run_auto_detect.Bind(wx.EVT_BUTTON, self.OnRunAutoDetect)

    # =========================================================================
    # THEME SWAP
# =========================================================================

    def OnToggleTheme(self, event):
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self.ApplyTheme(self.current_theme)

    def ApplyTheme(self, theme_name):
        colors = THEMES[theme_name]
        
        # Update dynamically generated icon bitmaps in ImageList
        self.tree_image_list.RemoveAll()
        self.icon_pdf_idx = self.tree_image_list.Add(VectorIconGenerator.create_bitmap("pdf", colors["primary"], 16))
        self.icon_folder_idx = self.tree_image_list.Add(VectorIconGenerator.create_bitmap("folder", colors["primary"], 16))
        self.icon_page_idx = self.tree_image_list.Add(VectorIconGenerator.create_bitmap("page", colors["text"], 16))
        
        # Redraw current tree with updated icons
        self.RebuildTreeCtrl()
        
        # Apply theme colors recursively to all widgets
        self.ApplyThemeToWindow(self, colors)
        self.Refresh()

    def ApplyThemeToWindow(self, win, colors):
        # Basic background/foreground colors
        win.SetBackgroundColour(wx.Colour(colors["bg"]))
        win.SetForegroundColour(wx.Colour(colors["text"]))
        
        # Control-specific adjustments
        if isinstance(win, wx.TreeCtrl):
            win.SetBackgroundColour(wx.Colour(colors["tree_bg"]))
            win.SetForegroundColour(wx.Colour(colors["text"]))
            # wxPython tree control requires a redraw
            win.Refresh()
        elif isinstance(win, wx.TextCtrl):
            win.SetBackgroundColour(wx.Colour(colors["input_bg"]))
            win.SetForegroundColour(wx.Colour(colors["text"]))
        elif isinstance(win, ModernButton):
            win.SetThemeColors(
                primary=colors["primary"],
                bg=colors["button_bg"],
                text=colors["button_text"],
                border=colors["border"]
            )
        elif isinstance(win, wx.Notebook):
            win.SetBackgroundColour(wx.Colour(colors["bg"]))
            
        # Recursive pass to children
        for child in win.GetChildren():
            self.ApplyThemeToWindow(child, colors)

    # =========================================================================
    # CONTROLLER LOGIC
    # =========================================================================

    def RebuildTreeCtrl(self):
        """Re-draws the entire TreeCtrl from the data model roots."""
        self.tree.DeleteAllItems()
        
        root_label = self.pdf_filename if self.pdf_filename else "No PDF Loaded"
        self.tree_root = self.tree.AddRoot(root_label, image=self.icon_pdf_idx)
        
        def add_to_tree(tree_parent, model_nodes):
            for node in model_nodes:
                has_children = len(node.children) > 0
                img = self.icon_folder_idx if has_children else self.icon_page_idx
                label = f"[Page {node.page_number + 1}] {node.title}"
                item = self.tree.AppendItem(tree_parent, label, image=img, data=node)
                
                if has_children:
                    add_to_tree(item, node.children)
                    self.tree.Expand(item)
                    
        add_to_tree(self.tree_root, self.model.roots)
        # Note: Do not call self.tree.Expand(self.tree_root) because the root is hidden (wx.TR_HIDE_ROOT)
        # and expanding a hidden root is invalid and crashes on Windows.

    def GetTreeState(self):
        """Saves expanded states and selected node reference."""
        expanded_nodes = set()
        selected_node = self.GetSelectedNode()
        
        def traverse(item):
            if not item.IsOk():
                return
            node = self.tree.GetItemData(item)
            if node and self.tree.IsExpanded(item):
                expanded_nodes.add(node)
            child, cookie = self.tree.GetFirstChild(item)
            while child.IsOk():
                traverse(child)
                child, cookie = self.tree.GetNextChild(item, cookie)
                
        if hasattr(self, 'tree_root') and self.tree_root.IsOk():
            traverse(self.tree_root)
        return expanded_nodes, selected_node

    def RestoreTreeState(self, state):
        """Restores expanded states and selects the node."""
        expanded_nodes, selected_node = state
        
        def traverse(item):
            if not item.IsOk():
                return
            node = self.tree.GetItemData(item)
            if node:
                if node in expanded_nodes:
                    self.tree.Expand(item)
                if node == selected_node:
                    self.tree.SelectItem(item)
            child, cookie = self.tree.GetFirstChild(item)
            while child.IsOk():
                traverse(child)
                child, cookie = self.tree.GetNextChild(item, cookie)
                
        if hasattr(self, 'tree_root') and self.tree_root.IsOk():
            traverse(self.tree_root)

    def RebuildAndSyncTree(self):
        """Rebuilds the tree and synchronizes selection and expansion states."""
        state = self.GetTreeState()
        self.RebuildTreeCtrl()
        self.RestoreTreeState(state)

    def UpdateDetails(self):
        """Refreshes PDF properties and title information."""
        if self.pdf_path:
            size_kb = os.path.getsize(self.pdf_path) / 1024
            self.info_title.SetLabel(self.pdf_filename)
            self.info_details.SetLabel(
                f"File Path: {self.pdf_path}\n"
                f"Total Pages: {self.total_pages}\n"
                f"File Size: {size_kb:.1f} KB\n\n"
                f"Use the Edit panel to manage bookmarks individually, "
                f"or Import/Export bulk text TOC files."
            )
            # Adjust spin controllers page limits
            self.spin_edit_page.SetMax(self.total_pages)
            self.spin_add_page.SetMax(self.total_pages)
        else:
            self.info_title.SetLabel("No PDF file loaded.")
            self.info_details.SetLabel("Please select a PDF document to start editing outlines.")
        
        self.info_details.Wrap(350)
        self.tab_info.Layout()

    def GetSelectedNode(self):
        """Utility to retrieve the BookmarkNode associated with active selection."""
        item = self.tree.GetSelection()
        if not item.IsOk() or item == self.tree_root:
            return None
        return self.tree.GetItemData(item)

    # --- Event Handlers ---

    def OnOpenPDF(self, event):
        wildcard = "PDF Files (*.pdf)|*.pdf"
        dialog = wx.FileDialog(self, "Choose a PDF File", wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        
        if dialog.ShowModal() == wx.ID_OK:
            self.pdf_path = dialog.GetPath()
            self.pdf_filename = os.path.basename(self.pdf_path)
            
            try:
                roots, pages = read_pdf_outlines(self.pdf_path)
                self.model.clear()
                self.model.roots = roots
                self.total_pages = pages
                
                self.RebuildTreeCtrl()
                self.UpdateDetails()
                self.statusbar.SetStatusText(f"Successfully loaded '{self.pdf_filename}' with {len(roots)} root bookmarks.")
            except Exception as e:
                wx.MessageBox(f"Failed to load PDF outlines:\n{str(e)}", "Error", wx.OK | wx.ICON_ERROR)
                
        dialog.Destroy()

    def OnSavePDF(self, event):
        if not self.pdf_path:
            wx.MessageBox("No PDF is currently loaded.", "Warning", wx.OK | wx.ICON_WARNING)
            return
            
        try:
            save_pdf_with_bookmarks(self.pdf_path, self.pdf_path, self.model)
            self.statusbar.SetStatusText("PDF saved successfully.")
            wx.MessageBox("Outline bookmarks saved directly to the PDF!", "Success", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Failed to save PDF bookmarks:\n{str(e)}", "Error", wx.OK | wx.ICON_ERROR)

    def OnSavePDFAs(self, event):
        if not self.pdf_path:
            wx.MessageBox("No PDF is currently loaded.", "Warning", wx.OK | wx.ICON_WARNING)
            return
            
        wildcard = "PDF Files (*.pdf)|*.pdf"
        dialog = wx.FileDialog(self, "Save PDF As", wildcard=wildcard, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        
        if dialog.ShowModal() == wx.ID_OK:
            out_path = dialog.GetPath()
            try:
                save_pdf_with_bookmarks(self.pdf_path, out_path, self.model)
                self.pdf_path = out_path
                self.pdf_filename = os.path.basename(self.pdf_path)
                self.UpdateDetails()
                self.RebuildTreeCtrl()
                
                self.statusbar.SetStatusText(f"Saved copy as '{self.pdf_filename}'")
                wx.MessageBox("PDF copy saved with updated outlines successfully!", "Success", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                wx.MessageBox(f"Failed to save PDF As:\n{str(e)}", "Error", wx.OK | wx.ICON_ERROR)
                
        dialog.Destroy()

    def OnClose(self, event):
        self.Close(True)

    def OnTreeSelectionChanged(self, event):
        node = self.GetSelectedNode()
        if node:
            self.txt_edit_title.SetValue(node.title)
            self.spin_edit_page.SetValue(node.page_number + 1)
        else:
            self.txt_edit_title.SetValue("")
            self.spin_edit_page.SetValue(1)

    def OnClearAllBookmarks(self, event):
        if not self.pdf_path:
            return
        if wx.MessageBox("Are you sure you want to delete all bookmarks from the outline?", 
                         "Confirm Clear", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.model.clear()
            self.RebuildTreeCtrl()
            self.statusbar.SetStatusText("Cleared all outlines from tree.")

    def OnUpdateSelectedNode(self, event):
        node = self.GetSelectedNode()
        if not node:
            wx.MessageBox("Please select a bookmark to edit from the tree.", "Selection Required", wx.OK | wx.ICON_INFORMATION)
            return
            
        new_title = self.txt_edit_title.GetValue().strip()
        new_page = self.spin_edit_page.GetValue() - 1
        
        if not new_title:
            wx.MessageBox("Title cannot be empty.", "Validation Error", wx.OK | wx.ICON_WARNING)
            return
            
        node.title = new_title
        node.page_number = new_page
        
        self.RebuildAndSyncTree()
        self.statusbar.SetStatusText(f"Updated bookmark target to [Page {new_page+1}]: {new_title}")

    def OnDeleteSelectedNode(self, event):
        node = self.GetSelectedNode()
        if not node:
            wx.MessageBox("Please select a bookmark to delete.", "Selection Required", wx.OK | wx.ICON_INFORMATION)
            return
            
        msg = f"Delete bookmark '{node.title}'? This will also remove all its child bookmarks."
        if wx.MessageBox(msg, "Confirm Delete", wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.model.remove_node(node)
            self.RebuildAndSyncTree()
            self.statusbar.SetStatusText("Deleted bookmark node.")

    def OnAddNode(self, event):
        if not self.pdf_path:
            wx.MessageBox("Please load a PDF file first.", "No PDF", wx.OK | wx.ICON_WARNING)
            return
            
        title = self.txt_add_title.GetValue().strip()
        page = self.spin_add_page.GetValue() - 1
        
        if not title:
            wx.MessageBox("Please enter a title for the new bookmark.", "Validation Error", wx.OK | wx.ICON_WARNING)
            return
            
        selected_node = self.GetSelectedNode()
        pos_type = self.radio_position.GetSelection()
        
        new_node = BookmarkNode(title, page)
        
        # Positions: 0 = "As Child", 1 = "Sibling Before", 2 = "Sibling After", 3 = "As Root End"
        if pos_type == 3 or not selected_node:
            self.model.add_root(new_node)
            self.statusbar.SetStatusText(f"Added bookmark '{title}' at root end.")
        else:
            parent, idx = self.model.find_parent_and_index(selected_node)
            if pos_type == 0:  # As Child
                selected_node.add_child(new_node)
                self.statusbar.SetStatusText(f"Added child bookmark '{title}' under '{selected_node.title}'.")
            elif pos_type == 1:  # Sibling Before
                if parent is None:
                    self.model.insert_root(idx, new_node)
                else:
                    parent.insert_child(idx, new_node)
                self.statusbar.SetStatusText(f"Added bookmark '{title}' before '{selected_node.title}'.")
            elif pos_type == 2:  # Sibling After
                if parent is None:
                    self.model.insert_root(idx + 1, new_node)
                else:
                    parent.insert_child(idx + 1, new_node)
                self.statusbar.SetStatusText(f"Added bookmark '{title}' after '{selected_node.title}'.")
                
        # Set new node to be selected when restoring state
        state = (self.GetTreeState()[0], new_node)
        self.RebuildTreeCtrl()
        self.RestoreTreeState(state)
        self.txt_add_title.SetValue("")

    # --- Reorder Actions ---

    def OnMoveUp(self, event):
        node = self.GetSelectedNode()
        if node and self.model.move_up(node):
            self.RebuildAndSyncTree()
            self.statusbar.SetStatusText("Moved selected node up.")
            
    def OnMoveDown(self, event):
        node = self.GetSelectedNode()
        if node and self.model.move_down(node):
            self.RebuildAndSyncTree()
            self.statusbar.SetStatusText("Moved selected node down.")
            
    def OnPromote(self, event):
        node = self.GetSelectedNode()
        if node and self.model.promote(node):
            self.RebuildAndSyncTree()
            self.statusbar.SetStatusText("Promoted selected node outward.")
            
    def OnDemote(self, event):
        node = self.GetSelectedNode()
        if node and self.model.demote(node):
            self.RebuildAndSyncTree()
            self.statusbar.SetStatusText("Demoted selected node inward.")

    def SelectTreeNodeByData(self, node):
        """Walks tree to find the item with node as data and sets selection."""
        def scan(item):
            if not item.IsOk():
                return None
            if self.tree.GetItemData(item) == node:
                return item
            # Scan children
            child, cookie = self.tree.GetFirstChild(item)
            while child.IsOk():
                res = scan(child)
                if res:
                    return res
                child, cookie = self.tree.GetNextChild(item, cookie)
            return None
            
        found_item = scan(self.tree_root)
        if found_item:
            self.tree.SelectItem(found_item)

    def OnShiftPages(self, event):
        if not self.pdf_path:
            return
        offset = self.spin_shift_offset.GetValue()
        self.model.shift_pages(offset)
        self.RebuildAndSyncTree()
        self.statusbar.SetStatusText(f"Shifted all page indexes by {offset}.")

    # --- Import / Export Handlers ---

    def OnImportTextTOC(self, event):
        if not self.pdf_path:
            wx.MessageBox("Please load a PDF file first.", "No PDF", wx.OK | wx.ICON_WARNING)
            return
            
        text = self.txt_toc_bulk.GetValue()
        if not text.strip():
            wx.MessageBox("Bulk TOC text box is empty.", "Warning", wx.OK | wx.ICON_WARNING)
            return
            
        try:
            roots = parse_text_toc(text)
            self.model.clear()
            self.model.roots = roots
            self.RebuildTreeCtrl()
            self.statusbar.SetStatusText(f"Successfully imported {len(roots)} tree nodes from text.")
            wx.MessageBox("Imported text outline. Click 'Save PDF' to apply permanently.", "Imported", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Failed to parse text TOC:\n{str(e)}", "Error", wx.OK | wx.ICON_ERROR)

    def OnExportTextTOC(self, event):
        if not self.model.roots:
            wx.MessageBox("Bookmark tree outline is empty.", "Warning", wx.OK | wx.ICON_WARNING)
            return
            
        text = export_toc_to_text(self.model.roots)
        self.txt_toc_bulk.SetValue(text)
        self.statusbar.SetStatusText("Exported bookmarks tree to text area.")

    # --- Generate physical TOC PDF Page ---

    def OnGenerateTOCPage(self, event):
        if not self.pdf_path:
            wx.MessageBox("Please load a PDF file first.", "No PDF", wx.OK | wx.ICON_WARNING)
            return
            
        if not self.model.roots:
            wx.MessageBox("Bookmark tree outline is empty. Cannot generate TOC.", "Warning", wx.OK | wx.ICON_WARNING)
            return
            
        # Get target output location
        wildcard = "PDF Files (*.pdf)|*.pdf"
        dialog = wx.FileDialog(self, "Save Merged PDF as", wildcard=wildcard, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        
        if dialog.ShowModal() == wx.ID_OK:
            out_path = dialog.GetPath()
            
            # Construct Layout Settings
            accent_idx = self.choice_color.GetSelection()
            accent_hex = self.color_map.get(accent_idx, "#1A73E8")
            
            dot_idx = self.choice_dots.GetSelection()
            dot_char = self.dots_map.get(dot_idx, ".")
            
            config = {
                "title": self.txt_toc_title.GetValue().strip(),
                "font_name": self.choice_font.GetString(self.choice_font.GetSelection()),
                "theme_color": accent_hex,
                "dot_leader": dot_char,
                "auto_shift": self.chk_auto_shift.GetValue(),
                "page_offset": 0,  # Insert at page index 0
                "margins": 54,
                "line_height": 22
            }
            
            # Execute physical generation
            self.statusbar.SetStatusText("Generating and inserting TOC page...")
            try:
                pages_added, updated_roots = generate_and_insert_toc(self.pdf_path, out_path, self.model, config)
                
                # Update current editor path to the newly saved file
                self.pdf_path = out_path
                self.pdf_filename = os.path.basename(self.pdf_path)
                self.model.roots = updated_roots
                
                # Refresh page count (which increased by pages_added)
                self.total_pages += pages_added
                
                self.RebuildTreeCtrl()
                self.UpdateDetails()
                
                msg = f"Generated and inserted a {pages_added}-page Table of Contents at the beginning!\n" \
                      f"All remaining bookmark targets have been shifted forward by {pages_added} pages automatically."
                wx.MessageBox(msg, "TOC Generated", wx.OK | wx.ICON_INFORMATION)
                self.statusbar.SetStatusText(f"Saved merged PDF with TOC to {self.pdf_filename}")
            except Exception as e:
                wx.MessageBox(f"Failed to generate physical TOC:\n{str(e)}", "Error", wx.OK | wx.ICON_ERROR)
                self.statusbar.SetStatusText("Failed to generate TOC.")
                
        dialog.Destroy()

    def OnRunAutoDetect(self, event):
        if not self.pdf_path:
            wx.MessageBox("Please load a PDF file first.", "No PDF", wx.OK | wx.ICON_WARNING)
            return
            
        mode_sel = self.combo_mode.GetSelection()
        mode_name = "Semantic" if mode_sel == 1 else "Heuristics"
        
        progress = wx.ProgressDialog("Scanning PDF", f"Running AI auto-detection ({mode_name} mode) on all pages...", 
                                     parent=self, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)
        
        try:
            if mode_sel == 1:
                detected_roots = auto_detect_bookmarks_semantics(self.pdf_path)
            else:
                detected_roots = auto_detect_bookmarks_heuristics(self.pdf_path)
            
            if not detected_roots:
                wx.MessageBox(f"No outlines or headings were detected using the {mode_name.lower()} engine. Try cycling modes or importing text outline.", 
                              "No Headings Found", wx.OK | wx.ICON_INFORMATION)
                progress.Destroy()
                return
                
            self.model.clear()
            self.model.roots = detected_roots
            self.RebuildTreeCtrl()
            
            count = len(detected_roots)
            self.statusbar.SetStatusText(f"Discovered {count} heading structure bookmarks.")
            wx.MessageBox(f"Successfully auto-detected {count} root-level outline structures using {mode_name} mode!\n"
                          f"Click 'Save PDF' on the Info tab to write them permanently.", 
                          "Heuristics Done", wx.OK | wx.ICON_INFORMATION)
        except Exception as e:
            wx.MessageBox(f"Failed to auto-detect bookmarks:\n{str(e)}", "Error", wx.OK | wx.ICON_ERROR)
        finally:
            progress.Destroy()


# =========================================================================
# APPLICATION ENTRYPOINT & UNIT TESTS
# =========================================================================

def run_tests():
    """Simple offline tests to assert correctness of tree manipulation."""
    print("Running offline unit tests...")
    
    # Test 1: Node creation
    root = BookmarkNode("Root", 0)
    child = BookmarkNode("Child", 2)
    root.add_child(child)
    assert len(root.children) == 1
    assert child.parent == root
    print("[OK] Test 1: Node structure verified.")

    # Test 2: Tree search & deletion
    model = PDFOutlineModel()
    model.add_root(root)
    parent, idx = model.find_parent_and_index(child)
    assert parent == root
    assert idx == 0
    
    model.remove_node(child)
    assert len(root.children) == 0
    print("[OK] Test 2: Tree node deletion verified.")

    # Test 3: Shift page numbers
    model.clear()
    n1 = BookmarkNode("N1", 0)
    n2 = BookmarkNode("N2", 5)
    model.add_root(n1)
    model.add_root(n2)
    model.shift_pages(2, start_page=3)
    assert n1.page_number == 0
    assert n2.page_number == 7
    print("[OK] Test 3: Page shifting logic verified.")
    
    # Test 4: Text TOC parsing
    text_data = """
Chapter 1: Intro - 1
    Section 1.1 - 2
    Section 1.2 - 3
Chapter 2 - 10
"""
    roots = parse_text_toc(text_data)
    assert len(roots) == 2
    assert roots[0].title == "Chapter 1: Intro"
    assert roots[0].page_number == 0
    assert len(roots[0].children) == 2
    assert roots[0].children[0].title == "Section 1.1"
    assert roots[0].children[0].page_number == 1
    assert roots[1].title == "Chapter 2"
    assert roots[1].page_number == 9
    print("[OK] Test 4: Text TOC parsing verified.")
    
    print("All tests passed successfully!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_tests()
    else:
        app = wx.App()
        frame = PDFEditorFrame()
        frame.Show()
        app.MainLoop()
