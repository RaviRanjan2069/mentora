import { Fragment } from "react";
import Icon from "../icons";
import { useCopy } from "./ui";

const CITE = /\[([a-z0-9]+(?:-[a-z0-9]+)*-p\d{3})\]/g;

/** Plain text with citation tags like [syn101-week3-loops-p002] turned into links to the passage. */
function Cited({ text }: { text: string }) {
  const out: (string | JSX.Element)[] = [];
  let last = 0;
  for (const m of text.matchAll(CITE)) {
    out.push(text.slice(last, m.index));
    out.push(
      <a key={m.index} className="cite" href={`#/resources?id=${m[1]}`} title={`Source: ${m[1]}`}>source</a>,
    );
    last = (m.index ?? 0) + m[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}

/** `inline code` becomes <code>; the rest goes through Cited. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/`([^`\n]+)`/);
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1
        ? <code key={i} className="inline-code">{p}</code>
        : <Cited key={i} text={p} />))}
    </>
  );
}

/** Tutor text: ``` fences become code blocks, citations become source links. */
export default function RichText({ text }: { text: string }) {
  const copy = useCopy();
  const parts = text.split(/```[a-zA-Z0-9]*\n?/);
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1
        ? (
          <div key={i} className="code-block">
            <pre>{p.replace(/\n$/, "")}</pre>
            <button type="button" className="btn small copy" onClick={() => copy(p.replace(/\n$/, ""))}
                    aria-label="Copy code">
              <Icon name="copy" />
            </button>
          </div>
        )
        : <Fragment key={i}><Inline text={p.trim()} /></Fragment>))}
    </>
  );
}
