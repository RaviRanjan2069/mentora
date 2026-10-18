// Shared UI pieces: toasts, loading placeholders, modal, drawer, popover, copy.
import { h, icon } from "./dom.js";

// --- toasts -------------------------------------------------------------------------------

let toastBox = null;

/** toast("Saved"), toast("Could not save", "error") */
export function toast(text, tone = "ok") {
  if (!toastBox) {
    toastBox = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.appendChild(toastBox);
  }
  const name = tone === "error" ? "alert" : tone === "ok" ? "check" : "bulb";
  const el = h("div", { class: `toast ${tone}` }, icon(name), h("span", null, text));
  toastBox.appendChild(el);
  window.setTimeout(() => el.remove(), 4000);
}

export function copyText(text) {
  if (!navigator.clipboard) {
    toast("Copy is not available in this browser", "error");
    return;
  }
  navigator.clipboard
    .writeText(text)
    .then(() => toast("Copied to clipboard"))
    .catch(() => toast("Copy is not available in this browser", "error"));
}

// --- loading placeholders -------------------------------------------------------------------

export function skeleton({ cards = 3, stats = false } = {}) {
  return h(
    "div",
    { class: "stack", "aria-busy": "true", "aria-label": "Loading" },
    stats
      ? h("div", { class: "grid cols-4" },
          [0, 1, 2, 3].map(() => h("div", { class: "card skeleton", style: { height: 96 } })))
      : null,
    Array.from({ length: cards }, (_, i) =>
      h("div", { class: "card skeleton", style: { height: i === 0 ? 220 : 140 } })),
  );
}

export const errorLine = (text) => h("p", { class: "error" }, text);

// --- overlays ---------------------------------------------------------------------------------

/** Opens an overlay in <body>; content(close) builds its body. Escape or a click on the
 * backdrop closes it. Returns close(). */
function overlay(kind, title, content, { wide = false, onClose } = {}) {
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    window.removeEventListener("keydown", onKey);
    root.remove();
    onClose?.();
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
  };
  const head = h(
    "div", { class: "row between modal-head" },
    h("h2", null, title),
    h("button", { class: "icon-btn", onClick: close, "aria-label": "Close" }, icon("x")),
  );
  const body = h("div");
  const panel = kind === "drawer"
    ? h("aside", { class: "drawer", role: "dialog", "aria-modal": "true", "aria-label": title }, head, body)
    : h("div", { class: `modal ${wide ? "wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title }, head, body);
  const root = h("div", {
    class: kind === "drawer" ? "overlay right" : "overlay",
    onMousedown: (e) => {
      if (e.target === e.currentTarget) close();
    },
  }, panel);
  window.addEventListener("keydown", onKey);
  document.body.appendChild(root);
  const built = content(close, body);
  if (built) body.appendChild(built);
  return close;
}

export const openModal = (title, content, opts) => overlay("modal", title, content, opts);
export const openDrawer = (title, content, opts) => overlay("drawer", title, content, opts);

/** Button plus a small panel that closes on outside click or Escape. content(close) -> node. */
export function popover({ button, label, badge = 0, content }) {
  const panel = h("div", { class: "popover", role: "menu" });
  const btn = h("button", { class: "icon-btn wide", "aria-label": label, "aria-expanded": "false" },
    button, badge > 0 ? h("span", { class: "dot" }, badge) : null);
  const wrap = h("div", { class: "popover-wrap" }, btn);
  const onDown = (e) => {
    if (!wrap.contains(e.target)) close();
  };
  const onKey = (e) => {
    if (e.key === "Escape") close();
  };
  function close() {
    panel.remove();
    btn.setAttribute("aria-expanded", "false");
    document.removeEventListener("mousedown", onDown);
    window.removeEventListener("keydown", onKey);
  }
  btn.addEventListener("click", () => {
    if (panel.isConnected) {
      close();
      return;
    }
    panel.replaceChildren(content(close));
    wrap.appendChild(panel);
    btn.setAttribute("aria-expanded", "true");
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
  });
  return wrap;
}
