import { beforeAll, describe, expect, it } from "vitest";
import { setLocaleSetting, t } from "./i18n";
import { CATALOGUE, catalogueIdFor, plans, presetFor, providersFor, unavailableLine } from "./providers";

describe("the own-key catalogue (contract C11)", () => {
  // the sentences below are the English ones; `t` follows the machine's language otherwise
  beforeAll(() => setLocaleSetting("en"));

  it("is the runtime's file, with the four capabilities and chat on every entry", () => {
    expect(CATALOGUE.length).toBeGreaterThan(10);
    for (const p of CATALOGUE) expect(p.capabilities, p.id).toContain("chat");
    expect(CATALOGUE.find((p) => p.id === "bailian")?.capabilities).toEqual(["chat", "vision", "image", "video"]);
  });

  it("leads with Bailian on the mainland and OpenRouter then OpenAI elsewhere", () => {
    expect(providersFor("cn").slice(0, 1).map((p) => p.id)).toEqual(["bailian"]);
    expect(providersFor("global").slice(0, 2).map((p) => p.id)).toEqual(["openrouter", "openai"]);
    // the local servers and "custom" are not in the list; the mainland-only vendor is not offered abroad
    for (const p of providersFor("global")) expect(["ollama", "lm-studio", "vllm", "custom", "bailian"]).not.toContain(p.id);
  });

  it("keeps only the providers with the capability", () => {
    for (const p of providersFor("global", "image")) expect(p.capabilities).toContain("image");
    expect(providersFor("global", "video")).toEqual([]);
    expect(providersFor("cn", "video").map((p) => p.id)).toEqual(["bailian"]);
  });

  it("writes the one sentence with the region's providers, four at most", () => {
    const line = unavailableLine(t, "image", "global", "en");
    expect(line).toMatch(/^Pictures need a provider with image models: .+ or .+\.$/);
    expect(line.split(", ").length).toBeLessThanOrEqual(4);
    expect(unavailableLine(t, "video", "cn", "en")).toBe("Clips need a provider with video models: Alibaba Cloud Bailian.");
  });

  it("maps the catalogue's ids to the runtime's presets and back", () => {
    expect(presetFor("bailian")).toBe("qwen");
    expect(presetFor("moonshot")).toBe("kimi");
    expect(presetFor("openai")).toBe("openai");
    expect(catalogueIdFor("qwen")).toBe("bailian");
    expect(catalogueIdFor("openai_responses")).toBe("openai");
  });

  it("knows the plans and that the ChatGPT one covers chat and the hands only", () => {
    const chatgpt = plans().find((p) => p.id === "chatgpt");
    expect(chatgpt?.covers).toEqual(["chat", "vision"]);
    expect(chatgpt?.here).toBe(true);
    expect(plans().map((p) => p.id)).toEqual(["chatgpt", "claude", "kimi", "openrouter"]);
  });
});
