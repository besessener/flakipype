# CI lokal mit act ausführen

flakipype ist nur für Linux gebaut. Entwickelst du unter Windows (oder macOS),
ist das native `uv run poe check` die schnelle Schleife, und
[act](https://nektosact.com/) führt die echten Jobs aus
`.github/workflows/ci.yml` als Linux-Prüfung in Linux-Containern aus. Einen
eigenen Dev-Container gibt es nicht: Der Workflow ist die einzige Quelle
dafür, was unter Linux bestehen muss.

## Voraussetzungen

- Eine laufende Docker-Engine mit Linux-Containern (Docker Desktop, Rancher
  Desktop oder Docker in WSL).
- act. Unter Windows ohne winget lädst du `act_Windows_x86_64.zip` aus den
  [act-Releases](https://github.com/nektos/act/releases) herunter, prüfst es
  gegen die `checksums.txt` des Releases und entpackst `act.exe` in ein
  Verzeichnis in deinem `PATH`.

Die `.actrc` des Repositorys wählt das Runner-Image
`catthehacker/ubuntu:act-latest` (nah an GitHubs `ubuntu-latest`) und
`linux/amd64`. Der erste Lauf lädt das Image (mehrere GB).

## Jobs ausführen

```bash
act pull_request -j test       # quality gates on Python 3.12 and 3.14
act pull_request -j hygiene    # gitleaks over the history, prek hooks, zizmor
act pull_request -j smoke      # install.sh and a first start on four distributions
act -l                         # list all jobs
```

Nicht committete Änderungen sind dabei: act kopiert das Arbeitsverzeichnis.
Neue Dateien müssen mindestens gestagt sein (`git add`), damit sie
zuverlässig mitkommen.

## TUI-Snapshots unter Linux aktualisieren

Snapshots der Textual-Bildschirme müssen unter Linux erzeugt werden, wo die
CI sie vergleicht. Kopiere in WSL das Arbeitsverzeichnis nach `/tmp`,
aktualisiere die Snapshots dort und kopiere nur den Ordner `__snapshots__`
zurück:

```bash
rm -rf /tmp/fpcopy && mkdir /tmp/fpcopy
tar --exclude=.venv --exclude=.git -C /mnt/c/path/to/flakipype -cf - . | tar -xf - -C /tmp/fpcopy
cd /tmp/fpcopy
UV_PROJECT_ENVIRONMENT=/tmp/fp-venv uv run --python 3.12 pytest tests/tui -p no:cacheprovider --snapshot-update
cp -r /tmp/fpcopy/tests/tui/__snapshots__/. /mnt/c/path/to/flakipype/tests/tui/__snapshots__/
```

Führe diese Zeilen in einer WSL-Shell aus, nicht über PowerShell: PowerShell
expandiert `$…` selbst, und eine leere Variable im Quellpfad von `cp -r`
kopiert das falsche Verzeichnis.

## Grenzen

- act ist eine Emulation. Maßgeblich bleibt die von GitHub gehostete CI am
  Pull Request.
- CodeQL (`codeql.yml`) braucht GitHubs Code-Scanning-Backend und läuft nicht
  unter act.
- Pages (`pages.yml`) veröffentlicht auf GitHub Pages und läuft nicht unter
  act; sieh dir `site/` stattdessen lokal an
  ([Webseite pflegen](webseite-pflegen.md)).
- `uv` gibt in act eventuell „Failed to hardlink files“ aus; das ist harmlos.
