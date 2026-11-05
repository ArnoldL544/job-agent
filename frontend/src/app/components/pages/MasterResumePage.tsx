"use client";

import { useEffect, useState } from "react";
import { ACTION_HEADERS, DataMode, Icon, LOCAL_API } from "../../lib/shared";

type Question = { question: string; jobs: string[] };
type OpenQuestion = { bulletId: string; bullet: string; section: string; questions: Question[] };
type Entry = { title: string; role: string; dates: string; kind: string; bullets: string[] };
type Master = {
  found: boolean; filename?: string; updatedAt?: string; error?: string;
  header?: string[]; education?: string[]; skills?: string[]; entries?: Entry[]; warnings?: string[];
  openQuestions?: OpenQuestion[]; resolvedQuestions?: number; canOpen?: boolean;
};
type Loaded = { key: number; master: Master | null; error: string };

const KIND_LABEL: Record<string, string> = { internship: "Internship", projects: "Project", research: "Research", leadership: "Leadership", awards: "Award" };

export default function MasterResumePage({ dataMode, onOpenProfileForm }: { dataMode: DataMode; onOpenProfileForm: () => void }) {
  const [reload, setReload] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [notice, setNotice] = useState("");
  const local = dataMode === "local";
  useEffect(() => {
    if (!local) return;
    const controller = new AbortController();
    fetch(`${LOCAL_API}/api/master`, { signal: controller.signal, cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error(); return r.json() as Promise<Master>; })
      .then(master => setLoaded({ key: reload, master, error: "" }))
      .catch(() => { if (!controller.signal.aborted) setLoaded({ key: reload, master: null, error: "Cannot reach the local API." }); });
    return () => controller.abort();
  }, [local, reload]);

  if (!local) return <section className="panel stage5-controls">
    <div className="panel-title">Your master resume lives on your computer</div>
    <p className="stage4-muted">Start the app with start.bat to see it here.</p>
  </section>;

  async function openInWord() {
    setNotice("");
    try {
      const res = await fetch(`${LOCAL_API}/api/master/open`, { method: "POST", headers: ACTION_HEADERS, body: "{}" });
      const data = await res.json() as { error?: string };
      setNotice(res.ok ? "Opened in Word. Save your changes there, then click Reload." : data.error || "Could not open the file.");
    } catch { setNotice("Could not reach the local API."); }
  }

  const master = loaded?.master;
  const stale = loaded && loaded.key !== reload;
  if (!loaded) return <p className="stage4-muted">Loading your master resume…</p>;
  if (loaded.error || !master) return <p className="stage4-warning">{loaded.error}</p>;
  if (!master.found) return <section className="panel stage5-controls">
    <div className="panel-title">No master resume found</div>
    <p className="stage4-muted">Put your full resume in the project folder as <strong>Resume_&lt;Your Name&gt;.docx</strong>, then click Reload. Every tailored draft is built from that one file.</p>
    <button className="secondary-button" onClick={() => setReload(v => v + 1)}>Reload</button>
  </section>;

  const questions = master.openQuestions ?? [];
  return <div className="master">
    <section className="panel master-file">
      <div>
        <div className="panel-title">{master.filename}</div>
        <div className="panel-subtitle">{master.updatedAt ? `Last saved ${new Date(master.updatedAt).toLocaleString()}` : ""} · every tailored draft is built from this file</div>
      </div>
      <div className="product-quick-buttons">
        {master.canOpen && <button className="primary-button" onClick={openInWord}><Icon name="file" size={16}/> Open in Word</button>}
        <button className="secondary-button" onClick={() => { setNotice(""); setReload(v => v + 1); }}>{stale ? "Reloading…" : "Reload"}</button>
      </div>
      {notice && <p className="stage4-muted master-notice">{notice}</p>}
      {master.error && <p className="stage4-warning master-notice">{master.error}</p>}
    </section>

    <section className="panel master-section">
      <div className="panel-title">Questions from your drafts</div>
      <p className="stage4-muted">Each tailored draft asks for facts that would make a bullet stronger. Add true answers to the bullet in Word; once that bullet changes, its questions close here.</p>
      {questions.length ? <ul className="question-list">{questions.map(q => <li key={q.bulletId}>
        <span className="master-q-section">{q.section}</span>
        <span>{q.bullet}</span>
        {q.questions.map(x => <strong key={x.question}>{x.question}{x.jobs.length > 0 && <small className="master-q-jobs"> · asked for {x.jobs.join(", ")}</small>}</strong>)}
      </li>)}</ul> : <p className="stage4-muted">No open questions. Generate a tailored draft to get suggestions.</p>}
      {(master.resolvedQuestions ?? 0) > 0 && <p className="stage4-muted">{master.resolvedQuestions} earlier question{master.resolvedQuestions === 1 ? "" : "s"} closed because you edited those bullets.</p>}
    </section>

    <section className="panel master-section">
      <div className="panel-title">What the editor reads</div>
      <p className="stage4-muted">Exactly how the tailoring step sees your resume. If a section or bullet is missing here, check its formatting in Word.</p>
      {(master.warnings ?? []).map(w => <p className="stage4-warning" key={w}>{w}</p>)}
      <div className="master-entries">{(master.entries ?? []).map(e => <div className="master-entry" key={`${e.title}-${e.role}`}>
        <div className="master-entry-head"><strong>{e.title}</strong>{KIND_LABEL[e.kind] && <span className="neutral-chip">{KIND_LABEL[e.kind]}</span>}</div>
        <div className="stage4-muted">{[e.role, e.dates].filter(Boolean).join(" · ")}</div>
        <ul>{e.bullets.map(b => <li key={b}>{b}</li>)}</ul>
      </div>)}</div>
      <div className="master-columns">
        <div><h3>Education</h3>{(master.education ?? []).map(t => <p className="stage4-muted" key={t}>{t}</p>)}</div>
        <div><h3>Skills</h3>{(master.skills ?? []).map(t => <p className="stage4-muted" key={t}>{t}</p>)}</div>
      </div>
    </section>

    <p className="stage4-muted master-legacy">The older My Profile form is still available for the &ldquo;Write from My Profile&rdquo; option. <button className="quiet-link" onClick={onOpenProfileForm}>Open My Profile form <Icon name="arrow" size={14}/></button></p>
  </div>;
}
