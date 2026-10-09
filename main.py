import sys
import json
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md_to_text
from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QPixmap, QTextDocument
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
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
APP_VERSION = "1.0"
MODEL_NAME = "llama3"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "sierra-desert-icon.png"
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

    def __init__(self, messages, use_search=False, stream=False, temperature=0.7):
        super().__init__()
        self.messages = list(messages)
        self.use_search = use_search
        self.stream = stream
        self.temperature = temperature

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
                llm = ChatOllama(model=MODEL_NAME, temperature=self.temperature)
                full_response = ""
                for chunk in llm.stream(self.messages):
                    if hasattr(chunk, 'content'):
                        content = chunk.content
                        full_response += content
                        self.stream_chunk.emit(content)
                self.response_ready.emit(full_response)
            else:
                # Non-streaming response
                answer = ChatOllama(model=MODEL_NAME, temperature=self.temperature).invoke(self.messages)
                self.response_ready.emit(str(answer.content))
        except Exception as exc:
            self.error.emit(str(exc))


class SierraMark(QLabel):
    """Display the supplied desert icon with a gradient background."""

    def __init__(self, size=52, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self._size = size
        pixmap = QPixmap(str(ICON_PATH))
        if pixmap.isNull():
            self.setText("S")
            self.setObjectName("iconFallback")
            return
        self.setPixmap(
            pixmap.scaled(
                size,
                size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QLinearGradient, QColor, QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self._size, self._size, self._size * 0.23, self._size * 0.23)
        grad = QLinearGradient(0, 0, self._size, self._size)
        grad.setColorAt(0.0, QColor("#C87838"))
        grad.setColorAt(0.5, QColor("#8B4520"))
        grad.setColorAt(1.0, QColor("#4A1E08"))
        painter.fillPath(path, grad)
        painter.end()
        super().paintEvent(event)


class GradientFrame(QFrame):
    """A QFrame that paints a gradient border around its contents."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QLinearGradient, QColor, QPainterPath
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # Draw gradient border
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor("#D4874A"))
        grad.setColorAt(0.5, QColor("#8B4520"))
        grad.setColorAt(1.0, QColor("#5A2A0C"))
        outer = QPainterPath()
        outer.addRoundedRect(0, 0, w, h, 12, 12)
        inner = QPainterPath()
        inner.addRoundedRect(1.5, 1.5, w - 3, h - 3, 11, 11)
        border_path = outer - inner
        painter.fillPath(border_path, grad)
        # Fill interior
        painter.fillPath(inner, QColor("#18130F"))
        painter.end()


class TrafficButton(QPushButton):
    def __init__(self, object_name, tooltip, parent=None):
        super().__init__("", parent)
        self.setObjectName(object_name)
        self.setToolTip(tooltip)
        self.setFixedSize(46, 32)
        self.setCursor(Qt.PointingHandCursor)
        # Add symbols
        if object_name == "trafficClose":
            self.setText("✕")
        elif object_name == "trafficMinimize":
            self.setText("−")
        elif object_name == "trafficMaximize":
            self.setText("□")


class TitleBar(QFrame):
    """A practical, Windows-friendly frameless title bar in the reference's style."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titleBar")
        self._drag_origin = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 0, 0)
        layout.setSpacing(10)

        title_icon = QLabel("✥")
        title_icon.setObjectName("titleIcon")
        layout.addWidget(title_icon)
        title = QLabel("New Chat")
        title.setObjectName("titleText")
        layout.addWidget(title)
        layout.addStretch()

        for glyph, tooltip in (("♜", "Start a new chat"), ("💾", "Save Chat"), ("📂", "Load Chat"), ("⚙", "Settings"), ("◉", "Local profile")):
            button = QPushButton(glyph)
            button.setObjectName("topIconButton")
            button.setToolTip(tooltip)
            button.setCursor(Qt.PointingHandCursor)
            if tooltip == "Start a new chat":
                button.clicked.connect(lambda checked=False: self.window().start_new_chat())
            elif tooltip == "Save Chat":
                button.clicked.connect(lambda checked=False: self.window().save_conversation())
            elif tooltip == "Load Chat":
                button.clicked.connect(lambda checked=False: self.window().load_conversation())
            layout.addWidget(button)

        # Add window controls on the right
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
        super().__init__(f"{icon}    {label}", parent)
        self.setObjectName("navButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(48)
        self.setCheckable(True)


class RecentChat(QPushButton):
    def __init__(self, title, age, parent=None):
        super().__init__(parent)
        self.setObjectName("recentChat")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(54)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)
        icon = QLabel("▢")
        icon.setObjectName("recentIcon")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(32, 32)
        layout.addWidget(icon)
        labels = QVBoxLayout()
        labels.setSpacing(3)
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
    chat_loaded = pyqtSignal(str)  # Signal with file path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(316)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 32, 18, 24)
        layout.setSpacing(10)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)
        brand_row.addWidget(SierraMark(48))
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(2)
        wordmark = QLabel(f"{APP_NAME} <span>{APP_VERSION}</span>")
        wordmark.setObjectName("wordmark")
        descriptor = QLabel("Your local Llama assistant")
        descriptor.setObjectName("brandDescription")
        brand_copy.addWidget(wordmark)
        brand_copy.addWidget(descriptor)
        brand_row.addLayout(brand_copy)
        brand_row.addStretch()
        layout.addLayout(brand_row)
        layout.addSpacing(30)

        self.new_chat = NavButton("✎", "New Chat")
        self.new_chat.setObjectName("navButtonActive")
        self.new_chat.setChecked(True)
        self.new_chat.clicked.connect(self._new_chat)
        layout.addWidget(self.new_chat)

        self.search = NavButton("⌕", "Search")
        self.search.toggled.connect(self._search_toggled)
        self.search.clicked.connect(lambda checked=False: self._select(self.search))
        layout.addWidget(self.search)

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        divider.setFrameShape(QFrame.HLine)
        layout.addSpacing(24)
        layout.addWidget(divider)
        layout.addSpacing(14)

        recent_heading = QLabel("Recent Chats")
        recent_heading.setObjectName("sectionHeading")
        layout.addWidget(recent_heading)

        # Load actual saved chats
        self.recent_chats_widget = QWidget()
        self.recent_chats_layout = QVBoxLayout(self.recent_chats_widget)
        self.recent_chats_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_chats_layout.setSpacing(6)
        self._load_recent_chats()
        layout.addWidget(self.recent_chats_widget)
        layout.addStretch()

        model_card = QFrame()
        model_card.setObjectName("sidebarModelCard")
        model_layout = QHBoxLayout(model_card)
        model_layout.setContentsMargins(10, 11, 9, 11)
        model_layout.setSpacing(10)
        model_layout.addWidget(SierraMark(42))
        model_copy = QVBoxLayout()
        model_copy.setSpacing(1)
        model_title = QLabel(f"{APP_NAME} {APP_VERSION}")
        model_title.setObjectName("sidebarModelTitle")
        model_subtitle = QLabel("Llama 3 · 8B · Local")
        model_subtitle.setObjectName("sidebarModelSubtitle")
        online = QLabel("●  Online")
        online.setObjectName("onlineIndicator")
        model_copy.addWidget(model_title)
        model_copy.addWidget(model_subtitle)
        model_copy.addWidget(online)
        model_layout.addLayout(model_copy)
        model_layout.addStretch()
        chevron = QLabel("›")
        chevron.setObjectName("cardChevron")
        model_layout.addWidget(chevron)
        layout.addWidget(model_card)

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
        self.setMinimumHeight(84)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 12, 14, 12)
        layout.setSpacing(12)
        icon_label = QLabel(icon)
        icon_label.setObjectName("actionIcon")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(40, 40)
        layout.addWidget(icon_label)
        copy = QVBoxLayout()
        copy.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("actionTitle")
        detail = QLabel(subtitle)
        detail.setObjectName("actionSubtitle")
        copy.addWidget(heading)
        copy.addWidget(detail)
        layout.addLayout(copy, 1)
        arrow = QLabel("›")
        arrow.setObjectName("cardChevron")
        layout.addWidget(arrow)


class WelcomeView(QWidget):
    prompt_chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(54, 30, 54, 30)
        layout.setSpacing(0)
        layout.addStretch(1)

        mark_row = QHBoxLayout()
        mark_row.addStretch()
        mark_row.addWidget(SierraMark(94))
        mark_row.addStretch()
        layout.addLayout(mark_row)
        layout.addSpacing(22)

        title = QLabel(f"{APP_NAME} <span>{APP_VERSION}</span>")
        title.setObjectName("heroTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel("Your local Llama assistant.")
        subtitle.setObjectName("heroSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)
        layout.addSpacing(25)
        description = QLabel("Ask me anything, get help with your ideas, or just have a conversation.")
        description.setObjectName("heroDescription")
        description.setAlignment(Qt.AlignCenter)
        layout.addWidget(description)
        layout.addSpacing(46)

        cards = QGridLayout()
        cards.setHorizontalSpacing(18)
        cards.setVerticalSpacing(17)
        entries = (
            ("◉", "Get answers", "Ask questions about anything.", "Answer this question clearly: "),
            ("</>", "Write code", "Debug, build, or learn to code.", "Help me write clean code for: "),
            ("▤", "Summarise", "Turn long text into short summaries.", "Summarise the following in clear bullet points: "),
            ("✦", "Be creative", "Brainstorm ideas and more.", "Brainstorm original ideas for: "),
        )
        for index, (icon, title_text, detail, prompt) in enumerate(entries):
            card = ActionCard(icon, title_text, detail, prompt)
            card.clicked.connect(lambda checked=False, text=prompt: self.prompt_chosen.emit(text))
            cards.addWidget(card, index // 2, index % 2)
        layout.addLayout(cards)
        layout.addStretch(2)


class MessageWidget(QWidget):
    def __init__(self, message, is_user, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 4)
        root.setSpacing(11)

        avatar = QLabel("YOU" if is_user else "AI")
        avatar.setObjectName("userAvatar" if is_user else "assistantAvatar")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignTop | Qt.AlignCenter)

        self.bubble = QTextEdit()
        self.bubble.setObjectName("userMessage" if is_user else "assistantMessage")
        self.bubble.setReadOnly(True)
        self.bubble.setLineWrapMode(QTextEdit.WidgetWidth)
        self.bubble.setFont(QFont("Segoe UI", 15))
        self.bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.bubble.setMinimumHeight(52)
        self.bubble.document().setDocumentMargin(8)

        if is_user:
            self.bubble.setStyleSheet(
                "QTextEdit { background: #3D2A1A; color: #E8B97A; border-radius: 12px; "
                "padding: 12px 16px; border: 1px solid #6B4428; font-size: 15px; }"
            )
        else:
            self.bubble.setStyleSheet(
                "QTextEdit { background: #2C2018; color: #D4A068; border-radius: 12px; "
                "padding: 12px 16px; border: 1px solid #4A3020; font-size: 15px; }"
            )

        self.set_message_text(message)
        self._adjust_height()

        if is_user:
            # User messages: bubble hugs right, grows left for longer text (max 75% width)
            root.addStretch(1)
            root.addWidget(self.bubble, 3)
            root.addWidget(avatar)
        else:
            # AI messages: fill the full width
            root.addWidget(avatar)
            root.addWidget(self.bubble, 1)

    def _adjust_height(self):
        self.bubble.document().adjustSize()
        doc_h = self.bubble.document().size().height()
        self.bubble.setFixedHeight(int(doc_h) + 24)

    def set_message_text(self, text):
        """Render markdown to HTML and display in bubble."""
        import markdown as md_lib
        html_body = md_lib.markdown(
            text,
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
        )
        text_color = "#E8B97A" if self.is_user else "#D4A068"
        html = f"""
        <html><body style="
            font-family: 'Segoe UI', Arial, sans-serif;
            font-size: 15px;
            line-height: 1.6;
            color: {text_color};
            margin: 0; padding: 0;
        ">{html_body}</body></html>
        """
        self.bubble.setHtml(html)

    def set_text(self, text):
        """Update the message text (for streaming)"""
        self.set_message_text(text)
        self._adjust_height()


class ThinkingWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("thinkingWidget")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(11)
        layout.addWidget(SierraMark(30))
        self.label = QLabel()
        self.label.setObjectName("thinkingText")
        layout.addWidget(self.label)
        self.timer = QTimer(self)
        self.count = 0
        self.timer.timeout.connect(self._animate)
        self._animate()

    def _animate(self):
        self.count = (self.count + 1) % 4
        self.label.setText("AI is typing" + "." * self.count)

    def stop(self):
        self.timer.stop()


class ModelPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modelPanel")
        self.setFixedWidth(350)
        self._build()

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
        model_top.addWidget(SierraMark(62))
        model_names = QVBoxLayout()
        model_names.setSpacing(2)
        name = QLabel("Llama 3 8B")
        name.setObjectName("modelName")
        status = QLabel("●  Running Locally")
        status.setObjectName("runningStatus")
        model_names.addWidget(name)
        model_names.addWidget(status)
        model_top.addLayout(model_names)
        model_top.addStretch()
        card_layout.addLayout(model_top)
        description = QLabel(
            "Meta's Llama 3 8B model, running on your device for privacy and speed."
        )
        description.setObjectName("modelDescription")
        description.setWordWrap(True)
        card_layout.addWidget(description)
        divider = QFrame()
        divider.setObjectName("panelDivider")
        divider.setFrameShape(QFrame.HLine)
        card_layout.addWidget(divider)
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
            row.addWidget(key_label)
            row.addStretch()
            row.addWidget(value_label)
            card_layout.addLayout(row)
        change = QPushButton("Change Model                                      ›")
        change.setObjectName("changeModelButton")
        change.setToolTip("Model selection can be added when more Ollama models are installed.")
        card_layout.addSpacing(2)
        card_layout.addWidget(change)
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


class LocalAIApp(QMainWindow):
    SYSTEM_PROMPT = (
        "You are Sierra, a friendly, capable local AI assistant. Be concise, clear, "
        "and conversational. Use Markdown only when it improves readability."
    )

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION} — Local AI Workspace")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(1260, 770)
        self.resize(1536, 972)
        self.conversation_history = []
        self.use_search = False
        self.chat_thread = None
        self.thinking_widget = None
        self._attached_file = None
        self.setStyleSheet(self._stylesheet())
        self._build()
        self._load_latest_chat()
        self.start_new_chat()

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QLinearGradient, QColor
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        grad = QLinearGradient(0, 0, self.width(), self.height())
        grad.setColorAt(0.0,  QColor("#0A0906"))   # near-black
        grad.setColorAt(0.45, QColor("#1A1008"))   # very dark amber-brown
        grad.setColorAt(0.75, QColor("#3A1E0A"))   # deep desert
        grad.setColorAt(1.0,  QColor("#6B3510"))   # warm desert amber
        painter.fillRect(self.rect(), grad)
        painter.end()

    @staticmethod
    def _stylesheet():
        return """
            * { font-family: 'Segoe UI', Arial, sans-serif; }
            QMainWindow { background: transparent; }
            QFrame#appShell { background: rgba(10, 8, 6, 0.82); border: 1px solid rgba(180, 100, 40, 0.35); border-radius: 12px; }
            QFrame#titleBar { background: #151311; border-bottom: 1px solid #352C26; min-height: 58px; max-height: 58px; border-top-right-radius: 12px; }
            QFrame#windowControls { background: transparent; border: none; }
            QPushButton#trafficClose, QPushButton#trafficMinimize, QPushButton#trafficMaximize { border: none; border-radius: 0; color: #C0C0C0; font-size: 14px; font-weight: bold; }
            QPushButton#trafficClose { background: transparent; } QPushButton#trafficMinimize { background: transparent; } QPushButton#trafficMaximize { background: transparent; }
            QPushButton#trafficClose:hover { background: #E81123; color: white; } QPushButton#trafficMinimize:hover { background: #4C4C4C; color: white; } QPushButton#trafficMaximize:hover { background: #4C4C4C; color: white; }
            QLabel#titleIcon { color: #D59A6E; font-size: 21px; }
            QLabel#titleText { color: #F1E9E0; font-size: 16px; font-weight: 600; }
            QPushButton#topIconButton { color: #C9A68B; background: transparent; border: none; font-size: 20px; min-width: 30px; }
            QPushButton#topIconButton:hover { color: #F3D1B3; }
            QFrame#sidebar { background: #15120F; border: none; border-right: 1px solid #352C26; border-bottom-left-radius: 12px; }
            QLabel#wordmark { color: #F1E9E0; font-size: 23px; font-weight: 700; }
            QLabel#wordmark span, QLabel#heroTitle span { color: #D08C5C; }
            QLabel#brandDescription { color: #BDA792; font-size: 13px; }
            QPushButton#navButton, QPushButton#navButtonActive { color: #C4B7A9; background: transparent; border: none; border-radius: 12px; padding: 0 14px; text-align: left; font-size: 15px; }
            QPushButton#navButton:hover { background: #2A211B; color: #F1E4D8; }
            QPushButton#navButton:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4A2E1A, stop:1 #3E2010); color: #FFF9F3; }
            QPushButton#navButtonActive { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6B4020, stop:1 #4A2810); color: #FFF9F3; font-weight: 600; }
            QPushButton#navButtonActive:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7D4D28, stop:1 #5A3418); }
            QFrame#sidebarDivider, QFrame#panelDivider { color: #3A302A; background: #3A302A; max-height: 1px; }
            QLabel#sectionHeading { color: #D3BDA9; font-size: 14px; font-weight: 500; padding: 0 0 7px 8px; }
            QFrame#recentChat { background: transparent; border-radius: 8px; }
            QFrame#recentChat:hover { background: #282019; }
            QLabel#recentIcon { color: #E0B187; background: #2A211B; border-radius: 8px; font-size: 15px; }
            QLabel#recentName { color: #D0C0B1; font-size: 14px; font-weight: 500; } QLabel#recentAge { color: #9D8877; font-size: 12px; }
            QFrame#sidebarModelCard { background: #211914; border: 1px solid #503827; border-radius: 12px; }
            QLabel#sidebarModelTitle { color: #F1E9E0; font-size: 14px; font-weight: 600; }
            QLabel#sidebarModelSubtitle { color: #C1A78F; font-size: 11px; } QLabel#onlineIndicator { color: #55D8A7; font-size: 11px; }
            QLabel#cardChevron { color: #D9AC85; font-size: 28px; font-weight: 200; }
            QScrollArea { background: transparent; border: none; } QScrollBar:vertical { background: transparent; width: 8px; margin: 8px 1px; }
            QScrollBar::handle:vertical { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #C8773A, stop:1 #7A3E1A); border-radius: 4px; min-height: 38px; } QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QWidget#centralPane { background: #0D0C0B; }
            QLabel#heroTitle { color: #F2EAE1; font-size: 51px; font-weight: 700; }
            QLabel#heroSubtitle { color: #D2B9A3; font-size: 20px; } QLabel#heroDescription { color: #AA9788; font-size: 15px; }
            QPushButton#actionCard { background: #191512; border: 1px solid #342A23; border-radius: 12px; text-align: left; }
            QPushButton#actionCard:hover { background: #251B16; border-color: #754C34; }
            QLabel#actionIcon { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3A2418, stop:1 #251710); color: #E2B189; border-radius: 12px; font-size: 17px; font-weight: 700; }
            QLabel#actionTitle { color: #F0E6DD; font-size: 14px; font-weight: 600; } QLabel#actionSubtitle { color: #B7A18E; font-size: 12px; }
            QFrame#composer { background: transparent; border: none; border-radius: 12px; }
            QTextEdit#chatInput { color: #F0E8E0; background: transparent; border: none; padding: 12px 18px; font-size: 15px; selection-background-color: #885334; }
            QTextEdit#chatInput:focus { border: none; }
            QPushButton#composerButton { color: #D0B89F; background: #2A211B; border: none; border-radius: 12px; padding: 0 13px; min-height: 39px; font-size: 13px; }
            QPushButton#composerButton:hover, QPushButton#composerButton:checked { color: #FFF7F0; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7A4828, stop:1 #4E2C14); }
            QPushButton#attachButton { color: #D0B89F; background: #2A211B; border: none; border-radius: 12px; min-height: 39px; min-width: 40px; max-width: 40px; font-size: 23px; }
            QPushButton#attachButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7A4828, stop:1 #4E2C14); color: #FFF7F0; }
            QPushButton#sendButton { color: #FFF8F1; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F09040, stop:1 #7A3010); border: none; border-radius: 12px; min-width: 40px; max-width: 40px; min-height: 40px; font-size: 21px; font-weight: 600; }
            QPushButton#sendButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFB060, stop:1 #993820); } QPushButton#sendButton:disabled { background: #493127; color: #A58A78; }
            QFrame#modelPanel { background: #12100E; border: none; border-left: 1px solid #352C26; border-bottom-right-radius: 12px; }
            QLabel#panelHeadingIcon, QLabel#featureSparkle { color: #D7A178; font-size: 20px; } QLabel#panelHeading { color: #E9DDD2; font-size: 17px; font-weight: 600; }
            QLabel#tuningIcon { color: #D7A178; font-size: 20px; } QFrame#modelCard, QFrame#darkModeCard { background: #1A1512; border: 1px solid #3C3028; border-radius: 12px; }
            QLabel#modelName { color: #F0E8E0; font-size: 16px; font-weight: 600; } QLabel#runningStatus { color: #50D5A3; font-size: 12px; }
            QLabel#modelDescription { color: #C6B09A; font-size: 13px; line-height: 1.5; } QLabel#statKey { color: #C9B5A1; font-size: 13px; } QLabel#statValue { color: #E0C5AC; font-size: 13px; }
            QPushButton#changeModelButton { color: #DEC3AA; background: #231A15; border: 1px solid #493528; border-radius: 12px; min-height: 40px; padding: 0 12px; text-align: left; font-size: 13px; }
            QPushButton#changeModelButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4A2E18, stop:1 #2E1C0E); color: #FFF7F0; }
            QLabel#featureIcon { color: #D9AA81; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #35231A, stop:1 #1E130C); border-radius: 12px; font-size: 18px; } QLabel#featureTitle { color: #E2D2C2; font-size: 13px; font-weight: 500; } QLabel#featureDetail { color: #A9927F; font-size: 11px; }
            QCheckBox#darkToggle::indicator { width: 39px; height: 24px; border-radius: 12px; background: #4C3A2F; } QCheckBox#darkToggle::indicator:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E08844, stop:1 #8C4418); } QCheckBox#darkToggle::indicator:checked:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F09A55, stop:1 #A05025); }
            QLabel#assistantAvatar { color: #FFF4E9; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #A86030, stop:1 #5A2E10); border-radius: 12px; font-size: 9px; font-weight: 800; } QLabel#userAvatar { color: #EAD7C3; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3E2D22, stop:1 #241610); border: 1px solid #60432F; border-radius: 12px; font-size: 8px; font-weight: 800; }
            QLabel#messageMeta { color: #AA9280; font-size: 10px; } QTextEdit#assistantMessage { color: #E9DED3; background: #2A2A2A; border-radius: 12px; padding: 12px 16px; font-size: 15px; } QTextEdit#userMessage { color: #F0EDE8; background: #3A3A3A; border-radius: 12px; padding: 12px 16px; font-size: 15px; }
            QTextEdit { border: none; }
            QFrame#thinkingWidget { background: transparent; border: none; } QLabel#thinkingText { color: #D7C1AB; font-size: 13px; font-weight: 600; }
            QLabel#iconFallback { color: #E8C09B; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4A2E1C, stop:1 #271610); border-radius: 12px; font-size: 18px; font-weight: 700; }
        """

    def _build(self):
        outer = QWidget()
        outer.setStyleSheet("background: transparent;")
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(12, 18, 12, 18)
        self.setCentralWidget(outer)

        shell = QFrame()
        shell.setObjectName("appShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        sidebar_column = QVBoxLayout()
        sidebar_column.setContentsMargins(0, 0, 0, 0)
        sidebar_column.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.new_chat_requested.connect(self.start_new_chat)
        self.sidebar.search_toggled.connect(self.set_search)
        self.sidebar.chat_loaded.connect(self.load_chat)
        sidebar_column.addWidget(self.sidebar, 1)
        shell_layout.addLayout(sidebar_column)

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
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.message_host = QWidget()
        self.message_host.setStyleSheet("background: transparent;")
        self.message_layout = QVBoxLayout(self.message_host)
        self.message_layout.setContentsMargins(60, 40, 60, 40)
        self.message_layout.setSpacing(28)
        self.message_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.message_host)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self._build_composer())
        return pane

    def _build_composer(self):
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(20, 0, 20, 28)
        layout.setSpacing(0)
        composer = GradientFrame()
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(20, 14, 20, 14)
        composer_layout.setSpacing(9)

        # Attachment indicator row (hidden until a file is attached)
        self.attach_row = QWidget()
        self.attach_row.setStyleSheet("background: transparent;")
        attach_row_layout = QHBoxLayout(self.attach_row)
        attach_row_layout.setContentsMargins(0, 0, 0, 0)
        attach_row_layout.setSpacing(6)
        self.attach_label = QLabel()
        self.attach_label.setObjectName("attachLabel")
        self.attach_label.setStyleSheet(
            "QLabel { color: #E8B97A; background: #3A2510; border: 1px solid #6B4428; "
            "border-radius: 8px; padding: 4px 10px; font-size: 12px; }"
        )
        remove_attach = QPushButton("✕")
        remove_attach.setFixedSize(22, 22)
        remove_attach.setStyleSheet(
            "QPushButton { color: #E8B97A; background: #3A2510; border: 1px solid #6B4428; "
            "border-radius: 6px; font-size: 11px; }"
            "QPushButton:hover { background: #6B2010; color: white; }"
        )
        remove_attach.clicked.connect(self._clear_attachment)
        attach_row_layout.addWidget(self.attach_label)
        attach_row_layout.addWidget(remove_attach)
        attach_row_layout.addStretch()
        self.attach_row.setVisible(False)
        composer_layout.addWidget(self.attach_row)

        self.chat_input = ChatInput()
        self.chat_input.setObjectName("chatInput")
        self.chat_input.setPlaceholderText(f"Message {APP_NAME}…")
        self.chat_input.setMinimumHeight(44)
        self.chat_input.setMaximumHeight(200)
        self.chat_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.chat_input.document().contentsChanged.connect(self._resize_input)
        self.chat_input.submitted.connect(self.send_message)
        composer_layout.addWidget(self.chat_input)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        attach = QPushButton("+")
        attach.setObjectName("attachButton")
        attach.setToolTip("Attach a file")
        attach.clicked.connect(self._attach_file)
        actions.addWidget(attach)
        self.search_button = QPushButton("◎  Search")
        self.search_button.setObjectName("composerButton")
        self.search_button.setCheckable(True)
        self.search_button.toggled.connect(self._composer_search_toggled)
        actions.addWidget(self.search_button)
        code = QPushButton("</>  Code")
        code.setObjectName("composerButton")
        code.clicked.connect(self._start_code_prompt)
        actions.addWidget(code)
        actions.addStretch()
        self.send_button = QPushButton("↑")
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setToolTip("Send message")
        self.send_button.clicked.connect(self.send_message)
        actions.addWidget(self.send_button)
        composer_layout.addLayout(actions)
        layout.addWidget(composer)
        return holder

    def _show_welcome(self):
        self.welcome = WelcomeView()
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
        if self.chat_thread and self.chat_thread.isRunning():
            return
        while self.message_layout.count():
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.conversation_history = [SystemMessage(content=self.SYSTEM_PROMPT)]
        self.thinking_widget = None
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

    def send_message(self):
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
        self.chat_input.setReadOnly(True)
        self.send_button.setEnabled(False)
        self._add_thinking()
        temperature = self.model_panel.temp_slider.value() / 100
        self.chat_thread = ChatThread(self.conversation_history, self.use_search, stream=True, temperature=temperature)
        self.chat_thread.response_ready.connect(self.display_response)
        self.chat_thread.stream_chunk.connect(self.stream_response)
        self.chat_thread.error.connect(self.show_error)
        self.chat_thread.start()

    def _add_message(self, text, is_user):
        message = MessageWidget(text, is_user)
        self.message_layout.addWidget(message)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _add_thinking(self):
        self.thinking_widget = ThinkingWidget()
        self.thinking_row = QWidget()
        self.thinking_row.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(self.thinking_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.thinking_widget)
        row_layout.addStretch()
        self.message_layout.addWidget(self.thinking_row)
        QTimer.singleShot(0, self._scroll_to_bottom)
        # Start typing animation immediately
        self.thinking_widget.timer.start(200)  # Faster animation for typing

    def _remove_thinking(self):
        if self.thinking_widget:
            self.thinking_widget.stop()
            self.thinking_row.setParent(None)
            self.thinking_row.deleteLater()
            self.thinking_widget = None

    def display_response(self, response):
        """Called when streaming is complete"""
        if hasattr(self, 'current_ai_message'):
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
            self.current_ai_widget = MessageWidget("", is_user=False)
            self.message_layout.addWidget(self.current_ai_widget)
            QTimer.singleShot(0, self._scroll_to_bottom)

        self.current_ai_message += chunk
        self.current_ai_widget.set_text(self.current_ai_message)
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
        self._add_message(
            f"I couldn't reach the local model. Make sure Ollama is running and the "
            f"'{MODEL_NAME}' model is installed.\n\nDetails: {error}",
            is_user=False,
        )
        self._ready()

    def _ready(self):
        self.chat_input.setReadOnly(False)
        self.chat_input.setFocus()
        self.send_button.setEnabled(True)
        self._scroll_to_bottom()

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
