// The page around the phone: the language, the status line, the lines to try, and the two
// buttons. The phone is MobileGym in a frame on this origin, booted and framed by MobileGym's own
// scripts (state-builder.js powers it on into #demo-frame and runs the State Builder; boot-hero.js
// runs the gesture keys and the power button). The nanoMuse app on the phone exposes
// window.__NANOMUSE__ on the frame's window (demo/mobilegym/apps/nanoMuse/host.ts), which is how
// a tap here becomes text in the chat there. The whole stage fits one screen: the phone is scaled
// to the room there is beside the panel.
(function () {
  "use strict";

  var root = document.documentElement;
  var frame = document.getElementById("demo-frame");
  var status = document.getElementById("status");
  var lookGroup = document.getElementById("group-look");
  // ?embed=1 (the inline script in index.html sets data-embed): this page is the frame on the
  // project site, nanomuse.cn. The site has the header, so ours is hidden (page.css); links
  // out of the page open in the top window, not inside the frame; the site tells us its
  // language and theme over postMessage ({type: "nanomuse:lang", lang} / {type: "nanomuse:theme",
  // theme}), the first paint taking them from ?lang= and ?theme=. Nothing on this page
  // scrolls, so a wheel turned over the frame reaches the site by itself (the browser hands a
  // scroll on to the parent when the frame has nowhere to go).
  var embed = root.getAttribute("data-embed") === "1";
  var EMBEDDERS = ["https://nanomuse.cn", "https://www.nanomuse.cn", "https://nano-muse.github.io"];
  // the page that holds the frame, when it is one of ours (a local preview of the site counts
  // while this page is served locally too)
  var embedder = (function () {
    var o = "";
    try {
      var anc = location.ancestorOrigins;
      o = anc && anc.length ? anc[0] : document.referrer ? new URL(document.referrer).origin : "";
    } catch (e) {
      o = "";
    }
    if (EMBEDDERS.indexOf(o) >= 0) return o;
    if (/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(o) && /^(localhost|127\.0\.0\.1)$/.test(location.hostname)) return o;
    return "";
  })();

  // ---- language -------------------------------------------------------------------------
  function lang() {
    return root.getAttribute("data-lang") === "zh" ? "zh" : "en";
  }
  function setLang(l) {
    root.setAttribute("data-lang", l);
    root.lang = l === "zh" ? "zh-CN" : "en";
    document.title = l === "zh" ? "nanoMuse · 在线体验" : "nanoMuse · Try it in the browser";
    try {
      localStorage.setItem("nm-lang", l);
    } catch (e) {
      /* private mode */
    }
    phoneLang();
    render();
  }
  // The phone has a language of its own (MobileGym's Settings; its default is Chinese) and
  // nanoMuse's welcome page, the capsule and the notifications follow it. The switch up here is
  // the one a visitor sees, so the phone follows it: on the first boot and on every change.
  // The phone follows the page's language: its own strings, and the Muse's replies (the
  // hosted runtime's reply language, so what it reads on a Chinese screen is told in the
  // page's language).
  function phoneLang() {
    var w = phoneWindow();
    var api = w && w.__OS__ && w.__OS__.locale;
    try {
      if (api && typeof api.setLocale === "function") api.setLocale(lang() === "zh" ? "zh-Hans" : "en");
      var h = w && w.__NANOMUSE__;
      if (h && typeof h.language === "function") h.language(lang());
    } catch (e) {
      /* a phone that is going away */
    }
  }
  document.getElementById("lang").addEventListener("click", function () {
    setLang(lang() === "zh" ? "en" : "zh");
  });
  if (embed) {
    window.addEventListener("message", function (ev) {
      if (EMBEDDERS.indexOf(ev.origin) < 0 && ev.origin !== embedder) return;
      var d = ev.data;
      if (!d) return;
      if (d.type === "nanomuse:lang" && (d.lang === "zh" || d.lang === "en") && d.lang !== lang()) setLang(d.lang);
      if (d.type === "nanomuse:theme") {
        if (d.theme === "dark") root.setAttribute("data-theme", "dark");
        else root.removeAttribute("data-theme");
      }
    });
    document.querySelectorAll('a[href^="http"]').forEach(function (a) {
      a.setAttribute("target", "_top");
    });
  }
  function tr(en, zh) {
    return lang() === "zh" ? zh : en;
  }

  // ---- what the showcase offers ---------------------------------------------------------
  var info = null;
  fetch("/api/demo/info", { cache: "no-store" })
    .then(function (r) {
      return r.ok ? r.json() : null;
    })
    .then(function (i) {
      info = i;
      if (i && lookGroup && !i.image_model) {
        // no image model on this showcase: the lines stay visible, but say why they will not draw
        lookGroup.classList.add("off");
        lookGroup.querySelectorAll(".chip").forEach(function (b) {
          b.disabled = true;
        });
        var why = document.getElementById("look-why");
        if (why) {
          why.innerHTML =
            '<i class="en">No image model here, so the Muse keeps its dragon look.</i>' +
            '<i class="zh">这里没有配图像模型，Muse 保持小龙的样子。</i>';
          why.classList.remove("hidden");
        }
      }
      render();
    })
    .catch(function () {
      /* the status line manages without */
    });

  // ---- the phone -----------------------------------------------------------------------
  // state-builder.js puts the phone's frame into #demo-frame when the boot button is pressed, and
  // the boot button back when Power off is. The page presses the button for the visitor once.
  function phoneWindow() {
    var f = frame.querySelector("iframe");
    try {
      return f ? f.contentWindow : null;
    } catch (e) {
      return null;
    }
  }
  function powerOn() {
    var btn = document.getElementById("demo-boot-btn");
    if (btn) btn.click();
  }

  // ---- the phone's nanoMuse app ---------------------------------------------------------
  var hostWindow = null; // the frame's window the host below belongs to
  var host = null; // window.__NANOMUSE__ of the frame
  var state = null; // what it last told us
  var launched = false;
  var flash = null; // a short message in the status line, over the regular one

  // A Muse from an earlier visit whose time is up, or that the server no longer knows.
  function over(s) {
    return !!(s && s.demo) && (Date.now() / 1000 > s.demo.expiresAt || s.link === "unauthorized");
  }

  var renewedAt = 0; // when the page started a fresh Muse by itself
  function renewing() {
    return renewedAt > 0 && Date.now() - renewedAt < 20000;
  }
  function adopt(w) {
    var api = w && w.__NANOMUSE__;
    if (!api || host) return !!host;
    host = api;
    hostWindow = w;
    api.subscribe(function (s) {
      if (host !== api) return; // a phone that was powered off since
      state = s;
      // Coming back to a Muse that is gone: start a fresh one without being asked (once).
      if (!renewedAt && over(s)) {
        renewedAt = Date.now();
        Promise.resolve(api.reset()).catch(function () {
          /* the status line says to Start over */
        });
      }
      render();
    });
    return true;
  }
  function forget() {
    host = null;
    hostWindow = null;
    state = null;
    launched = false;
    render();
  }

  // Bring nanoMuse to the front once the simulated phone has booted (a beat after
  // __OS__ appears, so the launcher is there to animate from).
  function launch(w) {
    if (launched || !host || !w || !w.__OS__) return;
    launched = true;
    phoneLang();
    setTimeout(function () {
      try {
        host.open();
      } catch (e) {
        /* the person can open it on the phone */
      }
    }, 1200);
  }

  // nanoMuse's icon at the top of the dock beside the phone (compose.mjs puts it there): a tap
  // brings the app to the front — or turns the phone on — and it is lit while the app is on
  // the screen.
  var dockApp = document.querySelector("[data-nanomuse-open]");
  function showApp() {
    if (!phoneWindow()) powerOn();
    else if (host) host.open();
  }
  function lightDock() {
    if (!dockApp) return;
    var front = false;
    if (host) {
      try {
        front = !!host.state().front;
      } catch (e) {
        /* a phone that is going away */
      }
    }
    dockApp.setAttribute("aria-pressed", front ? "true" : "false");
  }
  if (dockApp) dockApp.addEventListener("click", showApp);

  // The phone comes and goes (Power off, Click to start); follow whichever frame is there.
  setInterval(function () {
    var w = phoneWindow();
    if (!w) {
      if (host) forget();
      lightDock();
      return;
    }
    if (host && hostWindow !== w) forget();
    adopt(w);
    launch(w);
    lightDock();
  }, 250);

  // ---- the stage fits the screen ----------------------------------------------------------
  // MobileGym's stylesheet scales the phone to the viewport's height alone (and not below 0.7).
  // Here the phone shares the row with the panel, has a bezel, and its chrome stands beside it
  // (≥1280px) or under it (below); the scale comes from the room left for all of that, and
  // the margins take back the phantom space of the unscaled layout box.
  var hero = document.getElementById("demo");
  var layout = document.querySelector(".demo-layout");
  var wrap = document.querySelector(".demo-phone-wrap");
  var rig = document.querySelector(".phone-rig");
  var side = document.querySelector(".side");
  var BEZEL = 10;
  var SCREEN_W = 360;
  var SCREEN_H = 800;
  function fitPhone() {
    if (!hero || !layout || !wrap) return;
    var wide = window.innerWidth >= 1280; // their chrome beside the phone
    var column = window.innerWidth < 1000; // phones: a column that scrolls, the phone at its size
    // the room the chrome needs, in the phone's own pixels (it scales with the phone); below
    // 1280px the dock row under the phone is wider than the phone by about 55px a side
    var roomLeft = wide ? 24 + 168 + 8 : 60;
    var roomRight = wide ? 24 + 52 + 24 : 60;
    var roomBelow = wide ? 24 : 0; // the "Patch state" hint under the dock
    var layoutH = SCREEN_H + (wide ? 0 : 162); // their pills under the phone below 1280px (page.css)
    var s = 1;
    if (!column) {
      var styles = getComputedStyle(hero);
      var availH = hero.clientHeight - parseFloat(styles.paddingTop) - parseFloat(styles.paddingBottom);
      var gap = parseFloat(getComputedStyle(layout).gap) || 40;
      var sideMin = side ? parseFloat(getComputedStyle(side).minWidth) || 300 : 0;
      var availW = layout.clientWidth - sideMin - gap;
      s = Math.min(1, availH / (layoutH + roomBelow + 2 * BEZEL), availW / (SCREEN_W + roomLeft + roomRight));
      s = Math.max(0.4, Math.round(s * 1000) / 1000);
    }
    wrap.style.setProperty("--nm-scale", String(s));
    // the layout box stays 360 × layoutH; pull its edges in to the drawn size, plus the room
    wrap.style.marginLeft = Math.round(roomLeft * s - ((1 - s) * SCREEN_W) / 2) + "px";
    wrap.style.marginRight = Math.round(roomRight * s - ((1 - s) * SCREEN_W) / 2) + "px";
    wrap.style.marginBottom = Math.round((s - 1) * layoutH) + "px";
    placeDrawer();
  }

  // ---- the State Builder's drawer: beside the dock, level with the phone -------------------
  // MobileGym's stylesheet places the drawer assuming the phone is centred in the row; here the
  // panel shares the row, so the drawer follows the phone instead. On a phone (a column) their
  // stylesheet puts the drawer into the flow under the phone, and this leaves it alone.
  var drawer = document.getElementById("state-drawer");
  function placeDrawer() {
    if (!drawer || !layout || !rig) return;
    if (window.innerWidth < 1000) {
      drawer.style.left = "";
      drawer.style.top = "";
      return;
    }
    var l = layout.getBoundingClientRect();
    var r = rig.getBoundingClientRect(); // the phone as drawn (scaled)
    var s = parseFloat(wrap.style.getPropertyValue("--nm-scale")) || 1;
    // ≥1280px: the phone's right edge, the bezel, the dock (24px gap, ~52px wide) and another
    // 14px, as on their page; below, over the panel, right next to the phone
    var past = window.innerWidth >= 1280 ? (BEZEL + 24 + 52 + 14) * s : (BEZEL + 16) * s;
    drawer.style.left = Math.round(r.right - l.left + past) + "px";
    drawer.style.top = Math.round(r.top - l.top - BEZEL * s) + "px";
  }
  if (drawer) {
    new MutationObserver(placeDrawer).observe(drawer, { attributes: true, attributeFilter: ["data-open"] });
  }
  window.addEventListener("resize", fitPhone);
  if (window.ResizeObserver && hero) new ResizeObserver(fitPhone).observe(hero);
  fitPhone();

  // the lines' column fits the stage; in a window too short for all of them it scrolls, and
  // its lower edge fades while there is more of it below (page.css .groups.more)
  var groups = document.querySelector(".groups");
  function groupsMore() {
    if (!groups) return;
    var more = groups.scrollHeight > groups.clientHeight + 4 && groups.scrollTop + groups.clientHeight < groups.scrollHeight - 4;
    groups.classList.toggle("more", more);
  }
  if (groups) {
    groups.addEventListener("scroll", groupsMore, { passive: true });
    window.addEventListener("resize", groupsMore);
    if (window.ResizeObserver) new ResizeObserver(groupsMore).observe(groups);
    groupsMore();
  }

  // ---- the status line ------------------------------------------------------------------
  function minutesLeft() {
    if (!state || !state.demo) return null;
    return Math.max(0, Math.round((state.demo.expiresAt - Date.now() / 1000) / 60));
  }

  function render() {
    var cls = "status";
    var text;
    if (flash) {
      text = flash;
      cls += " flash";
    } else if (!phoneWindow()) {
      text = tr("The phone is off. Tap the screen to turn it on.", "手机关着，点一下屏幕开机。");
    } else if (!host) {
      text = tr("Starting the phone…", "手机启动中…");
    } else if (!state.configured && info && info.signin_required && !state.signedIn) {
      text = tr("Sign in on the phone (free) and it starts a Muse for you.", "在手机上登录（免费），它就为你启动一个 Muse。");
    } else if (!state || !state.configured) {
      // signed in (or no sign-in asked for): the page presses Start once a person is looking
      // (below); until then, or when it will not, the phone's page waits for the tap on Start
      text =
        state && state.startable && !autoStarted && !isBot()
          ? tr("A Muse starts for you in a moment; or tap Start on the phone.", "马上为你启动一个 Muse，也可以在手机上点「开始」。")
          : tr("Tap Start on the phone and it starts a Muse for you.", "在手机上点「开始」，它就为你启动一个 Muse。");
    } else if (state.demo && Date.now() / 1000 > state.demo.expiresAt) {
      text = renewing()
        ? tr("Starting a Muse for you…", "正在为你启动一个 Muse…")
        : tr("This Muse's time is up. Start over for a new one.", "这个 Muse 的时间到了，点「重新开始」再来一个。");
      if (!renewing()) cls += " warn";
    } else if (state.link === "unauthorized") {
      text = tr("The session has ended. Start over for a new one.", "会话已结束，点「重新开始」再来一个。");
      cls += " warn";
    } else if (state.link === "unreachable") {
      text = tr("Cannot reach your Muse right now; retrying…", "暂时连不上你的 Muse，正在重试…");
      cls += " warn";
    } else {
      var parts = [];
      var who = state.name && state.name.toLowerCase() !== "nanomuse" ? state.name : null;
      parts.push(who ? tr("Your Muse, " + who, "你的 Muse「" + who + "」") : tr("Your Muse", "你的 Muse"));
      var left = minutesLeft();
      if (left !== null) parts.push(tr(left + " min left", "还剩 " + left + " 分钟"));
      if (info && info.demo_model && !(state.demo && state.demo.byok)) parts.push(info.demo_model);
      if (state.link === "connecting" || state.web !== "ready") parts.push(tr("connecting…", "连接中…"));
      text = parts.join(" · ");
      cls += " live";
    }
    status.textContent = text;
    status.className = cls;
  }
  setInterval(render, 30000);

  function say(text, ms) {
    flash = text;
    render();
    setTimeout(function () {
      if (flash === text) {
        flash = null;
        render();
      }
    }, ms || 4000);
  }

  // ---- the lines to try -----------------------------------------------------------------
  document.querySelectorAll(".chip").forEach(function (chip) {
    chip.addEventListener("click", function () {
      var text = lang() === "zh" ? chip.getAttribute("data-zh") : chip.getAttribute("data-en");
      if (!text) return;
      if (!phoneWindow()) {
        powerOn();
        say(tr("Turning the phone on; one moment.", "正在开机，稍等一下。"));
        return;
      }
      if (!host) {
        say(tr("The phone is still starting; one moment.", "手机还在启动，稍等一下。"));
        return;
      }
      if (state && !state.configured) {
        if (info && info.signin_required && !state.signedIn) {
          say(tr("Sign in on the phone first; then try this.", "先在手机上登录，再试这句。"));
          return;
        }
        // the Start pill is on the screen: this tap presses it; the line waits for the chat
        // (host.draft keeps it until the web app says it is ready)
        if (state.startable && host.start) {
          autoStarted = true;
          Promise.resolve(host.start()).catch(function () {
            /* the phone shows what happened */
          });
        }
      }
      try {
        host.draft(text);
      } catch (e) {
        say(tr("Could not hand that to the phone.", "没能把这句话交给手机。"));
        return;
      }
      chip.classList.add("sent");
      setTimeout(function () {
        chip.classList.remove("sent");
      }, 1500);
      say(
        state && state.web === "ready"
          ? tr("In the chat on the phone. Tap send.", "已填进手机里的对话框，点发送就行。")
          : tr("Will be in the chat as soon as the Muse is up.", "等 Muse 启动好就会出现在对话框里。"),
      );
    });
  });

  document.getElementById("open").addEventListener("click", showApp);
  document.getElementById("reset").addEventListener("click", function () {
    if (!host) return;
    var ok = window.confirm(
      tr(
        "End this Muse and start a fresh one? Everything in it is gone.",
        "结束这个 Muse，重新来一个？里面的一切都会消失。",
      ),
    );
    if (!ok) return;
    say(tr("Starting over…", "正在重新开始…"), 8000);
    Promise.resolve(host.reset()).catch(function () {
      /* the phone shows what happened */
    });
  });

  render();

  // ---- the phone turns itself on, and the Muse starts once a person is looking --------------
  // The phone is on as soon as the page is, the frame on the project site included, and
  // nanoMuse comes to the front (launch, above): the visitor sees the welcome page, and a
  // sign-in the showcase asks for is theirs to do. Pressing Start (a container on the server,
  // a share of the day's model budget) is not done for every page load: it is pressed once
  // this page has been in view for a few seconds with the tab in front, or at the first sign
  // of a hand (a pointer moving over the page, a key, a touch, the wheel), and never for a
  // browser that says it is driven by a script. A failed start is left as it is: the phone
  // shows why, with Try again.
  var AUTO_START_AFTER_MS = 6000;
  var autoStarted = false;
  var seen = false; // a person's hand on the page
  var inView = false; // the stage within the viewport (the top window's, in a frame)
  var viewSince = 0;
  var autoTimer = null;
  function isBot() {
    return !!navigator.webdriver;
  }
  function tryAutoStart() {
    if (autoStarted || isBot() || !host || !state || !state.startable) return;
    if (document.visibilityState !== "visible") return;
    if (!seen && !(inView && viewSince && Date.now() - viewSince >= AUTO_START_AFTER_MS)) return;
    autoStarted = true;
    say(tr("Starting a Muse for you…", "正在为你启动一个 Muse…"), 8000);
    Promise.resolve(host.start()).catch(function () {
      /* the phone shows what happened */
    });
  }
  function armAutoStart() {
    if (autoTimer) clearTimeout(autoTimer);
    autoTimer = setTimeout(tryAutoStart, AUTO_START_AFTER_MS + 50);
  }
  function hand() {
    if (seen) return;
    seen = true;
    tryAutoStart();
  }
  ["pointerdown", "pointermove", "keydown", "touchstart", "wheel"].forEach(function (type) {
    window.addEventListener(type, hand, { passive: true, once: true });
  });
  if (window.IntersectionObserver && hero) {
    new IntersectionObserver(
      function (entries) {
        var e = entries[entries.length - 1];
        inView = !!e && e.isIntersecting;
        viewSince = inView ? Date.now() : 0;
        if (inView) armAutoStart();
      },
      { threshold: 0.5 },
    ).observe(hero);
  } else {
    inView = true;
    viewSince = Date.now();
    armAutoStart();
  }
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      if (inView) viewSince = Date.now();
      armAutoStart();
    }
  });
  // the host's state arrives after the phone has booted: try then too
  var autoPoll = setInterval(function () {
    if (autoStarted || (state && state.configured)) {
      clearInterval(autoPoll);
      return;
    }
    tryAutoStart();
  }, 1000);

  // a beat after the page is there, so the switch-on is seen
  setTimeout(powerOn, 400);
})();
