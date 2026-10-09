from typing import ClassVar

from textual import on, work
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, ProgressBar, Static

from flakipype.config.settings import DEFAULT_BASE_URL
from flakipype.github.auth import browser_login_arguments
from flakipype.github.binary import GhInstallError
from flakipype.github.gh import GhCommandError
from flakipype.setup.doctor import RUN_SETUP, Check, CheckStatus, gh_check, github_check, llm_check
from flakipype.setup.service import InvalidSetupError, SetupDraft, SetupService

_STATUS_CLASSES = ("ok", "warning", "failed", "busy")
GH_BUTTON = "install-gh"
LOGIN_BUTTONS = ("login-browser", "check-login", "login-token")
_BYTES_PER_MEGABYTE = 1_000_000


def download_status(received: int, total: int | None) -> str:
    done = f"{received / _BYTES_PER_MEGABYTE:.1f}"
    if total is None:
        return f"Downloading gh… {done} MB"
    if received >= total:
        return "Verifying checksum and installing…"
    return f"Downloading gh… {done} of {total / _BYTES_PER_MEGABYTE:.1f} MB"


class StatusLine(Static):
    def show(self, status: str, text: str) -> None:
        self.remove_class(*_STATUS_CLASSES)
        self.add_class(status)
        self.update(text)

    def show_check(self, check: Check) -> None:
        # Inside the wizard its buttons are the next step, so "run setup" would be circular.
        hint = "" if check.next_step.startswith(RUN_SETUP) else check.next_step
        self.show(check.status.value, f"{check.detail}\n{hint}" if hint else check.detail)


class SetupWizard(App[bool]):
    """Full-screen form for the model endpoint and GitHub; returns True once saved."""

    CSS_PATH = "setup_wizard.tcss"
    TITLE = "flakipype setup"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, service: SetupService) -> None:
        super().__init__()
        self._service = service

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="form"):
            yield Static(
                "Connect flakipype to an Anthropic model and to GitHub. "
                "Secrets go to the system keyring and never into the config file.",
                classes="intro",
            )
            yield from self._compose_model_section()
            yield from self._compose_github_section()
            with Horizontal(id="save-row"):
                yield Static("", id="save-status")
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def _compose_model_section(self) -> ComposeResult:
        with Vertical(classes="section", id="model-section") as section:
            section.border_title = "1  Model · Anthropic Messages API"
            yield Label("Base URL (api.anthropic.com, Azure AI Foundry or a proxy)")
            yield Input(id="base-url", placeholder=DEFAULT_BASE_URL)
            yield Label("API key")
            yield Input(id="api-key", password=True)
            yield Label("Model (on Foundry: the deployment name)")
            yield Input(id="model", placeholder="e.g. claude-sonnet-4-5")
            with Horizontal(classes="row"):
                yield Button("Test connection", id="test-llm")
                yield StatusLine("", id="llm-status", classes="status")

    def _compose_github_section(self) -> ComposeResult:
        with Vertical(classes="section", id="github-section") as section:
            section.border_title = "2  GitHub"
            yield Label("Host (github.com or your GitHub Enterprise Server)")
            yield Input(id="host")
            yield Label("User or organisation to scan")
            yield Input(id="owner", placeholder="e.g. octo-org")
            with Horizontal(classes="row"):
                yield Button("Download gh", id=GH_BUTTON)
                yield StatusLine("", id="gh-status", classes="status")
            yield ProgressBar(id="gh-progress", show_eta=False)
            with Horizontal(classes="row"):
                yield Button("Log in with browser", id="login-browser")
                yield Button("Check login", id="check-login")
                yield StatusLine("", id="auth-status", classes="status")
            yield Label("…or log in with a personal access token")
            with Horizontal(classes="row"):
                yield Input(id="token", password=True, placeholder="token")
                yield Button("Use token", id="login-token")

    def on_mount(self) -> None:
        state = self._service.load()
        self.query_one("#base-url", Input).value = state.settings.llm.base_url
        self.query_one("#model", Input).value = state.settings.llm.model
        self.query_one("#host", Input).value = state.settings.github.host
        self.query_one("#owner", Input).value = state.settings.github.owner
        if state.has_api_key:
            self.query_one("#api-key", Input).placeholder = "stored - leave empty to keep it"
        if state.problem:
            self.query_one("#save-status", Static).update(state.problem)
        self.refresh_github()

    def draft(self) -> SetupDraft:
        return SetupDraft(
            base_url=self.query_one("#base-url", Input).value,
            model=self.query_one("#model", Input).value,
            host=self.query_one("#host", Input).value,
            owner=self.query_one("#owner", Input).value,
            api_key=self.query_one("#api-key", Input).value.strip(),
        )

    def _host(self) -> str:
        return self.query_one("#host", Input).value.strip().lower()

    def _status(self, widget_id: str) -> StatusLine:
        return self.query_one(f"#{widget_id}", StatusLine)

    # --- Model ---------------------------------------------------------------

    @on(Button.Pressed, "#test-llm")
    def start_llm_test(self) -> None:
        draft = self.draft()
        try:
            self._service.llm_endpoint(draft)
        except InvalidSetupError as error:
            self._status("llm-status").show("failed", str(error))
            return
        self._status("llm-status").show("busy", "Testing…")
        self._test_llm(draft)

    @work(thread=True, exclusive=True, group="llm")
    def _test_llm(self, draft: SetupDraft) -> None:
        check = llm_check(self._service, draft)
        self.call_from_thread(self._status("llm-status").show_check, check)

    # --- GitHub --------------------------------------------------------------
    # gh and login have separate status lines, workers and buttons, so one never resets the other.

    def _lock(self, *button_ids: str) -> None:
        for button_id in button_ids:
            self.query_one(f"#{button_id}", Button).disabled = True

    def _unlock(self, *button_ids: str) -> None:
        for button_id in button_ids:
            self.query_one(f"#{button_id}", Button).disabled = False

    def refresh_github(self) -> None:
        self._lock(GH_BUTTON, *LOGIN_BUTTONS)
        self._status("gh-status").show("busy", "Looking for gh…")
        self._status("auth-status").show("busy", "Checking login…")
        self._check_gh_then_login(self._host())

    @work(thread=True, exclusive=True, group="gh")
    def _check_gh_then_login(self, host: str) -> None:
        self._run_gh_then_login_checks(host)

    def _run_gh_then_login_checks(self, host: str) -> None:
        # Worker threads call this directly: starting another "gh" worker would cancel the caller.
        self.call_from_thread(self._show_gh_check, gh_check(self._service))
        self.call_from_thread(self._show_login_check, github_check(self._service, host))

    def _show_gh_check(self, check: Check) -> None:
        self.query_one("#gh-progress", ProgressBar).display = False
        self._status("gh-status").show_check(check)
        self.query_one(f"#{GH_BUTTON}", Button).disabled = check.status is CheckStatus.OK

    def _show_login_check(self, check: Check) -> None:
        self._status("auth-status").show_check(check)
        self._unlock(*LOGIN_BUTTONS)

    @on(Button.Pressed, "#check-login")
    def start_login_check(self) -> None:
        self._lock(*LOGIN_BUTTONS)
        self._status("auth-status").show("busy", "Checking login…")
        self._check_login(self._host())

    @work(thread=True, exclusive=True, group="login")
    def _check_login(self, host: str) -> None:
        self.call_from_thread(self._show_login_check, github_check(self._service, host))

    @on(Button.Pressed, f"#{GH_BUTTON}")
    def start_gh_install(self) -> None:
        self._lock(GH_BUTTON, *LOGIN_BUTTONS)
        self._status("gh-status").show("busy", "Connecting to github.com…")
        self._install_gh(self._host())

    @work(thread=True, exclusive=True, group="gh")
    def _install_gh(self, host: str) -> None:
        def report(received: int, total: int | None) -> None:
            self.call_from_thread(self._show_download_progress, received, total)

        try:
            self._service.install_gh(on_progress=report)
        except GhInstallError as error:
            self.call_from_thread(self._show_install_failure, str(error))
            return
        self._run_gh_then_login_checks(host)

    def _show_download_progress(self, received: int, total: int | None) -> None:
        bar = self.query_one("#gh-progress", ProgressBar)
        bar.display = True
        bar.update(total=total, progress=received)
        self._status("gh-status").show("busy", download_status(received, total))

    def _show_install_failure(self, message: str) -> None:
        self.query_one("#gh-progress", ProgressBar).display = False
        self._status("gh-status").show("failed", message)
        self._unlock(GH_BUTTON, *LOGIN_BUTTONS)

    @on(Button.Pressed, "#login-token")
    def start_token_login(self) -> None:
        token = self.query_one("#token", Input).value.strip()
        if not token:
            self._status("auth-status").show("failed", "Paste a token first.")
            return
        self._lock(*LOGIN_BUTTONS)
        self._status("auth-status").show("busy", "Logging in…")
        self._login_with_token(self._host(), token)

    @work(thread=True, exclusive=True, group="login")
    def _login_with_token(self, host: str, token: str) -> None:
        try:
            self._service.login_with_token(host, token)
        except (GhCommandError, OSError) as error:
            self.call_from_thread(self._show_login_failure, str(error))
            return
        self.call_from_thread(self._clear_token)
        self.call_from_thread(self._show_login_check, github_check(self._service, host))

    def _show_login_failure(self, message: str) -> None:
        self._status("auth-status").show("failed", message)
        self._unlock(*LOGIN_BUTTONS)

    def _clear_token(self) -> None:
        self.query_one("#token", Input).value = ""

    @on(Button.Pressed, "#login-browser")
    def browser_login(self) -> None:
        host = self._host()
        if self._service.find_gh() is None:
            self._status("auth-status").show("failed", "Download gh first.")
            return
        try:
            with self.suspend():
                self._service.browser_login(host)
        except SuspendNotSupported:
            command = " ".join(["gh", *browser_login_arguments(host)])
            self._status("auth-status").show(
                "warning", f"Cannot hand over this terminal. Run in a shell:\n{command}"
            )
            return
        self.start_login_check()

    # --- Save / cancel -------------------------------------------------------

    @on(Button.Pressed, "#save")
    def action_save(self) -> None:
        try:
            self._service.save(self.draft())
        except InvalidSetupError as error:
            self.query_one("#save-status", Static).update(f"Cannot save: {error}")
            return
        self.exit(result=True)

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.exit(result=False)
