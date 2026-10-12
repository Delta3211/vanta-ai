import sys
import json
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md_to_text
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal, QPropertyAnimation, pyqtProperty, QEasingCurve
from PyQt5.QtGui import QFont, QIcon, QPixmap, QTextDocument
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from workspace import WorkspaceManager
from agent import AgentThread
from agent_ui import ToolCardWidget, WorkspaceBar, WorkspaceFileTree


def extract_file_text(path: str) -> str:
    """Extract readable text from a file. Supports txt, md, pdf, docx, csv, and most code files."""
    p = Path(path)
    ext = p.suffix.lower()

    try:
        # Plain text / code / markup
        if ext in (".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".html",
                   ".css", ".json", ".xml", ".yaml", ".yml", ".ini", ".cfg",
                   ".sh", ".bat", ".c", ".cpp", ".h", ".java", ".cs", ".rb",
                   ".go", ".rs", ".swift", ".kt", ".csv", ".log"):
            return p.read_text(encoding="utf-8", errors="replace")

        # Word documents
        if ext in (".docx",):
            import docx
            doc = docx.Document(path)
            return "\n".join(para.text for para in doc.paragraphs)

        # PDF
        if ext == ".pdf":
            import PyPDF2
            text = []
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text.append(page.extract_text() or "")
            return "\n".join(text)

        # Images — describe that they were attached but can't be read as text
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"):
            return f"[Image file attached: {p.name} — image content cannot be extracted as text]"

        # Fallback: try reading as text anyway
        return p.read_text(encoding="utf-8", errors="replace")

    except Exception as e:
        return f"[Could not read file '{p.name}': {e}]"


APP_NAME = "Sierra"
APP_VERSION = "1.2.0"
MODEL_NAME = "llama3"
LUNA_MODEL_NAME = "luna-1.1"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "sierra-desert-icon.png"
LUNA_ICON_PATH = Path(__file__).resolve().parent / "assets" / "luna-icon.png"
CHATS_DIR = Path.home() / ".sierra" / "chats"
CHATS_DIR.mkdir(parents=True, exist_ok=True)


def web_search(query):
    """Fetch concise DuckDuckGo notes when live context is enabled."""
    try:
        response = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results = [
            link.get_text(" ", strip=True)
            for link in soup.select("a.result__a")[:5]
        ]
        return "\n".join(results) if results else "No search results found."
    except Exception as exc:
        return f"Search failed: {exc}"


class ChatThread(QThread):
    """Run Ollama and optional web lookup without freezing the interface."""

    response_ready = pyqtSignal(str)
    stream_chunk = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, messages, use_search=False, stream=False, temperature=0.7, model=None):
        super().__init__()
        self.messages = list(messages)
        self.use_search = use_search
        self.stream = stream
        self.temperature = temperature
        self.model = model or MODEL_NAME

    def run(self):
        try:
            if self.use_search and self.messages:
                query = self.messages[-1].content
                self.messages.insert(
                    -1,
                    SystemMessage(
                        content=(
                            "Fresh web-search notes are below. Use them when helpful, "
                            "but be candid if they are incomplete or inconclusive.\n\n"
                            + web_search(query)
                        )
                    ),
                )

            if self.stream:
                # Streaming response
                llm = ChatOllama(model=self.model, temperature=self.temperature)
                full_response = ""
                for chunk in llm.stream(self.messages):
                    if hasattr(chunk, 'content'):
                        content = chunk.content
                        full_response += content
                        self.stream_chunk.emit(content)
                self.response_ready.emit(full_response)
            else:
                # Non-streaming response
                answer = ChatOllama(model=self.model, temperature=self.temperature).invoke(self.messages)
                self.response_ready.emit(str(answer.content))
        except Exception as exc:
            self.error.emit(str(exc))


class SierraMark(QLabel):
    """Display the supplied icon with a rounded gradient badge."""

    def __init__(self, size=52, luna=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self._size = size
        self._luna = luna
        icon_path = LUNA_ICON_PATH if luna and LUNA_ICON_PATH.exists() else ICON_PATH
        pixmap = QPixmap(str(icon_path))
        if pixmap.isNull():
            self.setText("L" if luna else "S")
            self.setObjectName("iconFallback")
            return
        self.setPixmap(
            pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QLinearGradient, QColor, QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        r = self._size * 0.28
        path = QPainterPath()
        path.addRoundedRect(0, 0, self._size, self._size, r, r)
        if self._luna:
            grad = QLinearGradient(0, 0, self._size, self._size)
            grad.setColorAt(0.0, QColor("#6366F1"))
            grad.setColorAt(1.0, QColor("#3730A3"))
        else:
            grad = QLinearGradient(0, 0, self._size, self._size)
            grad.setColorAt(0.0, QColor("#DA7756"))
            grad.setColorAt(1.0, QColor("#B25638"))
        painter.fillPath(path, grad)
        painter.end()
        super().paintEvent(event)


class GradientFrame(QFrame):
    """Refined elevated container with subtle border — adapts to Sierra / Luna theme."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QColor, QPainterPath, QPen
        from PyQt5.QtWidgets import QApplication
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        use_luna = False
        app = QApplication.instance()
        if app:
            for widget in app.topLevelWidgets():
                if hasattr(widget, 'use_luna'):
                    use_luna = widget.use_luna
                    break
        if use_luna:
            fill_color = QColor("#141A26")
            border_color = QColor(255, 255, 255, 22)
            glow_color = QColor(124, 140, 248, 22)
        else:
            fill_color = QColor("#22201C")
            border_color = QColor(255, 255, 255, 22)
            glow_color = QColor(218, 119, 86, 22)
        rad = 18
        path = QPainterPath()
        path.addRoundedRect(1, 1, w - 2, h - 2, rad, rad)
        painter.fillPath(path, fill_color)

        glow_pen = QPen(glow_color, 2)
        painter.setPen(glow_pen)
        painter.drawPath(path)

        pen = QPen(border_color, 1)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()


class TrafficButton(QPushButton):
    def __init__(self, object_name, tooltip, parent=None):
        super().__init__("", parent)
        self.setObjectName(object_name)
        self.setToolTip(tooltip)
        self.setFixedSize(40, 28)
        self.setCursor(Qt.PointingHandCursor)
        if object_name == "trafficClose":
            self.setText("✕")
        elif object_name == "trafficMinimize":
            self.setText("−")
        elif object_name == "trafficMaximize":
            self.setText("⬜")


class TitleBar(QFrame):
    """Sleek frameless title bar with drag, action buttons and window controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self._drag_origin = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 0, 0)
        layout.setSpacing(8)

        # Active chat breadcrumb
        crumb_icon = QLabel("◈")
        crumb_icon.setObjectName("titleIcon")
        layout.addWidget(crumb_icon)
        self.title_label = QLabel("New Chat")
        self.title_label.setObjectName("titleText")
        layout.addWidget(self.title_label)
        layout.addStretch()

        # Action buttons
        for glyph, tooltip, obj in (
            ("✎",  "New Chat",  "titleNewChat"),
            ("💾", "Save Chat", "titleSave"),
            ("📂", "Open Chat", "titleOpen"),
        ):
            btn = QPushButton(glyph)
            btn.setObjectName("topIconButton")
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(36, 36)
            if tooltip == "New Chat":
                btn.clicked.connect(lambda checked=False: self.window().start_new_chat())
            elif tooltip == "Save Chat":
                btn.clicked.connect(lambda checked=False: self.window().save_conversation())
            elif tooltip == "Open Chat":
                btn.clicked.connect(lambda checked=False: self.window().load_conversation())
            layout.addWidget(btn)

        layout.addSpacing(4)
        layout.addWidget(WindowControls())

    def _toggle_maximize(self):
        window = self.window()
        window.showNormal() if window.isMaximized() else window.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin and event.buttons() & Qt.LeftButton:
            delta = event.globalPos() - self._drag_origin
            self.window().move(self.window().pos() + delta)
            self._drag_origin = event.globalPos()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._toggle_maximize()


class WindowControls(QFrame):
    """Window controls positioned on the right side of title bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("windowControls")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(0)
        close = TrafficButton("trafficClose", "Close")
        minimize = TrafficButton("trafficMinimize", "Minimize")
        maximize = TrafficButton("trafficMaximize", "Maximize")
        close.clicked.connect(lambda: self.window().close())
        minimize.clicked.connect(lambda: self.window().showMinimized())
        maximize.clicked.connect(self._toggle_maximize)
        layout.addWidget(close)
        layout.addWidget(minimize)
        layout.addWidget(maximize)

    def _toggle_maximize(self):
        window = self.window()
        window.showNormal() if window.isMaximized() else window.showMaximized()


class ChatInput(QTextEdit):
    submitted = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)
        ):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class NavButton(QPushButton):
    def __init__(self, icon, label, parent=None):
        super().__init__(f"{icon}   {label}", parent)
        self.setObjectName("navButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setCheckable(True)


class RecentChat(QPushButton):
    def __init__(self, title, age, parent=None):
        super().__init__(parent)
        self.setObjectName("recentChat")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)
        icon = QLabel("💬")
        icon.setObjectName("recentIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(26, 26)
        layout.addWidget(icon)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        name = QLabel(title)
        name.setObjectName("recentName")
        time = QLabel(age)
        time.setObjectName("recentAge")
        labels.addWidget(name)
        labels.addWidget(time)
        layout.addLayout(labels)
        layout.addStretch()


class Sidebar(QFrame):
    new_chat_requested = pyqtSignal()
    search_toggled = pyqtSignal(bool)
    luna_toggled = pyqtSignal(bool)
    chat_loaded = pyqtSignal(str)

    def __init__(self, workspace=None, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.setObjectName("sidebar")
        self.setFixedWidth(270)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 22, 14, 18)
        layout.setSpacing(8)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self.brand_icon = SierraMark(40)
        brand_row.addWidget(self.brand_icon)
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(1)
        self.wordmark = QLabel(f"{APP_NAME} <span>{APP_VERSION}</span>")
        self.wordmark.setObjectName("wordmark")
        self.descriptor = QLabel("Your private AI assistant")
        self.descriptor.setObjectName("brandDescription")
        brand_copy.addWidget(self.wordmark)
        brand_copy.addWidget(self.descriptor)
        brand_row.addLayout(brand_copy)
        brand_row.addStretch()
        layout.addLayout(brand_row)
        layout.addSpacing(22)

        self.new_chat = NavButton("＋", "New Chat")
        self.new_chat.setObjectName("navButtonActive")
        self.new_chat.setChecked(True)
        self.new_chat.clicked.connect(self._new_chat)
        layout.addWidget(self.new_chat)

        self.search = NavButton("⌕", "Search")
        self.search.toggled.connect(self._search_toggled)
        self.search.clicked.connect(lambda checked=False: self._select(self.search))
        layout.addWidget(self.search)

        self.luna_button = NavButton("🌙", "Luna  —  Coding AI")
        self.luna_button.setObjectName("lunaButton")
        self.luna_button.setCheckable(True)
        self.luna_button.toggled.connect(self._luna_toggled)
        layout.addWidget(self.luna_button)

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        divider.setFrameShape(QFrame.HLine)
        layout.addSpacing(24)
        layout.addWidget(divider)
        layout.addSpacing(14)

        self.recent_heading = QLabel("Recent Chats")
        self.recent_heading.setObjectName("sectionHeading")
        layout.addWidget(self.recent_heading)

        # Load actual saved chats
        self.recent_chats_widget = QWidget()
        self.recent_chats_layout = QVBoxLayout(self.recent_chats_widget)
        self.recent_chats_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_chats_layout.setSpacing(6)
        self._load_recent_chats()
        layout.addWidget(self.recent_chats_widget)

        # Workspace File Tree (visible in Luna mode)
        self.file_tree = WorkspaceFileTree(self.workspace or WorkspaceManager())
        self.file_tree.setVisible(False)
        layout.addWidget(self.file_tree)

        layout.addStretch()

        model_card = QFrame()
        model_card.setObjectName("sidebarModelCard")
        model_layout = QHBoxLayout(model_card)
        model_layout.setContentsMargins(10, 11, 9, 11)
        model_layout.setSpacing(10)
        self.model_card_icon = SierraMark(42)
        model_layout.addWidget(self.model_card_icon)
        model_copy = QVBoxLayout()
        model_copy.setSpacing(1)
        self.model_card_title = QLabel(f"{APP_NAME} {APP_VERSION}")
        self.model_card_title.setObjectName("sidebarModelTitle")
        self.model_card_subtitle = QLabel("Llama 3 · 8B · Local")
        self.model_card_subtitle.setObjectName("sidebarModelSubtitle")
        online = QLabel("●  Online")
        online.setObjectName("onlineIndicator")
        model_copy.addWidget(self.model_card_title)
        model_copy.addWidget(self.model_card_subtitle)
        model_copy.addWidget(online)
        model_layout.addLayout(model_copy)
        model_layout.addStretch()
        chevron = QLabel("›")
        chevron.setObjectName("cardChevron")
        model_layout.addWidget(chevron)
        layout.addWidget(model_card)

    def update_branding(self, luna=False):
        """Swap sidebar logo, wordmark, model card, and explorer between Sierra and Luna."""
        from PyQt5.QtGui import QPixmap
        icon_path = LUNA_ICON_PATH if luna and LUNA_ICON_PATH.exists() else ICON_PATH
        pixmap = QPixmap(str(icon_path))
        size_brand = self.brand_icon._size
        size_card  = self.model_card_icon._size
        if not pixmap.isNull():
            self.brand_icon.setPixmap(pixmap.scaled(size_brand, size_brand, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.model_card_icon.setPixmap(pixmap.scaled(size_card, size_card, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.brand_icon._luna = luna
        self.model_card_icon._luna = luna
        self.brand_icon.update()
        self.model_card_icon.update()
        if luna:
            self.wordmark.setText("Luna <span>Agent</span>")
            self.descriptor.setText("Autonomous Coding AI")
            self.model_card_title.setText("Luna 1.1")
            self.model_card_subtitle.setText("Luna 1.1 · 14B · Local")
            if hasattr(self, 'recent_heading'):
                self.recent_heading.setText("Workspace Files")
            if hasattr(self, 'file_tree'):
                self.file_tree.setVisible(True)
            if hasattr(self, 'recent_chats_widget'):
                self.recent_chats_widget.setVisible(False)
        else:
            self.wordmark.setText(f"{APP_NAME} <span>{APP_VERSION}</span>")
            self.descriptor.setText("Your local Llama assistant")
            self.model_card_title.setText(f"{APP_NAME} {APP_VERSION}")
            self.model_card_subtitle.setText("Llama 3 · 8B · Local")
            if hasattr(self, 'recent_heading'):
                self.recent_heading.setText("Recent Chats")
            if hasattr(self, 'file_tree'):
                self.file_tree.setVisible(False)
            if hasattr(self, 'recent_chats_widget'):
                self.recent_chats_widget.setVisible(True)

    def _new_chat(self):
        self._select(self.new_chat)
        self.new_chat_requested.emit()

    def _select(self, selected):
        for button in (self.new_chat, self.search):
            if button is not selected:
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
        if selected is not self.search:
            selected.setChecked(True)

    def _search_toggled(self, enabled):
        self.search.setText("⌕    Search  ON" if enabled else "⌕    Search")
        self.search_toggled.emit(enabled)

    def _luna_toggled(self, enabled):
        self.luna_button.setText("🌙    Luna  ON" if enabled else "🌙    Luna  —  Coding AI")
        self.luna_toggled.emit(enabled)

    def _load_recent_chats(self):
        """Load and display recent saved chats"""
        # Clear existing
        while self.recent_chats_layout.count():
            item = self.recent_chats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Get all chat files
        chat_files = []
        if CHATS_DIR.exists():
            for file in CHATS_DIR.glob("*.json"):
                if file.name != "latest.json":
                    try:
                        with open(file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            timestamp = data.get("timestamp", "")
                            title = data.get("title", "Untitled Chat")
                            # Clean up title - remove special chars and limit length
                            title = title.strip()
                            if len(title) > 25:
                                title = title[:25] + "..."
                            if not title or title == "...":
                                title = "Untitled Chat"
                            chat_files.append((file, timestamp, title))
                    except Exception:
                        pass

        # Sort by timestamp (newest first)
        chat_files.sort(key=lambda x: x[1] if x[1] else "", reverse=True)

        # Display up to 5 recent chats
        for file, timestamp, title in chat_files[:5]:
            # Calculate age
            try:
                chat_time = datetime.fromisoformat(timestamp)
                now = datetime.now()
                diff = now - chat_time

                if diff.days > 0:
                    age = f"{diff.days}d ago"
                elif diff.seconds >= 3600:
                    age = f"{diff.seconds // 3600}h ago"
                else:
                    age = f"{diff.seconds // 60}m ago"
            except Exception:
                age = "Unknown"

            chat_widget = RecentChat(title, age)
            # Store file path for loading
            chat_widget.setProperty("chat_file", str(file))
            chat_widget.clicked.connect(lambda checked, f=str(file): self.chat_loaded.emit(f))
            self.recent_chats_layout.addWidget(chat_widget)

        if chat_files:
            # Show the widget
            self.recent_chats_widget.setVisible(True)
        else:
            # Show "No recent chats" message
            no_chats = QLabel("No recent chats")
            no_chats.setObjectName("noChatsLabel")
            no_chats.setAlignment(Qt.AlignCenter)
            self.recent_chats_layout.addWidget(no_chats)

    def refresh_recent_chats(self):
        """Refresh the recent chats list"""
        self._load_recent_chats()


class ActionCard(QPushButton):
    def __init__(self, icon, title, subtitle, prompt, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.setObjectName("actionCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(72)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        icon_label = QLabel(icon)
        icon_label.setObjectName("actionIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(36, 36)
        layout.addWidget(icon_label)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("actionTitle")
        detail = QLabel(subtitle)
        detail.setObjectName("actionSubtitle")
        detail.setWordWrap(True)
        copy.addWidget(heading)
        copy.addWidget(detail)
        layout.addLayout(copy, 1)
        arrow = QLabel("›")
        arrow.setObjectName("cardChevron")
        layout.addWidget(arrow)


class WelcomeView(QWidget):
    prompt_chosen = pyqtSignal(str)

    def __init__(self, luna=False, parent=None):
        super().__init__(parent)
        self._luna = luna
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 24, 56, 24)
        layout.setSpacing(0)
        layout.addStretch(1)

        mark_row = QHBoxLayout()
        mark_row.addStretch()
        mark_row.addWidget(SierraMark(68, luna=self._luna))
        mark_row.addStretch()
        layout.addLayout(mark_row)
        layout.addSpacing(18)

        if self._luna:
            title = QLabel("Luna <span>Agent</span>")
            subtitle_text = "How can I help you build today?"
            desc_text = "Autonomous coding AI with workspace awareness · Reads files, writes code, and runs tools."
        else:
            title = QLabel(f"{APP_NAME} <span>{APP_VERSION}</span>")
            subtitle_text = "How can I help you today?"
            desc_text = "Ask questions, analyze documents, write and review code, or explore ideas."

        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(8)
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("heroSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        description = QLabel(desc_text)
        description.setObjectName("heroDescription")
        description.setAlignment(Qt.AlignCenter)
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addSpacing(34)

        if self._luna:
            entries = (
                ("⚡", "Run & Build",       "Execute tests or shell commands in project.", "Run tests and verify our current workspace: "),
                ("📝", "Create Feature",     "Write new modules, files, or components.",    "Create a new feature for: "),
                ("🐛", "Diagnose & Fix",     "Inspect files and repair bugs.",              "Find and fix bugs in our project: "),
                ("📁", "Explore Codebase",   "Survey project architecture and files.",      "Analyze this workspace and describe its key components."),
            )
        else:
            entries = (
                ("✦", "Explain a Topic",     "Break down complex ideas with clarity.",      "Explain this concept clearly and intuitively: "),
                ("</>", "Write & Debug",      "Build features, fix bugs, or optimize.",      "Help me write clean code for: "),
                ("▤", "Summarize Notes",     "Extract key takeaways and action items.",     "Summarize the following in clear bullet points: "),
                ("✧", "Brainstorm Ideas",    "Explore fresh strategies and creative plans.","Brainstorm practical and creative ideas for: "),
            )
        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(12)
        for index, (icon, title_text, detail, prompt) in enumerate(entries):
            card = ActionCard(icon, title_text, detail, prompt)
            card.clicked.connect(lambda checked=False, text=prompt: self.prompt_chosen.emit(text))
            cards.addWidget(card, index // 2, index % 2)
        layout.addLayout(cards)
        layout.addStretch(2)


class MessageWidget(QWidget):
    regenerate_requested = pyqtSignal(object)   # emits self

    def __init__(self, message, is_user, luna=False, parent=None):
        super().__init__(parent)
        self.is_user  = is_user
        self.luna     = luna
        self._raw_text = message  # keep original markdown for copy
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(12)

        # Avatar - Claude style starburst for AI
        av_text = "YOU" if is_user else "\u273b"
        self.avatar = QLabel(av_text)
        self.avatar.setObjectName("userAvatar" if is_user else "assistantAvatar")
        self.avatar.setFixedSize(32, 32)
        self.avatar.setAlignment(Qt.AlignCenter)

        # Outer column: avatar + content + action bar
        col_widget = QWidget()
        col_widget.setStyleSheet("background: transparent;")
        col_layout = QVBoxLayout(col_widget)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(0)

        # Content container (bubble + code blocks)
        self.content_container = QWidget()
        self.content_container.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)

        self.bubble = QTextEdit()
        self.bubble.setObjectName("userMessage" if is_user else "assistantMessage")
        self.bubble.setReadOnly(True)
        self.bubble.setLineWrapMode(QTextEdit.WidgetWidth)
        self.bubble.setFont(QFont("Segoe UI", 14))
        self.bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.bubble.setMinimumHeight(44)
        self.bubble.document().setDocumentMargin(8 if is_user else 2)

        if is_user:
            if luna:
                self.bubble.setStyleSheet(
                    "QTextEdit { background: #162032; color: #F0F4FC; "
                    "border-radius: 16px; padding: 12px 18px; "
                    "border: 1px solid #23314D; font-size: 14px; }"
                )
            else:
                self.bubble.setStyleSheet(
                    "QTextEdit { background: #2A2722; color: #FAF7F2; "
                    "border-radius: 16px; padding: 12px 18px; "
                    "border: 1px solid rgba(255,255,255,0.08); font-size: 14px; }"
                )
        else:
            # Claude style: AI responses flow naturally unboxed
            if luna:
                self.bubble.setStyleSheet(
                    "QTextEdit { background: transparent; color: #F0F4F8; "
                    "border: none; padding: 2px 4px; font-size: 14px; }"
                )
            else:
                self.bubble.setStyleSheet(
                    "QTextEdit { background: transparent; color: #ECE8E1; "
                    "border: none; padding: 2px 4px; font-size: 14px; }"
                )

        self.content_layout.addWidget(self.bubble)
        col_layout.addWidget(self.content_container)

        # ── Action bar (AI messages only) ──────────────────────────────────
        if not is_user:
            self._action_bar = self._build_action_bar()
            col_layout.addWidget(self._action_bar)

        self.set_message_text(message)
        self._adjust_height()

        if is_user:
            root.addStretch(1)
            root.addWidget(col_widget, 3)
            root.addWidget(self.avatar)
        else:
            root.addWidget(self.avatar)
            root.addWidget(col_widget, 1)

    def _build_action_bar(self):
        """Build the slim row of action buttons shown under AI messages."""
        accent = "#7C8CF8" if self.luna else "#DA7756"
        bar = QWidget()
        bar.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(2, 4, 0, 0)
        lay.setSpacing(4)

        _btn_style = (
            "QPushButton { color: #7D796F; background: transparent; border: none; "
            "border-radius: 5px; font-size: 11px; padding: 3px 8px; font-weight: 500; }"
            f"QPushButton:hover {{ color: {accent}; background: rgba(255,255,255,0.05); }}"
        )

        copy_btn = QPushButton("\u2398  Copy")
        copy_btn.setObjectName("msgActionBtn")
        copy_btn.setToolTip("Copy response to clipboard")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet(_btn_style)
        copy_btn.clicked.connect(self._copy_response)
        lay.addWidget(copy_btn)
        self._copy_btn = copy_btn

        regen_btn = QPushButton("\u21ba  Regenerate")
        regen_btn.setObjectName("msgActionBtn")
        regen_btn.setToolTip("Re-run this response")
        regen_btn.setCursor(Qt.PointingHandCursor)
        regen_btn.setStyleSheet(_btn_style)
        regen_btn.clicked.connect(lambda: self.regenerate_requested.emit(self))
        lay.addWidget(regen_btn)
        self._regen_btn = regen_btn

        lay.addStretch()
        return bar

    def _copy_response(self):
        QApplication.clipboard().setText(self._raw_text)
        self._copy_btn.setText("\u2713  Copied!")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText("\u2398  Copy"))

    def _adjust_height(self):
        self.bubble.document().adjustSize()
        doc_h = self.bubble.document().size().height()
        self.bubble.setFixedHeight(int(doc_h) + 20)

    def set_message_text(self, text):
        """Render markdown to HTML in bubble; render code blocks as premium panels below."""
        import markdown as md_lib
        import re

        if self.luna:
            text_color = "#F0F4FC" if self.is_user else "#F0F4F8"
        else:
            text_color = "#FAF7F2" if self.is_user else "#ECE8E1"

        # ── Language-specific color themes ─────────────────────────────────
        _LANG_THEMES = {
            "html":       ("#FF8C42", "#1A0C00", "#2A1200", "#FFB347"),
            "css":        ("#C084FC", "#120A1A", "#1E1028", "#DDD6FE"),
            "scss":       ("#C084FC", "#120A1A", "#1E1028", "#DDD6FE"),
            "javascript": ("#FCD34D", "#131000", "#1F1A00", "#FEF08A"),
            "js":         ("#FCD34D", "#131000", "#1F1A00", "#FEF08A"),
            "typescript": ("#60A5FA", "#020C1A", "#081428", "#BFDBFE"),
            "ts":         ("#60A5FA", "#020C1A", "#081428", "#BFDBFE"),
            "jsx":        ("#67E8F9", "#001414", "#002020", "#A5F3FC"),
            "tsx":        ("#67E8F9", "#001414", "#002020", "#A5F3FC"),
            "python":     ("#4ADE80", "#011A08", "#032810", "#BBF7D0"),
            "py":         ("#4ADE80", "#011A08", "#032810", "#BBF7D0"),
            "bash":       ("#34D399", "#011A0E", "#022816", "#A7F3D0"),
            "sh":         ("#34D399", "#011A0E", "#022816", "#A7F3D0"),
            "json":       ("#FBBF24", "#130E00", "#1F1600", "#FDE68A"),
            "yaml":       ("#A78BFA", "#0D0A1A", "#160F28", "#C4B5FD"),
            "sql":        ("#FB923C", "#1A0A00", "#281000", "#FDBA74"),
            "go":         ("#67E8F9", "#001414", "#002020", "#A5F3FC"),
            "rust":       ("#FB923C", "#1A0A00", "#281000", "#FDBA74"),
            "rs":         ("#FB923C", "#1A0A00", "#281000", "#FDBA74"),
        }
        _DEFAULT_THEME = ("#94A3B8", "#080C14", "#0E1420", "#CBD5E1")

        # ── Split text into plain text + code blocks ────────────────────────
        pattern = r'```(\w*)\n?([\s\S]*?)```'
        parts   = re.split(pattern, text)

        plain_parts = []
        code_blocks = []
        i = 0
        while i < len(parts):
            seg = parts[i]
            if seg:
                plain_parts.append(seg)
            i += 1
            if i < len(parts):
                lang = parts[i] or "code"
                i += 1
                if i < len(parts):
                    code_blocks.append((lang, parts[i]))
                    i += 1

        # ── Render plain text ──────────────────────────────────────────────
        combined = "\n\n".join(p.strip() for p in plain_parts if p.strip())
        if combined:
            html_body = md_lib.markdown(
                combined,
                extensions=["tables", "nl2br", "sane_lists"],
            )
            html = (
                f'<html><body style="font-family: Segoe UI, Inter, Arial, sans-serif;'
                f'font-size:15px;line-height:1.7;color:{text_color};margin:0;padding:0;">'
                f'{html_body}</body></html>'
            )
            self.bubble.setHtml(html)

        # ── Remove stale code block panels ────────────────────────────────
        while self.content_layout.count() > 1:
            item = self.content_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        # ── Render code block panels ───────────────────────────────────────
        cb_bg = "#0C1017" if self.luna else "#141311"
        hdr_bg = "#131924" if self.luna else "#1B1A17"
        code_color = "#E2E8F0" if self.luna else "#E6E2D8"
        accent_color = "#7C8CF8" if self.luna else "#DA7756"

        for lang, code in code_blocks:
            # Outer frame
            code_frame = QFrame()
            code_frame.setStyleSheet(
                f"QFrame {{ background: {cb_bg}; border: 1px solid rgba(255,255,255,0.08); "
                f"border-radius: 10px; }}"
            )
            cf_lay = QVBoxLayout(code_frame)
            cf_lay.setContentsMargins(0, 0, 0, 0)
            cf_lay.setSpacing(0)

            # Header bar
            hdr_widget = QWidget()
            hdr_widget.setStyleSheet(
                f"background: {hdr_bg}; "
                f"border-bottom: 1px solid rgba(255,255,255,0.06); "
                f"border-top-left-radius: 10px; border-top-right-radius: 10px;"
            )
            hdr_lay = QHBoxLayout(hdr_widget)
            hdr_lay.setContentsMargins(14, 6, 10, 6)
            hdr_lay.setSpacing(8)

            # Language pill badge
            lang_pill = QLabel(lang.upper() if lang else "CODE")
            lang_pill.setStyleSheet(
                f"color: #A8A398; background: rgba(255,255,255,0.05); "
                f"border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; "
                f"font-size: 11px; font-weight: 700; "
                f"font-family: 'Consolas', monospace; "
                f"padding: 2px 7px; letter-spacing: 0.5px;"
            )
            hdr_lay.addWidget(lang_pill)
            hdr_lay.addStretch()

            # Save to workspace button
            save_btn = QPushButton("💾  Save to File")
            save_btn.setFixedHeight(26)
            save_btn.setCursor(Qt.PointingHandCursor)
            save_btn.setStyleSheet(
                f"QPushButton {{ color: {accent_color}; background: {accent_color}18; "
                f"border: 1px solid {accent_color}35; border-radius: 5px; "
                f"font-size: 11px; font-weight: 600; padding: 0 10px; margin-right: 4px; }}"
                f"QPushButton:hover {{ background: {accent_color}30; color: white; }}"
            )
            captured_code = code
            captured_lang = lang
            save_btn.clicked.connect(
                lambda _, c=captured_code, l=captured_lang, b=save_btn:
                    self._save_code_to_workspace(c, l, b)
            )
            hdr_lay.addWidget(save_btn)

            # Copy button
            copy_btn = QPushButton("Copy")
            copy_btn.setFixedHeight(26)
            copy_btn.setCursor(Qt.PointingHandCursor)
            copy_btn.setStyleSheet(
                f"QPushButton {{ color: #A8A398; background: rgba(255,255,255,0.04); "
                f"border: 1px solid rgba(255,255,255,0.08); border-radius: 5px; "
                f"font-size: 11px; font-weight: 600; padding: 0 10px; }}"
                f"QPushButton:hover {{ background: rgba(255,255,255,0.10); color: white; }}"
            )
            copy_btn.clicked.connect(
                lambda _, c=captured_code: QApplication.clipboard().setText(c)
            )
            hdr_lay.addWidget(copy_btn)
            cf_lay.addWidget(hdr_widget)

            # Code content
            code_edit = QTextEdit()
            code_edit.setReadOnly(True)
            code_edit.setLineWrapMode(QTextEdit.NoWrap)
            code_edit.setFont(QFont("Consolas", 13))
            code_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            code_edit.document().setDocumentMargin(0)
            code_edit.setStyleSheet(
                f"QTextEdit {{ background: transparent; border: none; "
                f"color: {code_color}; "
                f"font-family: 'Cascadia Code', 'Consolas', monospace; "
                f"font-size: 13px; padding: 14px 18px; }}"
                f"QScrollBar:horizontal {{ background: transparent; height: 5px; border-radius: 3px; }}"
                f"QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.15); border-radius: 3px; }}"
            )
            code_edit.setPlainText(code.strip())
            code_edit.document().adjustSize()
            code_h = int(code_edit.document().size().height()) + 36
            code_edit.setFixedHeight(min(code_h, 520))
            cf_lay.addWidget(code_edit)

            self.content_layout.addWidget(code_frame)

        QTimer.singleShot(50, self._adjust_height)

    def _save_code_to_workspace(self, code_text, lang, btn):
        """Save this code block directly into the active workspace."""
        from agent import detect_file_from_code_block
        from PyQt5.QtWidgets import QInputDialog

        # Always use the app's shared WorkspaceManager so files go to the user's chosen workspace
        parent_win = self.window()
        if hasattr(parent_win, 'workspace'):
            wm = parent_win.workspace
        else:
            from workspace import WorkspaceManager
            wm = WorkspaceManager()

        guessed_name = detect_file_from_code_block(code_text, lang_tag=lang)
        if not guessed_name:
            ext_map = {
                "python": "py", "javascript": "js", "typescript": "ts",
                "html": "html", "css": "css", "json": "json", "bash": "sh",
                "shell": "sh", "yaml": "yaml", "go": "go", "rust": "rs",
                "cpp": "cpp", "c": "c", "java": "java",
            }
            ext = ext_map.get(lang.lower(), "txt")
            guessed_name = f"main.{ext}"

        file_path, ok = QInputDialog.getText(
            self,
            "Save to Workspace",
            f"Enter file path (relative to workspace root '{wm.root.name}'):",
            text=guessed_name
        )
        if ok and file_path.strip():
            res = wm.write_file(file_path.strip(), code_text)
            if res.get("success"):
                btn.setText(f"✓ Saved → {Path(file_path.strip()).name}")
                btn.setStyleSheet(
                    "QPushButton { color: #A5D6A7; background: #1B5E20; border: 1px solid #2E7D32; "
                    "border-radius: 4px; font-size: 11px; padding: 0 8px; font-weight: bold; margin-right: 6px; }"
                )
                if hasattr(parent_win, 'sidebar') and hasattr(parent_win.sidebar, 'file_tree'):
                    parent_win.sidebar.file_tree.refresh_tree()
                if hasattr(parent_win, 'workspace_bar'):
                    parent_win.workspace_bar.update_workspace()
            else:
                btn.setText("⚠ Error saving")
                btn.setToolTip(res.get("error", "Unknown error"))

    def set_text(self, text):
        """Update the message text (for streaming)"""
        self._raw_text = text
        self.set_message_text(text)
        self._adjust_height()


class ThinkingWidget(QFrame):
    """Animated thinking indicator with pulsing starburst and clean phrasing."""

    _PHRASES_LUNA   = ["Thinking…", "Planning next step…", "Analyzing workspace…", "Synthesizing solution…"]
    _PHRASES_SIERRA = ["Thinking…", "Searching context…", "Formulating response…", "Polishing thoughts…"]

    def __init__(self, luna: bool = False, parent=None):
        super().__init__(parent)
        self.luna  = luna
        self.setObjectName("thinkingWidget")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(10)

        col = "#7C8CF8" if luna else "#DA7756"
        badge_bg = "rgba(124, 140, 248, 0.12)" if luna else "rgba(218, 119, 86, 0.12)"
        badge_bdr = "rgba(124, 140, 248, 0.28)" if luna else "rgba(218, 119, 86, 0.28)"

        self.icon_badge = QLabel("✻")
        self.icon_badge.setFixedSize(28, 28)
        self.icon_badge.setAlignment(Qt.AlignCenter)
        self.icon_badge.setStyleSheet(
            f"QLabel {{ color: {col}; background: {badge_bg}; "
            f"border: 1px solid {badge_bdr}; border-radius: 7px; "
            f"font-size: 15px; font-weight: bold; }}"
        )
        layout.addWidget(self.icon_badge)

        self.label = QLabel()
        self.label.setObjectName("thinkingText")
        self.label.setFont(QFont("Segoe UI", 12, QFont.Medium))
        self.label.setStyleSheet(f"color: {col}; background: transparent;")
        layout.addWidget(self.label)

        self._dot_row = QHBoxLayout()
        self._dot_row.setSpacing(3)
        self._dot_row.setContentsMargins(0, 0, 0, 0)
        self._dots = []
        for _ in range(3):
            d = QLabel("●")
            d.setStyleSheet(f"color: {col}; font-size: 6px; background: transparent;")
            self._dot_row.addWidget(d)
            self._dots.append(d)
        layout.addLayout(self._dot_row)
        layout.addStretch()

        self._phrase_idx = 0
        self.count = 0
        self.timer = QTimer(self)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self._animate)
        self._animate()
        self.timer.start()

    def _animate(self):
        self.count = (self.count + 1) % (len(self._dots) + 1)
        if self.count == 0:
            phrases = self._PHRASES_LUNA if self.luna else self._PHRASES_SIERRA
            self._phrase_idx = (self._phrase_idx + 1) % len(phrases)
            self.label.setText(phrases[self._phrase_idx])
        active = "#7C8CF8" if self.luna else "#DA7756"
        dim    = "rgba(124, 140, 248, 0.25)" if self.luna else "rgba(218, 119, 86, 0.25)"
        for i, dot in enumerate(self._dots):
            dot.setStyleSheet(
                f"color: {active if i < self.count else dim}; font-size: 6px; background: transparent;"
            )
        if self.count == 1:
            phrases = self._PHRASES_LUNA if self.luna else self._PHRASES_SIERRA
            self.label.setText(phrases[self._phrase_idx])

    def stop(self):
        self.timer.stop()


class ModelPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modelPanel")
        self.setFixedWidth(350)
        self._build()

    def update_branding(self, luna=False):
        """Swap model panel icon and text between Sierra and Luna."""
        from PyQt5.QtGui import QPixmap
        icon_path = LUNA_ICON_PATH if luna and LUNA_ICON_PATH.exists() else ICON_PATH
        pixmap = QPixmap(str(icon_path))
        size = self.panel_icon._size
        if not pixmap.isNull():
            self.panel_icon.setPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.panel_icon._luna = luna
        self.panel_icon.update()
        if luna:
            self.panel_model_name.setText("Luna 1.1")
            self.panel_description.setText(
                "Custom-trained Luna model optimised for web development — HTML, CSS, JS, React, Next.js and more."
            )
            self.stat_labels["Model Size"].setText("14B parameters")
            self.stat_labels["Context Window"].setText("16,384 tokens")
            self.stat_labels["Quantization"].setText("Q4_K_M (fast)")
        else:
            self.panel_model_name.setText("Llama 3 8B")
            self.panel_description.setText(
                "Meta's Llama 3 8B model, running on your device for privacy and speed."
            )
            self.stat_labels["Model Size"].setText("8B parameters")
            self.stat_labels["Context Window"].setText("8,192 tokens")
            self.stat_labels["Quantization"].setText("Q4_K_M (fast)")

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 32, 20, 28)
        layout.setSpacing(0)

        header = QHBoxLayout()
        badge = QLabel("◈")
        badge.setObjectName("panelHeadingIcon")
        header.addWidget(badge)
        heading = QLabel("Model")
        heading.setObjectName("panelHeading")
        header.addWidget(heading)
        header.addStretch()
        tuning = QLabel("☷")
        tuning.setObjectName("tuningIcon")
        header.addWidget(tuning)
        layout.addLayout(header)
        layout.addSpacing(18)

        model_card = QFrame()
        model_card.setObjectName("modelCard")
        card_layout = QVBoxLayout(model_card)
        card_layout.setContentsMargins(13, 13, 13, 12)
        card_layout.setSpacing(11)
        model_top = QHBoxLayout()
        self.panel_icon = SierraMark(62)
        model_top.addWidget(self.panel_icon)
        model_names = QVBoxLayout()
        model_names.setSpacing(2)
        self.panel_model_name = QLabel("Llama 3 8B")
        self.panel_model_name.setObjectName("modelName")
        status = QLabel("●  Running Locally")
        status.setObjectName("runningStatus")
        model_names.addWidget(self.panel_model_name)
        model_names.addWidget(status)
        model_top.addLayout(model_names)
        model_top.addStretch()
        card_layout.addLayout(model_top)
        self.panel_description = QLabel(
            "Meta's Llama 3 8B model, running on your device for privacy and speed."
        )
        self.panel_description.setObjectName("modelDescription")
        self.panel_description.setWordWrap(True)
        card_layout.addWidget(self.panel_description)
        divider = QFrame()
        divider.setObjectName("panelDivider")
        divider.setFrameShape(QFrame.HLine)
        card_layout.addWidget(divider)
        self.stat_labels = {}
        for key, value in (
            ("Model Size", "8B parameters"),
            ("Context Window", "8,192 tokens"),
            ("Quantization", "Q4_K_M (fast)"),
        ):
            row = QHBoxLayout()
            key_label = QLabel(key)
            key_label.setObjectName("statKey")
            value_label = QLabel(value)
            value_label.setObjectName("statValue")
            self.stat_labels[key] = value_label
            row.addWidget(key_label)
            row.addStretch()
            row.addWidget(value_label)
            card_layout.addLayout(row)
        layout.addWidget(model_card)
        layout.addSpacing(21)

        # Temperature slider
        temp_card = QFrame()
        temp_card.setObjectName("modelCard")
        temp_layout = QVBoxLayout(temp_card)
        temp_layout.setContentsMargins(13, 13, 13, 12)
        temp_layout.setSpacing(11)

        temp_header = QHBoxLayout()
        temp_label = QLabel("Temperature")
        temp_label.setObjectName("modelName")
        temp_value = QLabel("0.7")
        temp_value.setObjectName("statValue")
        temp_header.addWidget(temp_label)
        temp_header.addStretch()
        temp_header.addWidget(temp_value)
        temp_layout.addLayout(temp_header)

        temp_desc = QLabel("Controls creativity: 0.0 = focused, 1.0 = creative")
        temp_desc.setObjectName("modelDescription")
        temp_desc.setWordWrap(True)
        temp_layout.addWidget(temp_desc)

        from PyQt5.QtWidgets import QSlider
        self.temp_slider = QSlider(Qt.Horizontal)
        self.temp_slider.setRange(0, 100)  # 0.0 to 1.0
        self.temp_slider.setValue(70)  # Default 0.7
        self.temp_slider.valueChanged.connect(lambda v: temp_value.setText(str(v / 100)))
        temp_layout.addWidget(self.temp_slider)

        layout.addWidget(temp_card)
        layout.addSpacing(21)

        line = QFrame()
        line.setObjectName("panelDivider")
        line.setFrameShape(QFrame.HLine)
        layout.addWidget(line)
        layout.addSpacing(23)

        feature_header = QHBoxLayout()
        sparkle = QLabel("✦")
        sparkle.setObjectName("featureSparkle")
        feature_header.addWidget(sparkle)
        features_title = QLabel("Features")
        features_title.setObjectName("panelHeading")
        feature_header.addWidget(features_title)
        feature_header.addStretch()
        layout.addLayout(feature_header)
        layout.addSpacing(16)
        for icon, title, detail in (
            ("▣", "Local Inference", "Your data stays on your device"),
            ("♧", "Privacy First", "No data leaves your computer"),
            ("⇄", "Fast & Efficient", "Optimized for your hardware"),
            ("⚙", "Open Source", "Powered by Meta's Llama"),
        ):
            row = QHBoxLayout()
            row.setSpacing(11)
            icon_label = QLabel(icon)
            icon_label.setObjectName("featureIcon")
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setFixedSize(42, 42)
            feature_copy = QVBoxLayout()
            feature_copy.setSpacing(1)
            feature_title = QLabel(title)
            feature_title.setObjectName("featureTitle")
            feature_detail = QLabel(detail)
            feature_detail.setObjectName("featureDetail")
            feature_copy.addWidget(feature_title)
            feature_copy.addWidget(feature_detail)
            row.addWidget(icon_label)
            row.addLayout(feature_copy)
            row.addStretch()
            layout.addLayout(row)
            layout.addSpacing(11)

        layout.addStretch()
        dark_card = QFrame()
        dark_card.setObjectName("darkModeCard")
        dark_layout = QHBoxLayout(dark_card)
        dark_layout.setContentsMargins(12, 10, 12, 10)
        moon = QLabel("☾")
        moon.setObjectName("featureIcon")
        moon.setAlignment(Qt.AlignCenter)
        moon.setFixedSize(42, 42)
        dark_layout.addWidget(moon)
        dark_copy = QVBoxLayout()
        dark_copy.setSpacing(1)
        dark_title = QLabel("Dark Mode")
        dark_title.setObjectName("featureTitle")
        dark_detail = QLabel("Easy on your eyes")
        dark_detail.setObjectName("featureDetail")
        dark_copy.addWidget(dark_title)
        dark_copy.addWidget(dark_detail)
        dark_layout.addLayout(dark_copy)
        dark_layout.addStretch()
        toggle = QCheckBox()
        toggle.setObjectName("darkToggle")
        toggle.setChecked(True)
        toggle.setToolTip("Sierra is designed for dark mode.")
        dark_layout.addWidget(toggle)
        layout.addWidget(dark_card)


class WhatsNewDialog(QDialog):
    """Popup shown on first launch of a new version."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("What's New")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setFixedSize(580, 560)
        self.setStyleSheet("""
            QDialog {
                background: #0D0C0B;
                border: 1px solid #6B4428;
                border-radius: 16px;
            }
            QLabel#wn_title {
                color: #F2EAE1;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#wn_version {
                color: #D08C5C;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel#wn_section {
                color: #E8B97A;
                font-size: 14px;
                font-weight: 700;
                margin-top: 10px;
            }
            QLabel#wn_item {
                color: #D4C4B0;
                font-size: 13px;
                line-height: 1.6;
            }
            QPushButton#wn_close {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #F09040,stop:1 #7A3010);
                color: #FFF8F1;
                border: none;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 600;
                min-height: 42px;
                min-width: 140px;
            }
            QPushButton#wn_close:hover {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #FFB060,stop:1 #993820);
            }
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 6px; }
            QScrollBar::handle:vertical { background: #534239; border-radius: 3px; min-height: 24px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(0)

        # Header
        header = QHBoxLayout()
        icon = SierraMark(44)
        header.addWidget(icon)
        header.addSpacing(14)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("What's New in Vanta AI")
        title.setObjectName("wn_title")
        version = QLabel(f"Version {APP_VERSION} — Beta Release")
        version.setObjectName("wn_version")
        title_col.addWidget(title)
        title_col.addWidget(version)
        header.addLayout(title_col)
        header.addStretch()
        root.addLayout(header)
        root.addSpacing(20)

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("background: #3A2518; max-height: 1px;")
        root.addWidget(div)
        root.addSpacing(16)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 10, 0)
        content_layout.setSpacing(4)

        changelog = self._load_changelog()
        for line in changelog:
            if line.startswith("## "):
                pass  # skip top-level version header already shown
            elif line.startswith("### "):
                lbl = QLabel(line[4:])
                lbl.setObjectName("wn_section")
                lbl.setWordWrap(True)
                content_layout.addSpacing(8)
                content_layout.addWidget(lbl)
            elif line.startswith("- "):
                text = line[2:].replace("**", "")
                lbl = QLabel(f"  •  {text}")
                lbl.setObjectName("wn_item")
                lbl.setWordWrap(True)
                content_layout.addWidget(lbl)

        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)
        root.addSpacing(20)

        # Close button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Let's go  ›")
        close_btn.setObjectName("wn_close")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    def _load_changelog(self):
        """Read CHANGELOG.md and return lines for the latest version block."""
        cl_path = Path(__file__).resolve().parent / "CHANGELOG.md"
        if not cl_path.exists():
            return []
        lines = cl_path.read_text(encoding="utf-8").splitlines()
        # Return lines up to (but not including) the next ## version block
        result = []
        in_block = False
        for line in lines:
            if line.startswith("## "):
                if in_block:
                    break  # stop at next version
                in_block = True
                continue  # skip the version header itself
            if in_block:
                result.append(line)
        return result


class LocalAIApp(QMainWindow):
    SYSTEM_PROMPT = (
        "You are Sierra, a friendly, capable local AI assistant. Be concise, clear, "
        "and conversational. Use Markdown only when it improves readability."
    )
    LUNA_SYSTEM_PROMPT = (
        "You are Luna, an autonomous coding AI with direct workspace access. You write clean, "
        "production-ready code that saves directly into the user's workspace files.\n"
        "Follow these rules strictly:\n"
        "1. Whenever writing or creating code, write it directly into workspace files using write_file.\n"
        "2. Explain your code clearly and concisely.\n"
        "3. When debugging, identify the root cause before fixing.\n"
        "4. Prefer idiomatic patterns and best practices for each language.\n"
        "Be direct and technical. The user is a developer."
    )

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — Local AI Workspace")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(1280, 780)
        self.resize(1560, 980)
        self.conversation_history = []
        self.use_search = False
        self.use_luna = False
        self.auto_run = True
        self.workspace = WorkspaceManager()
        self.active_tool_cards = {}
        self.agent_thread = None
        self._transition_progress = 0.0
        self._transition_target = 0.0
        self.chat_thread = None
        self.thinking_widget = None
        self._attached_file = None
        self.setStyleSheet(self._stylesheet())
        self._build()
        self._load_latest_chat()
        self.start_new_chat()
        QTimer.singleShot(400, self._maybe_show_whats_new)

    def _get_transition_progress(self):
        return self._transition_progress

    def _set_transition_progress(self, value):
        self._transition_progress = value
        self.update()

    transition_progress = pyqtProperty(float, _get_transition_progress, _set_transition_progress)

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QLinearGradient, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        t = self._transition_progress  # 0.0 = Sierra, 1.0 = Luna

        def lerp_color(c1, c2, t):
            r = int(c1.red()   + (c2.red()   - c1.red())   * t)
            g = int(c1.green() + (c2.green() - c1.green()) * t)
            b = int(c1.blue()  + (c2.blue()  - c1.blue())  * t)
            return QColor(r, g, b)

        # Sierra background: calm, rich, velvety charcoal with warmest undertone
        s0 = QColor("#171614")
        s1 = QColor("#131210")
        # Luna background: deep architectural midnight slate
        l0 = QColor("#0D1117")
        l1 = QColor("#080B10")

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, lerp_color(s0, l0, t))
        grad.setColorAt(1.0, lerp_color(s1, l1, t))
        painter.fillRect(self.rect(), grad)
        painter.end()

    def _stylesheet(self):
        if self.use_luna:
            # ── Luna: Claude Code slate / indigo obsidian ─────────────────────
            shell_bg          = "#0E121B"
            shell_border      = "#1E2536"
            sidebar_bg        = "#0A0D15"
            sidebar_border    = "#19202E"
            title_bg          = "#0E121B"
            title_border      = "#19202E"
            panel_bg          = "#0B0E17"
            central_bg        = "#0D1118"
            accent            = "#7C8CF8"
            accent2           = "#9DAAFB"
            wordmark_version  = "#7C8CF8"
            nav_hover         = "#141A26"
            nav_checked       = "#1A2234"
            nav_active        = "#1A2234"
            send_bg           = "#6366F1"
            send_hover        = "#7579F6"
            scroll_handle     = "rgba(124, 140, 248, 0.35)"
            model_card_bg     = "#121724"
            model_card_border = "#1F273D"
            avatar_ai         = "#6366F1"
            avatar_user       = "#162032"
            avatar_user_bdr   = "#23314D"
            toggle_checked    = "#6366F1"
            action_card_bg    = "#121724"
            action_card_bdr   = "#1F273D"
            action_icon_bg    = "#182033"
            composer_fill     = "#141A26"
            input_selection   = "#2B3754"
            luna_btn          = "#1E1B4B"
            divider_col       = "#19202E"
            brand_desc_col    = "#5E6E8C"
            recent_hover      = "#141A26"
            recent_icon_bg    = "#182033"
            recent_name_col   = "#C8D3E6"
            recent_age_col    = "#5E6E8C"
            model_card_side   = "#121724"
            model_card_side_b = "#1F273D"
            chevron_col       = "#7C8CF8"
            stat_key_col      = "#5E6E8C"
            stat_val_col      = "#C8D3E6"
            panel_heading_col = "#94A3B8"
            feat_title_col    = "#C8D3E6"
            feat_detail_col   = "#5E6E8C"
            hero_title_col    = "#F1F5F9"
            hero_sub_col      = "#94A3B8"
            hero_desc_col     = "#64748B"
            action_title_col  = "#F1F5F9"
            action_sub_col    = "#64748B"
        else:
            # ── Sierra: Claude signature warm charcoal / terracotta ────────────
            shell_bg          = "#1A1916"
            shell_border      = "#2B2A25"
            sidebar_bg        = "#151412"
            sidebar_border    = "#24231E"
            title_bg          = "#1A1916"
            title_border      = "#24231E"
            panel_bg          = "#161513"
            central_bg        = "#191815"
            accent            = "#DA7756"
            accent2           = "#E58A6C"
            wordmark_version  = "#DA7756"
            nav_hover         = "#22201C"
            nav_checked       = "#2A2722"
            nav_active        = "rgba(218, 119, 86, 0.14)"
            send_bg           = "#DA7756"
            send_hover        = "#E58869"
            scroll_handle     = "rgba(218, 119, 86, 0.35)"
            model_card_bg     = "#201E1A"
            model_card_border = "#2D2A24"
            avatar_ai         = "#DA7756"
            avatar_user       = "#2A2722"
            avatar_user_bdr   = "#38342D"
            toggle_checked    = "#DA7756"
            action_card_bg    = "#201E1A"
            action_card_bdr   = "#2D2A24"
            action_icon_bg    = "#282520"
            composer_fill     = "#22201C"
            input_selection   = "#4A2B1E"
            luna_btn          = "#28203A"
            divider_col       = "#262420"
            brand_desc_col    = "#8C877D"
            recent_hover      = "#22201C"
            recent_icon_bg    = "#262420"
            recent_name_col   = "#D6D1C7"
            recent_age_col    = "#7D796F"
            model_card_side   = "#201E1A"
            model_card_side_b = "#2D2A24"
            chevron_col       = "#DA7756"
            stat_key_col      = "#8C877D"
            stat_val_col      = "#D6D1C7"
            panel_heading_col = "#B5B0A4"
            feat_title_col    = "#D6D1C7"
            feat_detail_col   = "#7D796F"
            hero_title_col    = "#FAF7F2"
            hero_sub_col      = "#B5B0A4"
            hero_desc_col     = "#858074"
            action_title_col  = "#FAF7F2"
            action_sub_col    = "#858074"

        return f"""
            * {{
                font-family: 'Segoe UI', 'Inter', -apple-system, Arial, sans-serif;
                font-size: 14px;
            }}
            QMainWindow {{ background: transparent; }}

            /* ── Shell ── */
            QFrame#appShell {{
                background: {shell_bg};
                border: 1px solid {shell_border};
                border-radius: 12px;
            }}

            /* ── Title bar ── */
            QFrame#titleBar {{
                background: {title_bg};
                border-bottom: 1px solid {title_border};
                min-height: 48px; max-height: 48px;
                border-top-right-radius: 12px;
            }}
            QFrame#windowControls {{ background: transparent; border: none; }}
            QPushButton#trafficClose, QPushButton#trafficMinimize, QPushButton#trafficMaximize {{
                border: none; border-radius: 0;
                color: #6C685F; font-size: 12px; font-weight: 600;
                background: transparent;
            }}
            QPushButton#trafficClose:hover   {{ background: rgba(220,50,50,0.80); color: #FFF; border-radius: 4px; }}
            QPushButton#trafficMinimize:hover {{ background: rgba(255,200,0,0.25); color: #FFF; border-radius: 4px; }}
            QPushButton#trafficMaximize:hover {{ background: rgba(255,255,255,0.08); color: #FFF; border-radius: 4px; }}
            QLabel#titleIcon {{ color: {accent}; font-size: 15px; }}
            QLabel#titleText {{ color: #A8A398; font-size: 13px; font-weight: 500; letter-spacing: 0.2px; }}
            QPushButton#topIconButton {{
                color: #7D796F; background: transparent;
                border: none; font-size: 15px;
                border-radius: 6px; min-width: 32px; min-height: 32px;
            }}
            QPushButton#topIconButton:hover {{
                background: rgba(255,255,255,0.06);
                color: {accent2};
            }}

            /* ── Sidebar ── */
            QFrame#sidebar {{
                background: {sidebar_bg};
                border: none;
                border-right: 1px solid {sidebar_border};
                border-bottom-left-radius: 12px;
            }}
            QLabel#wordmark {{
                color: #FAF7F2;
                font-size: 18px; font-weight: 700;
                letter-spacing: -0.4px;
            }}
            QLabel#wordmark span {{ color: {wordmark_version}; }}
            QLabel#heroTitle span {{ color: {wordmark_version}; }}
            QLabel#brandDescription {{ color: {brand_desc_col}; font-size: 11px; }}

            QPushButton#navButton, QPushButton#navButtonActive {{
                color: #9C978D;
                background: transparent; border: none;
                border-radius: 8px; padding: 0 12px;
                text-align: left; font-size: 13px; min-height: 38px;
            }}
            QPushButton#navButton:hover {{ background: {nav_hover}; color: #ECE8E1; }}
            QPushButton#navButton:checked {{ background: {nav_checked}; color: #ECE8E1; }}
            QPushButton#navButtonActive {{
                background: {nav_active}; color: #FAF7F2; font-weight: 600;
                border: 1px solid {accent}40;
            }}
            QPushButton#navButtonActive:hover {{ background: {nav_active}; }}
            QPushButton#lunaButton {{
                color: #9C978D; background: transparent; border: none;
                border-radius: 8px; padding: 0 12px;
                text-align: left; font-size: 13px; min-height: 38px;
            }}
            QPushButton#lunaButton:hover {{ background: #1A1828; color: #C4B5FD; }}
            QPushButton#lunaButton:checked {{ background: {luna_btn}; color: #E0E7FF; font-weight: 600; }}

            QFrame#sidebarDivider, QFrame#panelDivider {{
                background: {divider_col}; max-height: 1px; border: none;
            }}
            QLabel#sectionHeading {{
                color: {recent_age_col}; font-size: 11px;
                font-weight: 700; letter-spacing: 0.8px;
                padding: 0 0 4px 4px;
            }}
            QFrame#recentChat {{ background: transparent; border-radius: 8px; }}
            QFrame#recentChat:hover {{ background: {recent_hover}; }}
            QLabel#recentIcon {{
                color: {accent}; background: {recent_icon_bg};
                border-radius: 6px; font-size: 12px;
            }}
            QLabel#recentName {{
                color: {recent_name_col}; font-size: 13px; font-weight: 500;
            }}
            QLabel#recentAge {{ color: {recent_age_col}; font-size: 11px; }}
            QFrame#sidebarModelCard {{
                background: {model_card_side};
                border: 1px solid {model_card_side_b};
                border-radius: 10px;
            }}
            QLabel#sidebarModelTitle {{ color: #D6D1C7; font-size: 13px; font-weight: 600; }}
            QLabel#sidebarModelSubtitle {{ color: {stat_key_col}; font-size: 11px; }}
            QLabel#onlineIndicator {{ color: #34D399; font-size: 10px; }}
            QLabel#cardChevron {{ color: {chevron_col}; font-size: 20px; font-weight: 300; }}

            /* ── Scrollbar ── */
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent; width: 6px; margin: 4px 1px;
            }}
            QScrollBar::handle:vertical {{
                background: {scroll_handle}; border-radius: 3px; min-height: 32px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

            /* ── Central chat pane ── */
            QWidget#centralPane {{ background: {central_bg}; }}

            /* ── Welcome screen ── */
            QLabel#heroTitle {{
                color: {hero_title_col};
                font-size: 40px; font-weight: 700;
                letter-spacing: -0.8px;
            }}
            QLabel#heroSubtitle {{ color: {hero_sub_col}; font-size: 17px; font-weight: 500; }}
            QLabel#heroDescription {{ color: {hero_desc_col}; font-size: 13px; line-height: 1.5; }}

            /* ── Action cards ── */
            QPushButton#actionCard {{
                background: {action_card_bg};
                border: 1px solid {action_card_bdr};
                border-radius: 12px; text-align: left;
            }}
            QPushButton#actionCard:hover {{
                background: rgba(255,255,255,0.05);
                border-color: {accent}60;
            }}
            QLabel#actionIcon {{
                background: {action_icon_bg};
                color: {accent};
                border-radius: 8px;
                font-size: 16px; font-weight: 700;
            }}
            QLabel#actionTitle {{ color: {action_title_col}; font-size: 13px; font-weight: 600; }}
            QLabel#actionSubtitle {{ color: {action_sub_col}; font-size: 11px; }}

            /* ── Composer ── */
            QFrame#composer {{ background: transparent; border: none; border-radius: 18px; }}
            QTextEdit#chatInput {{
                color: #EDE8DF;
                background: transparent; border: none;
                padding: 10px 14px; font-size: 14px;
                selection-background-color: {input_selection};
            }}
            QPushButton#composerButton {{
                color: #9C978D;
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px; padding: 0 10px;
                min-height: 32px; font-size: 12px; font-weight: 500;
            }}
            QPushButton#composerButton:hover, QPushButton#composerButton:checked {{
                color: {accent2};
                background: rgba(255,255,255,0.08);
                border-color: {accent}55;
            }}
            QPushButton#attachButton {{
                color: #9C978D;
                background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
                min-height: 32px; min-width: 34px; max-width: 34px;
                font-size: 17px;
            }}
            QPushButton#attachButton:hover {{
                background: rgba(255,255,255,0.08);
                color: {accent};
            }}
            QPushButton#sendButton {{
                color: #FFFFFF;
                background: {send_bg};
                border: none; border-radius: 8px;
                min-width: 34px; max-width: 34px; min-height: 34px;
                font-size: 16px; font-weight: 700;
            }}
            QPushButton#sendButton:hover {{ background: {send_hover}; }}
            QPushButton#sendButton:disabled {{
                background: rgba(255,255,255,0.05);
                color: rgba(255,255,255,0.20);
            }}

            /* ── Model Panel ── */
            QFrame#modelPanel {{
                background: {panel_bg};
                border: none;
                border-left: 1px solid {sidebar_border};
                border-bottom-right-radius: 12px;
            }}
            QLabel#panelHeadingIcon {{ color: {accent}; font-size: 15px; }}
            QLabel#panelHeading {{ color: {panel_heading_col}; font-size: 14px; font-weight: 600; }}
            QLabel#tuningIcon {{ color: {accent}; font-size: 15px; }}
            QFrame#modelCard, QFrame#darkModeCard {{
                background: {model_card_bg};
                border: 1px solid {model_card_border};
                border-radius: 10px;
            }}
            QLabel#modelName {{ color: #D6D1C7; font-size: 13px; font-weight: 600; }}
            QLabel#runningStatus {{ color: #34D399; font-size: 11px; }}
            QLabel#modelDescription {{ color: {feat_detail_col}; font-size: 12px; line-height: 1.4; }}
            QLabel#statKey {{ color: {stat_key_col}; font-size: 12px; }}
            QLabel#statValue {{ color: {stat_val_col}; font-size: 12px; }}
            QLabel#featureIcon {{ color: {accent}; background: {action_icon_bg}; border-radius: 8px; font-size: 15px; }}
            QLabel#featureTitle {{ color: {feat_title_col}; font-size: 12px; font-weight: 500; }}
            QLabel#featureDetail {{ color: {feat_detail_col}; font-size: 11px; }}
            QCheckBox#darkToggle::indicator {{
                width: 34px; height: 18px; border-radius: 9px;
                background: rgba(255,255,255,0.08);
            }}
            QCheckBox#darkToggle::indicator:checked {{ background: {toggle_checked}; }}

            /* ── Avatars ── */
            QLabel#assistantAvatar {{
                color: {accent};
                background: rgba(218, 119, 86, 0.14);
                border: 1px solid rgba(218, 119, 86, 0.28);
                border-radius: 8px;
                font-size: 16px; font-weight: bold;
            }}
            QLabel#userAvatar {{
                color: #C2BEB5;
                background: {avatar_user};
                border: 1px solid {avatar_user_bdr};
                border-radius: 8px;
                font-size: 10px; font-weight: 700;
                letter-spacing: 0.5px;
            }}

            /* ── Misc ── */
            QLabel#messageMeta {{ color: {recent_age_col}; font-size: 10px; }}
            QTextEdit {{ border: none; }}
            QFrame#thinkingWidget {{ background: transparent; border: none; }}
            QLabel#thinkingText {{ color: {accent}; font-size: 12px; font-weight: 600; }}
            QLabel#iconFallback {{
                color: {accent}; background: {action_icon_bg};
                border-radius: 8px; font-size: 15px; font-weight: 700;
            }}
        """

    def _build(self):
        outer = QWidget()
        outer.setStyleSheet("background: transparent;")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(10, 14, 10, 14)
        self.setCentralWidget(outer)

        shell = QFrame()
        shell.setObjectName("appShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar(workspace=self.workspace)
        self.sidebar.new_chat_requested.connect(self.start_new_chat)
        self.sidebar.search_toggled.connect(self.set_search)
        self.sidebar.luna_toggled.connect(self.set_luna)
        self.sidebar.chat_loaded.connect(self.load_chat)
        if hasattr(self.sidebar, 'file_tree'):
            self.sidebar.file_tree.file_selected.connect(self._on_file_selected_from_tree)
        shell_layout.addWidget(self.sidebar)

        # Center column: title bar + chat
        workspace_column = QVBoxLayout()
        workspace_column.setContentsMargins(0, 0, 0, 0)
        workspace_column.setSpacing(0)
        self.title_bar = TitleBar()
        workspace_column.addWidget(self.title_bar)

        lower = QHBoxLayout()
        lower.setContentsMargins(0, 0, 0, 0)
        lower.setSpacing(0)
        lower.addWidget(self._build_chat_pane(), 1)
        self.model_panel = ModelPanel()
        lower.addWidget(self.model_panel)
        workspace_column.addLayout(lower, 1)
        shell_layout.addLayout(workspace_column, 1)
        outer_layout.addWidget(shell)

    def _build_chat_pane(self):
        pane = QWidget()
        pane.setObjectName("centralPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Workspace bar (only shown in Luna mode)
        self.workspace_bar = WorkspaceBar(self.workspace, luna=self.use_luna)
        self.workspace_bar.folder_change_requested.connect(self._choose_workspace_folder)
        self.workspace_bar.auto_run_toggled.connect(self._set_auto_run)
        self.workspace_bar.refresh_requested.connect(self._refresh_workspace)
        layout.addWidget(self.workspace_bar)

        # Message scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_host = QWidget()
        self.message_host.setStyleSheet("background: transparent;")
        self.message_layout = QVBoxLayout(self.message_host)
        self.message_layout.setContentsMargins(64, 28, 64, 28)
        self.message_layout.setSpacing(24)
        self.message_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.message_host)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self._build_composer())
        return pane

    def _build_composer(self):
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(48, 0, 48, 20)
        layout.setSpacing(0)

        composer = GradientFrame()
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(16, 10, 16, 10)
        composer_layout.setSpacing(8)

        # Attachment chip row (hidden until file is attached)
        self.attach_row = QWidget()
        self.attach_row.setStyleSheet("background: transparent;")
        attach_row_layout = QHBoxLayout(self.attach_row)
        attach_row_layout.setContentsMargins(0, 0, 0, 0)
        attach_row_layout.setSpacing(6)
        self.attach_label = QLabel()
        self.attach_label.setObjectName("attachLabel")
        self.attach_label.setStyleSheet(
            "QLabel { color: #D6D1C7; background: rgba(255,255,255,0.06); "
            "border: 1px solid rgba(255,255,255,0.10); border-radius: 6px; "
            "padding: 3px 10px; font-size: 11px; font-weight: 500; }"
        )
        remove_attach = QPushButton("✕")
        remove_attach.setFixedSize(18, 18)
        remove_attach.setStyleSheet(
            "QPushButton { color: #9C978D; background: rgba(255,255,255,0.04); "
            "border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; font-size: 10px; }"
            "QPushButton:hover { background: rgba(220,50,50,0.70); color: white; }"
        )
        remove_attach.clicked.connect(self._clear_attachment)
        attach_row_layout.addWidget(self.attach_label)
        attach_row_layout.addWidget(remove_attach)
        attach_row_layout.addStretch()
        self.attach_row.setVisible(False)
        composer_layout.addWidget(self.attach_row)

        # Input field
        self.chat_input = ChatInput()
        self.chat_input.setObjectName("chatInput")
        self.chat_input.setPlaceholderText("Message Sierra…")
        self.chat_input.setMinimumHeight(42)
        self.chat_input.setMaximumHeight(200)
        self.chat_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.chat_input.document().contentsChanged.connect(self._resize_input)
        self.chat_input.submitted.connect(self.send_message)
        composer_layout.addWidget(self.chat_input)

        # Bottom action row
        actions = QHBoxLayout()
        actions.setSpacing(6)

        # Attach
        attach_btn = QPushButton("⊕")
        attach_btn.setObjectName("attachButton")
        attach_btn.setToolTip("Attach a file")
        attach_btn.setCursor(Qt.PointingHandCursor)
        attach_btn.clicked.connect(self._attach_file)
        actions.addWidget(attach_btn)

        # Model switcher
        from PyQt5.QtWidgets import QMenu, QWidgetAction
        self.model_button = QPushButton("◈  Sierra")
        self.model_button.setObjectName("composerButton")
        self.model_button.setToolTip("Switch AI model")
        self.model_button.setCursor(Qt.PointingHandCursor)
        model_menu = QMenu(self.model_button)
        sierra_action = model_menu.addAction("◈  Sierra   (Llama 3 · 8B)")
        sierra_action.triggered.connect(lambda: self._switch_model("sierra"))
        luna_widget = QLabel("✦  Luna   (Qwen 2.5 Coder · 14B)")
        luna_widget.setStyleSheet(
            "QLabel { background: #182030; color: #C8D3E6; font-size: 12px; "
            "padding: 8px 16px; border-radius: 6px; border: 1px solid #253048; }"
        )
        luna_widget.setCursor(Qt.PointingHandCursor)
        luna_wa = QWidgetAction(model_menu)
        luna_wa.setDefaultWidget(luna_widget)
        luna_widget.mousePressEvent = lambda e: self._luna_menu_click(model_menu)
        model_menu.addAction(luna_wa)
        model_menu.setStyleSheet("""
            QMenu {
                background: #1F1D19; border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px; padding: 4px;
            }
            QMenu::item { padding: 6px 14px; border-radius: 6px; color: #D6D1C7; font-size: 12px; }
            QMenu::item:selected { background: rgba(255,255,255,0.06); color: #FAF7F2; }
        """)
        self.model_button.setMenu(model_menu)
        actions.addWidget(self.model_button)

        # Web search
        self.search_button = QPushButton("⌕  Search")
        self.search_button.setObjectName("composerButton")
        self.search_button.setCheckable(True)
        self.search_button.setToolTip("Toggle web search")
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.toggled.connect(self._composer_search_toggled)
        actions.addWidget(self.search_button)

        # Code prompt
        code_btn = QPushButton("✦  Code")
        code_btn.setObjectName("composerButton")
        code_btn.setToolTip("Start a code task")
        code_btn.setCursor(Qt.PointingHandCursor)
        code_btn.clicked.connect(self._start_code_prompt)
        actions.addWidget(code_btn)

        actions.addStretch()

        # Send
        self.send_button = QPushButton("↑")
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setToolTip("Send  (Enter)")
        self.send_button.clicked.connect(self.send_message)
        actions.addWidget(self.send_button)

        composer_layout.addLayout(actions)
        layout.addWidget(composer)
        return holder

    def _show_welcome(self):
        self.welcome = WelcomeView(luna=self.use_luna)
        self.welcome.prompt_chosen.connect(self.use_prompt)
        self.message_layout.addWidget(self.welcome)

    def _load_latest_chat(self):
        """Load the most recent saved chat on startup"""
        latest_path = CHATS_DIR / "latest.json"
        if latest_path.exists():
            try:
                with open(latest_path, 'r', encoding='utf-8') as f:
                    chat_data = json.load(f)

                for msg_data in chat_data.get("messages", []):
                    msg_type = msg_data["type"]
                    content = msg_data["content"]

                    if msg_type == "HumanMessage":
                        self.conversation_history.append(HumanMessage(content=content))
                    elif msg_type == "AIMessage":
                        self.conversation_history.append(AIMessage(content=content))
                    elif msg_type == "SystemMessage":
                        self.conversation_history.append(SystemMessage(content=content))
            except Exception:
                # If loading fails, just start fresh
                pass

    def load_chat(self, file_path):
        """Load a specific chat from file"""
        if self.chat_thread and self.chat_thread.isRunning():
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                chat_data = json.load(f)

            # Clear current chat
            while self.message_layout.count():
                item = self.message_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()

            # Load messages
            self.conversation_history = [SystemMessage(content=self.SYSTEM_PROMPT)]
            for msg_data in chat_data.get("messages", []):
                msg_type = msg_data["type"]
                content = msg_data["content"]

                if msg_type == "HumanMessage":
                    self.conversation_history.append(HumanMessage(content=content))
                    self._add_message(content, is_user=True)
                elif msg_type == "AIMessage":
                    self.conversation_history.append(AIMessage(content=content))
                    self._add_message(content, is_user=False)
                elif msg_type == "SystemMessage":
                    self.conversation_history.append(SystemMessage(content=content))

            self.thinking_widget = None
            self.chat_input.clear()
            self.chat_input.setReadOnly(False)
            self.chat_input.setFocus()
            self.send_button.setEnabled(True)

        except Exception as e:
            print(f"Error loading chat: {e}")

    def start_new_chat(self):
        if (self.chat_thread and self.chat_thread.isRunning()) or (self.agent_thread and self.agent_thread.isRunning()):
            return
        while self.message_layout.count():
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.conversation_history = [SystemMessage(content=self.LUNA_SYSTEM_PROMPT if self.use_luna else self.SYSTEM_PROMPT)]
        self.thinking_widget = None
        self.active_tool_cards.clear()
        # Reset session filename so this new chat gets its own file on close
        if hasattr(self, '_session_filename'):
            del self._session_filename
        self._show_welcome()
        self.chat_input.clear()
        self.chat_input.setFixedHeight(44)
        self.chat_input.setReadOnly(False)
        self.chat_input.setFocus()
        self.send_button.setEnabled(True)

    def use_prompt(self, prompt):
        self.chat_input.setPlainText(prompt)
        self.chat_input.setFocus()

    def _start_code_prompt(self):
        if not self.chat_input.toPlainText().strip():
            self.chat_input.setPlainText("Help me write clean code for: ")
        self.chat_input.setFocus()

    def _attach_file(self):
        """Open a file picker and store the selected file for the next send."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach a File",
            "",
            "All Supported Files (*.txt *.md *.pdf *.docx *.py *.js *.ts *.jsx *.tsx "
            "*.html *.css *.json *.xml *.yaml *.yml *.csv *.log *.c *.cpp *.h *.java "
            "*.cs *.rb *.go *.rs *.swift *.kt *.png *.jpg *.jpeg *.gif *.bmp *.webp);;"
            "All Files (*)"
        )
        if not file_path:
            return
        self._attached_file = file_path
        name = Path(file_path).name
        self.attach_label.setText(f"📎  {name}")
        self.attach_row.setVisible(True)
        self.chat_input.setFocus()

    def _clear_attachment(self):
        """Remove the currently attached file."""
        self._attached_file = None
        self.attach_label.setText("")
        self.attach_row.setVisible(False)

    def _composer_search_toggled(self, enabled):
        self.set_search(enabled, source="composer")

    def set_search(self, enabled, source="sidebar"):
        self.use_search = enabled
        if source != "composer":
            self.search_button.blockSignals(True)
            self.search_button.setChecked(enabled)
            self.search_button.blockSignals(False)
        if source != "sidebar":
            self.sidebar.search.blockSignals(True)
            self.sidebar.search.setChecked(enabled)
            self.sidebar.search.setText("⌕    Search  ON" if enabled else "⌕    Search")
            self.sidebar.search.blockSignals(False)

    def set_luna(self, enabled):
        self.use_luna = enabled
        active_prompt = self.LUNA_SYSTEM_PROMPT if enabled else self.SYSTEM_PROMPT
        if self.conversation_history:
            self.conversation_history[0] = SystemMessage(content=active_prompt)
        mode = "🌙 Luna — Coding AI" if enabled else "New Chat"
        for widget in self.title_bar.findChildren(QLabel):
            if widget.objectName() == "titleText":
                widget.setText(mode)
                break
        self._switch_model("luna" if enabled else "sierra")

    def _luna_menu_click(self, menu):
        menu.close()
        self._switch_model("luna")

    def _switch_model(self, mode):
        """Switch between Sierra and Luna from the composer model button."""
        going_luna = (mode == "luna")
        # Kick off background fade animation
        anim = QPropertyAnimation(self, b"transition_progress")
        anim.setDuration(600)
        anim.setStartValue(self._transition_progress)
        anim.setEndValue(1.0 if going_luna else 0.0)
        anim.setEasingCurve(QEasingCurve.InOutCubic)
        anim.start()
        self._anim = anim  # keep reference so it isn't garbage collected

        if going_luna:
            self.use_luna = True
            self.model_button.setText("🌙  Luna")
            if self.conversation_history:
                self.conversation_history[0] = SystemMessage(content=self.LUNA_SYSTEM_PROMPT)
            self.sidebar.luna_button.blockSignals(True)
            self.sidebar.luna_button.setChecked(True)
            self.sidebar.luna_button.setText("🌙    Luna  ON")
            self.sidebar.luna_button.blockSignals(False)
            for widget in self.title_bar.findChildren(QLabel):
                if widget.objectName() == "titleText":
                    widget.setText("🌙 Luna — Coding AI")
                    break
        else:
            self.use_luna = False
            self.model_button.setText("⬡  Sierra")
            if self.conversation_history:
                self.conversation_history[0] = SystemMessage(content=self.SYSTEM_PROMPT)
            self.sidebar.luna_button.blockSignals(True)
            self.sidebar.luna_button.setChecked(False)
            self.sidebar.luna_button.setText("🌙    Luna  —  Coding AI")
            self.sidebar.luna_button.blockSignals(False)
            for widget in self.title_bar.findChildren(QLabel):
                if widget.objectName() == "titleText":
                    widget.setText("New Chat")
                    break
        self.setStyleSheet(self._stylesheet())
        self.update()
        # Repaint composer border
        if self.centralWidget():
            self.centralWidget().update()
        # Update sidebar branding
        self.sidebar.update_branding(luna=self.use_luna)
        # Update model panel branding
        self.model_panel.update_branding(luna=self.use_luna)
        # Update workspace bar styling
        if hasattr(self, 'workspace_bar'):
            self.workspace_bar.set_luna_mode(self.use_luna)
        # Refresh welcome screen if it's currently showing
        if hasattr(self, 'welcome'):
            try:
                self.welcome.setParent(None)
                self.welcome.deleteLater()
            except RuntimeError:
                pass
            del self.welcome
            # Clear entire message layout then rebuild welcome
            while self.message_layout.count():
                item = self.message_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self._show_welcome()
        # Update chat input placeholder
        self.chat_input.setPlaceholderText("Ask Luna to code, run commands, or explore workspace…" if self.use_luna else f"Message {APP_NAME}…")

    def send_message(self):
        # If agent is running and button is clicked, cancel execution
        if hasattr(self, 'agent_thread') and self.agent_thread and self.agent_thread.isRunning():
            self.agent_thread.cancel()
            return

        text = self.chat_input.toPlainText().strip()
        if not text and not self._attached_file:
            return
        if self.chat_thread and self.chat_thread.isRunning():
            return
        if hasattr(self, "welcome"):
            try:
                self.welcome.setParent(None)
                self.welcome.deleteLater()
            except RuntimeError:
                pass
            del self.welcome

        # Build the full message — user text + file contents if attached
        display_text = text  # what shows in the bubble
        ai_text = text       # what goes to the model

        if self._attached_file:
            file_name = Path(self._attached_file).name
            file_content = extract_file_text(self._attached_file)
            # Append file content to the AI message but keep bubble readable
            if text:
                ai_text = (
                    f"{text}\n\n"
                    f"--- Attached file: {file_name} ---\n{file_content}\n---"
                )
                display_text = f"{text}\n\n📎 {file_name}"
            else:
                ai_text = f"--- Attached file: {file_name} ---\n{file_content}\n---"
                display_text = f"📎 {file_name}"
            self._clear_attachment()

        if not ai_text.strip():
            return

        self.conversation_history.append(HumanMessage(content=ai_text))
        self._add_message(display_text, is_user=True)
        self.chat_input.clear()
        self.chat_input.setFixedHeight(44)

        if self.use_luna:
            # === LUNA AUTONOMOUS AGENT MODE ===
            self.chat_input.setReadOnly(True)
            self._set_stop_button(True)
            self._add_thinking()

            temperature = self.model_panel.temp_slider.value() / 100
            self.agent_thread = AgentThread(
                messages=self.conversation_history,
                workspace=self.workspace,
                model=LUNA_MODEL_NAME,
                temperature=temperature,
                auto_run=self.auto_run,
                max_steps=25
            )
            self.agent_thread.stream_chunk.connect(self._on_agent_stream_chunk)
            self.agent_thread.tool_started.connect(self._on_tool_started)
            self.agent_thread.tool_needs_approval.connect(self._on_tool_needs_approval)
            self.agent_thread.tool_finished.connect(self._on_tool_finished)
            self.agent_thread.agent_status.connect(self._on_agent_status)
            self.agent_thread.agent_finished.connect(self._on_agent_finished)
            self.agent_thread.error.connect(self.show_error)
            self.agent_thread.start()
        else:
            # === SIERRA CONVERSATIONAL MODE ===
            self.chat_input.setReadOnly(True)
            self.send_button.setEnabled(False)
            self._add_thinking()
            temperature = self.model_panel.temp_slider.value() / 100
            self.chat_thread = ChatThread(
                self.conversation_history,
                self.use_search,
                stream=True,
                temperature=temperature,
                model=MODEL_NAME
            )
            self.chat_thread.response_ready.connect(self.display_response)
            self.chat_thread.stream_chunk.connect(self.stream_response)
            self.chat_thread.error.connect(self.show_error)
            self.chat_thread.start()

    def _add_message(self, text, is_user):
        message = MessageWidget(text, is_user, luna=self.use_luna)
        if not is_user:
            message.regenerate_requested.connect(self._regenerate_message)
        self.message_layout.addWidget(message)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _regenerate_message(self, msg_widget):
        """Remove the AI message widget and re-send the last user prompt."""
        if (self.chat_thread and self.chat_thread.isRunning()) or \
           (self.agent_thread and self.agent_thread.isRunning()):
            return  # busy

        # Remove the AI message from layout + history
        msg_widget.setParent(None)
        msg_widget.deleteLater()

        # Pop the last AI message from history
        for i in range(len(self.conversation_history) - 1, -1, -1):
            from langchain_core.messages import AIMessage as _AI
            if isinstance(self.conversation_history[i], _AI):
                self.conversation_history.pop(i)
                break

        # Find the last user message to re-send
        last_user_text = ""
        for msg in reversed(self.conversation_history):
            from langchain_core.messages import HumanMessage as _HM
            if isinstance(msg, _HM):
                last_user_text = msg.content
                break

        if not last_user_text:
            return

        # Re-run via thinking widget + model
        if self.use_luna:
            self.chat_input.setReadOnly(True)
            self._set_stop_button(True)
            self._add_thinking()
            temperature = self.model_panel.temp_slider.value() / 100
            self.agent_thread = AgentThread(
                messages=self.conversation_history,
                workspace=self.workspace,
                model=LUNA_MODEL_NAME,
                temperature=temperature,
                auto_run=self.auto_run,
                max_steps=25,
            )
            self.agent_thread.stream_chunk.connect(self._on_agent_stream_chunk)
            self.agent_thread.tool_started.connect(self._on_tool_started)
            self.agent_thread.tool_needs_approval.connect(self._on_tool_needs_approval)
            self.agent_thread.tool_finished.connect(self._on_tool_finished)
            self.agent_thread.agent_status.connect(self._on_agent_status)
            self.agent_thread.agent_finished.connect(self._on_agent_finished)
            self.agent_thread.error.connect(self.show_error)
            self.agent_thread.start()
        else:
            self.chat_input.setReadOnly(True)
            self.send_button.setEnabled(False)
            self._add_thinking()
            temperature = self.model_panel.temp_slider.value() / 100
            self.chat_thread = ChatThread(
                self.conversation_history,
                self.use_search,
                stream=True,
                temperature=temperature,
                model=MODEL_NAME,
            )
            self.chat_thread.response_ready.connect(self.display_response)
            self.chat_thread.stream_chunk.connect(self.stream_response)
            self.chat_thread.error.connect(self.show_error)
            self.chat_thread.start()

    def _add_thinking(self):
        self.thinking_widget = ThinkingWidget(luna=self.use_luna)
        self.thinking_row = QWidget()
        self.thinking_row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(self.thinking_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.thinking_widget)
        row_layout.addStretch()
        self.message_layout.addWidget(self.thinking_row)
        QTimer.singleShot(0, self._scroll_to_bottom)
        self.thinking_widget.timer.start(250)

    def _remove_thinking(self):
        if self.thinking_widget:
            self.thinking_widget.stop()
            self.thinking_row.setParent(None)
            self.thinking_row.deleteLater()
            self.thinking_widget = None

    def display_response(self, response):
        """Called when streaming is complete"""
        if hasattr(self, 'current_ai_message'):
            # Ensure final message is fully rendered
            self.current_ai_widget.set_text(response)
            self.conversation_history.append(AIMessage(content=response))
            self._auto_save()
            self.sidebar.refresh_recent_chats()
            del self.current_ai_message
            del self.current_ai_widget
        self.chat_input.setReadOnly(False)
        self.chat_input.setFocus()
        self.send_button.setEnabled(True)

    def stream_response(self, chunk):
        """Handle streaming response chunks"""
        if not hasattr(self, 'current_ai_message'):
            self._remove_thinking()
            self.current_ai_message = ""
            self.current_ai_widget = MessageWidget("", is_user=False, luna=self.use_luna)
            self.message_layout.addWidget(self.current_ai_widget)
            self.last_update_time = 0
            QTimer.singleShot(0, self._scroll_to_bottom)

        self.current_ai_message += chunk
        
        # Throttle updates to every 100ms for smooth rendering
        import time
        current_time = time.time()
        if not hasattr(self, 'last_update_time'):
            self.last_update_time = 0
            
        if current_time - self.last_update_time >= 0.1:  # 100ms throttle
            self.current_ai_widget.set_text(self.current_ai_message)
            self.last_update_time = current_time
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _set_stop_button(self, is_running: bool):
        if is_running:
            self.send_button.setText("◼")
            self.send_button.setToolTip("Stop agent execution")
            self.send_button.setStyleSheet(
                "QPushButton { background: #D32F2F; color: white; border: none; "
                "border-radius: 12px; min-width: 40px; max-width: 40px; min-height: 40px; "
                "font-size: 16px; font-weight: bold; } QPushButton:hover { background: #B71C1C; }"
            )
            self.send_button.setEnabled(True)
        else:
            self.send_button.setText("↑")
            self.send_button.setToolTip("Send message")
            self.setStyleSheet(self._stylesheet())

    def _choose_workspace_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Workspace Folder", str(self.workspace.root))
        if folder:
            self.workspace.set_root(folder)
            self.workspace_bar.update_workspace()
            if hasattr(self.sidebar, 'file_tree'):
                self.sidebar.file_tree.workspace = self.workspace
                self.sidebar.file_tree.refresh_tree()

    def _set_auto_run(self, enabled: bool):
        self.auto_run = enabled

    def _refresh_workspace(self):
        self.workspace_bar.update_workspace()
        if hasattr(self.sidebar, 'file_tree'):
            self.sidebar.file_tree.refresh_tree()

    def _on_file_selected_from_tree(self, rel_path: str):
        curr = self.chat_input.toPlainText()
        if not curr.strip():
            self.chat_input.setPlainText(f"Inspect and work on {rel_path}: ")
        else:
            self.chat_input.setPlainText(f"{curr} {rel_path}")
        self.chat_input.setFocus()

    def _on_agent_status(self, status_msg: str):
        if self.thinking_widget:
            for lbl in self.thinking_widget.findChildren(QLabel):
                if lbl.objectName() == "thinkingText":
                    lbl.setText(status_msg)
                    break

    def _on_agent_stream_chunk(self, chunk: str):
        """Handle a streaming text chunk from the agent's current response step."""
        self._remove_thinking()
        if not hasattr(self, 'current_ai_message'):
            self.current_ai_message = ""
            self.current_ai_widget = MessageWidget("", is_user=False, luna=self.use_luna)
            self.message_layout.addWidget(self.current_ai_widget)
            self.last_update_time = 0

        self.current_ai_message += chunk
        current_time = time.time()
        if not hasattr(self, 'last_update_time'):
            self.last_update_time = 0
        if current_time - self.last_update_time >= 0.08:
            self.current_ai_widget.set_text(self.current_ai_message)
            self.last_update_time = current_time
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _on_tool_started(self, tool_name: str, args: dict, call_id: str):
        """When a tool starts, finalize any partial streamed text and show the tool card."""
        self._remove_thinking()
        # If there was a streaming AI message in progress, finalize it as its own bubble
        if hasattr(self, 'current_ai_message') and self.current_ai_message.strip():
            self.current_ai_widget.set_text(self.current_ai_message)
        if hasattr(self, 'current_ai_message'):
            del self.current_ai_message
        if hasattr(self, 'current_ai_widget'):
            del self.current_ai_widget

        card = ToolCardWidget(tool_name, args, call_id, luna=self.use_luna)
        card.set_running()
        self.active_tool_cards[call_id] = card
        self.message_layout.addWidget(card)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _on_tool_needs_approval(self, tool_name: str, args: dict, call_id: str):
        """When a tool needs approval, finalize any partial streamed text and show the approval card."""
        self._remove_thinking()
        if hasattr(self, 'current_ai_message') and self.current_ai_message.strip():
            self.current_ai_widget.set_text(self.current_ai_message)
        if hasattr(self, 'current_ai_message'):
            del self.current_ai_message
        if hasattr(self, 'current_ai_widget'):
            del self.current_ai_widget

        card = ToolCardWidget(tool_name, args, call_id, luna=self.use_luna)
        card.set_needs_approval()
        card.approved.connect(lambda cid: self.agent_thread.approve_tool(cid) if self.agent_thread else None)
        card.rejected.connect(lambda cid: self.agent_thread.reject_tool(cid) if self.agent_thread else None)
        self.active_tool_cards[call_id] = card
        self.message_layout.addWidget(card)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _on_tool_finished(self, tool_name: str, args: dict, output_str: str, success: bool, call_id: str, extra_meta: dict):
        """Update the tool card when the tool execution completes. Refresh file tree if a file was written."""
        card = self.active_tool_cards.get(call_id)
        if card:
            card.set_finished(output_str, success)
        # Refresh workspace file tree whenever files/dirs are modified
        if tool_name in (
            "write_file", "edit_file", "patch_file", "append_file", "scaffold_project",
            "delete_file", "rename_file", "create_dir", "undo_last_edit"
        ) and success:
            if hasattr(self.sidebar, 'file_tree'):
                self.sidebar.file_tree.refresh_tree()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _on_agent_finished(self, final_response: str):
        """Called when the agent loop finishes — finalize any remaining streamed message."""
        self._remove_thinking()
        # Finalize any in-progress streamed bubble
        if hasattr(self, 'current_ai_message') and self.current_ai_message.strip():
            self.current_ai_widget.set_text(self.current_ai_message)
            # Only add to history if AgentThread hasn't already done so
            # (AgentThread appends AIMessage after each step, so we skip double-appending)
        if hasattr(self, 'current_ai_message'):
            del self.current_ai_message
        if hasattr(self, 'current_ai_widget'):
            del self.current_ai_widget

        self._set_stop_button(False)
        self.chat_input.setReadOnly(False)
        self.chat_input.setFocus()
        self._auto_save()
        self.sidebar.refresh_recent_chats()
        if hasattr(self.sidebar, 'file_tree'):
            self.sidebar.file_tree.refresh_tree()
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _auto_save(self, also_save_named=False):
        """Auto-save current conversation. Optionally also write a named timestamped file."""
        # Only save if there's at least one real user message
        has_user_msg = any(isinstance(m, HumanMessage) for m in self.conversation_history)
        if not self.conversation_history or not has_user_msg:
            return

        # Generate title from first user message
        title = "Untitled Chat"
        for msg in self.conversation_history:
            if isinstance(msg, HumanMessage):
                title = msg.content.strip()
                title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                if len(title) > 30:
                    title = title[:30] + "..."
                if not title:
                    title = "Untitled Chat"
                break

        chat_data = {
            "timestamp": datetime.now().isoformat(),
            "title": title,
            "messages": [
                {
                    "type": msg.__class__.__name__,
                    "content": msg.content
                }
                for msg in self.conversation_history
            ]
        }

        # Always update latest.json
        latest_path = CHATS_DIR / "latest.json"
        with open(latest_path, 'w', encoding='utf-8') as f:
            json.dump(chat_data, f, indent=2, ensure_ascii=False)

        # Also write a named file so it shows in recent chats
        if also_save_named:
            # Use a stable filename keyed to the session start so repeated
            # close/reopen doesn't create duplicates for the same conversation.
            if not hasattr(self, '_session_filename'):
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                self._session_filename = CHATS_DIR / f"chat_{ts}.json"
            with open(self._session_filename, 'w', encoding='utf-8') as f:
                json.dump(chat_data, f, indent=2, ensure_ascii=False)

    def closeEvent(self, event):
        """Save conversation to recent chats when closing."""
        self._auto_save(also_save_named=True)
        event.accept()

    def save_conversation(self):
        """Save current conversation to a file"""
        if not self.conversation_history:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"chat_{timestamp}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Conversation",
            str(CHATS_DIR / default_name),
            "JSON Files (*.json)"
        )

        if file_path:
            # Generate title from first user message
            title = "Untitled Chat"
            for msg in self.conversation_history:
                if isinstance(msg, HumanMessage):
                    title = msg.content.strip()
                    # Remove special characters and limit length
                    title = ''.join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                    if len(title) > 30:
                        title = title[:30] + "..."
                    if not title:
                        title = "Untitled Chat"
                    break

            chat_data = {
                "timestamp": datetime.now().isoformat(),
                "title": title,
                "messages": [
                    {
                        "type": msg.__class__.__name__,
                        "content": msg.content
                    }
                    for msg in self.conversation_history
                ]
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(chat_data, f, indent=2, ensure_ascii=False)

            # Refresh sidebar
            self.sidebar.refresh_recent_chats()

    def load_conversation(self):
        """Load a conversation from a file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Conversation",
            str(CHATS_DIR),
            "JSON Files (*.json)"
        )

        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    chat_data = json.load(f)

                self.start_new_chat()
                for msg_data in chat_data.get("messages", []):
                    msg_type = msg_data["type"]
                    content = msg_data["content"]

                    if msg_type == "HumanMessage":
                        self.conversation_history.append(HumanMessage(content=content))
                        self._add_message(content, is_user=True)
                    elif msg_type == "AIMessage":
                        self.conversation_history.append(AIMessage(content=content))
                        self._add_message(content, is_user=False)
                    elif msg_type == "SystemMessage":
                        self.conversation_history.append(SystemMessage(content=content))

            except Exception as e:
                self._add_message(f"Error loading conversation: {e}", is_user=False)

    def show_error(self, error):
        self._remove_thinking()
        self._set_stop_button(False)
        active_model = LUNA_MODEL_NAME if self.use_luna else MODEL_NAME
        self._add_message(
            f"I couldn't reach the local model. Make sure Ollama is running and the "
            f"'{active_model}' model is installed.\n\nDetails: {error}",
            is_user=False,
        )
        self._ready()

    def _ready(self):
        self.chat_input.setReadOnly(False)
        self.chat_input.setFocus()
        self.send_button.setEnabled(True)
        self._scroll_to_bottom()

    def _maybe_show_whats_new(self):
        """Show the What's New dialog if this version hasn't been seen before."""
        version_file = Path.home() / ".sierra" / "last_seen_version.txt"
        try:
            last_seen = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
        except Exception:
            last_seen = ""

        if last_seen != APP_VERSION:
            dlg = WhatsNewDialog(self)
            # Centre over the main window
            dlg.move(
                self.x() + (self.width()  - dlg.width())  // 2,
                self.y() + (self.height() - dlg.height()) // 2,
            )
            dlg.exec_()
            # Mark this version as seen
            try:
                version_file.parent.mkdir(parents=True, exist_ok=True)
                version_file.write_text(APP_VERSION, encoding="utf-8")
            except Exception:
                pass

    def _resize_input(self):
        """Grow the chat input vertically to fit content, up to its maximum height."""
        doc_height = int(self.chat_input.document().size().height())
        margins = self.chat_input.contentsMargins()
        new_height = doc_height + margins.top() + margins.bottom() + 16
        new_height = max(44, min(new_height, 200))
        self.chat_input.setFixedHeight(new_height)

    def _scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(f"{APP_NAME} {APP_VERSION}")
    window = LocalAIApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
