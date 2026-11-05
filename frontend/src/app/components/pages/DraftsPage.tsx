"use client";

import { useMemo, useState } from "react";
import { AppliedChip, CompanyMark, DataMode, DRAFT_KIND_LABEL, Icon, Job, LOCAL_API, MatchTag, PostingLink, ResumeRecord, Score } from "../../lib/shared";

type Props = {
  dataMode: DataMode; jobs: Job[]; resumes: ResumeRecord[]; resumesError: string; applied: string[];
  onOpenJob: (id: string) => void; onReview: (jobId: string, versionId: string) => void;
};
type Row = { draft: ResumeRecord; job?: Job; version: number; versions: number };

// Every draft as one row, newest first, each labelled with the job it was written for.
function buildRows(resumes: ResumeRecord[], jobs: Job[]): Row[] {
  const byJob = new Map<string, ResumeRecord[]>();
  for (const r of resumes) byJob.set(r.jobId, [...(byJob.get(r.jobId) ?? []), r]);
  const rows: Row[] = [];
  for (const list of byJob.values()) {
    const oldestFirst = [...list].sort((a, b) => a.updatedAt.localeCompare(b.updatedAt));
    oldestFirst.forEach((draft, i) => rows.push({ draft, job: jobs.find(j => j.id === draft.jobId), version: i + 1, versions: list.length }));
  }
  return rows.sort((a, b) => b.draft.updatedAt.localeCompare(a.draft.updatedAt));
}

function initials(company: string) {
  return company.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join("").toUpperCase() || "?";
}

export default function DraftsPage({ dataMode, jobs, resumes, resumesError, applied, onOpenJob, onReview }: Props) {
  const [search, setSearch] = useState("");
  const rows = useMemo(() => buildRows(resumes, jobs), [resumes, jobs]);
  const needle = search.trim().toLowerCase();
  const shown = rows.filter(r => `${r.draft.company} ${r.draft.jobTitle} ${r.draft.downloadName ?? ""}`.toLowerCase().includes(needle));

  if (dataMode !== "local") return <section className="panel stage5-controls">
    <div className="panel-title">Resume drafts need the local app</div>
    <p className="stage4-muted">Drafts are generated from the master resume on your computer. Start the app with start.bat, then open http://localhost:3000.</p>
  </section>;

  return <section className="panel opportunities-panel">
    <div className="toolbar">
      <label className="search-field"><Icon name="search" size={18}/><input placeholder="Search drafts by job or company..." value={search} onChange={e => setSearch(e.target.value)}/></label>
      <span className="neutral-chip">{shown.length} of {rows.length}</span>
    </div>
    {resumesError && <p className="stage4-warning draft-list-error">{resumesError}</p>}
    <div className="job-list detailed-list">{shown.length ? shown.map(({ draft, job, version, versions }) => {
      const done = applied.includes(draft.jobId);
      const latest = version === versions;
      return <div key={draft.id} className={`job-row draft-row ${done ? "is-applied" : ""}`}>
        {job ? <CompanyMark job={job}/> : <span className="company-mark logo-blue">{initials(draft.company)}</span>}
        <div className="job-row-main">
          <div className="job-row-company">Resume for · {draft.company}</div>
          {job
            ? <button className="job-title-link" onClick={() => onOpenJob(job.id)} title="Open this job">{draft.jobTitle}<Icon name="chevron" size={15}/></button>
            : <div className="job-title-link draft-title-static">{draft.jobTitle}</div>}
          <div className="job-row-meta"><Icon name="file" size={13}/>{draft.downloadName ?? draft.filename}</div>
          <div className="job-facts">
            {done && <AppliedChip/>}
            <span className={`draft-version ${latest ? "draft-latest" : ""}`}>{latest ? `Latest${versions > 1 ? ` · ${version} of ${versions}` : ""}` : `Version ${version} of ${versions}`}</span>
            <span className="job-auth">{DRAFT_KIND_LABEL[draft.kind ?? "profile"]}</span>
            <span className="job-auth">{new Date(draft.updatedAt).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span>
          </div>
        </div>
        {job && <div className="job-row-score"><div className="tiny-label">JOB MATCH</div><Score score={job.score}/></div>}
        {job && <div className="job-row-status"><MatchTag status={job.match}/></div>}
        {job && <PostingLink job={job}/>}
        <a className="icon-button" href={`${LOCAL_API}/api/resumes/${draft.jobId}/${draft.index}/download`} title={`Download ${draft.downloadName ?? "Word file"}`} aria-label={`Download the resume for ${draft.jobTitle}`}><Icon name="download" size={18}/></a>
        <button className="secondary-button draft-review" onClick={() => onReview(draft.jobId, draft.id)}>Review</button>
      </div>;
    }) : <div className="empty-state"><Icon name="file" size={29}/>
      <strong>{rows.length ? "No matching drafts" : "No resume drafts yet"}</strong>
      <p>{rows.length ? "Try another search." : "Open a job and choose Tailor resume to write your first draft."}</p>
    </div>}</div>
    <div className="panel-footer">Each draft is a Word file written for one job. Review opens it next to what changed, with save and download options.</div>
  </section>;
}
