# Den Chat nutzen

Starte `flakipype` ohne Befehl, um den Chat zu öffnen: links das Gespräch,
rechts die Befunde des aktuellen Scans. Stell Fragen in normaler Sprache oder
nutze Slash-Befehle. Scans und Untersuchungen lesen nur. Reruns, Dispatches
und Korrekturen laufen erst, wenn du jede einzelne bestätigst (oder innerhalb
der Budgets in `/mode auto`); eine Korrektur wird ein neuer Branch und ein
Draft-PR, nie eine Änderung am Standardbranch.

Dafür braucht es ein Terminal und ein Modell (siehe
[Modell verbinden](modell-verbinden.md)). Ohne Terminal gibt `flakipype`
stattdessen seine Hilfe aus.

## Eine typische Sitzung

```text
/scan                  scan with the configured window; findings appear on the right
why does the E2E test of Archivist fail?
/why 2                 the verdict for finding 2, with its evidence
/rerun 2               rerun its failed jobs; confirm in the dialog, watch it under Runs
/fix 2                 a fix as a draft pull request; review the diff in the dialog
```

Das Chat-Modell scannt, listet Befunde und startet Untersuchungen selbst, wenn
eine Frage sie braucht. Die Zeile über der Eingabe zeigt, was es gerade tut.
Wählst du in der Seitenleiste einen Befund aus (Pfeiltasten und Enter oder ein
Klick), steht `/investigate N` in der Eingabe, oder `/why N`, sobald er ein
Urteil hat; nichts startet, bevor du Enter drückst, denn Untersuchungen kosten
Tokens.

## Befehle

| Befehl | Wirkung |
| --- | --- |
| `/scan [days]` | Die Workflow-Läufe scannen und die Befunde nummerieren |
| `/findings`, `/flaky` | Die Befunde des aktuellen Scans auflisten |
| `/investigate N [N …]` | Befunde nach Nummer untersuchen; `all` für die instabilen Jobs und wiederkehrenden Fehler; `--fresh` ignoriert gespeicherte Urteile |
| `/why N` | Das Urteil zu Befund N zeigen (untersucht ihn vorher, falls nötig) |
| `/fix N [--fresh]` | Eine Korrektur für Befund N schreiben und sie nach deiner Bestätigung als Draft-PR pushen; `--fresh` verwirft eine Korrektur, die gezeigt, aber nicht gepusht wurde |
| `/rerun N [--all]` | Die fehlgeschlagenen Jobs des neuesten fehlgeschlagenen Laufs von Befund N erneut ausführen; `--all` führt alle Jobs seines neuesten Laufs erneut aus |
| `/dispatch N [ref] [xK]` | Den Workflow von Befund N auf dem Standardbranch oder `ref` starten, K-mal (1–10) |
| `/runs` | Die in dieser Sitzung gestarteten Läufe und ihr Zustand |
| `/cancel R` | Lauf R (`R1`, `R2`, …) abbrechen, der in dieser Sitzung gestartet wurde |
| `/actions` | Die in dieser Sitzung angeforderten Aktionen (Reruns, Dispatches, Abbrüche, Korrekturen) |
| `/mode ask\|auto` | Jede Aktion bestätigen (`ask`, der Standard) oder sie innerhalb der Budgets laufen lassen (`auto`); `/mode` zeigt den Modus |
| `/budget` | In dieser Sitzung verbrauchte Tokens: der Chat, seine Untersuchungen und seine Korrekturen |
| `/sessions` | Die zehn neuesten Sitzungen; die von [unbeaufsichtigten Läufen](zeitgesteuert-ausfuehren.md) enden auf `· run` |
| `/resume N` | Sitzung N fortsetzen; die nächste Aktion scannt erneut, mit Zeitfenster und Repositories der Sitzung auf dem konfigurierten Owner und Host. Die Sitzung eines Laufs öffnet sich als neue Chat-Sitzung mit ihrem Scan, ihren Urteilen und nicht gepushten Korrekturen; ihre Pull Requests bleiben beim Timer |
| `/new` | Eine neue Sitzung starten: der konfigurierte Scan, keine Befunde, ein neuer Token-Zähler |
| `/help` | Die Liste der Befehle |
| `/quit`, `/exit`, Ctrl+Q | Beenden; noch laufende Arbeit stoppt beim nächsten Modellaufruf |

## Sitzungen

Jede Nachricht wird gespeichert: das Gespräch, der Verlauf des Modells, die
Scan-Optionen, die Befundliste, die gestarteten Läufe, das Aktionsbudget,
Korrekturen, die gezeigt, aber nicht gepusht wurden, und geöffnete Pull
Requests mit ihrer Verifikation. Nicht gespeichert werden der Modus und eine
Frage, die gerade beantwortet wird: Eine mittendrin geschlossene Sitzung wird
vor dieser Frage fortgesetzt. Sitzungen liegen in der Cache-Datenbank neben
dem Scan-Cache (siehe [Konfiguration](../reference/konfiguration.md)).

Eine Sitzung, die für einen anderen Owner oder Host gespeichert wurde, wird
auf den konfigurierten fortgesetzt und sagt das. Eine Sitzung, die eine ältere
flakipype-Version oder ein anderes Modell gespeichert hat, wird ohne die
frühere Argumentation des Modells fortgesetzt; das Gespräch selbst bleibt.

## Limits

Jede Frage an das Chat-Modell hat die Limits einer Untersuchung (12 Runden,
200.000 Tokens, 5 Minuten Modellzeit); jede Untersuchung, die es startet, hat
ihre eigenen. Das Token-Limit einer Frage zählt nur, was die Frage dem
Gespräch hinzufügt, nicht den früheren Verlauf, den jede Anfrage erneut
sendet; so antworten auch lange und fortgesetzte Sitzungen weiter. Ist ein
Limit erreicht, sagt der Chat das: Frag in kleineren Schritten, fang mit
`/new` neu an oder erhöhe die Limits im Abschnitt `[agent]` der
Konfiguration. So funktioniert es: [der Agent](../explanation/agent.md).

## Reruns und Dispatches

`/rerun`, `/dispatch` und `/cancel` sowie dieselben Anfragen des
Chat-Modells öffnen einen Dialog, der genau sagt, was laufen wird. **Run**
startet es; **Don't run** (der Standard, auch Escape) tut nichts, und das
Modell fragt in diesem Zug nicht noch einmal. Gestartete Läufe erscheinen
unter **Runs** in der Seitenleiste und werden alle 10 Sekunden abgefragt. Ist
einer fertig, sagt ein Hinweis, wie er ausging, zum Beispiel „R1: E2E passed
on attempt 2 (failed on attempt 1): a proven flaky event“.

Eine Sitzung erlaubt standardmäßig 10 Reruns und Dispatches; `/new` beginnt
eine neue Zählung. Die Limits stehen im Abschnitt `[actions]` der
[Konfiguration](../reference/konfiguration.md). Die Regeln dahinter:
[Aktionen](../explanation/aktionen.md).

## Korrekturen

`/fix N`, oder die Bitte an den Chat, einen Befund zu korrigieren, funktioniert
für Befunde, deren geprüftes Urteil ein instabiler Test, instabile
Infrastruktur oder ein Konfigurationsproblem ist; ohne Urteil wird zuerst
untersucht. Ein Fixer-Agent bearbeitet eine Kopie des Standardbranches im
Speicher, Code prüft den Diff und ein Reviewer liest ihn. Dann zeigt ein
Dialog die Fakten, die Erklärung des Modells und den ganzen Diff: **Push**
legt einen Branch `flakipype/fix-…`, einen signierten Commit und einen
Draft-PR an und führt den Workflow auf dem Fix-Branch erneut aus; **Don't
push** (der Standard, auch Escape) behält die Korrektur in der Sitzung. Bitte
den Chat um Änderungen („keep the assertion“), und er überarbeitet diese
Korrektur; `/fix N --fresh` fängt neu an. Das Ergebnis der Verifikation kommt
als Hinweis und als Kommentar am Pull Request. Mergen bleibt immer dir
überlassen.

Die Statuszeile zeigt den Modus. In `/mode auto` laufen Aktionen ohne Dialog
innerhalb der Budgets, und eine Korrektur mit Warnungen (sie verdeckt
Fehlschläge, greift nach außen oder ändert `.github/`) wird nicht gepusht.
Eine Sitzung erlaubt standardmäßig 3 Pull Requests (`[fix]` in der
[Konfiguration](../reference/konfiguration.md)). So funktioniert es:
[Korrekturen](../explanation/korrekturen.md).
