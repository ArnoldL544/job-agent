"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import ProfileEditor from "./components/ProfileEditor";
import { ApplicationTracker, DeadlineOverview, ResumeUploader, SchedulePanel, TaskHistory } from "./components/AgentExtras";

type Page = "overview" | "opportunities" | "details" | "resumes" | "automation" | "profile";
type Match = "High Match" | "Review" | "Verify Eligibility";
type IconName =
  | "grid" | "briefcase" | "file" | "layers" | "workflow" | "search"
  | "chevron" | "arrow" | "check" | "shield" | "clock" | "sparkles"
  | "filter" | "pin" | "bookmark" | "external" | "bolt" | "code"
  | "mail" | "database" | "lock" | "menu" | "x" | "info" | "plus";

const glyphs: Record<IconName, ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  briefcase: <><rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 12h18M10 12v2h4v-2"/></>,
  file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/></>,
  layers: <><path d="m12 2 9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5"/></>,
  workflow: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><path d="M10 6h5a3 3 0 0 1 3 3v5M6 10v5a3 3 0 0 0 3 3h5"/></>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  chevron: <path d="m9 18 6-6-6-6"/>,
  arrow: <><path d="M5 12h14M13 6l6 6-6 6"/></>,
  check: <path d="m4 12 5 5L20 6"/>,
  shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  sparkles: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 17l.6 1.4L21 19l-1.4.6L19 21l-.6-1.4L17 19l1.4-.6L19 17z"/></>,
  filter: <><path d="M4 7h16M7 12h10M10 17h4"/></>,
  pin: <><path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0z"/><circle cx="12" cy="10" r="2.5"/></>,
  bookmark: <path d="M5 4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v18l-7-4-7 4z"/>,
  external: <><path d="M12 5h7v7M19 5l-9 9"/><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/></>,
  bolt: <path d="m13 2-9 12h7l-1 8 10-12h-7l0-8z"/>,
  code: <><path d="m8 8-4 4 4 4m8-8 4 4-4 4m-3-11-2 14"/></>,
  mail: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 7 9-7"/></>,
  database: <><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/></>,
  lock: <><rect x="5" y="10" width="14" height="12" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
  x: <path d="M5 5l14 14M19 5 5 19"/>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
};
function Icon({ name, size = 18, className = "" }: { name: IconName; size?: number; className?: string }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{glyphs[name]}</svg>;
}

type Job = {
  id: string;
  company: string;
  title: string;
  location: string;
  arrangement: string;
  score: number;
  match: Match;
  initials: string;
  color: string;
  skills: string[];
  summary: string;
  requirements: string[];
  flags: string[];
  hasJd?: boolean;
  resumeCount?: number;
  priority?: string;
};

type JobsApiResponse = { jobs: Job[]; count: number };
type JobDetail = { jobId: string; hasJd: boolean; jdText: string; jdFilename: string | null; priority: string; screeningNotes: string[] };
type ResumeRecord = { id: string; jobId: string; index: number; company: string; jobTitle: string; filename: string; updatedAt: string; hasTextPreview: boolean; kind?: "tailored" | "profile" };
type ResumeApiResponse = { count: number; resumes: ResumeRecord[] };
type ResumePreview = { jobId: string; filename: string; source: string; text: string };
type LocalTask = { id: string; action: string; status: "queued" | "running" | "succeeded" | "failed"; startedAt: number; endedAt: number | null; returnCode: number | null; logs: string[] };
const LOCAL_API = "http://127.0.0.1:8765";

// Deliberately fictional records: never use actual private Handshake/Gmail content as frontend fixtures.
const SAMPLE_JOBS: Job[] = [
  { id: "SAMPLE-001", company: "Northstar Labs", title: "Software Engineering Intern", location: "Remote · US", arrangement: "Remote", score: 93, match: "High Match", initials: "NL", color: "mint", skills: ["Python", "React", "REST APIs"], summary: "Example internship focused on building modern web applications and backend services.", requirements: ["Python or TypeScript experience", "Comfortable with APIs and Git", "Ability to work in a collaborative engineering team"], flags: ["Demo listing only", "Work eligibility must be verified for real positions"] },
  { id: "SAMPLE-002", company: "Meridian Data", title: "Machine Learning Intern", location: "New York · Hybrid", arrangement: "Hybrid", score: 89, match: "High Match", initials: "MD", color: "purple", skills: ["Python", "ML", "Pandas"], summary: "Example role involving machine learning experiments, evaluation and data pipelines.", requirements: ["Experience using Python for data analysis", "Familiarity with model evaluation", "Clear documentation practices"], flags: ["Demo listing only", "Sponsorship and student work authorization unknown"] },
  { id: "SAMPLE-003", company: "Atlas Systems", title: "Backend Developer Intern", location: "Boston · On-site", arrangement: "On-site", score: 84, match: "Review", initials: "AS", color: "blue", skills: ["Python", "SQL", "Docker"], summary: "Example backend internship focused on services, data storage and operational tooling.", requirements: ["Programming fundamentals", "Some SQL familiarity", "Comfortable reading unfamiliar code"], flags: ["Demo listing only", "Location constraints require review"] },
  { id: "SAMPLE-004", company: "Orbit Interactive", title: "AI Product Engineering Intern", location: "Remote · US", arrangement: "Remote", score: 78, match: "Verify Eligibility", initials: "OI", color: "orange", skills: ["LLMs", "JavaScript", "Product"], summary: "Example AI engineering position helping prototype LLM-powered product experiences.", requirements: ["Programming experience", "Interest in LLM-based applications", "Basic user interface development"], flags: ["Demo listing only", "Eligibility and location must be confirmed"] },
  { id: "SAMPLE-005", company: "Pioneer Analytics", title: "Data Analyst Intern", location: "Chicago · Hybrid", arrangement: "Hybrid", score: 86, match: "High Match", initials: "PA", color: "pink", skills: ["SQL", "Power BI", "Python"], summary: "Example analytics internship focused on dashboards, reporting and business insights.", requirements: ["Data cleaning and visualisation", "Python or SQL", "Ability to communicate findings"], flags: ["Demo listing only", "Check internship and work eligibility for real roles"] },
];

const MENU: { id: Page; label: string; icon: IconName }[] = [
  { id: "overview", label: "Home", icon: "grid" },
  { id: "opportunities", label: "Jobs", icon: "briefcase" },
  { id: "resumes", label: "Resumes", icon: "file" },
  { id: "profile", label: "My Profile", icon: "layers" },
];
const titles: Record<Page, { eyebrow: string; title: string; subtitle: string }> = {
  overview: { eyebrow: "WORKSPACE / HOME", title: "Your career workspace", subtitle: "Your applications, opportunities, and Agent activity at a glance." },
  opportunities: { eyebrow: "WORKSPACE / JOBS", title: "Your opportunities", subtitle: "Find and review all jobs discovered by your Agent." },
  details: { eyebrow: "WORKSPACE / JOBS / DETAILS", title: "Position details", subtitle: "Review the saved job description and screening notes." },
  resumes: { eyebrow: "WORKSPACE / RESUMES", title: "Your tailored resumes", subtitle: "Review every job-specific resume and download the Word document." },
  automation: { eyebrow: "WORKSPACE / HOME / AGENT", title: "Run Job Agent", subtitle: "Control job discovery, screening, and drafting with explicit approval." },
  profile: { eyebrow: "WORKSPACE / MY PROFILE", title: "My Profile", subtitle: "Your career background, organized once for future tailored applications." },
};

function MatchTag({ status }: { status: Match }) {
  return <span className={`match-tag ${status === "High Match" ? "tag-high" : status === "Review" ? "tag-review" : "tag-verify"}`}><span className="tag-dot"/>{status}</span>;
}
function CompanyMark({ job, size = "normal" }: { job: Job; size?: "normal" | "large" }) {
  return <span className={`company-mark logo-${job.color} ${size === "large" ? "company-mark-large" : ""}`}>{job.initials}</span>;
}
function Score({ score }: { score: number }) {
  return <span className="score-label"><strong>{score}</strong><span>/100</span></span>;
}
function JobRow({ job, saved, onOpen, onSave }: { job: Job; saved: boolean; onOpen: () => void; onSave: () => void }) {
  return <div className="job-row">
    <CompanyMark job={job}/>
    <div className="job-row-main">
      <div className="job-row-company">{job.company}</div>
      <button className="job-title-link" onClick={onOpen}>{job.title}<Icon name="chevron" size={15}/></button>
      <div className="job-row-meta"><span><Icon name="pin" size={13}/>{job.location}</span><span className="meta-separator">·</span><span>{job.arrangement}</span></div>
    </div>
    <div className="job-row-score"><div className="tiny-label">MATCH SCORE</div><Score score={job.score}/></div>
    <div className="job-row-status"><MatchTag status={job.match}/></div>
    <button className={`icon-button save-button ${saved ? "saved" : ""}`} onClick={onSave} aria-label={`${saved ? "Remove" : "Add"} ${job.title} ${saved ? "from" : "to"} shortlist`} title={saved ? "Remove from shortlist" : "Add to shortlist"}><Icon name="bookmark" size={19}/></button>
  </div>;
}

export default function Home() {
  const [jobs, setJobs] = useState<Job[]>(SAMPLE_JOBS);
  const [task, setTask] = useState<LocalTask | null>(null);
  const [taskError, setTaskError] = useState("");
  const [startingTask, setStartingTask] = useState(false);
  const [maxEmails, setMaxEmails] = useState(20);
  const [confirmRead, setConfirmRead] = useState(false);
  const [confirmPaid, setConfirmPaid] = useState(false);
  const [profileSource, setProfileSource] = useState<"json" | "legacy">("json");
  const [resumeEngine, setResumeEngine] = useState<"chunk" | "profile">("chunk");
  const [resumeRefresh, setResumeRefresh] = useState(0);
  const [allowRisk, setAllowRisk] = useState(false);
  const [forceDraft, setForceDraft] = useState(false);
  const [draftJobId, setDraftJobId] = useState("");
  const [dataMode, setDataMode] = useState<"demo" | "local">("demo");
  const [jobDetail, setJobDetail] = useState<JobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [resumes, setResumes] = useState<ResumeRecord[]>([]);
  const [resumesError, setResumesError] = useState("");
  const [activeResumeId, setActiveResumeId] = useState("");
  const [resumePreview, setResumePreview] = useState<ResumePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  useEffect(() => {
    // Production/Vercel deliberately never tries to access somebody's local service.
    if (!(["localhost", "127.0.0.1"].includes(window.location.hostname))) return;
    const controller = new AbortController();
    fetch("http://127.0.0.1:8765/api/jobs", { signal: controller.signal, cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error("Local API unavailable");
        return res.json() as Promise<JobsApiResponse>;
      })
      .then((data) => {
        if (controller.signal.aborted || !Array.isArray(data.jobs) || data.jobs.length === 0) return;
        setJobs(data.jobs);
        setDataMode("local");
        setSelectedId(data.jobs[0].id);
        setShortlisted([]);
      })
      .catch(() => { /* Keep the explicitly labelled demo when the API is offline. */ });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (dataMode !== "local") return;
    let mounted = true;
    const update = () => fetch(`${LOCAL_API}/api/tracker`, {cache:"no-store"})
      .then(res=>res.ok?res.json() as Promise<{applications:Record<string,{saved?:boolean}>}>:Promise.reject())
      .then(data=>{if(mounted)setShortlisted(Object.values(data.applications || {}).filter(x=>x.saved).map(x=>String((x as {jobId?:string}).jobId||"")));})
      .catch(()=>{});
    void update(); window.addEventListener("job-agent-tracker-updated",update);
    return ()=>{mounted=false;window.removeEventListener("job-agent-tracker-updated",update);};
  },[dataMode]);
  useEffect(() => {
    if (dataMode !== "local") return;
    const controller = new AbortController();
    fetch(`${LOCAL_API}/api/resumes`, { signal: controller.signal, cache: "no-store" })
      .then(response => { if (!response.ok) throw new Error("Cannot load local Word drafts"); return response.json() as Promise<ResumeApiResponse>; })
      .then(data => {
        if (controller.signal.aborted) return;
        setResumes(Array.isArray(data.resumes) ? data.resumes : []);
        setResumesError("");
      })
      .catch(() => { if (!controller.signal.aborted) setResumesError("Cannot load Word drafts. Restart api_local.py and refresh."); });
    return () => controller.abort();
  }, [dataMode, resumeRefresh]);
  useEffect(() => {
    if (dataMode !== "local") return;
    let active = true;
    const update = () => {
      fetch(`${LOCAL_API}/api/tasks/current`, { cache: "no-store" })
        .then(res => res.ok ? res.json() as Promise<{task: LocalTask | null}> : Promise.reject())
        .then(data => { if (active) setTask(data.task); })
        .catch(() => { /* Local server may have stopped. */ });
    };
    update();
    const timer = window.setInterval(update, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [dataMode]);
  const taskBusy = startingTask || task?.status === "queued" || task?.status === "running";
  async function startLocalTask(payload: Record<string, unknown>) {
    if (dataMode !== "local" || taskBusy) return;
    setStartingTask(true);
    setTaskError("");
    try {
      const res = await fetch(`${LOCAL_API}/api/tasks`, {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json", "X-Job-Agent-Action": "local-user-approved" },
        body: JSON.stringify(payload),
      });
      const result = await res.json() as LocalTask & { error?: string };
      if (!res.ok) throw new Error(result.error || "Cannot start local task");
      setTask(result);
      setConfirmPaid(false);
      setConfirmRead(false);
    } catch (err) {
      setTaskError(err instanceof Error ? err.message : "Failed to launch local task");
    } finally { setStartingTask(false); }
  }
  const stage5Monitor = dataMode === "local" && (task || taskError) ? <section className="panel stage5-monitor">
    <div className="panel-title">Local task monitor</div>
    {taskError && <p className="stage4-warning">{taskError}</p>}
    {task && <><div className="stage5-status">Task: {task.action} · {task.status}{task.returnCode !== null ? ` · Exit ${task.returnCode}` : ""}</div>
      <pre className="stage4-document stage5-logs">{task.logs.length ? task.logs.join("\n") : "Task queued. Waiting for output..."}</pre>
      {(task.status === "succeeded" || task.status === "failed") && <button className="secondary-button" onClick={() => window.location.reload()}>Reload local job & resume records</button>}
    </>}
  </section> : null;
  const [page, setPage] = useState<Page>("overview");
  const [selectedId, setSelectedId] = useState("SAMPLE-001");
  const [shortlisted, setShortlisted] = useState<string[]>(["SAMPLE-001", "SAMPLE-002"]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("All positions");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const activeResume = resumes.find(item => item.id === activeResumeId) ?? resumes[0] ?? null;
  useEffect(() => {
    if (dataMode !== "local" || page !== "details" || !/^[0-9]+$/.test(selectedId)) return;
    const controller = new AbortController();
    setJobDetail(null);
    setDetailError("");
    setDetailLoading(true);
    fetch(`${LOCAL_API}/api/jobs/${selectedId}/detail`, { signal: controller.signal, cache: "no-store" })
      .then(response => { if (!response.ok) throw new Error("Job description unavailable"); return response.json() as Promise<JobDetail>; })
      .then(data => { if (!controller.signal.aborted) setJobDetail(data); })
      .catch(() => { if (!controller.signal.aborted) setDetailError("Could not read the saved JD. Verify that the local API is running."); })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [dataMode, page, selectedId]);
  useEffect(() => {
    if (dataMode !== "local" || page !== "resumes" || !activeResume) return;
    const controller = new AbortController();
    setResumePreview(null);
    setPreviewError("");
    setPreviewLoading(true);
    fetch(`${LOCAL_API}/api/resumes/${activeResume.jobId}/${activeResume.index}/preview`, { signal: controller.signal, cache: "no-store" })
      .then(response => { if (!response.ok) throw new Error("Resume preview unavailable"); return response.json() as Promise<ResumePreview>; })
      .then(data => { if (!controller.signal.aborted) setResumePreview(data); })
      .catch(() => { if (!controller.signal.aborted) setPreviewError("Preview unavailable. You can still download the Word document."); })
      .finally(() => { if (!controller.signal.aborted) setPreviewLoading(false); });
    return () => controller.abort();
  }, [dataMode, page, activeResume?.id, activeResume?.jobId, activeResume?.index]);
  const selected = jobs.find(j => j.id === selectedId) ?? jobs[0];
  const best = [...jobs].sort((a,b) => b.score - a.score).slice(0, 3);
  const filtered = useMemo(() => jobs.filter(job => {
    const needle = `${job.company} ${job.title} ${job.skills.join(" ")} ${job.location}`.toLowerCase();
    return needle.includes(search.trim().toLowerCase()) && (filter === "All positions" || (filter === "Shortlisted" ? shortlisted.includes(job.id) : job.match === filter));
  }).sort((a,b) => b.score - a.score), [search, filter, shortlisted, jobs]);
  const highCount = jobs.filter(j => j.match === "High Match").length;
  function navigate(next: Page) { setPage(next); setSidebarOpen(false); }
  function openJob(id: string) { setSelectedId(id); navigate("details"); }
  function toggleSave(id: string) {
    const saved = !shortlisted.includes(id);
    setShortlisted(prev => saved ? [...prev.filter(x=>x!==id), id] : prev.filter(x=>x!==id));
    if (dataMode !== "local") return;
    fetch(`${LOCAL_API}/api/tracker`, {method:"POST", headers:{"Content-Type":"application/json","X-Job-Agent-Action":"local-user-approved"},body:JSON.stringify({jobId:id,saved})})
      .then(res=>{if(!res.ok)throw new Error("Save failed");window.dispatchEvent(new Event("job-agent-tracker-updated"));})
      .catch(()=>setShortlisted(prev=>saved?prev.filter(x=>x!==id):[...prev,id]));
  }
  const hero = titles[page];

  return <div className="app-shell">
    {sidebarOpen && <button className="mobile-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"/>}
    <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
      <div className="brand-lockup"><div className="brand-logo"><Icon name="sparkles" size={22}/></div><div><div className="brand-name">job<span>agent</span><span className="brand-period">.</span></div><div className="brand-subtitle">CAREER INTELLIGENCE</div></div><button className="mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Close menu"><Icon name="x" size={20}/></button></div>
      <div className="workspace-label"><span className="workspace-avatar">W</span><div><div className="workspace-title">My Workspace</div><div className="workspace-sub">Local workspace · Sign-in pending</div></div><Icon name="chevron" size={16} className="workspace-chevron"/></div>
      <div className="nav-caption">WORKSPACE</div>
      <nav className="sidebar-nav" aria-label="Main navigation">{MENU.map(item => <button key={item.id} className={`nav-link ${(page === item.id || (page === "details" && item.id === "opportunities") || (page === "automation" && item.id === "overview")) ? "nav-active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{item.label}</span>{(page === item.id || (page === "details" && item.id === "opportunities") || (page === "automation" && item.id === "overview")) && <span className="nav-active-pin"/>}</button>)}</nav>
      <div className="sidebar-grow"/>
      <div className="sidebar-note"><div className="sidebar-note-top"><Icon name="shield" size={17}/><span>Private by design</span></div><p>Local-only read access to private drafts. Never forward this API port or deploy it publicly.</p></div>
      <div className="sidebar-bottom"><span className="online-dot"/><span>Frontend online</span><span className="sidebar-version">{dataMode === "local" ? "v0.4 Local" : "v0.1 Demo"}</span></div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div className="topbar-left"><button className="mobile-menu icon-button" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Icon name="menu" size={20}/></button><span className="breadcrumb-root">Workspace</span><Icon name="chevron" size={14} className="breadcrumb-arrow"/><span className="breadcrumb-active">{(page === "details" ? "Jobs / Details" : page === "automation" ? "Home / Run Agent" : MENU.find(x=>x.id===page)?.label)}</span></div><div className="topbar-right"><div className="demo-badge"><span className="demo-dot"/>{dataMode === "local" ? "LOCAL DATA" : "DEMO MODE"}</div><span className="topbar-divider"/><div className="user-bubble" title="Google sign-in is not configured">?</div></div></header>
      <div className="page-content"><div className="page-heading"><div><div className="eyebrow">{hero.eyebrow}</div><h1>{hero.title}<span className="title-accent">.</span></h1><p>{hero.subtitle}</p></div><div className="heading-right"><span className="small-status"><Icon name="lock" size={14}/> {dataMode === "local" ? "Local Python API connected" : "Frontend preview · No backend connected"}</span></div></div>
      <div className="demo-notice"><Icon name="info" size={18}/><span>{dataMode === "local" ? <><strong>Local data mode.</strong> Showing saved job descriptions, screening scores and review drafts from your computer only. The published Vercel site still uses fictional data.</> : <><strong>Demo environment.</strong> All companies, positions, scores and activity shown here are fictional sample data. Your real local Agent is unchanged.</>}</span></div>

      {page === "overview" && <>
        <div className="product-quick-actions panel">
          <div className="product-quick-copy"><span className="tiny-label teal-label">AGENT CONTROL CENTER</span><h2>Ready for your next opportunity?</h2><p>Run your existing local workflow, inspect saved jobs, or update your career profile.</p></div>
          <div className="product-quick-buttons"><button className="primary-button" onClick={() => navigate("automation")}><Icon name="bolt" size={17}/> Run Agent</button><button className="secondary-button" onClick={() => navigate("opportunities")}><Icon name="briefcase" size={17}/> View Jobs</button><button className="secondary-button" onClick={() => navigate("profile")}><Icon name="layers" size={17}/> Edit Profile</button></div>
        </div>
        <DeadlineOverview enabled={dataMode === "local"} onViewJobs={() => navigate("opportunities")}/>
        <div className="metrics-grid">
          <div className="metric-card"><div className="metric-top"><span>{dataMode === "local" ? "Saved opportunities" : "Sample opportunities"}</span><span className="metric-icon mint-bg"><Icon name="briefcase" size={19}/></span></div><div className="metric-number">{jobs.length.toString().padStart(2,"0")}</div><div className="metric-foot"><span className="metric-foot-positive"><Icon name="layers" size={13}/> {dataMode === "local" ? "Local records" : "Demo records"}</span><span>In workspace</span></div></div>
          <div className="metric-card"><div className="metric-top"><span>High matches</span><span className="metric-icon blue-bg"><Icon name="sparkles" size={20}/></span></div><div className="metric-number">{highCount.toString().padStart(2,"0")}</div><div className="metric-foot"><span className="metric-foot-positive"><Icon name="check" size={13}/> {dataMode === "local" ? "Screening priority" : "85+ score"}</span><span>{dataMode === "local" ? "Local scoring" : "Sample ranking"}</span></div></div>
          <div className="metric-card"><div className="metric-top"><span>Shortlisted</span><span className="metric-icon purple-bg"><Icon name="bookmark" size={18}/></span></div><div className="metric-number">{shortlisted.length.toString().padStart(2,"0")}</div><div className="metric-foot"><span>Saved in this browser session</span></div></div>
          <div className="metric-card"><div className="metric-top"><span>Resume drafts</span><span className="metric-icon orange-bg"><Icon name="file" size={19}/></span></div><div className="metric-number">{(dataMode === "local" ? resumes.length : 0).toString().padStart(2,"0")}</div><div className="metric-foot"><span>{dataMode === "local" ? "Local Word review drafts" : "Cloud generator not connected"}</span></div></div>
        </div>
        <div className="content-grid">
          <section className="panel featured-panel"><div className="panel-header"><div><div className="panel-title">Top matching positions</div><div className="panel-subtitle">{dataMode === "local" ? "Saved roles ranked by match score" : "Sample roles ranked by match score"}</div></div><button className="quiet-link" onClick={() => navigate("opportunities")}>View all <Icon name="arrow" size={15}/></button></div><div className="job-list">{best.map(job => <JobRow key={job.id} job={job} saved={shortlisted.includes(job.id)} onOpen={()=>openJob(job.id)} onSave={()=>toggleSave(job.id)}/>)}</div></section>
          <section className="panel snapshot-panel"><div className="panel-header"><div><div className="panel-title">Your pipeline</div><div className="panel-subtitle">A preview of your workflow</div></div><span className="neutral-chip">5 STEPS</span></div><div className="pipeline">
            {[{name:"Discover jobs",description:"Gmail + Handshake",icon:"mail" as IconName,ready:true},{name:"Extract descriptions",description:"Playwright JD reader",icon:"code" as IconName,ready:true},{name:"Score & screen",description:"Matching and eligibility",icon:"filter" as IconName,ready:true},{name:"Draft tailored resume",description:"OpenAI + Word template",icon:"file" as IconName,ready:false},{name:"Human review",description:"Approve before using",icon:"shield" as IconName,ready:false}].map((item,index) => <div className="pipeline-step" key={item.name}><div className={`pipeline-icon ${item.ready ? "pipeline-icon-ready" : ""}`}><Icon name={item.icon} size={18}/></div><div className="pipeline-copy"><div>{item.name}</div><span>{item.description}</span></div><span className="pipeline-step-num">0{index+1}</span></div>)}</div><div className="pipeline-note">Existing local Python workflow. Cloud execution is not enabled.</div></section>
        </div>
        <div className="below-grid"><div className="tip-card"><span className="tip-icon"><Icon name="bolt" size={20}/></span><div><strong>Built for thoughtful applications</strong><p>Explore positions, verify eligibility, customize a resume and review it before any application.</p></div><button className="quiet-link" onClick={() => navigate("resumes")}>Resumes <Icon name="arrow" size={15}/></button></div></div>
      </>}

      {page === "opportunities" && <section className="panel opportunities-panel"><div className="panel-header opportunities-heading"><div><div className="panel-title">Job opportunities</div><div className="panel-subtitle">Browse {jobs.length} {dataMode === "local" ? "saved positions" : "fictional sample positions"}</div></div><span className="neutral-chip">{filtered.length} RESULTS</span></div><div className="toolbar"><label className="search-field"><Icon name="search" size={18}/><input placeholder="Search roles, companies, skills..." value={search} onChange={e=>setSearch(e.target.value)}/></label><label className="select-field"><Icon name="filter" size={17}/><select value={filter} onChange={e=>setFilter(e.target.value)} aria-label="Filter positions"><option>All positions</option><option>High Match</option><option>Review</option><option>Verify Eligibility</option><option>Shortlisted</option></select></label></div><div className="job-list detailed-list">{filtered.length ? filtered.map(job => <JobRow key={job.id} job={job} saved={shortlisted.includes(job.id)} onOpen={()=>openJob(job.id)} onSave={()=>toggleSave(job.id)}/>) : <div className="empty-state"><Icon name="search" size={29}/><strong>No matching positions</strong><p>Try another search or filter.</p><button className="secondary-button" onClick={()=>{setSearch("");setFilter("All positions")}}>Clear filters</button></div>}</div><div className="panel-footer">{dataMode === "local" ? "Scores from your local screening rules. Verify job requirements and work authorization independently." : "Sample match scores are illustrative only. Real job eligibility always requires independent verification."}</div></section>}

      {page === "details" && <><button className="secondary-button product-back" onClick={() => navigate("opportunities")}><Icon name="chevron" size={15}/> Back to Jobs</button><div className="detail-layout"><section className="panel detail-primary"><div className="detail-header"><CompanyMark job={selected} size="large"/><div className="detail-header-main"><div className="job-row-company">{selected.company} · {selected.id}</div><h2>{selected.title}</h2><div className="job-row-meta"><Icon name="pin" size={15}/>{selected.location}<span className="meta-separator">·</span>{selected.arrangement}</div></div></div><div className="detail-badges"><MatchTag status={selected.match}/><span className="skill-pill">{dataMode === "local" ? "Locally screened job" : "Sample listing"}</span></div><div className="detail-divider"/><h3>About this opportunity</h3><p className="detail-summary">{selected.summary}</p>
{dataMode === "local" && <section className="stage4-detail-block"><h3>Saved job description (full text)</h3>
{detailLoading ? <p className="stage4-muted">Loading saved JD…</p> : detailError ? <p className="stage4-warning">{detailError}</p> : jobDetail?.hasJd ? <><p className="stage4-muted">Private local file: {jobDetail.jdFilename}</p><pre className="stage4-document">{jobDetail.jdText}</pre></> : <p className="stage4-muted">No saved JD found for this job. Run your existing local JD extraction script first.</p>}
<h3>Screening priority</h3><p className="stage4-muted">{jobDetail?.priority || selected.priority || "Not recorded"}</p>
</section>}
<h3>{dataMode === "local" ? "Detected JD keywords" : "Example requirements"}</h3><ul className="bullet-list">{selected.requirements.map(r=><li key={r}>{r}</li>)}</ul><h3>Relevant skills</h3><div className="skills-row">{selected.skills.map(skill => <span className="skill-pill" key={skill}>{skill}</span>)}</div><h3>Review notes</h3><div className="review-notes">{selected.flags.map(flag=><div key={flag}><Icon name="info" size={15}/>{flag}</div>)}</div></section><aside className="detail-aside"><ApplicationTracker jobId={selected.id} enabled={dataMode === "local"}/><section className="panel detail-score"><div className="tiny-label">{dataMode === "local" ? "LOCAL SCREENING SCORE" : "ILLUSTRATIVE MATCH SCORE"}</div><div className="large-score">{selected.score}<span>/ 100</span></div><div className="score-track"><div style={{width:`${selected.score}%`}}/></div><p>{dataMode === "local" ? "Rule-based score; not a hiring prediction or authorization decision." : "This score is demo data, not a hiring prediction."}</p><button className={`primary-button ${shortlisted.includes(selected.id) ? "button-saved" : ""}`} onClick={()=>toggleSave(selected.id)}><Icon name="bookmark" size={17}/>{shortlisted.includes(selected.id) ? "Remove from shortlist" : "Add to shortlist"}</button><button className="secondary-button full-button" onClick={()=>navigate("resumes")}><Icon name="file" size={17}/> Go to Resume Studio</button></section><section className="panel detail-switch"><div className="panel-title">{dataMode === "local" ? "Other positions" : "Other sample roles"}</div>{jobs.filter(j=>j.id!==selected.id).slice(0,3).map(job=><button key={job.id} onClick={()=>setSelectedId(job.id)}><span>{job.title}<small>{job.company}</small></span><Icon name="chevron" size={17}/></button>)}</section></aside></div></>}

      {page === "resumes" && (dataMode === "local" ?
        <section className="stage4-studio">
          <div className="panel stage4-heading">
            <div><div className="panel-title">Your Word review drafts</div><div className="panel-subtitle">Local-only · Existing files from your Python Agent · No AI API call</div></div>
            <span className="neutral-chip">{resumes.length} WORD FILES</span>
          </div>
          <ResumeUploader enabled={dataMode === "local"} jobs={jobs} onUploaded={() => setResumeRefresh(value=>value+1)}/>
          <section className="panel stage5-generator">
            <div className="panel-title">Generate one tailored Word review draft</div>
            <p className="stage4-muted">Uses your existing local Python model integration. This can consume paid OpenAI API credits. It never submits a job application.</p>
            <label className="stage5-field">Target job
              <select value={draftJobId || jobs[0]?.id || ""} onChange={e => {setDraftJobId(e.target.value); setConfirmPaid(false); setAllowRisk(false);}}>
                {jobs.map(job => <option key={job.id} value={job.id}>{job.company} — {job.title} ({job.score}/100)</option>)}
              </select>
            </label>
            <label className="stage5-field">How to write the draft
              <select value={resumeEngine} onChange={e => setResumeEngine(e.target.value as "chunk" | "profile")}><option value="chunk">Tailor my master resume (recommended)</option><option value="profile">Write a new draft from My Profile</option></select>
            </label>
            {resumeEngine === "chunk" ? <p className="stage4-muted">Picks the most relevant bullets from Resume_&lt;Name&gt;.docx in the project folder, rewrites them for this job using only facts already in your resume, and fits one page. The review notes list what the job values and questions for facts you could add.</p> : <>
              <label className="stage5-field">Resume information source
                <select value={profileSource} onChange={e => setProfileSource(e.target.value as "json" | "legacy")}><option value="json">My Profile (recommended)</option><option value="legacy">Legacy profile.txt</option></select>
              </label>
              <p className="stage4-muted">My Profile must have at least one saved education, experience, or skill entry. The original profile.txt is never overwritten.</p>
            </>}
            <label className="stage5-check"><input type="checkbox" checked={allowRisk} onChange={e => setAllowRisk(e.target.checked)} /> I acknowledge that eligibility or deadline restrictions may require independent verification (only use if needed).</label>
            <label className="stage5-check"><input type="checkbox" checked={forceDraft} onChange={e => setForceDraft(e.target.checked)} /> Regenerate an existing matching draft (may incur additional cost)</label>
            <label className="stage5-check"><input type="checkbox" checked={confirmPaid} onChange={e => setConfirmPaid(e.target.checked)} /> I explicitly approve generating ONE paid AI resume draft for this selected job.</label>
            <button className="primary-button" disabled={!confirmPaid || taskBusy || !jobs.length} onClick={() => startLocalTask({action:"resume",jobId:draftJobId || jobs[0].id, confirmPaid:true,allowRisk,force:forceDraft,engine:resumeEngine,profileSource})}><Icon name="sparkles" size={16}/>{taskBusy ? "Task running..." : "Generate review draft"}</button>
          </section>
          {stage5Monitor}
          {resumesError && <div className="panel stage4-warning">{resumesError}</div>}
          {resumes.length === 0 ? <div className="panel stage4-empty"><Icon name="file" size={30}/><h3>No Word drafts found</h3><p>No saved Word files found. Choose a job and confirm AI drafting above, or upload a .docx you edited in Word.</p></div> :
            <div className="stage4-studio-grid">
              <section className="panel stage4-resume-list">
                <div className="panel-title">Saved drafts</div>
                {resumes.map(item => <button key={item.id} className={`stage4-resume-item ${activeResume?.id === item.id ? "stage4-active" : ""}`} onClick={() => setActiveResumeId(item.id)}>
                  <span className="stage4-resume-title">{item.jobTitle}</span>
                  <span className="stage4-muted">{item.company} · {item.jobId}</span>
                  <span className="stage4-small">{item.kind === "tailored" ? "Tailored from master · " : ""}{new Date(item.updatedAt).toLocaleString()}</span>
                </button>)}
              </section>
              <section className="panel stage4-resume-preview">
                <div className="panel-title">Draft review</div>
                {activeResume && <><div className="stage4-filename">{activeResume.filename}</div>
                  <a className="primary-button stage4-download" href={`${LOCAL_API}/api/resumes/${activeResume.jobId}/${activeResume.index}/download`}>
                    <Icon name="file" size={18}/> Download Word (.docx)
                  </a>
                  <p className="stage4-muted">Text preview only. Open the downloaded .docx in Word to verify actual formatting and content.</p>
                  {previewLoading ? <p className="stage4-muted">Loading preview…</p> : previewError ? <p className="stage4-warning">{previewError}</p> : resumePreview ? <pre className="stage4-document stage4-resume-text">{resumePreview.text}</pre> : null}
                </>}
              </section>
            </div>}
        </section>
        : <div className="studio-layout"><section className="panel studio-primary"><div className="studio-illustration"><div className="paper-back"/><div className="paper-front"><div className="paper-person"/><div className="paper-line paper-long"/><div className="paper-line paper-medium"/><div className="paper-divider"/><div className="paper-line paper-long"/><div className="paper-line paper-short"/><div className="paper-line paper-long"/><div className="paper-line paper-medium"/></div><div className="sparkle-float"><Icon name="sparkles" size={25}/></div></div><div className="studio-content"><div className="tiny-label teal-label">AI-POWERED RESUME WORKFLOW</div><h2>Make every application count.</h2><p>Your existing Python Agent can customize resume content and generate a Word document for review. The cloud generator has not been connected yet.</p><button className="primary-button disabled-button" disabled><Icon name="sparkles" size={18}/> Generate tailored resume <Icon name="lock" size={15}/></button><div className="disabled-caption">Disabled until a secure backend is configured. No AI calls or charges occur here.</div></div></section><section className="panel studio-side"><div className="panel-title">How it will work</div><div className="studio-steps"><div><span>01</span><section><strong>Select a position</strong><p>Choose a saved job with a verified description.</p></section></div><div><span>02</span><section><strong>Review the fit</strong><p>Inspect skills, location and eligibility notes.</p></section></div><div><span>03</span><section><strong>Create a Word draft</strong><p>Generate a tailored document from your private template.</p></section></div><div><span>04</span><section><strong>Approve the final version</strong><p>No automated job submission.</p></section></div></div></section></div>)}


      {page === "profile" && <ProfileEditor dataMode={dataMode} />}

      {page === "automation" && (dataMode === "local" ?
        <div className="stage5-automation">
          <section className="panel stage5-controls">
            <div className="panel-title">Run the local Job Agent</div>
            <p className="stage4-muted">Buttons run existing Python scripts on this computer. Only one task can run at a time; browser/OAuth windows may need attention. No automatic job applications.</p>
            <div className="stage5-actions">
              <button className="secondary-button" disabled={!!taskBusy} onClick={() => startLocalTask({action:"screen"})}>Rescore saved job descriptions</button>
              <button className="secondary-button" disabled={!!taskBusy} onClick={() => startLocalTask({action:"extract"})}>Extract pending descriptions (no Gmail)</button>
            </div>
            <div className="stage5-divider" />
            <label className="stage5-field">Max Handshake notification emails (1–50)
              <input type="number" min="1" max="50" value={maxEmails} onChange={e => setMaxEmails(Number(e.target.value))} />
            </label>
            <label className="stage5-check"><input type="checkbox" checked={confirmRead} onChange={e => setConfirmRead(e.target.checked)}/> I approve reading my connected Gmail to discover Handshake job notifications.</label>
            <button className="primary-button" disabled={!!taskBusy || !confirmRead || maxEmails < 1 || maxEmails > 50} onClick={() => startLocalTask({action:"import",maxEmails,confirmRead:true})}><Icon name="mail" size={16}/> {taskBusy ? "Task in progress..." : "Read Gmail → Extract JD → Screen"}</button>
          </section>
          <section className="panel stage5-controls">
            <div className="panel-title">Local integrations</div>
            <div className="panel-subtitle">Operations remain on your computer and reuse existing credentials.</div>
            {[{name:"Gmail OAuth",detail:"Uses current local token and Google authorization"},{name:"Playwright",detail:"Uses local browser session"},{name:"Screening",detail:"Your existing Python rules"},{name:"Word drafts",detail:"Explicit paid confirmation required"}].map(item => <div key={item.name} className="integration-row"><span>{item.name}</span><span className="stage4-muted">{item.detail}</span></div>)}
          </section>
          <SchedulePanel enabled={dataMode === "local"}/>
          <TaskHistory enabled={dataMode === "local"}/>
          {stage5Monitor}
        </div>
        : <div className="automation-grid"><section className="panel automain"><div className="automain-icon"><Icon name="workflow" size={32}/></div><div className="tiny-label teal-label">CLOUD NOT CONFIGURED</div><h2>Automate the repetitive work.</h2><p>The published Vercel site intentionally has no access to private Gmail, browser profiles, resumes or paid model calls. Use the local version until cloud authentication and storage are provisioned.</p><button className="primary-button disabled-button" disabled><Icon name="lock" size={17}/> Cloud pipeline unavailable</button></section><section className="panel integration-panel"><div className="panel-title">Cloud integrations</div>{[{name:"Gmail OAuth",icon:"mail" as IconName},{name:"Private cloud worker",icon:"code" as IconName},{name:"Private database",icon:"database" as IconName},{name:"Secure login",icon:"lock" as IconName}].map(row => <div className="integration-row" key={row.name}><span className="integration-icon"><Icon name={row.icon} size={18}/></span><span>{row.name}</span><span className="not-connected">Not connected</span></div>)}</section></div>)}
      <footer className="app-footer"><span>Job Agent · Frontend prototype</span><span>{dataMode === "local" ? "Private local JDs and Word drafts · No cloud sync" : "Fictional demo data · No personal data transmitted"}</span></footer>
      </div>
    </main>
  </div>;
}
