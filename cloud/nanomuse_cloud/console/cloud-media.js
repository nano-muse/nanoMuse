/* Optional Cloud video sheet. Keep the task ID so a reload polls the original render. */
function mediaRequestRejected(error) {
  return error.status >= 400 && error.status < 500 && error.status !== 408;
}
window.openMuseVideo = async function ({ h, api, token, session, current, openSheet, closeSheet, errText, zh }) {
  const t = zh ? {
    title: "生成人物视频", close: "关闭", prompt: "人物做什么动作？", avatar: "人物照片 HTTPS 地址",
    shot: "分镜图 HTTPS 地址（可选）", wav: "参考人声 WAV 的 HTTPS 地址", create: "生成 4 秒视频",
    note: "使用你有权提供的素材。请提供 10 至 60 秒参考人声，分镜图短边至少 720 像素。省略分镜时使用人物照片。图片和音频将交给百度千帆，生成会使用你的 Cloud 额度。",
    wait: "正在生成，可关闭页面，稍后回来查看。", unknown: "未收到任务编号。请先核对账号用量，再决定是否重新生成。",
    download: "打开并下载视频", again: "新建视频", query: "重新查询", failed: "生成失败", expired: "任务已过期",
    loading: "正在读取账号…", sending: "正在提交…", invalid: "请填写可访问的 HTTPS 素材地址。", check: "检查上次提交",
    reset: "先前的请求可能已经提交并使用额度。确定要开始一个新任务？", unsupported: "此账号当前无法使用人物视频生成。",
  } : {
    title: "Generate a character video", close: "Close", prompt: "What should the person do?", avatar: "Portrait HTTPS URL",
    shot: "Shot image HTTPS URL (optional)", wav: "Reference voice WAV HTTPS URL", create: "Generate a 4-second video",
    note: "Use material you have permission to share, including 10 to 60 seconds of reference speech. The shot image needs a short edge of at least 720 pixels. Leave it blank to use the portrait. Baidu Qianfan receives the media. Generation uses your Cloud allowance.",
    wait: "Rendering. You can close this page and come back.", unknown: "No task ID was received. Check your account usage before starting another render.",
    download: "Open and download video", again: "New video", query: "Check again", failed: "Generation failed", expired: "Task expired",
    loading: "Loading account…", sending: "Submitting…", invalid: "Enter accessible HTTPS URLs for your media.", check: "Check previous submission",
    reset: "The earlier submission may have used your allowance. Start a new task?", unsupported: "Character video generation is unavailable for this account.",
  };
  const section = h("section", { class: "sheet" });
  const main = h("div", { class: "card allow" });
  const status = h("p", { class: "fine", role: "status" }, t.loading);
  section.append(h("div", { class: "head" }, h("h2", {}, t.title), h("button", { class: "btn quiet sm", onclick: closeSheet }, t.close)), main, status);
  openSheet(section);
  const visible = () => current() && section.isConnected;
  const button = (label, action) => h("button", { class: "btn quiet sm", type: "button", onclick: action }, label);
  const secure = (value) => { try { const u = new URL(value); return u.protocol === "https:" && !u.username && !u.password; } catch { return false; } };
  let slot;
  try {
    const me = await api("GET", "/v1/me", null, token);
    if (!visible()) return;
    if (!me.account || !me.account.id) throw new Error(t.unsupported);
    slot = "nm.wizshot." + me.account.id;
  } catch (e) { if (visible()) status.textContent = errText(e); return; }

  const isSubmission = (id) => id === "submitting" || id?.startsWith("submitting:");
  function startOver(expected) {
    if (localStorage.getItem(slot) !== expected) { resume(); return; }
    if (isSubmission(expected) && !window.confirm(t.reset)) return;
    localStorage.removeItem(slot);
    drawForm();
  }
  function unknown(marker) {
    main.replaceChildren(button(t.check, resume), button(t.again, () => startOver(marker)));
    status.textContent = t.unknown;
  }
  async function poll(id) {
    if (!visible()) return;
    if (localStorage.getItem(slot) !== id) { resume(); return; }
    main.replaceChildren();
    status.textContent = t.wait;
    try {
      const reply = await api("GET", "/api/v1/tasks/" + encodeURIComponent(id), null, token);
      if (!visible()) return;
      if (localStorage.getItem(slot) !== id) { resume(); return; }
      const output = reply.output || {};
      if (output.task_status === "PENDING" || output.task_status === "RUNNING") {
        window.setTimeout(() => poll(id), 15000);
      } else if (output.task_status === "SUCCEEDED" && secure(output.video_url)) {
        main.replaceChildren(h("a", { href: output.video_url, target: "_blank", rel: "noopener noreferrer", class: "btn" }, t.download), button(t.again, () => startOver(id)));
        status.textContent = "";
      } else if (["FAILED", "CANCELED", "CANCELLED", "UNKNOWN"].includes(output.task_status)) {
        status.textContent = output.message || (output.task_status === "UNKNOWN" ? t.expired : t.failed);
        main.replaceChildren(button(t.query, () => poll(id)), button(t.again, () => startOver(id)));
      } else { throw new Error(output.message || t.failed); }
    } catch (e) {
      if (!visible()) return;
      if (localStorage.getItem(slot) !== id) { resume(); return; }
      status.textContent = errText(e);
      main.replaceChildren(button(t.query, () => poll(id)));
      if (e.status === 404 || e.status === 410) main.append(button(t.again, () => startOver(id)));
    }
  }
  function resume() {
    const id = localStorage.getItem(slot);
    if (session.video && id === session.video.marker) {
      main.replaceChildren(); status.textContent = t.sending;
      session.video.done.then((error) => {
        if (!visible()) return;
        resume();
        if (error && !localStorage.getItem(slot)) status.textContent = errText(error);
      });
    } else if (isSubmission(id)) unknown(id);
    else if (id) poll(id);
    else drawForm();
  }
  function drawForm() {
    const form = h("form");
    function field(text, type, required) {
      const input = h("input", { type, required: required ? "" : null, maxlength: type === "url" ? 8192 : 1000 });
      form.append(h("div", { class: "field" }, h("label", {}, text, h("span", { class: "in" }, input))));
      return input;
    }
    const prompt = field(t.prompt, "text", true), avatar = field(t.avatar, "url", true);
    const shot = field(t.shot, "url", false), audio = field(t.wav, "url", true);
    const submit = h("button", { type: "submit", class: "btn" }, t.create);
    form.append(submit); main.replaceChildren(form); status.textContent = t.note;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submit.disabled || !visible()) return;
      if (localStorage.getItem(slot)) { resume(); return; }
      const body = { model: "ernie-wizshot-me", prompt: prompt.value.trim(), avatar_url: avatar.value.trim(), reference_audio_url: audio.value.trim(), duration: 4 };
      if (shot.value.trim()) body.shot_image = shot.value.trim();
      if (!body.prompt || ![body.avatar_url, body.reference_audio_url, ...(body.shot_image ? [body.shot_image] : [])].every(secure)) {
        status.textContent = t.invalid; return;
      }
      const marker = "submitting:" + crypto.getRandomValues(new Uint32Array(4)).join("-");
      localStorage.setItem(slot, marker);
      submit.disabled = true;
      const done = (async () => {
        try {
          const response = await api("POST", "/v1/videos/generations", body, token);
          const id = response.output?.task_id;
          if (!id || typeof id !== "string") throw new Error(t.unknown);
          if (current() && localStorage.getItem(slot) === marker) localStorage.setItem(slot, id);
        } catch (e) {
          if (current() && localStorage.getItem(slot) === marker && mediaRequestRejected(e)) localStorage.removeItem(slot);
          return e;
        } finally {
          if (session.video?.marker === marker) session.video = null;
        }
      })();
      session.video = { marker, done };
      resume();
    });
  }
  resume();
};

window.openMuseImage = function ({ h, api, token, session, current, openSheet, closeSheet, errText, zh }) {
  const t = zh ? {
    title: "生成图片", prompt: "描述你想画的内容", create: "生成", download: "下载图片",
    close: "关闭", wait: "正在生成…", note: "提示词将发往百度千帆，生成一张图片会使用你的 Cloud 额度。", bad: "没有收到可读取的图片。",
    uncertain: "上一次请求可能已经使用额度。请先核对账号用量。", again: "确定再次生成并使用额度？",
  } : {
    title: "Generate an image", prompt: "Describe the picture", create: "Generate", download: "Download image",
    close: "Close", wait: "Generating…", note: "Your prompt goes to Baidu Qianfan. One image uses your Cloud allowance.", bad: "No readable image was returned.",
    uncertain: "Your last request may have used your allowance. Check your account usage.", again: "Generate again and use your allowance?",
  };
  const section = h("section", { class: "sheet" });
  const prompt = h("input", { type: "text", required: "", maxlength: 1000 });
  const submit = h("button", { type: "submit", class: "btn" }, t.create);
  const form = h("form", { class: "card allow" }, h("div", { class: "field" }, h("label", {}, t.prompt, h("span", { class: "in" }, prompt))), submit);
  const status = h("p", { class: "fine", role: "status" }, t.note);
  const output = h("div");
  section.append(h("div", { class: "head" }, h("h2", {}, t.title), h("button", { class: "btn quiet sm", onclick: closeSheet }, t.close)), form, status, output);
  openSheet(section);
  const marker = "nm.image.pending";
  const visible = () => current() && section.isConnected;
  async function show(request) {
    submit.disabled = true; prompt.disabled = true; prompt.value = request.prompt; status.textContent = t.wait;
    try {
      const { mime, src } = await request.result;
      if (!visible()) return;
      const picture = h("img", { src, alt: request.prompt, style: "max-width:100%;height:auto" });
      output.replaceChildren(picture, h("a", { class: "btn", href: src, download: "nanomuse." + mime }, t.download));
      status.textContent = "";
    } catch (err) {
      if (visible()) status.textContent = [errText(err), mediaRequestRejected(err) ? "" : t.uncertain].filter(Boolean).join(" ");
    } finally { submit.disabled = false; prompt.disabled = false; }
  }
  if (session.image) show(session.image);
  else if (sessionStorage.getItem(marker)) status.textContent = t.uncertain;
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = prompt.value.trim();
    if (!text || submit.disabled || !visible()) return;
    if (sessionStorage.getItem(marker) && !window.confirm(t.uncertain + " " + t.again)) return;
    sessionStorage.setItem(marker, "1");
    const result = (async () => {
      try {
        const reply = await api("POST", "/v1/images/generations", { model: "musesteamer-air-image", prompt: text, size: "1280x720", n: 1 }, token);
        const data = reply.data?.[0]?.b64_json;
        const mime = typeof data === "string" && (data.startsWith("/9j/") ? "jpeg" : data.startsWith("iVBOR") ? "png" : data.startsWith("UklG") ? "webp" : "");
        if (!mime) throw new Error(t.bad);
        const src = "data:image/" + mime + ";base64," + data;
        await h("img", { src }).decode();
        if (current()) sessionStorage.removeItem(marker);
        return { mime, src };
      } catch (err) {
        if (current() && mediaRequestRejected(err)) sessionStorage.removeItem(marker);
        throw err;
      }
    })();
    session.image = { prompt: text, result };
    show(session.image);
  });
};
