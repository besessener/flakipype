# Befehle

## Entwicklungs-Tasks (`uv run poe <task>`)

| Task | Führt aus | Zweck |
| --- | --- | --- |
| `format` | `ruff format` | Alle Dateien formatieren |
| `format-check` | `ruff format --check` | Bei unformatierten Dateien fehlschlagen |
| `lint` | `ruff check` | Lint mit allen ruff-Regeln (Ausnahmen in `pyproject.toml`) |
| `typecheck` | `ty check` | Typprüfung von `src` und `tests` (Regeln in `pyproject.toml`) |
| `arch` | `lint-imports` | Architekturgrenzen (import-linter) |
| `deps` | `deptry src` | Ungenutzte, fehlende und falsch eingeordnete Abhängigkeiten |
| `deadcode` | `vulture` | Toter Code |
| `shellcheck` | `shellcheck install.sh tests/smoke/smoke.sh` | Die Shell-Skripte prüfen |
| `test` | `pytest` | Tests ohne Abdeckung |
| `test-cov` | `pytest --cov` | Tests mit der Abdeckungsschwelle |
| `check` | alle oben außer `format`, `test` | Die lokale Definition of Done |

Außerhalb von poe:

| Befehl | Zweck |
| --- | --- |
| `prek run --all-files` | gitleaks, zizmor, Hooks für Dateihygiene |
| `act pull_request -j test` | Linux-CI-Job in Docker, siehe [CI lokal ausführen](../how-to/ci-lokal-ausfuehren.md) |
| `act pull_request -j smoke` | `install.sh` und ein erster Start unter Ubuntu, Debian, Fedora und Arch |

## `flakipype`-CLI

| Befehl | Zweck |
| --- | --- |
| `flakipype --version` | Die installierte Version ausgeben |
| `flakipype` (ohne Argumente) | Der Chat im Terminal, siehe [den Chat nutzen](../how-to/chat-nutzen.md); sonst die Hilfe. Exit-Codes: 0 Chat verlassen, 1 GitHub nicht lesbar oder der Chat ist abgestürzt, 2 nicht eingerichtet |
| `flakipype setup` | Einrichtungsassistent im Vollbild (braucht ein Terminal) |
| `flakipype setup --non-interactive [options]` | Einrichtung headless, siehe unten |
| `flakipype doctor` | Konfiguration, Modellverbindung, `gh` und die GitHub-Anmeldung prüfen |
| `flakipype scan [options]` | Instabile Jobs finden und ordnen, siehe unten |
| `flakipype investigate [options]` | Befunde vom Agenten mit Belegen erklären lassen; siehe [Befunde untersuchen](../how-to/befunde-untersuchen.md) |
| `flakipype run [options]` | Scannen, untersuchen und korrigieren ohne Fenster, siehe unten |
| `flakipype daemon install\|uninstall\|status` | Der systemd-Benutzer-Timer, der `flakipype run` startet, siehe unten |

### `flakipype run`

| Option | Bedeutung |
| --- | --- |
| `--mode auto\|ask` | `auto` (Standard) pusht Draft-PRs innerhalb der Limits; `ask` meldet nur, was es tun würde |
| `--days N`, `--repo NAME` | Wie bei `scan` |
| `--owner NAME` | Muss der konfigurierte `github.owner` sein (Groß- und Kleinschreibung egal): Ein Lauf korrigiert nur diesen Owner; jeder andere endet mit Code 2 |
| `--json` | Die Zusammenfassung als JSON ausgeben (`schema_version` 1) |

Exit-Codes: 0 beendet (ein erreichtes Limit ist ein normales Ende), 1 etwas
war unvollständig (Scan früh beendet, die Läufe eines Repositorys nicht
auflistbar, GitHub oder das Modell sind fehlgeschlagen, eine Auslieferung
ist fehlgeschlagen; bei HTTP 401 mit dem Hinweis, dich neu anzumelden), 2
nicht eingerichtet oder ein anderer `--owner`, 3 ein anderer `flakipype
run` läuft. So funktioniert es:
[unbeaufsichtigte Läufe](../explanation/unbeaufsichtigte-laeufe.md).

### `flakipype daemon`

| Befehl | Bedeutung |
| --- | --- |
| `install [--schedule S] [--mode auto\|ask]` | `doctor` in der Umgebung des Timers ausführen, dann `flakipype.timer` schreiben, aktivieren und starten; `S` ist ein systemd-Kalenderausdruck (Standard `daily`) |
| `install --print` | Die Unit-Dateien ausgeben, nichts ändern |
| `uninstall` | Den Timer stoppen und die Units entfernen, die flakipype geschrieben hat |
| `status` | Der Timer, das letzte Ergebnis und die Zusammenfassung des letzten Laufs |

`install` und `uninstall` enden mit 1, wenn systemd ablehnt, `install` mit 2,
wenn flakipype nicht eingerichtet ist (keine Konfigurationsdatei oder eine,
die es nicht lesen kann), und mit 1, wenn `doctor` in der Umgebung des Timers
fehlschlägt. `install --print` braucht keine Konfiguration. Anleitung:
[zeitgesteuert ausführen](../how-to/zeitgesteuert-ausfuehren.md).

### `flakipype scan`

| Option | Bedeutung |
| --- | --- |
| `--days N` | Tage, die zurückgeschaut wird, 1–400 (Standard `scan.window_days`) |
| `--repo NAME` | Nur dieses Repository (`repo` oder `owner/repo`); für mehrere wiederholen |
| `--owner NAME` | Ein anderer Benutzer oder eine andere Organisation (Standard `github.owner`) |
| `--max-logs N` | Höchstzahl der Job-Logs, die diesmal gelesen werden, 0–1000 (Standard `scan.max_log_downloads`) |
| `--min-runs N` | Läufe, die nötig sind, um einen Job instabil zu nennen, 1–100 (Standard `scan.min_flaky_runs`) |
| `--json` | Das [JSON-Ergebnis](scan-json.md) statt der Tabelle auf stdout ausgeben |

Exit-Codes: 0 beendet, 1 früh beendet oder GitHub nicht lesbar, 2 nicht
eingerichtet. Anleitung: [instabile Pipelines finden](../how-to/instabile-pipelines-finden.md).

### `flakipype setup --non-interactive`

| Option | Bedeutung |
| --- | --- |
| `--base-url URL` | Basis-URL der Anthropic Messages API |
| `--model NAME` | Modell, auf Foundry der Deployment-Name |
| `--host HOST` | GitHub-Host |
| `--owner NAME` | GitHub-Benutzer oder -Organisation, die gescannt wird |
| `--api-key-stdin` | Den API-Key von der Standardeingabe lesen |
| `--secret-store auto\|keyring\|file` | Wo der API-Key liegt (`secrets.store`); bei einem neuen Speicher den Key erneut übergeben |

Weggelassene Optionen behalten ihren gespeicherten Wert. Die Einrichtung lädt
`gh` bei Bedarf herunter und endet mit den Prüfungen von `doctor`. Der
Assistent (`flakipype setup` ohne `--non-interactive`) nimmt ebenfalls
`--secret-store` an und speichert diese Wahl.

### Exit-Codes

| Code | `setup` | `doctor` |
| --- | --- | --- |
| 0 | Gespeichert und alle Prüfungen bestanden (Warnungen erlaubt) | Alle Prüfungen bestanden (Warnungen erlaubt) |
| 1 | Gespeichert, aber eine Prüfung ist fehlgeschlagen; oder der Assistent wurde abgebrochen | Eine Prüfung ist fehlgeschlagen |
| 2 | Ungültige Eingabe, eine Konfigurationsdatei, die die Einrichtung nicht behalten kann, kein Terminal für den Assistenten, oder der Secret-Speicher kann nicht gelesen oder geschrieben werden | Der Secret-Speicher kann nicht gelesen werden |
