# Changelog

## Version 1.0 — Beta Release

### 🌙 Luna — Coding AI Mode
- Added **Luna mode**, a dedicated coding AI powered by Qwen 2.5 Coder 14B
- Switch between Sierra and Luna from the composer bar or sidebar
- Luna has its own dark blue starfield theme with animated fade transition
- Luna welcome screen shows coding-focused action cards (Write, Debug, Explain, Optimise)
- Luna icon, branding, and model panel all update when switching modes

### 🎨 Themes & UI
- **Desert gradient background** — warm amber-to-rust gradient for Sierra mode
- **Starfield background** — deep navy with scattered white stars for Luna mode
- **Animated theme transition** — smooth 600ms fade when switching between modes
- Gradient borders on the composer input box
- Gradient send button, scrollbar, and avatar icons

### 📎 File Attachments
- Click **+** to attach files directly to your messages
- Supports Word (.docx), PDF, plain text, Markdown, all major code formats, and CSV
- File badge shown in composer before sending — click ✕ to remove
- File content is sent to the AI silently; the chat bubble shows a clean filename

### 💬 Chat Improvements
- **Markdown rendering** — bold, italic, code blocks, tables, and lists all render properly
- Message bubbles match the active theme (amber for Sierra, blue for Luna)
- User messages align right with a coloured bubble; AI messages fill the full width
- Chat input auto-grows as you type, up to 200px tall

### 💾 Save & History
- Conversations **auto-save** when you close the app
- Saved chats appear in **Recent Chats** in the sidebar
- Each new conversation gets its own timestamped file — no duplicates

### ⚙️ Model Panel
- Temperature slider to control creativity (0.0 focused → 1.0 creative)
- Model panel updates to show correct model info for Sierra vs Luna
- **Change Model** moved into the composer bar as a dropdown

### 🐛 Bug Fixes
- Fixed crash when sending a message after the welcome screen was already cleaned up
- Fixed `sipBadCatcherResult` error from Luna menu click handler
- Fixed recent chats not appearing after closing mid-conversation
- Fixed duplicate `_select` method causing indent errors
