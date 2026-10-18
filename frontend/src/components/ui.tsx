import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Icon from "../icons";

// --- toasts -------------------------------------------------------------------------------------

type Tone = "ok" | "error" | "info";
interface Toast { id: number; text: string; tone: Tone }
const ToastCtx = createContext<(text: string, tone?: Tone) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Tone = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, text, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            <Icon name={t.tone === "error" ? "alert" : t.tone === "ok" ? "check" : "bulb"} />
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/** `toast("Saved")`, `toast("Could not save", "error")`. */
export const useToast = () => useContext(ToastCtx);

// --- loading placeholders ---------------------------------------------------------------------

export function Skeleton({ cards = 3, stats = false }: { cards?: number; stats?: boolean }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {stats && (
        <div className="grid cols-4">
          {[0, 1, 2, 3].map((i) => <div key={i} className="card skeleton" style={{ height: 96 }} />)}
        </div>
      )}
      {Array.from({ length: cards }, (_, i) => (
        <div key={i} className="card skeleton" style={{ height: i === 0 ? 220 : 140 }} />
      ))}
    </div>
  );
}

// --- overlays -------------------------------------------------------------------------------------

/** Overlays render into <body> so no transformed ancestor can clip or re-anchor them. */
export const Portal = ({ children }: { children: ReactNode }) => createPortal(children, document.body);

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
}

export function Modal({ title, onClose, children, wide }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean;
}) {
  useEscape(onClose);
  return (
    <Portal><div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="row between modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        {children}
      </div>
    </div></Portal>
  );
}

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEscape(onClose);
  return (
    <Portal><div className="overlay right" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="row between modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </div>
        {children}
      </aside>
    </div></Portal>
  );
}

/** Button plus a small panel that closes on outside click or Escape. */
export function Popover({ button, label, children, badge }: {
  button: ReactNode; label: string; children: (close: () => void) => ReactNode; badge?: number;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); window.removeEventListener("keydown", onKey); };
  }, [open]);
  return (
    <div className="popover-wrap" ref={ref}>
      <button className="icon-btn wide" aria-label={label} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {button}
        {badge !== undefined && badge > 0 && <span className="dot">{badge}</span>}
      </button>
      {open && <div className="popover" role="menu">{children(close)}</div>}
    </div>
  );
}

/** Copy text to the clipboard with a toast. */
export function useCopy() {
  const toast = useToast();
  return (text: string) => {
    navigator.clipboard?.writeText(text)
      .then(() => toast("Copied to clipboard"))
      .catch(() => toast("Copy is not available in this browser", "error"));
  };
}
