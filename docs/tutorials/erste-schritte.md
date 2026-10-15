# Erste Schritte

Das hier führt dich von der Installation bis zu einem gesunden
`flakipype doctor`. Du brauchst einen Linux-Rechner, einen Anthropic-API-Key
(oder ein Claude-Deployment auf Azure AI Foundry) und einen GitHub-Account
mit Zugriff auf die Repositories, die du scannen willst.

## 1. Installieren

```bash
curl -fsSLO https://raw.githubusercontent.com/besessener/flakipype/v0.2.0/install.sh
sh install.sh
flakipype --version
```

Das Skript braucht `curl`, `tar` und `git`. Es nutzt dein `uv`, wenn du eines
hast; sonst lädt es das `uv`-Release herunter, das es nennt, prüft den
Download gegen die SHA-256, die dieses Release veröffentlicht, und installiert
es nach `~/.local/bin`. Dann führt es `uv tool install` für das
flakipype-Release aus, das auch ein Python 3.12 oder neuer mitbringt, falls
dein System keines hat. Nichts braucht root. Ist `uv` schon installiert, ist
das hier dasselbe:

```bash
uv tool install git+https://github.com/besessener/flakipype@v0.2.0
```

## 2. Den Einrichtungsassistenten starten

```bash
flakipype setup
```

Der Assistent ist ein Vollbild-Formular mit zwei Abschnitten.

**1 Model**

- **Base URL**: `https://api.anthropic.com`, dein Foundry-Endpunkt
  (`https://<resource>.services.ai.azure.com/anthropic`) oder ein Proxy.
  Siehe [Modell verbinden](../how-to/modell-verbinden.md).
- **API key**: wird im System-Schlüsselbund gespeichert, nie in der
  Konfigurationsdatei.
- **Model**: der Modellname, auf Foundry der Deployment-Name.

Drück **Test connection**. flakipype sendet eine winzige Anfrage (ein
einziges Ausgabe-Token) und zeigt das Modell, das geantwortet hat, oder was
schiefging und was zu tun ist.

**2 GitHub**

- **Host**: `github.com` oder dein GitHub-Enterprise-Server-Host.
- **User or organisation to scan**: der User oder die Organisation, die
  gescannt wird.
- **gh**: Liegt kein `gh` 2.97.0 oder neuer in deinem `PATH`, drück
  **Download gh**. flakipype holt das neueste Release für deine Architektur,
  prüft seine SHA-256 gegen die Prüfsummendatei des Releases und installiert
  es nach `~/.local/share/flakipype/bin/gh`. Ein Fortschrittsbalken zeigt den
  Download (etwa 15 MB); die GitHub-Buttons sind gesperrt, bis er fertig ist.
- **Login**: flakipype teilt deine normale `gh`-Anmeldung. Bist du nicht
  angemeldet, drück **Log in with browser** (der Assistent übergibt das
  Terminal an `gh auth login`) oder füge ein Token ein und drück
  **Use token**.

Drück **Save** (oder `Ctrl+S`). `Esc` bricht ab, ohne zu speichern.

## 3. Alles prüfen

Nach dem Speichern und jederzeit später:

```bash
flakipype doctor
```

```text
 ✔  Configuration              ~/.config/flakipype/config.toml
 ✔  Model (Anthropic API)      claude-… at https://api.anthropic.com, key in system keyring (SecretService)
 ✔  gh CLI                     2.102.0 at /usr/bin/gh
 ✔  GitHub login (github.com)  octocat, scopes read:org, repo, workflow
 ✔  Scan target                octo-org on github.com
```

Jede fehlgeschlagene Zeile hat einen Pfeil mit dem nächsten Schritt. `doctor`
beendet sich mit Code 1, wenn eine Prüfung fehlschlägt, und funktioniert so
auch in Skripten.

Auf einem Server ohne Terminal-Oberfläche siehe
[Einen Headless-Rechner einrichten](../how-to/headless-einrichten.md); damit
flakipype selbstständig arbeitet,
[führ es zeitgesteuert aus](../how-to/zeitgesteuert-ausfuehren.md).
