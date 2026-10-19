# Webseite pflegen

Die Webseite liegt unter `site/` als reines HTML und CSS, ohne Build-Schritt.
Sie erscheint auf <https://besessener.github.io/flakipype/>. Aufbau,
Abschnitte und Stylesheet teilt sie mit den Seiten von
[PlayMonkey](https://besessener.github.io/PlayMonkey/),
[Archivist](https://besessener.github.io/Archivist/) und
[WOMBOT](https://besessener.github.io/WOMBOT/); nur Texte, Bilder, Icon und die
Farbtokens oben in `style.css` unterscheiden sich. Eine Änderung am Aufbau oder
am gemeinsamen Teil von `style.css` gehört in alle vier Seiten.

## Einmalig: GitHub Pages einschalten

1. Öffne im Repository Settings → Pages.
2. Wähle unter **Source** den Eintrag **GitHub Actions**.

## Inhalt ändern

1. Bearbeite `site/index.html` oder `site/style.css`. Texte sind Deutsch,
   sprechen mit „du“ und passen zur [README](../../README.md) und zum
   [Sicherheitsmodell](../explanation/sicherheitsmodell.md); was die Seite
   verspricht, muss der Code halten. Halte den Stand-Hinweis aktuell, solange
   Funktionen fehlen.
2. Öffne die Seite lokal, z. B. mit `uv run python -m http.server -d site`,
   und prüfe Hell und Dunkel (Farben des Systems) und ein handybreites
   Fenster.

Sobald eine Änderung unter `site/` auf `main` landet, veröffentlicht der
Workflow `pages.yml` die Seite. Von Hand startest du ihn unter Actions →
Pages → **Run workflow**.

## Screenshots erneuern

Die Bilder in `site/img/` sind die Snapshot-Tests der TUI, als PNG gerendert.
Sie zeigen deshalb die Fake-Welt der Tests, nie echte Repositories oder Namen:

- `chat.png` aus `tests/tui/__snapshots__/test_chat/test_chat_snapshot.raw`
- `fix.png` aus `tests/tui/__snapshots__/test_chat_fix/test_fix_dialog_snapshot.raw`

Die Snapshots sind SVG. Kopiere nach `uv run pytest tests/tui --snapshot-update`
einen davon in eine Datei mit der Endung `.svg` und nimm mit einem beliebigen
Chromium einen Screenshot von 1482 × 1030 davon auf, zum Beispiel
`chromium --headless --hide-scrollbars --window-size=1482,1030 --screenshot=site/img/chat.png file://$PWD/chat.svg`.
