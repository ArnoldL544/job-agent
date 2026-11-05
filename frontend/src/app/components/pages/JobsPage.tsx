"use client";

import { useMemo, useState } from "react";
import { DataMode, Icon, Job, JobRow } from "../../lib/shared";

type Props = { dataMode: DataMode; jobs: Job[]; shortlisted: string[]; applied: string[]; onOpenJob: (id: string) => void; onToggleSave: (id: string) => void };

export default function JobsPage({ dataMode, jobs, shortlisted, applied, onOpenJob, onToggleSave }: Props) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("All positions");
  const [sort, setSort] = useState<"score" | "deadline">("score");
  const filtered = useMemo(() => jobs.filter(job => {
    const needle = `${job.company} ${job.title} ${job.skills.join(" ")} ${job.location} ${job.pay ?? ""}`.toLowerCase();
    const days = job.deadlineDays;
    const keep = filter === "All positions" ? true
      : filter === "Shortlisted" ? shortlisted.includes(job.id)
      : filter === "Closing within 7 days" ? days !== null && days !== undefined && days >= 0 && days <= 7
      : filter === "Hide closed" ? !(days !== null && days !== undefined && days < 0)
      : filter === "Not applied yet" ? !applied.includes(job.id)
      : filter === "Applied" ? applied.includes(job.id)
      : job.match === filter;
    return needle.includes(search.trim().toLowerCase()) && keep;
  }).sort((a, b) => {
    if (sort === "deadline") {
      // Open jobs by soonest deadline, then unknown deadlines, then closed jobs.
      const rank = (j: Job) => j.deadlineDays === null || j.deadlineDays === undefined ? 1e6 : j.deadlineDays < 0 ? 2e6 - j.deadlineDays : j.deadlineDays;
      return rank(a) - rank(b) || b.score - a.score;
    }
    return b.score - a.score;
  }), [search, filter, sort, shortlisted, applied, jobs]);
  return <section className="panel opportunities-panel">
    <div className="toolbar">
      <label className="search-field"><Icon name="search" size={18}/><input placeholder="Search roles, companies, skills..." value={search} onChange={e => setSearch(e.target.value)}/></label>
      <label className="select-field"><Icon name="filter" size={17}/><select value={filter} onChange={e => setFilter(e.target.value)} aria-label="Filter positions"><option>All positions</option><option>High Match</option><option>Verify Eligibility</option><option>Conflict</option><option>Review</option><option>Closing within 7 days</option><option>Hide closed</option><option>Not applied yet</option><option>Applied</option><option>Shortlisted</option></select></label>
      <label className="select-field"><select value={sort} onChange={e => setSort(e.target.value as "score" | "deadline")} aria-label="Sort positions"><option value="score">Best match first</option><option value="deadline">Deadline soonest</option></select></label>
      <span className="neutral-chip">{filtered.length} of {jobs.length}</span>
    </div>
    <div className="job-list detailed-list">{filtered.length
      ? filtered.map(job => <JobRow key={job.id} job={job} saved={shortlisted.includes(job.id)} applied={applied.includes(job.id)} onOpen={() => onOpenJob(job.id)} onSave={() => onToggleSave(job.id)}/>)
      : <div className="empty-state"><Icon name="search" size={29}/><strong>No matching positions</strong><p>Try another search or filter.</p><button className="secondary-button" onClick={() => { setSearch(""); setFilter("All positions"); }}>Clear filters</button></div>}
    </div>
    <div className="panel-footer">{dataMode === "local" ? "Scores come from your local screening rules. Always verify eligibility and work authorization in the job posting." : "Sample scores are illustrative only."}</div>
  </section>;
}
