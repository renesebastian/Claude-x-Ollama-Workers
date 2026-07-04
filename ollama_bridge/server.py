# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "mcp[cli]>=1.2.0",
#     "httpx>=0.27",
# ]
# ///
"""
ollama-bridge: exposes local Ollama models as MCP tools for an orchestrating
Claude Code session. Started automatically via .mcp.json (uv run --script),
no manual environment setup required.

Design goals:
- Keep the orchestrator's own token usage minimal. delegate_task lets a
  local Ollama model self-correct against a verification command for
  several rounds without involving the orchestrator on each retry — only
  the final outcome is returned.
- Let Ollama models keep their own persistent notes (memory/*.md) between
  tasks, entirely between this tool and Ollama. The orchestrator only ever
  passes a short topic label; it never reads or writes the notes.
- Refuse up front, without spending a round-trip, if a chosen model
  obviously won't fit in this machine's memory (this repo runs on machines
  with very different amounts of RAM).
"""
import os
import re
import subprocess
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "300"))
REPO_ROOT = Path.cwd().resolve()
MEMORY_DIR = REPO_ROOT / "memory"

mcp = FastMCP("ollama-bridge")


# ---------------------------------------------------------------- helpers --

def _chat(model: str, messages: list, think: bool = False) -> str:
    payload = {"model": model, "messages": messages, "stream": False}
    if think:
        payload["think"] = True
    r = httpx.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")


def _extract_code(text: str) -> str:
    """Pull the first fenced code block out of a model response, if present."""
    match = re.search(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
    return match.group(1) if match else text


def _safe_path(rel_path: str) -> Path:
    path = (REPO_ROOT / rel_path).resolve()
    if REPO_ROOT != path and REPO_ROOT not in path.parents:
        raise ValueError("output_file must stay inside the project folder")
    return path


_IGNORE_DIRS = {
    ".git", ".claude", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", "memory",
}


def _repo_tree(max_entries: int = 300) -> str:
    """Relative file listing of the repo, so a model that never saw this
    project before still has real orientation instead of working blind."""
    lines = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORE_DIRS and not d.startswith("."))
        rel_root = Path(root).relative_to(REPO_ROOT)
        for f in sorted(files):
            if f.startswith("."):
                continue
            rel = (rel_root / f) if str(rel_root) != "." else Path(f)
            lines.append(str(rel))
            if len(lines) >= max_entries:
                lines.append("... (truncated, more files exist)")
                return "\n".join(lines)
    return "\n".join(lines) if lines else "(empty project)"


def _is_probably_text(path: Path, sniff_bytes: int = 2048) -> bool:
    try:
        chunk = path.read_bytes()[:sniff_bytes]
    except Exception:
        return False
    return b"\x00" not in chunk


def _repo_context(output_file: str) -> str:
    """The model should understand the whole project, not just the one file
    it's touching, so it can fix things properly instead of bolting on a
    narrow patch. This sends the repo's file listing plus the full content
    of its text files (skipping obvious binaries and anything huge), capped
    by a character budget so it still fits a local model's context window.
    output_file is shown separately afterward, front and center, since
    that's the one the model must actually write.
    """
    max_chars = int(os.environ.get("OLLAMA_CONTEXT_CHARS", "80000"))
    skip_path = _safe_path(output_file) if output_file else None

    header = f"Repository file listing (relative to project root):\n{_repo_tree()}\n"
    parts = [header]
    used = len(header)
    skipped_for_size = []
    truncated = False

    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORE_DIRS and not d.startswith("."))
        for f in sorted(files):
            if f.startswith("."):
                continue
            path = Path(root) / f
            if skip_path is not None and path.resolve() == skip_path:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > 200_000:
                skipped_for_size.append(str(path.relative_to(REPO_ROOT)))
                continue
            if not _is_probably_text(path):
                continue
            try:
                content = path.read_text(errors="replace")
            except Exception:
                continue
            rel = path.relative_to(REPO_ROOT)
            block = f"\n--- {rel} ---\n{content}\n"
            if used + len(block) > max_chars:
                truncated = True
                break
            parts.append(block)
            used += len(block)
        if truncated:
            break

    if truncated:
        parts.append(
            f"\n(stopped including further files: context budget of "
            f"{max_chars} characters reached — raise OLLAMA_CONTEXT_CHARS "
            "if this matters for the task)"
        )
    if skipped_for_size:
        parts.append("\n(skipped large files: " + ", ".join(skipped_for_size) + ")")

    if output_file:
        try:
            path = _safe_path(output_file)
            if path.exists():
                parts.append(
                    f"\nYou are now editing {output_file}. Its current full "
                    f"content:\n```\n{path.read_text(errors='replace')}\n```\n"
                )
            else:
                parts.append(f"\nYou are now creating a new file at {output_file}.\n")
        except Exception:
            pass

    parts.append(
        "\nUse the repository context above to understand how this fits "
        "into the whole project, and prefer fixing the actual underlying "
        "issue over a narrow patch that only treats the symptom. At the "
        "same time, keep the change surgical: touch only what this task "
        "requires, don't refactor or \"clean up\" unrelated code, match "
        "the existing style even where you'd do it differently, and don't "
        "add abstractions, options, or error handling that weren't asked "
        "for. If you're genuinely unsure about an assumption, say so in "
        "your reply instead of silently guessing."
    )
    return "".join(parts)


def _total_ram_bytes():
    """Best-effort total system RAM, in bytes. None if it can't be determined."""
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3
        )
        if out.returncode == 0 and out.stdout.strip().isdigit():
            return int(out.stdout.strip())
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return None


def _model_size_bytes(model: str):
    """Installed size of `model` per Ollama, in bytes. None if unknown."""
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
        r.raise_for_status()
    except Exception:
        return None
    for m in r.json().get("models", []):
        if m.get("name") == model:
            return m.get("size")
    return None


def _ram_warning(model: str) -> str:
    """Non-empty warning if `model` obviously won't fit in this machine's
    memory. This repo runs on machines ranging from 36GB to 128GB of RAM,
    so the same model name can be fine on one and reckless on the other."""
    total = _total_ram_bytes()
    size = _model_size_bytes(model)
    if not total or not size:
        return ""
    if size > 0.85 * total:
        return (
            f"Warning: {model} is {round(size / 1e9, 1)} GB, this machine "
            f"has {round(total / 1e9, 1)} GB of memory. That's unlikely to "
            "fit alongside the OS and everything else running. Pick a "
            "smaller model (see list_ollama_models) or check with the user "
            "before proceeding."
        )
    return ""


def _memory_path(topic: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", topic.strip()) or "general"
    return MEMORY_DIR / f"{safe}.md"


def _read_memory(topic: str) -> str:
    path = _memory_path(topic)
    return path.read_text() if path.exists() else ""


def _write_memory(topic: str, content: str) -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _memory_path(topic).write_text(content.strip() + "\n")


_MEMORY_BLOCK_RE = re.compile(r"---MEMORY---\s*(.*?)\s*---END MEMORY---", re.DOTALL)


def _split_memory_block(reply: str):
    """Return (reply_without_memory_block, memory_content_or_None)."""
    match = _MEMORY_BLOCK_RE.search(reply)
    if not match:
        return reply, None
    cleaned = reply[: match.start()] + reply[match.end():]
    return cleaned.strip(), match.group(1)


# -------------------------------------------------------------------- tools --

@mcp.tool()
def list_ollama_models() -> str:
    """List Ollama models installed on this machine, with size and family,
    plus this machine's total memory. Call this once per session before
    delegating, since both differ per machine this repo runs on."""
    try:
        r = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=10)
        r.raise_for_status()
    except httpx.ConnectError:
        return (
            f"Could not reach Ollama at {OLLAMA_HOST}. Is it running? "
            "Start it with `ollama serve` or open the Ollama app."
        )
    except Exception as e:
        return f"Error contacting Ollama: {e}"

    total = _total_ram_bytes()
    header = f"Total memory on this machine: {round(total / 1e9, 1)} GB.\n" if total else ""

    models = r.json().get("models", [])
    if not models:
        return header + "No models installed. Pull one first, e.g. `ollama pull qwen2.5-coder:7b`."

    lines = []
    for m in models:
        name = m.get("name", "unknown")
        size_gb = round(m.get("size", 0) / 1e9, 1)
        family = m.get("details", {}).get("family", "")
        lines.append(f"- {name} ({size_gb} GB, {family})")
    return header + "\n".join(lines)


@mcp.tool()
def list_memory_topics() -> str:
    """List existing memory topics: persistent notes local Ollama models
    keep for themselves between tasks, stored under memory/*.md. Check
    this before inventing a new topic name, so related tasks share one
    file instead of fragmenting into near-duplicates like "auth" and
    "authentication". You are not expected to read the contents — they're
    written and read entirely between Ollama and delegate_task."""
    if not MEMORY_DIR.exists():
        return "No memory topics yet."
    files = sorted(p.stem for p in MEMORY_DIR.glob("*.md"))
    return "\n".join(f"- {f}" for f in files) if files else "No memory topics yet."


@mcp.tool()
def ask_ollama(model: str, prompt: str, system: str = "", think: bool = False) -> str:
    """One-shot delegation to a local Ollama model. Use for small,
    non-code tasks: explanations, translation, drafting text. For code
    that should be written to a file and checked, use delegate_task instead.

    Args:
        model: Exact model name from list_ollama_models, e.g. "llama3.1:8b".
        prompt: Complete, self-contained task. The model has no memory of
            this conversation and no repo access beyond what you paste in.
        system: Optional system prompt for role/constraints/output format.
        think: Enable the model's extended-thinking mode for genuinely
            tricky reasoning. Leave off (default) for straightforward
            tasks — it's slower and uses more resources for no benefit.
    """
    warning = _ram_warning(model)
    if warning:
        return warning

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        return _chat(model, messages, think=think) or "(empty response)"
    except httpx.ConnectError:
        return f"Could not reach Ollama at {OLLAMA_HOST}. Is it running?"
    except httpx.HTTPStatusError as e:
        return f"Ollama returned an error ({e.response.status_code}): {e.response.text}"
    except httpx.ReadTimeout:
        return f"Ollama did not respond within {TIMEOUT}s. Try a smaller model or a shorter task."
    except Exception as e:
        return f"Error contacting Ollama: {e}"


@mcp.tool()
def delegate_task(
    model: str,
    task: str,
    system: str = "",
    output_file: str = "",
    verify_cmd: str = "",
    max_rounds: int = 3,
    think: bool = False,
    memory_topic: str = "",
) -> str:
    """Delegate a coding task to a local Ollama model and let it self-correct
    without spending orchestrator tokens on each retry.

    The model automatically gets the repo's file listing and, if
    output_file already exists, its current content — you don't need to
    paste that in yourself. Still write a clear, complete task: describe
    what changes, why, and any edge cases, since none of that is visible
    from the files alone. If output_file is set, the code from the
    model's response is written there after each attempt. If verify_cmd is
    also set (e.g. "pytest tests/test_x.py -q" or "python3 -m py_compile
    app.py"), it runs after every attempt; on failure, the error is fed
    straight back to the model for another try, up to max_rounds — all
    without involving you in between. Only the final outcome is returned.

    Args:
        model: Exact model name from list_ollama_models, e.g. "qwen2.5-coder:7b".
        task: Full, self-contained task description.
        system: Optional system prompt.
        output_file: Path, relative to the repo root, to write the result to.
        verify_cmd: Shell command to validate the result; non-zero exit triggers a retry.
        max_rounds: Max attempts before giving up (default 3).
        think: Enable the model's extended-thinking mode for genuinely
            tricky logic or edge cases. Leave off (default) for boilerplate
            and straightforward functions — it's slower and heavier for no
            benefit there.
        memory_topic: Short label (e.g. "auth", "utils") for a persistent
            notes file this model keeps for itself under memory/. Call
            list_memory_topics first so related work reuses one topic
            instead of fragmenting. You never see the contents of these
            notes: they're written and read entirely between Ollama and
            this tool, on purpose, so they stay Ollama's own working memory
            and don't cost you tokens.
    """
    warning = _ram_warning(model)
    if warning:
        return warning

    memory_instructions = ""
    if memory_topic:
        existing_memory = _read_memory(memory_topic)
        memory_instructions = (
            "You keep your own working notes about this part of the "
            f"codebase in a memory file called '{memory_topic}'. Here is "
            "its current content, written by a previous run of yours, not "
            f"by the orchestrator:\n\n{existing_memory or '(empty, nothing recorded yet)'}\n\n"
            "Use these notes. At the very end of your reply, after your "
            "code, add a block exactly like this:\n"
            "---MEMORY---\n"
            "<the complete, updated version of your notes: keep it short "
            "and concrete, overwrite anything now outdated, add anything "
            "new worth remembering next time>\n"
            "---END MEMORY---\n"
            "If nothing needs to change, repeat the existing notes "
            "unchanged in that block. Never put this block anywhere except "
            "the very end of your reply."
        )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "system", "content": _repo_context(output_file)})
    if memory_instructions:
        messages.append({"role": "system", "content": memory_instructions})
    messages.append({"role": "user", "content": task})

    last_error = ""
    for round_num in range(1, max(1, max_rounds) + 1):
        try:
            raw_reply = _chat(model, messages, think=think)
        except httpx.ConnectError:
            return f"Could not reach Ollama at {OLLAMA_HOST}. Is it running?"
        except httpx.HTTPStatusError as e:
            return f"Ollama returned an error ({e.response.status_code}): {e.response.text}"
        except httpx.ReadTimeout:
            return f"Ollama did not respond within {TIMEOUT}s on round {round_num}."
        except Exception as e:
            return f"Error contacting Ollama on round {round_num}: {e}"

        reply, new_memory = _split_memory_block(raw_reply)
        if memory_topic and new_memory is not None:
            _write_memory(memory_topic, new_memory)

        messages.append({"role": "assistant", "content": reply})

        if not output_file:
            return reply

        code = _extract_code(reply)
        try:
            path = _safe_path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code)
        except Exception as e:
            return f"Could not write {output_file}: {e}"

        if not verify_cmd:
            return f"Wrote {output_file} after round {round_num} (no verify_cmd given, not checked)."

        try:
            proc = subprocess.run(
                verify_cmd,
                shell=True,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return f"Verification command timed out on round {round_num}."

        if proc.returncode == 0:
            return f"Done in {round_num} round(s). {output_file} passes `{verify_cmd}`."

        last_error = (proc.stdout + proc.stderr).strip()[-4000:]
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Verification failed:\n{last_error}\n\n"
                    "Fix it and return the complete corrected file in a single code block."
                ),
            }
        )

    return (
        f"Gave up after {max_rounds} round(s). Last error:\n{last_error}\n"
        f"Last attempt is saved at {output_file} for you to inspect."
    )


if __name__ == "__main__":
    mcp.run()
