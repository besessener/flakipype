# Aktionen: Reruns, Dispatches und die Live-Ansicht der Läufe

> Stand: umgesetzt.

Scans und Untersuchungen lesen nur. Manche Fragen lassen sich nur
beantworten, indem CI noch einmal läuft: Besteht der fehlgeschlagene E2E-Job,
wenn derselbe Commit erneut ausgeführt wird? Wie oft schlägt der Workflow
fehl, wenn er fünfmal hintereinander läuft? Der Chat kann Läufe starten, um
das zu beantworten. Du bestätigst jeden einzelnen, und der Chat zeigt sie
live, solange sie laufen.

## Umfang

- **Enthalten**: im Chat die fehlgeschlagenen Jobs eines Laufs erneut
  ausführen, einen ganzen Lauf erneut ausführen, einen Workflow per Dispatch
  (`workflow_dispatch`) auf einem vorhandenen Branch oder Tag starten und
  Läufe abbrechen, die flakipype gestartet hat. Eine Live-Liste zeigt sie,
  ein Audit-Log zeichnet sie auf, und ein Budget begrenzt sie.
- **Nicht enthalten**: Headless-Aktionen; unbeaufsichtigte Läufe führen nur
  die eigenen Korrektur-Branches von flakipype erneut aus, siehe
  [unbeaufsichtigte Läufe](unbeaufsichtigte-laeufe.md). Code, Branches oder
  Pull Requests ändern und `/mode auto` im Chat behandelt
  [Korrekturen](korrekturen.md); im Modus `auto` laufen diese Aktionen ohne
  Dialog innerhalb des Budgets.

Keine dieser Aktionen schreibt auf einen Branch: Reruns und Dispatches führen
den Code aus, der schon da ist. Sie kosten CI-Minuten, keine Modell-Tokens.
In Repositories mit Deployments kann ein Dispatch alles tun, was der Workflow
tut; deshalb braucht jeder deine Bestätigung.

## Die Aktionen

| Aktion | Werkzeug / Befehl | GitHub-API (über `gh api`) | Risiko |
| --- | --- | --- | --- |
| Die fehlgeschlagenen Jobs eines Laufs erneut ausführen | `rerun_failed` · `/rerun N` | `POST …/actions/runs/{id}/rerun-failed-jobs` | `write` |
| Einen ganzen Lauf erneut ausführen | `rerun_run` · `/rerun N --all` | `POST …/actions/runs/{id}/rerun` | `write` |
| Einen Workflow per Dispatch auf einer Ref starten | `dispatch` · `/dispatch N [ref] [xK]` | `POST …/actions/workflows/{file}/dispatches` | `write` |
| Einen von flakipype gestarteten Lauf abbrechen | `cancel` · `/cancel R` | `POST …/actions/runs/{id}/cancel` | `write` |
| Die gestarteten Läufe zeigen | `watched_runs` · `/runs` | keine; der Zustand kommt aus dem Polling | `read` |
| Die Aktionsanfragen dieser Sitzung auflisten | `/actions` | keine; aus dem Audit-Log gelesen | – |

`N` ist eine Befundnummer, wie überall im Chat:

- `/rerun N` führt den neuesten Lauf des Befunds erneut aus, der noch
  fehlschlägt.
- `/rerun N --all` führt den neuesten Lauf des Befunds erneut aus, egal mit
  welchem Ergebnis.
- `/dispatch N` startet den Workflow des Befunds auf dem Standardbranch des
  Repositorys oder auf `ref`, wenn du eine angibst. `xK` wiederholt das
  K-mal (1–10), und jede Wiederholung zählt gegen das Budget. Eine Branch-
  oder Tag-Ref wird zuerst zu ihrem Commit aufgelöst; einem annotierten Tag
  wird bis zu dem Commit gefolgt, auf den er zeigt, und diesen zeigen der
  Dialog, das Audit-Log und die Liste Runs.

`R` ist die kurze Nummer, die ein gestarteter Lauf in der Liste Runs bekommt
(`R1`, `R2`, …). Die Werkzeuge des Modells können auch eine bestimmte Lauf-ID
nennen, aber nur die eines Laufs des Befunds.

Das Modell bekommt dieselben Werkzeuge. Die Prüfungen laufen im Code (Paket
`actions`), sodass das Modell die Werkzeuge nicht auf beliebige Ziele richten
kann:

- **Nur, was der Scan gefunden hat.** Reruns akzeptieren nur Läufe des
  Befunds im aktuellen Scan. Dispatches akzeptieren nur den Workflow des
  Befunds und nur, wenn seine Workflow-Datei an dieser Ref
  `workflow_dispatch` ohne Pflichteingaben ohne Standardwert deklariert. Die
  Datei wird mit einem YAML-Parser gelesen. flakipype sendet nie Eingaben.
- **Nur abgeschlossene Läufe.** GitHub führt nur abgeschlossene Läufe erneut
  aus. Ein Rerun fehlgeschlagener Jobs braucht einen Lauf, dessen neuester
  Versuch fehlgeschlagen ist.
- **Nur vorhandene Refs.** Die Ref muss ein vorhandener Branch oder Tag des
  Repositorys sein. flakipype legt nichts an.
- **Nur eigene Läufe werden abgebrochen.** Abbrechen akzeptiert nur Läufe,
  die in dieser Sitzung gestartet wurden und noch nicht fertig sind. Läufe,
  die jemand anderes gestartet hat, bricht es nie ab.
- **Nur der konfigurierte Owner und Host.**

## Bestätigung

Der Chat bleibt im Modus `ask`, also wartet jede `write`-Aktion auf dich.
Jedes Aktionswerkzeug gibt eine *vorbereitete Aktion* zurück: eine
Aktionsanfrage plus den Code, der sie ausführt. Das Gate reicht die Anfrage
an die Bestätigungsfunktion weiter und führt die Aktion nur bei „ja“ aus.
Der Code baut die Anfrage aus den validierten Argumenten und den Antworten
von GitHub, nie aus Text, den das Modell geschrieben hat:

```text
╭──────────────────────────────────────────────────────────────────────────╮
│ Rerun failed jobs?                                                       │
│                                                                          │
│ octo-org/app · CI · run 6 (attempt 1 → 2)                                │
│ commit 3f2a9c1 on main · failed jobs: lint                               │
│ Actions this session: 1 of 10                                            │
│                                                                          │
│                          Run           Don't run                         │
╰──────────────────────────────────────────────────────────────────────────╯
```

**Don't run** hat den Fokus, und auch Escape lehnt ab. Mit `/mode auto`
erscheint kein Dialog, und die Aktion läuft innerhalb des Budgets. Der Agent
wartet, bis du antwortest. Eine abgelehnte Anfrage geht als vom Benutzer
abgelehnt an das Modell zurück. Für den Rest dieser Runde bekommt das Modell
für jedes andere `write`-Werkzeug einen Fehler, damit es in derselben Frage
nicht noch einmal fragen kann. Auch ein `/rerun` oder `/dispatch`, das du
selbst tippst, zeigt den Dialog: Das Gate weiß nicht, wer gefragt hat, und
das ist so gewollt.

Im Code ist die Risikostufe eines Werkzeugs fest. Ein `write`- oder
`critical`-Werkzeug, das statt einer vorbereiteten Aktion reinen Text
zurückgibt, ist ein Programmierfehler (`TypeError`), sodass kein Werkzeug das
Gate umgehen kann. Ohne Fenster, in dem gefragt werden kann
(Headless-Befehle), lehnt die Bestätigungsfunktion alles ab.

## Budget

| Limit | Standard | Einstellung |
| --- | --- | --- |
| Reruns und Dispatches pro Chat-Sitzung | 10 | `actions.max_per_session` (1–100) |
| Gleichzeitig beobachtete Läufe | 10 | `actions.max_watched` (1–50) |
| Wie lange ein Lauf beobachtet wird | 6 Stunden | `actions.watch_hours` (1–24) |

Jeder gestartete Rerun und jede gestartete Wiederholung eines Dispatches
zählt einmal; Abbrechen zählt nicht. Der Zähler gehört zur Sitzung, also
setzt `/resume` ihn nicht zurück, `/new` aber schon. Eine Anfrage, die nicht
ins Budget oder ins Beobachtungslimit passt, scheitert mit einer Meldung,
bevor ein Dialog erscheint, zum Beispiel
„Action budget used up: 10 of 10 reruns and dispatches in this session“.
Das Budget wird noch einmal geprüft, wenn die bestätigte Aktion startet, weil
der Prüf-Rerun einer Korrektur die letzten Plätze verbraucht haben kann,
während der Dialog offen war; die Aktion läuft dann nicht und wird als
`not run` protokolliert. Scheitert ein wiederholter Dispatch mittendrin,
bleiben die Läufe, die schon gestartet sind, gezählt und beobachtet, und die
Antwort und der Audit-Eintrag nennen sie neben dem Fehler.

## Die Live-Ansicht der Läufe

Die Seitenleiste zeigt unter den Befunden eine zweite Liste, **Runs**, sobald
ein Lauf gestartet wurde. Jeder Lauf zeigt sein Repository, seinen Workflow,
seine Bezeichnung und seinen Zustand: `queued`, `in progress` mit
fehlgeschlagenen (`✗`) und laufenden (`⟳`) Jobs, `✓ passed`, `✗ failed`,
`cancelled` oder `no longer watched`.

```text
Runs
R1 app · CI #6/2
  ✓ passed
R2 app · E2E dispatch 1/3
  in progress · e2e ⟳
R3 app · E2E dispatch 2/3
  queued
```

- Unfertige Läufe werden im Hintergrund alle 10 Sekunden abgefragt, über
  dieselbe serielle `gh`-Warteschlange wie alles andere. Ein Lauf wird
  abgefragt, bis er fertig ist oder seine Beobachtungszeit abgelaufen ist.
  Ein Lauf, der erst nach seiner Beobachtungszeit zum ersten Mal abgefragt
  wird (einer, den eine spätere Sitzung übernommen hat), wird trotzdem
  einmal gelesen, sodass ein Lauf, der inzwischen fertig ist, sein Ergebnis
  behält.
- **Den Lauf finden.** Ein Rerun behält seine Lauf-ID und wartet auf die
  nächste Versuchsnummer. Ein Dispatch bekommt die ID des neuen Laufs von
  GitHub. Auf Versionen von GitHub Enterprise Server, die sie nicht
  zurückgeben, sucht flakipype seit dem Dispatch nach
  `workflow_dispatch`-Läufen auf dieser Ref vom angemeldeten Benutzer und
  nimmt den ältesten, den kein anderer gestarteter Lauf beansprucht hat.
- **Wenn ein Lauf fertig ist**, sagt das ein Hinweis in der Unterhaltung, zum
  Beispiel
  „R1: E2E passed on attempt 2 (failed on attempt 1): a proven flaky event“.
  `watched_runs` gibt dem Modell dieselben Fakten. Der nächste Scan erfasst
  den Lauf wie jeden anderen, sodass ein bestandener Rerun ohne neue
  Erkennungsregeln zum Beleg für Instabilität wird.
- Sind alle Läufe eines wiederholten Dispatches fertig, fasst ein Hinweis sie
  zusammen: „E2E on 3f2a9c1: 2 of 3 passed“.
- Ein Rate Limit pausiert die Runde: Die Läufe zeigen
  „waiting for GitHub's rate limit“, und die nächste Abfrage versucht es
  erneut. Andere Fehler erscheinen neben dem Lauf und halten die anderen
  nicht auf.

Gestartete Läufe, ihr Zustand und der Budgetzähler werden in der Sitzung
gespeichert. Eine fortgesetzte Sitzung fragt die Läufe ab, die noch nicht
fertig sind.

## Audit-Log

Jede Aktionsanfrage wird in der Cache-Datenbank gespeichert (Tabelle
`action_log`), ob sie ausgeführt wurde oder nicht. Jeder Eintrag enthält
Zeit, Sitzung, Werkzeug, wer gefragt hat (`model`, `command` oder `run` für
[unbeaufsichtigte Läufe](unbeaufsichtigte-laeufe.md)), den Anfragetext, die
Antwort (`confirmed`, `declined`, `auto`, `not run in auto
mode` oder `report only`), das Ergebnis (die Antwort von GitHub oder den
Fehler) und die Lauf-ID. Die Reruns und Dispatches, die eine Korrektur
prüfen, werden ebenfalls aufgezeichnet, als `verify_rerun` und
`verify_dispatch` mit der Antwort `covered by the push`, auch wenn GitHub sie
ablehnt (`failed: …`).
`/actions` listet die Einträge dieser Sitzung. Das Log wird nur ergänzt:
Nichts in flakipype ändert oder löscht es, außer dem Löschen der
Cache-Datei.

## Berechtigungen und Fehler

Erneut ausführen, Dispatches und Abbrechen brauchen Schreibzugriff auf
Actions. Ein klassisches Token oder ein `gh auth login` braucht den Scope
`repo`, der Standard ist. Ein Fine-grained Token braucht
**Actions: read and write**. `doctor` meldet fehlende Scopes, wo GitHub sie
anzeigt (klassische Tokens), mit einem `gh auth refresh`-Befehl, der das
`gh` nennt, das flakipype verwendet. Sonst erklärt ein `403`, welche
Berechtigung fehlt, und nichts wird wiederholt. Ein `403` wegen des Rate
Limits von GitHub sagt stattdessen das und bittet, es nach dem Zurücksetzen
des Limits erneut zu versuchen.

Andere GitHub-Fehler werden zu Werkzeugfehlern mit der Meldung von GitHub,
damit das Modell und du seht, was schiefgegangen ist.

## Sicherheit, zusammengefasst

- Kein Branch, Tag, keine Datei und kein Pull Request wird angelegt oder
  geändert. Die Regel zum Standardbranch bleibt unberührt.
- Jede Aktion wird in einem Dialog bestätigt. Das Gate erzwingt das im Code,
  und der Dialogtext kommt aus dem Code.
- Ziele sind auf das beschränkt, was der Scan gefunden und flakipype
  gestartet hat.
- Ein Budget pro Sitzung, ein Beobachtungslimit, ein Audit-Log und
  Schleifenerkennung wie bei jedem Werkzeug.
- Logs erneut ausgeführter Jobs sind Daten, wie alle Logs.

## Tests

- Das Gate: Anfragen pro Risikostufe, Bestätigen und Ablehnen, keine zweite
  Anfrage nach einer Ablehnung und schreibende Werkzeuge, die Text
  zurückgeben.
- Das Paket `actions` gegen ein GitHub im Speicher: Ziele außerhalb des
  Scans, Refs, per Dispatch startbare Workflows, das Budget und das
  Beobachtungslimit, Audit-Einträge, Polling mit einer Fake-Uhr
  (Zustandswechsel, gestartete Läufe ohne ID, Beobachtungszeit, Rate Limits)
  und Sitzungszustand.
- `RunControl` gegen den `gh`-Stub mit aufgezeichneten Antworten: Reruns,
  Dispatch (mit Lauf-ID und ohne, plus die Suche), Abbrechen, `403`.
- Die Chat-Befehle und die Werkzeugnutzung des Modells mit dem vorgegebenen
  Fake-Modell, einschließlich einer abgelehnten Anfrage.
- Der Bestätigungsdialog und die Liste Runs: Pilot-Tests und Snapshots.
