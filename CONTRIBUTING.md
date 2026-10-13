# Mitmachen

Danke, dass du hilfst. flakipype ist ein Linux-Kommandozeilenwerkzeug in
Python mit einem Textual-Chat; die [Dokumentation](docs/README.md) erklärt,
wie es funktioniert.

## Einrichten

[uv](https://docs.astral.sh/uv/) und [prek](https://prek.j178.dev/):

```bash
uv sync          # .venv with Python 3.12 and all dev tools
prek install     # git hooks
```

Ausführlich, auch für Windows mit Docker und act:
[Entwicklungsumgebung aufsetzen](docs/tutorials/entwicklungsumgebung.md).

## Arbeiten

| Aufgabe | Befehl |
| --- | --- |
| Alle Tests | `uv run poe test` |
| Eine Testdatei | `uv run pytest tests/unit/flaky/test_scoring.py` |
| Formatieren | `uv run poe format` |
| Lint, Typen, Architektur | `uv run poe lint`, `uv run poe typecheck`, `uv run poe arch` |
| Alle lokalen Qualitätsprüfungen | `uv run poe check` |
| TUI-Snapshots aktualisieren | `uv run pytest tests/tui --snapshot-update` |
| CLI ausprobieren | `uv run flakipype --version` |

Tests rufen nie das echte GitHub oder ein echtes Modell auf: GitHub ist ein
`gh`-Stub, der aufgezeichnetes JSON abspielt, das Modell ein lokaler
Fake-Anthropic-Server
([Test-Doubles](docs/reference/qualitaetssicherung.md#test-doubles)). Eine
TUI-Änderung bekommt einen Textual-Pilot-Test, eine neue Ansicht einen
Snapshot.

## Bevor du einen Pull Request öffnest

```bash
uv run poe format
uv run poe check                 # format, lint, types, architecture, deps, dead code, tests + coverage
prek run --all-files             # gitleaks, zizmor, file hygiene
act pull_request -j test         # the Linux CI job, when you work on Windows or macOS
```

- Halte Änderungen fokussiert: ein Thema je Pull Request.
- Die Dokumentation wandert mit dem Code: Eine Änderung an Verhalten,
  Einrichtung, Konfiguration oder einer Entwurfsentscheidung ändert die
  passende Datei unter [docs/](docs/README.md).
- Das [Sicherheitsmodell](docs/explanation/sicherheitsmodell.md) bleibt
  unangetastet: Der Standardbranch wird nie beschrieben, jedes
  Agentenwerkzeug läuft durch das Policy-Gate, und nichts erreicht das Modell
  unmaskiert.

Die CI führt alle [Qualitätsprüfungen](docs/reference/qualitaetssicherung.md)
aus (`ci.yml`, `codeql.yml`), einschließlich der Installations-Smoke-Tests
auf Ubuntu, Debian, Fedora und Arch.

## Veröffentlichen

Änderungen stehen in den [GitHub Releases](https://github.com/besessener/flakipype/releases).

1. Setze die neue Version in `pyproject.toml` und als `FLAKIPYPE_VERSION` in
   `install.sh` (ein Unit-Test prüft, dass beide übereinstimmen), und
   aktualisiere die Installationsbefehle in der [README](README.md), im
   Tutorial [Erste Schritte](docs/tutorials/erste-schritte.md), in
   [Unbeaufsichtigte Läufe und Release](docs/explanation/unbeaufsichtigte-laeufe.md)
   und in `site/index.html`. Merge das über einen Pull Request.
2. Tagge den Merge-Commit auf `main`, pushe den Tag und erstelle daraus ein
   GitHub-Release mit erzeugten Notizen:
   `git tag vX.Y.Z && git push origin vX.Y.Z`.

Es gibt keinen Release-Workflow und kein PyPI-Paket; wie die Installation
funktioniert:
[Unbeaufsichtigte Läufe und Release](docs/explanation/unbeaufsichtigte-laeufe.md#release).

## Erweitern

- Ein neues Agentenwerkzeug:
  [Was der Investigator nutzen kann](docs/explanation/agent.md#was-der-investigator-nutzen-kann)
  und seine [Risikostufe](docs/explanation/sicherheitsmodell.md#risikostufen-im-code-erzwungen).
- Ein neues Flake-Signal:
  [Wie Instabilität erkannt wird](docs/explanation/flake-erkennung.md).
