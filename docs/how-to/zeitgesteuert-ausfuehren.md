# flakipype zeitgesteuert ausführen

`flakipype run` scannt, untersucht und öffnet Draft-PRs ohne Fenster; ein
systemd-User-Timer startet es. Wie es entscheidet und was es begrenzt:
[unbeaufsichtigte Läufe](../explanation/unbeaufsichtigte-laeufe.md).

Um das von Anfang bis Ende auszuprobieren, ohne ein echtes Projekt
anzufassen, richte es auf die Sandbox
[besessener/flakipype-test](https://github.com/besessener/flakipype-test).
Sie ist auf bekannte Weise instabil und dafür da, Draft-PRs und Reruns zur
Verifikation zu empfangen: Hänge `--repo besessener/flakipype-test` an die
Befehle unten an.

## 1. Einen Probelauf machen

```bash
flakipype run --mode ask
```

`ask` ohne Fenster berichtet nur: Es scannt, untersucht und schreibt
Korrekturen, pusht aber nichts und zeigt, was es öffnen würde. Seine
Korrekturen bleiben in der Sitzung des Laufs; `/sessions` und `/resume N` im
Chat öffnen sie, und `/fix N` zeigt die Bestätigung mit dem Diff.

## 2. Einmal richtig ausführen

```bash
flakipype run
```

Die Zusammenfassung nennt jeden Draft-PR, jede Korrektur, die nicht gepusht
wurde, und warum, die Verifikation jedes Pull Requests und wie viel der
heutigen Limits die Läufe verbraucht haben. Exit-Codes: 0 fertig, 1 etwas
blieb unvollständig, 2 nicht eingerichtet, 3 ein anderer Lauf läuft gerade.

## 3. Den Key ohne Desktop-Sitzung lesbar machen

Ein Timer läuft oft, während keine Desktop-Sitzung den System-Schlüsselbund
entsperrt hat. Leg den Key stattdessen in eine Datei, die nur du lesen
kannst:

```bash
printf '%s' "$ANTHROPIC_KEY" | flakipype setup --non-interactive --secret-store file --api-key-stdin
```

Speichert auch `gh` sein Token im Schlüsselbund, melde dich mit
`gh auth login --insecure-storage` erneut an; dann liegt es in der eigenen
Konfigurationsdatei von `gh`.

## 4. Den Timer installieren

```bash
flakipype daemon install                      # daily
flakipype daemon install --schedule "Mon..Fri 06:00"
flakipype daemon install --print              # only show the unit files
```

`install` führt zuerst `flakipype doctor` über `systemd-run --user` aus, in
derselben Umgebung wie der Timer; schlägt das fehl, wird nichts installiert,
und die Ausgabe sagt, warum. Dann schreibt es `flakipype.service` und
`flakipype.timer` nach `~/.config/systemd/user/` und startet den Timer. Führe
`install` erneut aus, um den Zeitplan zu ändern.

Ohne Lingering läuft ein User-Timer nur, solange du angemeldet bist. So läuft
er auf einem Server ohne Anmeldesitzung:

```bash
loginctl enable-linger "$USER"
```

## 5. Nachsehen, wie es läuft

```bash
flakipype daemon status                       # next start, last result, last summary
journalctl --user -u flakipype.service        # every run's summary
```

Die Limits je Lauf und je Tag stehen im Abschnitt `[run]` der
[Konfiguration](../reference/konfiguration.md). Zum Beenden:

```bash
flakipype daemon uninstall
```
