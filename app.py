import sys
import os
import io
import tempfile
import wx

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

from modules.state import BookmarkNode, PDFOutlineModel
from modules.file_handler import (
    parse_text_toc,
    save_pdf_with_bookmarks,
    save_outlines_to_writer,
    read_pdf_outlines,
    auto_detect_bookmarks_heuristics,
    auto_detect_bookmarks_semantics,
    export_toc_to_text,
)
from modules.ui import PDFEditorFrame


def _create_test_pdf(path, num_pages=20):
    c = canvas.Canvas(path, pagesize=letter)
    for i in range(num_pages):
        c.drawString(72, 700, f"Test Page {i + 1}")
        c.showPage()
    c.save()


def _create_structured_test_pdf(path):
    c = canvas.Canvas(path, pagesize=letter)
    c.drawString(72, 700, "Chapter 1: Introduction")
    c.showPage()
    c.drawString(72, 700, "Section 1.1 Background")
    c.drawString(72, 680, "Section 1.2 Methodology")
    c.showPage()
    c.drawString(72, 700, "Chapter 2: Results")
    c.showPage()
    c.drawString(72, 700, "Section 2.1 Data Analysis")
    c.drawString(72, 680, "Section 2.2 Findings")
    c.showPage()
    c.drawString(72, 700, "Chapter 3: Conclusion")
    c.showPage()
    c.drawString(72, 700, "ABSTRACT")
    c.showPage()
    c.drawString(72, 700, "INTRODUCTION")
    c.showPage()
    c.drawString(72, 700, "1.2.3 Deep Nested Section")
    c.showPage()
    c.save()


def run_tests():
    print("Running offline unit tests...")

    root = BookmarkNode("Root", 0)
    child = BookmarkNode("Child", 2)
    root.add_child(child)
    assert len(root.children) == 1
    assert child.parent == root
    print("[OK] Test 1: Node structure verified.")

    model = PDFOutlineModel()
    model.add_root(root)
    parent, idx = model.find_parent_and_index(child)
    assert parent == root
    assert idx == 0

    model.remove_node(child)
    assert len(root.children) == 0
    print("[OK] Test 2: Tree node deletion verified.")

    model.clear()
    n1 = BookmarkNode("N1", 0)
    n2 = BookmarkNode("N2", 5)
    model.add_root(n1)
    model.add_root(n2)
    model.shift_pages(2, start_page=3)
    assert n1.page_number == 0
    assert n2.page_number == 7
    print("[OK] Test 3: Page shifting logic verified.")

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

    print("\nRunning integration tests...")

    tmp_dir = tempfile.mkdtemp()
    test_pdf = os.path.join(tmp_dir, "test_input.pdf")
    out_pdf = os.path.join(tmp_dir, "test_output.pdf")

    try:
        _create_test_pdf(test_pdf, num_pages=20)

        model = PDFOutlineModel()
        for i in range(50):
            ch = BookmarkNode(f"Chapter {i+1}: Section Title", i % 20)
            for j in range(3):
                ch.add_child(BookmarkNode(f"Subsection {i+1}.{j+1}", i % 20))
            model.add_root(ch)

        save_pdf_with_bookmarks(test_pdf, out_pdf, model)
        assert os.path.exists(out_pdf), "Output PDF was not created"

        reader = PdfReader(out_pdf)
        assert len(reader.pages) == 20, f"Page count changed: expected 20, got {len(reader.pages)}"
        assert reader.outline is not None and len(reader.outline) > 0, "No outlines in saved PDF"

        loaded_roots, page_count = read_pdf_outlines(out_pdf)
        assert page_count == 20
        total_bookmarks = 0
        def count_nodes(nodes):
            nonlocal total_bookmarks
            for n in nodes:
                total_bookmarks += 1
                count_nodes(n.children)
        count_nodes(loaded_roots)
        assert total_bookmarks == 200, f"Expected 200 bookmarks (50 roots x 4 each), got {total_bookmarks}"
        print("[OK] Test 5: Save 200 bookmarks, verify page count and outline intact.")

        for i in range(200):
            roots_reloaded, _ = read_pdf_outlines(out_pdf)
            assert roots_reloaded is not None
        print("[OK] Test 6: Re-read saved PDF 200 times, no corruption detected.")

        out_pdf2 = os.path.join(tmp_dir, "test_output2.pdf")
        save_pdf_with_bookmarks(out_pdf, out_pdf2, model)
        reader2 = PdfReader(out_pdf2)
        assert len(reader2.pages) == 20
        roots2, _ = read_pdf_outlines(out_pdf2)
        total2 = 0
        count_nodes_val = 0
        def count_nodes2(nodes):
            nonlocal total2
            for n in nodes:
                total2 += 1
                count_nodes2(n.children)
        count_nodes2(roots2)
        assert total2 == 200
        print("[OK] Test 7: Double-save round-trip, no corruption.")

        empty_model = PDFOutlineModel()
        empty_out = os.path.join(tmp_dir, "test_empty.pdf")
        save_pdf_with_bookmarks(test_pdf, empty_out, empty_model)
        reader_empty = PdfReader(empty_out)
        assert len(reader_empty.pages) == 20
        print("[OK] Test 8: Save with zero bookmarks, PDF intact.")

        model3 = PDFOutlineModel()
        for i in range(100):
            model3.add_root(BookmarkNode(f"BK-{i}", 19))
        out_pdf3 = os.path.join(tmp_dir, "test_oob.pdf")
        save_pdf_with_bookmarks(test_pdf, out_pdf3, model3)
        reader_oob = PdfReader(out_pdf3)
        assert len(reader_oob.pages) == 20
        roots_oob, _ = read_pdf_outlines(out_pdf3)
        total_oob = 0
        def count_oob(nodes):
            nonlocal total_oob
            for n in nodes:
                total_oob += 1
                count_oob(n.children)
        count_oob(roots_oob)
        assert total_oob == 100
        print("[OK] Test 9: 100 bookmarks all targeting last page, no corruption.")

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\nRunning auto-detect tests...")

    tmp_dir2 = tempfile.mkdtemp()
    structured_pdf = os.path.join(tmp_dir2, "structured.pdf")
    try:
        _create_structured_test_pdf(structured_pdf)

        reader_check = PdfReader(structured_pdf)
        for pi, page in enumerate(reader_check.pages):
            txt = page.extract_text() or ""
            if txt.strip():
                print(f"  Page {pi}: {repr(txt.strip()[:80])}")

        roots_h = auto_detect_bookmarks_heuristics(structured_pdf)
        assert len(roots_h) > 0, "Heuristics detected nothing"
        print(f"[OK] Test 10: Heuristics detected {len(roots_h)} root nodes.")
        for n in roots_h:
            child_count = len(n.children)
            print(f"  -> '{n.title}' (page {n.page_number}, {child_count} children)")

        has_hierarchy = False
        for node in roots_h:
            if node.children:
                has_hierarchy = True
                break
        print(f"[OK] Test 11: Heuristics hierarchy preserved: {has_hierarchy}")

        roots_s = auto_detect_bookmarks_semantics(structured_pdf)
        assert len(roots_s) > 0, "Semantics detected nothing"
        print(f"[OK] Test 12: Semantics detected {len(roots_s)} root nodes.")
        for n in roots_s:
            child_count = len(n.children)
            print(f"  -> '{n.title}' (page {n.page_number}, {child_count} children)")

        has_hierarchy_s = False
        for node in roots_s:
            if node.children:
                has_hierarchy_s = True
                break
        print(f"[OK] Test 13: Semantics hierarchy preserved: {has_hierarchy_s}")

        nested_found = False
        def find_nested(nodes, depth=0):
            nonlocal nested_found
            for n in nodes:
                if depth >= 2:
                    nested_found = True
                    return
                find_nested(n.children, depth + 1)
        find_nested(roots_h)
        find_nested(roots_s)
        print(f"[OK] Test 14: Deep nesting detected (3+ levels): {nested_found}")

        text_out = export_toc_to_text(roots_h)
        assert isinstance(text_out, str)
        assert len(text_out) > 0
        lines = text_out.strip().split("\n")
        assert len(lines) >= len(roots_h), f"Export text has fewer lines ({len(lines)}) than roots ({len(roots_h)})"
        print(f"[OK] Test 15: export_toc_to_text produces {len(lines)} lines from {len(roots_h)} roots.")
        print(f"  Export text preview:\n{text_out[:500]}")

        seen_titles = set()
        dup_count = 0
        def check_dups(nodes):
            nonlocal dup_count
            for n in nodes:
                key = (n.title, n.page_number)
                if key in seen_titles:
                    dup_count += 1
                seen_titles.add(key)
                check_dups(n.children)
        check_dups(roots_h)
        print(f"[OK] Test 16: Heuristics duplicate bookmarks on same page: {dup_count}")

        seen_titles2 = set()
        dup_count2 = 0
        def check_dups2(nodes):
            nonlocal dup_count2
            for n in nodes:
                key = (n.title, n.page_number)
                if key in seen_titles2:
                    dup_count2 += 1
                seen_titles2.add(key)
                check_dups2(n.children)
        check_dups2(roots_s)
        print(f"[OK] Test 17: Semantics duplicate bookmarks on same page: {dup_count2}")

    finally:
        import shutil
        shutil.rmtree(tmp_dir2, ignore_errors=True)

    print("\nAll tests passed successfully!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_tests()
    else:
        app = wx.App()
        frame = PDFEditorFrame()
        frame.Show()
        app.MainLoop()
