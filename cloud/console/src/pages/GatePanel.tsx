import { useT } from "../lib/i18n";
import type { UpstreamGate } from "../lib/types";
import { Gauge } from "../ui/charts";
import { Panel, cx } from "../ui/primitives";

export function GatePanel({ gate, models, retries }: { gate: UpstreamGate; models: [string, UpstreamGate][]; retries?: number }) {
  const T = useT();
  const retryLabel = retries === undefined ? "" : `${T.g.retries} ${retries}`;
  if (models.length) {
    return (
      <Panel title={T.lv.modelGates} sub={retryLabel}>
        <ul className="m-0 grid list-none gap-3 p-0">
          {models.map(([model, lane]) => (
            <li key={model}>
              <code className="break-all">{model}</code>
              <div className="mt-1 flex flex-wrap justify-between gap-x-2 text-[12px]">
                <span>{T.lv.activeOf(lane.active, lane.limit)}</span>
                <span className={lane.waiting ? "text-bad" : "text-ink-3"}>{T.lv.queued(lane.waiting)}</span>
              </div>
              <Gauge {...lane} className="mt-1" />
            </li>
          ))}
        </ul>
      </Panel>
    );
  }

  const sub = retries === undefined ? T.lv.gateSub(gate.limit) : `${T.g.limit} ${gate.limit} · ${retryLabel}`;
  return (
    <Panel title={T.lv.gate} sub={sub}>
      <div className="kpi">
        <div className={cx("v", gate.waiting > 0 ? "text-bad" : gate.active >= gate.limit * 0.75 ? "text-warn" : "")}>
          {gate.active} <span className="text-[14px] font-normal text-ink-3">/ {gate.limit}</span>
        </div>
        <div className="sub">{gate.waiting || retries !== undefined ? T.lv.queued(gate.waiting) : T.lv.activeOf(gate.active, gate.limit)}</div>
      </div>
      <Gauge {...gate} className="mt-3" />
    </Panel>
  );
}
