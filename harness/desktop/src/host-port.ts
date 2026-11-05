// The host's port, kept across launches (src/main.ts, hostPort). The window's origin is
// `127.0.0.1:<port>`, and the origin is the browser's storage key — the preferences, the
// star asks' memory, the live stage's place, the harness's own settings all live in that
// origin's localStorage — so a port that changed on every launch meant an app that forgot
// everything on every launch. The port used last time is tried first (it is written to
// `<home>/port`), then the default, then any free one.
//
// A taken port does not overwrite the memory, though. The usual taker is an orphaned Host
// of ours — the app was killed while the Host child lived on — and it is gone with the next
// reboot at the latest; the fallback port this launch runs on is for this one launch, and
// the remembered port comes back the moment its taker is. Writing the fallback down would
// strand the origin for good: everything the browser kept under `127.0.0.1:<last>` would
// sit behind a port the app never serves on again.
//
// Nothing here touches Electron, so `npm test` can run it with a fake tryPort.

/** The port tried first on a fresh install (the connectors' loopback is 38417). */
export const HOST_PORT_DEFAULT = 38421;

/** How the chooser reads and writes `<home>/port`, and tries to bind a port. */
export interface PortIO {
  /** The port the last launch served on, or 0 when nothing is remembered. */
  readRemembered(): number;
  /** Records the port the origin lives at. */
  writeRemembered(port: number): void;
  /** Tries to bind one loopback port (0 = any); the port bound, or 0 when it is taken. */
  tryPort(port: number): Promise<number>;
}

/** The port this launch serves on, and what became of the memory. */
export interface PortChoice {
  port: number;
  /** True when the memory names this port — on a fallback launch the remembered port is
   *  deliberately left in place for when its taker is gone. */
  remembered: boolean;
}

/** The port this launch's origin lives on: the remembered one when it is free, else the
 *  default, else any free port — remembering only a port the origin can keep living at. */
export async function chooseHostPort(io: PortIO): Promise<PortChoice> {
  const last = io.readRemembered();
  const candidates = last > 0 ? [last, HOST_PORT_DEFAULT, 0] : [HOST_PORT_DEFAULT, 0];
  for (const candidate of candidates) {
    const port = await io.tryPort(candidate);
    if (port <= 0) {
      continue;
    }
    const remembered = last === 0 || port === last;
    if (remembered) {
      io.writeRemembered(port);
    }
    return { port, remembered };
  }
  throw new Error("no free loopback port for the host");
}
