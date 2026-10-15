# Demo: flakipype an der Sandbox ausprobieren

Das hier führt dich einmal durch alles, was flakipype kann – scannen,
untersuchen, korrigieren, Draft-PR, Verifikation –, ohne ein echtes Projekt
anzufassen. Ziel ist die Sandbox
[besessener/flakipype-test](https://github.com/besessener/flakipype-test): Sie
ist auf bekannte Weise instabil und dafür da, Reruns und Draft-PRs zu
empfangen.

Du brauchst einen Linux-Rechner (unter Windows reicht WSL), einen
Anthropic-API-Key (oder ein Claude-Deployment auf Azure AI Foundry) und einen
GitHub-Account. Für Schritt 5 und 6 brauchst du Schreibrechte auf die Sandbox;
ohne sie hörst du nach Schritt 4 auf.

## 1. Installieren

Installiere das aktuelle Release wie in
[Erste Schritte](erste-schritte.md#1-installieren) beschrieben und prüf die
Version:

```bash
flakipype --version
```

## 2. Einrichten

```bash
flakipype setup
```

- **Model**: Base URL (`https://api.anthropic.com` oder dein
  Foundry-Endpunkt), API-Key und Modell; drück **Test connection**.
- **GitHub**: Host `github.com`, als User oder Organisation **`besessener`**.
  Fehlt `gh`, drück **Download gh**; dann melde dich an.

Speichere mit **Save** und prüf, dass jede Zeile grün ist:

```bash
flakipype doctor
```

`besessener` als Owner ist nötig, weil `flakipype run` nur den
konfigurierten Owner korrigiert. Damit nichts anderes von `besessener`
angefasst wird, bekommt jeder Befehl unten `--repo besessener/flakipype-test`.

## 3. Instabile Jobs finden

```bash
flakipype scan --repo besessener/flakipype-test
```

Das liest nur und kostet keine Modell-Tokens. Die Sandbox hat sechs Fälle,
jeder ein eigener Workflow:

| Workflow | Was passiert | Erwartetes Urteil | Korrigierbar |
| --- | --- | --- | --- |
| Timing race | Der Test schläft 50 ms auf einen Export, der 20 oder 80 ms braucht | `flaky_test` | ja: auf den Export warten |
| Random order | Ein Test liest die Datei, die ein anderer schreibt; die Reihenfolge wechselt | `flaky_test` | ja: der Test schreibt seine eigene Datei |
| Network | Der Download hat keinen Retry, der Mirror antwortet manchmal 503 | `flaky_infrastructure` | ja: `curl --retry` |
| Real bug | Preise werden abgeschnitten statt gerundet, bei jedem Lauf | `real_bug` | nein |
| Fixed | War instabil, bis ein Pull Request es behoben hat | `fixed` | nein |
| Configuration | Dem Workflow fehlt `issues: write`, HTTP 403 bei jedem Lauf | `configuration` | ja, mit einer `.github/`-Warnung |

Der Workflow **Rerun once** führt jeden ersten fehlgeschlagenen Versuch einmal
erneut aus. Die instabilen Fälle bestehen dann („passed on rerun“), der echte
Fehler und die Konfiguration schlagen wieder fehl. Welche Läufe Pech haben,
entscheidet `sandbox/environment.py`; eine Korrektur, die diese Datei
ändert, ist falsch.

## 4. Die Befunde erklären lassen

```bash
flakipype investigate --repo besessener/flakipype-test
```

Ab hier ruft flakipype das Modell auf und verbraucht Tokens, innerhalb der
Limits aus `[agent]` in der [Konfiguration](../reference/konfiguration.md).
Vergleiche die Urteile mit der Tabelle oben.

Dann ein Probelauf ohne Fenster, der nichts pusht:

```bash
flakipype run --mode ask --repo besessener/flakipype-test
```

Er scannt, untersucht, lässt den Fixer Korrekturen schreiben und den Reviewer
prüfen, und zeigt, was er öffnen würde. Die Korrekturen bleiben in der
Sitzung des Laufs.

## 5. Eine Korrektur als Draft-PR öffnen

Öffne den Chat:

```bash
flakipype
```

```text
/sessions              the latest sessions; the one from step 4 ends in "· run"
/resume N              open it: its scan, verdicts and unpushed fixes, only the sandbox
/findings              the numbered findings
/why N                 the verdict for finding N, with its evidence
/rerun N               rerun its failed jobs; confirm, watch it under Runs
/fix N                 the fix with its diff; Push opens a draft pull request
```

Ohne den Probelauf aus Schritt 4 fängst du stattdessen mit
`/scan flakipype-test` an: Das scannt nur die Sandbox, und die Auswahl bleibt
für den Rest der Sitzung.

Der Chat steht in `ask`: Jeder Rerun und jeder Push wartet auf deine
Bestätigung im Dialog. **Push** legt einen Branch `flakipype/fix-…` und
einen Draft-PR in der Sandbox an und führt den Workflow auf dem Fix-Branch
erneut aus; das Ergebnis kommt als Hinweis und als Kommentar am Pull Request.
`/budget` zeigt die verbrauchten Tokens, `/quit` beendet.

## 6. Unbeaufsichtigt laufen lassen

```bash
flakipype run --repo besessener/flakipype-test
```

`auto` ist der Standard ohne Fenster. Es pusht nur Korrekturen, die
ausschließlich Dokumentation ändern; jede Korrektur in der Sandbox ändert
Code oder `.github/`, deshalb öffnet dieser Lauf keinen Pull Request, sondern
meldet die Korrekturen mit ihrem Diff. Befunde mit einem offenen Draft-PR aus
Schritt 5 überspringt er. Warum das so ist:
[unbeaufsichtigte Läufe](../explanation/unbeaufsichtigte-laeufe.md).

Den systemd-Timer probierst du genauso aus: Hänge
`--repo besessener/flakipype-test` an die Befehle in
[Zeitgesteuert ausführen](../how-to/zeitgesteuert-ausfuehren.md) an.

## 7. Aufräumen

Schließe die Draft-PRs in der Sandbox und lösche ihre Branches
`flakipype/fix-…`, damit die nächste Demo sauber startet. Merge sie nicht:
Die Sandbox soll instabil bleiben.
