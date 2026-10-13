# Befunde untersuchen

`flakipype investigate` scannt und lässt dann den Agenten die Befunde
untersuchen und jeden mit Belegen erklären: was ihn verursacht, ob es ein
instabiler Test, instabile Infrastruktur, ein echter Fehler, ein
Konfigurationsproblem oder schon behoben ist, und was zu ändern ist. Der
Befehl liest nur; in deinen Repositories ändert sich nichts.

Dafür braucht es ein Modell (siehe [Modell verbinden](modell-verbinden.md)),
und es kostet Modell-Tokens: mit den Standardlimits höchstens 200.000 je
Befund und 1.000.000 je Lauf.

## Ausführen

```bash
flakipype scan                     # note the numbers of the findings
flakipype investigate              # the flaky jobs and the recurring errors
flakipype investigate --finding 3  # one finding; repeat --finding for more
flakipype investigate --finding 3f9c2a1b  # by reference from `scan --json`
flakipype investigate --all        # also "seen once" and "fixed"
```

Jedes Ergebnis zeigt die Einordnung und die Sicherheit, eine kurze
Zusammenfassung, die Ursache, einen Korrekturvorschlag, die Belege mit Zitaten
(Log-Zeilen, Commits, Dateien) und Gegenbelege, offene Fragen und wie die
Prüfung ausging:

```text
╭─ #1 octo-org/app › CI › test ──────────────────────────────────────────────╮
│ flaky test · confidence high                                               │
│                                                                            │
│ The E2E test asserts the row count before the second row is rendered.      │
│                                                                            │
│ Cause: …                                                                   │
│ Suggested fix: …                                                           │
│                                                                            │
│ Evidence                                                                   │
│  • log job 112720402394 lines 1010-1016: “Expected: 2 Received: 1 …”       │
│    …                                                                       │
╰─ flaky · review: accepted: … · 41,230 tokens, 6 rounds ────────────────────╯
```

Das sind Einschätzungen des Modells. Jedes Zitat wurde gegen das geprüft, was
die Werkzeuge geliefert haben, und ein zweiter Modelldurchgang hat die
Begründung geprüft; trotzdem sind es Urteile, keine vom Scan bewiesenen
Tatsachen.

## Wiederholte Läufe nutzen Urteile wieder

Ein fertiges Urteil wird gespeichert und wiederverwendet, bis der Befund einen
neueren Fehlschlag hat. `--fresh` untersucht erneut. Gescheiterte
Untersuchungen (ein Limit wurde erreicht, kein Urteil) werden nie gespeichert.

## Optionen und Ausgabe

| Option | Bedeutung |
| --- | --- |
| `--finding N` | Befund N untersuchen, oder den Befund mit einer Referenz aus `flakipype scan --json`; wiederholbar. `investigate` scannt erneut, und neue Läufe können die Nummern seit deinem Scan verschieben; eine Referenz bezeichnet immer denselben Befund. Im Chat wird nach `/resume` eine Nummer, die jetzt einen anderen Befund bezeichnet, einmal abgelehnt, und die Seitenleiste zeigt die neuen Nummern |
| `--all` | Jeden Befund statt nur instabiler Jobs und wiederkehrender Fehler |
| `--fresh` | Gespeicherte Urteile ignorieren |
| `--days`, `--repo`, `--owner` | Wie bei `flakipype scan` |
| `--json` | Ergebnisse als JSON auf stdout, mit dem vollständigen Scan unter `scan` |

Exit-Codes: 0 alle Untersuchungen abgeschlossen, 1 eine endete ohne Urteil
oder der Scan brach vorzeitig ab, 2 nicht eingerichtet.

Für Rückfragen nutzt du stattdessen [den Chat](chat-nutzen.md). Die Limits
stehen im Abschnitt `[agent]` der
[Konfiguration](../reference/konfiguration.md). So funktioniert es:
[der Agent](../explanation/agent.md).
