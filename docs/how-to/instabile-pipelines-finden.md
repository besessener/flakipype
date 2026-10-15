# Instabile Pipelines finden

`flakipype scan` liest die GitHub-Actions-Läufe des konfigurierten Users oder
der Organisation, findet Jobs, die auf demselben Code fehlgeschlagen und
durchgelaufen sind, und sortiert die nach oben, bei denen das immer wieder
passiert. Dafür braucht es ein abgeschlossenes `flakipype setup`; das Modell
wird nicht genutzt.

## Scannen

```bash
flakipype scan
```

Während er läuft, zeigt ein Fortschrittsbalken die Phase: Repositories
auflisten, Workflow-Läufe lesen, fehlgeschlagene Versuche prüfen und die Logs
fehlgeschlagener Jobs lesen. Dann gibt er eine Rangliste aus, die am stärksten
betroffenen Läufe zuerst:

```text
╭─ flakipype scan · octo-org on github.com ─────────────────────────────────────────╮
│ 18 repositories · 1,396 runs · last 30 days (09 Sep – 09 Oct 2026)                  │
│ 1 flaky job in 1 workflow · 4 seen once · 5 recurring errors                         │
╰─────────────────────────────────────────────────────────────────────────────────────╯
  #  Flaky job                                     Runs   Flake rate   Signal
  1  octo-org/app                                  4/509  █░░░  0.8%   ↻ 4 passed on rerun
     CI › test › E2E (Electron under Xvfb)
     timeout ×4 tests/e2e/scan.spec.ts:N:N › … toHaveCount(expected) failed
     latest failure ↗
```

- **Runs**: Läufe mit einem instabilen Fehlschlag dieses Jobs / fertige Läufe
  seines Workflows.
- **Signal**: `↻ passed on rerun` (stark) oder `≡ same commit passed`
  (mittel); siehe
  [wie Flakiness erkannt wird](../explanation/flake-erkennung.md).
- **Signaturen**: der Fehler hinter den Fehlschlägen, über Läufe hinweg
  gruppiert, mit einer Kategorie wie Timeout, Netzwerk oder Abhängigkeiten.
- **latest failure ↗** ist ein Terminal-Hyperlink zum Job auf GitHub.

Unter der Rangliste folgen bis zu drei weitere Abschnitte:

- **Seen once**: bewiesene Ereignisse in nur einem Lauf. Kann ein Ausfall
  sein oder eine Korrektur außerhalb des Codes mit anschließendem Rerun; zählt
  nicht als instabil.
- **Fixed**: in mehreren Läufen fehlgeschlagen, danach lief der Workflow
  durchgehend durch. Ein echter Fehler, der behoben wurde; nicht instabil.
- **Recurring errors**: derselbe Fehler in mehreren Läufen (beliebiger
  Branch) ohne Beweis. Kann ein instabiler Test sein, den niemand erneut
  ausgeführt hat, oder ein echter Fehler, der wieder auftritt.

Warum diese getrennt bleiben:
[wie Flakiness erkannt wird](../explanation/flake-erkennung.md).

Jeder Eintrag hat eine Nummer (**#**), über alle Abschnitte hinweg gezählt.
Mit ihr lässt du den Agenten einen Befund erklären:
`flakipype investigate --finding 3`; siehe
[Befunde untersuchen](befunde-untersuchen.md).

## Eingrenzen oder erweitern

```bash
flakipype scan --days 7                 # look back 7 days instead of 30
flakipype scan --repo app --repo docs   # only these repositories
flakipype scan --owner other-org        # another user or organisation
flakipype scan --max-logs 200           # read more logs this time
flakipype scan --min-runs 3             # need 3 runs before calling a job flaky
```

Passt ein Name bei `--repo` auf kein Repository des Owners (vertippt,
archiviert oder ein Fork), nennt der Scan ihn unter den Hinweisen; der Rest
läuft normal weiter.

Die Standardwerte kommen aus dem Abschnitt `[scan]` der
[Konfiguration](../reference/konfiguration.md).

## In Skripten nutzen

```bash
flakipype scan --json > flaky.json
jq '.jobs[] | select(.status == "flaky") | .repository + " " + .job' flaky.json
```

Das JSON geht auf die Standardausgabe, der Fortschritt auf die
Standardfehlerausgabe. Das Format beschreibt die
[Referenz zum Scan-JSON](../reference/scan-json.md).

| Exit-Code | Bedeutung |
| --- | --- |
| 0 | Scan fertig (egal, ob instabile Jobs gefunden wurden) |
| 1 | Vorzeitig abgebrochen (Rate Limit), oder GitHub ließ sich gar nicht lesen |
| 2 | Nicht eingerichtet: keine Konfiguration, kein Owner oder kein `gh` |

## Wiederholte Scans sind schnell

Jobs abgeschlossener Versuche und die Ergebnisse gelesener Logs ändern sich
nie, deshalb speichert flakipype sie in
`~/.local/share/flakipype/cache.sqlite3`. Ein zweiter Scan listet nur die
Läufe erneut auf. Jobs werden je Scan für höchstens `max_job_reads` Versuche
gelesen und Logs höchstens `max_log_downloads`-mal heruntergeladen, die
neuesten instabilen Fehlschläge zuerst; der nächste Scan macht dort weiter,
wo der letzte aufgehört hat, und die *Notes* sagen, wie viele noch fehlen.
Die Cache-Datei zu löschen kostet für Scan-Daten nur Zeit, löscht aber auch
die Chat- und Lauf-Sitzungen, ausstehende Verifikationen und das
Audit-Protokoll hinter den Tageslimits von `flakipype run`; siehe
[Konfiguration](../reference/konfiguration.md).

## Wenn etwas schiefgeht

- **Ein Repository ließ sich nicht lesen** (zum Beispiel Actions
  abgeschaltet): Es steht unter *Notes*, der Rest des Scans läuft weiter.
- **Rate Limit**: Der Scan stoppt, zeigt, was er bis dahin gefunden hat, und
  beendet sich mit 1. Starte ihn später erneut; bereits zwischengespeicherte
  Arbeit wird nicht wiederholt.
- **Anmeldung nicht mehr gültig**: Führe `flakipype setup` aus und melde dich
  erneut an.
- **Logs abgelaufen**: GitHub bewahrt Logs standardmäßig 90 Tage auf. Solche
  Fehlschläge werden weiterhin gezählt, nur ohne Signatur.
