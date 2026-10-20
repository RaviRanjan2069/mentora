// The sign-in whiteboard: the Mentora tutor sketches what Mentora does, one service per board.
import { h, logo, s } from "./dom.js";

// Each line: [text, kind, mark, side note]. kind: title | step | answer | code | aside | graph.
// mark: underline | circle | tick. One board per Mentora service; the numbers are examples.
const LESSONS = [
  {
    subject: "AI tutor",
    lines: [
      ["Ask the AI tutor anything", "title", "underline"],
      ["You: why does my loop never stop?", "step"],
      ["Tutor: i never changes...", "step", null, "explains why"],
      ["add  i += 1  inside the loop", "answer", "circle"],
      ["step by step, in any subject", "aside", "tick"],
    ],
    note: "Ask in your own words, any time. I explain step by step.",
  },
  {
    subject: "Goals & plans",
    lines: [
      ["Goal: learn Java", "title", "underline"],
      ["Week 1: syntax and variables", "aside", "tick"],
      ["Week 2: loops and arrays", "aside", "tick"],
      ["Week 3: classes and objects", "answer", "circle", "you are here"],
      ["Week 4: final project", "step"],
    ],
    note: "Set a goal and get a week-by-week plan that adapts to you.",
  },
  {
    subject: "Adaptive practice",
    lines: [
      ["Practice that adapts", "title", "underline"],
      ["Round of 10 questions", "step"],
      ["Loops  9/10", "step", null, "harder ones next"],
      ["Recursion  4/10", "answer", "circle", "comes back first"],
      ["practise where you need it most", "aside", "tick"],
    ],
    note: "Questions you miss come back until you get them right.",
  },
  {
    subject: "Progress analytics",
    lines: [
      ["Your progress", "title", "underline"],
      ["", "graph"],
      ["accuracy  58% to 77%", "answer", "circle", "+19 points"],
      ["every subject, from your real results", "aside", "tick"],
    ],
    note: "See what is improving and what needs another round.",
  },
  {
    subject: "Teachers",
    lines: [
      ["Learn with your teacher", "title", "underline"],
      ["join with a class code", "step", null, "teacher accepts"],
      ["folders: notes, files, quizzes", "step"],
      ["Quiz 2:  8/10", "answer", "circle", "teacher sees the analysis"],
      ["help when you are stuck", "aside", "tick"],
    ],
    note: "Teachers share material and quizzes, and follow your progress.",
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

/** A hand-drawn line graph: rising accuracy over six weeks. */
function graphSvg() {
  return s("svg", { class: "wb-chart", viewBox: "0 0 300 110", "aria-hidden": "true" },
    s("path", { class: "wb-axis", d: "M14 6 L 13 98 L 292 99" }),
    s("path", { class: "wb-plot", d: "M18 84 C 50 80, 62 70, 74 72 C 98 75, 112 56, 132 54 C 156 52, 168 60, 186 46 C 212 28, 236 34, 252 24 C 266 16, 276 14, 286 12" }),
    ...[[74, 72], [132, 54], [186, 46], [252, 24]].map(([cx, cy]) => s("circle", { class: "wb-point", cx, cy, r: 4 })));
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
    const row = h("div", { class: `wb-line wb-${kind}` }, kind === "graph" ? graphSvg() : text);
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
      if (line[1] === "graph") {
        row.classList.add("drawn");
        if (!reduced) await wait(1100, id);
        continue;
      }
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
