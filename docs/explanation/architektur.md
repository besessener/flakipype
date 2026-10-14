# Architektur

flakipype ist ein einzelnes Python-Paket (`src/flakipype/`), aufgeteilt in
Unterpakete nach Zuständigkeit. import-linter (`uv run poe arch`) erzwingt
die Schichten: Eine höhere Schicht darf eine niedrigere importieren, nie
umgekehrt, und Pakete auf derselben Schicht importieren einander nicht. Der
Vertrag ist erschöpfend, ein neues Unterpaket muss also eine Schicht
bekommen. Zwei weitere Verträge halten `flaky` rein (kein `os`, `pathlib`,
`subprocess`, `sqlite3`, `socket`, `time`, `httpx2`, `anthropic` oder
`config`) und erlauben `subprocess` nur in `github` und `setup/daemon.py`.
Die Uhr liest nur `cli/wiring.py`: ruff verbietet `datetime.now`,
`date.today`, `time.time` und ihre Verwandten überall sonst (`TID251`), alle
anderen bekommen `now` als Parameter.

```text
cli                               Typer entry point, composition root (cli/wiring.py)
 ├─ tui                           Textual: setup wizard, chat window, confirmation dialog
 └─ unattended                    flakipype run: steps in code, daily limits, report
     └─ investigate               scan and investigate findings; verdict cache; the chat's workspace and commands
         └─ fix                   fixes: diff checks, delivery, pull request texts, verification, session state
             └─ actions           reruns, dispatches, cancels: targets, budget, audit, watched runs
                 ├─ agent         investigator, fixer, reviewer, chat orchestrator, working copy, tools, gate, budgets, masking
                 ├─ setup         setup and health checks (wizard, headless, doctor); systemd units
                 └─ scan          scan an owner: fetch, cache, detect, rank
                     ├─ llm       Anthropic Messages API client
                     ├─ github    gh CLI wrapper; Actions, runs, commits, files, branches, pull requests; downloads gh
                     └─ store     SQLite cache, chat sessions and the action audit log
                         ├─ flaky   pure detection, scoring, findings, log excerpts
                         └─ config  settings and secret storage
```

## Pakete

- **`flaky`** ist rein. Es bekommt Läufe, Jobs und Log-Text als Werte und
  liefert instabile Fehlschläge, Rangfolgen und Fehlersignaturen. Kein
  Netzwerk, kein Dateisystem, kein `gh`, keine Datenbank, keine Uhr – die
  aktuelle Zeit ist ein Parameter. So bleibt die Kernlogik deterministisch
  und lässt sich leicht erschöpfend testen. Wie es entscheidet:
  [Flake-Erkennung](flake-erkennung.md).
- **`config`** liest und schreibt Einstellungen unter
  `$XDG_CONFIG_HOME/flakipype` und hält Secrets im Schlüsselbund des Systems;
  auf Rechnern ohne Oberfläche weicht es auf eine `0600`-Datei aus.
- **`github`** ist die einzige Stelle, die `gh` ausführt. Liegt kein
  passendes `gh` im `PATH`, lädt es das Release-Tarball für die Architektur
  des Rechners herunter, prüft dessen SHA-256 gegen die Release-Prüfsummen
  und installiert es unter `$XDG_DATA_HOME/flakipype/bin`. Unterstützt
  github.com und GitHub Enterprise Server (`GH_HOST`). flakipype nutzt die
  `gh`-Anmeldung des Benutzers mit, statt ein eigenes Token zu halten. Die
  Release- und Versionslogik (`release.py`) ist rein; der Download läuft über
  `httpx2`, denselben HTTP-Stack, den das `anthropic`-SDK nutzt.
  `actions.py` liest Repositories, Läufe, Jobs und Logs mit `gh api`,
  validiert die Antworten mit pydantic-Modellen (`payloads.py`) und macht aus
  `gh`-Fehlern typisierte Exceptions (Rate Limit, Authentifizierung, andere).
  `runs.py` (`RunControl`) führt Läufe erneut aus, startet sie per Dispatch,
  bricht sie ab und liest ihren Zustand. `pulls.py` (`PullRequests`) liest
  die Push-Berechtigung, den Dateibaum und exakte Dateibytes, legt einen
  Branch nur dort an, wo keiner existiert, committet über GraphQL
  `createCommitOnBranch` (von GitHub signiert, mit dem erwarteten
  Head-Commit), öffnet Pull Requests immer als Entwurf und kommentiert.
- **`llm`** kapselt das offizielle `anthropic`-SDK mit konfigurierbarer
  Basis-URL, sodass derselbe Code mit api.anthropic.com und Azure AI Foundry
  spricht (gewählt am Hostnamen). Verbindungsprobleme werden kategorisiert
  (`ConnectionProblem`), jedes mit einem nächsten Schritt für den Benutzer.
- **`setup`** ist der Anwendungsdienst hinter dem Assistenten, dem
  Headless-Setup und `doctor`: Er validiert Eingaben, speichert Einstellungen
  und den Schlüssel, findet oder installiert `gh` und prüft die Anmeldung.
  Seine Kollaborateure (Secret-Speicher, `gh`-Provider, Modellprüfung) werden
  hineingereicht, sodass Tests sie durch Fakes ersetzen.
- **`scan`** ist der Anwendungsdienst hinter `flakipype scan` (und später den
  Scan-Werkzeugen des Agenten): Er listet Läufe, holt Jobs für Versuche, die
  instabil sein können, und für den letzten Versuch fehlgeschlagener Läufe,
  liest eine begrenzte Zahl von Logs und liefert die Einordnungen (instabil,
  einmal gesehen, behoben) plus wiederkehrende Fehler ohne Nachweis. Ein
  Rate Limit, das Zeitlimit eines unbeaufsichtigten Laufs oder ein GitHub,
  das mehrmals hintereinander nicht antwortet, stoppt ihn vorzeitig mit
  einem Bericht dessen, was gefunden wurde; andere Fehler überspringen den
  Eintrag und werden aufgelistet. Der
  Fortschritt wird als Ereignisse gemeldet, sodass CLI und TUI ihn auf ihre
  eigene Weise zeigen können.
- **`store`** verwaltet den SQLite-Cache unter `$XDG_DATA_HOME/flakipype`:
  Jobs abgeschlossener Versuche und Log-Ergebnisse, die sich nie ändern.
  Schema-Migrationen werden nur angehängt (`PRAGMA user_version`) und laufen
  in einer Transaktion unter der Schreibsperre, sodass ein abgebrochenes oder
  gleichzeitiges Öffnen nie ein halbes Schema hinterlässt;
  zwischengespeicherte Signaturen tragen die Version des
  Signaturalgorithmus und werden neu berechnet, wenn er sich ändert. Lauflisten werden nicht zwischengespeichert:
  Sie abzurufen ist günstig, und sie ändern sich ständig. Chat- und
  Laufsitzungen werden ebenfalls dort gespeichert, als ein JSON-Dokument pro
  Sitzung, ebenso das nur ergänzte Audit-Log der Aktionsanfragen
  (`audit.py`). Die Datenbank nutzt das WAL-Journal von SQLite, sodass Chat
  und Lauf sie gemeinsam nutzen können; `lock.py` hält einen zweiten
  `flakipype run` über die eigene Dateisperre von SQLite fern, die das
  Betriebssystem freigibt, wenn ein Lauf abstürzt.
- **`agent`** untersucht einen Befund: eine Werkzeugschleife des
  Investigators über die Messages API, eine deterministische Zitatprüfung,
  einen Durchgang des Reviewers und höchstens eine Überarbeitung
  ([Der Agent](agent.md)). Jedes Werkzeug deklariert eine Risikostufe und
  läuft nur durch das Policy-Gate ([Sicherheitsmodell](sicherheitsmodell.md));
  alles, was an das Modell geht, wird zuerst maskiert. Er weiß nichts vom
  Scan-Dienst: Er bekommt ein `Finding` und die `Evidence` des Scans als
  Werte. Der Chat-Orchestrator (`orchestrator.py`) ist ebenfalls eine
  Werkzeugschleife; seine Werkzeuge rufen ein `Workspace`-Protokoll auf, das
  `investigate` implementiert. Für Korrekturen hat er den Fixer
  (`fixer.py`) mit Bearbeitungswerkzeugen (`fix_tools.py`) auf einer
  Arbeitskopie eines Commits im Speicher (`workcopy.py`), und
  `fix_pipeline.py` lässt Fixer und Reviewer mit höchstens einer
  Überarbeitung laufen ([Korrekturen](korrekturen.md)). Investigator und
  Fixer teilen sich eine Werkzeugschleife (`tool_loop.py`): aufrufen,
  Werkzeuge ausführen, die Abgabe prüfen, höchstens zweimal korrigieren;
  jeder bringt sein eigenes Abgabewerkzeug und seine Prüfungen mit.
- **`actions`** bereitet die Reruns, Dispatches und Abbrüche des Chats für
  das Policy-Gate vor: Es prüft die Ziele gegen die Befunde des aktuellen
  Scans, liest die Workflow-Datei, um `workflow_dispatch` zu prüfen,
  erzwingt das Sitzungsbudget, zeichnet jede Anfrage im Audit-Log auf und
  beobachtet gestartete Läufe (Polling, Hinweise bei Abschluss,
  Sitzungszustand). Einen bestätigten Rerun oder Dispatch auf GitHub zu
  starten, liegt in `starting.py`. Seine GitHub-Kollaborateure sind
  Protokolle, die `github` implementiert ([Aktionen](aktionen.md)).
- **`fix`** macht aus einem geprüften Urteil einen Draft-PR für den Chat: Es
  lehnt Befunde ab, die sich nicht korrigieren lassen, prüft den
  Push-Zugriff und offene Pull Requests von flakipype, lässt den Fixer über
  eine übergebene Funktion laufen, prüft den Diff im Code (`checks.py`),
  bereitet die eine Bestätigung mit dem Diff vor, liefert Branch, Commit und
  Draft-PR aus (`delivery.py`), prüft den Korrektur-Branch und kommentiert
  das Ergebnis (`verify.py`) und hält Vorschläge, geöffnete Pull Requests und
  das Pull-Request-Budget als Sitzungszustand ([Korrekturen](korrekturen.md)).
- **`investigate`** führt einen Scan aus, nummeriert die Befunde, wählt die
  angeforderten aus, lässt Untersuchungen parallel unter einem gemeinsamen
  Laufbudget laufen und speichert abgeschlossene Urteile im Cache, bis ein
  Befund einen neueren Fehlschlag hat. Für den Chat hält es den aktuellen
  Scan und seine Urteile (`workspace.py`) und verarbeitet Slash-Befehle und
  Sitzungen (`chat.py`), unabhängig von Textual.
- **`tui`** stellt den Einrichtungsassistenten und den Chat mit Textual dar.
  Es spricht mit `setup` und `investigate` und führt `gh` oder das Modell nie
  selbst aus; langsame Arbeit läuft in Worker-Threads, damit die Oberfläche
  reaktionsfähig bleibt. Das Chat-Fenster beantwortet die
  Bestätigungsanfragen des Gates mit einem Dialog (mit dem Text des Modells
  und dem Diff bei einer Korrektur), zeigt den Modus in seiner Statuszeile
  und fragt gestartete Läufe und Korrekturprüfungen im Hintergrund ab.
- **`unattended`** (auf der Schicht von `tui` und unabhängig davon) führt
  `flakipype run` ohne Fenster aus: Scannen, Untersuchen, Korrigieren und
  Prüfen in festen Schritten auf dem Workspace des Chats, jede Aktion über
  das `HeadlessGate`, mit Tageslimits über Läufe hinweg (`limits.py`), den
  aus dem letzten Lauf übernommenen Pull Requests (`carry.py`) und einem
  Bericht, den die CLI ausgibt
  ([unbeaufsichtigte Läufe](unbeaufsichtigte-laeufe.md)). Die systemd-Units
  erzeugt und installiert `setup` (`daemon.py`).
- **`cli`** verbindet alles: `cli/wiring.py` ist die einzige Stelle, die die
  Konfiguration von flakipype aus der Umgebung liest und echte
  Kollaborateure baut. `GhCli` reicht die Prozessumgebung (mit gefiltertem
  `PATH`) an `gh` weiter. `cli/readiness.py` enthält, was ein Befehl braucht,
  bevor er startet, und `cli/errors.py` die Exit-Codes und Fehlerzeilen, die
  jeder Headless-Befehl auf stderr ausgibt. Headless-Befehle umgehen `tui`,
  aber nicht `setup` oder `agent`.

## Datenfluss

1. **Scan**: `github` listet Repositories und Workflow-Läufe im
   konfigurierten Zeitfenster (Standard 30 Tage); `flaky` wählt die Versuche
   aus, die einen Blick wert sind, deren Jobs und Logs `github` dann holt und
   `store` zwischenspeichert.
2. **Fakten**: `flaky` behält Fehlschläge mit Nachweis (beim Rerun
   bestanden, derselbe Commit bestanden), entscheidet instabil / einmal
   gesehen / behoben, listet wiederkehrende Fehler ohne Nachweis auf und
   extrahiert Fehlersignaturen. Deterministisch und ohne Modellkosten.
3. **Urteil**: Der Agent untersucht Befunde mit Werkzeugen (aufbereitete
   Log-Auszüge, Laufverlauf, Commit-Diffs, Dateien), als Daten markiert, und
   liefert Urteile mit zitierten Belegen, die ein Durchgang des Reviewers
   prüft.
4. **Korrektur** ([Korrekturen](korrekturen.md)): Der Agent bearbeitet eine
   Kopie des Repositorys im Speicher, Code prüft den Diff, ein neuer Branch
   mit einem signierten Commit und ein Draft-PR werden über die GitHub-API
   angelegt, und Reruns des Korrektur-Branches werden mit der Flake-Rate des
   Standardbranches verglichen.
