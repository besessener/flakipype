# Scan-JSON (`flakipype scan --json`)

Das Format ist über `schema_version` versioniert. Innerhalb einer Version
kommen nur Felder hinzu; das Umbenennen oder Entfernen eines Feldes erhöht
die Version.

## Schema-Version 1

```json
{
  "schema_version": 1,
  "owner": "octo-org",
  "host": "github.com",
  "window": {"start": "2026-09-09T12:00:00Z", "end": "2026-10-09T12:00:00Z"},
  "complete": true,
  "repositories": 18,
  "runs": 1396,
  "logs_not_read": 0,
  "attempts_not_read": 0,
  "problems": [],
  "min_flaky_runs": 2,
  "jobs": [
    {
      "finding": 1,
      "reference": "3f9c2a1b",
      "status": "flaky",
      "repository": "octo-org/app",
      "workflow": {"name": "CI", "path": ".github/workflows/ci.yml"},
      "job": "test",
      "step": "E2E (Electron under Xvfb)",
      "flaky_failures": 4,
      "affected_runs": 4,
      "total_runs": 509,
      "flake_rate": 0.0079,
      "signals": {"rerun_passed": 4, "same_commit": 0},
      "first_seen": "2026-09-30T14:02:11Z",
      "last_seen": "2026-10-07T09:28:45Z",
      "passing_since": "2026-10-07T09:17:20Z",
      "examples": ["https://github.com/octo-org/app/actions/runs/1/job/2"],
      "signatures": [
        {
          "category": "timeout",
          "message": "tests/e2e/scan.spec.ts:N:N › … · Error: expect(locator).toHaveCount(expected) failed · …",
          "fingerprint": "3f9a0c1b2d4e",
          "occurrences": 4
        }
      ]
    }
  ],
  "recurring_errors": [
    {
      "finding": 2,
      "repository": "octo-org/app",
      "workflow": {"name": "CI", "path": ".github/workflows/ci.yml"},
      "job": "test",
      "step": "Run npm ci",
      "runs": 2,
      "branches": ["dependabot/npm_and_yarn/typescript-7.0.2"],
      "first_seen": "2026-10-04T08:12:40Z",
      "last_seen": "2026-10-05T08:13:02Z",
      "examples": ["https://github.com/octo-org/app/actions/runs/3/job/4"],
      "signature": {"category": "dependencies", "message": "npm error code ERESOLVE", "fingerprint": "8d1e…"}
    }
  ]
}
```

Wie die Status entschieden werden: [wie Instabilität erkannt wird](../explanation/flake-erkennung.md).

### Oberste Ebene

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| `schema_version` | int | Formatversion, derzeit `1` |
| `owner`, `host` | string | Was gescannt wurde |
| `window.start`, `window.end` | UTC-Zeitstempel | Läufe, die in diesem Zeitraum erstellt wurden |
| `complete` | bool | `false`, wenn der Scan früh beendet wurde (Rate-Limit) |
| `repositories` | int | Gescannte Repositories (keine archivierten, keine Forks) |
| `runs` | int | Im Zeitfenster aufgelistete Workflow-Läufe |
| `logs_not_read` | int | Fehlgeschlagene Jobs, deren Log noch nicht gelesen wurde (Limit oder früher Abbruch) |
| `attempts_not_read` | int | Versuche, deren Jobs noch nicht gelesen wurden (`scan.max_job_reads` oder früher Abbruch); spätere Scans machen weiter |
| `problems` | Liste von Strings | Repositories oder Einträge, die nicht gelesen werden konnten |
| `min_flaky_runs` | int | Nötige Läufe für den Status `flaky` |
| `jobs` | Liste | Jobs mit nachgewiesenen Flake-Ereignissen: alle `flaky` in Rangfolge, dann `seen_once`, dann `fixed` |
| `recurring_errors` | Liste | Derselbe Fehler in mehreren Läufen ohne Nachweis; instabil oder ein echter Fehler, nie in der Rangfolge |

### `jobs[]`

| Feld | Bedeutung |
| --- | --- |
| `finding` | Die Nummer des Befunds, wie `flakipype scan` sie zeigt. Nummern gehören zu einem Scan: Ein späterer Scan (den `investigate` ausführt) kann anders nummerieren |
| `reference` | 8 Hex-Zeichen, die denselben Befund in jedem späteren Scan benennen; `flakipype investigate --finding REF` akzeptiert sie |
| `status` | `flaky`, `seen_once` (weniger Läufe als `min_flaky_runs`) oder `fixed` (alle Ereignisse liegen vor dem Zeitpunkt, ab dem der Workflow dauerhaft wieder bestand) |
| `repository`, `workflow.name`, `workflow.path`, `job`, `step` | Wo die Fehlschläge passieren; `step` ist der erste fehlgeschlagene Schritt, leer, wenn unbekannt |
| `flaky_failures` | Fehlgeschlagene Jobs mit Nachweis (ein Lauf kann mehrere Versuche beitragen) |
| `affected_runs` | Verschiedene Läufe mit einem solchen Fehlschlag |
| `total_runs` | Abgeschlossene Läufe (Erfolg oder Fehlschlag) dieses Workflows im Zeitfenster |
| `flake_rate` | `affected_runs / total_runs`, 4 Nachkommastellen; nur für `flaky` aussagekräftig |
| `signals.rerun_passed` | Fehlschläge in einem Versuch, den ein späterer Versuch desselben Laufs behoben hat |
| `signals.same_commit` | Fehlschläge von Läufen, deren Commit in einem anderen Lauf des Workflows bestanden hat |
| `first_seen`, `last_seen` | Wann der älteste und der neueste solche Fehlschlag abgeschlossen wurde |
| `passing_since` | Erster bestandener Lauf des Workflows nach dem letzten betroffenen Lauf, ohne die Reruns der betroffenen Läufe selbst; `null`, wenn es keinen gibt |
| `examples` | Bis zu 3 Job-URLs, neueste zuerst |
| `signatures[]` | Fehlersignaturen aus den bisher gelesenen Logs, häufigste zuerst |

### `recurring_errors[]`

| Feld | Bedeutung |
| --- | --- |
| `finding` | Die Nummer des Befunds; die Nummerierung setzt nach `jobs[]` fort |
| `reference` | Wie in `jobs[]` |
| `repository`, `workflow`, `job`, `step` | Wie in `jobs[]` |
| `runs` | Läufe, die mit diesem Fehler endeten |
| `branches` | Branches, auf denen diese Läufe waren |
| `first_seen`, `last_seen`, `examples` | Wie in `jobs[]` |
| `signature` | `category`, `message`, `fingerprint` des gemeinsamen Fehlers |

### `signatures[]`

| Feld | Bedeutung |
| --- | --- |
| `category` | `runner`, `resources`, `rate limit`, `network`, `dependencies`, `timeout`, `assertion`, `exit code` oder `other` |
| `message` | Normalisierter Fehlertext: Alleinstehende Zahlen werden zu `N`, Dauern zu `<duration>`, Hashes zu `<hex>`, Uhrzeiten zu `<time>`, temporäre Pfade zu `<tmp>` |
| `fingerprint` | 12 Hex-Zeichen; gleiche Fingerprints bedeuten denselben Fehler |
| `occurrences` | Fehlschläge dieses Jobs mit dieser Signatur |
