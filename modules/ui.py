import os
import wx

from .state import BookmarkNode, PDFOutlineModel
from .file_handler import (
    HAS_REPORTLAB,
    read_pdf_outlines,
    save_pdf_with_bookmarks,
    generate_and_insert_toc,
    parse_text_toc,
    export_toc_to_text,
    auto_detect_bookmarks_heuristics,
    auto_detect_bookmarks_semantics,
    auto_detect_bookmarks_nlp,
)


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


class VectorIconGenerator:
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
            gc.SetPen(gc.CreatePen(wx.Pen(color, 1)))
            gc.SetBrush(gc.CreateBrush(wx.Brush(color)))
            path = gc.CreatePath()
            path.AddArc(8, 8, 6, 1.57, 4.71, False)
            path.CloseSubpath()
            gc.DrawPath(path)
            path2 = gc.CreatePath()
            path2.AddArc(8, 8, 6, 4.71, 1.57, False)
            gc.StrokePath(path2)

        dc.SelectObject(wx.NullBitmap)
        return bmp


class ModernButton(wx.Button):
    def __init__(self, parent, id=wx.ID_ANY, label="", pos=wx.DefaultPosition, size=wx.DefaultSize,
                 variant="secondary", icon_type=None, name="ModernButton"):
        super().__init__(parent, id, label, pos, size, name=name)
        self.variant = variant
        self.icon_type = icon_type

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


class PDFEditorFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="mpdf - PDF Outline & TOC Editor", size=(1000, 700))

        self.model = PDFOutlineModel()
        self.current_theme = "light"
        self.pdf_path = None
        self.pdf_filename = None
        self.total_pages = 0

        self.InitUI()
        self.ApplyTheme(self.current_theme)

    def InitUI(self):
        self.statusbar = self.CreateStatusBar()
        self.statusbar.SetStatusText("Ready. Open a PDF to begin.")

        menu_bar = wx.MenuBar()

        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, "&Open PDF...\tCtrl+O", "Open a PDF file to edit outlines")
        self.save_item = file_menu.Append(wx.ID_SAVE, "&Save PDF\tCtrl+S", "Save changes to current PDF")
        self.save_as_item = file_menu.Append(wx.ID_SAVEAS, "Save PDF &As...\tCtrl+Shift+S", "Save changes to new PDF")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit", "Close the app")

        theme_menu = wx.Menu()
        toggle_theme_item = theme_menu.Append(wx.ID_ANY, "&Toggle Light/Dark Mode\tCtrl+T", "Switch app aesthetic theme")

        options_menu = wx.Menu()
        options_item = options_menu.Append(wx.ID_ANY, "&Options Settings...\tAlt+O", "Configure application options")
        self.Bind(wx.EVT_MENU, self.OnShowOptions, options_item)

        menu_bar.Append(file_menu, "&File")
        menu_bar.Append(theme_menu, "&Theme")
        menu_bar.Append(options_menu, "&Options")
        self.SetMenuBar(menu_bar)

        self.Bind(wx.EVT_MENU, self.OnOpenPDF, open_item)
        self.Bind(wx.EVT_MENU, self.OnSavePDF, self.save_item)
        self.Bind(wx.EVT_MENU, self.OnSavePDFAs, self.save_as_item)
        self.Bind(wx.EVT_MENU, self.OnClose, exit_item)
        self.Bind(wx.EVT_MENU, self.OnToggleTheme, toggle_theme_item)

        self.splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE | wx.SP_3D)

        self.left_panel = wx.Panel(self.splitter)
        left_sizer = wx.BoxSizer(wx.VERTICAL)

        tree_label = wx.StaticText(self.left_panel, label="&Bookmarks:")
        font_header = wx.Font(11, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        tree_label.SetToolTip("PDF Outline bookmarks")
        tree_label.SetFont(font_header)
        left_sizer.Add(tree_label, 0, wx.ALL, 10)

        self.tree = wx.TreeCtrl(self.left_panel, style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_DEFAULT_STYLE)
        self.tree.SetHelpText("Bookmarks tree. Use arrow keys to navigate, Enter to select.")
        self.tree.SetName("PDFOutlineTree")

        left_sizer.Add(self.tree, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.left_panel.SetSizer(left_sizer)

        self.tree_image_list = wx.ImageList(16, 16)
        self.icon_pdf_idx = -1
        self.icon_folder_idx = -1
        self.icon_page_idx = -1
        self.tree.SetImageList(self.tree_image_list)

        self.right_panel = wx.Panel(self.splitter)
        right_sizer = wx.BoxSizer(wx.VERTICAL)

        self.notebook = wx.Notebook(self.right_panel)

        self._build_tab_info()
        self._build_tab_edit()
        self._build_tab_text()
        self._build_tab_gen_toc()
        self._build_tab_auto_detect()

        self.notebook.AddPage(self.tab_info, "Info")
        self.notebook.AddPage(self.tab_edit, "Edit Bookmarks")
        self.notebook.AddPage(self.tab_text, "Import / Export")
        self.notebook.AddPage(self.tab_gen_toc, "Generate TOC Page")
        self.notebook.AddPage(self.tab_auto_detect, "Auto-Detect")

        right_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)
        self.right_panel.SetSizer(right_sizer)

        self.splitter.SplitVertically(self.left_panel, self.right_panel, 350)
        self.splitter.SetMinimumPaneSize(200)

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

    def _build_tab_info(self):
        self.tab_info = wx.Panel(self.notebook)
        info_sizer = wx.BoxSizer(wx.VERTICAL)

        self.info_title = wx.StaticText(self.tab_info, label="No PDF file loaded.")
        self.info_title.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
        info_sizer.Add(self.info_title, 0, wx.ALL, 15)

        self.info_details = wx.StaticText(self.tab_info, label="Please select a PDF document to start editing outlines, importing bookmarks, or generating Tables of Contents.")
        self.info_details.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        self.info_details.Wrap(350)
        info_sizer.Add(self.info_details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 15)

        action_box = wx.StaticBox(self.tab_info, label="Quick PDF Actions")
        action_sizer = wx.StaticBoxSizer(action_box, wx.VERTICAL)

        self.btn_clear_bookmarks = ModernButton(self.tab_info, label="Delete All Bookmarks", variant="danger", icon_type="minus")
        self.btn_save_quick = ModernButton(self.tab_info, label="Save Changes", variant="primary", icon_type="save")

        action_sizer.Add(self.btn_clear_bookmarks, 0, wx.EXPAND | wx.ALL, 6)
        action_sizer.Add(self.btn_save_quick, 0, wx.EXPAND | wx.ALL, 6)
        info_sizer.Add(action_sizer, 0, wx.EXPAND | wx.ALL, 15)

        self.tab_info.SetSizer(info_sizer)

    def _build_tab_edit(self):
        self.tab_edit = wx.Panel(self.notebook)
        edit_sizer = wx.BoxSizer(wx.VERTICAL)

        edit_sel_box = wx.StaticBox(self.tab_edit, label="Edit Selected Bookmark")
        edit_sel_sizer = wx.StaticBoxSizer(edit_sel_box, wx.VERTICAL)

        row_title = wx.BoxSizer(wx.HORIZONTAL)
        lbl_title = wx.StaticText(self.tab_edit, label="&Title:", size=(80, -1))
        lbl_title.SetToolTip("Bookmark title input")
        self.txt_edit_title = wx.TextCtrl(self.tab_edit)
        self.txt_edit_title.SetHelpText("Enter bookmark title")
        self.txt_edit_title.SetName("EditTitleInput")
        row_title.Add(lbl_title, 0, wx.ALIGN_CENTER_VERTICAL)
        row_title.Add(self.txt_edit_title, 1, wx.EXPAND)
        self.txt_edit_title.SetLabel("Title input")
        edit_sel_sizer.Add(row_title, 0, wx.EXPAND | wx.ALL, 5)

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

        edit_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_update_node = ModernButton(self.tab_edit, label="Apply Edit", variant="secondary")
        self.btn_delete_node = ModernButton(self.tab_edit, label="Delete Bookmark", variant="danger", icon_type="minus")
        edit_btn_sizer.Add(self.btn_update_node, 1, wx.EXPAND | wx.RIGHT, 5)
        edit_btn_sizer.Add(self.btn_delete_node, 1, wx.EXPAND | wx.LEFT, 5)
        edit_sel_sizer.Add(edit_btn_sizer, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 10)

        edit_sizer.Add(edit_sel_sizer, 0, wx.EXPAND | wx.ALL, 10)

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

        add_box = wx.StaticBox(self.tab_edit, label="Add New Bookmark")
        add_sizer = wx.StaticBoxSizer(add_box, wx.VERTICAL)

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

        self.radio_position = wx.RadioBox(self.tab_edit, label="Position",
                                          choices=["As Child", "Sibling Before", "Sibling After", "As Root End"],
                                          majorDimension=2, style=wx.RA_SPECIFY_COLS)
        add_sizer.Add(self.radio_position, 0, wx.EXPAND | wx.ALL, 5)

        self.btn_add_node = ModernButton(self.tab_edit, label="Add Bookmark Item", variant="primary", icon_type="plus")
        add_sizer.Add(self.btn_add_node, 0, wx.EXPAND | wx.ALL, 5)

        edit_sizer.Add(add_sizer, 0, wx.EXPAND | wx.ALL, 10)

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

    def _build_tab_text(self):
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

    def _build_tab_gen_toc(self):
        self.tab_gen_toc = wx.Panel(self.notebook)
        gen_sizer = wx.BoxSizer(wx.VERTICAL)

        gen_desc = wx.StaticText(self.tab_gen_toc, label="This creates a Table of Contents PDF page from current bookmarks and merges it directly at the start of your document with clickable page hyperlinks.")
        gen_desc.Wrap(380)
        gen_sizer.Add(gen_desc, 0, wx.ALL, 10)

        params_box = wx.StaticBox(self.tab_gen_toc, label="TOC Layout & Page Styles")
        params_sizer = wx.StaticBoxSizer(params_box, wx.VERTICAL)

        t_row = wx.BoxSizer(wx.HORIZONTAL)
        t_lbl = wx.StaticText(self.tab_gen_toc, label="TOC Title:", size=(100, -1))
        self.txt_toc_title = wx.TextCtrl(self.tab_gen_toc)
        self.txt_toc_title.SetValue("Table of Contents")
        t_row.Add(t_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        t_row.Add(self.txt_toc_title, 1, wx.EXPAND)
        params_sizer.Add(t_row, 0, wx.EXPAND | wx.ALL, 4)

        f_row = wx.BoxSizer(wx.HORIZONTAL)
        f_lbl = wx.StaticText(self.tab_gen_toc, label="Font Style:", size=(100, -1))
        self.choice_font = wx.Choice(self.tab_gen_toc, choices=["Helvetica", "Times-Roman", "Courier"])
        self.choice_font.SetSelection(0)
        f_row.Add(f_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        f_row.Add(self.choice_font, 1, wx.EXPAND)
        params_sizer.Add(f_row, 0, wx.EXPAND | wx.ALL, 4)

        c_row = wx.BoxSizer(wx.HORIZONTAL)
        c_lbl = wx.StaticText(self.tab_gen_toc, label="Theme Accent:", size=(100, -1))
        self.choice_color = wx.Choice(self.tab_gen_toc, choices=["Google Blue", "Teal Emerald", "Deep Charcoal", "Crimson Red", "Royal Purple"])
        self.choice_color.SetSelection(0)
        self.color_map = {
            0: "#1A73E8",
            1: "#0F9D58",
            2: "#37474F",
            3: "#D93025",
            4: "#673AB7",
        }
        c_row.Add(c_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        c_row.Add(self.choice_color, 1, wx.EXPAND)
        params_sizer.Add(c_row, 0, wx.EXPAND | wx.ALL, 4)

        d_row = wx.BoxSizer(wx.HORIZONTAL)
        d_lbl = wx.StaticText(self.tab_gen_toc, label="Dot Leader:", size=(100, -1))
        self.choice_dots = wx.Choice(self.tab_gen_toc, choices=["Dots (. . .)", "Dashes (- - -)", "None"])
        self.choice_dots.SetSelection(0)
        self.dots_map = {0: ".", 1: "-", 2: ""}
        d_row.Add(d_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        d_row.Add(self.choice_dots, 1, wx.EXPAND)
        params_sizer.Add(d_row, 0, wx.EXPAND | wx.ALL, 4)

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

    def _build_tab_auto_detect(self):
        self.tab_auto_detect = wx.Panel(self.notebook)
        auto_detect_sizer = wx.BoxSizer(wx.VERTICAL)

        ad_desc = wx.StaticText(self.tab_auto_detect, label="Automatically discover bookmarks based on headings, numbering structures, and formatting styles across all pages.")
        ad_desc.Wrap(380)
        auto_detect_sizer.Add(ad_desc, 0, wx.ALL, 15)

        mode_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl_mode = wx.StaticText(self.tab_auto_detect, label="Detection Mode:")
        self.combo_mode = wx.Choice(self.tab_auto_detect, choices=["Heuristics (Pattern-based)", "Semantic (Structure & Keyword)", "Gemini AI NLP (API-based)"])
        self.combo_mode.SetSelection(0)
        mode_row.Add(lbl_mode, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        mode_row.Add(self.combo_mode, 1, wx.EXPAND)
        auto_detect_sizer.Add(mode_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 15)

        self.btn_run_auto_detect = ModernButton(self.tab_auto_detect, label="Run Auto-Detection", variant="primary", icon_type="plus")
        auto_detect_sizer.Add(self.btn_run_auto_detect, 0, wx.EXPAND | wx.ALL, 15)

        self.tab_auto_detect.SetSizer(auto_detect_sizer)

    def OnToggleTheme(self, event):
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self.ApplyTheme(self.current_theme)

    def ApplyTheme(self, theme_name):
        colors = THEMES[theme_name]

        self.tree_image_list.RemoveAll()
        self.icon_pdf_idx = self.tree_image_list.Add(VectorIconGenerator.create_bitmap("pdf", colors["primary"], 16))
        self.icon_folder_idx = self.tree_image_list.Add(VectorIconGenerator.create_bitmap("folder", colors["primary"], 16))
        self.icon_page_idx = self.tree_image_list.Add(VectorIconGenerator.create_bitmap("page", colors["text"], 16))

        self.RebuildTreeCtrl()

        self.ApplyThemeToWindow(self, colors)
        self.Refresh()

    def ApplyThemeToWindow(self, win, colors):
        win.SetBackgroundColour(wx.Colour(colors["bg"]))
        win.SetForegroundColour(wx.Colour(colors["text"]))

        if isinstance(win, wx.TreeCtrl):
            win.SetBackgroundColour(wx.Colour(colors["tree_bg"]))
            win.SetForegroundColour(wx.Colour(colors["text"]))
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

        for child in win.GetChildren():
            self.ApplyThemeToWindow(child, colors)

    def RebuildTreeCtrl(self):
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

    def GetTreeState(self):
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
        state = self.GetTreeState()
        self.RebuildTreeCtrl()
        self.RestoreTreeState(state)

    def UpdateDetails(self):
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
            self.spin_edit_page.SetMax(self.total_pages)
            self.spin_add_page.SetMax(self.total_pages)
        else:
            self.info_title.SetLabel("No PDF file loaded.")
            self.info_details.SetLabel("Please select a PDF document to start editing outlines.")

        self.info_details.Wrap(350)
        self.tab_info.Layout()

    def GetSelectedNode(self):
        item = self.tree.GetSelection()
        if not item.IsOk() or item == self.tree_root:
            return None
        return self.tree.GetItemData(item)

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

        if pos_type == 3 or not selected_node:
            self.model.add_root(new_node)
            self.statusbar.SetStatusText(f"Added bookmark '{title}' at root end.")
        else:
            parent, idx = self.model.find_parent_and_index(selected_node)
            if pos_type == 0:
                selected_node.add_child(new_node)
                self.statusbar.SetStatusText(f"Added child bookmark '{title}' under '{selected_node.title}'.")
            elif pos_type == 1:
                if parent is None:
                    self.model.insert_root(idx, new_node)
                else:
                    parent.insert_child(idx, new_node)
                self.statusbar.SetStatusText(f"Added bookmark '{title}' before '{selected_node.title}'.")
            elif pos_type == 2:
                if parent is None:
                    self.model.insert_root(idx + 1, new_node)
                else:
                    parent.insert_child(idx + 1, new_node)
                self.statusbar.SetStatusText(f"Added bookmark '{title}' after '{selected_node.title}'.")

        state = (self.GetTreeState()[0], new_node)
        self.RebuildTreeCtrl()
        self.RestoreTreeState(state)
        self.txt_add_title.SetValue("")

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
        def scan(item):
            if not item.IsOk():
                return None
            if self.tree.GetItemData(item) == node:
                return item
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

    def OnGenerateTOCPage(self, event):
        if not self.pdf_path:
            wx.MessageBox("Please load a PDF file first.", "No PDF", wx.OK | wx.ICON_WARNING)
            return

        if not self.model.roots:
            wx.MessageBox("Bookmark tree outline is empty. Cannot generate TOC.", "Warning", wx.OK | wx.ICON_WARNING)
            return

        wildcard = "PDF Files (*.pdf)|*.pdf"
        dialog = wx.FileDialog(self, "Save Merged PDF as", wildcard=wildcard, style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)

        if dialog.ShowModal() == wx.ID_OK:
            out_path = dialog.GetPath()

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
                "page_offset": 0,
                "margins": 54,
                "line_height": 22
            }

            self.statusbar.SetStatusText("Generating and inserting TOC page...")
            try:
                pages_added, updated_roots = generate_and_insert_toc(self.pdf_path, out_path, self.model, config)

                self.pdf_path = out_path
                self.pdf_filename = os.path.basename(self.pdf_path)
                self.model.roots = updated_roots

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
        if mode_sel == 2:
            mode_name = "Gemini AI NLP"
        elif mode_sel == 1:
            mode_name = "Semantic"
        else:
            mode_name = "Heuristics"

        if mode_sel == 2:
            config = wx.Config("mpdf")
            api_key = config.Read("GeminiAPIKey", "").strip()
            gemini_model = config.Read("GeminiModel", "gemini-2.5-flash")
            if not api_key:
                wx.MessageBox("Gemini API Key is missing. Please set your API Key first by opening the Options menu (Alt+O).",
                              "API Key Required", wx.OK | wx.ICON_WARNING)
                return

        progress = wx.ProgressDialog("Scanning PDF", f"Running AI auto-detection ({mode_name} mode) on all pages...",
                                     parent=self, style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE)

        try:
            if mode_sel == 2:
                detected_roots = auto_detect_bookmarks_nlp(self.pdf_path, api_key, model=gemini_model)
            elif mode_sel == 1:
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

    def OnShowOptions(self, event):
        dialog = wx.Dialog(self, title="Application Options", size=(420, 300))
        panel = wx.Panel(dialog)
        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl_info = wx.StaticText(panel, label="Enter your Gemini API Key for NLP Auto-Detection:")
        sizer.Add(lbl_info, 0, wx.ALL, 10)

        config = wx.Config("mpdf")
        saved_key = config.Read("GeminiAPIKey", "")
        saved_model = config.Read("GeminiModel", "gemini-2.5-flash")

        self.txt_api_key = wx.TextCtrl(panel, value=saved_key, style=wx.TE_PASSWORD)
        self.txt_api_key.SetHelpText("Enter your Gemini API Key here")
        self.txt_api_key.SetName("GeminiAPIKeyInput")
        sizer.Add(self.txt_api_key, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        lbl_model = wx.StaticText(panel, label="Gemini Model:")
        sizer.Add(lbl_model, 0, wx.LEFT | wx.RIGHT, 10)

        GEMINI_MODELS = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-1.0-pro",
        ]
        self.choice_gemini_model = wx.Choice(panel, choices=GEMINI_MODELS)
        if saved_model in GEMINI_MODELS:
            self.choice_gemini_model.SetStringSelection(saved_model)
        else:
            self.choice_gemini_model.SetSelection(0)
        sizer.Add(self.choice_gemini_model, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        lbl_note = wx.StaticText(panel, label="Note: Your API Key is saved securely in local settings.")
        lbl_note.SetFont(wx.Font(8, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        sizer.Add(lbl_note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        btn_sizer = wx.StdDialogButtonSizer()
        btn_save = wx.Button(panel, wx.ID_OK, label="Save")
        btn_cancel = wx.Button(panel, wx.ID_CANCEL, label="Cancel")
        btn_sizer.AddButton(btn_save)
        btn_sizer.AddButton(btn_cancel)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        panel.SetSizer(sizer)

        def on_save(evt):
            import json as _json
            import urllib.request as _urllib_request

            api_key = self.txt_api_key.GetValue().strip()
            model = self.choice_gemini_model.GetStringSelection()

            config.Write("GeminiModel", model)

            if not api_key:
                config.Write("GeminiAPIKey", "")
                self.statusbar.SetStatusText("Gemini API Key removed.")
                dialog.EndModal(wx.ID_OK)
                return

            busy = wx.BusyInfo("Validating Gemini API Key. Please wait...", parent=dialog)

            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}
            body = {"contents": [{"parts": [{"text": "Hello"}]}]}
            req = _urllib_request.Request(url, data=_json.dumps(body).encode("utf-8"), headers=headers, method="POST")

            try:
                with _urllib_request.urlopen(req, timeout=10) as response:
                    res_data = _json.loads(response.read().decode("utf-8"))
                    if "candidates" in res_data:
                        del busy
                        config.Write("GeminiAPIKey", api_key)
                        self.statusbar.SetStatusText(f"Gemini API Key validated and saved ({model}).")
                        dialog.EndModal(wx.ID_OK)
                    else:
                        del busy
                        wx.MessageBox("Invalid API response format received. The key might be invalid.",
                                      "Validation Failed", wx.OK | wx.ICON_ERROR, parent=dialog)
            except Exception as e:
                del busy
                error_msg = str(e)
                if "400" in error_msg or "403" in error_msg or "Unauthorized" in error_msg:
                    wx.MessageBox("Invalid Gemini API Key. Please check the key and try again.",
                                  "Validation Failed", wx.OK | wx.ICON_ERROR, parent=dialog)
                else:
                    wx.MessageBox(f"Validation failed (Network / Server Error):\n{error_msg}",
                                  "Error", wx.OK | wx.ICON_ERROR, parent=dialog)

        btn_save.Bind(wx.EVT_BUTTON, on_save)

        dialog.ShowModal()
        dialog.Destroy()
