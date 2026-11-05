"use client";

import { useEffect, useState } from "react";
import { ApplicationTracker } from "../AgentExtras";
import { CompanyMark, DataMode, Icon, Job, JobDetail, JobMeta, LOCAL_API, MatchTag } from "../../lib/shared";

type Props = {
  dataMode: DataMode; job: Job; others: Job[]; saved: boolean;
  onBack: () => void; onSelect: (id: string) => void; onToggleSave: () => void; onTailor: () => void;
};
type Loaded = { id: string; detail: JobDetail | null; error: string };

export default function JobDetailPage({ dataMode, job, others, saved, onBack, onSelect, onToggleSave, onTailor }: Props) {
  const local = dataMode === "local";
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  useEffect(() => {
    if (!local || !/^[0-9]+$/.test(job.id)) return;
    const controller = new AbortController();
    fetch(`${LOCAL_API}/api/jobs/${job.id}/detail`, { signal: controller.signal, cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error(); return r.json() as Promise<JobDetail>; })
      .then(detail => setLoaded({ id: job.id, detail, error: "" }))
      .catch(() => { if (!controller.signal.aborted) setLoaded({ id: job.id, detail: null, error: "Could not read the saved job description. Is the local API running?" }); });
    return () => controller.abort();
  }, [local, job.id]);
  const current = loaded?.id === job.id ? loaded : null;

  return <>
    <button className="secondary-button product-back" onClick={onBack}><Icon name="chevron" size={15}/> Back to jobs</button>
    <div className="detail-layout">
      <section className="panel detail-primary">
        <div className="detail-header"><CompanyMark job={job} size="large"/><div className="detail-header-main">
          <div className="job-row-company">{job.company} · {job.id}</div><h2>{job.title}</h2><JobMeta job={job} size={15}/>
        </div></div>
        <div className="detail-badges"><MatchTag status={job.match}/>{job.priority && <span className="skill-pill">{job.priority}</span>}</div>
        <div className="detail-divider"/>
        <h3>Screening notes</h3>
        <p className="detail-summary">{job.summary}</p>
        <div className="review-notes">{job.flags.map(flag => <div key={flag}><Icon name="info" size={15}/>{flag}</div>)}</div>
        {job.skills.length > 0 && <><h3>Your matching skills</h3><div className="skills-row">{job.skills.map(s => <span className="skill-pill" key={s}>{s}</span>)}</div></>}
        {local && <>
          <h3>Job description</h3>
          {!current ? <p className="stage4-muted">Loading saved job description…</p>
            : current.error ? <p className="stage4-warning">{current.error}</p>
            : current.detail?.hasJd ? <pre className="stage4-document">{current.detail.jdText}</pre>
            : <p className="stage4-muted">No saved job description yet. Use Find jobs → Extract descriptions.</p>}
        </>}
        {!local && <><h3>Example requirements</h3><ul className="bullet-list">{job.requirements.map(r => <li key={r}>{r}</li>)}</ul></>}
      </section>
      <aside className="detail-aside">
        <section className="panel detail-score">
          <div className="tiny-label">MATCH SCORE</div>
          <div className="large-score">{job.score}<span>/ 100</span></div>
          <div className="score-track"><div style={{ width: `${job.score}%` }}/></div>
          <p>Rule-based score, not a hiring prediction.</p>
          <button className="primary-button" onClick={onTailor}><Icon name="sparkles" size={17}/> Tailor resume for this job</button>
          <button className={`secondary-button full-button ${saved ? "button-saved" : ""}`} onClick={onToggleSave}><Icon name="bookmark" size={17}/>{saved ? "Remove from shortlist" : "Add to shortlist"}</button>
        </section>
        <ApplicationTracker jobId={job.id} enabled={local}/>
        <section className="panel detail-switch"><div className="panel-title">Other positions</div>
          {others.slice(0, 3).map(o => <button key={o.id} onClick={() => onSelect(o.id)}><span>{o.title}<small>{o.company}</small></span><Icon name="chevron" size={17}/></button>)}
        </section>
      </aside>
    </div>
  </>;
}
