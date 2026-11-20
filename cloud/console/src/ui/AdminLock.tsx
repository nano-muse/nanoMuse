/** The admin entry validates a token without treating a service outage as bad credentials. */
import { useEffect, useRef, useState } from "react";
import { ApiError, get, token } from "../lib/api";
import { LANG_KEY, initialLang, tableOf } from "../lib/i18n";
import type { Lang } from "../lib/locales";
import { Btn } from "./primitives";

export function AdminLock({ onEnter, expired }: { onEnter: () => void; expired: boolean }) {
  const [lang, setLang] = useState<Lang>(initialLang);
  const T = tableOf(lang);
  const [v, setV] = useState("");
  const [failure, setFailure] = useState<"token" | "service" | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    const candidate = v.trim();
    if (!candidate || inFlight.current || !mounted.current) return;
    inFlight.current = true;
    setBusy(true);
    setFailure(null);
    try {
      // A candidate is not a saved sign-in until validation succeeds.
      await get("/v1/admin/health", candidate);
      if (!mounted.current) return;
      token.set(candidate);
      setFailure(null);
      onEnter();
    } catch (error) {
      // The API clears rejected credentials only on 401; outages are retryable.
      if (mounted.current) setFailure(error instanceof ApiError && error.status === 401 ? "token" : "service");
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="panel w-full max-w-sm p-6">
        <div className="mb-1 flex items-center gap-2">
          <img src="/app/icon.svg" alt="" className="h-7 w-7 rounded-lg" />
          <div className="text-[16px] font-semibold">{T.app}</div>
          <button
            type="button"
            className="ml-auto text-[12px] text-ink-3 hover:text-ink"
            onClick={() => {
              const l = lang === "zh" ? "en" : "zh";
              setLang(l);
              localStorage.setItem(LANG_KEY, l);
            }}
          >
            {T.top.lang}
          </button>
        </div>
        <div className="text-[14px] font-medium">{T.lock.title}</div>
        <p className="sub mt-1 mb-4">{T.lock.hint}</p>
        <input type="password" className="inp w-full" placeholder={T.lock.placeholder} value={v} autoFocus onChange={(e) => setV(e.target.value)} onKeyDown={(e) => e.key === "Enter" && go()} />
        {(failure || expired) && <div role="alert" className="mt-2 text-[12.5px] text-bad">{failure === "token" ? T.lock.bad : failure === "service" ? T.lock.unavailable : T.lock.expired}</div>}
        <Btn variant="primary" className="mt-4 w-full justify-center" onClick={go} disabled={busy}>
          {T.lock.enter}
        </Btn>
      </div>
    </div>
  );
}

