# Unbeaufsichtigte Läufe und Release

> Stand: umgesetzt. Einrichtung: [Zeitgesteuert ausführen](../how-to/zeitgesteuert-ausfuehren.md).

Der Chat braucht dich an der Tastatur. flakipype kann auch nach Zeitplan
arbeiten: `flakipype run` scannt, untersucht und öffnet Draft-Pull-Requests
für korrigierbare Befunde ohne Fenster, `flakipype daemon install` startet es
über einen systemd-User-Timer, und ein Installationsskript plus Smoke-Tests
auf vier Distributionen machen es installierbar. Jede Regel des
[Sicherheitsmodells](sicherheitsmodell.md) gilt unverändert; dass niemand
zusieht, bedeutet engere Limits, nicht lockerere.

## Umfang

- **Enthalten**: `flakipype run [--mode auto|ask]`; Fortsetzen von
  Verifikationen von Korrekturen über Läufe hinweg; Tageslimits über Läufe
  hinweg; eine Laufsperre; `flakipype daemon install|uninstall|status` für
  einen systemd-User-Timer; eine Einstellung `secrets.store` und ein
  sauberer Fehler für einen nicht erreichbaren Schlüsselbund; `install.sh`;
  das erste Release-Tag `v0.1.0`; ein CI-Smoke-Job auf Ubuntu, Debian,
  Fedora und Arch.
- **Nicht enthalten**: Reruns oder Dispatches auf dem Standardbranch, um
  Belege zu sammeln (headless Läufe führen nur flakipypes eigene
  Korrektur-Branches erneut aus); ein Modell, das entscheidet, was zu tun ist
  (die Schritte des Laufs sind im Code festgelegt); systemweite Dienste,
  Cron-Dateien, Container-Images; PyPI; ein Release-Workflow.

## `flakipype run`

Ein Lauf macht in dieser Reihenfolge, alles im Code und ohne
Orchestrator-Modell:

```text
lock ──▶ continue earlier verifications ──▶ scan ──▶ investigate ──▶ fix ──▶ poll until done or time is up ──▶ summary
```

1. **Sperre.** Ein zweites `flakipype run`, während eines läuft, endet sofort
   mit Code 3 (unten).
2. **Fortsetzen.** Die Pull Requests, die der letzte Lauf unverifiziert
   hinterlassen hat, werden übernommen
   ([Verifikationen](#verifikationen-über-läufe-hinweg)) und sofort in der
   Sitzung des neuen Laufs gespeichert, sodass ein Lauf, der später abstürzt,
   sie trotzdem weitergibt.
3. **Scan** des konfigurierten Owners, wie `flakipype scan` es macht. Ein
   Scan, den das Rate-Limit von GitHub gestoppt hat, beendet den Schritt
   hier: Untersuchungen würden nur sehen, wie GitHub ihre Werkzeuge
   ablehnt, also warten sie und die Korrekturen auf den nächsten Lauf.
4. **Untersuchen** der instabilen und wiederkehrenden Befunde, wie
   `flakipype investigate` es macht: Gecachte Urteile werden
   wiederverwendet, bis ein Befund einen neueren Fehlschlag hat. Ein Befund,
   dessen Untersuchung in einem früheren Lauf ohne Urteil endete
   (`no_verdict` oder eine Schleife, in beiden Modi), wird erst wieder
   untersucht, wenn er einen neueren Fehlschlag hat; gehen die Tokens aus
   oder tritt ein Modellfehler auf, wird es beim nächsten Mal erneut
   versucht. Nach `run.max_minutes` startet keine Untersuchung mehr.
5. **Korrigieren** von Befunden mit einem geprüften Urteil mit der Einstufung
   `flaky_test`, `flaky_infrastructure` oder `configuration`, die am höchsten
   gerankten zuerst, über dasselbe Werkzeug `fix` und dasselbe Policy-Gate
   wie im Chat ([Korrekturen](korrekturen.md)). Übersprungen werden: Befunde
   mit einem offenen Pull Request von flakipype oder ohne Push-Zugriff sowie
   Befunde, deren Korrektur ein früherer `auto`-Lauf nicht gepusht hat
   (ausführbarer Code, Warnungen, keine Korrektur, vom Reviewer abgelehnt
   oder ein gepushter
   Commit, zu dem sich kein Pull Request öffnen ließ), bis sie einen neueren
   Fehlschlag haben, damit ein Lauf nicht jeden Tag für dieselbe abgelehnte
   Korrektur bezahlt. Ein Modellfehler während der Korrektur oder ihrer
   Prüfung ist ein Problem des Laufs (Exit-Code 1) und wird beim nächsten
   Mal erneut versucht. Eine Korrektur bekommt höchstens die Zeit, die dem
   Lauf noch bleibt, auch wenn `fix.max_seconds` länger ist. Ein gepushter
   Commit, zu dem sich kein Pull Request öffnen ließ, zählt gegen die
   Pull-Request-Limits wie ein geöffneter.
6. **Abfragen** (nur `auto`) gestarteter Verifikationen alle 10 Sekunden,
   bis alle fertig sind oder `run.max_minutes` erreicht ist.
7. **Zusammenfassung** auf der Standardausgabe, die systemd an das Journal
   schickt.

Optionen: `--mode auto|ask` (Standard `auto`), `--json` sowie `--repo` und
`--days` wie bei `scan`. `--owner` muss den konfigurierten `github.owner`
nennen (Groß- und Kleinschreibung egal): Ein Lauf korrigiert nur diesen
Owner, ein anderer wird also mit Exit-Code 2 abgelehnt, bevor irgendetwas
gelesen wird; `scan` und `investigate` lesen auch andere Owner. Der
Fortschritt geht auf die Standardfehlerausgabe, und nur auf einem Terminal.

### Modi ohne Fenster

| | `auto` (Standard) | `ask` |
| --- | --- | --- |
| Scan, Untersuchung, Fixer und Reviewer | laufen | laufen |
| Push und Draft-Pull-Request (`critical`) | laufen im Rahmen der Budgets, wenn die Korrektur nur Dokumentation ändert und keine Warnung hat | laufen nicht: werden mit ihrem Diff berichtet |
| Verifikations-Reruns der eigenen Korrektur-Branches des Laufs (`write`) | laufen im Rahmen der Budgets | keine: Pull Requests früherer Läufe warten auf den nächsten `auto`-Lauf |
| Korrektur an [ausführbarem Code](korrekturen.md#modi) oder mit Warnung (verbirgt Fehlschläge, greift nach außen, `.github/`) | nicht gepusht, aufbewahrt | aufbewahrt |
| Eine nicht gepushte Korrektur | gemerkt, bis der Befund wieder fehlschlägt | nicht gemerkt |
| Draft-Pull-Request | immer | – |

Fast jede Korrektur eines flaky Tests ändert Code. Ein `auto`-Lauf öffnet
für sie keinen Pull Request, sondern bereitet sie vor, lässt sie prüfen und
meldet sie mit ihrem Diff; pushen kannst du sie aus dem Chat (unten). Die
Musterliste der Warnungen und der Reviewer sind dabei Hilfen, keine Sperre:
Die Sperre ist die Regel für ausführbaren Code.

`ask` ohne Fenster ist ein Probelauf, der trotzdem durch das Gate geht: Das
`HeadlessGate` beantwortet jede `write`- und `critical`-Anfrage mit `report
only`, und das Audit-Log hält das so fest. Eine nicht gepushte Korrektur
wird für den Chat in der Sitzung des Laufs aufbewahrt (unten). Ein headless
Lauf startet nie einen Rerun oder Dispatch auf etwas anderem als seinen
eigenen Korrektur-Branches; die Läufe des Scans werden nur gelesen.

### Zusammenfassung und Exit-Codes

```text
flakipype run · octo-org · auto · 2026-10-12 06:02–06:41 CEST
Scan: 42 repositories, 1,204 runs, 5 flaky, 2 recurring error
Investigated: 2 (1 flaky_test, 1 real_bug), 3 verdicts from the cache
Fixes: #1 octo-org/app › E2E › e2e: not pushed: it changes files that can run as code: tests/e2e/scan.spec.ts (kept for the chat)
       #2 octo-org/app › CI › lint: not fixed: real bug, which flakipype does not fix
       #4 octo-org/api › CI › test: not pushed: the diff has warnings: changes .github/: .github/workflows/ci.yml (kept for the chat)
       #6 octo-org/api › CodeQL › analyze: not investigated again: an earlier run ended without a verdict (no_verdict: …), and it has not failed since
Verification: octo-org/app#51: flakipype verification: E2E passed 3 of 3 runs on this branch.
Budget: pull requests today 1 of 3 · actions today 4 of 20 · tokens 412,000 of 1,000,000 (today 412,000 of 3,000,000)
```

Die Kopfzeile zeigt die lokale Zeit und Zeitzone des Rechners, wie der
Zeitplan des Timers und das Journal; `--json` und die gespeicherte Sitzung
bleiben bei UTC. Die Sitzung des Laufs in `/sessions` im Chat ist genauso
benannt, zum Beispiel `run 2026-10-12 06:02 CEST (auto)`.

`Fixes` hat eine Zeile für jeden instabilen Befund und jeden wiederkehrenden
Fehler: den Pull Request oder warum es keinen gibt (kein Urteil, eine
Einstufung, die flakipype nicht korrigiert, ein Urteil, dessen Prüfung nicht
laufen konnte, ein Limit, eine nicht gepushte Korrektur). Weitere Zeilen
nennen die Limits, die einen Schritt gestoppt haben (`Stopped by:`), und die
Fehler (`Problems:`). `--json` gibt dasselbe als ein Objekt mit
`schema_version` 1 aus, einschließlich des Diffs jeder nicht gepushten
Korrektur.

| Code | Bedeutung |
| --- | --- |
| 0 | Der Lauf ist fertig geworden; ein erreichtes Budget oder Zeitlimit ist ein normales Ende und wird in der Zusammenfassung genannt |
| 1 | Etwas war unvollständig: Der Scan hat vorzeitig aufgehört, GitHub oder das Modell sind fehlgeschlagen, eine Untersuchung oder eine Auslieferung ist fehlgeschlagen |
| 2 | Nicht bereit: keine Konfiguration, kein Key, ein nicht erreichbarer Schlüsselbund, `gh` nicht angemeldet oder sein Token abgelaufen (geprüft vor dem Scan), ein anderer `--owner` als der konfigurierte |
| 3 | Ein anderes `flakipype run` hält die Sperre |

## Verifikationen über Läufe hinweg

Ein Korrektur-Branch wird durch bis zu `fix.verify_runs` Läufe verifiziert,
was länger dauern kann, als ein Lauf dauern darf. Jeder Lauf wird als Sitzung
gespeichert, wie eine Chat-Sitzung, mit seinem Scan, seinen Urteilen,
aufbewahrten Korrekturen, gestarteten Läufen und geöffneten Pull Requests.
Erreicht ein Lauf `run.max_minutes`, bleiben unfertige Verifikationen in
seiner Sitzung. Der nächste Lauf übernimmt die Pull Requests, die der letzte
Lauf unverifiziert hinterlassen hat, mit den Läufen, die sie unter ihren
Nummern verfolgen, und ein `auto`-Lauf fragt sie ab, bis sie fertig sind oder
ihre Beobachtungszeit (`actions.watch_hours`) vorbei ist; der Kommentar am
Pull Request sagt dann, nach wie vielen Läufen und warum, wie im Chat. Ein
`ask`-Lauf bewahrt sie nur für den nächsten `auto`-Lauf auf. Reruns, die für
die Verifikation eines früheren Laufs gestartet werden, zählen gegen die
Aktionslimits des Laufs, der sie startet.

**Im Chat** listet `/sessions` Laufsitzungen mit der Markierung `run` auf.
`/resume` auf einer Laufsitzung startet eine neue Chat-Sitzung mit einer
Kopie des Scans, der Urteile und der aufbewahrten Korrekturen des Laufs, im
Modus `ask`. Die gestarteten Läufe und Pull Requests des Laufs bleiben bei
der Laufsitzung, sodass nur der Timer sie abfragt und nichts zweimal erneut
ausgeführt wird. Eine aufbewahrte Korrektur an ausführbarem Code oder mit
Warnungen funktioniert dann wie im Chat: `/fix N` zeigt die Bestätigung mit
den Warnungen und dem vollständigen Diff.

## Budgets

Die Limits eines Laufs sind die bestehenden Sitzungslimits; ein Lauf ist eine
Sitzung. Zusätzlich zählen Tageslimits jeden headless Lauf der letzten 24
Stunden, sodass ein kurzes Timer-Intervall sie nicht vervielfachen kann:

| Limit | Standard | Einstellung |
| --- | --- | --- |
| Draft-Pull-Requests pro Lauf | 3 | `fix.max_prs_per_session` |
| Reruns und Dispatches pro Lauf | 10 | `actions.max_per_session` |
| Tokens pro Lauf, Untersuchungen und Korrekturen zusammen | 1.000.000 | `agent.max_tokens_per_run` |
| Laufzeit pro Lauf | 120 Minuten | `run.max_minutes` (10–720) |
| Draft-Pull-Requests in 24 Stunden | 3 | `run.max_prs_per_day` (1–20) |
| Reruns und Dispatches in 24 Stunden | 20 | `run.max_actions_per_day` (1–200) |
| Tokens in 24 Stunden | 3.000.000 | `run.max_tokens_per_day` (10k–50M) |

Pull Requests und Aktionen in 24 Stunden werden aus dem Audit-Log gezählt
(Einträge mit dem Ursprung `run`, die ausgeführt wurden); Tokens aus den
Laufsitzungen. Der Chat zählt nicht gegen die Tageslimits, und Läufe zählen
nicht gegen die des Chats. Ein erreichtes Limit stoppt, was es begrenzt:
keine weiteren Korrekturen nach dem Pull-Request-Limit, keine Untersuchung
mehr, wenn die heutigen Tokens aufgebraucht sind, und keine weitere Korrektur
nach einem Token-Limit (eine bereits laufende Korrektur endet trotzdem an
ihrem eigenen `fix.max_tokens`); das Abfragen von Verifikationen geht im
Rahmen des Aktionslimits weiter. Die Zusammenfassung nennt das Limit.

## Neben dem Chat laufen

- **Laufsperre.** `run` hält für seine gesamte Dauer eine exklusive
  SQLite-Sperre auf `$XDG_DATA_HOME/flakipype/run.lock`; das Betriebssystem
  gibt sie frei, wenn der Prozess stirbt. Ein zweiter Lauf endet mit Code 3
  und rührt nichts an.
- **Datenbank.** Die Cache-Datenbank nutzt das WAL-Journal von SQLite mit
  einem Busy-Timeout, sodass Chat und Lauf gleichzeitig lesen und schreiben
  können. SQLite wendet dieses Timeout nicht auf den Wechsel zu WAL an,
  deshalb wiederholt das Öffnen des Caches den Wechsel selbst, bis zum
  selben Timeout.
- **Doppelte Pull Requests.** Chat und Lauf können denselben Befund
  gleichzeitig korrigieren. Die Auslieferung sucht direkt vor dem Anlegen
  des Branchs noch einmal nach einem offenen Pull Request von flakipype für
  den Befund und verlinkt stattdessen diesen.
- **Audit.** Einträge aus Läufen haben den Ursprung `run`, neben `model` und
  `command`. Verifikations-Reruns und -Dispatches werden ebenfalls
  festgehalten, als `verify_rerun` und `verify_dispatch` mit der Antwort
  `covered by the push`; das tägliche Aktionslimit zählt sie.

## Secrets unter systemd

Ein User-Timer läuft oft ohne Desktop-Sitzung. Dann fehlt der
Schlüsselbund des Systems (keyring weicht auf die `0600`-Datei aus, die leer
ist, wenn die Einrichtung den Key im Schlüsselbund gespeichert hat), oder er
ist gesperrt. Deshalb:

- Die Einstellung `secrets.store` ist `auto` (der Schlüsselbund, wo es einen
  gibt, sonst die Datei), `keyring` oder `file`.
  `flakipype setup --non-interactive
  --secret-store file --api-key-stdin` speichert den Key in
  `~/.config/flakipype/secrets.json` (Modus `0600`), die ein Timer ohne
  Sitzung lesen kann.
- Ein gesperrter oder nicht erreichbarer Schlüsselbund ist ein typisierter
  Fehler: Exit-Code 2 und genau dieser nächste Schritt, nie ein Traceback.
- `doctor` sagt, welcher Speicher den Key hält.
- `daemon install` prüft, bevor es irgendetwas installiert (unten).

Das GitHub-Token bleibt die Anmeldung von `gh`. Bewahrt `gh` es im
Schlüsselbund auf, gilt dasselbe für `gh`; `gh auth login --insecure-storage`
bewahrt es stattdessen in der eigenen Konfigurationsdatei von `gh` auf
([Zeitgesteuert ausführen](../how-to/zeitgesteuert-ausfuehren.md)).

## `flakipype daemon`

| Befehl | Macht |
| --- | --- |
| `daemon install [--schedule S] [--mode auto\|ask]` | Prüft, schreibt die Units, `systemctl --user daemon-reload`, aktiviert und startet den Timer |
| `daemon install --print` | Gibt die Units aus und ändert nichts |
| `daemon uninstall` | Deaktiviert den Timer und entfernt die Units, die flakipype geschrieben hat |
| `daemon status` | Nächster und letzter Start des Timers, das letzte Ergebnis und der Exit-Status sowie die Zusammenfassung des letzten Laufs aus dem Journal |

`--schedule` nimmt einen systemd-Kalenderausdruck, geprüft mit
`systemd-analyze calendar`; Standard `daily`. Die Units landen in
`$XDG_CONFIG_HOME/systemd/user/`:

```ini
# flakipype.service, generated by flakipype
[Unit]
Description=flakipype: find and fix flaky GitHub Actions pipelines

[Service]
Type=oneshot
ExecStart=/home/me/.local/bin/flakipype run --mode auto
TimeoutStartSec=730min
Nice=10
```

```ini
# flakipype.timer, generated by flakipype
[Unit]
Description=Run flakipype on a schedule

[Timer]
OnCalendar=daily
RandomizedDelaySec=15min
Persistent=true

[Install]
WantedBy=timers.target
```

- `ExecStart` ist der absolute Pfad des laufenden `flakipype`, weil der
  `PATH` einer User-Unit `~/.local/bin` nicht enthält.
- `TimeoutStartSec` ist der höchste erlaubte Wert für `run.max_minutes` (720)
  plus 10 Minuten. Das ist eine Rückfallgrenze: Der Lauf behält sein eigenes
  `run.max_minutes`, und eine spätere Änderung dieser Einstellung braucht
  keine neue Unit. Ein Schritt, der beim Erreichen des Limits schon läuft
  (der Scan, eine Untersuchung, der letzte Modellaufruf einer Korrektur),
  wird trotzdem fertig, sodass ein Lauf ein paar Minuten nach
  `run.max_minutes` enden kann, aber nie auch nur in der Nähe des Limits der
  Unit.
- `Type=oneshot` bedeutet, dass systemd den Dienst nie zweimal gleichzeitig
  startet; die Laufsperre deckt manuelle Läufe ab.
- Unit-Dateien, die flakipype nicht geschrieben hat (keine Zeile
  `generated by flakipype`), werden nie überschrieben oder entfernt.

**Prüfungen vor der Installation.** `daemon install` prüft den Zeitplan mit
`systemd-analyze calendar` und führt
`systemd-run --user --wait --pipe --collect <flakipype> doctor` aus, sodass
`doctor` in derselben Umgebung läuft wie später der Timer. Schlägt eines
davon fehl, wird nichts geschrieben, und die Ausgabe sagt, warum,
typischerweise der Schlüsselbund. Der Pfad zur ausführbaren Datei und der
Zeitplan dürfen keine Zeichen enthalten, die einer Unit-Datei Zeilen
hinzufügen könnten. Lehnt systemd ab, nachdem die Dateien geschrieben sind,
sagt die Meldung, wo sie liegen und dass `daemon uninstall` sie entfernt.
Ohne Lingering (`loginctl show-user` meldet `Linger=no`) sagt eine Warnung,
dass der Timer nur läuft, solange du angemeldet bist, und dass
`loginctl enable-linger` das ändert; flakipype führt es nicht selbst aus.

## Installationsskript

`install.sh` im Wurzelverzeichnis des Repositorys, POSIX-`sh`, für eine
Benutzerinstallation ohne root:

```bash
curl -fsSLO https://raw.githubusercontent.com/besessener/flakipype/v0.1.0/install.sh
sh install.sh
```

1. Prüft Linux, `x86_64` oder `aarch64`, glibc sowie `curl`, `tar`,
   `sha256sum` und `git`; fehlt eines, wird es mit dem zu installierenden
   Paket genannt.
2. Nutzt `uv` aus dem `PATH`, wenn es eines gibt. Andernfalls lädt es das im
   Skript festgelegte `uv`-Release von `github.com/astral-sh/uv/releases`
   herunter, prüft das Tarball gegen die veröffentlichte `.sha256`-Datei des
   Releases und installiert `uv` nach `~/.local/bin`. Eine Abweichung bricht
   ab und installiert nichts.
3. Führt `uv tool install --force
   git+https://github.com/besessener/flakipype@v0.1.0` aus. Das Tag ist
   dasjenige, mit dem das Skript veröffentlicht wurde. uv nimmt ein Python
   3.12 oder neuer vom System oder lädt eines herunter, das es selbst prüft.
4. Gibt den nächsten Schritt aus (`flakipype setup`) und einen Hinweis, wenn
   `~/.local/bin` nicht im `PATH` liegt.

`FLAKIPYPE_SOURCE` installiert stattdessen aus einem lokalen Checkout, für
die Smoke-Tests. `uv tool install git+…` bleibt für alle dokumentiert, die
`uv` schon haben.

## Release

Die Version ist `0.1.0` in `pyproject.toml`, und `install.sh` nennt das Tag
`v0.1.0`; ein Unit-Test prüft, dass beide übereinstimmen. Das Tag auf `main`
und das GitHub-Release daraus werden von Hand erstellt. Es gibt keinen
Release-Workflow und kein PyPI-Paket.

## Smoke-Tests

Der Job `smoke` in `.github/workflows/ci.yml`, bei Pull Requests und Pushes
auf `main`, und ausführbar mit `act pull_request -j smoke`. Eine Matrix aus
Containern, Images per Digest festgelegt: `ubuntu:24.04`, `debian:12`,
`fedora:latest` und `archlinux:latest`. Jeder installiert als root `curl`,
`git` und `systemd` (und `ca-certificates` oder `tar`, wo das Image sie nicht
hat) und führt dann `tests/smoke/smoke.sh` als neuer Benutzer ohne root aus,
das:

1. `install.sh` mit `FLAKIPYPE_SOURCE` auf eine Kopie des Checkouts ausführt,
   was auch den geprüften `uv`-Download testet, da kein Image `uv` hat;
2. `flakipype --version` gegen `pyproject.toml` prüft;
3. prüft, dass `flakipype doctor` ohne Konfiguration mit Code 1 endet und auf
   `flakipype setup` verweist;
4. die Units mit `daemon install --print` rendert, prüft, dass `ExecStart`
   den installierten Befehl startet, und beide Units mit
   `systemd-analyze verify` prüft.

Der Job darf das Repository nur lesen und checkt ohne Zugangsdaten aus, wie
die anderen Jobs. Echtes GitHub und ein echtes Modell werden nicht genutzt;
`run` selbst wird im Job `test` mit GitHub-Fakes im Speicher und einem
Fake-Modell getestet.

## Wo es im Code liegt

- **`unattended`** (auf der Ebene von `tui`, unabhängig davon): der
  Lauf-Service mit den Schritten oben und seinem Bericht (`service.py`), die
  Tageslimits (`limits.py`) und was ein Lauf vom letzten übernimmt
  (`carry.py`). Er nutzt den Workspace des Chats und die Services
  `investigate`, `fix` und `actions` so, wie der Chat es tut.
- **`agent`**: das `HeadlessGate` neben dem Policy-Gate (`tools.py`).
- **`setup`**: `daemon.py` rendert die Units (reiner Text) und installiert
  sie über einen Befehlsausführer, den es übergeben bekommt.
- **`store`**: die Laufsperre (`lock.py`), WAL, Laufsitzungen, die
  Korrekturen, die ein Lauf nicht gepusht hat, die Untersuchungen, die ohne
  Urteil endeten, und Audit-Einträge seit einem Zeitpunkt.
- **`config`**: `[run]`, `[secrets]` und die Wahl des Speichers.
- **`fix`** und **`actions`**: der Ursprung `run`, auditierte
  Verifikationsläufe, die Übernahme von Pull Requests und Läufen, die Suche
  nach einem offenen Pull Request vor der Auslieferung und typisierte Fehler
  für eine nicht erstellte Korrektur und eine fehlgeschlagene Auslieferung.
- **`investigate`**: Laufsitzungen in `/sessions` und `/resume`.
- **`cli`**: `run` und `daemon` (`run_command.py`, `run_report.py`,
  `daemon_commands.py`), verdrahtet in `wiring.py`.

## Tests

- Der Lauf-Service über GitHub-Fakes im Speicher und einem Fake-Agenten und
  -Fixer, mit einer einstellbaren Uhr: beide Modi, eine Korrektur mit
  Warnungen, eine an ausführbarem Code, eine abgelehnte Korrektur, die nicht
  erneut versucht wird (auch in einem Probelauf), jedes Limit, das Zeitlimit
  mit übrig gebliebenen Verifikationen, die der nächste `auto`-Lauf zu Ende
  führt, eine fehlgeschlagene Auslieferung, die Sitzung, die er für den Chat
  hinterlässt.
- Die echte Verdrahtung in `open_run` gegen den `gh`-Stub: Ein Lauf in `ask`
  meldet nur (`report only`) und schickt keinen schreibenden Aufruf an
  GitHub; nach den Pull Requests, die Läufe heute schon geöffnet haben, lehnt
  er jede weitere Korrektur mit der Budget-Meldung ab.
- Eine Zeile für jeden Befund, der nicht korrigiert wurde, und
  Untersuchungen ohne Urteil, die der nächste Lauf bis zu einem neueren
  Fehlschlag überspringt.
- Die tägliche Nutzung aus Audit-Einträgen und die Limits pro Lauf, die sie
  übrig lässt.
- Die Laufsperre zweimal gehalten; WAL auf einer Cache-Datei.
- `/resume` einer Laufsitzung: eine neue Sitzung mit den nicht gepushten
  Korrekturen des Laufs, ohne seine Pull Requests.
- Die exakten Unit-Dateien; Installation, Deinstallation und Status gegen
  einen Fake-Befehlsausführer, einschließlich eines fehlschlagenden
  `doctor`, fremder Unit-Dateien und eines abgelehnten Starts.
- Der Schlüsselbund-Fehler und jeder Wert von `secrets.store`.
- Die Zusammenfassung, ihr JSON und jeder Exit-Code von `run`; die
  `daemon`-Befehle.
- `install.sh` und der Smoke-Test mit ShellCheck (`shellcheck-py`) in
  `poe check`, ein Test, dass das Skript die Version aus `pyproject.toml`
  installiert, und Ende-zu-Ende im Smoke-Job.
