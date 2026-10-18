// Tutor text: ``` fences become code blocks, `inline code` becomes <code>, and citation tags
// like [syn101-week3-loops-p002] become links to the passage. Text is never parsed as HTML.
import { h, icon } from "./dom.js";
import { copyText } from "./ui.js";

const CITE = /\[([a-z0-9]+(?:-[a-z0-9]+)*-p\d{3})\]/g;

function cited(text) {
  const out = [];
  let last = 0;
  for (const m of text.matchAll(CITE)) {
    out.push(text.slice(last, m.index));
    out.push(h("a", { class: "cite", href: `#/resources?id=${m[1]}`, title: `Source: ${m[1]}` }, "source"));
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return out;
}

function inline(text) {
  return text.split(/`([^`\n]+)`/).map((part, i) =>
    (i % 2 === 1 ? h("code", { class: "inline-code" }, part) : cited(part)));
}

export function richText(text) {
  return text.split(/```[a-zA-Z0-9]*\n?/).map((part, i) => {
    if (i % 2 === 0) return inline(part.trim());
    const code = part.replace(/\n$/, "");
    return h(
      "div", { class: "code-block" },
      h("pre", null, code),
      h("button", { type: "button", class: "btn small copy", "aria-label": "Copy code", onClick: () => copyText(code) },
        icon("copy")),
    );
  });
}
