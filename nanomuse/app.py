"""Composition root: wires settings → stores, vault, Sentinel, tools, LLM, agent."""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime
from pathlib import Path

from nanomuse import prompts
from nanomuse.agent import MuseAgent
from nanomuse.agent.holds import Holds
from nanomuse.background import spawn
from nanomuse.calendar import CalendarFeeds
from nanomuse.cloud import CLOUD_KEY, DEFAULT_GUI_MODEL, model_url
from nanomuse.computer.link import ComputerLink
from nanomuse.config import CHATGPT_PROVIDER, PROTOCOLS, LLMSettings, Settings
from nanomuse.contacts import ContactBook
from nanomuse.goals import GoalStore
from nanomuse.llm import BaseLLM, catalogue, create_llm
from nanomuse.llm.catalogue import Provider
from nanomuse.logger import logger, setup_logging
from nanomuse.memory import Embedder, MemoryIndex, MemoryStore
from nanomuse.phone import PhoneLink
from nanomuse.phone.operator import AUTO_LANGUAGE, COMPUTER, PhoneOperator
from nanomuse.reminders import ReminderStore
from nanomuse.runtime import device, device_mcp_server
from nanomuse.sandbox import Sandbox
from nanomuse.search import WebSearchProvider
from nanomuse.sentinel import AuditLog, Sentinel
from nanomuse.skills import SkillLibrary
from nanomuse.tools import (
    AskUser,
    Browser,
    Calendar,
    Contacts,
    Files,
    Forget,
    Goals,
    MCPManager,
    PythonExecute,
    ReadEmails,
    Recall,
    Remember,
    Reminders,
    SendEmail,
    Shell,
    Skills,
    Terminate,
    ToolCollection,
    Triggers,
    WebFetch,
    WebSearch,
    playwright_available,
)
from nanomuse.tools.computer import ComputerAct, ComputerScreen, ComputerTask
from nanomuse.tools.phone import PhoneAct, PhoneScreen, PhoneTask
from nanomuse.triggers import TriggerStore
from nanomuse.ui import UI
from nanomuse.vault import CredentialVault


class NanoMuseApp:
    def __init__(
        self,
        settings: Settings,
        ui: UI,
        llm: BaseLLM | None = None,
        session_id: str | None = None,
        phone: PhoneLink | None = None,
    ):
        self.settings = settings
        self.ui = ui
        # The phone, when a server is around to hold its socket (the CLI has none).
        self.phone = phone
        setup_logging(settings.log_level, settings.data_dir / "logs")
        settings.ensure_dirs()
        self.session_id = (
            session_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        )

        self.vault = CredentialVault(settings.vault_file, settings.vault_key_file)
        self.memory = MemoryStore(settings.memory_db) if settings.memory.enabled else None
        self.embedder: Embedder | None = None
        self.attach_embedder()
        self.goals = GoalStore(settings.goals_db)
        self.reminders = ReminderStore(settings.reminders_db)
        self.triggers = TriggerStore(settings.triggers_db)
        self.calendar = CalendarFeeds(
            settings.connectors.calendar, vault=self.vault, cache_file=settings.calendar_cache
        )
        self.contacts = ContactBook(
            settings.connectors.contacts,
            vault=self.vault,
            own_file=settings.contacts_file,
            cache_file=settings.contacts_cache,
        )
        self.skills = SkillLibrary(settings.skills, own_dir=settings.skills_dir)
        self.audit = AuditLog(settings.audit_file, session_id=self.session_id)
        self.sentinel = Sentinel(
            settings.sentinel,
            audit=self.audit,
            ui=ui,
            vault=self.vault,
            persistent_approvals_file=settings.data_dir / "approvals.json",
        )
        self.llm = llm or self.make_llm()
        # Holds: the person takes the browser, the screen or the phone over for a while and
        # the tools wait (docs/browser.md). The server routes the cards; the CLI has none.
        self.holds = Holds(emit=getattr(ui, "on_hold", None))
        # the relay's hands model for the account (set by the hub from /v1/models' `for`)
        self.cloud_gui_model: str = ""
        # On the phone, the app's own capabilities (clipboard, calendar, alarms …) are an MCP
        # server on 127.0.0.1; it joins the configured ones as `device`.
        self.device = device()
        mcp_servers = list(settings.mcp.servers)
        if self.device is not None and self.device.has_host:
            mcp_servers.append(device_mcp_server(self.device))
        self.mcp = (
            MCPManager(
                mcp_servers,
                resolve=lambda v: self.vault.resolve(v, strict=False),
                redact=self.vault.redact,
            )
            if mcp_servers
            else None
        )
        # This computer's own screen and hands (docs/every-device.md); the link exists when
        # there is a display to look at, the tools only while [hands] is on.
        self.computer: ComputerLink | None = None
        if self.device is None:
            self.computer = ComputerLink(
                settings.hands,
                shots_dir=settings.agent.workspace / "screenshots",
                on_event=getattr(ui, "on_hands", None),
            )
        self.tools = self._build_tools()
        self.agent = MuseAgent(
            settings=settings,
            llm=self.llm,
            tools=self.tools,
            sentinel=self.sentinel,
            ui=ui,
            audit=self.audit,
            memory=self.memory,
            goals=self.goals,
            calendar=self.calendar,
            contacts=self.contacts,
            skills=self.skills,
            session_file=settings.data_dir / "sessions" / f"{self.session_id}.json",
        )

    def attach_embedder(self) -> None:
        """(Re)build the embedding client from the current settings and give the memory
        store its index — at start, and again when the model or the embeddings endpoint is
        changed in the app. Vectors already stored are kept per model, so a switch back is
        free."""
        old = self.embedder
        self.embedder = None
        if self.memory is not None and self.settings.memory.embeddings != "off":
            self.embedder = Embedder(
                self.settings.memory, self.settings.llm, api_key=self._embedding_key()
            )
        if self.memory is not None:
            self.memory.index = (
                MemoryIndex(self.memory, self.embedder) if self.embedder is not None else None
            )
        if old is not None:
            with contextlib.suppress(RuntimeError):
                spawn(old.close(), "closing the previous embedder")

    def _embedding_key(self) -> str:
        """The key for the embeddings endpoint, resolved from the vault when it refers
        there; the model's own key when none is set (same endpoint, same key)."""
        m = self.settings.memory
        key = m.embedding_api_key or self.settings.llm.api_key
        if self.vault.has_placeholders(key):
            key = self.vault.resolve(key, strict=False)
            if self.vault.has_placeholders(key):
                key = ""
        return key

    # ------------------------------------------------------------------ llm
    def make_llm(self) -> BaseLLM:
        """The model client. ``llm.api_key`` may be a ``{{vault:NAME}}`` reference (that is
        how a key entered in the app is stored); it is resolved here, for the HTTP client
        only — the model itself never sees it."""
        llm_settings = self.settings.llm
        if self.vault.has_placeholders(llm_settings.api_key):
            key = self.vault.resolve(llm_settings.api_key, strict=False)
            if self.vault.has_placeholders(key):
                logger.warning("llm.api_key refers to a vault secret that is not set: {}", key)
                key = ""
            llm_settings = llm_settings.model_copy(update={"api_key": key})
        return create_llm(llm_settings, data_dir=self.settings.data_dir)

    def llm_is_cloud(self) -> bool:
        """Whether the chat model is the account: the relay as the endpoint, or the Cloud
        key from the vault."""
        llm = self.settings.llm
        if CLOUD_KEY in str(llm.api_key or ""):
            return True
        base = str(llm.base_url or "").rstrip("/")
        return bool(base) and base == model_url(self.settings.cloud.base_url).rstrip("/")

    def cloud_signed_in(self) -> bool:
        """Whether the account is signed in on this runtime (the Cloud key is in the vault),
        whichever provider the chat model is."""
        return bool(self.vault.get(CLOUD_KEY))

    def cloud_models_on(self) -> bool:
        """Whether the account's models are a source: signed in and ``[cloud] models`` not
        switched off (the apps' *Use nanoMuse Cloud models*). Every automatic rung that
        would reach the relay (the hands, pictures, clips, the providers' listing) asks
        this, not :meth:`cloud_signed_in`; the sign-in is a different question."""
        return self.cloud_signed_in() and self.settings.cloud.models

    def chat_entry(self) -> Provider | None:
        """The catalogue entry the chat model is on: the one ``[llm] provider`` names, else
        the one whose host ``base_url`` is. None for the relay, the ChatGPT sign-in and a
        host the catalogue does not list (a local server, a gateway)."""
        llm = self.settings.llm
        if self.llm_is_cloud() or llm.provider == CHATGPT_PROVIDER:
            return None
        cat = catalogue.load()
        if llm.provider not in PROTOCOLS:
            return cat.get(llm.provider)
        return cat.by_base_url(llm.base_url)

    def hands_choice(self, default_only: bool = False) -> tuple[str, str]:
        """Where the hands' model comes from and which it is, in the order of the Models
        contract (§3): ``("gui", m)`` for an explicit ``[gui] model``; else ``("chat", m)``
        — the chat provider's own hands model when it is an own provider with vision, the
        chat model itself on a host the catalogue does not know; else ``("cloud", m)`` —
        the relay's hands model when the account is signed in and its models are on; else
        the chat model. ``default_only`` answers what it would be without ``[gui]``."""
        gui, llm = self.settings.gui, self.settings.llm
        if gui.model and not default_only:
            return "gui", gui.model
        cloud_model = self.cloud_gui_model or DEFAULT_GUI_MODEL
        if self.llm_is_cloud():
            return "cloud", cloud_model
        entry = self.chat_entry()
        if entry is None or entry.has("vision"):
            # an own provider with vision: its hands model; the ChatGPT sign-in reads
            # pictures; a host the catalogue does not list is whatever the person installed
            return "chat", (entry.defaults.get("hands") if entry else "") or llm.model
        if self.cloud_models_on():
            # a chat provider that cannot see, and an account that can (while its models are on)
            return "cloud", cloud_model
        return "chat", llm.model

    def gui_model(self, default_only: bool = False) -> str:
        """The model the hands use (contract C4): ``[gui] model`` when set; else what
        :meth:`hands_choice` resolves. ``default_only`` answers what it would be without
        ``[gui]``."""
        return self.hands_choice(default_only)[1]

    def make_gui_llm(self) -> BaseLLM:
        """The model for the GUI operator: ``[gui]`` where set, the main model's settings
        for the rest — so one provider and one key can serve both. Without a ``[gui]``
        model the hands follow :meth:`hands_choice`: the relay's hands model under the
        account key when that is the answer, even while the chat model is elsewhere."""
        gui, llm = self.settings.gui, self.settings.llm
        where, model = self.hands_choice()
        if where == "cloud" and not self.llm_is_cloud():
            merged = LLMSettings(
                provider="openai",
                model=model,
                base_url=model_url(self.settings.cloud.base_url),
                api_key=self.vault.get(CLOUD_KEY) or "",
                tool_mode="native",
                stream=False,
                temperature=0.0,
                max_tokens=llm.max_tokens,
                timeout=llm.timeout,
            )
            return create_llm(merged, data_dir=self.settings.data_dir)
        # `[gui] provider` may be a catalogue id, which brings its own endpoint
        gui_base = gui.endpoint
        own_host = bool(gui_base) and gui_base != llm.endpoint
        key = gui.api_key or (llm.api_key if not own_host else "")
        if self.vault.has_placeholders(key):
            key = self.vault.resolve(key, strict=False)
            if self.vault.has_placeholders(key):
                logger.warning("gui.api_key refers to a vault secret that is not set: {}", key)
                key = ""
        merged = LLMSettings(
            provider=gui.provider if gui.model else llm.provider,
            model=model,
            base_url=gui_base or llm.base_url,
            api_key=key,
            tool_mode="native",
            stream=False,
            # grounding wants the model's first choice, not a sample
            temperature=0.0,
            max_tokens=llm.max_tokens,
            timeout=llm.timeout,
            extra_headers=dict(llm.extra_headers) if not own_host else {},
            # the same host is reached the same way: through the chat model's proxy
            proxy=llm.proxy if not own_host else "",
        )
        return create_llm(merged, data_dir=self.settings.data_dir)

    # ------------------------------------------------------------------ tools
    def _build_tools(self) -> ToolCollection:
        s = self.settings
        ws: Path = s.agent.workspace
        self.sandbox = Sandbox(
            s.sandbox,
            workspace=ws,
            extra_roots=list(s.agent.extra_roots),
            data_dir=s.data_dir,
            # a skill's scripts and references are readable from inside the box
            ro_roots=[self.skills.own_dir, self.skills.builtin_dir] if s.skills.enabled else [],
            # and so are the tools the user shares with it (a CLI under ~/.nvm; its login)
            shared=list(s.sandbox.share),
            shared_ro=list(s.sandbox.share_read_only),
        )
        tools = ToolCollection(
            Terminate(),
            AskUser(ui=self.ui),
            Files(workspace=ws, extra_roots=list(s.agent.extra_roots)),
            Shell(workspace=ws, sandbox=self.sandbox),
            PythonExecute(workspace=ws, sandbox=self.sandbox),
            WebSearch(provider=WebSearchProvider(s.connectors.search, vault=self.vault)),
            WebFetch(),
            Goals(store=self.goals),
            Reminders(store=self.reminders),
            Triggers(store=self.triggers, available=self.trigger_kinds),
        )
        if self.memory is not None:
            tools.add(
                Remember(store=self.memory), Recall(store=self.memory), Forget(store=self.memory)
            )
        if s.connectors.email.enabled:
            tools.add(
                ReadEmails(settings=s.connectors.email, vault=self.vault),
                SendEmail(settings=s.connectors.email, vault=self.vault, book=self.contacts),
            )
        if s.connectors.calendar.enabled:
            tools.add(Calendar(feeds=self.calendar, workspace=ws))
        if s.connectors.contacts.enabled:
            tools.add(Contacts(book=self.contacts))
        if s.skills.enabled:
            tools.add(Skills(library=self.skills))
        if s.gui.enabled and self.phone is not None:
            tools.add(*self.phone_tools())
        if s.hands.enabled and self.computer is not None:
            tools.add(*self.computer_tools())
        if s.browser.enabled:
            tools.add(self.browser_tool())
        return tools

    def browser_tool(self) -> Browser:
        """The browser: Playwright here, or the phone's WebView through the phone link."""
        s = self.settings
        tool = Browser(
            headless=s.browser.headless,
            timeout_ms=s.browser.timeout_ms,
            workspace=s.agent.workspace,
            backend_mode=s.browser.backend,
            default_profile=s.browser.profile,
            link=self.phone,
            holds=self.holds,
        )
        if not playwright_available() and s.browser.backend != "device" and self.device is None:
            logger.warning(
                "browser.enabled=true but playwright is missing: pip install 'nanomuse[browser]' "
                "(the browser tool will use the phone's WebView when the app is connected)"
            )
        return tool

    def phone_tools(self) -> list[PhoneScreen | PhoneAct | PhoneTask]:
        """The three phone tools, sharing one link and one operator."""
        assert self.phone is not None
        gui = self.settings.gui
        act = PhoneAct(link=self.phone, gui=gui, holds=self.holds)

        def language() -> str:
            lang = self.settings.agent.language
            return AUTO_LANGUAGE if lang in ("", "auto") else lang

        operator = PhoneOperator(
            self.phone,
            gui,
            self.sentinel,
            act,
            self.ui,
            make_llm=self.make_gui_llm,
            language=language,
            traces_dir=self.settings.data_dir / "phone-traces",
            holds=self.holds,
        )
        self.phone_operator = operator
        return [
            PhoneScreen(link=self.phone, holds=self.holds),
            act,
            PhoneTask(link=self.phone, operator=operator, holds=self.holds),
        ]

    def computer_tools(self) -> list[ComputerScreen | ComputerAct | ComputerTask]:
        """The three tools for this computer's screen, sharing one link and one operator
        (the phone's operator loop, speaking the `computer_use` dialect)."""
        assert self.computer is not None
        gui = self.settings.gui

        async def app_gate(app_id: str, label: str) -> bool:
            # "Let <Muse> use <App>?" — the agent's name as the person set it
            muse = str(self.settings.agent.name or "nanoMuse")
            return await self.sentinel.allow_app(app_id, label, muse)

        act = ComputerAct(link=self.computer, gui=gui, holds=self.holds, app_gate=app_gate)

        def language() -> str:
            lang = self.settings.agent.language
            return AUTO_LANGUAGE if lang in ("", "auto") else lang

        operator = PhoneOperator(
            self.computer,  # type: ignore[arg-type]  # the same face as the phone link
            gui,
            self.sentinel,
            act,
            self.ui,
            make_llm=self.make_gui_llm,
            language=language,
            traces_dir=self.settings.data_dir / "computer-traces",
            dialect=COMPUTER,
            holds=self.holds,
        )
        self.computer_operator = operator
        return [
            ComputerScreen(link=self.computer, holds=self.holds),
            act,
            ComputerTask(link=self.computer, operator=operator, holds=self.holds),
        ]

    def set_hands_enabled(self, enabled: bool) -> None:
        """Turn this computer's screen tools on or off while running (the switch in the app)."""
        self.settings.hands.enabled = bool(enabled)
        if self.computer is None:
            return
        present = "computer_act" in self.tools
        if enabled and not present:
            self.tools.add(*self.computer_tools())
        elif not enabled and present:
            for name in ("computer_screen", "computer_act", "computer_task"):
                self.tools.remove(name)

    def set_gui_enabled(self, enabled: bool) -> None:
        """Turn the phone tools on or off while running (the switch in the app)."""
        self.settings.gui.enabled = bool(enabled)
        if self.phone is None:
            return
        present = "phone_act" in self.tools
        if enabled and not present:
            self.tools.add(*self.phone_tools())
        elif not enabled and present:
            for name in ("phone_screen", "phone_act", "phone_task"):
                self.tools.remove(name)

    def trigger_kinds(self) -> dict[str, bool]:
        """Which trigger kinds have their connector: mail needs the mailbox, event the calendar."""
        s = self.settings
        return {
            "mail": bool(s.connectors.email.enabled and s.connectors.email.imap_host),
            "event": bool(s.connectors.calendar.enabled and s.connectors.calendar.feeds),
            "hook": True,
        }

    async def start(self) -> NanoMuseApp:
        """Connect optional MCP servers. Call once before using the agent."""
        if self.mcp is not None:
            for tool in await self.mcp.connect():
                self.tools.add(tool)
        return self

    async def close(self) -> None:
        await self.tools.cleanup()
        if self.mcp is not None:
            await self.mcp.close()
        await self.llm.close()
        if self.embedder is not None:
            await self.embedder.close()
        if self.memory is not None:
            self.memory.close()
        self.goals.close()
        self.reminders.close()
        self.triggers.close()

    async def __aenter__(self) -> NanoMuseApp:
        return await self.start()

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ------------------------------------------------------------------ high-level ops
    async def run(self, task: str) -> str:
        return await self.agent.run(task)

    async def advance_goal(self, goal_id: str) -> str:
        goal = self.goals.get(goal_id)
        if goal is None:
            raise ValueError(f"no goal {goal_id}")
        if goal.status != "active":
            raise ValueError(f"goal {goal_id} is {goal.status}")
        self.agent.reset()
        return await self.agent.run(prompts.ADVANCE_GOAL_PROMPT.format(goal=goal.render()))


__all__ = ["NanoMuseApp"]
