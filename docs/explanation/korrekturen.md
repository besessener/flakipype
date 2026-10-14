# Korrekturen: vom Urteil zum Draft-Pull-Request

> Stand: umgesetzt.

Eine Untersuchung erklärt einen instabilen Befund und schlägt eine Korrektur
vor. flakipype lässt den Agenten diese Korrektur schreiben, zeigt dir den
Diff, pusht ihn als neuen Branch, öffnet einen Draft-Pull-Request und führt
den Korrektur-Branch erneut aus, um zu prüfen, ob sie hält. Das Mergen bleibt
deine Entscheidung.

## Umfang

- **Enthalten**: `/fix N` und ein Werkzeug `fix` im Chat; ein Fixer-Agent,
  der eine Kopie des Repositorys im Speicher bearbeitet; deterministische
  Prüfungen des Diffs; eine Bestätigung für Push, Pull Request und
  Verifikation; ein Branch plus ein signierter Commit über die API von
  GitHub; ein Draft-Pull-Request; Verifikations-Reruns mit einem
  Ergebniskommentar; `/mode ask|auto` im Chat.
- **Nicht enthalten**: headless Korrekturen, die stattdessen `flakipype run`
  macht (siehe [unbeaufsichtigte Läufe](unbeaufsichtigte-laeufe.md)); Forks
  (eine Korrektur braucht Push-Zugriff auf das Repository); Dateien löschen;
  einen Pull Request aktualisieren, nachdem er geöffnet wurde; Mergen, niemals.

## Der Ablauf

```text
/fix 2 ──▶ verdict? ──no──▶ investigate first
              │ flaky_test · flaky_infrastructure · configuration, reviewed
              ▼
        ┌───────────┐  read tools + edit tools on an in-memory copy
        │  Fixer    │  of the default branch at one pinned commit
        └─────┬─────┘
              ▼ submit_fix(title, explanation)
        ┌───────────┐
        │ Checks    │  size caps, parse, warnings (code)
        └─────┬─────┘
              ▼
        ┌───────────┐
        │ Reviewer  │  does the diff fix the cause without hiding it? (model)
        └─────┬─────┘
              ▼ critical: one confirmation (ask) or the auto rules
   branch + commit ──▶ draft pull request ──▶ verification runs ──▶ PR comment
```

1. **Welche Befunde.** `/fix N` braucht ein geprüftes Urteil mit der
   Einstufung `flaky_test`, `flaky_infrastructure` oder `configuration`.
   Ohne Urteil wird zuerst untersucht. `real_bug`, `fixed`, `unclear` und
   ungeprüfte Urteile werden mit Begründung abgelehnt. Gibt es für den Befund
   schon einen offenen Pull Request von flakipype, verlinkt `/fix` diesen,
   statt einen zweiten zu öffnen; gefunden wird er über eine versteckte
   Markierung (einen Hash des Befunds) in der ersten Zeile der
   Pull-Request-Beschreibung, auf einem Branch unter `flakipype/` im
   Repository selbst; der Pull Request eines Forks zählt nie.
2. **Push-Zugriff.** flakipype liest `permissions.push` des Repositorys,
   bevor der Fixer startet. Fehlt er, bricht `/fix` ab und sagt das. Keine
   Forks.
3. **Fixer.** Ein frischer Agent pro Korrektur, wie ein Investigator: der
   Befund, das Urteil mit seinen Belegen (als Daten) und die Werkzeuge
   unten. Er endet mit `submit_fix`.
4. **Prüfungen** im Code, dann ein Durchgang des **Reviewers** über den Diff
   (unten). Eine Korrektur, die eine Prüfung nicht besteht, geht höchstens
   zweimal mit den Gründen an den Fixer zurück. Ein `revise` des Reviewers
   schickt sie einmal zurück; `reject` beendet die Korrektur ohne Pull
   Request.
5. **Auslieferung** nach der Bestätigung: Branch, Commit, Draft-Pull-Request,
   Verifikation. Jeder Schritt meldet sein Ergebnis; ein Fehler stoppt den
   nächsten Schritt und sagt, was bereits existiert.

## Die Werkzeuge des Fixers

Der Fixer arbeitet auf einer Arbeitskopie im Speicher, festgelegt auf den
Head-Commit des Standardbranchs zu Beginn der Korrektur. Nichts wird geklont
oder auf die Festplatte geschrieben, kein Code des Repositorys läuft auf
deinem Rechner, und es gibt keine Git-Hooks, die laufen könnten.

| Werkzeug | Macht | Risiko |
| --- | --- | --- |
| `list_files(path)` | Dateien und Verzeichnisse unter einem Pfad im festgelegten Commit (Git-Trees-API) | `read` |
| `read_file(path, from_line, to_line)` | Die Version der Arbeitskopie: bearbeitet, wenn bearbeitet, sonst von GitHub | `read` |
| `replace_in_file(path, old, new)` | Ersetzt ein exaktes, eindeutiges Vorkommen; ein mehrdeutiges oder fehlendes `old` ist ein Fehler | `read` |
| `write_file(path, content)` | Legt eine neue Datei an oder ersetzt eine ganze Datei | `read` |
| `show_diff()` | Unified Diff der Arbeitskopie gegen den festgelegten Commit | `read` |
| `submit_fix(title, explanation)` | Beendet die Korrektur; läuft nach den anderen Aufrufen der Antwort und geht an den Fixer zurück, wenn einer davon fehlgeschlagen ist | – |

Dazu kommen die Werkzeuge des Investigators (`failure_excerpt`, `log_range`,
`run_history`, `compare_commits`, `file_diff`, `workflow_file`). Änderungen
haben das Risiko `read`: Sie ändern nur den Speicher. Die einzige
`critical`-Aktion ist der Push (unten), einmal bestätigt mit dem vollständigen
Diff. Nur UTF-8-Textdateien lassen sich bearbeiten, und nur im Repository des
Befunds; Pfade werden normalisiert, und `.git/`, absolute oder `..`-Pfade und
Pfade mit Steuerzeichen werden abgelehnt. Der Fixer liest Dateien mit
maskierten Secrets, deshalb wird eine Änderung abgelehnt, die einen
Platzhalter `[masked: …]` zurück in eine Datei schreiben würde. Symbolische
Links und Submodule lassen sich nicht bearbeiten (ein Commit würde den Link
ersetzen, nicht sein Ziel). Ein Neuschreiben behält den abschließenden
Zeilenumbruch der Datei; der Diff vergleicht auch Zeilenenden, sodass ein
geänderter abschließender Zeilenumbruch oder CRLF darin auftaucht.

## Prüfungen im Code

Deterministisch, vor dem Reviewer und vor jedem Dialog:

| Prüfung | Regel |
| --- | --- |
| Nicht leer | Mindestens eine geänderte Zeile |
| Größe | Höchstens 10 Dateien und 400 geänderte Zeilen (`fix.max_files`, `fix.max_changed_lines`) |
| Noch parsebar | Eine geänderte `.yml`-, `.yaml`-, `.json`- oder `.toml`-Datei, die vorher parsebar war (oder neu ist), ist weiterhin parsebar. YAML darf mehrere Dokumente und Anwendungs-Tags (`!Sub`, `!Ref`) enthalten; JSON darf mit einer Byte Order Mark beginnen. Eine Datei, die vorher nicht parsebar war (zum Beispiel JSONC mit Kommentaren), wird nicht geprüft. Workflow-Dateien, die `.yml`- und `.yaml`-Dateien direkt in `.github/workflows/`, enthalten weiterhin ein Dokument mit `on` und `jobs` |
| Nichts maskiert | Keine Datei bekommt einen Platzhalter `[masked: …]`; maskierte Zeilen verbergen echten Inhalt |
| Verbirgt Fehlschläge | Fügt `continue-on-error: true`, `if: always()` oder eine Skip- oder Fokus-Markierung für Tests hinzu (`pytest.skip(`, `pytest.xfail(`, `pytest.mark.skip`/`xfail` mit oder ohne `@`, `@unittest.skip`, `.skipTest(`, `SkipTest`, `.skip(` und `.only(` an einem Test (`test.`, `it.`, `describe.`, `context.`, `suite.`, `fixture.`, `this.`), `xit(`, `@Disabled`, `@Ignore`, `t.Skip`), die die Datei nicht schon genauso oft enthielt, oder entfernt mehr Testdeklarationen (einschließlich `async def test_` und Modifikatorformen wie `test.serial(`), als sie hinzufügt |
| Greift nach außen | Fügt eine Referenz `secrets.`, `github.token`, einen Umgebungs-Dump (`env`, `printenv`), `curl`, `wget`, `nc`, `ncat` oder eine `http(s)://`-URL außer localhost hinzu (der Host muss genau `localhost`, `127.0.0.1` oder `[::1]` sein; jede URL mit `user@` zählt) |
| Berührt `.github/` | Ändert Workflows oder Composite Actions unter `.github/` |

Die ersten vier sind Fehler: Die Korrektur geht an den Fixer zurück. Die
letzten drei sind **Warnungen**: Im Modus `ask` erscheinen sie oben in der
Bestätigung und im Pull Request; im Modus `auto` wird eine Korrektur mit
einer davon nicht gepusht (siehe [Modi](#modi)). Die Warnungen sind eine
Musterliste: Sie finden die üblichen Formen, nicht jede (eine
zusammengesetzte URL, `dict(os.environ)` oder `--reruns` in einer
Konfigurationsdatei fallen nicht auf). Darum hängt `auto` nicht von ihnen
ab, sondern pusht nur reine Dokumentation.

## Reviewer

Ein zweiter Modellaufruf mit dem Befund, dem Urteil, dem Diff und der
Erklärung des Fixers, nicht mit dem ganzen Gespräch des Fixers. Er antwortet
`accept`, `revise` (mit konkreten Punkten; der Fixer macht einmal weiter)
oder `reject` (mit Begründung) und prüft:

- Der Diff behebt die Ursache, die das Urteil nennt, nicht ein Symptom.
- Er verbirgt den Fehlschlag nicht: keine pauschalen Wiederholungen, keine
  längeren Timeouts ohne Grund in den Belegen, keine übersprungenen Tests.
- Keine Änderung, die nichts mit der Ursache zu tun hat.

Eine Korrektur, die der Reviewer nicht akzeptiert, wird nicht gepusht. Der
Chat zeigt den Diff und die Begründung, sodass du trotzdem Änderungen
anfordern kannst.

## Bestätigung

Der Push ist eine einzige `critical`-Aktion. Der Dialog zeigt oben Fakten aus
dem Code, den Text des Modells deutlich gekennzeichnet und den vollständigen
Diff in einem scrollbaren Bereich. Nichts darin wird als Markup gelesen, und
Steuerzeichen werden als Escapes wie `\x1b` angezeigt, sodass kein Inhalt
eine Zeile verbergen oder umschreiben kann:

```text
╭──────────────────────────────────────────────────────────────────────────╮
│ Push fix and open a draft pull request?                                  │
│                                                                          │
│ octo-org/app · base main @ 3f2a9c1                                       │
│ new branch flakipype/fix-e2e-7c41d0                                      │
│ 2 files · +14 −3 · tests/e2e/scan.spec.ts, playwright.config.ts          │
│ then reruns E2E on the fix branch 3 times                                │
│ Pull requests this session: 1 of 3 · Actions: 4 of 10                    │
│ Opens a draft pull request; merging stays with you.                      │
│ Warnings: none                                                           │
│ ── written by the model ─────────────────────────────────────────────    │
│ Wait for the document rows instead of a fixed delay                      │
│ The test counts rows before the second import finished …                 │
│ ── diff ─────────────────────────────────────────────────────────────    │
│ --- a/tests/e2e/scan.spec.ts                                             │
│ +++ b/tests/e2e/scan.spec.ts                                             │
│ …                                                                        │
│                         Push           Don't push                        │
╰──────────────────────────────────────────────────────────────────────────╯
```

**Don't push** hat den Fokus. Der Text des Modells und der Diff erscheinen
als reiner Text, nie als Markup. Eine abgelehnte Korrektur bleibt in der
Sitzung (auch über `/resume` hinweg): `/fix N` zeigt sie erneut, ohne den
Fixer laufen zu lassen, `/fix N --fresh` fängt neu an, und du kannst das
Modell um Änderungen bitten, die es dem Werkzeug `fix` als `instructions`
übergibt. Der Fixer bekommt sie als Daten markiert, weil das Modell darin
Log- oder Repository-Text zitieren kann, und startet vom früheren Diff am
selben festgelegten Commit. Alles andere folgt dem Gate wie bei den [Aktionen](aktionen.md): keine
zweite Schreibanfrage nach einer Ablehnung im selben Zug und ein Eintrag im
Audit-Log für jede Anfrage.

## Auslieferung

Alles über `gh api`, nur gegen den konfigurierten Owner und Host. Direkt vor
dem Branch sucht flakipype noch einmal nach einem offenen Pull Request von
flakipype für den Befund, da der Chat oder ein Lauf einen geöffnet haben
kann, während der Fixer arbeitete; gibt es einen, wird nichts gepusht, und
die Meldung verlinkt ihn. Beide Suchen lesen jede Seite der offenen Pull
Requests des Repositorys, sodass auch ein älterer Pull Request von flakipype
hinter vielen neueren gefunden wird.

1. **Branch.** `POST /repos/{o}/{r}/git/refs` legt
   `refs/heads/flakipype/fix-<workflow>-<hash>` am festgelegten Commit an
   (der Hash ist der des Diffs). Der Name beginnt immer mit `flakipype/`.
   Eine existierende Ref anzulegen schlägt fehl, also probiert flakipype die
   Suffixe `-2` bis `-5` und hört dann auf; es committet immer nur auf einen
   Branch, den es gerade selbst angelegt hat, sodass kein existierender
   Branch beschrieben wird, auch nicht der Standardbranch.
2. **Commit.** GraphQL `createCommitOnBranch` fügt die geänderten Dateien als
   einen Commit hinzu, mit `expectedHeadOid` auf dem festgelegten Commit,
   sodass er nur an den neuen Branch anhängen und nie etwas überschreiben
   kann. GitHub signiert den Commit, er erscheint also als *Verified* und
   besteht Branch-Regeln, die signierte Commits verlangen. Nachricht: der
   Titel, die Erklärung und ein Trailer `Generated-by: flakipype`.
3. **Pull Request.** `POST /repos/{o}/{r}/pulls` mit `draft: true`, immer, in
   beiden Modi. Die Beschreibung ist eine Vorlage im Code (unten).
4. **Verifikation** startet (unten).

Schlägt ein Schritt fehl, laufen die folgenden Schritte nicht, und die
Meldung sagt, was existiert: zum Beispiel „Branch flakipype/fix-e2e-7c41d0
created; the commit failed: … The branch was left as it is; flakipype never
deletes branches.“ Kann die Verifikation nicht starten (zum Beispiel weil
die Workflow-Datei nicht lesbar ist), bleibt der Pull Request offen, und das
Ergebnis und ein Kommentar am Pull Request sagen, warum.

Die Beschreibung des Pull Requests: Die vom Code geschriebenen Warnungen
stehen vor jedem Text des Modells, und der Text des Modells ist ein Zitat, in
dem HTML-Kommentare escapt sind, sodass er die Abschnitte, die der Code
schreibt, nicht verbergen kann:

```markdown
<!-- flakipype:finding=3f9c2a71b0d4 -->
## Flaky: e2e in octo-org/app

**Scan facts:** On main, E2E failed 4 of 31 runs (13%) in the scanned window.

- the finding's facts from the scan, one per line

### Warnings
none

**Verdict** (model's assessment, reviewed): flaky_test, high confidence.

> the verdict's summary

### The change (written by the model)

> the fixer's explanation

### Verification
Pending: flakipype reruns E2E on this branch 3 times.

---
Opened by flakipype as a draft. Merging is up to you.
```

## Verifikation

Der Korrektur-Branch muss zeigen, dass er dort durchläuft, wo der
Standardbranch instabil ist:

1. Läuft der Workflow (wie im Korrektur-Commit) bei `push` oder
   `pull_request`, startet das Öffnen des Pull Requests einen eigenen Lauf:
   flakipype wartet auf einen Lauf des Workflows des Befunds auf dem
   Korrektur-Commit. Erscheint innerhalb von 10 Minuten kein Lauf (Branch-,
   Typ- oder Pfadfilter können den Korrektur-Branch oder den
   Draft-Pull-Request ausschließen), startet flakipype den Workflow per
   Dispatch, wenn er `workflow_dispatch` ohne Pflichteingaben erlaubt;
   andernfalls lautet das Ergebnis „cannot verify automatically“. Eine
   Abfrage, die GitHub wiederholt ablehnt (außer wegen seines Rate-Limits),
   beendet das Warten nach 10 Minuten auf dieselbe Weise, mit dem Fehler von
   GitHub als Grund. Läuft der Workflow weder bei `push` noch bei
   `pull_request`, lässt sich aber per Dispatch starten, startet flakipype
   ihn sofort auf dem Korrektur-Branch. Andernfalls lautet das Ergebnis sofort
   „cannot verify automatically“, mit dem Grund (kein `workflow_dispatch` oder
   die Eingaben, die er verlangt).
2. Ist der Lauf fertig, führt flakipype den ganzen Lauf erneut aus, bis der
   Workflow `fix.verify_runs`-mal (Standard 3) auf dem Korrektur-Commit
   gelaufen ist. Die Läufe erscheinen in der Liste **Runs** wie bei den
   [Aktionen](aktionen.md) und zählen gegen dasselbe Aktionsbudget; die
   Push-Bestätigung deckt sie bereits ab. Einen Lauf zu beobachten, den
   flakipype nicht gestartet hat (den eigenen des Pull Requests), kostet kein
   Budget.
3. Ein Lauf zählt nur als durchgelaufen, wenn der Job des Befunds darin lief
   und durchlief. Ein erfolgreicher Lauf, der den Job übersprungen hat (zum
   Beispiel durch ein `if:` bei Draft-Pull-Requests), stoppt die
   Verifikation, da ein Rerun dasselbe Ereignis wiederholt. Die Verifikation
   stoppt auch vorzeitig, wenn ein Lauf weder durchgelaufen noch
   fehlgeschlagen endet (zum Beispiel abgebrochen), nicht innerhalb von
   `actions.watch_hours` fertig wird oder sich so lange nicht lesen lässt,
   GitHub einen Rerun oder Dispatch ablehnt oder das Aktionsbudget
   aufgebraucht ist; der Kommentar sagt, nach wie vielen Läufen und warum.
   Ein Rate-Limit pausiert sie nur bis zur nächsten Abfrage.
4. Das Ergebnis wird als Kommentar am Pull Request veröffentlicht, vom Code
   geschrieben:

```text
flakipype verification: E2E passed 3 of 3 runs on this branch.
On main, E2E failed 4 of 31 runs (13%) in the scanned window.
Three passes in a row would also happen by chance 66% of the time without a fix, so this is a first signal, not proof.
```

Jeder fehlgeschlagene Lauf bekommt eine Zeile: Ein Fehlschlag des Jobs des
Befunds mit der Fehlersignatur des Befunds sagt, dass die Korrektur nicht
gehalten hat, einer mit einer anderen Signatur wird mit seiner Meldung
berichtet, ein Fehlschlag in einem anderen Job nennt diesen Job, und ein
unlesbares Log wird als solches gemeldet. Die Rate ist der Anteil der Läufe,
in denen der Job des Befunds im Scan auf dem Standardbranch mindestens einmal
fehlschlug, oder auf allen Branches, wenn der Scan keine Läufe auf dem
Standardbranch hat; wie der Scan zählt sie nur Läufe, die durchliefen oder
fehlschlugen, keine abgebrochenen oder übersprungenen. Die angezeigte Chance
ist `(1 − rate)^runs`, nur wenn jeder Lauf durchlief. Die Verifikation wird
abgefragt, solange der Chat offen ist, und ihr Hinweis erscheint im Chat; eine
fortgesetzte Sitzung setzt sie fort. Einen Pull Request, den ein
[unbeaufsichtigter Lauf](unbeaufsichtigte-laeufe.md) geöffnet hat, fragt
dieser Lauf ab und, wenn er nicht rechtzeitig fertig ist, der nächste.

## Modi

`/mode ask|auto` wechselt den Modus des Chats; `/mode` allein zeigt ihn an.
Der Chat startet immer in `ask`, `/new` und `/resume` wechseln zurück zu
`ask`, der Modus wird nicht in der Sitzung gespeichert, und die Statuszeile
zeigt ihn an.

| | `ask` | `auto` |
| --- | --- | --- |
| Reruns, Dispatches, Abbrüche (`write`) | Dialog | laufen im Rahmen des Budgets |
| Push und Draft-PR (`critical`) | Dialog mit dem Diff | läuft im Rahmen des Budgets, wenn die Korrektur nur Dokumentation ändert und keine Warnung hat |
| Korrektur an ausführbarem Code (unten) | Dialog mit dem Diff | nicht gepusht; aufbewahrt für `/mode ask` |
| Korrektur mit Warnung (verbirgt Fehlschläge, greift nach außen, `.github/`) | Dialog zeigt die Warnungen | nicht gepusht; aufbewahrt für `/mode ask` |
| Draft-Pull-Request | immer | immer |

Ausführbar ist jede geänderte Datei außer reiner Dokumentation. Als reine
Dokumentation zählt nur eine Datei mit der Endung `.md`, `.markdown`, `.rst`
oder `.adoc`, die

- nicht in einem versteckten Ordner (`.github/`, `.claude/` …) oder einem
  Testordner (`test`, `tests`, `spec`, `specs`, `__tests__`, `fixtures`,
  `testdata`) liegt,
- keine Anweisungsdatei für Coding-Agenten ist (`AGENTS.md`, `CLAUDE.md`,
  `GEMINI.md`), die ein Workflow mit Secrets lesen könnte,
- und nach der Änderung nichts enthält, das ein Doku-Werkzeug ausführen
  könnte: keinen Doctest-Prompt `>>>`, keinen Codeblock mit ` ``` ` oder
  `~~~` und keine reStructuredText-Direktive (`.. name::`).

Alles andere gilt als ausführbar, auch `.txt`, Konfiguration, Manifeste wie
`package.json` oder `requirements.txt`, `Makefile`, `conftest.py` und das
YAML von Workflows und Actions. Im Zweifel ist eine Datei ausführbar.

Die Regel gibt es, weil ein gepushter Branch im selben Repository dessen
`push`-Workflows mit den Secrets des Repositorys auslöst, mit den
Workflow-Dateien und dem Code aus diesem Branch, bevor irgendjemand den Pull
Request prüft. Job-Logs und Dateien im Repository, auch die eines Pull
Requests aus einem Fork, können Text enthalten, der versucht, das Modell zu
steuern. Die Warnungen und der Reviewer fangen die üblichen Fälle ab, aber
eine Musterliste findet nur bekannte Formen, und der Reviewer ist selbst ein
Modell. Garantiert ist, was der Code durchsetzt: Im Modus `ask` siehst du
vorher jede Zeile des Diffs, im Modus `auto` kommt ausführbarer Code nie ohne
dich auf einen Branch. Audit-Einträge halten `auto` als Antwort fest, oder
`not run in auto mode` für eine Korrektur, die eine Person braucht; diese
Korrektur bleibt für `/mode ask` und `/fix N` in der Sitzung.

## Budget

| Limit | Standard | Einstellung |
| --- | --- | --- |
| Pull Requests pro Chat-Sitzung | 3 | `fix.max_prs_per_session` (1–20) |
| Dateien und geänderte Zeilen pro Korrektur | 10 und 400 | `fix.max_files` (1–50), `fix.max_changed_lines` (10–2.000) |
| Verifikationsläufe pro Korrektur | 3 | `fix.verify_runs` (1–10) |
| Werkzeugrunden des Fixers | 20 | `fix.max_rounds` (5–60) |
| Tokens des Fixers (Fixer und Reviewer) | 300.000 | `fix.max_tokens` (10.000–2.000.000) |
| Laufzeit des Fixers | 10 Minuten | `fix.max_seconds` (60–3.600) |

Verifikations-Reruns zählen gegen `actions.max_per_session`. Wird ein Limit
erreicht, endet die Korrektur mit einer Zusammenfassung, wie überall.

## Berechtigungen

Die Scopes `repo` und `workflow`, die flakipype ohnehin anfordert, decken
Branches, Commits (einschließlich Workflow-Dateien) und Pull Requests ab. Ein
Fine-grained Token braucht **Contents**, **Pull requests** und **Workflows:
read and write**, dazu **Actions: read and write** für die Verifikation. Ein
`403` erklärt, welche Berechtigung fehlt, und nichts wird wiederholt. Ein
`403` wegen des Rate-Limits von GitHub sagt stattdessen genau das und bittet
darum, es nach dem Zurücksetzen des Limits erneut zu versuchen. Nennt GitHub
Gründe für eine Ablehnung (ein `422` wie „Draft pull requests are not
supported in this repository“), enthält die Meldung sie.

## Wo es im Code liegt

- **`agent`**: der Fixer (`fixer.py`), der generische Reviewer
  (`reviewer.py`), Fixer und dann Reviewer mit höchstens einer Überarbeitung
  (`fix_pipeline.py`), die Bearbeitungswerkzeuge (`fix_tools.py`) und die
  Arbeitskopie (`workcopy.py`: eine Überlagerung der bearbeiteten Dateien
  über dem festgelegten Commit, mit dem Unified Diff aus `difflib`).
- **`fix`** (zwischen `investigate` und `actions`): die Prüfungen
  (`checks.py`), Branch-Name, Pull-Request-Beschreibung und Kommentartexte
  (`texts.py`), die Verifikation (`verify.py`), die Auslieferung
  (`delivery.py`), der Sitzungszustand der Korrekturen (`state.py`) und der
  Service mit dem Pull-Request-Budget und der Bestätigung (`service.py`).
- **`github`**: `pulls.py` für Refs, `createCommitOnBranch`, Pull Requests,
  Kommentare, Push-Berechtigung und die Baumauflistung.
- **`investigate`**: `/fix`, `/mode`, die Workspace-Seite des Werkzeugs
  `fix`.
- **`tui`**: der Text des Modells und der Diff im Bestätigungsdialog, der
  Modus in der Statuszeile.

## Tests

- Die Arbeitskopie und die Bearbeitungswerkzeuge: eindeutige und mehrdeutige
  Ersetzungen, neue Dateien, Pfadnormalisierung, der Diff.
- Jede Prüfung, mit Diffs, die sie bestehen und nicht bestehen.
- Fixer und Reviewer mit dem geskripteten Fake-Modell: accept, revise,
  reject, eine fehlschlagende Prüfung, Budgetende.
- `pulls.py` gegen den `gh`-Stub mit aufgezeichneten Antworten, einschließlich
  des GraphQL-Commits, eines existierenden Branch-Namens, `403` und eines
  Fehlers, nachdem der Branch angelegt wurde.
- Auslieferung, Verifikation (durchgelaufen, gleiche Signatur, andere
  Signatur, nicht verifizierbar) und der Kommentartext mit einer Fake-Uhr.
- Das Gate in beiden Modi, einschließlich Warnungen und ausführbarem Code in
  `auto`.
- Die Bestätigung mit einem Diff und der Modus in der Statuszeile:
  Pilot-Tests und Snapshots.
