# Qualitätsprüfungen

## Lokale Prüfungen

| Prüfung | Werkzeug | Setzt durch |
| --- | --- | --- |
| Formatierung | ruff format | Ein Stil, keine Diskussion |
| Lint | ruff (`select = ["ALL"]`) | Fehler, Sicherheit (bandit-Regeln), Komplexität ≤ 10 pro Funktion, höchstens 4 Parameter (3 positionale) |
| Typen | ty, dazu ruff `ANN` für Annotationen | Vollständig typisierte `src` und `tests`; Warnungen schlagen fehl; Ausnahmen sind `# ty: ignore[<rule>]` (`type: ignore` wird nicht beachtet) |
| Architektur | import-linter | Schichtenvertrag, siehe [Architektur](../explanation/architektur.md) |
| Abhängigkeiten | deptry | Keine ungenutzten, fehlenden oder falsch eingeordneten Abhängigkeiten |
| Toter Code | vulture | Kein ungenutzter Code |
| Shell-Skripte | ShellCheck (`shellcheck-py`) | `install.sh` und der Smoke-Test |
| Tests | pytest, Warnungen sind Fehler | Verhalten, nicht Implementierung |
| Abdeckung | coverage.py, Branch-Abdeckung | `fail_under` in `pyproject.toml`, wird immer nur angehoben |
| Hygiene | prek: gitleaks, zizmor, pre-commit-hooks | Keine Secrets, sichere Workflows, saubere Dateien |

## Test-Doubles

Tests erreichen nie das echte GitHub oder ein echtes Modell.

- **GitHub**: `tests/fakes/gh.py` vertritt `gh`. Jeder Test hinterlegt die
  erwarteten Aufrufe mit der Fixture `fake_gh` (`tests/conftest.py`,
  `tests/support/fake_gh.py`); der Fake spielt aufgezeichnete Ausgaben aus
  `tests/fixtures/gh/` ab und protokolliert jeden Aufruf (Argumente, stdin,
  `GH_HOST`) für Assertions. Er läuft als `python tests/fakes/gh.py` und
  funktioniert daher auch unter Windows.
- **Actions-API**: `tests/fixtures/gh/` enthält gekürzte echte Antworten
  (Repository-Liste, eine Seite mit Läufen, die Jobs eines fehlgeschlagenen
  Versuchs); `tests/fixtures/logs/` enthält gekürzte echte Job-Logs
  (Playwright-Timeout, npm-Build-Fehler und Stryker-Fehler hinter einem
  allgemeinen Exit-Code). Der Scan-Service wird gegen einen Fake im Speicher
  (`tests/support/fake_actions.py`) getestet, der auf Wunsch jeden
  GitHub-Fehler auslösen kann; `tests/support/builders.py` baut Läufe und
  Jobs für die reinen Erkennungstests.
- **Downloads**: Der `gh`-Installer wird gegen einen
  `httpx2.MockTransport` getestet, der ein Release, eine Prüfsummendatei und
  ein Tarball ausliefert, die im Test gebaut werden.
- **LLM**: `tests/support/fake_anthropic.py` antwortet wie die Messages API
  über `httpx2.MockTransport`: vorgegebene Züge (Thinking, Tool-Aufrufe,
  `submit_verdict`, `submit_review`, HTTP-Fehler), und es zeichnet jede
  Anfrage auf, damit Tests Maskierung, Tool-Ergebnisse und
  Thinking-Einstellungen prüfen können. Wie die echte API lehnt es einen
  Verlauf, den die API ablehnen würde (eine leere Nachricht vor der letzten
  oder ein Tool-Aufruf ohne sein Ergebnis in der nächsten Nachricht), mit 400
  ab, sodass ein kaputter Chat-Verlauf den nächsten Zug scheitern lässt. Der
  echte `anthropic`-Client wird verwendet, nur der Transport ist gefälscht.
- **Agent**: `tests/support/fake_sources.py` (Logs, Commits, Dateien) und
  `tests/support/fake_investigation.py` (eine Scan-Welt mit einem Befund
  jeder Art und einem Platzhalter für den Agenten).
- **Einrichtungswelt**: `tests/support/fake_setup.py` baut einen
  `SetupService` mit einem temporären Konfigurationsverzeichnis, einem
  Secret-Speicher in einer Datei, einem gefälschten `gh`-Anbieter und einem
  gefälschten Modell.
- **Unbeaufsichtigte Läufe**: `tests/support/fake_run.py` baut einen
  `RunService` über der Untersuchungswelt mit einstellbarer Uhr (Schlafen
  stellt sie vor), und `tests/support/fake_daemon.py` beantwortet
  `systemctl`, `systemd-run` und `loginctl` aus einer Tabelle.
- **TUI**: Textual-Pilot-Tests steuern die App (`tests/tui/`); jede Ansicht
  hat einen SVG-Snapshot in `tests/tui/__snapshots__/`. Nach einer gewollten
  Änderung der Oberfläche aktualisierst du ihn mit
  `uv run pytest tests/tui --snapshot-update` und prüfst den SVG-Diff.
- **Plattformspezifische Tests**: Drei Tests brauchen POSIX (`0600` für
  Secrets, ausführbares `gh`, durch `:` getrennter `PATH`); sie werden unter
  Windows übersprungen und laufen in der CI.
- **Echte Daten**: Bevor eine Änderung am Scan gemergt wird, läuft
  `flakipype scan` einmal gegen ein echtes Konto in WSL oder Linux. Er liest
  nur; gib dabei nie Tokens aus und übergib sie nie auf der Kommandozeile.
- **End to End**: Untersuchungen, Korrekturen, Draft-PRs, Verifikation und
  der Timer werden gegen die Sandbox
  [besessener/flakipype-test](https://github.com/besessener/flakipype-test)
  ausprobiert, nie gegen echte Projekte. Jeder ihrer Workflows ist auf eine
  bekannte Weise instabil oder kaputt, und ihr README listet das erwartete
  Urteil pro Fall auf; das ist die Checkliste für Evaluationen gegen ein
  echtes Modell.

Evaluationen gegen ein echtes Modell sind für `tests/eval` geplant, das es
noch nicht gibt. Sie werden nicht Teil von `poe check` oder der CI sein und
laufen nur auf Nachfrage.

## CI (`.github/workflows/`)

| Workflow / Job | Prüft | Wann |
| --- | --- | --- |
| `ci.yml` → `hygiene` | gitleaks über die ganze Historie (Binärdatei mit geprüfter Prüfsumme), alle prek-Hooks | PR, Push auf `main` |
| `ci.yml` → `test` | `uv sync --locked` und `poe check` auf Python 3.12 und 3.14; Abdeckungstabelle in der Job-Zusammenfassung | PR, Push auf `main` |
| `ci.yml` → `smoke` | In Containern mit Ubuntu 24.04, Debian 12, Fedora und Arch (per Digest festgelegt), als Benutzer ohne root: `install.sh` aus dem Checkout (mit dem geprüften `uv`-Download), `flakipype --version`, `doctor` ohne Konfiguration und die Unit-Dateien über `systemd-analyze verify` (`tests/smoke/smoke.sh`) | PR, Push auf `main` |
| `codeql.yml` | CodeQL `security-extended` für Python und Actions | PR, Push auf `main`, wöchentlich |
| `pages.yml` | Veröffentlicht `site/` auf GitHub Pages, siehe [Webseite pflegen](../how-to/webseite-pflegen.md) | Push auf `main`, der `site/` ändert, von Hand |
| `dependabot.yml` | Updates für Actions, uv-Abhängigkeiten und Hook-Revisionen, 7 Tage Wartezeit | wöchentlich |

**Härtung der Workflows**: Jede Action ist auf einen Commit-SHA festgelegt
(der Kommentar nennt den Tag), Workflows haben standardmäßig keine
Token-Berechtigungen (`permissions: {}`) und checken mit
`persist-credentials: false` aus. zizmor setzt das durch.
