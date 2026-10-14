# Sicherheitsmodell

flakipype führt Pipelines erneut aus und schreibt Code in den Repositories
anderer Leute. Diese Regeln halten das sicher, ob ein Mensch zusieht oder
nicht.

## Pull Requests, nie der Standardbranch

Jede Korrektur ist ein neuer Branch plus ein Pull Request. flakipype pusht
nie auf den Standardbranch, macht nie einen Force-Push und merget nie –
Mergen ist immer die Entscheidung eines Menschen nach einem Review. Das gilt
in jedem Modus und lässt sich nicht wegkonfigurieren.

## Zwei Modi

| Modus | Standard für | Verhalten |
| --- | --- | --- |
| `ask` | den Chat | Jede `write`- und `critical`-Aktion wartet auf deine Bestätigung. |
| `auto` | Headless-Befehle und den systemd-Timer | Aktionen laufen ohne Bestätigung innerhalb der Budgets; Pull Requests werden **nur als Entwurf** geöffnet, und eine Korrektur an ausführbarem Code wird nur vorbereitet und gemeldet. |

Umschalten kannst du im Chat mit `/mode ask|auto` (der Chat startet immer in
`ask`, und `/new` und `/resume` schalten dorthin zurück) oder auf der
Kommandozeile mit `flakipype run --mode auto|ask`. Ohne Fenster kann niemand
bestätigen, daher ist `ask` dort ein Probelauf: Jede `write`- und
`critical`-Anfrage wird mit `report only` beantwortet, und nichts wird
gepusht ([unbeaufsichtigte Läufe](unbeaufsichtigte-laeufe.md)). Jeder Pull
Request von flakipype ist ein Entwurf, in beiden Modi.

Im Modus `auto` pusht flakipype eine Korrektur nur, wenn sie ausschließlich
reine Dokumentation ändert (Markdown, reStructuredText oder AsciiDoc ohne
Code darin) und ihr Diff keine Warnung hat. Jede andere Datei gilt als
ausführbar, im Zweifel auch Konfiguration, Manifeste, `Makefile`,
`conftest.py` und das YAML von Workflows und Actions: Eine solche Korrektur
bereitet `auto` vor und meldet sie, pushen kannst du sie nach Prüfung in
`ask` ([Korrekturen](korrekturen.md#modi)). Der Grund: Ein gepushter Branch
führt seine eigenen Workflows und seinen Code mit den Secrets des
Repositorys aus, bevor ihn jemand geprüft hat, und Logs oder Dateien im
Repository können das Modell zu einer bösartigen Änderung verleiten.

Was davon garantiert ist: nur diese Regel im Code. Die Warnungen sind eine
Musterliste (verbirgt Fehlschläge, greift nach außen, `.github/`), die die
üblichen Formen findet, aber nicht jede; ein zusammengesetzter URL-String
oder `dict(os.environ)` fällt ihr nicht auf. Der Reviewer ist ein Modell und
lässt sich wie der Fixer täuschen. Beide helfen dir beim Prüfen; dass
ausführbarer Code nie ohne eine Person auf einen Branch kommt, hängt an
keinem von beiden.

## Risikostufen, im Code erzwungen

Jedes Werkzeug des Agenten deklariert eine feste Risikostufe; das Modell kann
sie weder wählen noch ändern. Das Policy-Gate in `agent` entscheidet, bevor
ein Werkzeug läuft:

| Stufe | Beispiele | `ask` | `auto` |
| --- | --- | --- | --- |
| `read` | Läufe auflisten, Logs lesen, Dateien lesen, die Kopie des Fixers im Speicher bearbeiten | läuft | läuft |
| `write` | einen Job erneut ausführen, einen Workflow per Dispatch starten, einen Lauf abbrechen | bestätigen | läuft innerhalb des Budgets |
| `critical` | einen Korrektur-Branch pushen und einen Draft-PR öffnen | bestätigen, mit dem Diff | läuft innerhalb des Budgets nur für reine Dokumentation ohne Warnung; sonst wartet die Korrektur auf dich |

Bearbeitungen sind `read`, weil sie nur den Speicher ändern: Nichts wird
geklont oder auf die Platte geschrieben, und nichts verlässt den Rechner vor
dem Push, den du einmal mit dem vollständigen Diff bestätigst.

Das Gate steckt im Code, nicht in Prompts oder der Oberfläche, sodass weder
eine Prompt-Injection noch ein Fehler in der Oberfläche es umgehen kann.

## Bestätigungen zeigen Fakten aus dem Code

Eine Bestätigung zeigt eine Aktionsanfrage, die der Code aus den validierten
Argumenten und den Daten von GitHub baut: Repository, Workflow, Lauf, Ref,
Commit und wie viel vom Budget verbraucht ist. Text, den das Modell
geschrieben hat, erscheint nur in der Bestätigung einer Korrektur, unter den
Fakten bei „written by the model“, neben dem vollständigen Diff und immer
als reiner Text, sodass ein manipuliertes Modell eine Aktion nicht als etwas
anderes tarnen kann. Schreibende Werkzeuge akzeptieren nur Ziele, die der
Scan gefunden oder flakipype selbst gestartet hat. Jede Anfrage wird
zusammen mit deiner Antwort in ein Audit-Log geschrieben, das nur ergänzt
wird. Einzelheiten zu Reruns und Dispatches: [Aktionen](aktionen.md).

## Logs sind Daten

Job-Logs, Workflow-Dateien, Quellcode und Issue- oder PR-Text können Text
enthalten, den irgendwer geschrieben hat. Sie gehen immer als Daten markiert
an das Modell, nie als Anweisungen. Aktionen kommen nur aus deiner Anfrage
oder dem eingestellten Modus. Auch die Wünsche, die das Chat-Modell für eine
Korrektur an den Fixer weitergibt (`instructions`), sind für den Fixer als
Daten markiert, weil das Modell darin Log- oder Repository-Text zitieren
kann.

## Secrets bleiben lokal

Alles, was an das Modell geht, durchläuft zuerst die Maskierung von Secrets
(`agent/masking.py`): der konfigurierte API-Key selbst, Tokens von GitHub,
Anthropic, AWS und Slack, JWTs, Blöcke privater Schlüssel (PEM und PGP),
Zugangsdaten in URLs, Bearer-Tokens und Zuweisungen im Stil von
`password=`/`token:` (auch mit ausgerichteten Leerzeichen) werden zu
`[masked: …]`. Ein Header eines privaten Schlüssels ohne seine END-Zeile
maskiert nur den Schlüsselinhalt danach, nie den Rest des Prompts. Jedes
Muster läuft in linearer Zeit, sodass eine präparierte Log-Zeile die
Maskierung nicht aufhalten kann. GitHubs eigenes `***` bleibt, wie es ist.
Der API-Key wird im Schlüsselbund des Systems gespeichert oder, wo es keinen
gibt, in einer `0600`-Datei; das GitHub-Token bleibt in der eigenen
Anmeldung von `gh`.

## Budgets

Jeder Lauf hat harte, konfigurierbare Limits mit sicheren Standardwerten:
Reruns und Dispatches (10 pro Chat-Sitzung, `actions.max_per_session`),
gleichzeitig beobachtete Läufe, Pull Requests (3 pro Chat-Sitzung,
`fix.max_prs_per_session`), Dateien und Zeilen pro Korrektur, Tokens und
Laufzeit, dazu Schleifenerkennung. Unbeaufsichtigte Läufe haben außerdem
Tageslimits über Läufe hinweg für Pull Requests, Aktionen und Tokens, damit
ein kurzes Timer-Intervall die Limits pro Lauf nicht vervielfachen kann
([unbeaufsichtigte Läufe](unbeaufsichtigte-laeufe.md#budgets)). Ist ein Limit
erreicht, endet der Lauf mit einer Zusammenfassung dessen, was erledigt ist
und was noch fehlt – nie ein halb fertiger Zustand ohne Erklärung. Kein
Limit ist standardmäßig unbegrenzt.

## Geprüfte Downloads

Das `gh`-Binary, das flakipype herunterlädt, wird vor der ersten Nutzung
gegen den SHA-256 aus der Prüfsummendatei des Releases geprüft; bei einer
Abweichung bricht es ab.
