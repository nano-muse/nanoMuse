import { afterEach, describe, expect, it } from "vitest";
import { dictionaryKeys, getLocale, setLocaleSetting, t } from "./index";
import zhCN from "./zh-CN";

// The app's source, as text, so the dictionary can be checked against what is actually rendered.
const SOURCES = import.meta.glob<string>(["../**/*.ts", "../**/*.tsx", "!../**/*.test.ts", "!../i18n/**"], {
  query: "?raw",
  import: "default",
  eager: true,
});

afterEach(() => setLocaleSetting("en"));

describe("t", () => {
  it("returns the English key when there is no translation", () => {
    setLocaleSetting("en");
    expect(t("Nothing here")).toBe("Nothing here");
    expect(t("Hi, {name}", { name: "Sam" })).toBe("Hi, Sam");
  });

  it("translates and keeps placeholders", () => {
    setLocaleSetting("zh-CN");
    expect(getLocale()).toBe("zh-CN");
    expect(t("Feed")).toBe("动态");
    expect(t("Hi, I'm {name}.", { name: "Muse" })).toBe("你好，我是 Muse。");
    expect(t("{n} frames", { n: 3 })).toBe("3 帧");
  });

  it("leaves unknown placeholders alone rather than printing undefined", () => {
    setLocaleSetting("en");
    expect(t("Due in {n} days")).toBe("Due in {n} days");
  });
});

/** Every `t("...")` literal in the app source. */
function sourceKeys(): Set<string> {
  const keys = new Set<string>();
  const re = /\bt\(\s*"((?:[^"\\]|\\.)*)"/g;
  for (const src of Object.values(SOURCES)) {
    for (const m of src.matchAll(re)) keys.add(m[1].replace(/\\"/g, '"'));
  }
  return keys;
}

describe("zh-CN dictionary", () => {
  it("sees the app source", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(10);
  });

  it("covers every literal string the app translates", () => {
    const missing = [...sourceKeys()].filter((k) => !(k in zhCN)).sort();
    expect(missing, `strings without a 简体中文 translation:\n${missing.join("\n")}`).toEqual([]);
  });

  it("keeps the same placeholders as the English text", () => {
    const vars = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    const broken = dictionaryKeys("zh-CN").filter((k) => JSON.stringify(vars(k)) !== JSON.stringify(vars(zhCN[k])));
    expect(broken, `placeholders differ:\n${broken.join("\n")}`).toEqual([]);
  });

  it("has no empty translations", () => {
    expect(dictionaryKeys("zh-CN").filter((k) => !zhCN[k].trim())).toEqual([]);
  });
});

describe("localLabel", () => {
  it("translates the fixed part of a server label and keeps the user's words", async () => {
    const { localLabel } = await import("./index");
    setLocaleSetting("zh-CN");
    expect(localLabel("Working on your goal: Run a 10k")).toBe("推进目标：Run a 10k");
    expect(localLabel("Reminder: call mum")).toBe("提醒：call mum");
    expect(localLabel("Tidied memory")).toBe("整理了记忆");
    expect(localLabel("Something else")).toBe("Something else");
    setLocaleSetting("en");
    expect(localLabel("Check-in: Japanese")).toBe("Check-in: Japanese");
  });
});

describe("localReason", () => {
  it("says why the Sentinel asked in the person's words, keeping the tool and the target", async () => {
    const { localReason } = await import("./index");
    setLocaleSetting("en");
    expect(localReason("'shell' is in always_ask_tools")).toBe("shell is on your always-ask list");
    expect(localReason("risk level is 'sensitive' (mode=ask)")).toBe("an action rated sensitive, in ask mode");
    expect(localReason("auto mode: approval skipped")).toBe("auto mode: not asked");
    expect(localReason("covered by your 'always' permission for shell:ls")).toBe("covered by your always permission for shell:ls");
    expect(localReason("matched rule tool='shell' match=rm")).toBe("matched rule tool='shell' match=rm");
    setLocaleSetting("zh-CN");
    expect(localReason("'shell' is in always_ask_tools")).toBe("shell 在你的「总是询问」列表里");
    expect(localReason("risk level is 'sensitive' (mode=ask)")).toBe("这个操作的风险等级是「敏感」，哨兵处于询问模式");
    expect(
      localReason("private data was read earlier in this conversation and 'web_fetch' can send data to example.org, which is not on sentinel.egress_allowlist"),
    ).toBe("这段对话早些时候读取过私密数据，而 web_fetch 可能把它发给 example.org，这个地址不在你的允许列表里");
  });
});

describe("localDetail", () => {
  it("translates a server sentence that carries a number", async () => {
    const { localDetail } = await import("./index");
    setLocaleSetting("zh-CN");
    expect(localDetail("the file is larger than 25 MB")).toBe("文件超过了 25 MB。");
    expect(localDetail("empty file")).toBe("文件是空的");
    setLocaleSetting("en");
    expect(localDetail("the file is larger than 25 MB")).toBe("The file is larger than 25 MB.");
  });
});
