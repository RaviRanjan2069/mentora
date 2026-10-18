import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import Icon, { IconName } from "../icons";
import { Portal } from "./ui";

export interface PaletteEntry { label: string; hint?: string; icon: IconName; run: () => void }
interface Hit { id: string; section: string | null; week: number | null; text: string }

/** Ctrl+K / ⌘K: jump to a page, search the course material, or (students) ask the tutor. */
export default function CommandPalette({ pages, onClose, ask }: {
  pages: PaletteEntry[]; onClose: () => void; ask?: (q: string) => void;
}) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);

  useEffect(() => {
    const query = q.trim();
    if (query.length < 3) { setHits([]); return; }
    const t = window.setTimeout(() => {
      api.get<{ hits: Hit[] }>(`/api/rag/search?q=${encodeURIComponent(query)}`)
        .then((r) => setHits(r.hits.slice(0, 4)))
        .catch(() => setHits([]));
    }, 250);
    return () => window.clearTimeout(t);
  }, [q]);

  const entries = useMemo<PaletteEntry[]>(() => {
    const needle = q.trim().toLowerCase();
    const out = pages.filter((p) => !needle || p.label.toLowerCase().includes(needle));
    if (ask && needle.length >= 3) {
      out.push({ label: `Ask the tutor: “${q.trim()}”`, icon: "bot", run: () => ask(q.trim()) });
    }
    for (const h of hits) {
      out.push({
        label: h.section ?? h.id, hint: h.text.slice(0, 90), icon: "book",
        run: () => { window.location.hash = `#/resources?id=${h.id}`; },
      });
    }
    return out;
  }, [pages, q, hits, ask]);

  useEffect(() => setActive(0), [q, hits]);

  function choose(e: PaletteEntry) { e.run(); onClose(); }
  function onKey(ev: KeyboardEvent) {
    if (ev.key === "ArrowDown") { ev.preventDefault(); setActive((a) => Math.min(a + 1, entries.length - 1)); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (ev.key === "Enter" && entries[active]) { ev.preventDefault(); choose(entries[active]); }
    else if (ev.key === "Escape") onClose();
  }

  return (
    <Portal><div className="overlay top" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search and jump">
        <div className="palette-input">
          <Icon name="search" />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
                 placeholder="Go to a page, search course notes…" aria-label="Search"
                 role="combobox" aria-expanded="true" aria-controls="palette-list" />
          <kbd>Esc</kbd>
        </div>
        <ul className="palette-list" id="palette-list" role="listbox">
          {entries.length === 0 && <li className="empty" style={{ padding: "10px 14px" }}>No matches.</li>}
          {entries.map((e, i) => (
            <li key={`${e.label}-${i}`} role="option" aria-selected={i === active}
                className={i === active ? "active" : ""} onMouseEnter={() => setActive(i)}
                onMouseDown={(ev) => { ev.preventDefault(); choose(e); }}>
              <Icon name={e.icon} />
              <div style={{ minWidth: 0 }}>
                <div className="title">{e.label}</div>
                {e.hint && <div className="muted small ellipsis">{e.hint}</div>}
              </div>
            </li>
          ))}
        </ul>
        <div className="palette-foot muted small">↑ ↓ to move · Enter to open · type 3+ letters to search the course notes</div>
      </div>
    </div></Portal>
  );
}
