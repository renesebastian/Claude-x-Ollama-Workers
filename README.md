# Claude x Ollama

Let Claude Code plan and check, and let local Ollama models do most of the
actual writing and iterating.

## Requirements

- Ollama installed, with at least one model pulled, e.g.:
  `ollama run ornith:9b`
- Ollama running: `ollama serve`, or just have the Ollama app open
- [uv](https://docs.astral.sh/uv/) installed: `brew install uv`
- Claude Code CLI, logged in

## Usage

Place this folder in your main project folder. Then:

1. Run `claude`.
2. Say: **"Read the 'Claude-x-Ollama-Workers' folder and adjust your workflow to
   it."**

That's it.

## What's under the hood

Claude reads `CLAUDE.md` inside this folder and takes over as an
orchestrator: it plans, hands tasks to a local Ollama model, and checks
the result, instead of writing everything itself. A few things happen
automatically as part of that:

- **Delegation with self-correction** — Ollama writes the code, a test or
  lint command checks it, and Ollama fixes its own mistakes for a few
  rounds before Claude ever gets involved again.
- **Persistent memory** — Ollama keeps its own short notes per part of the
  codebase (`memory/*.md`), so it doesn't start from zero every time.
- **Thinking mode** — switched on for tasks with real logic, left off for
  boilerplate, since it's slower and heavier.
- **Memory-aware model choice** — a model's size is checked against this
  machine's available RAM before it's used, since this can run on very
  different machines.
- **No MCP connection needed** — when this folder is read out of another
  project rather than opened directly, Claude reaches Ollama through the
  same logic via a plain CLI instead of a wired-up tool. Either way, the
  behavior is the same.

The exact mechanics — commands, flags, protocol — live in `CLAUDE.md`,
which Claude reads directly; there's nothing here you need to run by hand.
