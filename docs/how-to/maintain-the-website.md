# Maintain the website

The website lives in `site/` as plain HTML and CSS, with no build step. It is
published at <https://besessener.github.io/flakipype/>. It shares its layout,
sections and stylesheet with the [PlayMonkey](https://besessener.github.io/PlayMonkey/)
and [Archivist](https://besessener.github.io/Archivist/) pages; only the texts,
images, icon and the colour tokens at the top of `style.css` differ. A change
to the layout or to the shared part of `style.css` goes to all three sites.

## Once: switch GitHub Pages on

1. Open the repository's Settings → Pages.
2. Under **Source**, choose **GitHub Actions**.

## Change the content

1. Edit `site/index.html` or `site/style.css`. Texts are English and match
   the [README](../../README.md) and the [safety model](../explanation/safety-model.md);
   a claim on the page must be true of the code. Keep the status note current
   while features are missing.
2. Open the page locally, e.g. `uv run python -m http.server -d site`, and
   check light and dark (the system's colour scheme) and a phone-wide window.

As soon as a change under `site/` lands on `main`, the workflow `pages.yml`
publishes it. To start it by hand: Actions → Pages → **Run workflow**.

## Refresh the screenshots

The images in `site/img/` are the TUI's snapshot tests rendered to PNG, so
they show the fake world of the tests, never real repositories or names:

- `chat.png` from `tests/tui/__snapshots__/test_chat/test_chat_snapshot.raw`
- `fix.png` from `tests/tui/__snapshots__/test_chat_fix/test_fix_dialog_snapshot.raw`

The snapshots are SVG. After `uv run pytest tests/tui --snapshot-update`, copy
one to a file ending in `.svg` and take a 1482 × 1030 screenshot of it with any
Chromium, for example
`chromium --headless --hide-scrollbars --window-size=1482,1030 --screenshot=site/img/chat.png file://$PWD/chat.svg`.
