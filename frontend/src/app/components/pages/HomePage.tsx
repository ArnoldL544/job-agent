"use client";

import { DeadlineOverview } from "../AgentExtras";
import { DataMode, Icon, Job, JobRow, ResumeRecord } from "../../lib/shared";

type Props = {
  dataMode: DataMode; jobs: Job[]; resumes: ResumeRecord[]; shortlisted: string[];
  onFindJobs: () => void; onJobs: () => void; onOpenJob: (id: string) => void;
  onToggleSave: (id: string) => void; onOpenDrafts: (jobId: string) => void;
};

export default function HomePage({ dataMode, jobs, resumes, shortlisted, onFindJobs, onJobs, onOpenJob, onToggleSave, onOpenDrafts }: Props) {
  const local = dataMode === "local";
  const best = [...jobs].sort((a, b) => b.score - a.score).slice(0, 3);
  const highCount = jobs.filter(j => j.match === "High Match").length;
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
    <div className="product-quick-actions panel home-actions">
      <div className="product-quick-copy"><h2>Ready for your next opportunity?</h2><p>Check Gmail for new Handshake jobs, then review the best matches.</p></div>
      <div className="product-quick-buttons">
        <button className="primary-button" onClick={onFindJobs}><Icon name="mail" size={17}/> Find new jobs</button>
        <button className="secondary-button" onClick={onJobs}><Icon name="briefcase" size={17}/> Browse jobs</button>
      </div>
    </div>
    <DeadlineOverview enabled={local}/>
    <div className="metrics-grid">
      {metrics.map(m => <div className="metric-card" key={m.label}>
        <div className="metric-top"><span>{m.label}</span><span className={`metric-icon ${m.tone}`}><Icon name={m.icon} size={19}/></span></div>
        <div className="metric-number">{m.value}</div>
      </div>)}
    </div>
    <div className="content-grid">
      <section className="panel featured-panel">
        <div className="panel-header"><div><div className="panel-title">Top matches</div><div className="panel-subtitle">Highest screening scores</div></div><button className="quiet-link" onClick={onJobs}>All jobs <Icon name="arrow" size={15}/></button></div>
        <div className="job-list">{best.map(job => <JobRow key={job.id} job={job} saved={shortlisted.includes(job.id)} onOpen={() => onOpenJob(job.id)} onSave={() => onToggleSave(job.id)}/>)}</div>
      </section>
      <section className="panel snapshot-panel">
        <div className="panel-header"><div><div className="panel-title">Latest resume drafts</div><div className="panel-subtitle">Most recent draft per job</div></div></div>
        {latest.length ? <div className="home-drafts">{latest.map(r => <button key={r.id} className="home-draft" onClick={() => onOpenDrafts(r.jobId)}>
          <span><strong>{r.jobTitle}</strong><small>{r.company} · {new Date(r.updatedAt).toLocaleDateString()}</small></span><Icon name="chevron" size={16}/>
        </button>)}</div> : <p className="stage4-muted">{local ? "No drafts yet. Open a job and choose Tailor resume." : "Drafts appear here in the local app."}</p>}
      </section>
    </div>
  </>;
}
