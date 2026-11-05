"use client";

import { AppliedCheck, AppliedChip, DataMode, deadlineLabel, Icon, Job, JobRow, MatchTag, ResumeRecord } from "../../lib/shared";

type Props = {
  dataMode: DataMode; jobs: Job[]; resumes: ResumeRecord[]; shortlisted: string[]; applied: string[];
  onFindJobs: () => void; onJobs: () => void; onOpenJob: (id: string) => void;
  onToggleSave: (id: string) => void; onToggleApplied: (id: string) => void; onOpenDrafts: (jobId: string) => void;
};

export default function HomePage({ dataMode, jobs, resumes, shortlisted, applied, onFindJobs, onJobs, onOpenJob, onToggleSave, onToggleApplied, onOpenDrafts }: Props) {
  const local = dataMode === "local";
  const best = [...jobs].sort((a, b) => b.score - a.score).slice(0, 3);
  const highCount = jobs.filter(j => j.match === "High Match").length;
  const closing = jobs
    .filter(j => j.deadlineDays !== null && j.deadlineDays !== undefined && j.deadlineDays >= 0 && j.deadlineDays <= 7 && j.match !== "Conflict")
    // Applied jobs stay visible (checked, dimmed) but move to the bottom.
    .sort((a, b) => Number(applied.includes(a.id)) - Number(applied.includes(b.id))
      || (a.deadlineDays ?? 0) - (b.deadlineDays ?? 0) || b.score - a.score);
  // Latest draft per job, newest first.
  const latest: ResumeRecord[] = [];
  for (const r of [...resumes].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))) {
    if (!latest.some(x => x.jobId === r.jobId)) latest.push(r);
    if (latest.length === 3) break;
  }
  const metrics = [
    { label: local ? "Saved jobs" : "Sample jobs", value: jobs.length, icon: "briefcase" as const, tone: "mint-bg" },
    { label: "High matches", value: highCount, icon: "sparkles" as const, tone: "blue-bg" },
    { label: "Shortlisted", value: shortlisted.length, icon: "bookmark" as const, tone: "purple-bg" },
    { label: "Resume drafts", value: local ? resumes.length : 0, icon: "file" as const, tone: "orange-bg" },
  ];
  return <>
    <div className="metrics-grid">
      {metrics.map(m => <div className="metric-card" key={m.label}>
        <div className="metric-top"><span>{m.label}</span><span className={`metric-icon ${m.tone}`}><Icon name={m.icon} size={19}/></span></div>
        <div className="metric-number">{m.value}</div>
      </div>)}
    </div>
    <div className="content-grid">
      <section className="panel featured-panel">
        <div className="panel-header"><div><div className="panel-title">Top matches</div><div className="panel-subtitle">Highest screening scores</div></div><button className="quiet-link" onClick={onJobs}>All jobs <Icon name="arrow" size={15}/></button></div>
        <div className="job-list">{best.map(job => <JobRow key={job.id} job={job} saved={shortlisted.includes(job.id)} onOpen={() => onOpenJob(job.id)} onSave={() => onToggleSave(job.id)}
          applied={applied.includes(job.id)} onToggleApplied={local ? () => onToggleApplied(job.id) : undefined}/>)}</div>
      </section>
      <section className="panel snapshot-panel">
        <div className="panel-header"><div><div className="panel-title">Latest resume drafts</div><div className="panel-subtitle">Most recent draft per job</div></div></div>
        {latest.length ? <div className="home-drafts">{latest.map(r => <button key={r.id} className={`home-draft ${applied.includes(r.jobId) ? "is-applied" : ""}`} onClick={() => onOpenDrafts(r.jobId)}>
          <span><strong>{r.jobTitle}</strong><small>{r.company} · {new Date(r.updatedAt).toLocaleDateString()}</small></span><Icon name="chevron" size={16}/>
        </button>)}</div> : <p className="stage4-muted">{local ? "No drafts yet. Open a job and choose Tailor resume." : "Drafts appear here in the local app."}</p>}
      </section>
    </div>
    {local && <section className="panel closing-panel">
      <div className="panel-header"><div><div className="panel-title">Closing soon</div><div className="panel-subtitle">Open jobs with a deadline in the next 7 days</div></div></div>
      {closing.length ? <div className="closing-list">{closing.map(job => {
        const due = deadlineLabel(job);
        const done = applied.includes(job.id);
        return <div key={job.id} className={`closing-row ${done ? "is-applied" : ""}`}>
          <AppliedCheck checked={done} onToggle={() => onToggleApplied(job.id)} title={job.title}/>
          <button className="closing-item" onClick={() => onOpenJob(job.id)}>
            {done ? <AppliedChip/> : <span className={`deadline-chip deadline-${due?.tone || "soon"}`}>{due?.text}</span>}
            <span className="closing-title"><strong>{job.title}</strong><small>{job.company}</small></span>
            <span className="closing-score" title="Match score"><strong>{job.score}</strong>/100</span>
            <MatchTag status={job.match}/>
          </button>
        </div>;
      })}</div> : <p className="stage4-muted">Nothing closes in the next 7 days.</p>}
    </section>}
    <div className="product-quick-actions panel home-actions">
      <div className="product-quick-copy"><h2>Ready for your next opportunity?</h2><p>Check Gmail for new Handshake jobs, then review the best matches.</p></div>
      <div className="product-quick-buttons">
        <button className="primary-button" onClick={onFindJobs}><Icon name="mail" size={17}/> Find new jobs</button>
        <button className="secondary-button" onClick={onJobs}><Icon name="briefcase" size={17}/> Browse jobs</button>
      </div>
    </div>
  </>;
}
