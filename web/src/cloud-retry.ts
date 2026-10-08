import type { TimelineEvent } from "./types";

/**
 * *Use nanoMuse Cloud this time* under a failed turn (the own-key models contract, section 4).
 * The button belongs under an error notice when the person is signed in, the chat model is not
 * the account's, the chat is not another device's, the failure is not the allowance's (that card
 * has its own ways on) and the failed turn was not on the account already (`model_used`). It
 * resends the words of the last user message above the notice, attachments included.
 */
export interface CloudRetryContext {
  signedIn: boolean;
  chatOnCloud: boolean;
  deviceChat: boolean;
}

export function cloudRetryTarget(events: readonly TimelineEvent[], index: number, ctx: CloudRetryContext): { text: string; files: string[] } | undefined {
  if (!ctx.signedIn || ctx.chatOnCloud || ctx.deviceChat) return undefined;
  const ev = events[index];
  if (ev?.type !== "notice" || ev.level !== "error" || !ev.code || ev.code === "allowance" || ev.model_used) return undefined;
  for (let j = index - 1; j >= 0; j--) {
    const u = events[j];
    if (u?.type === "user") {
      const files = (u.files ?? []).map((f) => f.path);
      return u.text || files.length > 0 ? { text: u.text, files } : undefined;
    }
  }
  return undefined;
}
