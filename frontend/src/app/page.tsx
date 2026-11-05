"use client";

import { useEffect, useRef, useState } from "react";
import ProfileEditor from "./components/ProfileEditor";
import FindJobsPage from "./components/pages/FindJobsPage";
import HomePage from "./components/pages/HomePage";
import JobDetailPage from "./components/pages/JobDetailPage";
import JobsPage from "./components/pages/JobsPage";
import MasterResumePage from "./components/pages/MasterResumePage";
import ResumesPage from "./components/pages/ResumesPage";
import DraftsPage from "./components/pages/DraftsPage";
import "./components/studio.css";
import { ACTION_HEADERS, DataMode, Icon, isApplied, Job, LOCAL_API, LocalTask, Page, ResumeRecord } from "./lib/shared";

type JobsApiResponse = { jobs: Job[]; count: number };
type ResumeApiResponse = { count: number; resumes: ResumeRecord[] };

// Deliberately fictional records: never use actual private Handshake/Gmail content as frontend fixtures.
const SAMPLE_JOBS: Job[] = [
  { id: "SAMPLE-001", company: "Northstar Labs", title: "Software Engineering Intern", location: "Remote · US", arrangement: "Remote", score: 93, match: "High Match", initials: "NL", color: "mint", skills: ["Python", "React", "REST APIs"], summary: "Example internship focused on building modern web applications and backend services.", requirements: ["Python or TypeScript experience", "Comfortable with APIs and Git", "Ability to work in a collaborative engineering team"], flags: ["Demo listing only", "Work eligibility must be verified for real positions"] },
  { id: "SAMPLE-002", company: "Meridian Data", title: "Machine Learning Intern", location: "New York · Hybrid", arrangement: "Hybrid", score: 89, match: "High Match", initials: "MD", color: "purple", skills: ["Python", "ML", "Pandas"], summary: "Example role involving machine learning experiments, evaluation and data pipelines.", requirements: ["Experience using Python for data analysis", "Familiarity with model evaluation", "Clear documentation practices"], flags: ["Demo listing only", "Sponsorship and student work authorization unknown"] },
  { id: "SAMPLE-003", company: "Atlas Systems", title: "Backend Developer Intern", location: "Boston · On-site", arrangement: "On-site", score: 84, match: "Review", initials: "AS", color: "blue", skills: ["Python", "SQL", "Docker"], summary: "Example backend internship focused on services, data storage and operational tooling.", requirements: ["Programming fundamentals", "Some SQL familiarity", "Comfortable reading unfamiliar code"], flags: ["Demo listing only", "Location constraints require review"] },
  { id: "SAMPLE-004", company: "Orbit Interactive", title: "AI Product Engineering Intern", location: "Remote · US", arrangement: "Remote", score: 78, match: "Verify Eligibility", initials: "OI", color: "orange", skills: ["LLMs", "JavaScript", "Product"], summary: "Example AI engineering position helping prototype LLM-powered product experiences.", requirements: ["Programming experience", "Interest in LLM-based applications", "Basic user interface development"], flags: ["Demo listing only", "Eligibility and location must be confirmed"] },
  { id: "SAMPLE-005", company: "Pioneer Analytics", title: "Data Analyst Intern", location: "Chicago · Hybrid", arrangement: "Hybrid", score: 86, match: "High Match", initials: "PA", color: "pink", skills: ["SQL", "Power BI", "Python"], summary: "Example analytics internship focused on dashboards, reporting and business insights.", requirements: ["Data cleaning and visualisation", "Python or SQL", "Ability to communicate findings"], flags: ["Demo listing only", "Check internship and work eligibility for real roles"] },
];

// Sidebar follows the workflow: find -> review -> tailor -> profile.
// Job lists (saved, high matches, shortlist, drafts) open from the Home cards.
const MENU: { id: Page; label: string; icon: "grid" | "mail" | "briefcase" | "file" | "layers" }[] = [
  { id: "overview", label: "Home", icon: "grid" },
  { id: "find", label: "Find Jobs", icon: "mail" },
  { id: "resumes", label: "Resumes", icon: "file" },
  { id: "master", label: "Master Resume", icon: "layers" },
];
const TITLES: Record<Page, { title: string; subtitle: string }> = {
  overview: { title: "Your career workspace", subtitle: "New jobs, deadlines and drafts at a glance." },
  find: { title: "Find jobs", subtitle: "Import Handshake jobs from Gmail and score them." },
  opportunities: { title: "Saved jobs", subtitle: "Every saved job, ranked by match score." },
  high: { title: "High matches", subtitle: "Jobs your screening rated as a high match." },
  shortlist: { title: "Shortlisted", subtitle: "Jobs you bookmarked to come back to." },
  drafts: { title: "Resume drafts", subtitle: "Every tailored resume and the job it was written for." },
  details: { title: "Job details", subtitle: "Read the job, track your application, tailor a resume." },
  resumes: { title: "Resumes", subtitle: "Generate tailored drafts and review what changed." },
  master: { title: "Master resume", subtitle: "The one resume every tailored draft is built from." },
  profile: { title: "My Profile (older)", subtitle: "Used only by the older “Write from My Profile” option." },
};

// Pages a job can be opened from; "Back" on the job page returns there.
const LIST_PAGES: Page[] = ["overview", "opportunities", "high", "shortlist", "drafts"];

export default function Home() {
  const [dataMode, setDataMode] = useState<DataMode>("demo");
  const [jobs, setJobs] = useState<Job[]>(SAMPLE_JOBS);
  const [resumes, setResumes] = useState<ResumeRecord[]>([]);
  const [resumesError, setResumesError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [task, setTask] = useState<LocalTask | null>(null);
  const [taskError, setTaskError] = useState("");
  const [startingTask, setStartingTask] = useState(false);
  const [page, setPage] = useState<Page>("overview");
  const [selectedId, setSelectedId] = useState("SAMPLE-001");
  const [draftJobId, setDraftJobId] = useState("");
  const [draftVersionId, setDraftVersionId] = useState("");
  // Where "Back" on a job's page returns to.
  const [listPage, setListPage] = useState<Page>("opportunities");
  const [shortlisted, setShortlisted] = useState<string[]>(["SAMPLE-001", "SAMPLE-002"]);
  const [applied, setApplied] = useState<string[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const loadedLocal = useRef(false);

  useEffect(() => {
    // The published site never tries to reach somebody's local service.
    if (!(["localhost", "127.0.0.1"].includes(window.location.hostname))) return;
    const controller = new AbortController();
    fetch(`${LOCAL_API}/api/jobs`, { signal: controller.signal, cache: "no-store" })
      .then(res => { if (!res.ok) throw new Error(); return res.json() as Promise<JobsApiResponse>; })
      .then(data => {
        if (controller.signal.aborted || !Array.isArray(data.jobs) || data.jobs.length === 0) return;
        setJobs(data.jobs);
        if (!loadedLocal.current) {
          loadedLocal.current = true;
          setSelectedId(data.jobs[0].id);
          setShortlisted([]);
          setDataMode("local");
        }
      })
      .catch(() => { /* Keep the labelled demo when the API is offline. */ });
    return () => controller.abort();
  }, [refresh]);
  useEffect(() => {
    if (dataMode !== "local") return;
    let mounted = true;
    const update = () => fetch(`${LOCAL_API}/api/tracker`, { cache: "no-store" })
      .then(res => res.ok ? res.json() as Promise<{ applications: Record<string, { saved?: boolean; jobId?: string; status?: string }> }> : Promise.reject())
      .then(data => {
        if (!mounted) return;
        const rows = Object.values(data.applications || {});
        setShortlisted(rows.filter(x => x.saved).map(x => String(x.jobId || "")));
        setApplied(rows.filter(x => isApplied(x.status)).map(x => String(x.jobId || "")));
      })
      .catch(() => {});
    void update(); window.addEventListener("job-agent-tracker-updated", update);
    return () => { mounted = false; window.removeEventListener("job-agent-tracker-updated", update); };
  }, [dataMode]);
  useEffect(() => {
    if (dataMode !== "local") return;
    const controller = new AbortController();
    fetch(`${LOCAL_API}/api/resumes`, { signal: controller.signal, cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error(); return r.json() as Promise<ResumeApiResponse>; })
      .then(data => { setResumes(Array.isArray(data.resumes) ? data.resumes : []); setResumesError(""); })
      .catch(() => { if (!controller.signal.aborted) setResumesError("Cannot load drafts. Restart the local API and refresh."); });
    return () => controller.abort();
  }, [dataMode, refresh]);
  useEffect(() => {
    if (dataMode !== "local") return;
    let active = true;
    let lastStatus = "";
    const update = () => fetch(`${LOCAL_API}/api/tasks/current`, { cache: "no-store" })
      .then(res => res.ok ? res.json() as Promise<{ task: LocalTask | null }> : Promise.reject())
      .then(data => {
        if (!active) return;
        setTask(data.task);
        const status = data.task?.status ?? "";
        // Reload jobs and drafts automatically when a task finishes.
        if ((lastStatus === "running" || lastStatus === "queued") && (status === "succeeded" || status === "failed")) setRefresh(v => v + 1);
        lastStatus = status;
      })
      .catch(() => { /* Local server may have stopped. */ });
    void update();
    const timer = window.setInterval(update, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [dataMode]);

  const local = dataMode === "local";
  const taskBusy = startingTask || task?.status === "queued" || task?.status === "running";
  async function startTask(payload: Record<string, unknown>) {
    if (!local || taskBusy) return;
    setStartingTask(true);
    setTaskError("");
    try {
      const res = await fetch(`${LOCAL_API}/api/tasks`, { method: "POST", cache: "no-store", headers: ACTION_HEADERS, body: JSON.stringify(payload) });
      const result = await res.json() as LocalTask & { error?: string };
      if (!res.ok) throw new Error(result.error || "Cannot start the task");
      setTask(result);
    } catch (err) {
      setTaskError(err instanceof Error ? err.message : "Cannot start the task");
    } finally { setStartingTask(false); }
  }
  function navigate(next: Page) { setPage(next); setSidebarOpen(false); }
  function openJob(id: string) {
    if (page !== "details") setListPage(LIST_PAGES.includes(page) ? page : "opportunities");
    setSelectedId(id); navigate("details");
  }
  // Opening Resumes for a job preselects it in the form and its drafts (and a version, from the drafts list).
  function openResumes(id: string, versionId = "") { setDraftJobId(id); setDraftVersionId(versionId); navigate("resumes"); }
  function toggleSave(id: string) {
    const saved = !shortlisted.includes(id);
    setShortlisted(prev => saved ? [...prev.filter(x => x !== id), id] : prev.filter(x => x !== id));
    if (!local) return;
    fetch(`${LOCAL_API}/api/tracker`, { method: "POST", headers: ACTION_HEADERS, body: JSON.stringify({ jobId: id, saved }) })
      .then(res => { if (!res.ok) throw new Error(); window.dispatchEvent(new Event("job-agent-tracker-updated")); })
      .catch(() => setShortlisted(prev => saved ? prev.filter(x => x !== id) : [...prev, id]));
  }
  // Checked on Home = tracker status "Applied"; unchecked = back to "Discovered".
  // Stored in the same tracker as the job page's Application status, so both agree.
  function toggleApplied(id: string) {
    const nowApplied = !applied.includes(id);
    setApplied(prev => nowApplied ? [...prev.filter(x => x !== id), id] : prev.filter(x => x !== id));
    if (!local) return;
    fetch(`${LOCAL_API}/api/tracker`, { method: "POST", headers: ACTION_HEADERS, body: JSON.stringify({ jobId: id, status: nowApplied ? "Applied" : "Discovered" }) })
      .then(res => { if (!res.ok) throw new Error(); window.dispatchEvent(new Event("job-agent-tracker-updated")); })
      .catch(() => setApplied(prev => nowApplied ? prev.filter(x => x !== id) : [...prev, id]));
  }
  const selected = jobs.find(j => j.id === selectedId) ?? jobs[0];
  const activeMenu = page === "profile" ? "master" : LIST_PAGES.includes(page) || page === "details" ? "overview" : page;
  const hero = TITLES[page];
  const listTitle = listPage === "overview" ? "Home" : TITLES[listPage].title;
  const crumb = page === "details" ? (listPage === "overview" ? `Home / ${selected.company}` : `Home / ${listTitle} / ${selected.company}`)
    : page === "profile" ? "Master Resume / My Profile"
    : LIST_PAGES.includes(page) && page !== "overview" ? `Home / ${hero.title}`
    : MENU.find(x => x.id === page)?.label;

  return <div className="app-shell">
    {sidebarOpen && <button className="mobile-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"/>}
    <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
      <div className="brand-lockup"><div className="brand-logo"><Icon name="sparkles" size={22}/></div><div><div className="brand-name">job<span>agent</span><span className="brand-period">.</span></div><div className="brand-subtitle">CAREER INTELLIGENCE</div></div><button className="mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Close menu"><Icon name="x" size={20}/></button></div>
      <nav className="sidebar-nav" aria-label="Main navigation">{MENU.map(item => <button key={item.id} className={`nav-link ${activeMenu === item.id ? "nav-active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{item.label}</span>{activeMenu === item.id && <span className="nav-active-pin"/>}</button>)}</nav>
      <div className="sidebar-grow"/>
      <div className="sidebar-bottom" title={local ? "Reading data from api_local.py on this computer" : "Local API not running: showing sample data"}><span className={local ? "online-dot" : "offline-dot"}/><span>{local ? "Local API connected" : "Sample data"}</span></div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div className="topbar-left"><button className="mobile-menu icon-button" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Icon name="menu" size={20}/></button><span className="breadcrumb-active">{crumb}</span></div></header>
      <div className="page-content">
        <div className="page-heading"><div><h1>{hero.title}<span className="title-accent">.</span></h1><p>{hero.subtitle}</p></div></div>
        {!local && <div className="demo-notice"><Icon name="info" size={18}/><span><strong>Sample data.</strong> The local API is not running, so the companies and scores shown are fictional. Start the app with start.bat to see your own jobs.</span></div>}

        {page === "overview" && <HomePage dataMode={dataMode} jobs={jobs} resumes={resumes} shortlisted={shortlisted} applied={applied}
          onFindJobs={() => navigate("find")} onJobs={() => navigate("opportunities")} onOpenJob={openJob} onOpenList={navigate}
          onToggleSave={toggleSave} onToggleApplied={toggleApplied} onOpenDrafts={openResumes}/>}
        {page === "find" && <FindJobsPage dataMode={dataMode} task={task} taskError={taskError} taskBusy={taskBusy} startTask={startTask} onTaskDone={() => setRefresh(v => v + 1)}/>}
        {LIST_PAGES.includes(page) && page !== "overview" && <button className="secondary-button product-back" onClick={() => navigate("overview")}><Icon name="chevron" size={15}/> Back to Home</button>}
        {page === "opportunities" && <JobsPage dataMode={dataMode} jobs={jobs} shortlisted={shortlisted} applied={applied} onOpenJob={openJob} onToggleSave={toggleSave}/>}
        {page === "high" && <JobsPage dataMode={dataMode} jobs={jobs.filter(j => j.match === "High Match")} shortlisted={shortlisted} applied={applied} onOpenJob={openJob} onToggleSave={toggleSave}
          empty={{ title: "No high matches yet", text: "Find new jobs or rescore your saved jobs to see high matches here." }}/>}
        {page === "shortlist" && <JobsPage dataMode={dataMode} jobs={jobs.filter(j => shortlisted.includes(j.id))} shortlisted={shortlisted} applied={applied} onOpenJob={openJob} onToggleSave={toggleSave}
          empty={{ title: "Nothing shortlisted yet", text: "Click the bookmark on any job to keep it here." }}/>}
        {page === "drafts" && <DraftsPage dataMode={dataMode} jobs={jobs} resumes={resumes} resumesError={resumesError} applied={applied}
          onOpenJob={openJob} onReview={openResumes}/>}
        {page === "details" && <JobDetailPage dataMode={dataMode} job={selected} others={jobs.filter(j => j.id !== selected.id)} saved={shortlisted.includes(selected.id)}
          applied={applied.includes(selected.id)}
          backLabel={listPage === "overview" ? "Back to Home" : `Back to ${listTitle.toLowerCase()}`} onBack={() => navigate(listPage)} onSelect={setSelectedId} onToggleSave={() => toggleSave(selected.id)} onTailor={() => openResumes(selected.id)}/>}
        {page === "resumes" && <ResumesPage dataMode={dataMode} jobs={jobs} resumes={resumes} resumesError={resumesError} applied={applied}
          draftJobId={draftJobId} setDraftJobId={setDraftJobId} draftVersionId={draftVersionId} task={task} taskError={taskError} taskBusy={taskBusy}
          startTask={startTask} onRefresh={() => setRefresh(v => v + 1)}/>}
        {page === "master" && <MasterResumePage dataMode={dataMode} onOpenProfileForm={() => navigate("profile")}/>}
        {page === "profile" && <>
          <button className="secondary-button product-back" onClick={() => navigate("master")}><Icon name="chevron" size={15}/> Back to master resume</button>
          <ProfileEditor dataMode={dataMode}/>
        </>}
      </div>
    </main>
  </div>;
}
