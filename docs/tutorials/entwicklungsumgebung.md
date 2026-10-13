# Entwicklungsumgebung aufsetzen

Das hier führt dich von einem frischen Klon bis dahin, dass jede
Qualitätsprüfung grün ist. Es funktioniert unter Linux, macOS und Windows;
flakipype selbst ist nur für Linux gebaut, deshalb läuft die Linux-Prüfung
unter Windows über [act](../how-to/ci-lokal-ausfuehren.md).

## 1. Werkzeuge installieren

- [uv](https://docs.astral.sh/uv/getting-started/installation/) – installiert
  das passende Python und alle Entwicklungswerkzeuge.
- [prek](https://prek.j178.dev/) (oder `pre-commit`) – führt die Git-Hooks aus.
- Docker und [act](https://nektosact.com/) – nur für den Linux-CI-Job auf
  einem Rechner ohne Linux nötig.

## 2. Umgebung anlegen

```bash
git clone https://github.com/besessener/flakipype.git
cd flakipype
uv sync
prek install
```

`uv sync` legt `.venv` mit Python 3.12 an (festgelegt in `.python-version`)
und installiert flakipype im Editable-Modus zusammen mit der Dev-Gruppe.

## 3. Prüfungen ausführen

```bash
uv run poe check          # format, lint, types, architecture, deps, dead code, tests + coverage
prek run --all-files      # gitleaks, zizmor, file hygiene
act pull_request -j test  # Linux CI job in Docker (Windows/macOS)
```

Sind alle drei grün, kannst du einen Pull Request öffnen. Was jede Prüfung
abdeckt: [Qualitätsprüfungen](../reference/qualitaetssicherung.md).

## 4. Die CLI ausprobieren

```bash
uv run flakipype --version
```
