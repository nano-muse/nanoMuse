import { CalendarDays, Code2, FileImage, FileSpreadsheet, FileText, Globe, LibraryBig, Loader2, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, fileUrl } from "../api";
import { TabHeader } from "../components/TabHeader";
import { LoadError } from "../components/LoadError";
import { useT } from "../i18n";
import { useStore } from "../store";
import type { FileInfo } from "../types";
import { relativeDay } from "../components/ChatsDrawer";
import { cx, fileKind } from "../util";

/** Media are what the eye takes in; everything else is an artifact — Muse's two-way split. */
const MEDIA_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "heic", "mp3", "wav", "m4a", "ogg", "flac", "mp4", "mov", "webm", "mkv"]);
function isMedia(name: string): boolean {
  return MEDIA_EXT.has(name.toLowerCase().split(".").pop() ?? "");
}

/**
 * Muse's Library: a two-way segmented control (artifacts / media) over what the agent made,
 * newest first, with Muse's empty states. Rows open the file viewer. This is the agent's
 * workspace, so files you drop there yourself show up too.
 */
export function LibraryScreen() {
  const { state, openFile } = useStore();
  const space = state.threads.find((thread) => thread.id === state.activeThread)?.memory_space ?? "personal";
  const [files, setFiles] = useState<FileInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [segment, setSegment] = useState<0 | 1>(0);
  const [query, setQuery] = useState("");
  const t = useT();

  // Reload whenever the agent finishes a step (the timeline moves) or the tab is opened.
  const version = Object.values(state.events).reduce((n, list) => n + list.length, 0);
  useEffect(() => {
    let alive = true;
    setFiles(null);
    api.files(500, space)
      .then((d) => {
        if (!alive) return;
        setFiles(d);
        setError(null);
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [version, state.feedVersion, attempt, space]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (files ?? []).filter((f) => isMedia(f.name) === (segment === 1) && (!q || f.path.toLowerCase().includes(q)));
  }, [files, segment, query]);

  return (
    <div className="flex h-full flex-col">
      <TabHeader title={t("Library")} />
      <div className="shrink-0 px-4 pt-1 pb-2.5">
        <Segmented labels={[t("Artifacts"), t("Media")]} selected={segment} onSelect={(i) => setSegment(i as 0 | 1)} />
        {(files?.length ?? 0) > 8 && (
          <label className="mt-2.5 flex items-center gap-2 rounded-full bg-surface-2 px-3.5 py-2">
            <Search size={16} className="text-muted" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("Search files")} className="flex-1 bg-transparent text-[14.5px] outline-none" />
          </label>
        )}
      </div>

      <div className="flex-1 overflow-y-auto pb-6">
        {files === null && error && <LoadError message={error} onRetry={() => setAttempt((n) => n + 1)} />}
        {files === null && !error && (
          <div className="flex justify-center py-10 text-muted">
            <Loader2 className="animate-spin" size={20} />
          </div>
        )}
        {files !== null && shown.length === 0 && (
          <div className="flex flex-col items-center px-8 pt-9 text-center">
            <LibraryBig size={34} className="text-muted" />
            <div className="mt-3.5 text-[16px] font-medium text-muted">
              {query ? t("No files match.") : segment === 0 ? t("Nothing created yet") : t("No media yet")}
            </div>
            {!query && (
              <p className="mt-1 text-[12px] text-muted">
                {segment === 0 ? t("Documents, tables and pages I write for you will show up here.") : t("Photos, screenshots and recordings I produce will show up here.")}
              </p>
            )}
          </div>
        )}
        <ul>
          {shown.map((f) => (
            <li key={f.path}>
              <FileRow file={f} onOpen={() => openFile(f.path)} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** Muse's pill-shaped two-way control: white track with a hairline, grey pill on the active side. */
export function Segmented({ labels, selected, onSelect }: { labels: string[]; selected: number; onSelect: (i: number) => void }) {
  return (
    <div role="tablist" className="flex h-12 w-full rounded-full border border-border bg-surface p-1">
      {labels.map((label, i) => (
        <button
          key={label}
          type="button"
          role="tab"
          aria-selected={i === selected}
          onClick={() => onSelect(i)}
          className={cx("flex-1 rounded-full text-[14px] font-semibold transition", i === selected ? "bg-surface-2" : "bg-transparent")}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** One file the way Muse lists it: a tile (the picture itself for images, a glyph otherwise), the name, when · size · folder. */
function FileRow({ file, onOpen }: { file: FileInfo; onOpen: () => void }) {
  const kind = fileKind(file.name);
  const icon =
    kind === "html" ? (
      <Globe size={22} />
    ) : kind === "image" ? (
      <FileImage size={22} />
    ) : kind === "data" ? (
      <FileSpreadsheet size={22} />
    ) : kind === "code" ? (
      <Code2 size={22} />
    ) : kind === "event" ? (
      <CalendarDays size={22} />
    ) : (
      <FileText size={22} />
    );
  const dir = file.path.includes("/") ? file.path.slice(0, file.path.lastIndexOf("/")) : "";
  return (
    <button type="button" onClick={onOpen} className="flex w-full items-center gap-3.5 px-4 py-2 text-left active:bg-surface-2/70">
      <span className="flex h-[46px] w-[46px] shrink-0 items-center justify-center overflow-hidden rounded-[10px] bg-surface-2 text-muted">
        {kind === "image" ? <img src={fileUrl(file.path)} alt="" loading="lazy" className="h-full w-full object-cover" /> : icon}
      </span>
      <span className="min-w-0 flex-1 space-y-0.5">
        <span className="block truncate text-[15px] font-medium">{file.name}</span>
        <span className="block truncate text-[12px] text-muted">{[relativeDay(file.modified), formatSize(file.size), dir].filter(Boolean).join(" · ")}</span>
      </span>
    </button>
  );
}

function formatSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
