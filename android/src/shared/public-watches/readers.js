/* nanoMuse phone public source readers. Native code performs each bounded GET. */
(function (global) {
  "use strict";

  var DAY = 86400000;
  var ALEX = "https://api.openalex.org";
  var GITHUB = "https://api.github.com";
  var ATOM = "http://www.w3.org/2005/Atom";
  var RSS1 = "http://purl.org/rss/1.0/";
  var RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#";
  var RESERVED = (
    "about account accounts apps collections contact customer-stories dashboard discussions " +
    "enterprise events explore features gist gists github-sponsors issues join login logout marketplace " +
    "new notifications orgs organizations pricing projects pulls readme search security sessions settings " +
    "site sponsors stars topics trending users watch"
  ).split(" ");

  function requireValue(condition) {
    if (!condition) throw new Error("Invalid or incomplete public source");
  }

  function feedURL(value) {
    var match = /^https:\/\/([^/?#]+)(\/[A-Za-z0-9._~/-]{0,256})?$/.exec(value);
    requireValue(match);
    var host = match[1].toLowerCase();
    var path = match[2] || "/";
    requireValue(
      /^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$/.test(host) &&
        !/\.(local|internal|localhost|lan|home|onion)$/.test(host) &&
        !/^\/\//.test(path) &&
        !/(?:^|\/)\.{1,2}(?:\/|$)/.test(path)
    );
    return "https://" + host + path;
  }

  function normalize(kind, target) {
    requireValue(typeof target === "string" && target.length > 0 && target.length <= 512);
    requireValue(kind === "research_topic" || !/\s/.test(target));
    if (kind === "feed") return feedURL(target);
    if (kind === "scholar_profile") {
      if (target.indexOf("https://") === 0) {
        var scholar = /^https:\/\/scholar\.google\.com\/citations\?([^#]+)$/.exec(target);
        requireValue(scholar);
        var ids = [];
        scholar[1].split("&").forEach(function (field) {
          if (/^user=/.test(field)) ids.push(field.slice(5));
          else requireValue(/^hl=[a-zA-Z_-]+$/.test(field));
        });
        requireValue(ids.length === 1);
        target = ids[0];
      }
      requireValue(/^[a-zA-Z0-9_-]{8,32}$/.test(target));
      return target;
    }
    var value = target.toLowerCase();
    if (kind === "github_repo" || kind === "github_user") {
      var parts = value
        .replace(/^https:\/\/github\.com\//, "")
        .replace(/\/$/, "")
        .split("/");
      requireValue(
        parts.length === (kind === "github_repo" ? 2 : 1) &&
          /^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/.test(parts[0]) &&
          RESERVED.indexOf(parts[0]) < 0
      );
      if (parts.length === 2)
        requireValue(/^[a-z0-9._-]{1,100}$/.test(parts[1]) && !/^\.{1,2}$/.test(parts[1]));
      return parts.join("/");
    }
    if (kind === "research_work") {
      value = value.replace(/^https:\/\/doi\.org\//, "");
      requireValue(
        /^10\.[0-9]{4,9}\/[-._;()/:a-z0-9]+$/.test(value) &&
          value.length <= 200 &&
          !/(?:^|\/)\.{1,2}(?:\/|$)/.test(value)
      );
      return value;
    }
    if (kind === "research_author") {
      value = value.replace(/^https:\/\/(openalex|orcid)\.org\//, "").toUpperCase();
      if (/^A[1-9][0-9]{0,14}$/.test(value)) return value;
      requireValue(/^(?:[0-9]{4}-){3}[0-9]{3}[0-9X]$/.test(value));
      var digits = value.replace(/-/g, "");
      var total = 0;
      for (var i = 0; i < 15; i++) total = (total + Number(digits.charAt(i))) * 2;
      requireValue(digits.charAt(15) === "0123456789X".charAt((12 - (total % 11)) % 11));
      return value;
    }
    requireValue(kind === "research_topic");
    value = value.replace(/\s+/g, " ").trim();
    requireValue(
      /^[a-z0-9_ \-\u00c0-\u02af\u0370-\u052f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]{4,80}$/.test(value) &&
        /[a-z\u00c0-\u02af\u0370-\u052f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]/.test(value)
    );
    return value;
  }

  function sameOrigin(a, b) {
    return a.split("/")[2] === b.split("/")[2];
  }

  function resolve(base, ref) {
    if (!ref) return base;
    if (ref.indexOf("https://") === 0) return feedURL(ref);
    requireValue(!/^[A-Za-z][a-z0-9+.\-]*:/i.test(ref));
    if (ref.indexOf("//") === 0) return feedURL("https:" + ref);
    var origin = base.split("/").slice(0, 3).join("/");
    var path = ref[0] === "/" ? ref : base.slice(origin.length).replace(/[^/]*$/, "") + ref;
    var parts = [];
    path.split("/").forEach(function (part) {
      if (part === "..") parts.pop();
      else if (part && part !== ".") parts.push(part);
    });
    return feedURL(origin + "/" + parts.join("/") + (parts.length && /\/$/.test(path) ? "/" : ""));
  }

  function shortTitle(value) {
    requireValue(typeof value === "string" && value.trim());
    return value.replace(/\s+/g, " ").trim().slice(0, 240);
  }

  function day(ms) {
    return new Date(ms).toISOString().slice(0, 10);
  }

  function timestamp(value) {
    requireValue(typeof value === "string");
    var iso = /^(\d{4})-(\d\d)-(\d\d)(?:T(\d\d):(\d\d):(\d\d)(?:\.\d+)?Z)?$/.exec(value);
    var ms = iso
      ? Date.UTC(+iso[1], +iso[2] - 1, +iso[3], +(iso[4] || 0), +(iso[5] || 0), +(iso[6] || 0))
      : Date.parse(value);
    requireValue(isFinite(ms));
    if (iso) requireValue(day(ms) === value.slice(0, 10));
    return ms;
  }

  function query(url, params) {
    return (
      url +
      "?" +
      Object.keys(params)
        .map(function (key) {
          return encodeURIComponent(key) + "=" + encodeURIComponent(params[key]);
        })
        .join("&")
    );
  }

  function list(obj, name, limit) {
    var rows = obj[name];
    requireValue(Array.isArray(rows) && rows.length <= limit);
    rows.forEach(function (row) {
      requireValue(row && typeof row === "object" && !Array.isArray(row));
    });
    return rows;
  }

  function issues(kind, target, now, read) {
    var scope = kind === "github_repo" ? "repo" : "user";
    var start = now - 14 * DAY;
    var obj = JSON.parse(
      read(
        query(GITHUB + "/search/issues", {
          q: scope + ":" + target + " is:issue is:open created:>=" + day(start),
          sort: "created",
          order: "desc",
          per_page: "25",
        })
      ).body
    );
    requireValue(obj.incomplete_results === false);
    var items = [];
    list(obj, "items", 25).forEach(function (row) {
      if ("pull_request" in row || row.state === "closed") return;
      requireValue(
        row.state === "open" &&
          typeof row.number === "number" &&
          row.number >= 1 &&
          Math.floor(row.number) === row.number &&
          typeof row.repository_url === "string" &&
          row.repository_url.indexOf(GITHUB + "/repos/") === 0
      );
      var repo = normalize("github_repo", row.repository_url.slice((GITHUB + "/repos/").length));
      requireValue((scope === "repo" ? repo : repo.split("/")[0]) === target);
      var at = timestamp(row.created_at);
      if (at >= start && at <= now) {
        var label = repo + "#" + row.number;
        items.push({
          key: "github:" + label,
          text: "Open issue " + label + " (" + day(at) + "): " + shortTitle(row.title),
          url: "https://github.com/" + repo + "/issues/" + row.number,
        });
      }
    });
    return items;
  }

  function workID(row) {
    var match = /^https:\/\/openalex\.org\/(W[1-9][0-9]{0,14})$/.exec(row.id);
    requireValue(match);
    return match[1];
  }

  function primaryTopic(row) {
    var t = row.primary_topic;
    if (
      !t ||
      typeof t.display_name !== "string" ||
      !t.display_name.trim() ||
      typeof t.score !== "number" ||
      !(t.score >= 0.8 && t.score <= 1)
    )
      return null;
    var match = /^https:\/\/openalex\.org\/(T[1-9][0-9]{0,14})$/.exec(t.id);
    return match ? { id: match[1], name: shortTitle(t.display_name).slice(0, 120) } : null;
  }

  function dominant(portfolio, now) {
    var votes = Object.create(null),
      seen = Object.create(null),
      best,
      count = 0;
    portfolio.forEach(function (row) {
      var id = workID(row),
        at = timestamp(row.publication_date);
      if (
        seen[id] ||
        count >= 10 ||
        ["article", "preprint", "review"].indexOf(row.type) < 0 ||
        day(at) < day(now - 730 * DAY) ||
        day(at) > day(now)
      )
        return;
      seen[id] = true;
      count++;
      var t = primaryTopic(row);
      if (!t) return;
      votes[t.id] = (votes[t.id] || 0) + 1;
      if (!best || votes[t.id] > votes[best.id]) best = t;
    });
    return best && votes[best.id] >= 3 && votes[best.id] * 5 >= count * 3 ? best : null;
  }

  function research(kind, target, now, read) {
    var end = day(now),
      start = day(now - 90 * DAY);
    function works(filter, topics, search, limit) {
      var params = {
        filter: filter,
        sort: "publication_date:desc",
        per_page: String(limit || 25),
        select: "id,title,publication_date" + (topics ? ",type,primary_topic" : ""),
      };
      if (search) params.search = '"' + search + '"';
      return list(JSON.parse(read(query(ALEX + "/works", params)).body), "results", limit || 25);
    }
    function papers(rows, label, from) {
      var out = [];
      rows.forEach(function (row) {
        var id = workID(row),
          published = day(timestamp(row.publication_date));
        if (published >= from && published <= end)
          out.push({
            key: "openalex:" + id,
            url: "https://openalex.org/" + id,
            text: label + " (" + published + "): " + shortTitle(row.title),
          });
      });
      return out;
    }
    var dates = "from_publication_date:" + start + ",to_publication_date:" + end;
    if (kind === "research_topic")
      return papers(works(dates, false, target), 'Research matching "' + target + '"', start);
    var ids = [],
      authored = [],
      related = [],
      label;
    if (kind === "research_work") {
      var work = JSON.parse(
        read(
          query(ALEX + "/works/https://doi.org/" + target.split("/").map(encodeURIComponent).join("/"), {
            select: "id,doi",
          })
        ).body
      );
      requireValue(normalize("research_work", work.doi) === target);
      ids = [workID(work)];
      label = "Paper citing DOI " + target;
    } else {
      var field = target.charAt(0) === "A" ? "authorships.author.id" : "authorships.author.orcid";
      var portfolio = works(field + ":" + target + ",to_publication_date:" + end, true);
      ids = portfolio.map(workID);
      authored = papers(portfolio, "Work by author " + target, start);
      var t = dominant(portfolio, now);
      if (t) {
        var since = day(now - 7 * DAY);
        var matches = works(
          "primary_topic.id:" +
            t.id +
            "," +
            field +
            ":!" +
            target +
            ",type:article|preprint|review,from_publication_date:" +
            since +
            ",to_publication_date:" +
            end,
          true,
          "",
          5
        ).filter(function (row) {
          var primary = primaryTopic(row);
          return primary && primary.id === t.id && primary.name === t.name;
        });
        related = papers(
          matches,
          'Related research in the author’s recurring topic "' + t.name + '"',
          since
        ).slice(0, 3);
      }
      label = "Paper citing a work by author " + target;
    }
    if (!ids.length) return authored;
    var citing = papers(works("cites:" + ids.join("|") + "," + dates), label, start);
    var seen = Object.create(null);
    return authored.concat(citing, related).filter(function (item) {
      if (seen[item.key]) return false;
      seen[item.key] = true;
      return true;
    });
  }

  // SHA-256, adapted from web/src/ticket.ts for engines without typed arrays.
  var K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  function rotr(x, n) {
    return (x >>> n) | (x << (32 - n));
  }
  function hashID(text) {
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var data = unescape(encodeURIComponent(text));
    var words = [],
      bits = data.length * 8,
      i;
    for (i = 0; i < data.length; i++)
      words[i >> 2] = (words[i >> 2] || 0) | (data.charCodeAt(i) << (24 - (i % 4) * 8));
    words[i >> 2] = (words[i >> 2] || 0) | (128 << (24 - (i % 4) * 8));
    var size = Math.ceil((data.length + 9) / 64) * 16;
    words[size - 1] = bits;
    for (var offset = 0; offset < size; offset += 16) {
      var W = [];
      for (i = 0; i < 16; i++) W[i] = words[offset + i] || 0;
      for (var i = 16; i < 64; i++) {
        var w15 = W[i - 15];
        var w2 = W[i - 2];
        var s0 = rotr(w15, 7) ^ rotr(w15, 18) ^ (w15 >>> 3);
        var s1 = rotr(w2, 17) ^ rotr(w2, 19) ^ (w2 >>> 10);
        W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
      }
      var a = H[0];
      var b = H[1];
      var c = H[2];
      var d = H[3];
      var e = H[4];
      var f = H[5];
      var g = H[6];
      var h = H[7];
      for (var i = 0; i < 64; i++) {
        var S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        var ch = (e & f) ^ (~e & g);
        var t1 = (h + S1 + ch + K[i] + W[i]) >>> 0;
        var S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) >>> 0;
        h = g;
        g = f;
        f = e;
        e = (d + t1) >>> 0;
        d = c;
        c = b;
        b = a;
        a = (t1 + t2) >>> 0;
      }
      H[0] = (H[0] + a) >>> 0;
      H[1] = (H[1] + b) >>> 0;
      H[2] = (H[2] + c) >>> 0;
      H[3] = (H[3] + d) >>> 0;
      H[4] = (H[4] + e) >>> 0;
      H[5] = (H[5] + f) >>> 0;
      H[6] = (H[6] + g) >>> 0;
      H[7] = (H[7] + h) >>> 0;
    }
    return H.map(function (v) {
      return ("00000000" + v.toString(16)).slice(-8);
    }).join("");
  }

  function attr(node, name) {
    var a = node.attributes[name];
    return (a && a.value) || "";
  }

  function advertised(html, site) {
    var parser = global.nmWatchSax.parser(false, { lowercase: true });
    var head = false,
      base = "",
      links = [],
      hidden = 0,
      stop = {};
    var hiddenTag = /^(script|style|template|noscript|svg|math|iframe|title|textarea)$/;
    parser.onopentag = function (node) {
      var name = node.name;
      if (name === "body") throw stop;
      if (name === "head") head = true;
      if (hiddenTag.test(name)) hidden++;
      if (!head || hidden) return;
      var a = node.attributes;
      if (name === "base" && !base && a.href) base = a.href;
      if (
        name === "link" &&
        /(?:^|\s)alternate(?:\s|$)/i.test(a.rel || "") &&
        /^(application\/(?:rss|atom)\+xml)$/i.test(
          String(a.type || "")
            .split(";")[0]
            .trim()
        ) &&
        a.href
      )
        links.push(a.href);
    };
    parser.onclosetag = function (name) {
      if (name === "head") throw stop;
      if (hiddenTag.test(name) && hidden) hidden--;
    };
    try {
      parser.write(html.slice(0, 131072));
    } catch (e) {
      if (e !== stop) throw e;
    }
    base = resolve(site, base);
    var allowed = [];
    links.forEach(function (href) {
      try {
        var url = resolve(base, href.trim());
        if (sameOrigin(site, url) && url !== site && allowed.indexOf(url) < 0) allowed.push(url);
      } catch (ignored) {
        /* Invalid advertised URLs are not fetched. */
      }
    });
    requireValue(allowed.length === 1);
    return allowed[0];
  }

  function plain(value) {
    return String(value || "")
      .replace(/<[^>]{1,500}>/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 240);
  }

  function parseFeed(xml, source, now) {
    var parser = global.nmWatchSax.parser(true, { xmlns: true, strictEntities: true });
    var stack = [],
      items = [],
      keys = Object.create(null),
      format = "",
      ready = false,
      seen = 0;
    var row = null,
      rowDepth = 0,
      field = "",
      value = "";
    parser.ondoctype = function () {
      throw new Error("Unsupported DTD");
    };
    parser.onerror = function (e) {
      throw e;
    };
    parser.onopentag = function (node) {
      requireValue(stack.length < 100);
      var base = stack.length ? stack[stack.length - 1].base : source;
      var next = attr(node, "xml:base");
      if (next) {
        try {
          base = resolve(base, next);
        } catch (ignored) {
          base = "";
        }
      }
      var depth = stack.length + 1,
        local = node.local,
        uri = node.uri;
      if (depth === 1) {
        if (uri === ATOM && local === "feed") {
          format = "atom";
          ready = true;
        } else if (uri === RDF && local === "RDF") {
          format = "rdf";
          ready = true;
        } else if (!uri && local === "rss") format = "rss";
        else throw new Error("Unsupported feed format");
      }
      if (format === "rss" && depth === 2 && local === "channel" && !uri) ready = true;
      var isRow =
        (format === "atom" && depth === 2 && uri === ATOM && local === "entry") ||
        (format === "rdf" && depth === 2 && uri === RSS1 && local === "item") ||
        (format === "rss" && depth === 3 && !uri && local === "item" && stack[1].local === "channel");
      stack.push({ base: base, local: local });
      if (isRow && seen++ < 40) {
        row = { id: attr(node, "rdf:about"), url: "" };
        rowDepth = depth;
      } else if (row && depth === rowDepth + 1) {
        field = "";
        var feedNs = format === "atom" ? ATOM : format === "rdf" ? RSS1 : "";
        if (
          uri === feedNs &&
          /^(title|summary|description|id|guid|published|updated|pubDate|link)$/.test(local)
        )
          field = local;
        if (uri === "http://purl.org/dc/elements/1.1/" && local === "date") field = "date";
        value = "";
        if (field === "link" && format === "atom") {
          var rel = attr(node, "rel");
          if (!row.url && (!rel || rel === "alternate") && base && attr(node, "href")) {
            try {
              row.url = resolve(base, attr(node, "href").trim());
            } catch (ignored) {
              /* Use another alternate or the selected feed. */
            }
          }
          field = "";
        }
      }
    };
    function append(text) {
      if (row && field && value.length < 2400) value += text.slice(0, 2400 - value.length);
    }
    parser.ontext = append;
    parser.oncdata = append;
    parser.onclosetag = function () {
      var depth = stack.length,
        element = stack.pop();
      if (!row) return;
      if (depth === rowDepth + 1 && field) {
        if (field === "link" && value.trim() && !row.url && element.base) {
          try {
            row.url = resolve(element.base, value.trim());
          } catch (ignored) {
            /* Fall back to the feed. */
          }
        } else if (!row[field]) row[field] = value.trim();
        field = "";
      }
      if (depth !== rowDepth) return;
      var title = plain(row.title) || plain(row.summary) || plain(row.description);
      var when = row.published || row.pubDate || row.date || row.updated;
      // Feed dates are optional. The first sample is silent for undated feeds.
      var stamp = NaN;
      if (when) {
        try {
          stamp = timestamp(when);
        } catch (ignored) {
          /* Nonstandard label. */
        }
      }
      if (title && (!isFinite(stamp) || (stamp >= now - 90 * DAY && stamp <= now))) {
        var key = "feed:" + hashID(source + "\n" + (row.id || row.guid || row.url || title));
        if (!keys[key]) {
          items.push({ key: key, text: title, url: row.url || source });
          keys[key] = true;
        }
      }
      row = null;
    };
    parser.write(xml).close();
    requireValue(ready);
    return items;
  }

  function run(input) {
    requireValue(input && typeof input.now === "number" && isFinite(input.now) && input.now >= 0);
    var kind = input.kind,
      target = normalize(kind, input.target),
      responses = input.responses;
    requireValue(Array.isArray(responses) && responses.length <= 6 && kind !== "scholar_profile");
    var index = 0,
      awaiting = {};
    function read(url) {
      if (index === responses.length) {
        awaiting.url = url;
        throw awaiting;
      }
      var r = responses[index++];
      requireValue(
        r &&
          r.url === url &&
          typeof r.body === "string" &&
          r.body.length <= (kind === "feed" ? 1048576 : 2097152)
      );
      var actual = r.finalUrl || url;
      requireValue(kind === "feed" ? sameOrigin(feedURL(actual), target) : actual === url);
      return { body: r.body, finalUrl: actual };
    }
    try {
      var result;
      if (kind === "feed") {
        var feed = read(target);
        if (/^\s*(?:<!doctype\s+html\b|<html\b|<head\b)/i.test(feed.body))
          feed = read(advertised(feed.body, feed.finalUrl));
        result = { source: feed.finalUrl, items: parseFeed(feed.body, feed.finalUrl, input.now) };
      } else {
        result = {
          items:
            kind.indexOf("github_") === 0
              ? issues(kind, target, input.now, read)
              : research(kind, target, input.now, read),
        };
      }
      requireValue(index === responses.length);
      return result;
    } catch (e) {
      if (e === awaiting) return { request: { url: e.url } };
      throw e;
    }
  }

  global.nmWatchNormalize = normalize;
  global.NanoMusePublicRead = function (text) {
    try {
      return JSON.stringify(run(JSON.parse(text)));
    } catch (ignored) {
      return '{"error":"Public source unavailable"}';
    }
  };
})(this);
