"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";

type Page = "overview" | "opportunities" | "details" | "resumes" | "automation";
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
};

// Deliberately fictional records: never use actual private Handshake/Gmail content as frontend fixtures.
const SAMPLE_JOBS: Job[] = [
  { id: "SAMPLE-001", company: "Northstar Labs", title: "Software Engineering Intern", location: "Remote · US", arrangement: "Remote", score: 93, match: "High Match", initials: "NL", color: "mint", skills: ["Python", "React", "REST APIs"], summary: "Example internship focused on building modern web applications and backend services.", requirements: ["Python or TypeScript experience", "Comfortable with APIs and Git", "Ability to work in a collaborative engineering team"], flags: ["Demo listing only", "Work eligibility must be verified for real positions"] },
  { id: "SAMPLE-002", company: "Meridian Data", title: "Machine Learning Intern", location: "New York · Hybrid", arrangement: "Hybrid", score: 89, match: "High Match", initials: "MD", color: "purple", skills: ["Python", "ML", "Pandas"], summary: "Example role involving machine learning experiments, evaluation and data pipelines.", requirements: ["Experience using Python for data analysis", "Familiarity with model evaluation", "Clear documentation practices"], flags: ["Demo listing only", "Sponsorship and student work authorization unknown"] },
  { id: "SAMPLE-003", company: "Atlas Systems", title: "Backend Developer Intern", location: "Boston · On-site", arrangement: "On-site", score: 84, match: "Review", initials: "AS", color: "blue", skills: ["Python", "SQL", "Docker"], summary: "Example backend internship focused on services, data storage and operational tooling.", requirements: ["Programming fundamentals", "Some SQL familiarity", "Comfortable reading unfamiliar code"], flags: ["Demo listing only", "Location constraints require review"] },
  { id: "SAMPLE-004", company: "Orbit Interactive", title: "AI Product Engineering Intern", location: "Remote · US", arrangement: "Remote", score: 78, match: "Verify Eligibility", initials: "OI", color: "orange", skills: ["LLMs", "JavaScript", "Product"], summary: "Example AI engineering position helping prototype LLM-powered product experiences.", requirements: ["Programming experience", "Interest in LLM-based applications", "Basic user interface development"], flags: ["Demo listing only", "Eligibility and location must be confirmed"] },
  { id: "SAMPLE-005", company: "Pioneer Analytics", title: "Data Analyst Intern", location: "Chicago · Hybrid", arrangement: "Hybrid", score: 86, match: "High Match", initials: "PA", color: "pink", skills: ["SQL", "Power BI", "Python"], summary: "Example analytics internship focused on dashboards, reporting and business insights.", requirements: ["Data cleaning and visualisation", "Python or SQL", "Ability to communicate findings"], flags: ["Demo listing only", "Check internship and work eligibility for real roles"] },
];

const MENU: { id: Page; label: string; icon: IconName }[] = [
  { id: "overview", label: "Overview", icon: "grid" },
  { id: "opportunities", label: "Opportunities", icon: "briefcase" },
  { id: "details", label: "Job Details", icon: "file" },
  { id: "resumes", label: "Resume Studio", icon: "layers" },
  { id: "automation", label: "Automation", icon: "workflow" },
];
const titles: Record<Page, { eyebrow: string; title: string; subtitle: string }> = {
  overview: { eyebrow: "WORKSPACE / OVERVIEW", title: "Your career workspace", subtitle: "A clear view of opportunities, matching and next steps." },
  opportunities: { eyebrow: "WORKSPACE / OPPORTUNITIES", title: "Explore opportunities", subtitle: "Search, filter and shortlist positions in one place." },
  details: { eyebrow: "WORKSPACE / JOB DETAILS", title: "Position details", subtitle: "Review a sample job description before taking action." },
  resumes: { eyebrow: "WORKSPACE / RESUME STUDIO", title: "Resume studio", subtitle: "Tailored resumes with a human review checkpoint." },
  automation: { eyebrow: "WORKSPACE / AUTOMATION", title: "Automation center", subtitle: "A future home for your email-to-resume pipeline." },
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
  const [page, setPage] = useState<Page>("overview");
  const [selectedId, setSelectedId] = useState("SAMPLE-001");
  const [shortlisted, setShortlisted] = useState<string[]>(["SAMPLE-001", "SAMPLE-002"]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("All positions");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const selected = SAMPLE_JOBS.find(j => j.id === selectedId) ?? SAMPLE_JOBS[0];
  const best = [...SAMPLE_JOBS].sort((a,b) => b.score - a.score).slice(0, 3);
  const filtered = useMemo(() => SAMPLE_JOBS.filter(job => {
    const needle = `${job.company} ${job.title} ${job.skills.join(" ")} ${job.location}`.toLowerCase();
    return needle.includes(search.trim().toLowerCase()) && (filter === "All positions" || (filter === "Shortlisted" ? shortlisted.includes(job.id) : job.match === filter));
  }).sort((a,b) => b.score - a.score), [search, filter, shortlisted]);
  const highCount = SAMPLE_JOBS.filter(j => j.match === "High Match").length;
  function navigate(next: Page) { setPage(next); setSidebarOpen(false); }
  function openJob(id: string) { setSelectedId(id); navigate("details"); }
  function toggleSave(id: string) { setShortlisted(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]); }
  const hero = titles[page];

  return <div className="app-shell">
    {sidebarOpen && <button className="mobile-scrim" onClick={() => setSidebarOpen(false)} aria-label="Close navigation"/>}
    <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
      <div className="brand-lockup"><div className="brand-logo"><Icon name="sparkles" size={22}/></div><div><div className="brand-name">job<span>agent</span><span className="brand-period">.</span></div><div className="brand-subtitle">CAREER INTELLIGENCE</div></div><button className="mobile-close" onClick={() => setSidebarOpen(false)} aria-label="Close menu"><Icon name="x" size={20}/></button></div>
      <div className="workspace-label"><span className="workspace-avatar">W</span><div><div className="workspace-title">My Workspace</div><div className="workspace-sub">Personal dashboard</div></div><Icon name="chevron" size={16} className="workspace-chevron"/></div>
      <div className="nav-caption">WORKSPACE</div>
      <nav className="sidebar-nav" aria-label="Main navigation">{MENU.map(item => <button key={item.id} className={`nav-link ${page === item.id ? "nav-active" : ""}`} onClick={() => navigate(item.id)}><Icon name={item.icon} size={19}/><span>{item.label}</span>{page === item.id && <span className="nav-active-pin"/>}</button>)}</nav>
      <div className="sidebar-grow"/>
      <div className="sidebar-note"><div className="sidebar-note-top"><Icon name="shield" size={17}/><span>Private by design</span></div><p>No Gmail data, tokens, or personal resumes are included in this demo.</p></div>
      <div className="sidebar-bottom"><span className="online-dot"/><span>Frontend online</span><span className="sidebar-version">v0.1 Demo</span></div>
    </aside>

    <main className="main-content">
      <header className="topbar"><div className="topbar-left"><button className="mobile-menu icon-button" onClick={() => setSidebarOpen(true)} aria-label="Open navigation"><Icon name="menu" size={20}/></button><span className="breadcrumb-root">Workspace</span><Icon name="chevron" size={14} className="breadcrumb-arrow"/><span className="breadcrumb-active">{MENU.find(x=>x.id===page)?.label}</span></div><div className="topbar-right"><div className="demo-badge"><span className="demo-dot"/>DEMO MODE</div><span className="topbar-divider"/><div className="user-bubble">JA</div></div></header>
      <div className="page-content"><div className="page-heading"><div><div className="eyebrow">{hero.eyebrow}</div><h1>{hero.title}<span className="title-accent">.</span></h1><p>{hero.subtitle}</p></div><div className="heading-right"><span className="small-status"><Icon name="lock" size={14}/> Frontend preview · No backend connected</span></div></div>
      <div className="demo-notice"><Icon name="info" size={18}/><span><strong>Demo environment.</strong> All companies, positions, scores and activity shown here are fictional sample data. Your real local Agent is unchanged.</span></div>

      {page === "overview" && <>
        <div className="metrics-grid">
          <div className="metric-card"><div className="metric-top"><span>Sample opportunities</span><span className="metric-icon mint-bg"><Icon name="briefcase" size={19}/></span></div><div className="metric-number">{SAMPLE_JOBS.length.toString().padStart(2,"0")}</div><div className="metric-foot"><span className="metric-foot-positive"><Icon name="layers" size={13}/> Demo records</span><span>In workspace</span></div></div>
          <div className="metric-card"><div className="metric-top"><span>High matches</span><span className="metric-icon blue-bg"><Icon name="sparkles" size={20}/></span></div><div className="metric-number">{highCount.toString().padStart(2,"0")}</div><div className="metric-foot"><span className="metric-foot-positive"><Icon name="check" size={13}/> 85+ score</span><span>Sample ranking</span></div></div>
          <div className="metric-card"><div className="metric-top"><span>Shortlisted</span><span className="metric-icon purple-bg"><Icon name="bookmark" size={18}/></span></div><div className="metric-number">{shortlisted.length.toString().padStart(2,"0")}</div><div className="metric-foot"><span>Saved in this browser session</span></div></div>
          <div className="metric-card"><div className="metric-top"><span>Resume drafts</span><span className="metric-icon orange-bg"><Icon name="file" size={19}/></span></div><div className="metric-number">00</div><div className="metric-foot"><span>Cloud generator not connected</span></div></div>
        </div>
        <div className="content-grid">
          <section className="panel featured-panel"><div className="panel-header"><div><div className="panel-title">Top matching positions</div><div className="panel-subtitle">Sample roles ranked by match score</div></div><button className="quiet-link" onClick={() => navigate("opportunities")}>View all <Icon name="arrow" size={15}/></button></div><div className="job-list">{best.map(job => <JobRow key={job.id} job={job} saved={shortlisted.includes(job.id)} onOpen={()=>openJob(job.id)} onSave={()=>toggleSave(job.id)}/>)}</div></section>
          <section className="panel snapshot-panel"><div className="panel-header"><div><div className="panel-title">Your pipeline</div><div className="panel-subtitle">A preview of your workflow</div></div><span className="neutral-chip">5 STEPS</span></div><div className="pipeline">
            {[{name:"Discover jobs",description:"Gmail + Handshake",icon:"mail" as IconName,ready:true},{name:"Extract descriptions",description:"Playwright JD reader",icon:"code" as IconName,ready:true},{name:"Score & screen",description:"Matching and eligibility",icon:"filter" as IconName,ready:true},{name:"Draft tailored resume",description:"OpenAI + Word template",icon:"file" as IconName,ready:false},{name:"Human review",description:"Approve before using",icon:"shield" as IconName,ready:false}].map((item,index) => <div className="pipeline-step" key={item.name}><div className={`pipeline-icon ${item.ready ? "pipeline-icon-ready" : ""}`}><Icon name={item.icon} size={18}/></div><div className="pipeline-copy"><div>{item.name}</div><span>{item.description}</span></div><span className="pipeline-step-num">0{index+1}</span></div>)}</div><div className="pipeline-note">Existing local Python workflow. Cloud execution is not enabled.</div></section>
        </div>
        <div className="below-grid"><div className="tip-card"><span className="tip-icon"><Icon name="bolt" size={20}/></span><div><strong>Built for thoughtful applications</strong><p>Explore positions, verify eligibility, customize a resume and review it before any application.</p></div><button className="quiet-link" onClick={() => navigate("resumes")}>Resume Studio <Icon name="arrow" size={15}/></button></div></div>
      </>}

      {page === "opportunities" && <section className="panel opportunities-panel"><div className="panel-header opportunities-heading"><div><div className="panel-title">Job opportunities</div><div className="panel-subtitle">Browse {SAMPLE_JOBS.length} fictional sample positions</div></div><span className="neutral-chip">{filtered.length} RESULTS</span></div><div className="toolbar"><label className="search-field"><Icon name="search" size={18}/><input placeholder="Search roles, companies, skills..." value={search} onChange={e=>setSearch(e.target.value)}/></label><label className="select-field"><Icon name="filter" size={17}/><select value={filter} onChange={e=>setFilter(e.target.value)} aria-label="Filter positions"><option>All positions</option><option>High Match</option><option>Review</option><option>Verify Eligibility</option><option>Shortlisted</option></select></label></div><div className="job-list detailed-list">{filtered.length ? filtered.map(job => <JobRow key={job.id} job={job} saved={shortlisted.includes(job.id)} onOpen={()=>openJob(job.id)} onSave={()=>toggleSave(job.id)}/>) : <div className="empty-state"><Icon name="search" size={29}/><strong>No matching sample positions</strong><p>Try another search or filter.</p><button className="secondary-button" onClick={()=>{setSearch("");setFilter("All positions")}}>Clear filters</button></div>}</div><div className="panel-footer">Sample match scores are illustrative only. Real job eligibility always requires independent verification.</div></section>}

      {page === "details" && <div className="detail-layout"><section className="panel detail-primary"><div className="detail-header"><CompanyMark job={selected} size="large"/><div className="detail-header-main"><div className="job-row-company">{selected.company} · {selected.id}</div><h2>{selected.title}</h2><div className="job-row-meta"><Icon name="pin" size={15}/>{selected.location}<span className="meta-separator">·</span>{selected.arrangement}</div></div></div><div className="detail-badges"><MatchTag status={selected.match}/><span className="skill-pill">Sample listing</span></div><div className="detail-divider"/><h3>About this opportunity</h3><p className="detail-summary">{selected.summary}</p><h3>Example requirements</h3><ul className="bullet-list">{selected.requirements.map(r=><li key={r}>{r}</li>)}</ul><h3>Relevant skills</h3><div className="skills-row">{selected.skills.map(skill => <span className="skill-pill" key={skill}>{skill}</span>)}</div><h3>Review notes</h3><div className="review-notes">{selected.flags.map(flag=><div key={flag}><Icon name="info" size={15}/>{flag}</div>)}</div></section><aside className="detail-aside"><section className="panel detail-score"><div className="tiny-label">ILLUSTRATIVE MATCH SCORE</div><div className="large-score">{selected.score}<span>/ 100</span></div><div className="score-track"><div style={{width:`${selected.score}%`}}/></div><p>This score is demo data, not a hiring prediction.</p><button className={`primary-button ${shortlisted.includes(selected.id) ? "button-saved" : ""}`} onClick={()=>toggleSave(selected.id)}><Icon name="bookmark" size={17}/>{shortlisted.includes(selected.id) ? "Remove from shortlist" : "Add to shortlist"}</button><button className="secondary-button full-button" onClick={()=>navigate("resumes")}><Icon name="file" size={17}/> Go to Resume Studio</button></section><section className="panel detail-switch"><div className="panel-title">Other sample roles</div>{SAMPLE_JOBS.filter(j=>j.id!==selected.id).slice(0,3).map(job=><button key={job.id} onClick={()=>setSelectedId(job.id)}><span>{job.title}<small>{job.company}</small></span><Icon name="chevron" size={17}/></button>)}</section></aside></div>}

      {page === "resumes" && <div className="studio-layout"><section className="panel studio-primary"><div className="studio-illustration"><div className="paper-back"/><div className="paper-front"><div className="paper-person"/><div className="paper-line paper-long"/><div className="paper-line paper-medium"/><div className="paper-divider"/><div className="paper-line paper-long"/><div className="paper-line paper-short"/><div className="paper-line paper-long"/><div className="paper-line paper-medium"/></div><div className="sparkle-float"><Icon name="sparkles" size={25}/></div></div><div className="studio-content"><div className="tiny-label teal-label">AI-POWERED RESUME WORKFLOW</div><h2>Make every application count.</h2><p>Your existing Python Agent can customize resume content and generate a Word document for review. The cloud generator has not been connected yet.</p><button className="primary-button disabled-button" disabled><Icon name="sparkles" size={18}/> Generate tailored resume <Icon name="lock" size={15}/></button><div className="disabled-caption">Disabled until a secure backend is configured. No AI calls or charges occur here.</div></div></section><section className="panel studio-side"><div className="panel-title">How it will work</div><div className="studio-steps"><div><span>01</span><section><strong>Select a position</strong><p>Choose a saved job with a verified description.</p></section></div><div><span>02</span><section><strong>Review the fit</strong><p>Inspect skills, location and eligibility notes.</p></section></div><div><span>03</span><section><strong>Create a Word draft</strong><p>Generate a tailored document from your private template.</p></section></div><div><span>04</span><section><strong>Approve the final version</strong><p>No automated job submission.</p></section></div></div></section></div>}

      {page === "automation" && <div className="automation-grid"><section className="panel automain"><div className="automain-icon"><Icon name="workflow" size={32}/></div><div className="tiny-label teal-label">PIPELINE CONFIGURATION</div><h2>Automate the repetitive work.</h2><p>Your local pipeline already imports Handshake emails, verifies URLs, extracts job descriptions, screens roles, and prepares a review queue. In the cloud, these tasks need a secure backend and persistent storage.</p><button className="primary-button disabled-button" disabled><Icon name="bolt" size={18}/> Run cloud pipeline <Icon name="lock" size={15}/></button><div className="disabled-caption">Unavailable in the frontend demo. Your existing local Python scripts are unchanged.</div></section><section className="panel integration-panel"><div className="panel-title">Cloud integrations</div><div className="panel-subtitle">Connection status for this deployed preview</div>{[{name:"Gmail OAuth",icon:"mail" as IconName},{name:"Playwright worker",icon:"code" as IconName},{name:"Persistent database",icon:"database" as IconName},{name:"Resume generation API",icon:"sparkles" as IconName}].map(row => <div className="integration-row" key={row.name}><span className="integration-icon"><Icon name={row.icon} size={18}/></span><span>{row.name}</span><span className="not-connected">Not connected</span></div>)}</section></div>}
      <footer className="app-footer"><span>Job Agent · Frontend prototype</span><span>Fictional demo data · No personal data transmitted</span></footer>
      </div>
    </main>
  </div>;
}
