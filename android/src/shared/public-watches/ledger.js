// Offline phone state machine. The host scopes and serializes state per account.
// The only text retained from conversations is a validated public selector.
var NanoMuseWatch = (function () {
  "use strict";
  var hour = 3600000,
    day = 24 * hour,
    grammar = nmWatchGrammar;
  function rule(name, whole) {
    return new RegExp(whole ? "^(?:" + grammar[name] + ")$" : grammar[name], "i");
  }
  var quoted = rule("quoted"),
    uncertain = rule("uncertain"),
    own = rule("own", true);
  var request = rule("request", true),
    related = rule("related", true),
    ongoing = rule("ongoing");
  var topicRequest = rule("topic_request", true),
    topicInterest = rule("topic_interest", true);
  var negative =
    /(?:don't|don’t|do not|never|stop)\s+(?:(?:automatically|ever)\s+)?(?:watch|track|monitor|follow|subscribe)|(?:别再?|不要|不用|不想|停止|取消|不再)(?:(?:自动|定期|持续|帮我))*(?:关注|跟踪|追踪|监测|监控|订阅|提醒)/i;
  var forwarded =
    /forwarded message|转发邮件|(?:以下|下面)(?:是)?(?:引文|引用|示例|转述|聊天记录)|(?:example|(?:translate|summari[sz]e|review)(?: the following| this)?|quoted text|transcript|(?:he|she|they|someone) (?:said|wrote)|例如|举例|原文|翻译|[他她]说)[：:]\s*$/i;
  function lines(text) {
    if (text.length > 6000 || negative.test(text)) return [];
    var output = [],
      fenced = false,
      closing = "";
    var raw = text.split(/\r\n?|\n/),
      pairs = [
        ["“", "”"],
        ["「", "」"],
        ["『", "』"],
        ['"', '"'],
      ];
    for (var i = 0; i < raw.length; i++) {
      var line = raw[i].replace(/[ \t\x00\u200b]+$/, "");
      if (/[\x00\u200b§]/.test(line)) continue;
      var indented = /^(?: {4}|\t)/.test(line);
      line = line.replace(/\s+/g, " ").trim();
      if (/^(?:```|~~~)/.test(line)) {
        fenced = !fenced;
        continue;
      }
      if (fenced || indented || /^(?:>|\||#|\/\/)/.test(line)) continue;
      if (closing) {
        if (line.indexOf(closing) >= 0) closing = "";
        continue;
      }
      for (var j = 0; j < pairs.length; j++) {
        var start = line.indexOf(pairs[j][0]);
        if (start >= 0 && line.indexOf(pairs[j][1], start + 1) < 0) {
          closing = pairs[j][1];
          break;
        }
      }
      if (forwarded.test(line)) break;
      if (!closing && !quoted.test(line) && !uncertain.test(line)) output.push(line);
    }
    return output;
  }

  function identify(raw, context, mention) {
    var ref = raw,
      kind;
    if (/^10\./.test(ref)) kind = "research_work";
    else if (/^(?:A[1-9][0-9]{0,14}|(?:[0-9]{4}-){3}[0-9]{3}[0-9X])$/i.test(ref)) {
      if (/^A/i.test(ref) && !/openalex/i.test(context)) return null;
      kind = "research_author";
    } else {
      if (ref.indexOf("://") < 0) ref = "https://" + ref;
      var url = /^https:\/\/([a-z0-9.-]+)(\/[^#]*)?$/i.exec(ref);
      if (!url) return null;
      var host = url[1].toLowerCase(),
        path = (url[2] || "/").replace(/^\/+/, "");
      if (host === "scholar.google.com") kind = "scholar_profile";
      else if (/[?#]/.test(ref)) return null;
      else if (host === "github.com") {
        if (mention) path = path.replace(/^(.*?\/[^/]+)\/(?:issues|pull|discussions)\/[1-9][0-9]*$/i, "$1");
        ref = path.replace(/\/$/, "").replace(/\.git$/, "");
        kind = ref.indexOf("/") < 0 ? "github_user" : "github_repo";
      } else if (host === "doi.org" || host === "dx.doi.org") {
        kind = "research_work";
        ref = path;
      } else if (host === "openalex.org" || host === "orcid.org") {
        kind = "research_author";
        ref = path;
      } else if (
        /(?:^|\/)(?:feed|atom|rss)(?:\/|$)|\.(?:atom|rss|xml)$/i.test(path) ||
        /\b(?:website|site|blog|subscribe to|watch|monitor|rss|atom|feed)\b|网站|官网|博客|订阅|关注/i.test(
          context
        )
      )
        kind = "feed";
      else return null;
    }
    try {
      return { kind: kind, target: nmWatchNormalize(kind, ref) };
    } catch (ignore) {
      return null;
    }
  }

  function subject(match) {
    var text = (match[1] || match[2] || "").trim();
    if (
      grammar.broad.indexOf(text.toLowerCase()) >= 0 ||
      text.length > 80 ||
      (text.match(/[a-z\u3400-\u9fff]/gi) || []).length < 4 ||
      /[^\w \u3400-\u9fff-]|[_\d]{3,}|\b(?:my|your|http|and then|please)\b|然后|帮我|我的|地址/i.test(text) ||
      (!/\s/.test(text) && (text.match(/[\u3400-\u9fff]/g) || []).length < 4)
    )
      return null;
    try {
      return { kind: "research_topic", target: nmWatchNormalize("research_topic", text) };
    } catch (ignore) {
      return null;
    }
  }

  function indexBy(list, field, value) {
    for (var i = 0; i < list.length; i++) if (list[i][field] === value) return i;
    return -1;
  }
  function discovery(text, personal) {
    var candidates = [],
      references = [];
    function add(list, ref, active) {
      if (!ref) return;
      var id = ref.kind + ":" + ref.target,
        i = indexBy(list, "id", id);
      if (i >= 0) {
        if (active) list[i].active = true;
      } else if (list.length < 4) list.push({ kind: ref.kind, target: ref.target, id: id, active: !!active });
    }
    lines(text).forEach(function (line) {
      line = line.replace(/\[[^\]\n]{1,120}\]\((https?:\/\/[^\s<>]+?)\)(?=[\s.,;!?，。；！、？]|$)/g, "$1");
      line = line.replace(
        /((?:my github (?:username|handle|login|account)(?: is)?|我的\s*github\s*(?:账号|帐号|账户|用户名)(?:是|为)?)\s*[:：]?\s*)(?!(?:is|at)\b|https?:|github\.com\/)@?([a-z0-9]+(?:-[a-z0-9]+)*)(?=[\s.,，。！!?？]|$)/gi,
        "$1https://github.com/$2"
      );
      var refs = [],
        slots = line.replace(new RegExp(grammar.reference, "ig"), function (token, offset) {
          if (offset && /[A-Za-z0-9_.\/@-]/.test(line.charAt(offset - 1))) return token;
          var ref = token.replace(/[.,;!?]+$/, "");
          while (/\)$/.test(ref) && (ref.match(/\(/g) || []).length < (ref.match(/\)/g) || []).length)
            ref = ref.slice(0, -1);
          var context = /openalex(?:\s+(?:author|id))?\s*[:：]?\s*$/i.test(line.slice(0, offset))
            ? "openalex"
            : "";
          add(references, identify(ref, context, true), false);
          refs.push(ref);
          return "§" + (refs.length - 1) + "§" + token.slice(ref.length);
        });
      slots.split(/[.。；;！!，]|,\s+/).forEach(function (clause) {
        clause = clause.trim();
        if (/[?？]|[吗么呢]$/.test(clause)) return;
        var tokens = clause.match(/§[0-9]+§/g) || [];
        if (!tokens.length) {
          var ask = topicRequest.exec(clause),
            topic = ask || topicInterest.exec(clause);
          if (topic) add(candidates, subject(topic), personal && ask);
        } else if (tokens.length === 1) {
          var key = tokens[0],
            evidence = clause.replace(key, "@"),
            owned = own.test(evidence),
            asked = request.test(evidence);
          if (
            !owned &&
            !asked &&
            !related.test(evidence) &&
            !(personal && evidence.length < 220 && ongoing.test(evidence))
          )
            return;
          var ref = identify(refs[Number(key.slice(1, -1))], evidence, false);
          add(
            candidates,
            ref,
            ref && personal && ref.kind !== "scholar_profile" && (asked || (owned && ref.kind !== "feed"))
          );
        }
      });
    });
    return { candidates: candidates, references: references };
  }

  function fresh() {
    return {
      version: 1,
      revision: 0,
      enabled: true,
      since: 0,
      rows: [],
      mentions: [],
      turns: [],
      handled: [],
    };
  }
  function reset(row) {
    row.lastChecked = null;
    row.next = 0;
    row.failures = 0;
    row.source = "";
    row.seen = [];
    row.pending = [];
  }
  function assign(s, kind, target, status, origin) {
    var id = kind + ":" + target,
      i = indexBy(s.rows, "id", id),
      row = s.rows[i];
    if (row && row.status === status) return;
    if (
      (!row && s.rows.length >= 512) ||
      ((status === "active" || status === "suggested") &&
        s.rows.filter(function (r) {
          return r.status === status;
        }).length >= 16)
    )
      throw Error("limit");
    if (status === "dismissed") {
      // Keep a single stable selector to honour the choice across restarts.
      s.rows[i] = { id: id, status: status };
    } else {
      if (!row || row.status === "dismissed") {
        row = { id: id, kind: kind, target: target, label: target, origin: origin };
        if (i >= 0) s.rows[i] = row;
        else s.rows.push(row);
      }
      row.status = status;
      reset(row);
    }
    s.revision++;
  }
  function observe(s, input) {
    if (!s.enabled) return;
    var now = input.now,
      floor = Math.max(s.since, now - 30 * day);
    s.mentions = s.mentions.filter(function (m) {
      return m.at >= floor;
    });
    (input.turns || []).slice(-100).forEach(function (turn) {
      if (
        !turn ||
        !shortString(turn.id, 200) ||
        !shortString(turn.text, 6000) ||
        typeof turn.personal !== "boolean" ||
        !validTime(turn.at) ||
        turn.at < floor ||
        turn.at > now ||
        s.turns.indexOf(turn.id) >= 0
      )
        return;
      s.turns.push(turn.id);
      s.turns = s.turns.slice(-192);
      var found = discovery(turn.text, turn.personal),
        candidates = found.candidates;
      if (turn.personal)
        found.references.forEach(function (ref) {
          var i = indexBy(s.mentions, "id", ref.id);
          if (i >= 0) {
            if (s.mentions[i].turn !== turn.id && indexBy(candidates, "id", ref.id) < 0) {
              ref.repeated = true;
              candidates.push(ref);
            }
            s.mentions.splice(i, 1);
          }
          s.mentions.push({ id: ref.id, at: turn.at, turn: turn.id });
        });
      s.mentions = s.mentions.slice(-128);
      candidates.slice(0, 4).forEach(function (c) {
        var i = indexBy(s.rows, "id", c.id);
        if (i >= 0 && !(s.rows[i].status === "suggested" && c.active)) return;
        try {
          assign(
            s,
            c.kind,
            c.target,
            c.active ? "active" : "suggested",
            turn.personal ? (c.repeated ? "recurring" : "chat") : "connected"
          );
        } catch (err) {
          if (err.message !== "limit") throw err;
        }
      });
    });
  }
  function canonical(kind, value) {
    try {
      return nmWatchNormalize(kind, value);
    } catch (ignore) {
      throw Error("invalid_target");
    }
  }
  function edit(s, p) {
    if (s.revision !== p.revision) throw Error("stale");
    if (typeof p.enabled === "boolean") {
      if (s.enabled !== p.enabled) {
        s.enabled = p.enabled;
        s.since = p.now;
        s.turns = [];
        s.mentions = [];
        s.rows.forEach(function (row) {
          if (row.status !== "dismissed") reset(row);
        });
        s.revision++;
      }
      return;
    }
    if (!s.enabled && p.action !== "pause" && p.action !== "dismiss") throw Error("disabled");
    if (!p.id && !p.action) {
      assign(
        s,
        p.kind,
        canonical(p.kind, p.target),
        p.kind === "scholar_profile" ? "suggested" : "active",
        "manual"
      );
      return;
    }
    var row = s.rows[indexBy(s.rows, "id", p.id)];
    if (!row || row.status === "dismissed") throw Error("stale");
    if (p.action === "confirm" && row.kind === "scholar_profile" && row.status === "suggested") {
      if (p.kind !== "research_author" && p.kind !== "research_work") throw Error("invalid_target");
      assign(s, p.kind, canonical(p.kind, p.target), "active", "manual");
      assign(s, row.kind, row.target, "dismissed", row.origin);
      return;
    }
    if (p.kind || p.target) throw Error("invalid_target");
    var transitions = {
      confirm: ["suggested", "active"],
      pause: ["active", "paused"],
      resume: ["paused", "active"],
    };
    if (p.action === "dismiss") assign(s, row.kind, row.target, "dismissed", row.origin);
    else if (
      Object.prototype.hasOwnProperty.call(transitions, p.action) &&
      transitions[p.action][0] === row.status
    ) {
      assign(s, row.kind, row.target, transitions[p.action][1], row.origin);
    } else throw Error("stale");
  }
  function shortString(value, limit) {
    return typeof value === "string" && !!value && value.length <= limit;
  }
  function validTime(n) {
    return typeof n === "number" && isFinite(n) && n >= 0;
  }
  function validItem(item) {
    return (
      item &&
      shortString(item.key, 512) &&
      shortString(item.text, 1024) &&
      shortString(item.url, 1600) &&
      /^https:\/\/(?:[a-z0-9-]+\.)+[a-z]{2,24}(?:[/?#]|$)/i.test(item.url) &&
      !/[\s<>"\\\x60\x00-\x1f]/.test(item.url)
    );
  }
  function sample(s, p) {
    var row = s.rows[indexBy(s.rows, "id", p.id)];
    if (!s.enabled || !row || row.status !== "active") return;
    if (p.failed || !Array.isArray(p.items) || p.items.length > 100 || !p.items.every(validItem)) {
      row.failures = Math.min(8, row.failures + 1);
      row.next = p.now + Math.min(12 * hour, (hour / 4) * Math.pow(2, row.failures - 1));
      return;
    }
    var source = p.source || row.target,
      baseline = row.lastChecked === null || row.source !== source;
    if (baseline) {
      row.pending = [];
      row.seen = [];
    }
    var nextKeys = [],
      pending = [];
    p.items.forEach(function (item) {
      if (nextKeys.indexOf(item.key) >= 0) return;
      nextKeys.push(item.key);
      var j = indexBy(row.pending, "key", item.key);
      if (!baseline && s.handled.indexOf(item.key) < 0 && (j >= 0 || row.seen.indexOf(item.key) < 0)) {
        pending.push({
          key: item.key,
          text: item.text,
          url: item.url,
          at: j >= 0 ? row.pending[j].at : p.now,
        });
      }
    });
    row.seen = row.seen
      .filter(function (k) {
        return nextKeys.indexOf(k) < 0;
      })
      .concat(nextKeys)
      .slice(-512);
    row.pending = pending
      .filter(function (item) {
        return item.at >= p.now - 7 * day;
      })
      .slice(0, 25);
    row.failures = 0;
    row.source = source;
    row.lastChecked = p.now;
    row.next = p.now + (row.kind.indexOf("research_") === 0 ? day : 4 * hour);
  }
  function consume(s, p) {
    if (!Array.isArray(p.keys)) return;
    var removed = [];
    s.rows.forEach(function (row) {
      if (row.status !== "active") return;
      row.pending = row.pending.filter(function (item) {
        if (p.keys.indexOf(item.key) < 0) return true;
        if (removed.indexOf(item.key) < 0) removed.push(item.key);
        return false;
      });
    });
    s.handled = s.handled.concat(removed).slice(-512);
  }
  function publicView(s, now) {
    var watches = [],
      due = [],
      pending = [];
    s.rows.forEach(function (row) {
      if (row.status === "dismissed") return;
      watches.push({
        id: row.id,
        kind: row.kind,
        target: row.target,
        label: row.label,
        status: row.status,
        origin: row.origin,
        lastChecked: row.lastChecked,
        unavailable: row.failures > 0,
      });
      if (!s.enabled || row.status !== "active") return;
      if (row.next <= now) due.push(row);
      row.pending.forEach(function (item) {
        if (item.at <= now && item.at >= now - 7 * day && indexBy(pending, "key", item.key) < 0) {
          pending.push({
            id: row.id,
            kind: row.kind,
            target: row.target,
            key: item.key,
            text: item.text,
            url: item.url,
          });
        }
      });
    });
    return {
      state: s,
      enabled: s.enabled,
      revision: s.revision,
      watches: watches,
      pending: pending,
      due: due
        .sort(function (a, b) {
          return a.next - b.next;
        })
        .slice(0, 3)
        .map(function (r) {
          return { id: r.id, kind: r.kind, target: r.target };
        }),
    };
  }
  return function (input) {
    var p = JSON.parse(input),
      s = p.state && p.state.version === 1 ? p.state : fresh();
    if (p.state && p.state.version && p.state.version !== 1) throw Error("Unsupported watch data");
    if (!validTime(p.now)) throw Error("Missing clock");
    try {
      if (p.op === "observe") observe(s, p);
      else if (p.op === "edit") edit(s, p);
      else if (p.op === "sample") sample(s, p);
      else if (p.op === "consume") consume(s, p);
      else if (p.op !== "view") throw Error("invalid_operation");
      return JSON.stringify(publicView(s, p.now));
    } catch (err) {
      var old = JSON.parse(input).state,
        unchanged = publicView(old && old.version === 1 ? old : fresh(), p.now);
      unchanged.error = String(err.message || "invalid_operation");
      return JSON.stringify(unchanged);
    }
  };
})();
