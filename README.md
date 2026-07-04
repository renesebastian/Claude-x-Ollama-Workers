# Claude x Ollama

Laat Claude Code plannen en controleren, en laat lokale Ollama-modellen het
meeste van het eigenlijke schrijf- en itereerwerk doen. Een Claude model
naar keuze is de orchestrator: het geeft opdrachten, checkt resultaten, en
houdt zijn eigen tokengebruik minimaal doordat Ollama zelf fouten oplost
via een lokale verify-en-herstel loop (zie CLAUDE.md en `delegate_task` in
`ollama_bridge/server.py`). Ollama-modellen houden daarbij ook hun eigen
werkgeheugen bij per onderdeel van de code, zodat kennis blijft hangen
tussen taken door.

Alles gebeurt automatisch zodra je deze map opent in Claude Code: geen
skill, commando of los stapje. `CLAUDE.md` wordt vanzelf geladen, en de
`SessionStart` hook (`.claude/hooks/session_start.sh`) checkt bij elke
sessiestart vanzelf of Ollama draait, welke modellen er lokaal staan, en
hoeveel geheugen de machine heeft.

## Vereisten (op elke Mac waar je dit gebruikt)

- Ollama geïnstalleerd, met minstens één model gepulled, bijvoorbeeld:
  `ollama pull qwen2.5-coder:7b`
- Ollama draaiend: `ollama serve`, of gewoon de Ollama app open
- [uv](https://docs.astral.sh/uv/) geïnstalleerd: `brew install uv`
- Claude Code CLI, ingelogd

## Gebruik

1. Clone deze repo.
2. Zorg dat Ollama draait en er minstens één model gepulled is.
3. `cd` naar de repo en start `claude`.
4. Claude Code ziet `.mcp.json` en vraagt eenmalig toestemming om de
   `ollama-bridge` server te starten. Keur dat goed.
5. Claude leest automatisch `CLAUDE.md` en weet meteen dat hij orchestreert
   en het werk aan Ollama overlaat.

Verder geen setup nodig. `.mcp.json` start de server met `uv run --script`;
`uv` installeert de paar benodigde packages (`mcp`, `httpx`) de eerste keer
automatisch, geïsoleerd van de rest van je systeem. Omdat het script zelf
zijn dependencies declareert, werkt hetzelfde repo ongewijzigd op beide
Macs, ongeacht welke modellen daar lokaal geïnstalleerd zijn.

## Bestanden

- `CLAUDE.md` — het protocol dat de orchestrator volgt
- `.mcp.json` — project MCP-configuratie, start `ollama_bridge/server.py`
- `ollama_bridge/server.py` — de brug naar de lokale Ollama API
- `.claude/settings.json` — registreert de SessionStart hook
- `.claude/hooks/session_start.sh` — checkt bij sessiestart of Ollama
  draait, welke modellen er lokaal staan en hoeveel geheugen de machine
  heeft, en print dat direct in Claude's context
- `memory/*.md` — werkgeheugen van de Ollama-modellen zelf, per onderdeel
  van de code (zie hieronder). Gewoon meenemen in git, zodat beide Macs
  hetzelfde geheugen delen na een pull
- `README.md` — dit bestand

Puur gericht op Claude Code. Geen Cowork-ondersteuning, geen tunnel, geen
externe connector — dit draait lokaal, klaar.

## Tools voor de orchestrator

- `list_ollama_models` — welke modellen staan lokaal klaar, en hoeveel
  geheugen deze machine heeft
- `list_memory_topics` — welke werkgeheugen-bestanden al bestaan
- `ask_ollama(model, prompt, system, think)` — één prompt, één antwoord,
  voor kleine taken (tekst, uitleg, vertaling)
- `delegate_task(model, task, system, output_file, verify_cmd, max_rounds, think, memory_topic)`
  — de kerntool. Geeft het model automatisch de bestandsboom van de repo
  en, als `output_file` al bestaat, de huidige inhoud daarvan mee, zodat
  het niet blind hoeft te gokken naar bestaande conventies. Schrijft het
  resultaat naar een bestand en laat Ollama tot `max_rounds` keer zichzelf
  corrigeren op basis van de uitkomst van `verify_cmd` (tests, compileren,
  linten), zonder dat de orchestrator daar tussendoor tokens aan kwijt is

## Werkgeheugen van de Ollama-modellen

Ollama heeft, anders dan Claude, geen geheugen tussen taken door: elke
aanroep begint bij nul. `delegate_task` vult dat gedeeltelijk aan via
`memory_topic`: geef je die mee, dan krijgt het model zijn eigen eerdere
aantekeningen over dat onderdeel van de code te lezen, en schrijft het aan
het eind een bijgewerkte versie terug naar `memory/<topic>.md`. Dat gebeurt
volledig binnen de tool. De orchestrator geeft alleen het label door, ziet
de inhoud nooit, en kost er dus ook geen tokens aan. Het model overschrijft
zijn eigen aantekeningen elke keer met een volledige, bijgewerkte versie in
plaats van eindeloos aan te vullen, dus het blijft vanzelf compact.

## Denken aan of uit

Sommige Ollama-modellen ondersteunen een `think`-modus voor uitgebreider
redeneren, ten koste van snelheid en geheugengebruik. `ask_ollama` en
`delegate_task` hebben een `think` parameter (standaard uit) die de
orchestrator per taak aanzet voor taken met echte logica, en uit laat voor
boilerplate.

## Geheugencheck voordat een model draait

Dit repo draait op machines met sterk verschillend geheugen (deze Mac
bijvoorbeeld 36 GB, de Mac Studio 128 GB). `delegate_task` en `ask_ollama`
vergelijken de bestandsgrootte van het gekozen model met het totale
geheugen van de machine, en weigeren met een duidelijke melding als een
model daar duidelijk niet in past, in plaats van het gewoon te laten
vastlopen of de boel te laten swappen.

## Instellen

- `OLLAMA_HOST` (env var, default `http://localhost:11434`)
- `OLLAMA_TIMEOUT` (env var, seconden, default 300) — hoger zetten voor
  grote modellen op de Mac Studio

## Voorbeeld

```
Bouw een functie is_palindrome(s) in utils.py met tests in test_utils.py,
gebruik qwen2.5-coder:7b, en check met pytest.
```

De orchestrator roept dan ongeveer aan:

```
delegate_task(
  model="qwen2.5-coder:7b",
  task="Schrijf is_palindrome(s) in utils.py ...",
  output_file="utils.py",
  verify_cmd="pytest test_utils.py -q",
  memory_topic="utils",
)
```

en rapporteert alleen het eindresultaat: geslaagd na N rondes, of vastgelopen
met de laatste foutmelding.
