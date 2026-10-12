import re
import json
import uuid
import time
import webbrowser
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from PyQt5.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from workspace import WorkspaceManager

LUNA_AGENT_SYSTEM_PROMPT = """You are Luna, an elite autonomous coding AI and expert web designer.
You work directly inside the user's active workspace: {workspace_path}

You have full authority to inspect, create, edit, run, and restructure any code. You build complete, production-quality software — especially beautiful, modern websites and web apps that look stunning.

╔══════════════════════════════════════════════╗
║         ACTIVE WORKSPACE FILES               ║
╚══════════════════════════════════════════════╝
{workspace_files}

CRITICAL RULES REGARDING WORKSPACE FILES:
- The files listed above ALREADY EXIST in this project.
- When the user asks you to modify, update, redesign, restyle, or fix the project:
  1. DO NOT create new duplicate files (e.g. NEVER create index2.html, new_style.css, test.html).
  2. ALWAYS inspect the existing file first using `read_file`.
  3. Surgically update the existing file with `patch_file` or `edit_file`.
  4. DO NOT overwrite existing files from scratch with `write_file` unless the user explicitly requested a complete rewrite from scratch.

╔══════════════════════════════════════════════╗
║  CRITICAL RULE — ALWAYS WRITE TO WORKSPACE   ║
╚══════════════════════════════════════════════╝
Every single line of code you write MUST be saved directly to a workspace file via `write_file`, `edit_file`, or `patch_file`.
NEVER output a raw code block for the user to copy-paste. Always apply it directly.
Choose professional filenames: `index.html`, `style.css`, `script.js`, `main.py`, etc.

╔══════════════════════════════════════════════╗
║   CLAUDE-GRADE WEB DESIGN & ARCHITECTURE     ║
╚══════════════════════════════════════════════╝
You build software with the aesthetic excellence and complete feature-depth of Claude 3.7 Sonnet and v0.
Follow this EXACT architecture for all web apps:

## 1. THE MODERN DESIGN STACK (MANDATORY IN EVERY index.html)
To achieve world-class aesthetics, EVERY `index.html` MUST include in `<head>`:
- Tailwind CSS CDN: `<script src="https://cdn.tailwindcss.com"></script>`
- Lucide Icons CDN: `<script src="https://unpkg.com/lucide@latest"></script>`
- Google Fonts: `<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700;800&display=swap" rel="stylesheet">`
- Stylesheet: `<link rel="stylesheet" href="style.css">`
And at the bottom of `<body>`:
- Script: `<script src="script.js"></script>`
- Icons init: `<script>lucide.createIcons();</script>`

Using Tailwind CDN + Lucide Icons gives you an immediate superpower:
- Rich utility styling: `bg-slate-950 text-slate-100 font-sans`
- Glassmorphic panels: `bg-slate-900/60 backdrop-blur-2xl border border-white/10 rounded-2xl shadow-2xl`
- Sleek gradient buttons: `bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 text-white shadow-lg shadow-indigo-500/25`
- Crisp vector icons: `<i data-lucide="play" class="w-4 h-4"></i>`, `<i data-lucide="rotate-ccw" class="w-4 h-4"></i>`, `<i data-lucide="check" class="w-4 h-4"></i>`, `<i data-lucide="trash-2" class="w-4 h-4"></i>`

## 2. ZERO SHORTCUTS — 100% FEATURE COMPLETION (MANDATORY)
Before writing code, extract EVERY SINGLE REQUIREMENT from the user prompt:
- If configurable timer modes are requested (e.g. 25m, 5m, 15m), YOU MUST BUILD ALL MODES with interactive pill buttons.
- If a progress ring is requested, YOU MUST BUILD an animated SVG circle ring (`stroke-dasharray`, `stroke-dashoffset`).
- If an audio alert is requested, YOU MUST BUILD a Web Audio API synthesizer (`new (window.AudioContext || window.webkitAudioContext)()`) that plays a clean chime with zero external audio files. NEVER write `new Audio('alert.mp3')` with a missing file.
- If task checklist / persistence is requested, YOU MUST BUILD complete add/toggle/delete logic backed by `localStorage`.
- NEVER omit requested features. If the user asked for 4 features, build ALL 4 features completely!

## 3. COMPONENT DOM INTEGRITY & CO-DESIGN (CRITICAL)
- NEVER leave empty placeholder shells in HTML (e.g. `<div id="task-checklist"></div>`).
  Every form, input, button, and list element MUST be written explicitly in `index.html`.
  JavaScript should NEVER query or attach listeners to elements that do not exist in HTML!
- Circular Progress Rings: Always place the timer numbers centered INSIDE the ring using absolute positioning:
  Wrap in `.relative w-72 h-72 flex items-center justify-center` with SVG `-rotate-90` and `.absolute inset-0 flex flex-col items-center justify-center`.
  NEVER place timer text below the circle or use harsh primary colors like `#ff0000`. Use an SVG `<linearGradient>` with indigo/purple stops.
- Multi-Panel Layouts: Use structured 2-column dashboard layouts (`max-w-5xl mx-auto grid lg:grid-cols-12 gap-6`) so timers, controls, and tasks sit side-by-side gracefully.

## 4. LUXURY CUSTOM CSS in style.css
`style.css` provides the luxury layer:
- Ambient floating radial glow backgrounds with blur(100px) and fixed positioning behind glass cards.
- Circular SVG progress ring animations with `transition: stroke-dashoffset 0.8s cubic-bezier(0.16, 1, 0.3, 1);`
- Tabular figures for digital numbers: `font-variant-numeric: tabular-nums;`
- Custom sleek scrollbars and checkbox transitions.

## 5. CRASH-PROOF JAVASCRIPT in script.js
- Wrap in `document.addEventListener('DOMContentLoaded', () => { ... })`.
- Declare all state variables (`remainingSeconds`, `timerInterval`, `tasks`) in outer module scope so all functions access shared state.
- Safely query every DOM element before use. Zero undeclared variables. Zero missing files.

╔══════════════════════════════════════════════╗
║   EDITING EXISTING FILES — MANDATORY RULES   ║
╚══════════════════════════════════════════════╝
When the user asks you to MODIFY, UPDATE, FIX, or IMPROVE an existing file, follow this EXACT workflow:

  STEP 1 → `read_file`  — Read the file first to see exact current content + line numbers.
  STEP 2 → `edit_file` or `patch_file` — Surgically edit ONLY the changed lines.
  NEVER  → `write_file` on an existing file — This destroys the whole file.

Think like Antigravity / Cursor:
  ✓ read_file → see lines 42-58 → patch_file(start_line=42, end_line=58, new_content=...)
  ✓ read_file → find the CSS rule → edit_file(old_str="...", new_str="...")
  ✗ NEVER overwrite a whole file just to change 3 lines.
  ✗ NEVER guess what's in a file without reading it first.

╔══════════════════════════════════════════════╗
║            DEBUGGING METHODOLOGY             ║
╚══════════════════════════════════════════════╝
When the user reports a bug or asks you to fix something:
  1. `grep` or `search_code` → locate the problem area
  2. `read_file` with precise start_line/end_line → see exact context
  3. Identify ROOT CAUSE before writing any fix
  4. `edit_file` or `patch_file` → surgical fix
  5. `run_command` → verify with tests or lint if applicable
  6. Report what you changed and why

For Python errors: run `python -c "import ast; ast.parse(open('file.py').read())"` to syntax-check.
For JavaScript: run `node --check file.js` to validate.

╔══════════════════════════════════════════════╗
║              AVAILABLE TOOLS                 ║
╚══════════════════════════════════════════════╝

1. `write_file` — Create or overwrite a file. Use for NEW files ONLY.
   NEVER use placeholder text like "...full content...". Always supply 100% complete, real code.
   ```tool
   {{"tool": "write_file", "args": {{"path": "index.html", "content": "<!DOCTYPE html>\\n<html lang=\\"en\\">\\n<head>\\n  <meta charset=\\"UTF-8\\">\\n  <title>App</title>\\n</head>\\n<body>\\n  <h1>Welcome</h1>\\n</body>\\n</html>"}}}}
   ```

2. `read_file` — Read a file with line numbers. ALWAYS call this before editing.
   ```tool
   {{"tool": "read_file", "args": {{"path": "style.css", "start_line": 1, "end_line": 80}}}}
   ```

3. `edit_file` — Replace an exact block of text. Include a few surrounding context lines.
   ```tool
   {{"tool": "edit_file", "args": {{"path": "style.css", "old_str": "  color: red;\\n  font-size: 1rem;", "new_str": "  color: hsl(260, 80%, 65%);\\n  font-size: 1.1rem;"}}}}
   ```

4. `patch_file` — Replace a line range (use line numbers from read_file). Safer for large blocks.
   ```tool
   {{"tool": "patch_file", "args": {{"path": "script.js", "start_line": 42, "end_line": 58, "new_content": "  const btn = document.querySelector('.cta-btn');\\n  btn.addEventListener('click', () => alert('Ready!'));"}}}}
   ```

5. `append_file` — Append content to the end of a file.
   ```tool
   {{"tool": "append_file", "args": {{"path": "style.css", "content": "\\n/* New section */\\n.new-class {{ color: red; }}"}}}}
   ```

6. `delete_file` — Permanently delete a file from the workspace.
   ```tool
   {{"tool": "delete_file", "args": {{"path": "old_file.js"}}}}
   ```

7. `rename_file` — Rename or move a file within the workspace.
   ```tool
   {{"tool": "rename_file", "args": {{"path": "old_name.js", "new_name": "new_name.js"}}}}
   ```

8. `create_dir` — Create a folder (and any parent folders) in the workspace.
   ```tool
   {{"tool": "create_dir", "args": {{"path": "src/components"}}}}
   ```

9. `list_dir` — List files and subfolders in the workspace.
   ```tool
   {{"tool": "list_dir", "args": {{"path": "."}}}}
   ```

10. `get_file_info` — Get metadata about a file (size, line count, last modified).
    ```tool
    {{"tool": "get_file_info", "args": {{"path": "main.py"}}}}
    ```

11. `run_command` — Run a PowerShell command in the workspace directory.
    ```tool
    {{"tool": "run_command", "args": {{"command": "npm install"}}}}
    ```

12. `search_code` — Simple text search across all workspace files.
    ```tool
    {{"tool": "search_code", "args": {{"query": "background-color"}}}}
    ```

13. `grep` — Regex-capable search with file-type filtering and case control.
    ```tool
    {{"tool": "grep", "args": {{"pattern": "def\\s+\\w+\\(self", "path": ".", "file_glob": "*.py", "case_sensitive": true}}}}
    ```

14. `open_browser` — Open a workspace file in the user's default browser (instant preview).
    ```tool
    {{"tool": "open_browser", "args": {{"path": "index.html"}}}}
    ```

15. `scaffold_project` — Create a complete project skeleton instantly.
    ```tool
    {{"tool": "scaffold_project", "args": {{"type": "html", "name": "my-site"}}}}
    ```
    Types: "html" | "react" | "node" | "python-flask"

16. `check_syntax` — Validate syntax for Python, JavaScript, HTML, CSS, or JSON without executing.
    ```tool
    {{"tool": "check_syntax", "args": {{"path": "script.js"}}}}
    ```

17. `get_file_outline` — Extract code structure outline (classes, functions, IDs) with line numbers.
    ```tool
    {{"tool": "get_file_outline", "args": {{"path": "main.py"}}}}
    ```

18. `undo_last_edit` — Roll back the most recent file change made in this session.
    ```tool
    {{"tool": "undo_last_edit", "args": {{}}}}
    ```

╔══════════════════════════════════════════════╗
║           AGENT EXECUTION RULES              ║
╚══════════════════════════════════════════════╝
- Operate fully autonomously — plan, execute, and iterate without asking for permission.

- For a NEW WEBSITE / NEW FILES:
  1. list_dir → check what exists
  2. write_file → index.html, style.css, script.js (each as its own tool call)
  3. open_browser → instant preview

- For MODIFYING EXISTING FILES (updates, fixes, improvements):
  1. read_file → see exact current content + line numbers
  2. patch_file OR edit_file → surgical change only what's needed
  3. open_browser → show the updated result

- For DEBUGGING:
  1. grep OR search_code → locate problem
  2. read_file → understand context
  3. edit_file → surgical fix
  4. run_command → verify

- For FILE REORGANIZATION:
  1. list_dir → see structure
  2. create_dir → make new folders as needed
  3. rename_file → move files
  4. delete_file → clean up old/duplicate files

- Wrap every tool call in a ```tool ... ``` fence block — that is what triggers execution.
- After each tool result, decide the next step. Keep going until fully done.
- End with a clean markdown summary of what changed and which files were edited.
- NEVER say "I'll write code below". Just do it. Into the workspace. Right now.
- NEVER rewrite an entire file to fix 3 lines. Read → find → patch.
"""

# =============================================================================
# Web-specific scaffold templates
# =============================================================================
HTML_SCAFFOLD = {
    "index.html": """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{name}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="style.css" />
</head>
<body>
  <header class="header">
    <nav class="nav">
      <div class="nav__logo">{name}</div>
      <ul class="nav__links">
        <li><a href="#features">Features</a></li>
        <li><a href="#about">About</a></li>
        <li><a href="#contact">Contact</a></li>
      </ul>
      <button class="btn btn--primary nav__cta">Get Started</button>
      <button class="nav__toggle" aria-label="Menu">&#9776;</button>
    </nav>
  </header>

  <main>
    <section class="hero">
      <div class="hero__content">
        <span class="hero__tag">Welcome to {name}</span>
        <h1 class="hero__title">Build Something <span class="gradient-text">Extraordinary</span></h1>
        <p class="hero__desc">A modern platform built for the next generation of creators, developers, and dreamers.</p>
        <div class="hero__actions">
          <button class="btn btn--primary btn--lg">Get Started Free</button>
          <button class="btn btn--ghost btn--lg">Learn More</button>
        </div>
      </div>
      <div class="hero__visual">
        <div class="hero__glow"></div>
      </div>
    </section>

    <section class="features" id="features">
      <div class="container">
        <h2 class="section__title">Why Choose <span class="gradient-text">{name}</span></h2>
        <p class="section__sub">Everything you need to succeed, in one place.</p>
        <div class="features__grid">
          <div class="card feature-card">
            <div class="feature-card__icon">&#9889;</div>
            <h3>Lightning Fast</h3>
            <p>Optimised for performance from the ground up. Zero compromise on speed.</p>
          </div>
          <div class="card feature-card">
            <div class="feature-card__icon">&#128274;</div>
            <h3>Secure by Default</h3>
            <p>Enterprise-grade security built in, so you can focus on building.</p>
          </div>
          <div class="card feature-card">
            <div class="feature-card__icon">&#127775;</div>
            <h3>Beautiful Design</h3>
            <p>Crafted with pixel-perfect attention to detail and smooth animations.</p>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer class="footer">
    <div class="container">
      <p>&copy; 2025 {name}. All rights reserved.</p>
    </div>
  </footer>

  <script src="script.js"></script>
</body>
</html>
""",
    "style.css": """\
/* ─── Variables ─────────────────────────────── */
:root {
  --bg:         #080818;
  --bg-2:       #0e0e2a;
  --surface:    rgba(255,255,255,0.05);
  --border:     rgba(255,255,255,0.08);
  --text:       #e2e8f0;
  --text-muted: #94a3b8;
  --accent:     hsl(260, 80%, 65%);
  --accent-2:   hsl(200, 90%, 60%);
  --radius:     16px;
  --transition: 0.3s ease;
  --font-head:  'Space Grotesk', sans-serif;
  --font-body:  'Inter', sans-serif;
  --shadow:     0 8px 32px rgba(0,0,0,0.5);
  --glow:       0 0 40px rgba(139, 92, 246, 0.35);
}

/* ─── Reset ─────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body { background: var(--bg); color: var(--text); font-family: var(--font-body); line-height: 1.7; overflow-x: hidden; }

/* ─── Gradient text ──────────────────────────── */
.gradient-text {
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* ─── Container ─────────────────────────────── */
.container { max-width: 1180px; margin: 0 auto; padding: 0 24px; }

/* ─── Buttons ───────────────────────────────── */
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 12px 28px; border-radius: 999px; font-family: var(--font-body); font-weight: 600; font-size: 0.95rem; cursor: pointer; border: none; transition: all var(--transition); text-decoration: none; }
.btn--primary { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #fff; box-shadow: 0 4px 24px rgba(139,92,246,0.4); }
.btn--primary:hover { transform: translateY(-2px); box-shadow: 0 8px 32px rgba(139,92,246,0.6); }
.btn--ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); backdrop-filter: blur(12px); }
.btn--ghost:hover { background: rgba(255,255,255,0.1); transform: translateY(-2px); }
.btn--lg { padding: 15px 36px; font-size: 1.05rem; }

/* ─── Nav ───────────────────────────────────── */
.header { position: fixed; top: 0; left: 0; right: 0; z-index: 100; padding: 16px 0; background: rgba(8,8,24,0.7); backdrop-filter: blur(20px); border-bottom: 1px solid var(--border); }
.nav { max-width: 1180px; margin: 0 auto; padding: 0 24px; display: flex; align-items: center; gap: 40px; }
.nav__logo { font-family: var(--font-head); font-weight: 700; font-size: 1.3rem; background: linear-gradient(135deg, var(--accent), var(--accent-2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; margin-right: auto; }
.nav__links { display: flex; gap: 32px; list-style: none; }
.nav__links a { color: var(--text-muted); text-decoration: none; font-weight: 500; transition: color var(--transition); }
.nav__links a:hover { color: var(--text); }
.nav__toggle { display: none; background: none; border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 8px 12px; cursor: pointer; font-size: 1.1rem; }

/* ─── Hero ──────────────────────────────────── */
.hero { min-height: 100vh; display: flex; align-items: center; padding: 120px 24px 80px; max-width: 1180px; margin: 0 auto; position: relative; }
.hero__content { flex: 1; max-width: 640px; }
.hero__tag { display: inline-block; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 6px 16px; font-size: 0.85rem; color: var(--accent); font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 24px; }
.hero__title { font-family: var(--font-head); font-size: clamp(2.5rem, 6vw, 4.5rem); font-weight: 700; line-height: 1.1; letter-spacing: -0.03em; margin-bottom: 24px; }
.hero__desc { color: var(--text-muted); font-size: clamp(1rem, 2vw, 1.2rem); max-width: 520px; margin-bottom: 40px; line-height: 1.8; }
.hero__actions { display: flex; gap: 16px; flex-wrap: wrap; }
.hero__visual { flex: 1; display: flex; justify-content: center; align-items: center; }
.hero__glow { width: 360px; height: 360px; background: radial-gradient(circle, rgba(139,92,246,0.35) 0%, transparent 70%); border-radius: 50%; animation: pulse-glow 4s ease-in-out infinite; }

/* ─── Features ──────────────────────────────── */
.features { padding: 100px 0; }
.section__title { font-family: var(--font-head); font-size: clamp(2rem, 4vw, 3rem); font-weight: 700; text-align: center; margin-bottom: 16px; letter-spacing: -0.02em; }
.section__sub { color: var(--text-muted); text-align: center; font-size: 1.1rem; margin-bottom: 64px; }
.features__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; }

/* ─── Card ──────────────────────────────────── */
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 32px; backdrop-filter: blur(12px); transition: all var(--transition); }
.card:hover { transform: translateY(-6px); box-shadow: var(--glow); border-color: rgba(139,92,246,0.3); }

/* ─── Feature Card ──────────────────────────── */
.feature-card__icon { font-size: 2rem; margin-bottom: 20px; }
.feature-card h3 { font-family: var(--font-head); font-size: 1.25rem; font-weight: 600; margin-bottom: 12px; }
.feature-card p { color: var(--text-muted); line-height: 1.7; }

/* ─── Footer ────────────────────────────────── */
.footer { border-top: 1px solid var(--border); padding: 40px 0; text-align: center; color: var(--text-muted); }

/* ─── Animations ────────────────────────────── */
@keyframes pulse-glow { 0%, 100% { opacity: 0.7; transform: scale(1); } 50% { opacity: 1; transform: scale(1.1); } }
@keyframes fade-up { from { opacity: 0; transform: translateY(30px); } to { opacity: 1; transform: translateY(0); } }
.fade-up { animation: fade-up 0.7s ease forwards; opacity: 0; }

/* ─── Responsive ────────────────────────────── */
@media (max-width: 768px) {
  .hero { flex-direction: column; text-align: center; }
  .hero__actions { justify-content: center; }
  .hero__visual { display: none; }
  .nav__links, .nav__cta { display: none; }
  .nav__toggle { display: block; }
}
""",
    "script.js": """\
// ─── Smooth scroll for nav links
document.querySelectorAll('a[href^="#"]').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const target = document.querySelector(link.getAttribute('href'));
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
});

// ─── Mobile nav toggle
const toggle = document.querySelector('.nav__toggle');
const navLinks = document.querySelector('.nav__links');
const navCta = document.querySelector('.nav__cta');
if (toggle) {
  toggle.addEventListener('click', () => {
    const open = navLinks.style.display === 'flex';
    navLinks.style.display = open ? 'none' : 'flex';
    navLinks.style.flexDirection = 'column';
    navLinks.style.position = 'absolute';
    navLinks.style.top = '70px';
    navLinks.style.right = '24px';
    navLinks.style.background = 'rgba(14,14,42,0.98)';
    navLinks.style.border = '1px solid rgba(255,255,255,0.08)';
    navLinks.style.borderRadius = '12px';
    navLinks.style.padding = '16px';
  });
}

// ─── Scroll-based fade-up animations
const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('fade-up');
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.15 });

document.querySelectorAll('.feature-card, .card').forEach(el => observer.observe(el));

// ─── Header shadow on scroll
window.addEventListener('scroll', () => {
  const header = document.querySelector('.header');
  if (window.scrollY > 50) {
    header.style.boxShadow = '0 4px 40px rgba(0,0,0,0.6)';
  } else {
    header.style.boxShadow = 'none';
  }
});

// ─── Animated hero glow follows cursor
document.addEventListener('mousemove', e => {
  const glow = document.querySelector('.hero__glow');
  if (!glow) return;
  const x = (e.clientX / window.innerWidth - 0.5) * 30;
  const y = (e.clientY / window.innerHeight - 0.5) * 30;
  glow.style.transform = `translate(${{x}}px, ${{y}}px)`;
});
"""
}


def get_scaffold_files(project_type: str, name: str) -> Dict[str, str]:
    """Return a dict of {relative_path: content} for the given scaffold type."""
    safe_name = name.strip() or "my-project"

    if project_type == "html":
        return {
            k: v.replace("{name}", safe_name)
            for k, v in HTML_SCAFFOLD.items()
        }

    if project_type == "python-flask":
        return {
            "app.py": f"""\
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)
""",
            "templates/index.html": f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{safe_name}</title></head>
<body><h1>{safe_name}</h1></body>
</html>
""",
            "requirements.txt": "flask>=3.0\n",
        }

    if project_type == "node":
        return {
            "server.js": f"""\
const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static('public'));

app.get('/api/health', (req, res) => res.json({{ status: 'ok', name: '{safe_name}' }}));

app.listen(PORT, () => console.log(`{safe_name} running on http://localhost:${{PORT}}`));
""",
            "package.json": json.dumps({
                "name": safe_name.lower().replace(" ", "-"),
                "version": "1.0.0",
                "main": "server.js",
                "scripts": {"start": "node server.js", "dev": "nodemon server.js"},
                "dependencies": {"express": "^4.18.2"}
            }, indent=2) + "\n",
            "public/index.html": f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{safe_name}</title></head>
<body><h1>{safe_name}</h1></body>
</html>
""",
        }

    # react / vite — return just a note; Luna will run npm commands
    return {
        "README.md": f"# {safe_name}\n\nScaffold with: `npm create vite@latest . -- --template react`\n"
    }


# ─────────────────────────────────────────────────────────────────────────────
# File path heuristic helpers
# ─────────────────────────────────────────────────────────────────────────────

# Sorted most-specific first so the first match wins
_WEB_EXTENSION_MAP = {
    "html": "html", "htm": "html",
    "css": "css", "scss": "scss", "sass": "sass", "less": "less",
    "javascript": "js", "js": "js", "jsx": "jsx",
    "typescript": "ts", "ts": "ts", "tsx": "tsx",
    "python": "py", "py": "py",
    "json": "json", "yaml": "yaml", "yml": "yml",
    "bash": "sh", "shell": "sh", "sh": "sh",
    "go": "go", "rust": "rs", "cpp": "cpp", "c": "c",
    "java": "java", "kotlin": "kt", "swift": "swift",
    "sql": "sql", "graphql": "graphql",
    "markdown": "md", "md": "md",
    "xml": "xml", "svg": "svg",
}

# Smarter default filename per language tag
_WEB_DEFAULT_FILE = {
    "html": "index.html",
    "css": "style.css",
    "scss": "style.scss",
    "js": "script.js",
    "jsx": "App.jsx",
    "ts": "app.ts",
    "tsx": "App.tsx",
    "py": "main.py",
    "json": "package.json",
    "sh": "setup.sh",
}


def detect_file_from_code_block(code: str, lang_tag: str = "", preceding_text: str = "") -> Optional[str]:
    """
    Detect destination file path from code block syntax or surrounding context.
    Returns a relative path string or None.
    """
    # Strategy 1: lang tag contains path hint e.g. ```html:index.html
    if ":" in lang_tag:
        parts = lang_tag.split(":", 1)
        if len(parts) > 1 and "." in parts[1]:
            return parts[1].strip()

    # Strategy 2: shebang or comment in first 3 lines: # filename: style.css
    first_lines = code.strip().splitlines()[:3]
    for line in first_lines:
        line_clean = line.strip()
        m = re.search(
            r'(?:#|//|/\*|<!--|;)\s*(?:filename:?\s*|file:?\s*)?'
            r'([a-zA-Z0-9_\-\./\\]+\.(?:html?|css|s?css|jsx?|tsx?|py|json|ya?ml|sh|go|rs|cpp?|h|java|kt|sql|md|svg|xml))',
            line_clean, re.IGNORECASE
        )
        if m:
            candidate = m.group(1).strip()
            if candidate and not candidate.startswith("http"):
                return candidate.replace("\\", "/")

    # Strategy 3: filename in preceding prose (with backticks or plain text) e.g. "create `style.css`" or "content of style.css"
    if preceding_text:
        tail = preceding_text[-400:]
        matches = re.findall(
            r'(?:[`"\'\s\(]|^)([a-zA-Z0-9_\-\./\\]+\.(?:html?|css|s?css|jsx?|tsx?|py|json|ya?ml|sh|go|rs|cpp?|h|java|kt|sql|md))[`"\'\s\.,;:!?]?',
            tail
        )
        if matches:
            return matches[-1].replace("\\", "/")

        # Strategy 4: "write/create/save X.ext" in prose
        matches2 = re.findall(
            r'(?:write|create|save|generate|build|make|add)\s+(?:the\s+)?(?:file\s+)?'
            r'([a-zA-Z0-9_\-\./\\]+\.(?:html?|css|s?css|jsx?|tsx?|py|json|ya?ml|sh|go|rs|cpp?|h|java|kt|sql|md))',
            tail, re.IGNORECASE
        )
        if matches2:
            return matches2[-1].replace("\\", "/")

    # Strategy 5: smart default by lang tag
    ext = _WEB_EXTENSION_MAP.get(lang_tag.lower().split(":")[0], None)
    if ext:
        return _WEB_DEFAULT_FILE.get(ext, f"main.{ext}")

    return None


def extract_tool_calls(text: str, workspace: Optional[WorkspaceManager] = None) -> List[Tuple[str, Dict[str, Any], str]]:
    """
    Extract tool calls from text.
    Returns list of (tool_name, args_dict, matched_raw_block).
    Supports:
      1. ```tool / ```json blocks
      2. Raw JSON objects {"tool": ...}
      3. Claude / Aider style <<<<<<< SEARCH ... ======= ... >>>>>>> blocks
      4. Auto-detected markdown code blocks (safeguarded against destroying existing files)
    """
    results = []

    # Strategy 1: ```tool ... ``` or ```json ... ``` blocks
    tool_blocks = re.findall(r'```(?:tool|json)\s*([\s\S]*?)```', text, re.IGNORECASE)
    for block in tool_blocks:
        block_clean = block.strip()
        try:
            data = json.loads(block_clean)
            if isinstance(data, dict):
                tool_name = data.get("tool") or data.get("name") or data.get("action")
                args = (
                    data.get("args") or data.get("arguments") or
                    data.get("parameters") or data.get("action_input") or {}
                )
                if tool_name and isinstance(args, dict):
                    results.append((tool_name, args, block))
                    continue
        except Exception:
            pass

    # Strategy 2: Raw JSON object with "tool"/"name" key
    if not results:
        raw_matches = re.findall(
            r'(\{\s*"(?:tool|name)"\s*:\s*"[^"]+"\s*,\s*"(?:args|arguments)"\s*:\s*\{[\s\S]*?\}\s*\})',
            text
        )
        for raw in raw_matches:
            try:
                data = json.loads(raw)
                tool_name = data.get("tool") or data.get("name")
                args = data.get("args") or data.get("arguments") or {}
                if tool_name and isinstance(args, dict):
                    results.append((tool_name, args, raw))
            except Exception:
                pass

    # Strategy 2.5: Search / Replace diff blocks (Claude / Aider style)
    if not results:
        sr_matches = list(re.finditer(
            r'<<<<<<< SEARCH\s*\n([\s\S]*?)\n=======\s*\n([\s\S]*?)\n>>>>>>>',
            text
        ))
        for sr in sr_matches:
            old_part = sr.group(1)
            new_part = sr.group(2)
            preceding = text[:sr.start()]
            fn_match = re.search(
                r'(?:in|for|to|file:?|filename:?|update|edit|patch)\s*[`"]?([a-zA-Z0-9_\-\./\\]+\.[a-zA-Z0-9]+)[`"]?',
                preceding[-300:], re.IGNORECASE
            )
            if fn_match:
                target_p = fn_match.group(1).replace("\\", "/")
                # Clean line numbers from replacement if present
                clean_new = re.sub(r'(?m)^\s*\d+:\s?', '', new_part)
                results.append(("edit_file", {"path": target_p, "old_str": old_part, "new_str": clean_new}, sr.group(0)))

    # Strategy 3: Auto-detect code blocks → write or surgical edit to workspace
    if not results:
        code_blocks = list(re.finditer(r'(?:^|\n)```([a-zA-Z0-9_\-:\.]+)?\n([\s\S]*?)```', text))
        # Handle unclosed code block at end of text (e.g. streaming or cutoff)
        if not code_blocks:
            unclosed = re.search(r'(?:^|\n)```([a-zA-Z0-9_\-:\.]+)?\n([\s\S]+)$', text)
            if unclosed:
                code_blocks = [unclosed]

        for match in code_blocks:
            lang_tag = match.group(1) or ""
            code_content = match.group(2) or ""
            if not code_content.strip():
                continue
            skip_langs = {"tool", "bash", "sh", "cmd", "powershell", "ps1", "console", "terminal", "text", ""}
            if lang_tag.lower() in skip_langs:
                continue
            preceding = text[:match.start()]
            candidate_file = detect_file_from_code_block(code_content, lang_tag, preceding)
            if not candidate_file:
                continue

            # Automatically strip any accidental line numbers like "240: " from code lines
            clean_code = re.sub(r'(?m)^\s*\d+:\s?', '', code_content)

            # Safe-guard existing files: if candidate exists, verify whether this is a snippet or append
            if workspace is not None:
                target_path = workspace.resolve_path(candidate_file)
                if target_path.exists() and target_path.is_file():
                    try:
                        curr_content = target_path.read_text(encoding="utf-8", errors="replace")
                        curr_lines   = curr_content.splitlines()
                        code_lines   = clean_code.splitlines()

                        # Check if prose indicates appending
                        is_append = bool(re.search(r'\b(append|additional|add|extend|more)\b', preceding[-300:], re.IGNORECASE))
                        if is_append:
                            results.append(("append_file", {"path": candidate_file, "content": clean_code}, match.group(0)))
                            continue

                        # HTML snippet check: if missing <html> and <!DOCTYPE, it's a snippet
                        is_html = candidate_file.endswith((".html", ".htm"))
                        is_snippet = False
                        if is_html and "<html" not in clean_code.lower() and "<!doctype" not in clean_code.lower():
                            is_snippet = True
                        elif len(code_lines) < 0.6 * len(curr_lines) and len(curr_lines) > 20:
                            is_snippet = True

                        if is_snippet:
                            first_line = code_lines[0].strip() if code_lines else ""
                            if first_line and first_line in curr_content:
                                results.append(("edit_file", {
                                    "path": candidate_file,
                                    "old_str": first_line,
                                    "new_str": clean_code
                                }, match.group(0)))
                                continue
                            elif candidate_file.endswith((".css", ".scss", ".js", ".ts")):
                                results.append(("append_file", {"path": candidate_file, "content": clean_code}, match.group(0)))
                                continue
                    except Exception:
                        pass

            results.append(("write_file", {"path": candidate_file, "content": clean_code}, match.group(0)))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Agent Thread
# ─────────────────────────────────────────────────────────────────────────────

class AgentThread(QThread):
    """Autonomous agent execution thread for Luna with tool calling loop."""

    stream_chunk       = pyqtSignal(str)
    tool_started       = pyqtSignal(str, dict, str)           # (tool_name, args, call_id)
    tool_needs_approval = pyqtSignal(str, dict, str)          # (tool_name, args, call_id)
    tool_finished      = pyqtSignal(str, dict, str, bool, str, dict)  # (tool_name, args, output, success, call_id, meta)
    agent_finished     = pyqtSignal(str)                      # (final_response)
    agent_status       = pyqtSignal(str)                      # status message
    error              = pyqtSignal(str)

    def __init__(
        self,
        messages: List[Any],
        workspace: WorkspaceManager,
        model: str = "luna-1.1",
        temperature: float = 0.2,
        auto_run: bool = True,
        max_steps: int = 20,
        parent=None
    ):
        super().__init__(parent)
        self.messages    = list(messages)
        self.workspace   = workspace
        self.model       = model
        self.temperature = temperature
        self.auto_run    = auto_run
        self.max_steps   = max_steps

        self._cancelled          = False
        self._mutex              = QMutex()
        self._wait_cond          = QWaitCondition()
        self._approval_result: Optional[bool] = None
        self._current_call_id: Optional[str]  = None

    def cancel(self):
        self._cancelled = True
        self._mutex.lock()
        self._approval_result = False
        self._wait_cond.wakeAll()
        self._mutex.unlock()

    def approve_tool(self, call_id: str):
        self._mutex.lock()
        if self._current_call_id == call_id:
            self._approval_result = True
            self._wait_cond.wakeAll()
        self._mutex.unlock()

    def reject_tool(self, call_id: str):
        self._mutex.lock()
        if self._current_call_id == call_id:
            self._approval_result = False
            self._wait_cond.wakeAll()
        self._mutex.unlock()

    def run(self):
        try:
            llm = ChatOllama(model=self.model, temperature=self.temperature)

            # Discover current workspace files to ground Luna in what already exists
            entries = self.workspace.list_dir(".").get("entries", [])
            if entries:
                file_lines = []
                for e in entries:
                    kind = "📁" if e.get("type") == "dir" else "📄"
                    sz = f" ({e.get('size', 0):,} bytes)" if e.get("type") == "file" else ""
                    file_lines.append(f"  {kind} {e.get('name')}{sz}")
                ws_files_str = "\n".join(file_lines)
            else:
                ws_files_str = "  (Workspace is empty — create files as needed)"

            sys_prompt = (
                LUNA_AGENT_SYSTEM_PROMPT
                .replace("{workspace_path}", str(self.workspace.root))
                .replace("{workspace_files}", ws_files_str)
                .replace("{{", "{")
                .replace("}}", "}")
            )
            if not self.messages or not isinstance(self.messages[0], SystemMessage):
                self.messages.insert(0, SystemMessage(content=sys_prompt))
            else:
                self.messages[0] = SystemMessage(content=sys_prompt)

            accumulated_full_text = ""

            for step in range(1, self.max_steps + 1):
                if self._cancelled:
                    break

                self.agent_status.emit(f"Luna is thinking… (step {step}/{self.max_steps})")

                step_response = ""
                for chunk in llm.stream(self.messages):
                    if self._cancelled:
                        break
                    if hasattr(chunk, "content"):
                        c = chunk.content
                        step_response += c
                        self.stream_chunk.emit(c)

                if self._cancelled:
                    break

                tool_calls = extract_tool_calls(step_response, workspace=self.workspace)

                if not tool_calls:
                    # No tool call → final answer
                    accumulated_full_text += ("\n\n" if accumulated_full_text else "") + step_response
                    self.messages.append(AIMessage(content=step_response))
                    self.agent_finished.emit(accumulated_full_text.strip())
                    return

                # Record AI message and execute tool calls
                self.messages.append(AIMessage(content=step_response))

                for tool_name, tool_args, raw_block in tool_calls:
                    if self._cancelled:
                        break

                    call_id = str(uuid.uuid4())[:8]
                    self._current_call_id = call_id

                    # Approval gate for destructive ops when auto_run is OFF
                    needs_approval = (not self.auto_run) and (
                        tool_name in (
                            "run_command", "write_file", "edit_file", "patch_file",
                            "append_file", "delete_file", "rename_file", "scaffold_project",
                            "undo_last_edit"
                        )
                    )
                    if needs_approval:
                        self.agent_status.emit(f"Waiting for approval: {tool_name}…")
                        self.tool_needs_approval.emit(tool_name, tool_args, call_id)

                        self._mutex.lock()
                        self._approval_result = None
                        while self._approval_result is None and not self._cancelled:
                            self._wait_cond.wait(self._mutex, 100)
                        approved = self._approval_result
                        self._mutex.unlock()

                        if self._cancelled or not approved:
                            result_str = f"Tool '{tool_name}' was skipped by user."
                            self.tool_finished.emit(tool_name, tool_args, result_str, False, call_id, {})
                            self.messages.append(HumanMessage(content=f"[TOOL RESULT: {tool_name}]\n{result_str}"))
                            continue

                    self.tool_started.emit(tool_name, tool_args, call_id)
                    self.agent_status.emit(f"Executing {tool_name}…")
                    output_text, success, extra_meta = self._execute_tool(tool_name, tool_args)
                    self.tool_finished.emit(tool_name, tool_args, output_text, success, call_id, extra_meta)

                    feedback = (
                        f"[TOOL RESULT: {tool_name}]\n"
                        f"{output_text}\n"
                        f"Analyze this result and continue with the next step, or summarize if the task is complete."
                    )
                    self.messages.append(HumanMessage(content=feedback))

            if self._cancelled:
                self.agent_status.emit("Agent stopped.")
                self.agent_finished.emit(accumulated_full_text + "\n\n*(Stopped by user)*")
            else:
                self.agent_finished.emit(accumulated_full_text or "Task completed.")

        except Exception as exc:
            self.error.emit(str(exc))

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Tuple[str, bool, Dict[str, Any]]:
        """Execute a tool and return (output_string, success_bool, extra_meta_dict)."""
        try:
            if name == "list_dir":
                p = args.get("path", ".")
                res = self.workspace.list_dir(p)
                if "error" in res:
                    return res["error"], False, {}
                entries = res.get("entries", [])
                formatted = [f"  {'📁' if e['type']=='dir' else '📄'} {e['name']}" for e in entries]
                return f"Directory '{p}':\n" + "\n".join(formatted), True, {}

            elif name == "read_file":
                p   = args.get("path", "")
                s   = int(args.get("start_line", 1))
                e   = args.get("end_line")
                e   = int(e) if e is not None else None
                res = self.workspace.read_file(p, s, e)
                if "error" in res:
                    return res["error"], False, {}
                return (
                    f"File: {res['path']} "
                    f"(lines {res['start_line']}–{res['end_line']} of {res['total_lines']}):\n"
                    f"[NOTE: Line numbers '1:', '240:' below are for reference only. Do not copy line numbers into code.]\n"
                    f"{res['content']}"
                ), True, {}

            elif name == "write_file":
                p       = args.get("path", "")
                content = args.get("content", "")
                # Guard against placeholder text
                clean = content.strip().lower()
                if clean in ("...full content...", "...code here...", "...", "/* code */", "<!-- code -->") or clean == "...full content...":
                    return "Error: You passed placeholder text ('...full content...'). Placeholders are forbidden. You must provide the COMPLETE, REAL code for this file.", False, {}

                # Automatically strip accidental leading line numbers like "240: "
                content = re.sub(r'(?m)^\s*\d+:\s?', '', content)

                res = self.workspace.write_file(p, content)
                if not res.get("success", False):
                    return res.get("error", "Write failed"), False, {}
                diff = res.get("diff", "")
                out  = res.get("message", "File written successfully")
                if diff:
                    out += f"\n\nDiff preview:\n{diff[:800]}"
                return out, True, {
                    "snapshot_id": res.get("snapshot_id"),
                    "diff": diff,
                    "path": res.get("path"),
                }

            elif name == "edit_file":
                p       = args.get("path", "")
                old_str = args.get("old_str", "")
                new_str = args.get("new_str", "")
                # Strip accidental line numbers from new_str
                new_str = re.sub(r'(?m)^\s*\d+:\s?', '', new_str)
                res     = self.workspace.edit_file(p, old_str, new_str)
                if not res.get("success", False):
                    return res.get("error", "Edit failed"), False, {}
                diff = res.get("diff", "")
                out  = res.get("message", "File edited successfully")
                if diff:
                    out += f"\n\nDiff:\n{diff[:800]}"
                return out, True, {
                    "snapshot_id": res.get("snapshot_id"),
                    "diff": diff,
                    "path": res.get("path"),
                }

            elif name == "patch_file":
                p          = args.get("path", "")
                start_line = int(args.get("start_line", 1))
                end_line   = int(args.get("end_line", 1))
                new_cnt    = args.get("new_content", args.get("replacement", args.get("content", "")))
                clean_p    = new_cnt.strip().lower()
                if clean_p in ("...replacement lines...", "...full content...", "...code here..."):
                    return "Error: You passed placeholder text. Placeholders are forbidden. You must provide the COMPLETE, REAL replacement code.", False, {}

                # Automatically strip accidental leading line numbers like "240: "
                new_cnt = re.sub(r'(?m)^\s*\d+:\s?', '', new_cnt)

                res = self.workspace.patch_file(p, start_line, end_line, new_cnt)
                if not res.get("success", False):
                    return res.get("error", "Patch failed"), False, {}
                diff = res.get("diff", "")
                out  = res.get("message", "File patched successfully")
                if diff:
                    out += f"\n\nDiff:\n{diff[:800]}"
                return out, True, {
                    "snapshot_id": res.get("snapshot_id"),
                    "diff": diff,
                    "path": res.get("path"),
                }

            elif name == "append_file":
                p       = args.get("path", "")
                content = args.get("content", "")
                clean_p = content.strip().lower()
                if clean_p in ("...replacement lines...", "...full content...", "...code here..."):
                    return "Error: You passed placeholder text. Placeholders are forbidden. You must provide the COMPLETE, REAL code.", False, {}

                # Automatically strip accidental leading line numbers like "240: "
                content = re.sub(r'(?m)^\s*\d+:\s?', '', content)

                res = self.workspace.append_file(p, content)
                if not res.get("success", False):
                    return res.get("error", "Append failed"), False, {}
                diff = res.get("diff", "")
                out  = res.get("message", "Appended to file successfully")
                if diff:
                    out += f"\n\nDiff:\n{diff[:800]}"
                return out, True, {
                    "snapshot_id": res.get("snapshot_id"),
                    "diff": diff,
                    "path": res.get("path"),
                }

            elif name == "run_command":
                cmd = args.get("command", "")
                res = self.workspace.run_command(cmd)
                if "error" in res:
                    return f"Error: {res['error']}", False, {}
                code = res.get("exit_code", 0)
                out  = res.get("output", "")
                return f"Exit code: {code}\n\n{out}", (code == 0), {
                    "command": cmd,
                    "exit_code": code,
                }

            elif name == "search_code":
                q   = args.get("query", "")
                p   = args.get("path", ".")
                res = self.workspace.search_code(q, p)
                if "error" in res:
                    return res["error"], False, {}
                count   = res.get("count", 0)
                matches = res.get("matches", [])
                lines   = [f"  {m['file']}:{m['line']}: {m['text']}" for m in matches[:30]]
                return f"Found {count} matches for '{q}':\n" + "\n".join(lines), True, {}

            elif name == "open_browser":
                p      = args.get("path", "index.html")
                target = self.workspace.resolve_path(p)
                if not target.exists():
                    return f"File not found: {p}", False, {}
                url = target.as_uri()  # file:///...
                webbrowser.open(url)
                return f"Opened in browser: {url}", True, {"url": url, "path": str(target)}

            elif name == "scaffold_project":
                project_type = args.get("type", "html").lower()
                project_name = args.get("name", "my-project")
                files        = get_scaffold_files(project_type, project_name)
                created      = []
                errors       = []
                for rel_path, content in files.items():
                    res = self.workspace.write_file(rel_path, content)
                    if res.get("success"):
                        created.append(rel_path)
                    else:
                        errors.append(f"{rel_path}: {res.get('error','?')}")
                msg = f"Scaffolded '{project_name}' ({project_type}) — created {len(created)} files:\n"
                msg += "\n".join(f"  ✓ {f}" for f in created)
                if errors:
                    msg += "\n\nErrors:\n" + "\n".join(errors)
                return msg, len(errors) == 0, {"created": created, "type": project_type}

            elif name == "delete_file":
                p   = args.get("path", "")
                res = self.workspace.delete_file(p)
                if not res.get("success", False):
                    return res.get("error", "Delete failed"), False, {}
                return res.get("message", f"Deleted {p}"), True, {"path": p}

            elif name == "rename_file":
                p        = args.get("path", "")
                new_name = args.get("new_name", "")
                res = self.workspace.rename_file(p, new_name)
                if not res.get("success", False):
                    return res.get("error", "Rename failed"), False, {}
                return res.get("message", f"Renamed {p}"), True, {"from": p, "to": new_name}

            elif name == "create_dir":
                p   = args.get("path", "")
                res = self.workspace.create_dir(p)
                if not res.get("success", False):
                    return res.get("error", "Create dir failed"), False, {}
                return res.get("message", f"Created dir {p}"), True, {"path": p}

            elif name == "get_file_info":
                p   = args.get("path", "")
                res = self.workspace.get_file_info(p)
                if "error" in res:
                    return res["error"], False, {}
                parts = [f"Path: {res.get('path')}", f"Type: {res.get('type')}"]
                if res.get('type') == 'file':
                    parts.append(f"Size: {res.get('size_bytes', 0):,} bytes")
                    parts.append(f"Lines: {res.get('line_count', 0):,}")
                    parts.append(f"Modified: {res.get('modified')}")
                return "\n".join(parts), True, res

            elif name == "grep":
                pattern        = args.get("pattern", "")
                p              = args.get("path", ".")
                case_sensitive = bool(args.get("case_sensitive", True))
                file_glob      = args.get("file_glob", "*")
                res = self.workspace.grep_files(pattern, p, case_sensitive, file_glob)
                if "error" in res:
                    return res["error"], False, {}
                count   = res.get("count", 0)
                matches = res.get("matches", [])
                lines   = [f"  {m['file']}:{m['line']}: {m['text']}" for m in matches[:40]]
                return f"Grep '{pattern}' — {count} match(es):\n" + "\n".join(lines), True, {}

            elif name == "check_syntax":
                p = args.get("path", "")
                res = self.workspace.check_syntax(p)
                if not res.get("valid", False):
                    err_msg = res.get("error", "Syntax error")
                    line_info = f" (line {res.get('line')})" if res.get('line') else ""
                    return f"Syntax Error in {p}{line_info}:\n{err_msg}", False, res
                return res.get("message", f"Syntax valid for {p}"), True, res

            elif name == "get_file_outline":
                p = args.get("path", "")
                res = self.workspace.get_file_outline(p)
                if "error" in res:
                    return res["error"], False, {}
                outline = res.get("outline", "")
                count = res.get("total_items", 0)
                if not outline:
                    return f"Outline for {p}: {res.get('summary', 'No symbols found')}", True, res
                return f"Outline for {p} ({count} items):\n{outline}", True, res

            elif name == "undo_last_edit":
                res = self.workspace.undo_last_edit()
                if not res.get("success", False):
                    return res.get("error", "Undo failed"), False, {}
                return res.get("message", "Reverted last change"), True, res

            else:
                available = (
                    "list_dir, read_file, write_file, edit_file, patch_file, append_file, "
                    "delete_file, rename_file, create_dir, get_file_info, "
                    "run_command, search_code, grep, check_syntax, get_file_outline, undo_last_edit, "
                    "open_browser, scaffold_project"
                )
                return f"Unknown tool: '{name}'. Available tools: {available}", False, {}

        except Exception as exc:
            return f"Tool execution failed ({name}): {exc}", False, {}
