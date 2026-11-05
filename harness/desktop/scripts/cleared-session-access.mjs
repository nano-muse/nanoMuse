// The pinned Harness keeps append-only session files. This compatibility policy prevents
// cleared synced sessions from being reopened through its conversation APIs. It does not
// delete files or change the person's separately authorized filesystem access.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const marker = "// nanoMuse: cleared conversation access policy v1";
const helpers = `${marker}
function nanomuseSessionParent(header) {
  return header?.origin === "subagent" ? header.parentSession : undefined;
}
function nanomuseSessionBlocked(ctx, id) {
  if (!id) return false;
  const cloud = ctx.get("nanomuseCloud");
  return !cloud || typeof cloud.isClearedSession !== "function" || cloud.isClearedSession(String(id));
}
function nanomuseSessionGuard(ctx, ...ids) {
  const id = ids.find((id) => nanomuseSessionBlocked(ctx, id));
  if (id) throw new RemoteError("session/not-found", \`session "\${id}" not found\`, { sessionId: id });
}
function nanomuseSessionCall(ctx, ids, read) {
  nanomuseSessionGuard(ctx, ...ids);
  const value = read();
  if (value && typeof value.then === "function") return value.then((result) => {
    nanomuseSessionGuard(ctx, ...ids);
    return result;
  });
  return value;
}
async function* nanomuseSessionControl(ctx, signal, read) {
  for await (const value of read(signal)) {
    if (value.type === "baseline") {
      yield { ...value, value: { ...value.value, projections: Object.fromEntries(Object.entries(value.value.projections).filter(([id]) => ctx.sessions.get(id) && !nanomuseSessionBlocked(ctx, id))) } };
    } else if (ctx.sessions.get(value.sessionId) && !nanomuseSessionBlocked(ctx, value.sessionId)) yield value;
  }
}
async function* nanomuseSessionFollow(ctx, request, signal, read) {
  const ids = [request.address.sessionId, request.address.childSessionId, request.address.parentSessionId];
  nanomuseSessionGuard(ctx, ...ids);
  const abort = new AbortController();
  const cloud = ctx.get("nanomuseCloud");
  const off = cloud.onChange(() => {
    if (ids.some((id) => nanomuseSessionBlocked(ctx, id))) abort.abort();
  });
  try {
    for await (const value of read(request, AbortSignal.any([signal, abort.signal]))) {
      nanomuseSessionGuard(ctx, ...ids);
      yield value;
    }
  } finally { off(); }
}
`;

function once(source, before, after, count = 1) {
  if (source.split(before).length !== count + 1) {
    throw new Error(`The Harness cleared-session seam changed: ${before.slice(0, 80)}`);
  }
  return source.split(before).join(after);
}

export function clearedSessionAccessSource(source) {
  if (source.includes(marker)) return source;
  let next = source;
  // Ordinary requests, file/media references and the upload resolver share this internal path.
  next = once(next, "\tasync resolveAgent(sessionId) {", "\tasync resolveAgent(sessionId) {\n\t\tnanomuseSessionGuard(this.ctx, sessionId);", 2);
  for (const [before, id] of [
    ["\tasync resolveObservedAgent(observation) {", "observation.header.id, nanomuseSessionParent(observation.header)"],
    ["\tasync ensureSession(sessionId, cwd, checkPersistedIdentity, presetId) {", "sessionId"],
    ["\tasync createOrAdopt(sessionId, cwd, checkPersistedIdentity, presetId) {", "sessionId"],
    ["\tasync readSessionState(sessionId) {", "sessionId"],
  ]) next = once(next, before, `${before}\n\t\tnanomuseSessionGuard(this.ctx, ${id});`);
  next = once(next, "\t\tconst sessionId = addressId(address);", "\t\tconst sessionId = addressId(address);\n\t\tnanomuseSessionGuard(this.ctx, sessionId, address.parentSessionId);");
  // Check again after asynchronous admission, immediately before adding work or a fork.
  next = once(next, "\t\t\t\t\tif (request.mode === \"steer\") agent.steer(message);", "\t\t\t\t\tnanomuseSessionGuard(this.ctx, request.sessionId);\n\t\t\t\t\tif (request.mode === \"steer\") agent.steer(message);");
  next = once(next, "\t\t\t\tawait this.ctx.agents.create({\n\t\t\t\t\tsessionId: childId,", "\t\t\t\tnanomuseSessionGuard(this.ctx, request.sessionId);\n\t\t\t\tawait this.ctx.agents.create({\n\t\t\t\t\tsessionId: childId,");
  next = once(next, "\n\t\treturn (await this.ctx.agents.resume({", "\n\t\tnanomuseSessionGuard(this.ctx, sessionId, nanomuseSessionParent(observation.header));\n\t\treturn (await this.ctx.agents.resume({");
  next = once(next, "\t\t\t\treturn (await this.ctx.agents.resume({", "\t\t\t\tnanomuseSessionGuard(this.ctx, sessionId, nanomuseSessionParent(observation.header));\n\t\t\t\treturn (await this.ctx.agents.resume({");
  next = once(next, "\n\t\treturn (await this.ctx.agents.create({", "\n\t\tnanomuseSessionGuard(this.ctx, sessionId);\n\t\treturn (await this.ctx.agents.create({");
  next = once(next, "\t\t\tconst agent = await resume;", "\t\t\tconst agent = await resume;\n\t\t\tif (nanomuseSessionBlocked(this.ctx, sessionId)) agent.cancel({ kind: \"user\" });\n\t\t\tnanomuseSessionGuard(this.ctx, sessionId);");
  // The remote entry points are checked both before and after asynchronous work.
  for (const name of ["create", "selectModel", "rename", "fork", "attachment", "updateQueue"]) {
    const before = `\t\t\treturn this.commands.${name}(request);`;
    next = once(next, before, `\t\t\treturn nanomuseSessionCall(this.ctx, [request.sessionId], () => this.commands.${name}(request));`);
  }
  next = once(next, "\t\t\treturn this.commands.prompt(request);", "\t\t\treturn nanomuseSessionCall(this.ctx, [request.sessionId], () => this.commands.prompt(request));");
  next = once(next, "\t\tinspect(sessionId, signal) {", "\t\tinspect(sessionId, signal) {\n\t\t\tnanomuseSessionGuard(this.ctx, sessionId);");
  next = once(next, "\t\t\treturn inspectApiSession(this.ctx, sessionId, signal);", "\t\t\treturn nanomuseSessionCall(this.ctx, [sessionId], () => inspectApiSession(this.ctx, sessionId, signal));");
  next = once(next, "\t\t\treturn { items: await this.listState.list(signal) };", "\t\t\treturn { items: (await this.listState.list(signal)).filter((row) => !nanomuseSessionBlocked(this.ctx, row.sessionId) && !nanomuseSessionBlocked(this.ctx, (row.origin === 'subagent' ? row.parentSessionId : undefined))) };");
  next = once(next, "\t\t\treturn this.listState.search(request.query, signal);", "\t\t\treturn this.listState.search(request.query, signal).then((value) => ({ ...value, items: value.items.filter((row) => !nanomuseSessionBlocked(this.ctx, row.sessionId)) }));");
  next = once(next, "\t\t\treturn this.history.page(request, signal);", "\t\t\treturn nanomuseSessionCall(this.ctx, [request.address.sessionId, request.address.childSessionId, request.address.parentSessionId], () => this.history.page(request, signal));");
  next = once(next, "\t\t\treturn this.history.follow(request, signal);", "\t\t\treturn nanomuseSessionFollow(this.ctx, request, signal, (request, signal) => this.history.follow(request, signal));");
  next = once(next, "\t\tasync projections(request, signal) {\n\t\t\tconst { sessionId } = request;", "\t\tasync projections(request, signal) {\n\t\t\tconst { sessionId } = request;\n\t\t\tnanomuseSessionGuard(this.ctx, sessionId);");
  next = once(next, "\t\t\t\t\tif (projections === void 0)", "\t\t\t\t\tnanomuseSessionGuard(this.ctx, sessionId);\n\t\t\t\t\tif (projections === void 0)");
  next = once(next, "\t\t\treturn this.controlState.control(signal);", "\t\t\treturn nanomuseSessionControl(this.ctx, signal, (signal) => this.controlState.control(signal));");
  next = once(next, "\t\t\treturn this.agents.resolveAgent(sessionId);", "\t\t\treturn nanomuseSessionCall(this.ctx, [sessionId], () => this.agents.resolveAgent(sessionId));");
  next = once(next, "\t\treturn this.resolve(sessionId);", "\t\treturn nanomuseSessionCall(this.ctx, [sessionId], () => this.resolve(sessionId));");
  next = once(next, "\t\treturn this.resolve(observation.header.id, observation);", "\t\treturn nanomuseSessionCall(this.ctx, [observation.header.id, nanomuseSessionParent(observation.header)], () => this.resolve(observation.header.id, observation));");
  next = once(next, "\t\t\tif (observation.header.cwd === void 0) {", "\t\t\tif (nanomuseSessionBlocked(this.ctx, nanomuseSessionParent(observation.header))) { observation[Symbol.dispose](); nanomuseSessionGuard(this.ctx, nanomuseSessionParent(observation.header)); }\n\t\t\tif (observation.header.cwd === void 0) {");
  next = once(next, "\t\t\t\t\tif (!visibleIds.has(hit.header.id)", "\t\t\t\t\tif (nanomuseSessionBlocked(this.ctx, hit.header.id) || nanomuseSessionBlocked(this.ctx, nanomuseSessionParent(hit.header))) continue;\n\t\t\t\t\tif (!visibleIds.has(hit.header.id)");
  next = once(next, "\t\t\t\titems: authorized.slice(0, 20),", "\t\t\t\titems: authorized.slice(0, 20).filter((row) => !nanomuseSessionBlocked(this.ctx, row.sessionId) && !nanomuseSessionBlocked(this.ctx, nanomuseSessionParent(visible.find((record) => record.header.id === row.sessionId)?.header))),");
  next = once(next, 'ctx.emit("api-session/added", this.listState.summaryFor(session));', 'if (!nanomuseSessionBlocked(ctx, session.id) && !nanomuseSessionBlocked(ctx, nanomuseSessionParent(session.header))) ctx.emit("api-session/added", this.listState.summaryFor(session));');
  next = once(next, 'if (ctx.sessions.get(agent.id) === agent.session) ctx.emit("api-session/added",', 'if (!nanomuseSessionBlocked(ctx, agent.id) && !nanomuseSessionBlocked(ctx, nanomuseSessionParent(agent.session.header)) && ctx.sessions.get(agent.id) === agent.session) ctx.emit("api-session/added",');
  for (const [before, id] of [
    ['\t\t\tctx.on("agent/status", ({ agent, status }) => {', 'agent.id, nanomuseSessionParent(agent.session.header)'],
    ['\t\t\tctx.on("agent/error", ({ agent, error }) => {', 'agent.id, nanomuseSessionParent(agent.session.header)'],
    ['\t\t\tctx.on("session/event", (session, event) => {', 'session.id, nanomuseSessionParent(session.header)'],
  ]) next = once(next, before, before + `\n\t\t\t\tif ([${id}].some((id) => nanomuseSessionBlocked(ctx, id))) return;`);
  next = once(next, "\t\t\tconst attached = this.ctx.sessions.get(sessionId);\n\t\t\tif (attached !== void 0) return Promise.resolve({", "\t\t\tconst attached = this.ctx.sessions.get(sessionId);\n\t\t\tnanomuseSessionGuard(this.ctx, nanomuseSessionParent(attached?.header));\n\t\t\tif (attached !== void 0) return Promise.resolve({");
  next = once(next, "\t\t\tif (observation.header.cwd === void 0) throw new ApiSessionNotFound", "\t\t\tnanomuseSessionGuard(ctx, nanomuseSessionParent(observation.header));\n\t\t\tif (observation.header.cwd === void 0) throw new ApiSessionNotFound");
  // Cold list/search must not use cleared logs even when the final visible page is full.
  next = once(next, "\t\tfor (const record of records) {", "\t\tfor (const record of records) {\n\t\t\tif (nanomuseSessionBlocked(this.ctx, record.header.id) || nanomuseSessionBlocked(this.ctx, nanomuseSessionParent(record.header))) continue;");
  next = once(next, "visible.filter((record) => record.header.cwd !== void 0)", "visible.filter((record) => record.header.cwd !== void 0 && !nanomuseSessionBlocked(this.ctx, record.header.id) && !nanomuseSessionBlocked(this.ctx, nanomuseSessionParent(record.header)))");
  next = once(next, "\t\tfor (const session of sessions) {", "\t\tfor (const session of sessions) {\n\t\t\tif (nanomuseSessionBlocked(this.ctx, session.id) || nanomuseSessionBlocked(this.ctx, nanomuseSessionParent(session.header))) continue;");
  return helpers + next;
}

export function clearedFileUploadSource(source) {
  if (source.includes(marker)) return source;
  let next = once(source, "\t\tassertOrdinaryAgent(agent) {", "\t\tassertOrdinaryAgent(agent) {\n\t\t\tnanomuseSessionGuard(this.ctx, agent.id, nanomuseSessionParent(agent.session.header));");
  next = once(next, "\t\tasync resolveAgent(sessionId) {", "\t\tasync resolveAgent(sessionId) {\n\t\t\tnanomuseSessionGuard(this.ctx, sessionId);");
  next = once(next, "\t\t\tif (this.ctx.agents.get(agent.id) !== agent)", "\t\t\tnanomuseSessionGuard(this.ctx, agent.id, nanomuseSessionParent(agent.session.header));\n\t\t\tif (this.ctx.agents.get(agent.id) !== agent)");
  return helpers + next;
}

export function patchClearedSessionAccess(stage) {
  for (const [name, transform] of [["dsh-api-session-controller", clearedSessionAccessSource], ["dsh-client-file-upload", clearedFileUploadSource]]) {
    const root = join(stage, "node_modules", "@deepseek-ai", name);
    const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
    if (manifest.version !== "0.2.0-rc.2") throw new Error(`Review cleared-session access for ${name} ${manifest.version}.`);
    const path = join(root, "lib", "index.js");
    const source = readFileSync(path, "utf8");
    const next = transform(source);
    if (source !== next) writeFileSync(path, next);
  }
}
