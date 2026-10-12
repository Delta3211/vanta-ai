import os
from pathlib import Path
from typing import Dict, Any, Optional
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty
from PyQt5.QtGui import QFont, QColor, QCursor, QPainter, QPen
from PyQt5.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QScrollArea, QSizePolicy,
    QTreeWidget, QTreeWidgetItem,
)
from workspace import WorkspaceManager


# ─────────────────────────────────────────────────────────────────────────────
# Animated glowing border frame
# ─────────────────────────────────────────────────────────────────────────────
class GlowFrame(QFrame):
    """QFrame with a softly pulsing gradient glow border."""

    def __init__(self, glow_color="#4C70F0", bg_color="#04060F", radius=16, parent=None):
        super().__init__(parent)
        self._glow_color = QColor(glow_color)
        self._bg_color   = QColor(bg_color)
        self._radius     = radius
        self._opacity    = 0.22
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._anim = QPropertyAnimation(self, b"glow_opacity")
        self._anim.setDuration(2200)
        self._anim.setStartValue(0.18)
        self._anim.setEndValue(0.80)
        self._anim.setEasingCurve(QEasingCurve.SineCurve)
        self._anim.setLoopCount(-1)
        self._anim.start()

    def _get_opacity(self):
        return self._opacity

    def _set_opacity(self, v):
        self._opacity = v
        self.update()

    glow_opacity = pyqtProperty(float, _get_opacity, _set_opacity)

    def set_static(self, color: str):
        """Lock to a static color (call on tool finish)."""
        self._anim.stop()
        self._glow_color = QColor(color)
        self._opacity    = 0.65
        self.update()

    def paintEvent(self, event):
        from PyQt5.QtGui import QLinearGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = self.rect().adjusted(1, 1, -1, -1)

        # Background fill
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg_color)
        p.drawRoundedRect(r, self._radius, self._radius)

        # Glow border — two concentric strokes for depth
        gc = QColor(self._glow_color)
        gc.setAlphaF(self._opacity * 0.5)
        p.setPen(QPen(gc, 2.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, self._radius, self._radius)

        gc2 = QColor(self._glow_color)
        gc2.setAlphaF(self._opacity)
        p.setPen(QPen(gc2, 1.0))
        inner = self.rect().adjusted(2, 2, -2, -2)
        p.drawRoundedRect(inner, self._radius - 1, self._radius - 1)


# ─────────────────────────────────────────────────────────────────────────────
# Status badge helper
# ─────────────────────────────────────────────────────────────────────────────
_BADGE = {
    "running": ("Executing…",       "#60A5FA", "rgba(60,100,250,0.10)",  "rgba(60,110,255,0.30)"),
    "waiting": ("Awaiting Approval", "#FBBF24", "rgba(251,191,36,0.10)",  "rgba(251,191,36,0.35)"),
    "success": ("Completed ✓",       "#34D399", "rgba(52,211,153,0.10)",  "rgba(52,211,153,0.30)"),
    "error":   ("Failed ✕",          "#F87171", "rgba(248,113,113,0.10)", "rgba(248,113,113,0.30)"),
    "skipped": ("Skipped",           "#64748B", "rgba(100,116,139,0.08)", "rgba(100,116,139,0.20)"),
}

def _badge(label: QLabel, state: str):
    text, col, bg, border = _BADGE.get(state, _BADGE["running"])
    label.setText(text)
    label.setStyleSheet(f"""
        QLabel {{
            color: {col}; background: {bg}; border: 1px solid {border};
            border-radius: 6px; padding: 2px 9px;
            font-size: 10px; font-weight: 700;
            letter-spacing: 0.4px;
        }}
    """)


# ─────────────────────────────────────────────────────────────────────────────
# Tool icon map
# ─────────────────────────────────────────────────────────────────────────────
_ICONS = {
    "run_command":      ("⚡", "#FCD34D"),
    "write_file":       ("📝", "#818CF8"),
    "edit_file":        ("✏",  "#818CF8"),
    "patch_file":       ("🩹", "#EC4899"),
    "append_file":      ("➕", "#38BDF8"),
    "read_file":        ("📖", "#67E8F9"),
    "delete_file":      ("🗑", "#F87171"),
    "rename_file":      ("🔄", "#38BDF8"),
    "create_dir":       ("📁", "#A78BFA"),
    "get_file_info":    ("ℹ",  "#67E8F9"),
    "list_dir":         ("📂", "#A78BFA"),
    "search_code":      ("🔍", "#34D399"),
    "grep":             ("🔎", "#34D399"),
    "check_syntax":     ("✓",  "#2DD4BF"),
    "get_file_outline": ("📑", "#FBBF24"),
    "undo_last_edit":   ("↩",  "#C084FC"),
    "open_browser":     ("🌐", "#60A5FA"),
    "scaffold_project": ("🏗",  "#FB923C"),
}

def _tool_icon(name: str):
    return _ICONS.get(name, ("⚙", "#94A3B8"))


# ─────────────────────────────────────────────────────────────────────────────
# ToolCardWidget
# ─────────────────────────────────────────────────────────────────────────────
class ToolCardWidget(QWidget):
    """Premium animated card rendered in chat when Luna calls a tool."""

    approved = pyqtSignal(str)
    rejected = pyqtSignal(str)

    def __init__(self, tool_name: str, args: Dict[str, Any], call_id: str,
                 luna: bool = True, parent=None):
        super().__init__(parent)
        self.tool_name   = tool_name
        self.args        = args
        self.call_id     = call_id
        self.luna        = luna
        self.is_expanded = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._build_ui()

    # ── build ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        icon_char, icon_col = _tool_icon(self.tool_name)
        glow_col  = "#7C8CF8" if self.luna else "#DA7756"
        card_bg   = "#0F1420" if self.luna else "#1A1916"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(0)

        self.frame = GlowFrame(glow_color=glow_col, bg_color=card_bg, radius=12)
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(14, 12, 14, 12)
        fl.setSpacing(10)
        outer.addWidget(self.frame)

        # ── header ─────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(10)

        # Icon bubble
        ib = QLabel(icon_char)
        ib.setFixedSize(34, 34)
        ib.setAlignment(Qt.AlignCenter)
        ib.setStyleSheet(f"""
            QLabel {{
                font-size: 15px;
                background: {icon_col}18;
                border: 1px solid {icon_col}30;
                border-radius: 8px;
            }}
        """)
        hdr.addWidget(ib)

        # Title + detail
        tc = QVBoxLayout()
        tc.setSpacing(2)
        tc.setContentsMargins(0, 0, 0, 0)

        title_col = "#F0F4FC" if self.luna else "#FAF7F2"
        self.title_lbl = QLabel(self._fmt_title())
        self.title_lbl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.title_lbl.setStyleSheet(f"color: {title_col}; background: transparent;")

        detail_col = "#94A3B8" if self.luna else "#A8A398"
        self.detail_lbl = QLabel(self._fmt_detail())
        self.detail_lbl.setFont(QFont("Segoe UI", 9))
        self.detail_lbl.setStyleSheet(f"color: {detail_col}; background: transparent;")
        self.detail_lbl.setWordWrap(True)

        tc.addWidget(self.title_lbl)
        tc.addWidget(self.detail_lbl)
        hdr.addLayout(tc, 1)

        # Badge
        self.badge = QLabel()
        _badge(self.badge, "running")
        hdr.addWidget(self.badge)

        # Toggle button
        btn_col = "#5070E8" if self.luna else "#D08020"
        self.toggle_btn = QPushButton("Output ▾")
        self.toggle_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                color: {btn_col};
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 7px; padding: 4px 11px;
                font-size: 10px; font-weight: 600;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,0.09); color: #E0E8FF; }}
        """)
        self.toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self.toggle_btn)
        fl.addLayout(hdr)

        # ── approval row ──────────────────────────────────────────────
        self.approval_row = QWidget()
        self.approval_row.setStyleSheet("background: transparent;")
        ar = QHBoxLayout(self.approval_row)
        ar.setContentsMargins(44, 2, 0, 2)
        ar.setSpacing(10)

        run_btn = QPushButton("✓  Approve & Run")
        run_btn.setCursor(QCursor(Qt.PointingHandCursor))
        run_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #166534,stop:1 #15803D);
                color: #A7F3D0; border: 1px solid #166534; border-radius: 8px;
                padding: 7px 18px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background: #15803D; color: white; }
        """)
        run_btn.clicked.connect(lambda: self.approved.emit(self.call_id))

        skip_btn = QPushButton("✕  Skip")
        skip_btn.setCursor(QCursor(Qt.PointingHandCursor))
        skip_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.04); color: #64748B;
                border: 1px solid rgba(255,255,255,0.10); border-radius: 8px;
                padding: 7px 16px; font-size: 12px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.10); color: white; }
        """)
        skip_btn.clicked.connect(lambda: self.rejected.emit(self.call_id))

        ar.addWidget(run_btn)
        ar.addWidget(skip_btn)
        ar.addStretch()
        self.approval_row.setVisible(False)
        fl.addWidget(self.approval_row)

        # ── output panel ─────────────────────────────────────────────
        self.output_panel = QWidget()
        self.output_panel.setStyleSheet("background: transparent;")
        op = QVBoxLayout(self.output_panel)
        op.setContentsMargins(0, 4, 0, 0)
        op.setSpacing(0)

        term_bg   = "#020614" if self.luna else "#0A0604"
        term_text = "#7DD3FC" if self.luna else "#FDE68A"
        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setFont(QFont("Consolas", 11))
        self.output_edit.setLineWrapMode(QTextEdit.NoWrap)
        self.output_edit.setStyleSheet(f"""
            QTextEdit {{
                background: {term_bg}; color: {term_text};
                border: 1px solid rgba(255,255,255,0.06); border-radius: 10px;
                padding: 12px 14px;
                font-family: 'Cascadia Code', 'Consolas', monospace;
                font-size: 11.5px;
            }}
            QScrollBar:vertical {{
                background: transparent; width: 6px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255,255,255,0.15); border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        """)
        self.output_edit.setFixedHeight(175)
        op.addWidget(self.output_edit)
        self.output_panel.setVisible(False)
        fl.addWidget(self.output_panel)

    # ── description helpers ───────────────────────────────────────────────
    def _fmt_title(self) -> str:
        return {
            "run_command":      "Run Command",
            "write_file":       "Write File",
            "edit_file":        "Edit File",
            "patch_file":       "Patch File",
            "append_file":      "Append to File",
            "read_file":        "Read File",
            "delete_file":      "Delete File",
            "rename_file":      "Rename File",
            "create_dir":       "Create Folder",
            "get_file_info":    "File Metadata",
            "list_dir":         "List Directory",
            "search_code":      "Search Code",
            "grep":             "Grep Search",
            "check_syntax":     "Check Syntax",
            "get_file_outline": "Code Outline",
            "undo_last_edit":   "Undo Last Edit",
            "open_browser":     "Open in Browser",
            "scaffold_project": "Scaffold Project",
        }.get(self.tool_name, self.tool_name.replace("_", " ").title())

    def _fmt_detail(self) -> str:
        a = self.args
        if self.tool_name == "run_command":
            cmd = a.get("command", "")
            return (cmd[:80] + "…") if len(cmd) > 80 else cmd
        if self.tool_name in ("write_file", "edit_file", "read_file", "append_file", "delete_file", "create_dir", "get_file_info", "check_syntax", "get_file_outline"):
            return a.get("path", "")
        if self.tool_name == "patch_file":
            return f"{a.get('path', '')} (lines {a.get('start_line', '?')}–{a.get('end_line', '?')})"
        if self.tool_name == "rename_file":
            return f"{a.get('path', '')} → {a.get('new_name', '')}"
        if self.tool_name == "list_dir":
            return a.get("path", ".")
        if self.tool_name == "search_code":
            return f'"{a.get("query","")}"  in {a.get("path",".")}'
        if self.tool_name == "grep":
            return f'"{a.get("pattern","")}"  in {a.get("path",".")}'
        if self.tool_name == "undo_last_edit":
            return "Revert last file change"
        if self.tool_name == "open_browser":
            return a.get("path", "index.html")
        if self.tool_name == "scaffold_project":
            return f'type: {a.get("type","html")}  |  name: {a.get("name","project")}'
        return ""

    # ── state transitions ─────────────────────────────────────────────────
    def set_running(self):
        _badge(self.badge, "running")
        self.approval_row.setVisible(False)

    def set_needs_approval(self):
        _badge(self.badge, "waiting")
        self.approval_row.setVisible(True)

    def set_finished(self, output: str, success: bool):
        self.approval_row.setVisible(False)
        self.output_edit.setPlainText(output)
        if success:
            _badge(self.badge, "success")
            self.frame.set_static("#10B981")
        else:
            _badge(self.badge, "error")
            self.frame.set_static("#EF4444")
            self._set_expanded(True)

    # ── expand / collapse ─────────────────────────────────────────────────
    def _toggle(self):
        self._set_expanded(not self.is_expanded)

    def _set_expanded(self, v: bool):
        self.is_expanded = v
        self.output_panel.setVisible(v)
        self.toggle_btn.setText("Output ▴" if v else "Output ▾")


# ─────────────────────────────────────────────────────────────────────────────
# WorkspaceBar
# ─────────────────────────────────────────────────────────────────────────────
class WorkspaceBar(QFrame):
    """Compact top bar: workspace path + auto-run toggle + change/refresh buttons."""

    folder_change_requested = pyqtSignal()
    auto_run_toggled        = pyqtSignal(bool)
    refresh_requested       = pyqtSignal()

    def __init__(self, workspace: WorkspaceManager, luna: bool = True, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.luna      = luna
        self.auto_run  = True
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("workspaceBar")
        self.setFixedHeight(46)
        self._apply_style()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(8)

        folder_icon = QLabel("📁")
        folder_icon.setStyleSheet("font-size: 13px; background: transparent; color: #4A5A80;")
        lay.addWidget(folder_icon)

        self.path_label = QLabel(self._short_path())
        self.path_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.path_label.setToolTip(str(self.workspace.root))
        self.path_label.setStyleSheet("color: #5A6A90; background: transparent; letter-spacing: 0.2px;")
        lay.addWidget(self.path_label)

        self.change_btn = QPushButton("change")
        self.change_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.change_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none;
                color: #2E3A58; font-size: 10px; font-weight: 600;
                padding: 0 4px; letter-spacing: 0.5px;
            }
            QPushButton:hover { color: #6080C8; }
        """)
        self.change_btn.clicked.connect(self.folder_change_requested.emit)
        lay.addWidget(self.change_btn)

        lay.addStretch()

        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setToolTip("Refresh workspace")
        self.refresh_btn.setFixedSize(28, 28)
        self.refresh_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 7px; color: #2E3A58;
                font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { background: rgba(255,255,255,0.10); color: #6080C8; }
        """)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        lay.addWidget(self.refresh_btn)

        self.auto_btn = QPushButton()
        self.auto_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.auto_btn.setToolTip(
            "Auto-Run ON: Luna executes tools automatically.\n"
            "Auto-Run OFF: Luna asks for approval before each action."
        )
        self.auto_btn.setFixedHeight(30)
        self._update_auto_btn()
        self.auto_btn.clicked.connect(self._toggle_auto)
        lay.addWidget(self.auto_btn)

    def _short_path(self) -> str:
        return f"  {self.workspace.root.name}"

    def update_workspace(self):
        self.path_label.setText(self._short_path())
        self.path_label.setToolTip(str(self.workspace.root))

    def _toggle_auto(self):
        self.auto_run = not self.auto_run
        self._update_auto_btn()
        self.auto_run_toggled.emit(self.auto_run)

    def _update_auto_btn(self):
        if self.auto_run:
            self.auto_btn.setText("⚡  Auto-Run  ON")
            col = "#7C8CF8" if self.luna else "#DA7756"
            self.auto_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {col};
                    color: #FFFFFF; border: none;
                    border-radius: 6px; padding: 0 12px;
                    font-size: 11px; font-weight: 700; letter-spacing: 0.3px;
                }}
                QPushButton:hover {{
                    background: {col}EE;
                }}
            """)
        else:
            self.auto_btn.setText("⏸  Auto-Run  OFF")
            self.auto_btn.setStyleSheet("""
                QPushButton {{
                    background: rgba(255,255,255,0.04);
                    color: #9C978D;
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 6px; padding: 0 12px;
                    font-size: 11px; font-weight: 600;
                }}
                QPushButton:hover {{ background: rgba(255,255,255,0.08); color: #ECE8E1; }}
            """)

    def set_luna_mode(self, luna: bool):
        self.luna = luna
        self._apply_style()

    def _apply_style(self):
        if self.luna:
            bg, border = "#0D1118", "#1E2536"
        else:
            bg, border = "#191815", "#2B2A25"
        self.setStyleSheet(f"""
            QFrame#workspaceBar {{
                background: {bg};
                border-bottom: 1px solid {border};
            }}
            QLabel {{ background: transparent; }}
        """)


# ─────────────────────────────────────────────────────────────────────────────
# WorkspaceFileTree
# ─────────────────────────────────────────────────────────────────────────────
class WorkspaceFileTree(QFrame):
    """File explorer sidebar panel with file-type icons and size labels."""

    file_selected = pyqtSignal(str)

    def __init__(self, workspace: WorkspaceManager, luna: bool = True, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.luna      = luna
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("workspaceFileTree")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        lay.setSpacing(8)

        # header row
        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        ico = QLabel("📁")
        ico.setStyleSheet("font-size: 14px; background: transparent;")
        hdr.addWidget(ico)

        ttl = QLabel("Workspace Files")
        ttl.setFont(QFont("Segoe UI", 11, QFont.Bold))
        ttl.setStyleSheet("color: #64748B; background: transparent;")
        hdr.addWidget(ttl, 1)

        ref = QPushButton("⟳")
        ref.setFixedSize(24, 24)
        ref.setCursor(QCursor(Qt.PointingHandCursor))
        ref.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px; color: #475569;
                font-size: 13px; font-weight: bold;
            }
            QPushButton:hover { color: #94A3B8; background: rgba(255,255,255,0.06); }
        """)
        ref.clicked.connect(self.refresh_tree)
        hdr.addWidget(ref)
        lay.addLayout(hdr)

        # tree
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)
        self.tree.setStyleSheet("""
            QTreeWidget {
                background: rgba(4,8,22,0.55);
                color: #94A3B8;
                border: 1px solid rgba(255,255,255,0.05);
                border-radius: 10px; padding: 6px;
                font-family: 'Segoe UI', Arial; font-size: 12px; outline: none;
            }
            QTreeWidget::item { padding: 4px 6px; border-radius: 6px; }
            QTreeWidget::item:hover {
                background: rgba(99,102,241,0.12); color: #C7D2FE;
            }
            QTreeWidget::item:selected {
                background: rgba(99,102,241,0.25); color: #E0E7FF; border: none;
            }
            QScrollBar:vertical {
                background: transparent; width: 5px; border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.12); border-radius: 3px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)
        self.tree.itemDoubleClicked.connect(self._on_double)
        lay.addWidget(self.tree)
        self.refresh_tree()

    def refresh_tree(self):
        self.tree.clear()
        res     = self.workspace.list_dir(recursive=True, max_depth=3)
        entries = res.get("entries", [])
        nodes   = {}

        for e in entries:
            rel    = e.get("rel_path", "")
            is_dir = e.get("type") == "dir"
            name   = e.get("name", "")
            size   = e.get("size")

            icon    = "📁" if is_dir else self._icon(name)
            display = f"{icon}  {name}"
            if not is_dir and size is not None:
                if size < 1024:
                    sz = f"{size} B"
                elif size < 1_048_576:
                    sz = f"{size // 1024} KB"
                else:
                    sz = f"{size // 1_048_576} MB"
                display += f"   [{sz}]"

            item = QTreeWidgetItem([display])
            item.setData(0, Qt.UserRole, rel)

            parts = Path(rel).parts
            if len(parts) <= 1:
                self.tree.addTopLevelItem(item)
            else:
                parent_path = str(Path(rel).parent).replace("\\", "/")
                parent_node = nodes.get(parent_path)
                if parent_node:
                    parent_node.addChild(item)
                else:
                    self.tree.addTopLevelItem(item)
            nodes[rel] = item

        self.tree.expandToDepth(0)

    def _icon(self, name: str) -> str:
        ext = Path(name).suffix.lower()
        return {
            ".html": "🌐", ".htm": "🌐",
            ".css": "🎨", ".scss": "🎨", ".sass": "🎨",
            ".js": "⚡", ".jsx": "⚡",
            ".ts": "🔷", ".tsx": "🔷",
            ".py": "🐍", ".pyw": "🐍",
            ".json": "📋", ".yaml": "📋", ".yml": "📋",
            ".md": "📝", ".txt": "📝",
            ".sh": "⚙", ".bat": "⚙", ".ps1": "⚙",
            ".svg": "🖼", ".png": "🖼", ".jpg": "🖼",
            ".jpeg": "🖼", ".gif": "🖼", ".webp": "🖼",
            ".go": "🐹", ".rs": "🦀", ".java": "☕",
            ".cpp": "⚙", ".c": "⚙",
            ".sql": "🗃", ".db": "🗃",
        }.get(ext, "📄")

    def _on_double(self, item, col):
        rel = item.data(0, Qt.UserRole)
        if rel:
            self.file_selected.emit(rel)
