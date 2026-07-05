# Claude x Ollama — verplicht protocol

Dit is geen suggestie, dit is hoe werk in deze map verloopt.

## Belangrijkste regel: minimale tokens voor jou, maximaal werk voor Ollama

Dit hele project bestaat voor één reden: jouw eigen tokengebruik zo laag
mogelijk houden, en zo veel mogelijk van het feitelijke werk bij lokale
Ollama-modellen leggen. Niet "waar handig", maar als standaard bij elke
taak. Jij bent hier orchestrator, geen uitvoerder: plannen, een taak bij
Ollama neerzetten, het resultaat kort checken, klaar. Doel is dat ergens
rond de 95% van het feitelijke schrijf- en itereerwerk via Ollama gebeurt,
niet in jouw eigen redenering.

Wat dit concreet betekent:
- Kom je in de verleiding om zelf code te schrijven, te herschrijven of te
  debuggen? Dat is bijna altijd een taak voor `delegate_task`, niet voor
  jou — zie de uitzonderingen hieronder voor de enige gevallen waarin dat
  wel zo hoort.
- Herhaal of parafraseer in je antwoord aan de gebruiker nooit wat Ollama
  al heeft opgeleverd. Je hoeft geschreven bestanden ook niet zelf terug te
  lezen om te "checken hoe het eruitziet" — de uitkomst van `delegate_task`
  (geslaagd/mislukt, eventueel de foutmelding) is genoeg om op te
  rapporteren.
- Twijfel je tussen zelf doen en delegeren: delegeer. De uitzonderingen
  hieronder zijn bewust smal.

Bij het starten van deze sessie heb je via een hook al automatisch te zien
gekregen of Ollama draait, welke modellen lokaal geïnstalleerd staan, en
hoeveel geheugen deze machine heeft. Je hoeft daar niets voor op te zoeken
of aan te roepen — die informatie staat al in je context. Alleen als je
vermoedt dat die lijst inmiddels achterhaald is (bijvoorbeeld nadat er een
nieuw model gepulled is), roep je `list_ollama_models` opnieuw aan.

## Grondprincipe: denk in het hele project, nooit in hotfixes

Bij elke taak, groot of klein: denk nooit in een geïsoleerde quick fix.
Vraag jezelf af hoe een wijziging bijdraagt aan het grotere geheel, en of
er een structurele oplossing is die het onderliggende probleem wegneemt in
plaats van een symptoom te verhelpen. Dit geldt voor de taakomschrijving die
jij opstelt, en `delegate_task` geeft dit ook automatisch mee aan Ollama,
samen met de volledige inhoud van de repo (niet alleen het ene bestand) —
juist zodat het model dit ook kan doen in plaats van klein te denken.

Dit staat niet haaks op klein en gericht wijzigen. Gebruik het volledige
overzicht om de juiste, onderliggende oplossing te vinden, en implementeer
die daarna met zo min mogelijk voetafdruk: geen bijvangst-refactors, geen
ongevraagde abstracties. Groot denken, klein en precies uitvoeren. Concreet
(bekende valkuilen van LLM-coding, hieronder volledig uitgeschreven — geen
externe bron nodig, dit bestand is zelfvoorzienend):

- **Denk eerst na, verberg geen verwarring.** Maak aannames expliciet. Is
  iets echt onduidelijk of zijn er meerdere redelijke interpretaties, kies
  er dan niet stilzwijgend één: leg het voor aan de gebruiker.
- **Simpel eerst.** De minimale code die het probleem oplost. Geen
  speculatieve flexibiliteit, configuratie-opties of foutafhandeling voor
  scenario's die niet gevraagd zijn. Zou een senior engineer dit
  overbodig ingewikkeld noemen? Vereenvoudig dan.
- **Chirurgisch wijzigen.** Raak alleen aan wat de taak vereist. Geen
  aangrenzende code "verbeteren", geen ongevraagde refactors, bestaande
  stijl volgen ook als je het zelf anders zou doen. Ruim op wat je eigen
  wijziging overbodig maakte; laat bestaande dode code met rust tenzij
  erom gevraagd wordt.
- **Doelgericht met verificatie.** Vertaal een opdracht naar een
  verifieerbaar doel in plaats van een vage instructie: "schrijf een test
  die het probleem aantoont, los dan op tot hij slaagt" in plaats van
  "fix de bug". Dit is precies waar `verify_cmd` in `delegate_task` voor
  is: sterke succescriteria laten Ollama zelfstandig doorlopen tot
  `max_rounds`, zwakke criteria leveren rondjes zonder resultaat op.

Deze vier punten gaan zowel over hoe jij een taak opstelt, als over wat
`delegate_task` automatisch aan Ollama meegeeft.

## Protocol, voor elke taak die code, tests of bestanden oplevert

1. Vat in één zin samen wat er precies gebouwd of aangepast moet worden.
2. Kies een model uit de lijst die je al hebt. Voorkeur voor een
   coder-gericht model (naam bevat bijvoorbeeld "coder", ornith modellen etc); anders het
   grootste/meest capabele model dat er staat. Vergelijk de bestandsgrootte
   van dat model met het geheugen van deze machine (uit de hook): past het
   niet ruim, kies dan een kleiner model of overleg met de gebruiker in
   plaats van het gewoon te proberen. `delegate_task` en `ask_ollama`
   weigeren zelf ook als een model duidelijk te groot is, maar bedenk dit
   liever van tevoren dan dat je het moet laten mislukken. Bepaal ook of
   `think` aan moet: aan bij taken met echte logica of edge cases, uit
   (standaard) bij boilerplate en simpele functies, waar het alleen
   trager maakt zonder iets op te leveren.
3. Roep `delegate_task` aan. Het model krijgt automatisch de bestandsboom
   én de inhoud van de repo te zien (tot een tekenbudget,
   `OLLAMA_CONTEXT_CHARS`), plus apart en expliciet de huidige inhoud van
   `output_file` als dat al bestaat — dat hoef je niet zelf te plakken.
   Geef altijd:
   - een duidelijke, volledige taakomschrijving: wat moet er veranderen,
     waarom, en welke randgevallen. Dat blijkt niet uit de bestanden zelf.
   - `output_file`
   - `verify_cmd` waar mogelijk (`pytest ...`, `python3 -m py_compile ...`,
     een linter). Dit laat Ollama zelf herstellen op fouten, zonder dat jij
     daar tussendoor tokens aan besteedt.
   - `memory_topic`, een kort label voor het onderdeel van de code
     waaraan gewerkt wordt (bijvoorbeeld "auth", "utils"). Roep bij twijfel
     eerst `list_memory_topics` aan en hergebruik een bestaand label in
     plaats van een net iets andere naam te verzinnen.
   Schrijf de code niet zelf, tenzij dit onder de uitzonderingen hieronder
   valt.
4. Lees het resultaat. Geslaagd: klaar, ga door. Na `max_rounds` nog steeds
   mislukt: beoordeel zelf of je het overneemt of teruglegt bij de
   gebruiker.
5. Rapporteer in een paar zinnen wat er gebouwd is en of het slaagde. Geen
   uitgebreide samenvattingen, geen volledige bestandsinhoud tenzij erom
   gevraagd.

Voor kleine, niet-code taken (uitleg, vertaling, tekst opstellen) gebruik je
`ask_ollama` in plaats van dit hele protocol: één prompt, één antwoord.

## Het geheugen onder memory/ is niet voor jou

`delegate_task` laat Ollama-modellen hun eigen aantekeningen bijhouden per
`memory_topic`, onder `memory/*.md`, zodat kennis over een deel van de
codebase blijft hangen tussen taken door in plaats van steeds opnieuw te
beginnen. Dit gebeurt volledig binnen de tool: jij geeft alleen het label
mee, je leest of schrijft die bestanden zelf niet, en je vat de inhoud ook
niet samen. Dat is bewust zo: het is werkgeheugen van de sub-modellen, geen
onderdeel van jouw context. Bemoei je er niet mee, ook niet als je uit
nieuwsgierigheid geneigd bent een keer te kijken wat erin staat.

## Uitzonderingen — dit doe je zelf, niet delegeren

Architectuurkeuzes, alles met veiligheidsimpact, en taken waarvan de spec
echt onduidelijk is. Dit is de uitzondering, niet de standaard.

## Waarom dit vanzelf werkt

Dit bestand wordt door Claude Code automatisch geladen zodra je deze map
opent, en de hook in `.claude/settings.json` draait automatisch bij elke
sessiestart. Er is geen skill, commando of aparte stap nodig: openen en
werken.

## Vereisten

Ollama moet lokaal draaien (`ollama serve` of de Ollama app) met minstens
één gepulled model. Zonder dat meldt de hook dit bij het starten van de
sessie.
