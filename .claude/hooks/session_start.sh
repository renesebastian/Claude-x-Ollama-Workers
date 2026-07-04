#!/bin/bash
# Runs automatically every time Claude Code starts or resumes a session in
# this project (SessionStart hook, see .claude/settings.json). Its stdout is
# injected straight into Claude's context, so by the time Claude reads the
# first message it already knows whether Ollama is up and which models are
# installed on this specific machine — no tool call, no guessing.

set -uo pipefail

RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || true)
if [ -n "${RAM_BYTES:-}" ]; then
  RAM_GB=$(( RAM_BYTES / 1024 / 1024 / 1024 ))
  echo "Geheugen op deze machine: ${RAM_GB} GB. Houd hier rekening mee bij het kiezen van een model."
fi

TAGS=$(curl -s --max-time 3 http://localhost:11434/api/tags 2>/dev/null) || true

if [ -z "$TAGS" ]; then
  echo "Ollama is niet bereikbaar op localhost:11434. Start 'ollama serve' of open de Ollama app voordat je delegate_task of ask_ollama gebruikt."
  exit 0
fi

echo "Ollama draait op deze machine. Lokaal beschikbare modellen (gebruik deze exacte namen bij delegate_task/ask_ollama):"
echo "$TAGS" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    print('- (kon modellenlijst niet lezen, roep list_ollama_models handmatig aan)')
    sys.exit(0)
models = data.get('models', [])
if not models:
    print('- geen modellen gepulled. Doe dat eerst, bijvoorbeeld: ollama pull qwen2.5-coder:7b')
for m in models:
    name = m.get('name', '?')
    size_gb = round(m.get('size', 0) / 1e9, 1)
    family = m.get('details', {}).get('family', '')
    print(f'- {name} ({size_gb} GB, {family})')
"
