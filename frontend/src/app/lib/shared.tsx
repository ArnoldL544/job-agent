import type { ReactNode } from "react";

export const LOCAL_API = "http://127.0.0.1:8765";
export const ACTION_HEADERS = { "Content-Type": "application/json", "X-Job-Agent-Action": "local-user-approved" };

export type Page = "overview" | "find" | "opportunities" | "high" | "shortlist" | "drafts" | "details" | "resumes" | "master" | "profile";
export type DataMode = "demo" | "local";
export type Match = "High Match" | "Review" | "Verify Eligibility" | "Conflict";

export type Job = {
  id: string; company: string; title: string; location: string; arrangement: string;
  score: number; match: Match; initials: string; color: string; skills: string[];
  summary: string; requirements: string[]; flags: string[];
  hasJd?: boolean; resumeCount?: number; priority?: string;
  // Parsed from the saved JD by the local API (phase 2); absent in sample data.
  pay?: string; schedule?: string; workAuth?: string; deadline?: string; deadlineDays?: number | null; reason?: string;
  url?: string;  // https link to the posting (Handshake), checked by the API
};
export type JobDetail = { jobId: string; hasJd: boolean; jdText: string; jdFilename: string | null; priority: string; screeningNotes: string[] };
export type DraftKind = "tailored" | "profile" | "uploaded";
export const DRAFT_KIND_LABEL: Record<DraftKind, string> = { tailored: "Tailored from master", profile: "From My Profile", uploaded: "Your edit" };
export type ResumeRecord ={ id: string; jobId: string; index: number; company: string; jobTitle: string; filename: string; updatedAt: string; hasTextPreview: boolean; kind?: DraftKind; downloadName?: string };
export type DraftSummary = {
  model: string; focus: string[]; questions: { question: string; bullet: string }[];
  changes: { section: string; kind: "rewritten" | "merged"; before: string[]; after: string }[];
  skills: string[]; bulletCount: number; pageCount: number | null;
};
export type ResumePreview = { jobId: string; filename: string; source: string; text: string; summary?: DraftSummary | null };
export type LocalTask = { id: string; action: string; status: "queued" | "running" | "succeeded" | "failed"; startedAt: number; endedAt: number | null; returnCode: number | null; logs: string[] };
export type StartTask = (payload: Record<string, unknown>) => void;

type IconName =
  | "grid" | "briefcase" | "file" | "layers" | "search" | "chevron" | "arrow" | "check"
  | "sparkles" | "filter" | "pin" | "bookmark" | "bolt" | "mail" | "menu" | "x" | "info" | "download" | "external";

const glyphs: Record<IconName, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  briefcase: <><rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18M10 12v2h4v-2"/></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/></>,
  layers: <><path d="m12 2 9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5"/></>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  chevron: <path d="m9 18 6-6-6-6"/>,
  arrow: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
  check: <path d="m4 12 5 5L20 6"/>,
  sparkles: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 17l.6 1.4L21 19l-1.4.6L19 21l-.6-1.4L17 19l1.4-.6L19 17z"/></>,
  filter: <><path d="M4 7h16M7 12h10M10 17h4"/></>,
  pin: <><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0z"/><circle cx="12" cy="10" r="2.5"/></>,
  bookmark: <path d="M5 4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v18l-7-4-7 4z"/>,
  bolt: <path d="m13 2-9 12h7l-1 8 10-12h-7l0-8z"/>,
  mail: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 7 9-7"/></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
  x: <path d="M5 5l14 14M19 5 5 19"/>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
  download: <><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></>,
  external: <><path d="M12 5h7v7M19 5l-9 9"/><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/></>,
};

// Opens the posting in a new tab; only https links from the API are rendered.
export function PostingLink({ job, label }: { job: Job; label?: string }) {
  if (!job.url || !job.url.startsWith("https://")) return null;
  return <a className={label ? "secondary-button full-button posting-link" : "icon-button posting-icon"} href={job.url} target="_blank" rel="noopener noreferrer"
    title="Open the job posting to apply" aria-label={`Open the ${job.title} posting`}>
    <Icon name="external" size={label ? 17 : 18}/>{label}
  </a>;
}

export function Icon({ name, size = 18, className = "" }: { name: IconName; size?: number; className?: string }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{glyphs[name]}</svg>;
}

// Tracker statuses that mean the user already applied.
const APPLIED_STATUSES = new Set(["Applied", "Interview", "Offer", "Rejected", "Withdrawn"]);
export function isApplied(status?: string) { return !!status && APPLIED_STATUSES.has(status); }

export function AppliedCheck({ checked, onToggle, title }: { checked: boolean; onToggle: () => void; title: string }) {
  return <label className="applied-check" title={checked ? "Applied: click to undo" : "Mark as applied"}>
    <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`${checked ? "Unmark" : "Mark"} ${title} as applied`}/>
    <span aria-hidden="true"><Icon name="check" size={13}/></span>
  </label>;
}

export function AppliedChip() {
  return <span className="applied-chip"><Icon name="check" size={12}/> Applied</span>;
}

const TAG_CLASS: Record<Match, string> = { "High Match": "tag-high", "Review": "tag-review", "Verify Eligibility": "tag-verify", "Conflict": "tag-conflict" };
export function MatchTag({ status }: { status: Match }) {
  return <span className={`match-tag ${TAG_CLASS[status]}`}><span className="tag-dot"/>{status}</span>;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function shortDate(iso: string) {
  const [, m, d] = iso.split("-").map(Number);
  return m && d ? `${MONTHS[m - 1]} ${d}` : iso;
}
// Days come from the API (computed on the server), so rendering never reads the clock.
export function deadlineLabel(job: Job): { text: string; tone: "" | "soon" | "closed" } | null {
  if (!job.deadline) return null;
  const days = job.deadlineDays;
  if (days === null || days === undefined) return { text: `Apply by ${shortDate(job.deadline)}`, tone: "" };
  if (days < 0) return { text: `Closed ${shortDate(job.deadline)}`, tone: "closed" };
  if (days === 0) return { text: "Due today", tone: "soon" };
  if (days <= 7) return { text: `Due in ${days} day${days > 1 ? "s" : ""} · ${shortDate(job.deadline)}`, tone: "soon" };
  return { text: `Apply by ${shortDate(job.deadline)}`, tone: "" };
}

export function CompanyMark({ job, size = "normal" }: { job: Job; size?: "normal" | "large" }) {
  return <span className={`company-mark logo-${job.color} ${size === "large" ? "company-mark-large" : ""}`}>{job.initials}</span>;
}

export function Score({ score }: { score: number }) {
  return <span className="score-label"><strong>{score}</strong><span>/100</span></span>;
}

// The local API fills location/arrangement with placeholders until JD parsing
// supplies real values; show nothing rather than repeating a placeholder.
const PLACEHOLDER = /not verified|verify job details/i;
export function JobMeta({ job, size = 13 }: { job: Job; size?: number }) {
  const parts = [job.location, job.arrangement, job.pay].filter((v): v is string => !!v && !PLACEHOLDER.test(v));
  if (!parts.length) return null;
  return <div className="job-row-meta"><Icon name="pin" size={size}/>{parts.join(" · ")}</div>;
}

export function JobFacts({ job, applied = false }: { job: Job; applied?: boolean }) {
  const due = deadlineLabel(job);
  if (!due && !job.workAuth && !job.reason && !applied) return null;
  return <div className="job-facts">
    {applied && <AppliedChip/>}
    {due && <span className={`deadline-chip ${due.tone ? `deadline-${due.tone}` : ""}`}>{due.text}</span>}
    {job.workAuth && <span className="job-auth">{job.workAuth}</span>}
    {job.reason && <span className="job-reason" title={job.reason}>{job.reason}</span>}
  </div>;
}

export function JobRow({ job, saved, onOpen, onSave, applied = false, onToggleApplied }: {
  job: Job; saved: boolean; onOpen: () => void; onSave: () => void; applied?: boolean; onToggleApplied?: () => void;
}) {
  return <div className={`job-row ${applied ? "is-applied" : ""}`}>
    {onToggleApplied && <AppliedCheck checked={applied} onToggle={onToggleApplied} title={job.title}/>}
    <CompanyMark job={job}/>
    <div className="job-row-main">
      <div className="job-row-company">{job.company}</div>
      <button className="job-title-link" onClick={onOpen}>{job.title}<Icon name="chevron" size={15}/></button>
      <JobMeta job={job}/>
      <JobFacts job={job} applied={applied}/>
    </div>
    <div className="job-row-score"><div className="tiny-label">MATCH SCORE</div><Score score={job.score}/></div>
    <div className="job-row-status"><MatchTag status={job.match}/></div>
    <PostingLink job={job}/>
    <button className={`icon-button save-button ${saved ? "saved" : ""}`} onClick={onSave} aria-label={`${saved ? "Remove" : "Add"} ${job.title} ${saved ? "from" : "to"} shortlist`} title={saved ? "Remove from shortlist" : "Add to shortlist"}><Icon name="bookmark" size={19}/></button>
  </div>;
}

const TASK_LABELS: Record<string, string> = { import: "Find new jobs", screen: "Rescore jobs", extract: "Extract descriptions", resume: "Resume draft" };

export function TaskMonitor({ task, error, onDone }: { task: LocalTask | null; error: string; onDone: () => void }) {
  if (!task && !error) return null;
  const finished = task && (task.status === "succeeded" || task.status === "failed");
  const last = task?.logs.filter(line => line.trim()).slice(-1)[0] ?? "";
  return <section className={`panel task-monitor task-${task?.status ?? "failed"}`}>
    {error && <p className="stage4-warning">{error}</p>}
    {task && <>
      <div className="task-line">
        <span className="task-dot"/>
        <strong>{TASK_LABELS[task.action] ?? task.action}</strong>
        <span className="stage4-muted">{task.status === "queued" ? "Starting…" : task.status === "running" ? "Running…" : task.status === "succeeded" ? "Done" : `Failed${task.returnCode !== null ? ` (exit ${task.returnCode})` : ""}`}</span>
        {finished && <button className="secondary-button task-refresh" onClick={onDone}>Refresh results</button>}
      </div>
      {last && <div className="task-last">{last}</div>}
      <details className="task-details"><summary>Full log</summary>
        <pre className="stage4-document">{task.logs.length ? task.logs.join("\n") : "Waiting for output…"}</pre>
      </details>
    </>}
  </section>;
}
