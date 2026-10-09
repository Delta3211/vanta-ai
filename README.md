# Vanta AI — Local AI Assistant (Beta)

> A beautiful, ChatGPT-style local AI chat app powered by Llama 3. Runs entirely on your computer. No API keys. No cloud. 100% private.

![Welcome Screen](assets/screenshot-welcome.png)

---

## ✨ Features

- 🤖 **Local AI** — Powered by Llama 3 via Ollama, runs fully on-device
- ⚡ **Streaming Responses** — Text appears as it generates, word by word
- 📎 **File Attachments** — Attach Word docs, PDFs, code files, CSVs and more — the AI reads them
- 💾 **Auto-Save** — Conversations save automatically on close and appear in Recent Chats
- 🌐 **Web Search** — Optional DuckDuckGo integration for up-to-date answers
- 🎨 **Desert Theme** — Warm amber gradient UI with dark tones
- 🖥️ **GPU Accelerated** — Optimized for NVIDIA GPUs (RTX 4070 SUPER tested)
- 💬 **Markdown Rendering** — Bold, italics, code blocks, tables all render properly
- 🕓 **Recent Chats** — Sidebar shows your last 5 conversations

---

## 📸 Screenshots

### Welcome Screen
![Welcome Screen](assets/screenshot-welcome.png)

### Chat
![Chat](assets/screenshot-chat.png)

### File Attachments
![File Attachment](assets/screenshot-attachment.png)

---

## 🚀 Quick Start

### Prerequisites

1. **Python 3.9+**
2. **Ollama** — [Download here](https://ollama.com/download)

### 1. Install Ollama & pull the model

```bash
ollama pull llama3
```

### 2. Clone & set up Vanta AI

```bash
git clone https://github.com/Delta3211/vanta-ai.git
cd vanta-ai
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run

```bash
python main.py
```

Or double-click **`run.bat`** on Windows.

---

## 🎯 Usage

| Action | How |
|---|---|
| Send a message | Type and press `Enter` |
| New line in input | `Shift+Enter` |
| Attach a file | Click **+** in the composer |
| Toggle web search | Click **Search** in the sidebar or composer |
| Save chat manually | Click 💾 in the title bar |
| Load a past chat | Click 📂 or pick from Recent Chats |
| New conversation | Click **New Chat** |

### Supported File Types for Attachment
`.txt` `.md` `.pdf` `.docx` `.py` `.js` `.ts` `.html` `.css` `.json` `.xml` `.yaml` `.csv` `.c` `.cpp` `.java` `.cs` `.go` and more

---

## ⚙️ Customization

### Change the model

Edit `main.py` line ~65:

```python
MODEL_NAME = "llama3"  # swap for mistral, gemma2, phi3, etc.
```

### Change the theme

All styling lives in the `_stylesheet()` method and the `paintEvent` of `LocalAIApp`. The palette is built around warm desert ambers.

---

## 🛠️ Project Structure

```
vanta-ai/
├── main.py              # Entire application
├── requirements.txt     # Python dependencies
├── run.bat              # Windows one-click launcher
├── assets/
│   ├── sierra-desert-icon.png
│   ├── screenshot-welcome.png
│   ├── screenshot-chat.png
│   └── screenshot-attachment.png
└── .sierra/             # Auto-created user data (chats stored here)
```

---

## 📦 Requirements

| Requirement | Minimum |
|---|---|
| OS | Windows 10/11 |
| Python | 3.9+ |
| RAM | 8 GB (16 GB recommended) |
| GPU | NVIDIA recommended (CUDA), CPU works too |
| Storage | 5 GB+ for models |

---

## 🐛 Troubleshooting

**"Ollama not running" error**
```bash
ollama serve
```

**Model not found**
```bash
ollama pull llama3
```

**Import errors**
```bash
venv\Scripts\activate
pip install -r requirements.txt
```

---

## ⚠️ Beta Notice

This is a **beta release**. Expect rough edges. Issues and PRs are welcome.

---

## 📄 License

MIT — see [LICENSE](LICENSE)

---

*Powered by [Ollama](https://ollama.com) · [LangChain](https://langchain.com) · [Meta Llama 3](https://llama.meta.com)*
