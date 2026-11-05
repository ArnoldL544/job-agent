"use client";

import { useMemo, useState } from "react";
import { DataMode, Icon, Job, JobRow } from "../../lib/shared";

type Props = { dataMode: DataMode; jobs: Job[]; shortlisted: string[]; onOpenJob: (id: string) => void; onToggleSave: (id: string) => void };

export default function JobsPage({ dataMode, jobs, shortlisted, onOpenJob, onToggleSave }: Props) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("All positions");
  const filtered = useMemo(() => jobs.filter(job => {
    const needle = `${job.company} ${job.title} ${job.skills.join(" ")} ${job.location}`.toLowerCase();
    return needle.includes(search.trim().toLowerCase())
      && (filter === "All positions" || (filter === "Shortlisted" ? shortlisted.includes(job.id) : job.match === filter));
  }).sort((a, b) => b.score - a.score), [search, filter, shortlisted, jobs]);
  return <section className="panel opportunities-panel">
    <div className="toolbar">
      <label className="search-field"><Icon name="search" size={18}/><input placeholder="Search roles, companies, skills..." value={search} onChange={e => setSearch(e.target.value)}/></label>
      <label className="select-field"><Icon name="filter" size={17}/><select value={filter} onChange={e => setFilter(e.target.value)} aria-label="Filter positions"><option>All positions</option><option>High Match</option><option>Review</option><option>Verify Eligibility</option><option>Shortlisted</option></select></label>
      <span className="neutral-chip">{filtered.length} of {jobs.length}</span>
    </div>
    <div className="job-list detailed-list">{filtered.length
      ? filtered.map(job => <JobRow key={job.id} job={job} saved={shortlisted.includes(job.id)} onOpen={() => onOpenJob(job.id)} onSave={() => onToggleSave(job.id)}/>)
      : <div className="empty-state"><Icon name="search" size={29}/><strong>No matching positions</strong><p>Try another search or filter.</p><button className="secondary-button" onClick={() => { setSearch(""); setFilter("All positions"); }}>Clear filters</button></div>}
    </div>
    <div className="panel-footer">{dataMode === "local" ? "Scores come from your local screening rules. Always verify eligibility and work authorization in the job posting." : "Sample scores are illustrative only."}</div>
  </section>;
}
