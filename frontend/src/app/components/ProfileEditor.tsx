"use client";

import { useEffect, useMemo, useState } from "react";
import "./profile-layout.css";

type Section = "personal" | "education" | "projects" | "work" | "research" | "leadership" | "skills";
type Personal = { fullName: string; email: string; phone: string; location: string; linkedin: string; github: string; website: string };
type Education = { id: string; school: string; degree: string; major: string; gpa: string; startDate: string; endDate: string; courses: string };
type Experience = { id: string; title: string; organization: string; role: string; period: string; startDate: string; endDate: string; location: string; description: string };
type Skills = { languages: string; frameworks: string; tools: string; other: string };
type Profile = { personal: Personal; education: Education[]; projects: Experience[]; work: Experience[]; research: Experience[]; leadership: Experience[]; skills: Skills };

const API = "http://127.0.0.1:8765";
const EMPTY: Profile = {
  personal: { fullName: "", email: "", phone: "", location: "", linkedin: "", github: "", website: "" },
  education: [], projects: [], work: [], research: [], leadership: [],
  skills: { languages: "", frameworks: "", tools: "", other: "" },
};

const TABS: { id: Section; label: string; subtitle: string; icon: string }[] = [
  { id: "personal", label: "Personal Information", subtitle: "Your contact details and professional links", icon: "01" },
  { id: "education", label: "Education", subtitle: "Universities, degrees, GPA and coursework", icon: "02" },
  { id: "projects", label: "Projects & Activities", subtitle: "Academic projects, competitions and activities", icon: "03" },
  { id: "work", label: "Work Experience", subtitle: "Internships, responsibilities and outcomes", icon: "04" },
  { id: "research", label: "Research Experience", subtitle: "Research questions, methods and contributions", icon: "05" },
  { id: "leadership", label: "Leadership", subtitle: "Teams and organizations you have led", icon: "06" },
  { id: "skills", label: "Technical Skills", subtitle: "Programming languages, frameworks and tools", icon: "07" },
];
const EXPERIENCE_LABELS: Record<"projects" | "work" | "research" | "leadership", { title: string; organization: string; role: string }> = {
  projects: { title: "Project / Activity", organization: "School / Group (optional)", role: "Your contribution" },
  work: { title: "Position title", organization: "Company", role: "Team / Focus (optional)" },
  research: { title: "Research topic", organization: "Lab / Institution", role: "Your research role" },
  leadership: { title: "Leadership title", organization: "Organization / Team", role: "Responsibilities" },
};

function field(label: string, value: string, onChange: (next: string) => void, disabled: boolean, opts?: { full?: boolean; multiline?: boolean; placeholder?: string }) {
  return <label className={`product-field ${opts?.full ? "full" : ""}`} key={label}>
    <span className="product-field-label">{label}</span>
    {opts?.multiline
      ? <textarea value={value} placeholder={opts?.placeholder} disabled={disabled} onChange={e => onChange(e.target.value)} rows={4} />
      : <input type="text" value={value} 
placeholder={
  opts?.placeholder ||
  (label === "Start date"
    ? "e.g., 08/2025 (MM/YYYY)"
    : label === "Graduation / End date"
      ? "e.g., 05/2029 (MM/YYYY)"
      : `Enter ${label.toLowerCase()}`)
}
 disabled={disabled} onChange={e => onChange(e.target.value)} />}
  </label>;
}
const makeId = () => typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
const blankEducation = (): Education => ({ id: makeId(), school: "", degree: "", major: "", gpa: "", startDate: "", endDate: "", courses: "" });
const blankExperience = (): Experience => ({ id: makeId(), title: "", organization: "", role: "", period: "", startDate: "", endDate: "", location: "", description: "" });

export default function ProfileEditor({ dataMode }: { dataMode: "local" | "demo" }) {
  const local = dataMode === "local";
  const [section, setSection] = useState<Section>("personal");
  const [profile, setProfile] = useState<Profile>(EMPTY);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [savedMessage, setSavedMessage] = useState("");
  const [retry, setRetry] = useState(0);
  const tab = useMemo(() => TABS.find(t => t.id === section)!, [section]);
  const editable = local && loaded && !loading && !saving;
  const canSave = editable && dirty;

  useEffect(() => {
    if (!local) { setLoaded(false); setError(""); return; }
    const controller = new AbortController();
    setLoading(true);
    setLoaded(false);
    setError("");
    fetch(`${API}/api/profile`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        if (!response.ok) {
          if (response.status === 404) throw new Error("The current Python API does not have /api/profile. Restart the updated api_local.py.");
          throw new Error(`Profile API returned HTTP ${response.status}.`);
        }
        return response.json() as Promise<{ profile?: Profile }>;
      })
      .then(result => {
        if (controller.signal.aborted) return;
        if (!result.profile) throw new Error("Profile API returned no profile data.");
        setProfile(result.profile);
        setLoaded(true);
        setDirty(false);
        setSavedMessage("");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        const explanation = reason instanceof Error ? reason.message : "Unknown error";
        setError(`Cannot load your profile. ${explanation} Check http://127.0.0.1:8765/api/profile and restart the Python API if needed.`);
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [local, retry]);

  function change(update: (current: Profile) => Profile) {
    if (!editable) return;
    setProfile(update);
    setDirty(true);
    setSavedMessage("");
    setError("");
  }
  const personal = (key: keyof Personal, value: string) => change(prev => ({ ...prev, personal: { ...prev.personal, [key]: value } }));
  const skills = (key: keyof Skills, value: string) => change(prev => ({ ...prev, skills: { ...prev.skills, [key]: value } }));
  const education = (id: string, key: keyof Education, value: string) => change(prev => ({ ...prev, education: prev.education.map(item => item.id === id ? { ...item, [key]: value } : item) }));
  const experience = (group: "projects" | "work" | "research" | "leadership", id: string, key: keyof Experience, value: string) => change(prev => ({ ...prev, [group]: prev[group].map(item => item.id === id ? { ...item, [key]: value } : item) }));

  async function save() {
    if (!canSave) return;
    setSaving(true);
    setError("");
    setSavedMessage("");
    try {
      const response = await fetch(`${API}/api/profile`, {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json", "X-Job-Agent-Action": "local-user-approved" },
        body: JSON.stringify({ profile }),
      });
      const result = await response.json() as { profile?: Profile; error?: string };
      if (!response.ok || !result.profile) throw new Error(result.error || `HTTP ${response.status}`);
      setProfile(result.profile);
      setDirty(false);
      setSavedMessage("Your profile was saved to this computer.");
    } catch (reason) {
      setError(`Save failed: ${reason instanceof Error ? reason.message : "Unknown error"}`);
    } finally { setSaving(false); }
  }

  function countFor(group: Section) {
    if (group === "personal" || group === "skills") return null;
    return profile[group].length;
  }

  return <div className="product-profile-workspace">
    <section className="panel product-profile-connection" aria-labelledby="profile-account-heading">
      <div className="product-profile-connection-head">
        <div>
          <span className="product-small-heading">ACCOUNT & INTEGRATIONS</span>
          <h3 id="profile-account-heading">Google account & Gmail</h3>
          <p>Signing in and granting email access are separate permissions. Connect them when secure cloud authentication is ready.</p>
        </div>
        <span className="neutral-chip">CLOUD SETUP PENDING</span>
      </div>
      <div className="product-connection-steps" aria-label="Planned onboarding steps">
        <div className="product-connection-step"><span>01</span><div><strong>Sign in with Google</strong><small>Identity only</small></div></div>
        <div className="product-connection-step"><span>02</span><div><strong>Connect Gmail</strong><small>Separate email permission</small></div></div>
        <div className="product-connection-step"><span>03</span><div><strong>Complete profile</strong><small>Career details and skills</small></div></div>
      </div>
      <div className="product-quick-buttons">
        <button type="button" className="secondary-button" disabled title="Cloud Google login is not implemented yet">Google sign-in · Coming soon</button>
        <button type="button" className="secondary-button" disabled title="Requires secure Gmail OAuth setup">Connect Gmail · Coming soon</button>
      </div>
    </section>

    <div className={`product-profile-status ${local ? "is-local" : "is-demo"}`} role="status">
      <span className="product-status-dot" aria-hidden="true" />
      <div>
        <strong>{local ? "Your data stays on this computer" : "Read-only demo mode"}</strong>
        <p>{local ? "Profile entries are saved in profile_data.json. This is separate from the older profile.txt used by the resume generator." : "The public demo does not accept or save personal information."}</p>
      </div>
    </div>

    <div className="product-profile-layout">
      <nav className="panel product-profile-menu" aria-label="Profile sections">
        <div className="product-menu-heading">PROFILE SECTIONS</div>
        {TABS.map(item => <button key={item.id} type="button" className={section === item.id ? "active" : ""} onClick={() => setSection(item.id)} aria-current={section === item.id ? "page" : undefined}>
          <span className="product-menu-index">{item.icon}</span>
          <span className="product-menu-label">{item.label}</span>
          {countFor(item.id) !== null && <span className="product-menu-count">{countFor(item.id)}</span>}
          <span className="product-menu-chevron" aria-hidden="true">›</span>
        </button>)}
        <p className="product-menu-tip">Save details once, then reuse them for matching and tailored resumes.</p>
      </nav>

      <section className="panel product-profile-body" aria-labelledby="profile-section-heading">
        <header className="product-profile-body-head">
          <div>
            <div className="product-small-heading">MY PROFILE / {tab.icon}</div>
            <h2 id="profile-section-heading">{tab.label}</h2>
            <p className="product-profile-intro">{tab.subtitle}. Enter only information you can verify.</p>
          </div>
          {countFor(section) !== null && <span className="product-entry-count">{countFor(section)} entries</span>}
        </header>
        {!local && <div className="product-info-banner">Connect the local Python API to edit your profile. The online version remains a preview.</div>}
        {loading && <div className="product-info-banner">Loading profile…</div>}
        {error && !loaded && <div className="product-error-banner" role="alert">
          <span>{error}</span>
          <button className="secondary-button" type="button" onClick={() => setRetry(n => n+1)}>Retry</button>
        </div>}
        <div className="product-profile-form">
          {section === "personal" && <div className="product-profile-fields">
            {([ ["fullName", "Full name"], ["email", "Email"], ["phone", "Phone"], ["location", "City / Location"], ["linkedin", "LinkedIn URL"], ["github", "GitHub URL"], ["website", "Website / Portfolio"] ] as [keyof Personal,string][]).map(([key,label]) => field(label,profile.personal[key], value => personal(key,value),!editable))}
          </div>}
          {section === "education" && <>
            {profile.education.length === 0 && <div className="product-profile-empty">No education entries yet. Add your university, degree, major, GPA and coursework.</div>}
            {profile.education.map((item,i) => <div className="product-profile-record" key={item.id}>
              <div className="product-profile-record-head"><strong>Education #{i+1}</strong><button type="button" disabled={!editable} onClick={() => change(prev => ({ ...prev, education: prev.education.filter(row => row.id !== item.id) }))}>Remove</button></div>
              <div className="product-profile-fields">
                {([ ["school","University / School"], ["degree","Degree"], ["major","Major(s)"], ["gpa","GPA"], ["startDate","Start date"], ["endDate","Graduation / End date"] ] as [keyof Education,string][]).map(([key,label]) => field(label,item[key],value => education(item.id,key,value),!editable))}
                {field("Relevant coursework",item.courses,value => education(item.id,"courses",value),!editable,{full:true,multiline:true,placeholder:"Separate courses with commas or line breaks"})}
              </div>
            </div>)}
            <button type="button" className="product-add-button" disabled={!editable || profile.education.length>=20} onClick={() => change(prev => ({ ...prev, education: [...prev.education,blankEducation()] }))}>＋ Add education</button>
          </>}
          {(["projects","work","research","leadership"] as Section[]).includes(section) && (() => {
            const group = section as "projects" | "work" | "research" | "leadership";
            const labels = EXPERIENCE_LABELS[group];
            return <>
              {profile[group].length === 0 && <div className="product-profile-empty">No entries yet. Add an experience and describe your actual contribution.</div>}
              {profile[group].map((item,i) => <div className="product-profile-record" key={item.id}>
                <div className="product-profile-record-head"><strong>{tab.label} #{i+1}</strong><button type="button" disabled={!editable} onClick={() => change(prev => ({ ...prev, [group]: prev[group].filter(row => row.id !== item.id) }))}>Remove</button></div>
                <div className="product-profile-fields">
                  {([ ["title",labels.title], ["organization",labels.organization], ["role",labels.role]] as [keyof Experience,string][]).map(([key,label]) => field(label,item[key],value => experience(group,item.id,key,value),!editable))}
                  {field("Start date",item.startDate ?? "",value => experience(group,item.id,"startDate",value),!editable,{placeholder:"e.g., 08/2025 (MM/YYYY)"})}
                  {field("End date",item.endDate ?? "",value => experience(group,item.id,"endDate",value),!editable,{placeholder:"e.g., 05/2029 (MM/YYYY) or Present"})}
                  {item.period?.trim() ? field("Earlier saved period (optional)",item.period,value => experience(group,item.id,"period",value),!editable) : null}
                  {field("Location (optional)",item.location,value => experience(group,item.id,"location",value),!editable)}
                  {field("Responsibilities, contributions & outcomes",item.description,value => experience(group,item.id,"description",value),!editable,{full:true,multiline:true,placeholder:"Use one line per achievement. Include measurable results when accurate."})}
                </div>
              </div>)}
              <button type="button" className="product-add-button" disabled={!editable || profile[group].length>=30} onClick={() => change(prev => ({ ...prev, [group]: [...prev[group],blankExperience()] }))}>＋ Add {tab.label.toLowerCase()} entry</button>
            </>;
          })()}
          {section === "skills" && <div className="product-profile-fields">
            {([ ["languages","Programming languages"], ["frameworks","Frameworks & libraries"], ["tools","Developer tools & platforms"], ["other","Other technical skills"] ] as [keyof Skills,string][]).map(([key,label]) => field(label,profile.skills[key],value => skills(key,value),!editable,{full:true,multiline:true,placeholder:"Separate items with commas or line breaks"}))}
          </div>}
          <div className="product-profile-actions">
            <div className="product-profile-save-state" aria-live="polite">
              {error && loaded ? <span className="product-profile-error">{error}</span> : savedMessage ? <span className="product-profile-success">✓ {savedMessage}</span> : dirty ? <span>● Unsaved changes</span> : <span>{loaded ? "All changes saved" : "No changes to save"}</span>}
            </div>
            <button className="primary-button" type="button" onClick={save} disabled={!canSave}>{saving ? "Saving…" : "Save profile"}</button>
          </div>
        </div>
      </section>
    </div>
  </div>;
}
