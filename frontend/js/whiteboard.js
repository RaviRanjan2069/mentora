// The sign-in whiteboard: the Mentora tutor writes short lessons by hand, then marks the answer.
import { h, logo, s } from "./dom.js";

// Each line: [text, kind, mark, side note]. kind: title | step | answer | code | aside.
// mark: underline | circle | tick. Lessons follow Mentora's subjects.
const LESSONS = [
  {
    subject: "Maths",
    lines: [
      ["Solve for x", "title", "underline"],
      ["2x + 6 = 14", "step"],
      ["2x = 14 − 6 = 8", "step", null, "take 6 from both sides"],
      ["x = 8 ÷ 2", "step"],
      ["x = 4", "answer", "circle"],
      ["check: 2(4) + 6 = 14", "aside", "tick"],
    ],
    note: "Do the same thing to both sides, then check your answer.",
  },
  {
    subject: "Python",
    lines: [
      ["Loops in Python", "title", "underline"],
      ["for i in range(3):", "code"],
      ["    print(i)", "code"],
      ["prints  0  1  2", "answer", "circle", "stops before 3!"],
      ["range(1, 4) gives 1 2 3", "aside", "tick"],
    ],
    note: "Your turn: what does range(2, 8, 2) give?",
  },
  {
    subject: "Data structures",
    lines: [
      ["Stack: last in, first out", "title", "underline"],
      ["push 1, push 2, push 3", "step"],
      ["[ 1 | 2 | 3 ]  top = 3", "code", null, "like a pile of plates"],
      ["pop() gives 3", "answer", "circle"],
      ["undo in an editor uses a stack", "aside", "tick"],
    ],
    note: "Practice rounds come back to the topics you miss.",
  },
  {
    subject: "DBMS",
    lines: [
      ["Top students in SQL", "title", "underline"],
      ["SELECT name, score", "code"],
      ["FROM results", "code"],
      ["WHERE score >= 80", "code", null, "filter first"],
      ["ORDER BY score DESC;", "answer", "circle", "then sort"],
    ],
    note: "Stuck? Ask the AI tutor or your teacher, any time.",
  },
];

const TYPE_MS = 42;
const LINE_PAUSE_MS = 380;
const MARK_MS = 650;
const HOLD_MS = 4200;

function markSvg(kind) {
  const paths = {
    underline: "M2 8 C 30 3, 60 11, 98 5",
    circle: "M56 4 C 84 4, 98 22, 96 52 C 94 84, 70 97, 46 96 C 16 95, 2 76, 4 48 C 6 20, 26 5, 52 4",
    tick: "M10 52 L 38 82 L 92 14",
  };
  const view = kind === "underline" ? "0 0 100 12" : "0 0 100 100";
  return s("svg", { class: `wb-mark wb-mark-${kind}`, viewBox: view, preserveAspectRatio: "none", "aria-hidden": "true" },
    s("path", { d: paths[kind] }));
}

function arrowSvg() {
  return s("svg", { class: "wb-arrow", viewBox: "0 0 40 20", "aria-hidden": "true" },
    s("path", { d: "M38 10 C 26 4, 14 14, 3 10 M3 10 L 10 4 M3 10 L 10 16" }));
}

/** A self-running whiteboard element. It stops by itself once it leaves the page. */
export function whiteboard() {
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const subject = h("span", { class: "wb-subject" });
  const dots = h("span", { class: "wb-dots" });
  const surface = h("div", { class: "wb-surface" });
  const note = h("p", { class: "wb-note" });
  const board = h("section", { class: "wb", "aria-label": "The Mentora tutor solving a short problem on a whiteboard" },
    h("div", { class: "wb-bar" },
      h("span", { class: "wb-live" }, h("i"), "Live lesson"),
      subject,
      dots),
    surface,
    h("div", { class: "wb-tutor" },
      h("span", { class: "wb-avatar" }, logo()),
      h("div", { class: "wb-bubble" }, h("b", null, "Mentora tutor"), note)),
    h("div", { class: "wb-tray", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("span")));

  let lesson = 0;
  let run = 0; // bumps on every lesson change, so old timers stop
  let gone = 0;

  const wait = (ms, id) => new Promise((resolve, reject) => {
    setTimeout(() => {
      // render() moves the board between paints; it is only really gone if it stays out
      gone = board.isConnected ? 0 : gone + 1;
      if (id !== run || gone > 1) reject(new Error("stopped"));
      else resolve();
    }, ms);
  });

  function setDots() {
    dots.replaceChildren(...LESSONS.map((l, i) => h("button", {
      type: "button", class: i === lesson ? "on" : "", "aria-label": `Show the ${l.subject} lesson`,
      onClick: () => show(i),
    })));
  }

  function lineEl([, kind, mark, side]) {
    const text = h("span", { class: "wb-text" });
    const row = h("div", { class: `wb-line wb-${kind}` }, text);
    if (mark) text.append(markSvg(mark));
    if (side) row.append(h("span", { class: "wb-side" }, arrowSvg(), h("span", null, side)));
    return { row, text };
  }

  async function play(i, id) {
    const l = LESSONS[i];
    subject.textContent = l.subject;
    note.textContent = "";
    setDots();
    surface.classList.remove("erasing");
    surface.replaceChildren();
    for (const line of l.lines) {
      const { row, text } = lineEl(line);
      surface.append(row);
      const words = h("span", { class: "wb-chars" });
      text.prepend(words);
      if (reduced) {
        words.textContent = line[0];
      } else {
        const caret = h("span", { class: "wb-caret" });
        text.insertBefore(caret, words.nextSibling);
        for (const ch of line[0]) {
          words.textContent += ch;
          await wait(ch === " " ? TYPE_MS / 2 : TYPE_MS, id);
        }
        caret.remove();
      }
      if (line[2] || line[3]) {
        row.classList.add("drawn");
        if (!reduced) await wait(MARK_MS, id);
      }
      if (!reduced) await wait(LINE_PAUSE_MS, id);
    }
    note.textContent = l.note;
    await wait(reduced ? 9000 : HOLD_MS, id);
    surface.classList.add("erasing");
    await wait(reduced ? 0 : 600, id);
    lesson = (i + 1) % LESSONS.length;
    play(lesson, id).catch(() => undefined);
  }

  function show(i) {
    lesson = i;
    run += 1;
    gone = 0;
    play(i, run).catch(() => undefined);
  }

  show(0);
  return board;
}
