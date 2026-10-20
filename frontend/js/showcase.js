// The sign-in background: app windows that act out Mentora's services with example data.
// Plain DOM and CSS. One clock per window drives its scenes, and it stops by itself once it
// leaves the page.
import { h, icon, logo, s } from "./dom.js";

const SCENE_MS = 11000;
const TICK_MS = 30;

// --- scenes: each returns { el, run }; run uses the clock helpers in t --------------------------

function tutorScene(t) {
  const thread = h("div", { class: "sc-thread" },
    h("div", { class: "sc-msg bot" }, h("span", { class: "sc-av" }, logo()),
      h("div", { class: "sc-answer" }, h("p", null, "Hi! What would you like to learn today?"))));
  const input = h("span", { class: "sc-input-text" });
  const send = h("span", { class: "sc-send" }, icon("send"));
  const el = h("div", { class: "sc-scene sc-chat" }, thread,
    h("div", { class: "sc-input" }, input, h("span", { class: "sc-caret" }), send));
  async function run() {
    await t.sleep(500);
    await t.type(input, "Why does my while loop never stop?", 32);
    await t.click(send);
    input.textContent = "";
    thread.append(h("div", { class: "sc-msg user" }, "Why does my while loop never stop?"));
    const typing = h("div", { class: "sc-msg bot" }, h("span", { class: "sc-av" }, logo()),
      h("span", { class: "sc-typing" }, h("i"), h("i"), h("i")));
    thread.append(typing);
    await t.sleep(1100);
    const body = h("div", { class: "sc-answer" });
    typing.replaceWith(h("div", { class: "sc-msg bot" }, h("span", { class: "sc-av" }, logo()), body));
    const p1 = h("p");
    body.append(p1);
    await t.words(p1, "Your condition never becomes false, because i never changes inside the loop. Add one line:");
    body.append(h("pre", { class: "sc-code" }, "i = 0\nwhile i < 5:\n    print(i)\n    ", h("mark", null, "i += 1"), "   # the fix"));
    await t.sleep(700);
    const p2 = h("p");
    body.append(p2);
    await t.words(p2, "Now i grows each time, and the loop stops at 5.");
  }
  return { el, run };
}

function practiceScene(t) {
  const bars = [h("i"), h("i"), h("i")];
  const levelText = h("span");
  const level = h("span", { class: "sc-level" }, h("span", { class: "sc-bars" }, bars), levelText);
  const count = h("span", { class: "sc-count" });
  const card = h("div", { class: "sc-q" });
  const fill = h("span");
  const pct = h("b");
  const el = h("div", { class: "sc-scene sc-practice" },
    h("div", { class: "sc-qhead" }, h("span", { class: "sc-chip" }, "Python · Loops"), count, level),
    card,
    h("div", { class: "sc-mastery" }, h("span", null, "Loops mastery"), h("div", { class: "sc-track" }, fill), pct));
  const setLevel = (n, text, tone) => {
    bars.forEach((b, i) => b.classList.toggle("on", i < n));
    levelText.textContent = text;
    level.className = `sc-level ${tone || ""}`;
  };
  const setMastery = (v) => { fill.style.width = `${v}%`; pct.textContent = `${v}%`; };
  const ask = (n, q, options) => {
    count.textContent = `Question ${n} of 10`;
    const opts = options.map((o, i) => h("div", { class: "sc-opt" }, h("b", null, "ABCD"[i]), h("span", null, o)));
    card.replaceChildren(h("p", { class: "sc-question" }, q), ...opts);
    return opts;
  };
  const feedback = (tone, text) => card.append(h("div", { class: `sc-feedback ${tone}` }, icon(tone === "good" ? "check" : "alert"), h("span", null, text)));
  setLevel(2, "Medium");
  setMastery(40);
  ask(3, "What does range(2, 8, 2) give?", ["2, 4, 6, 8", "2, 4, 6", "2, 3, 4, 5, 6, 7", "4, 6, 8"]);
  async function run() {
    let opts = card.querySelectorAll(".sc-opt");
    await t.sleep(1000);
    await t.click(opts[0]);
    opts[0].classList.add("wrong");
    await t.sleep(300);
    opts[1].classList.add("right");
    feedback("bad", "Not quite: range stops before 8. This one comes back later in the round.");
    await t.sleep(700);
    setLevel(1, "Easier next", "down");
    await t.sleep(1900);
    opts = ask(4, "How many times does  for i in range(3)  run?", ["2 times", "3 times", "4 times", "Forever"]);
    await t.sleep(1000);
    await t.click(opts[1]);
    opts[1].classList.add("right");
    feedback("good", "Correct! The next question is a step harder.");
    setMastery(55);
    await t.sleep(600);
    setLevel(3, "Harder next", "up");
  }
  return { el, run };
}

function goalsScene(t) {
  const input = h("span", { class: "sc-input-text" });
  const button = h("span", { class: "sc-btn" }, "Create my plan");
  const weeks = h("ol", { class: "sc-weeks" });
  const fill = h("span");
  const pct = h("b", null, "0%");
  const note = h("div", { class: "sc-note" });
  const el = h("div", { class: "sc-scene sc-goals" },
    h("div", { class: "sc-goalrow" }, h("div", { class: "sc-input" }, icon("target"), input, h("span", { class: "sc-caret" })), button),
    h("div", { class: "sc-planhead" }, h("span", null, "Your 5-week plan"), h("div", { class: "sc-track" }, fill), pct),
    weeks, note);
  const plan = [
    ["Java basics: syntax and variables", "done"], ["Control flow and loops", "done"], ["Arrays and strings", "now"],
    ["Classes and objects", ""], ["Final project: a library app", ""],
  ];
  async function run() {
    await t.sleep(400);
    await t.type(input, "Learn Java", 60);
    await t.click(button);
    for (const [i, [topic, state]] of plan.entries()) {
      weeks.append(h("li", { class: `sc-week ${state}` },
        h("span", { class: "sc-wk" }, state === "done" ? icon("check") : `W${i + 1}`),
        h("span", null, topic), state === "now" ? h("em", null, "This week") : null));
      await t.sleep(260);
    }
    await t.sleep(300);
    fill.style.width = "40%";
    await t.count(pct, 40, "%");
    await t.sleep(900);
    note.append(icon("sparkle"), h("span", null, "Plan updated: 60% right on arrays, so this week adds an extra practice round."));
    note.classList.add("show");
  }
  return { el, run };
}

function progressScene(t) {
  const kpi = (label, to, unit) => {
    const b = h("b", null, "0");
    return [h("div", { class: "sc-kpi" }, h("small", null, label), h("span", null, b, unit)), () => t.count(b, to, "")];
  };
  const [k1, c1] = kpi("Accuracy", 77, "%");
  const [k2, c2] = kpi("Questions", 240, "");
  const [k3, c3] = kpi("Day streak", 6, "");
  const x = (i) => 30 + i * 52;
  const y = (v) => 150 - v * 1.3;
  const series = [
    ["Python", "var(--cat-1)", [42, 50, 48, 61, 66, 70, 78, 82]],
    ["Java", "var(--cat-2)", [30, 35, 44, 41, 50, 55, 60, 64]],
  ];
  const graph = s("svg", { class: "sc-graph", viewBox: "0 0 470 175", "aria-hidden": "true" },
    [0, 50, 100].map((v) => [s("line", { class: "sc-grid", x1: 30, x2: 400, y1: y(v), y2: y(v) }),
      s("text", { class: "sc-axis", x: 22, y: y(v) + 4, "text-anchor": "end" }, `${v}`)]),
    Array.from({ length: 8 }, (_, i) => s("text", { class: "sc-axis", x: x(i), y: 170, "text-anchor": "middle" }, `W${i + 1}`)),
    series.map(([name, colour, vals], j) => [
      s("path", { class: "sc-line", pathLength: "1", style: { stroke: colour, animationDelay: `${j * 0.5}s` },
        d: vals.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ") }),
      s("circle", { class: "sc-end", cx: x(7), cy: y(vals[7]), r: 4.5, style: { fill: colour, animationDelay: `${2.2 + j * 0.5}s` } }),
      s("text", { class: "sc-endlabel", x: x(7) + 9, y: y(vals[7]) + 4, style: { animationDelay: `${2.2 + j * 0.5}s` } }, `${name} ${vals[7]}%`),
    ]));
  const chip = h("div", { class: "sc-needs" }, icon("alert"), h("span", null, h("b", null, "Needs work: "), "Recursion, 40% right"));
  const el = h("div", { class: "sc-scene sc-progress" },
    h("div", { class: "sc-kpis" }, k1, k2, k3),
    h("div", { class: "sc-chart" },
      h("div", { class: "sc-legend" }, series.map(([name, colour]) => h("span", null, h("i", { style: { background: colour } }), name))),
      graph),
    chip);
  async function run() {
    await t.sleep(200);
    graph.classList.add("go");
    await Promise.all([c1(), c2(), c3()]);
    await t.sleep(2600);
    chip.classList.add("show");
  }
  return { el, run };
}

function teacherScene(t) {
  const results = [92, 85, 40, 76, 61, 95];
  const bars = results.map((v, i) => h("div", { class: `sc-bar ${i === 2 ? "low" : ""}`, style: { "--h": `${v}%` } },
    h("span", { class: "sc-bar-val" }, `${v}%`), h("i"), h("small", null, `Q${i + 1}`)));
  const students = h("ul", { class: "sc-students" });
  const insight = h("div", { class: "sc-note" });
  const el = h("div", { class: "sc-scene sc-teacher" },
    h("div", { class: "sc-classhead" },
      h("div", null, h("b", null, "Class CS-A · Quiz 2: Loops"), h("small", null, "18 of 20 students answered")),
      h("span", { class: "sc-chip" }, "Class code 4825 013 967")),
    h("div", { class: "sc-teachgrid" },
      h("div", null, h("small", { class: "sc-sub" }, "Right answers per question"), h("div", { class: "sc-qbars" }, bars)),
      h("div", null, h("small", { class: "sc-sub" }, "Students"), students)),
    insight);
  const roster = [["Aarav", 9], ["Diya", 8], ["Kabir", 7], ["Meera", 5]];
  async function run() {
    await t.sleep(300);
    el.classList.add("go");
    for (const [name, score] of roster) {
      await t.sleep(450);
      students.append(h("li", null, h("span", { class: "sc-initial" }, name[0]), h("span", null, name),
        h("span", { class: "sc-mini" }, h("i", { style: { width: `${score * 10}%` } })), h("b", null, `${score}/10`)));
    }
    await t.sleep(1200);
    insight.append(icon("bulb"), h("span", null, "Q3 (while loops) was the hardest: 40% right. Add a recap to the folder?"));
    insight.classList.add("show");
  }
  return { el, run };
}

const SCENES = [
  { title: "AI tutor", build: tutorScene },
  { title: "My Learning · adaptive practice", build: practiceScene },
  { title: "Goals & plans", build: goalsScene },
  { title: "Progress", build: progressScene },
  { title: "Teacher · class analysis", build: teacherScene },
];

// --- the background player --------------------------------------------------------------------------

/**
 * A self-running app window that loops through some scenes, for the sign-in page background.
 * Decorative (aria-hidden). Check `.stopped` before reusing it after it left the page.
 */
export function showcase(sceneIndexes = SCENES.map((_, i) => i)) {
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  let pos = 0;
  let elapsed = 0;
  let waiters = [];
  let gone = 0;

  const stage = h("div", { class: "sc-stage" });
  const title = h("span", { class: "sc-title" });
  const root = h("div", { class: "sc", "aria-hidden": "true" },
    h("div", { class: "sc-top" },
      h("span", { class: "sc-lights" }, h("i"), h("i"), h("i")),
      title,
      h("span", { class: "sc-badge" }, "Example")),
    stage);

  const sleep = (ms) => (reduced || ms <= 0 ? Promise.resolve() : new Promise((resolve) => waiters.push({ at: elapsed + ms, resolve })));
  let cursor = null;
  const t = {
    sleep,
    async type(el, text, ms) {
      if (reduced) { el.textContent = text; return; }
      for (const ch of text) {
        el.textContent += ch;
        await sleep(ms);
      }
    },
    async words(el, text) {
      if (reduced) { el.textContent = text; return; }
      for (const w of text.split(" ")) {
        el.textContent += (el.textContent ? " " : "") + w;
        await sleep(70);
      }
    },
    async count(el, to, unit) {
      for (let k = 1; k <= 24; k += 1) {
        el.textContent = `${Math.round(to * (1 - (1 - k / 24) ** 3))}${unit}`;
        if (!reduced) await sleep(50);
      }
      el.textContent = `${to}${unit}`;
    },
    async click(target) {
      if (!reduced && cursor && target.isConnected) {
        // the window may be scaled with CSS: measure in its own (unscaled) pixels
        const k = stage.getBoundingClientRect().width / stage.offsetWidth || 1;
        const r = target.getBoundingClientRect();
        const sr = stage.getBoundingClientRect();
        const x = (r.left - sr.left) / k + Math.min(r.width / k / 2, 60);
        const y = (r.top - sr.top) / k + (r.height / k) * 0.55;
        cursor.style.transform = `translate(${x}px, ${y}px)`;
        cursor.classList.add("shown");
        await sleep(750);
        cursor.classList.add("press");
        await sleep(220);
        cursor.classList.remove("press");
      }
      target.classList.add("pressed");
      await sleep(150);
      target.classList.remove("pressed");
    },
  };

  function go(p) {
    pos = p;
    elapsed = 0;
    waiters = [];
    const sc = SCENES[sceneIndexes[pos]];
    const { el, run } = sc.build(t);
    cursor = h("span", { class: "sc-cursor" },
      s("svg", { viewBox: "0 0 24 24" }, s("path", { d: "M5 3 L19 12 L12 13.5 L8.5 20 Z" })));
    stage.replaceChildren(el, cursor);
    title.textContent = sc.title;
    run().catch(() => undefined);
  }

  const timer = window.setInterval(() => {
    // render() moves the window between paints; it has only really left if it stays out
    gone = root.isConnected ? 0 : gone + 1;
    if (gone > 3) {
      window.clearInterval(timer);
      root.stopped = true;
      return;
    }
    if (reduced) return;
    elapsed += TICK_MS;
    const due = waiters.filter((w) => w.at <= elapsed);
    waiters = waiters.filter((w) => w.at > elapsed);
    due.forEach((w) => w.resolve());
    if (elapsed >= SCENE_MS) go((pos + 1) % sceneIndexes.length);
  }, TICK_MS);

  go(0);
  return root;
}
