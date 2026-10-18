# Einen Headless-Rechner einrichten

Das hier gilt für Server, Container oder SSH ohne interaktive
Terminal-Oberfläche.

## 1. Bei GitHub anmelden

flakipype teilt die Anmeldung von `gh`. Auf einem Rechner ohne Browser
meldest du dich mit einem Token an:

```bash
gh auth login --hostname github.com --with-token < token.txt
```

Ein klassisches Token oder die eigene OAuth-Anmeldung von `gh` braucht die
Scopes `repo`, `workflow` und `read:org`. Ein Fine-grained Token braucht
Lese- und Schreibzugriff auf Actions, Contents, Pull requests und Workflows
in den Repositories, die du scannst; GitHub meldet diese nicht zurück, deshalb
zeigt `doctor` eine Warnung statt eines Häkchens.

Ist `gh` noch nicht installiert, lädt Schritt 2 es herunter; die Anmeldung
kannst du danach mit `~/.local/share/flakipype/bin/gh` ausführen.

## 2. Konfiguration speichern

```bash
printf '%s' "$ANTHROPIC_KEY" | flakipype setup --non-interactive \
  --base-url https://api.anthropic.com \
  --model <model> \
  --owner <user-or-org> \
  --api-key-stdin
```

- Optionen, die du weglässt, behalten ihren gespeicherten Wert (oder den
  Standard).
- Für eine OpenAI-kompatible API wie STACKIT AI Model Serving gib dazu
  `--provider openai` und deren `/v1`-Basis als `--base-url` an; siehe
  [Ein Modell verbinden](modell-verbinden.md#eine-openai-kompatible-api).
- Der Key wird von der Standardeingabe gelesen, damit er nie in der
  Prozessliste oder im Shell-Verlauf auftaucht. Ohne `--api-key-stdin` bleibt
  der gespeicherte Key erhalten.
- Auf Rechnern ohne System-Schlüsselbund landet der Key in
  `~/.config/flakipype/secrets.json` mit Modus `0600`, ebenso, wenn du
  keyring mit `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`
  abschaltest. Mit `--secret-store file` bleibt er dort, auch wenn es einen
  Schlüsselbund gibt, z. B. für einen [Timer](zeitgesteuert-ausfuehren.md),
  der ohne Desktop-Sitzung läuft.
- Setup liest den Key nach dem Speichern zurück. Behält der Schlüsselbund ihn
  nicht, meldet setup das mit Code 2 und dem Befehl mit
  `--secret-store file`, statt „Saved“ zu melden.
- Findet setup kein passendes `gh`, lädt es eines herunter und prüft es.

Setup endet mit denselben Prüfungen wie `flakipype doctor` und beendet sich
mit Code 1, wenn eine fehlschlägt, oder 2, wenn die Eingabe ungültig war oder
der Schlüsselbund nicht gelesen werden kann (auch, wenn er nicht innerhalb
von 15 Sekunden antwortet).

## 3. Unbeaufsichtigt ausführen

[flakipype zeitgesteuert ausführen](zeitgesteuert-ausfuehren.md) mit einem
systemd-User-Timer.
