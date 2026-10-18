import { FormEvent, useMemo, useState } from "react";
import { api, Resource } from "../../api";
import Icon from "../../icons";
import { Skeleton } from "../../components/ui";
import { useLoad } from "../../session";

function queryParam(name: string): string | null {
  const q = window.location.hash.split("?")[1];
  return q ? new URLSearchParams(q).get(name) : null;
}

interface Hit { id: string; section: string | null; week: number | null; text: string }

export default function Resources() {
  const [rows] = useLoad<Resource[]>("/api/resources");
  const [open, setOpen] = useState<string | null>(queryParam("id"));
  const [concept] = useState<string | null>(queryParam("concept"));
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);

  const weeks = useMemo(() => {
    const by = new Map<string, Resource[]>();
    for (const r of rows ?? []) {
      if (concept && !r.concepts.includes(concept)) continue;
      const k = r.week ? `Week ${r.week}` : "General";
      by.set(k, [...(by.get(k) ?? []), r]);
    }
    return [...by.entries()];
  }, [rows, concept]);

  function toggle(id: string) {
    const next = open === id ? null : id;
    setOpen(next);
    if (next) void api.post(`/api/resources/${id}/view`).catch(() => undefined);
  }

  async function search(e: FormEvent) {
    e.preventDefault();
    if (q.trim().length < 2) return;
    const r = await api.get<{ hits: Hit[] }>(`/api/rag/search?q=${encodeURIComponent(q.trim())}`);
    setHits(r.hits);
  }

  if (!rows) return <Skeleton cards={3} />;
  return (
    <div className="stack">
      <section className="card">
        <form className="row" onSubmit={search}>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the course material, e.g. Does range(10) include 10?"
                 aria-label="Search course material" style={{ flex: 1 }} />
          <button className="btn primary" type="submit">Search</button>
        </form>
        {hits && (
          <ul className="list mt">
            {hits.length === 0 && <li className="empty">No passages found.</li>}
            {hits.map((h) => (
              <li key={h.id} className="list-row">
                <span className="ico"><Icon name="file" /></span>
                <div className="body">
                  <div className="title">{h.section} <span className="muted">· week {h.week ?? "–"}</span></div>
                  <div className="muted">{h.text}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {concept && <p className="muted">Showing material for one concept. <a href="#/resources">Show everything</a></p>}
      {weeks.map(([week, list]) => (
        <section className="card" key={week}>
          <h2>{week}</h2>
          <ul className="list">
            {list.map((r) => (
              <li key={r.id}>
                <div className="list-row">
                  <span className="ico orange"><Icon name="book" /></span>
                  <div className="body">
                    <div className="title">{r.section ?? r.id}</div>
                    <div className="muted">{r.source?.split("#")[0]}{r.concepts.length ? ` · ${r.concepts.join(", ")}` : ""}</div>
                  </div>
                  <button className="btn small" onClick={() => toggle(r.id)} aria-expanded={open === r.id}>
                    <Icon name="eye" /> {open === r.id ? "Close" : "Read"}
                  </button>
                </div>
                {open === r.id && <p style={{ whiteSpace: "pre-wrap", margin: "10px 0 0 46px" }}>{r.text}</p>}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
