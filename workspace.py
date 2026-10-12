import os
import subprocess
import json
import uuid
import difflib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

class WorkspaceManager:
    """Manages workspace folder, file operations, and terminal commands."""

    def __init__(self, root_dir: Optional[str] = None):
        self.snapshots: Dict[str, Dict[str, Any]] = {}
        self.snapshot_history: List[str] = []
        if root_dir and Path(root_dir).exists() and Path(root_dir).is_dir():
            self.root = Path(root_dir).resolve()
        else:
            self.root = Path.cwd().resolve()
            self._load_saved_workspace()

    def _get_config_path(self) -> Path:
        config_dir = Path.home() / ".sierra"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "workspace_config.json"

    def _load_saved_workspace(self):
        try:
            cfg = self._get_config_path()
            if cfg.exists():
                data = json.loads(cfg.read_text(encoding="utf-8"))
                saved_root = data.get("active_workspace")
                if saved_root and Path(saved_root).exists() and Path(saved_root).is_dir():
                    self.root = Path(saved_root).resolve()
        except Exception:
            pass

    def save_workspace(self):
        try:
            cfg = self._get_config_path()
            cfg.write_text(json.dumps({"active_workspace": str(self.root)}, indent=2), encoding="utf-8")
        except Exception:
            pass

    def set_root(self, path: str) -> bool:
        p = Path(path).resolve()
        if p.exists() and p.is_dir():
            self.root = p
            self.save_workspace()
            return True
        return False

    def resolve_path(self, rel_path: str) -> Path:
        """Resolve a relative or absolute path within the workspace."""
        p = Path(rel_path)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (self.root / rel_path).resolve()
        return resolved

    def is_safe_path(self, path: Path) -> bool:
        """Prevent accidental path traversal outside workspace."""
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def list_dir(self, path: str = ".", recursive: bool = False, max_depth: int = 2) -> Dict[str, Any]:
        """List files and folders in the workspace, skipping heavy ignore dirs."""
        target = self.resolve_path(path)
        if not target.exists() or not target.is_dir():
            return {"error": f"Directory not found: {path}"}

        ignore_dirs = {
            ".git", "node_modules", "venv", ".venv", "__pycache__",
            ".pytest_cache", ".next", "dist", "build", ".sierra", ".idea", ".vscode"
        }

        results = []
        try:
            if not recursive:
                for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                    if entry.name in ignore_dirs:
                        results.append({"name": entry.name + "/", "type": "dir", "ignored": True})
                        continue
                    results.append({
                        "name": entry.name + ("/" if entry.is_dir() else ""),
                        "type": "dir" if entry.is_dir() else "file",
                        "size": entry.stat().st_size if entry.is_file() else None,
                        "rel_path": str(entry.relative_to(self.root)).replace("\\", "/")
                    })
            else:
                for root, dirs, files in os.walk(target):
                    dirs[:] = [d for d in dirs if d not in ignore_dirs]
                    rel_dir = Path(root).relative_to(target)
                    depth = len(rel_dir.parts)
                    if depth > max_depth:
                        continue
                    for d in sorted(dirs):
                        p = Path(root) / d
                        results.append({
                            "name": d + "/",
                            "type": "dir",
                            "rel_path": str(p.relative_to(self.root)).replace("\\", "/")
                        })
                    for f in sorted(files):
                        p = Path(root) / f
                        results.append({
                            "name": f,
                            "type": "file",
                            "size": p.stat().st_size,
                            "rel_path": str(p.relative_to(self.root)).replace("\\", "/")
                        })
            return {"workspace_root": str(self.root), "path": path, "entries": results}
        except Exception as e:
            return {"error": f"Failed to list directory: {e}"}

    def read_file(self, path: str, start_line: int = 1, end_line: Optional[int] = None) -> Dict[str, Any]:
        """Read file contents with line numbers."""
        target = self.resolve_path(path)
        if not target.exists():
            return {"error": f"File not found: {path}"}
        if not target.is_file():
            return {"error": f"Path is not a file: {path}"}

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            total_lines = len(lines)

            s_idx = max(1, start_line)
            e_idx = min(total_lines, end_line) if end_line is not None else total_lines

            sliced_lines = lines[s_idx - 1:e_idx]
            numbered = [f"{i + s_idx}: {line}" for i, line in enumerate(sliced_lines)]

            return {
                "path": str(target.relative_to(self.root)).replace("\\", "/"),
                "total_lines": total_lines,
                "start_line": s_idx,
                "end_line": e_idx,
                "content": "\n".join(numbered)
            }
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        """Create or overwrite a file in the workspace, generating diff and snapshot."""
        target = self.resolve_path(path)
        existed = target.exists() and target.is_file()
        old_content = target.read_text(encoding="utf-8", errors="replace") if existed else ""
        snapshot_id = str(uuid.uuid4())[:8]

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            line_count = len(content.splitlines())
            byte_size = len(content.encode("utf-8"))
            rel_str = str(target.relative_to(self.root)).replace("\\", "/")

            # Generate unified diff
            diff_lines = list(difflib.unified_diff(
                old_content.splitlines(),
                content.splitlines(),
                fromfile=f"a/{rel_str}",
                tofile=f"b/{rel_str}",
                lineterm=""
            ))
            diff_text = "\n".join(diff_lines) if diff_lines else f"+ [New file: {rel_str} ({line_count} lines)]"

            self.snapshots[snapshot_id] = {
                "target": target,
                "rel_path": rel_str,
                "existed": existed,
                "old_content": old_content,
                "new_content": content,
                "diff": diff_text
            }
            self.snapshot_history.append(snapshot_id)

            return {
                "success": True,
                "path": rel_str,
                "lines": line_count,
                "bytes": byte_size,
                "snapshot_id": snapshot_id,
                "diff": diff_text,
                "message": f"Successfully wrote {line_count} lines to {rel_str}"
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to write file {path}: {e}"}

    def edit_file(self, path: str, old_str: str, new_str: str) -> Dict[str, Any]:
        """
        Replace old_str with new_str in a file.
        Tries three strategies in order:
          1. Exact match
          2. Whitespace-normalized match (ignores leading/trailing space differences per line)
          3. Stripped-line sequence match (ignores all indentation differences)
        Generates a unified diff and snapshot on success.
        """
        target = self.resolve_path(path)
        if not target.exists() or not target.is_file():
            return {"success": False, "error": f"File not found: {path}"}

        try:
            old_content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"success": False, "error": f"Cannot read {path}: {e}"}

        # ── Strategy 1: Exact match ──────────────────────────────────────────
        if old_str in old_content:
            count = old_content.count(old_str)
            if count > 1:
                return {
                    "success": False,
                    "error": (
                        f"Found {count} identical occurrences of the target string in {path}. "
                        f"Include more surrounding lines to make it unique."
                    )
                }
            updated = old_content.replace(old_str, new_str, 1)
            return self._write_edit_result(target, old_content, updated)

        # ── Strategy 2: Whitespace-normalised line comparison ────────────────
        def _norm(s: str) -> str:
            """Normalise each line: strip trailing space, collapse internal runs."""
            return "\n".join(" ".join(l.split()) for l in s.splitlines())

        norm_content = _norm(old_content)
        norm_old     = _norm(old_str)
        if norm_old and norm_old in norm_content:
            # Locate the real span by matching line-by-line
            old_lines     = old_str.splitlines()
            content_lines = old_content.splitlines()
            for start_idx in range(len(content_lines) - len(old_lines) + 1):
                chunk = content_lines[start_idx: start_idx + len(old_lines)]
                if [" ".join(l.split()) for l in chunk] == [" ".join(l.split()) for l in old_lines]:
                    # Rebuild preserving surrounding lines
                    new_lines = new_str.splitlines()
                    updated_lines = content_lines[:start_idx] + new_lines + content_lines[start_idx + len(old_lines):]
                    updated = "\n".join(updated_lines)
                    # Preserve trailing newline
                    if old_content.endswith("\n"):
                        updated += "\n"
                    return self._write_edit_result(target, old_content, updated)

        # ── Strategy 3: Stripped-line sequence (ignore all indentation) ──────
        stripped_content = [l.strip() for l in old_content.splitlines()]
        stripped_old     = [l.strip() for l in old_str.splitlines() if l.strip()]
        if stripped_old:
            for start_idx in range(len(stripped_content) - len(stripped_old) + 1):
                chunk = [l for l in stripped_content[start_idx: start_idx + len(stripped_old) + 4]
                         if l][:len(stripped_old)]
                if chunk == stripped_old:
                    content_lines = old_content.splitlines()
                    # Find real start/end lines
                    real_start = start_idx
                    real_end   = start_idx + len(stripped_old)
                    new_lines  = new_str.splitlines()
                    updated_lines = content_lines[:real_start] + new_lines + content_lines[real_end:]
                    updated = "\n".join(updated_lines)
                    if old_content.endswith("\n"):
                        updated += "\n"
                    return self._write_edit_result(target, old_content, updated,
                                                   note="(matched via stripped-line strategy)")

        # ── All strategies failed ────────────────────────────────────────────
        # Provide helpful context: show surrounding lines if partial match found
        hint = ""
        old_first = old_str.strip().splitlines()[0].strip() if old_str.strip() else ""
        if old_first:
            for i, line in enumerate(old_content.splitlines()):
                if old_first[:30] in line:
                    ctx_start = max(0, i - 2)
                    ctx_end   = min(len(old_content.splitlines()), i + 5)
                    ctx_lines = old_content.splitlines()[ctx_start:ctx_end]
                    hint = (
                        f"\n\nClosest match found at line ~{i+1}:\n"
                        + "\n".join(f"  {ctx_start+j+1}: {l}" for j, l in enumerate(ctx_lines))
                    )
                    break

        return {
            "success": False,
            "error": (
                f"Could not find the target text in '{path}' using exact, "
                f"whitespace-normalized, or stripped-line matching.\n"
                f"Use read_file to view the current file content and copy the exact lines to replace."
                + hint
            )
        }

    def _write_edit_result(
        self, target: Path, old_content: str, updated: str, note: str = ""
    ) -> Dict[str, Any]:
        """Write updated content, generate diff and snapshot. Internal helper."""
        try:
            target.write_text(updated, encoding="utf-8")
            rel_str     = str(target.relative_to(self.root)).replace("\\", "/")
            snapshot_id = str(uuid.uuid4())[:8]

            diff_lines = list(difflib.unified_diff(
                old_content.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{rel_str}",
                tofile=f"b/{rel_str}",
                lineterm=""
            ))
            diff_text = "\n".join(diff_lines) if diff_lines else f"~ [Modified {rel_str}]"

            self.snapshots[snapshot_id] = {
                "target":      target,
                "rel_path":    rel_str,
                "existed":     True,
                "old_content": old_content,
                "new_content": updated,
                "diff":        diff_text,
            }
            self.snapshot_history.append(snapshot_id)

            msg = f"Successfully edited {rel_str}"
            if note:
                msg += f" {note}"
            return {
                "success":     True,
                "path":        rel_str,
                "snapshot_id": snapshot_id,
                "diff":        diff_text,
                "message":     msg,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to write edit to {target}: {e}"}

    def patch_file(self, path: str, start_line: int, end_line: int, new_content: str) -> Dict[str, Any]:
        """
        Replace lines [start_line, end_line] (1-indexed, inclusive) with new_content.
        Equivalent to Antigravity's replace_file_content — line-range based surgical edit.
        If new_content is empty, cleanly deletes lines [start_line, end_line].
        """
        target = self.resolve_path(path)
        if not target.exists() or not target.is_file():
            return {"success": False, "error": f"File not found: {path}"}

        try:
            old_content   = target.read_text(encoding="utf-8", errors="replace")
            lines         = old_content.splitlines(keepends=True)
            total         = len(lines)

            if total == 0:
                return self._write_edit_result(target, "", new_content)

            # Clamp gracefully to valid range
            start_line = max(1, min(int(start_line), total))
            end_line   = max(start_line, min(int(end_line), total))

            # Build replacement: preserve or delete
            if new_content == "":
                new_lines = ""
            else:
                new_lines = new_content if new_content.endswith("\n") else new_content + "\n"

            updated = (
                "".join(lines[:start_line - 1])
                + new_lines
                + "".join(lines[end_line:])
            )

            return self._write_edit_result(target, old_content, updated)

        except Exception as e:
            return {"success": False, "error": f"Failed to patch {path}: {e}"}

    def append_file(self, path: str, content: str) -> Dict[str, Any]:
        """
        Append content to the end of an existing file in the workspace.
        If the file doesn't exist, creates it.
        """
        target = self.resolve_path(path)
        if not target.exists() or not target.is_file():
            return self.write_file(path, content)

        try:
            old_content = target.read_text(encoding="utf-8", errors="replace")
            new_content = old_content
            if new_content and not new_content.endswith("\n"):
                new_content += "\n"
            new_content += content
            if not new_content.endswith("\n"):
                new_content += "\n"

            return self._write_edit_result(target, old_content, new_content, note="(appended)")
        except Exception as e:
            return {"success": False, "error": f"Failed to append to {path}: {e}"}



    def delete_file(self, path: str) -> Dict[str, Any]:
        """Delete a file from the workspace (cannot delete directories)."""
        target = self.resolve_path(path)
        if not self.is_safe_path(target):
            return {"success": False, "error": "Path is outside the workspace."}
        if not target.exists():
            return {"success": False, "error": f"File not found: {path}"}
        if target.is_dir():
            return {"success": False, "error": f"'{path}' is a directory. Use delete_dir to remove directories."}
        try:
            rel_str = str(target.relative_to(self.root)).replace("\\", "/")
            old_content = target.read_text(encoding="utf-8", errors="replace")
            snapshot_id = str(uuid.uuid4())[:8]
            target.unlink()
            self.snapshots[snapshot_id] = {
                "target": target,
                "rel_path": rel_str,
                "existed": True,
                "old_content": old_content,
                "new_content": "",
                "diff": f"- [Deleted: {rel_str}]"
            }
            self.snapshot_history.append(snapshot_id)
            return {"success": True, "path": rel_str, "snapshot_id": snapshot_id, "message": f"Deleted {rel_str}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to delete {path}: {e}"}

    def rename_file(self, path: str, new_name: str) -> Dict[str, Any]:
        """Rename or move a file within the workspace."""
        source = self.resolve_path(path)
        dest   = self.resolve_path(new_name)
        if not self.is_safe_path(source):
            return {"success": False, "error": "Source path is outside the workspace."}
        if not self.is_safe_path(dest):
            return {"success": False, "error": "Destination path is outside the workspace."}
        if not source.exists():
            return {"success": False, "error": f"File not found: {path}"}
        if dest.exists():
            return {"success": False, "error": f"Destination already exists: {new_name}"}
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            source.rename(dest)
            src_str = str(source.relative_to(self.root)).replace("\\", "/")
            dst_str = str(dest.relative_to(self.root)).replace("\\", "/")
            return {"success": True, "from": src_str, "to": dst_str, "message": f"Renamed {src_str} → {dst_str}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to rename {path}: {e}"}

    def create_dir(self, path: str) -> Dict[str, Any]:
        """Create a directory (and any parents) inside the workspace."""
        target = self.resolve_path(path)
        if not self.is_safe_path(target):
            return {"success": False, "error": "Path is outside the workspace."}
        try:
            target.mkdir(parents=True, exist_ok=True)
            rel_str = str(target.relative_to(self.root)).replace("\\", "/")
            return {"success": True, "path": rel_str, "message": f"Created directory {rel_str}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to create directory {path}: {e}"}

    def get_file_info(self, path: str) -> Dict[str, Any]:
        """Return metadata about a file: size, line count, last modified, encoding hint."""
        target = self.resolve_path(path)
        if not target.exists():
            return {"error": f"File not found: {path}"}
        try:
            import stat as stat_module
            st = target.stat()
            rel_str = str(target.relative_to(self.root)).replace("\\", "/")
            if target.is_file():
                text = target.read_text(encoding="utf-8", errors="replace")
                lines = len(text.splitlines())
                size  = st.st_size
                mtime = datetime.fromtimestamp(st.st_mtime).isoformat()
                return {
                    "path": rel_str,
                    "type": "file",
                    "size_bytes": size,
                    "line_count": lines,
                    "modified": mtime,
                }
            else:
                return {"path": rel_str, "type": "directory", "modified": datetime.fromtimestamp(st.st_mtime).isoformat()}
        except Exception as e:
            return {"error": f"Failed to get info for {path}: {e}"}

    def grep_files(self, pattern: str, path: str = ".", case_sensitive: bool = True,
                   file_glob: str = "*", max_matches: int = 60) -> Dict[str, Any]:
        """
        Regex-capable grep across workspace files.
        Returns matched lines with file and line number context.
        """
        import re as re_module
        import fnmatch
        target = self.resolve_path(path)
        if not target.exists():
            return {"error": f"Directory not found: {path}"}

        ignore_dirs = {".git", "node_modules", "venv", ".venv", "__pycache__",
                       ".pytest_cache", ".next", "dist", "build", ".sierra"}
        flags = 0 if case_sensitive else re_module.IGNORECASE
        try:
            regex = re_module.compile(pattern, flags)
        except re_module.error as e:
            return {"error": f"Invalid regex pattern: {e}"}

        matches = []
        try:
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                for fname in files:
                    if not fnmatch.fnmatch(fname, file_glob):
                        continue
                    fp = Path(root) / fname
                    if fp.stat().st_size > 2_000_000:
                        continue
                    try:
                        content = fp.read_text(encoding="utf-8", errors="ignore")
                        for lineno, line in enumerate(content.splitlines(), 1):
                            if regex.search(line):
                                rel = str(fp.relative_to(self.root)).replace("\\", "/")
                                matches.append({"file": rel, "line": lineno, "text": line.strip()})
                                if len(matches) >= max_matches:
                                    break
                    except Exception:
                        continue
                    if len(matches) >= max_matches:
                        break
                if len(matches) >= max_matches:
                    break
            return {"pattern": pattern, "count": len(matches), "matches": matches}
        except Exception as e:
            return {"error": f"grep failed: {e}"}


    def revert_snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        """Roll back a previous write_file or edit_file action."""
        entry = self.snapshots.get(snapshot_id)
        if not entry:
            return {"success": False, "error": f"Snapshot '{snapshot_id}' not found"}

        target = entry["target"]
        rel_str = entry["rel_path"]
        try:
            if entry["existed"]:
                target.write_text(entry["old_content"], encoding="utf-8")
                return {"success": True, "path": rel_str, "message": f"Reverted {rel_str} to previous version"}
            else:
                if target.exists():
                    target.unlink()
                return {"success": True, "path": rel_str, "message": f"Deleted created file {rel_str}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to revert snapshot: {e}"}

    def undo_last_edit(self) -> Dict[str, Any]:
        """Roll back the most recent file change made in this session."""
        if not self.snapshot_history:
            return {"success": False, "error": "No recent edits to undo in this session."}
        last_id = self.snapshot_history.pop()
        return self.revert_snapshot(last_id)

    def check_syntax(self, path: str) -> Dict[str, Any]:
        """
        Validate syntax for code/markup files (.py, .json, .html, .js, .css, etc.)
        without executing them.
        """
        target = self.resolve_path(path)
        if not target.exists() or not target.is_file():
            return {"valid": False, "error": f"File not found: {path}"}

        rel_str = str(target.relative_to(self.root)).replace("\\", "/")
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"valid": False, "error": f"Could not read file: {e}"}

        suffix = target.suffix.lower()

        # 1. Python AST validation
        if suffix == ".py":
            import ast
            try:
                ast.parse(content, filename=rel_str)
                return {"valid": True, "path": rel_str, "language": "python", "message": "Syntax valid. No syntax errors detected."}
            except SyntaxError as e:
                return {
                    "valid": False,
                    "path": rel_str,
                    "language": "python",
                    "error": f"SyntaxError at line {e.lineno}, col {e.offset}: {e.msg}",
                    "line": e.lineno,
                    "offset": e.offset,
                    "text": e.text.strip() if e.text else "",
                }

        # 2. JSON validation
        elif suffix in (".json", ".jsonc"):
            try:
                json.loads(content)
                return {"valid": True, "path": rel_str, "language": "json", "message": "Valid JSON format."}
            except json.JSONDecodeError as e:
                return {
                    "valid": False,
                    "path": rel_str,
                    "language": "json",
                    "error": f"JSONDecodeError at line {e.lineno}, col {e.colno}: {e.msg}",
                    "line": e.lineno,
                }

        # 3. HTML validation (checks tag balance)
        elif suffix in (".html", ".htm"):
            from html.parser import HTMLParser
            class TagValidator(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.stack = []
                    self.errors = []
                    self.void_tags = {
                        "area", "base", "br", "col", "embed", "hr", "img", "input",
                        "link", "meta", "param", "source", "track", "wbr", "!doctype"
                    }
                def handle_starttag(self, tag, attrs):
                    t = tag.lower()
                    if t not in self.void_tags:
                        self.stack.append((t, self.getpos()))
                def handle_endtag(self, tag):
                    t = tag.lower()
                    if t in self.void_tags:
                        return
                    if not self.stack:
                        self.errors.append(f"Unexpected closing </{t}> at line {self.getpos()[0]}")
                    elif self.stack[-1][0] == t:
                        self.stack.pop()
                    else:
                        for idx in range(len(self.stack) - 1, -1, -1):
                            if self.stack[idx][0] == t:
                                missed = [f"<{name}> (line {pos[0]})" for name, pos in self.stack[idx+1:]]
                                if missed:
                                    self.errors.append(f"Unclosed tag(s) {', '.join(missed)} before </{t}> at line {self.getpos()[0]}")
                                self.stack = self.stack[:idx]
                                break

            val = TagValidator()
            try:
                val.feed(content)
                val.close()
                if val.errors:
                    return {"valid": False, "path": rel_str, "language": "html", "error": "; ".join(val.errors[:5])}
                if val.stack:
                    unclosed = [f"<{name}> (line {pos[0]})" for name, pos in val.stack]
                    return {"valid": False, "path": rel_str, "language": "html", "error": f"Unclosed tags at end of file: {', '.join(unclosed)}"}
                return {"valid": True, "path": rel_str, "language": "html", "message": "HTML structure valid. All tags properly balanced."}
            except Exception as e:
                return {"valid": False, "path": rel_str, "language": "html", "error": f"HTML parsing error: {e}"}

        # 4. JavaScript / TypeScript / CSS brace balance check
        elif suffix in (".js", ".ts", ".jsx", ".tsx", ".css", ".scss"):
            stack = []
            pairs = {')': '(', '}': '{', ']': '['}
            lines = content.splitlines()
            in_comment = False
            for lineno, line in enumerate(lines, 1):
                i = 0
                while i < len(line):
                    ch = line[i]
                    if in_comment:
                        if ch == '*' and i + 1 < len(line) and line[i+1] == '/':
                            in_comment = False
                            i += 2
                            continue
                        i += 1
                        continue
                    if ch == '/' and i + 1 < len(line):
                        if line[i+1] == '/':
                            break
                        elif line[i+1] == '*':
                            in_comment = True
                            i += 2
                            continue
                    if ch in ('"', "'", '`'):
                        quote = ch
                        i += 1
                        while i < len(line):
                            if line[i] == '\\':
                                i += 2
                            elif line[i] == quote:
                                i += 1
                                break
                            else:
                                i += 1
                        continue
                    if ch in "({[":
                        stack.append((ch, lineno))
                    elif ch in ")}]":
                        expected = pairs[ch]
                        if not stack:
                            return {"valid": False, "path": rel_str, "language": suffix[1:], "error": f"Unmatched closing '{ch}' at line {lineno}"}
                        top, open_line = stack.pop()
                        if top != expected:
                            return {"valid": False, "path": rel_str, "language": suffix[1:], "error": f"Mismatched '{ch}' at line {lineno} (expected '{top}' from line {open_line})"}
                    i += 1
            if stack:
                top, open_line = stack[-1]
                return {"valid": False, "path": rel_str, "language": suffix[1:], "error": f"Unclosed '{top}' from line {open_line}"}
            return {"valid": True, "path": rel_str, "language": suffix[1:], "message": f"{suffix[1:].upper()} syntax brackets balanced."}

        return {"valid": True, "path": rel_str, "language": suffix[1:] or "text", "message": "File syntax check passed."}

    def get_file_outline(self, path: str) -> Dict[str, Any]:
        """
        Extract code structure outline (classes, functions, methods, headers, IDs)
        with line numbers so the agent can quickly navigate large files.
        """
        target = self.resolve_path(path)
        if not target.exists() or not target.is_file():
            return {"error": f"File not found: {path}"}

        rel_str = str(target.relative_to(self.root)).replace("\\", "/")
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {"error": f"Could not read file: {e}"}

        suffix = target.suffix.lower()
        items = []

        if suffix == ".py":
            import ast
            try:
                tree = ast.parse(content, filename=rel_str)
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, ast.ClassDef):
                        items.append(f"Line {node.lineno}: class {node.name}")
                        for sub in node.body:
                            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                items.append(f"  Line {sub.lineno}: def {sub.name}()")
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        items.append(f"Line {node.lineno}: def {node.name}()")
            except Exception:
                pass

        elif suffix in (".js", ".ts", ".jsx", ".tsx"):
            import re
            lines = content.splitlines()
            for lineno, line in enumerate(lines, 1):
                line_str = line.strip()
                if re.match(r'^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z0-9_$]+)', line_str):
                    items.append(f"Line {lineno}: {line_str[:60]}")
                elif re.match(r'^(?:export\s+)?class\s+([A-Za-z0-9_$]+)', line_str):
                    items.append(f"Line {lineno}: {line_str[:60]}")
                elif re.match(r'^(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z0-9_$]+)\s*=>', line_str):
                    items.append(f"Line {lineno}: {line_str[:60]}")

        elif suffix in (".html", ".htm"):
            import re
            lines = content.splitlines()
            for lineno, line in enumerate(lines, 1):
                m = re.search(r'<(h[1-6]|header|footer|nav|main|section|article|div)\b([^>]*)>', line, re.IGNORECASE)
                if m:
                    tag = m.group(1).lower()
                    attrs = m.group(2)
                    id_m = re.search(r'id=["\']([^"\']+)["\']', attrs)
                    class_m = re.search(r'class=["\']([^"\']+)["\']', attrs)
                    info = f"<{tag}"
                    if id_m:
                        info += f' id="#{id_m.group(1)}"'
                    if class_m:
                        info += f' class=".{class_m.group(1).split()[0]}"'
                    info += ">"
                    if tag in ('h1', 'h2', 'h3') or id_m:
                        items.append(f"Line {lineno}: {info}")

        elif suffix in (".css", ".scss"):
            lines = content.splitlines()
            for lineno, line in enumerate(lines, 1):
                if line.strip().endswith('{') and not line.strip().startswith('@media') and not line.strip().startswith('/*'):
                    selector = line.strip()[:-1].strip()
                    if selector and len(selector) < 50:
                        items.append(f"Line {lineno}: {selector}")

        if not items:
            total_lines = len(content.splitlines())
            return {
                "path": rel_str,
                "total_lines": total_lines,
                "summary": f"{rel_str} ({total_lines} lines)",
                "items": []
            }

        return {
            "path": rel_str,
            "total_items": len(items),
            "outline": "\n".join(items)
        }

    def run_command(self, command: str, timeout: int = 120) -> Dict[str, Any]:
        """Execute a shell command in the workspace directory."""
        if not command or not command.strip():
            return {"error": "Empty command provided"}

        cmd_str = command.strip()
        try:
            shell_cmd = ["powershell.exe", "-NoProfile", "-Command", cmd_str] if os.name == "nt" else cmd_str
            proc = subprocess.Popen(
                shell_cmd,
                cwd=str(self.root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False if os.name == "nt" else True
            )

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return {
                    "command": cmd_str,
                    "exit_code": -1,
                    "timed_out": True,
                    "output": f"Command timed out after {timeout} seconds.\n{stdout}\n{stderr}".strip()
                }

            combined = ""
            if stdout:
                combined += stdout
            if stderr:
                if combined:
                    combined += "\n"
                combined += f"[stderr]\n{stderr}"

            max_len = 5000
            if len(combined) > max_len:
                combined = combined[:max_len] + f"\n... [Output truncated, {len(combined) - max_len} more chars]"

            if not combined.strip():
                combined = "(Command executed with no output)"

            return {
                "command": cmd_str,
                "exit_code": exit_code,
                "output": combined.strip()
            }
        except Exception as e:
            return {
                "command": cmd_str,
                "exit_code": 1,
                "error": f"Failed to execute command: {e}"
            }

    def search_code(self, query: str, path: str = ".", max_matches: int = 50) -> Dict[str, Any]:
        """Search files in workspace for text matches."""
        target = self.resolve_path(path)
        if not target.exists():
            return {"error": f"Directory not found: {path}"}

        ignore_dirs = {
            ".git", "node_modules", "venv", ".venv", "__pycache__",
            ".pytest_cache", ".next", "dist", "build", ".sierra"
        }

        matches = []
        try:
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in ignore_dirs]
                for file_name in files:
                    file_path = Path(root) / file_name
                    if file_path.stat().st_size > 1_000_000:
                        continue
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="ignore")
                        for line_num, line in enumerate(content.splitlines(), start=1):
                            if query.lower() in line.lower():
                                rel = str(file_path.relative_to(self.root)).replace("\\", "/")
                                matches.append({
                                    "file": rel,
                                    "line": line_num,
                                    "text": line.strip()
                                })
                                if len(matches) >= max_matches:
                                    break
                    except Exception:
                        continue
                    if len(matches) >= max_matches:
                        break
                if len(matches) >= max_matches:
                    break

            return {
                "query": query,
                "count": len(matches),
                "matches": matches
            }
        except Exception as e:
            return {"error": f"Search failed: {e}"}
