# Wie Instabilität erkannt wird

Eine rote Pipeline ist kein Beleg für Instabilität: Echte Fehler zu finden
ist genau die Aufgabe von Pipelines. Ein Test ist instabil, wenn er *auf
demselben Code manchmal* fehlschlägt. flakipype trennt deshalb **Beweis** von
**Verdacht**, und nur der Beweis zählt. Alles hier ist reine Logik im Paket
`flaky`; kein Modell ist beteiligt. Die unbewiesenen Fälle zu beurteilen ist
Aufgabe des Agenten.

## Beweis: derselbe Code ist fehlgeschlagen und durchgelaufen

**Beim Rerun durchgelaufen (stark).** Ein Versuch eines Laufs ist
fehlgeschlagen, und ein späterer Versuch *desselben Laufs* ist durchgelaufen.
Gleicher Commit, gleiche Workflow-Datei, gleiche Eingaben – nur Glück oder
Umgebung haben sich geändert. Der klassische Flake nach dem Motto „einfach
noch mal laufen lassen“.

**Gleicher Commit durchgelaufen (mittel).** Ein Lauf ist fehlgeschlagen, aber
ein anderer Lauf desselben Workflows auf demselben Commit ist durchgelaufen,
zum Beispiel ein Push und ein manueller Dispatch. Schwächer, weil sich die
Läufe in Ereignis, Eingaben oder Umgebung unterscheiden können.
Pull-Request-Läufe (`pull_request`, `pull_request_target`) zählen hier nicht:
Sie testen den Merge des Heads mit dem Basisbranch, nicht den Head-Commit
selbst, also haben ein Erfolg beim Push und ein Fehlschlag im Pull Request
unterschiedlichen Code getestet. Ihre Reruns zählen trotzdem als „beim Rerun
durchgelaufen“.

Beide Regeln vergleichen identischen Code – das ganze Repository, nicht nur
den Workflow –, sodass Codeänderungen an anderer Stelle der Historie kein
Ereignis vortäuschen können. Ein Lauf, der nach einem Rerun weiterhin
fehlschlägt, ist nicht instabil, sondern kaputt.

Generierte Workflows ohne Datei im Repository (die `dynamic/…`-Läufe von
Dependabot) werden übersprungen: Ihr Name ändert sich mit jedem Update, und
im Repository gibt es nichts zu korrigieren.

## Urteile: flaky, seen once, fixed

Bewiesene Ereignisse werden nach Repository, Workflow, Job und erstem
fehlgeschlagenem Schritt gruppiert – über Commits und Branches hinweg, weil
die Ursache eines instabilen Tests oft monatelang besteht. Ein einzelnes
Ereignis reicht trotzdem nicht:

| Urteil | Regel | Warum |
| --- | --- | --- |
| **flaky** | Ereignisse in mindestens `scan.min_flaky_runs` Läufen (Standard 2) **und** der Workflow ist zwischen dem ersten und dem letzten davon durchgelaufen | Der Fehler kommt nach guten Phasen immer wieder |
| **seen once** | Weniger Läufe als `min_flaky_runs` | Ein einzelnes Ereignis kann ein Ausfall sein, ein abgestürzter Runner oder eine Korrektur außerhalb des Codes (eine Repository-Einstellung, ein Secret), gefolgt von einem Rerun |
| **fixed** | Genug Läufe, alle davon bevor der Workflow endgültig wieder durchlief, und nach dem letzten ist er durchgelaufen | Ein echter Fehler, der behoben wurde, z. B. ein Push ist zweimal fehlgeschlagen, die Pages-Einstellung wurde geändert, und ein Dispatch auf demselben Commit ist durchgelaufen |

Ein Job mit genug Läufen, der seit seinem letzten Fehlschlag nicht wieder
durchgelaufen ist, ist nicht behoben: Er zählt als **flaky** und wird
untersucht, wobei der Agent ihn immer noch als echten Fehler einstufen kann.

„Durchgelaufen“ heißt, dass der ganze Workflow-Lauf durchgelaufen ist. Ein
Lauf, in dem der Job durchlief, aber ein anderer Job fehlschlug, zählt nicht
als Erfolg; die Regel neigt also eher zu „fixed“ als zu „flaky“.

Nur Jobs mit dem Urteil **flaky** werden gerankt. Die **Flake-Rate** ist die
Zahl der Läufe mit einem Flake-Ereignis geteilt durch die abgeschlossenen
Läufe des Workflows im Zeitfenster. Rangfolge: die meisten betroffenen Läufe
zuerst, dann die höhere Rate, dann der jüngste. Jobs mit „seen once“ und
„fixed“ werden getrennt aufgeführt und nie gerankt.

## Verdacht: wiederkehrende Fehler

Instabilität, bei der niemand einen Rerun gestartet hat, ist für die
Beweisregeln unsichtbar: Ein Lauf schlägt fehl, niemand führt ihn erneut aus,
der nächste Commit läuft durch, und eine Woche später schlägt er auf dieselbe
Weise wieder fehl. Dasselbe Muster passt aber auch zu einem echten Fehler,
der mehrmals erwischt wurde, oder zu einem Feature-Branch, der rot bleibt,
bis er korrigiert ist. Um sie zu unterscheiden, muss man sich ansehen, was
sich zwischen dem Fehlschlag und dem nächsten Erfolg geändert hat – das ist
Urteilsvermögen, keine Regel.

Deshalb führt flakipype **wiederkehrende Fehler** getrennt auf: derselbe Job,
derselbe Schritt und derselbe Fehler-Fingerprint in mindestens
`min_flaky_runs` Läufen, auf beliebigen Branches, ohne Beweis. Sie sind als
„flaky or a real bug“ gekennzeichnet, haben keine Flake-Rate und werden nie
gerankt. Der Agent untersucht sie anhand der Commit-Diffs. Ein Fehler, den
derselbe Scan für denselben Job und Schritt als instabil bewiesen hat, wird
nicht noch einmal als wiederkehrender Fehler aufgeführt.

Ein generischer *exit code N* verbindet nie Läufe miteinander; das tut nur
eine echte Fehlerzeile.

## Was es kostet

Die Laufliste von GitHub zeigt nur den letzten Versuch jedes Laufs.
flakipype listet alle Läufe (etwa ein Aufruf pro 100 Läufe; das Zeitfenster
wird geteilt, wenn die Obergrenze von 1.000 Ergebnissen bei GitHub die Liste
abschneiden würde) und holt dann die Jobs für die Versuche, die instabil sein
können, und für den letzten Versuch jedes fehlgeschlagenen Laufs.
Abgeschlossene Versuche ändern sich nie, deshalb werden ihre Jobs dauerhaft
gecacht. Ein Scan liest die Jobs von höchstens `scan.max_job_reads` Versuchen
(Standard 500), zuerst die, die instabil sein können, und die neuesten
zuerst; der Rest wird als noch nicht geprüft gezählt und von späteren Scans
gelesen. Bei einem Ziel in Organisationsgröße (Hunderte Repositories) bauen
die ersten Scans den Cache deshalb über mehrere Läufe auf.

Es werden höchstens 1.000 Repositories eines Owners gescannt; eine längere
Liste wird abgeschnitten und in den Problemen des Scans genannt, und `--repo`
wählt andere aus. Ein Scan, den das Rate-Limit von GitHub gestoppt hat,
nutzt trotzdem jeden gecachten Job und jedes gecachte Log-Ergebnis.

Anfragen laufen nacheinander, wie GitHub es empfiehlt, um seine sekundären
Rate-Limits zu vermeiden. Auf einem echten Konto (18 Repositories, etwa
1.400 Läufe in 30 Tagen, etwa 70 fehlgeschlagene Läufe) dauerte der erste
Scan etwa 3 Minuten und ein wiederholter Scan etwa 50 Sekunden, fast
vollständig die Zeit, in der GitHub Seiten mit 100 Läufen beantwortet (je
etwa 3 Sekunden). Lauflisten lassen sich nicht cachen: Ein Rerun eines alten
Laufs behält sein Erstellungsdatum, also sieht ihn nur erneutes Auflisten.

## Fehlersignaturen

flakipype liest Job-Logs – zuerst bewiesen instabile Fehlschläge, dann die
anderen fehlgeschlagenen Jobs, innerhalb jeder Gruppe die neuesten zuerst,
bis zu `scan.max_log_downloads` pro Scan, gecacht – und gewinnt daraus eine
Signatur pro Log:

1. Die erste `##[error]`-Annotation, die nicht das generische
   *Process completed with exit code N* ist.
2. Gibt es nur die generische, die aussagekräftigste Zeile kurz davor:
   Zeilen mit `ERR!`, `Error:` (auch `TypeError:`, `AssertionError:` und
   andere Namen, die auf `Error` enden), `fatal:`, `Traceback`, `FAILED` und
   Namen, die auf `Exception` enden, gewinnen; Warnungen und Stack-Frames
   werden übersprungen.

Der Text wird normalisiert (alleinstehende Zahlen, Dauern, Hashes,
Zeitstempel und temporäre Pfade werden durch Platzhalter ersetzt), sodass
derselbe Fehler an einem anderen Tag oder mit verschobener Zeilennummer
denselben **Fingerprint** ergibt. Eine Kategorie (Timeout, Netzwerk,
Abhängigkeiten, …) ergibt sich aus Schlüsselwortregeln, die spezifischeren
zuerst. HTTP-Statuscodes (429, 502–504) zählen nur neben `HTTP/…`, `status`
oder ihrer Reason-Phrase, nie als bloße Zahl wie eine Zeilennummer oder eine
Testanzahl.

Logs schreibt jeder, der Code pushen kann, deshalb sind sie nicht
vertrauenswürdig: Terminal-Escape-Sequenzen und Steuerzeichen werden
entfernt, bevor etwas gespeichert oder angezeigt wird, und Logs erreichen das
Modell nur als Daten, nie als Anweisungen (siehe das
[Sicherheitsmodell](sicherheitsmodell.md)).

## Bekannte Grenzen

- Änderungen außerhalb des Repositorys (Einstellungen, Secrets, externe
  Dienste) sind in den Laufdaten nicht sichtbar; deshalb gibt es „seen once“
  und „fixed“.
- Wiederkehrende Fehler sind nur ein Verdacht, bis der Agent sie sich
  angesehen hat.
- Die Signatur-Heuristiken sind an echten Logs (Playwright, npm, Stryker)
  abgestimmt und werden besser werden; eine Änderung an ihnen erhöht eine
  Version, sodass gecachte Signaturen neu berechnet werden.
- Logs, die älter sind als die Aufbewahrungsfrist von GitHub (standardmäßig
  90 Tage), können nicht gelesen werden.
