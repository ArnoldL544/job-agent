"use client";

import { useEffect, useState } from "react";
import { ACTION_HEADERS, DataMode, DraftKind, Icon, Job, LOCAL_API, LocalTask, PostingLink, ResumePreview, ResumeRecord, StartTask, TaskMonitor } from "../../lib/shared";

type Props = {
  dataMode: DataMode; jobs: Job[]; resumes: ResumeRecord[]; resumesError: string;
  draftJobId: string; setDraftJobId: (id: string) => void;
  task: LocalTask | null; taskError: string; taskBusy: boolean; startTask: StartTask; onRefresh: () => void;
};
type Group = { jobId: string; company: string; title: string; versions: ResumeRecord[] };
type SaveConfig = { folder: string; canBrowse: boolean };
type Loaded = { key: string; preview: ResumePreview | null; error: string };

const KIND_LABEL: Record<DraftKind, string> = { tailored: "Tailored from master", profile: "From My Profile", uploaded: "Your edit" };

function groupDrafts(resumes: ResumeRecord[]): Group[] {
  const map = new Map<string, Group>();
  for (const r of [...resumes].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))) {
    const g = map.get(r.jobId) ?? { jobId: r.jobId, company: r.company, title: r.jobTitle, versions: [] };
    g.versions.push(r);
    map.set(r.jobId, g);
  }
  return [...map.values()];
}

export default function ResumesPage(props: Props) {
  const { dataMode, jobs, resumes, resumesError, draftJobId, setDraftJobId, task, taskError, taskBusy, startTask, onRefresh } = props;
  const [engine, setEngine] = useState<"chunk" | "profile">("chunk");
  const [profileSource, setProfileSource] = useState<"json" | "legacy">("json");
  const [allowRisk, setAllowRisk] = useState(false);
  const [forceDraft, setForceDraft] = useState(false);
  const [confirmPaid, setConfirmPaid] = useState(false);
  const [activeJob, setActiveJob] = useState("");
  const [activeVersion, setActiveVersion] = useState("");
  const [saveConfig, setSaveConfig] = useState<SaveConfig>({ folder: "", canBrowse: false });
  useEffect(() => {
    if (dataMode !== "local") return;
    const controller = new AbortController();
    fetch(`${LOCAL_API}/api/save-folder`, { signal: controller.signal, cache: "no-store" })
      .then(r => r.ok ? r.json() as Promise<SaveConfig> : Promise.reject())
      .then(setSaveConfig)
      .catch(() => { /* Falls back to browser downloads. */ });
    return () => controller.abort();
  }, [dataMode]);

  const groups = groupDrafts(resumes);
  const group = groups.find(g => g.jobId === activeJob) ?? groups.find(g => g.jobId === draftJobId) ?? groups[0] ?? null;
  const version = group ? group.versions.find(v => v.id === activeVersion) ?? group.versions[0] : null;
  const targetId = draftJobId || jobs[0]?.id || "";

  if (dataMode !== "local") return <section className="panel stage5-controls">
    <div className="panel-title">Resume drafts need the local app</div>
    <p className="stage4-muted">Tailored resumes are generated from the master resume on your computer. Start the app with start.bat, then open http://localhost:3000.</p>
  </section>;

  function generate() {
    startTask({ action: "resume", jobId: targetId, confirmPaid: true, allowRisk, force: forceDraft, engine, profileSource });
    setConfirmPaid(false);
    setActiveJob(targetId);
    setActiveVersion("");
  }

  return <div className="studio">
    <section className="panel studio-generate">
      <div className="panel-title">Tailor a resume</div>
      <label className="stage5-field">Job
        <select value={targetId} onChange={e => { setDraftJobId(e.target.value); setConfirmPaid(false); setAllowRisk(false); }}>
          {jobs.map(job => <option key={job.id} value={job.id}>{job.company} — {job.title} ({job.score}/100)</option>)}
        </select>
      </label>
      <p className="stage4-muted">{engine === "chunk"
        ? "Built from your master resume: picks the bullets that fit this job, rewrites them using only facts already in your resume, and keeps it to one page."
        : "Older method: writes a new draft from the My Profile form."}</p>
      <details className="studio-options"><summary>Options</summary>
        <label className="stage5-check"><input type="checkbox" checked={allowRisk} onChange={e => setAllowRisk(e.target.checked)}/> Draft even if screening flagged eligibility or deadline issues</label>
        <label className="stage5-check"><input type="checkbox" checked={forceDraft} onChange={e => setForceDraft(e.target.checked)}/> Regenerate even if an identical draft exists</label>
        <label className="stage5-check"><input type="checkbox" checked={engine === "profile"} onChange={e => setEngine(e.target.checked ? "profile" : "chunk")}/> Use the older My Profile writer instead of the master resume</label>
        {engine === "profile" && <label className="stage5-field">Profile source
          <select value={profileSource} onChange={e => setProfileSource(e.target.value as "json" | "legacy")}><option value="json">My Profile form</option><option value="legacy">Legacy profile.txt</option></select>
        </label>}
      </details>
      <div className="studio-confirm">
        <label className="stage5-check"><input type="checkbox" checked={confirmPaid} onChange={e => setConfirmPaid(e.target.checked)}/> I approve one paid OpenAI call for this job.</label>
        <button className="primary-button" disabled={!confirmPaid || taskBusy || !targetId} onClick={generate}><Icon name="sparkles" size={16}/>{taskBusy ? "A task is running…" : "Generate draft"}</button>
      </div>
    </section>

    <TaskMonitor task={task?.action === "resume" ? task : null} error={taskError} onDone={onRefresh}/>
    {resumesError && <div className="panel stage4-warning">{resumesError}</div>}

    {!group ? <div className="panel stage4-empty"><Icon name="file" size={30}/><h3>No drafts yet</h3><p>Pick a job above and generate your first tailored resume.</p></div> :
      <div className="studio-grid">
        <nav className="panel studio-list" aria-label="Drafts by job">
          <div className="panel-title">Drafts by job</div>
          {groups.map(g => {
            const job = jobs.find(j => j.id === g.jobId);
            // A link cannot sit inside the <button>, so it is a sibling placed over the item's corner.
            return <div key={g.jobId} className="studio-item-wrap">
              <button className={`studio-item ${g.jobId === group.jobId ? "active" : ""} ${job?.url ? "has-apply" : ""}`} onClick={() => { setActiveJob(g.jobId); setActiveVersion(""); }}>
                <strong>{g.title}</strong>
                <span>{g.company}</span>
                <small>{g.versions.length} version{g.versions.length > 1 ? "s" : ""} · {new Date(g.versions[0].updatedAt).toLocaleDateString()}</small>
              </button>
              {job && <PostingLink job={job}/>}
            </div>;
          })}
        </nav>
        {version && <DraftView key={version.id} group={group} version={version} onVersion={setActiveVersion} onUploaded={onRefresh}
          saveConfig={saveConfig} onSaveConfig={setSaveConfig}/>}
      </div>}
  </div>;
}

function DraftView({ group, version, onVersion, onUploaded, saveConfig, onSaveConfig }: {
  group: Group; version: ResumeRecord; onVersion: (id: string) => void; onUploaded: () => void;
  saveConfig: SaveConfig; onSaveConfig: (c: SaveConfig) => void;
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = version.id;
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${LOCAL_API}/api/resumes/${version.jobId}/${version.index}/preview`, { signal: controller.signal, cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error(); return r.json() as Promise<ResumePreview>; })
      .then(preview => setLoaded({ key, preview, error: "" }))
      .catch(() => { if (!controller.signal.aborted) setLoaded({ key, preview: null, error: "Preview unavailable. You can still download the Word file." }); });
    return () => controller.abort();
  }, [key, version.jobId, version.index]);
  const current = loaded?.key === key ? loaded : null;
  const summary = current?.preview?.summary;

  return <section className="panel studio-view">
    <div className="studio-view-head">
      <div><div className="panel-title">{group.title}</div><div className="panel-subtitle">{group.company} · {group.jobId}</div></div>
      <SaveControls key={saveConfig.folder} version={version} config={saveConfig} onConfig={onSaveConfig}/>
    </div>
    {group.versions.length > 1 && <div className="version-tabs" role="tablist">
      {group.versions.map((v, i) => <button key={v.id} role="tab" aria-selected={v.id === version.id} className={v.id === version.id ? "active" : ""} onClick={() => onVersion(v.id)}>
        {i === 0 ? "Latest" : new Date(v.updatedAt).toLocaleDateString()}<small>{KIND_LABEL[v.kind ?? "profile"]}</small>
      </button>)}
    </div>}
    <p className="stage4-muted studio-meta">{KIND_LABEL[version.kind ?? "profile"]} · {new Date(version.updatedAt).toLocaleString()}{summary?.model ? ` · ${summary.model}` : ""}{summary?.pageCount ? ` · ${summary.pageCount} page` : ""}{version.downloadName ? ` · downloads as ${version.downloadName}` : ""}</p>

    {!current ? <p className="stage4-muted">Loading…</p> : current.error ? <p className="stage4-warning">{current.error}</p> : summary ? <>
      {summary.focus.length > 0 && <div className="studio-block"><h3>What this job values</h3><div className="focus-chips">{summary.focus.map(f => <span key={f}>{f}</span>)}</div></div>}
      <div className="studio-block"><h3>Make your master resume stronger</h3>
        {summary.questions.length ? <ul className="question-list">{summary.questions.map(q => <li key={q.question}><strong>{q.question}</strong><span>{q.bullet}</span></li>)}</ul>
          : <p className="stage4-muted">No questions this time.</p>}
        <p className="stage4-muted">Add true answers to your master resume; later drafts will use them. All open questions are collected on the Master Resume page.</p>
      </div>
      <div className="studio-block"><h3>What changed</h3>
        {summary.changes.length ? summary.changes.map((c, i) => <div className="change-item" key={i}>
          <div className="change-meta">{c.section} · {c.kind === "merged" ? "merged 2 bullets" : "rewritten"}</div>
          {c.before.map((b, j) => <p className="change-before" key={j}>{b}</p>)}
          <p className="change-after">{c.after}</p>
        </div>) : <p className="stage4-muted">Bullets were selected and ordered for this job; no sentences were rewritten.</p>}
      </div>
      {summary.skills.length > 0 && <div className="studio-block"><h3>Skills reordered</h3>{summary.skills.map(s => <p className="stage4-muted" key={s}>{s}</p>)}</div>}
      <details className="studio-raw"><summary>Full review report</summary><pre className="stage4-document">{current.preview?.text}</pre></details>
    </> : <pre className="stage4-document">{current.preview?.text}</pre>}

    <UploadEdited jobId={group.jobId} onUploaded={onUploaded}/>
  </section>;
}

// Folder box + Browse… left of the download button. With a folder set, the API
// copies the draft there as "<Job title>_resume.docx"; empty = browser download.
function SaveControls({ version, config, onConfig }: { version: ResumeRecord; config: SaveConfig; onConfig: (c: SaveConfig) => void }) {
  const [text, setText] = useState(config.folder);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const post = async (path: string, body: object) => {
    const res = await fetch(`${LOCAL_API}${path}`, { method: "POST", headers: ACTION_HEADERS, body: JSON.stringify(body) });
    const data = await res.json() as { folder?: string; error?: string; saved?: string; cancelled?: boolean };
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  };
  async function commit() {
    if (text.trim() === config.folder) return;
    setMessage(null);
    try {
      const data = await post("/api/save-folder", { folder: text });
      onConfig({ ...config, folder: data.folder ?? "" });
    } catch (e) { setMessage({ ok: false, text: e instanceof Error ? e.message : "Could not set the folder" }); }
  }
  async function browse() {
    setBusy(true); setMessage({ ok: true, text: "Choose a folder in the window that opened…" });
    try {
      const data = await post("/api/save-folder/browse", {});
      setMessage(null);
      if (!data.cancelled) onConfig({ ...config, folder: data.folder ?? "" });
    } catch (e) { setMessage({ ok: false, text: e instanceof Error ? e.message : "Could not open the folder picker" }); }
    finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setMessage(null);
    try {
      const data = await post(`/api/resumes/${version.jobId}/${version.index}/save`, {});
      setMessage({ ok: true, text: `Saved to ${data.saved}` });
    } catch (e) { setMessage({ ok: false, text: e instanceof Error ? e.message : "Save failed" }); }
    finally { setBusy(false); }
  }
  async function openFolder() {
    try { await post("/api/save-folder/open", {}); } catch { /* the path is shown anyway */ }
  }
  return <div className="save-controls">
    <div className="save-row">
      <label className="save-folder" title="Folder where the Word file is saved. Leave empty to use your browser's Downloads folder.">
        <span>Save to</span>
        <input value={text} placeholder="Browser Downloads folder" onChange={e => setText(e.target.value)} onBlur={commit}
          onKeyDown={e => { if (e.key === "Enter") e.currentTarget.blur(); }} spellCheck={false}/>
      </label>
      {config.canBrowse && <button className="secondary-button" disabled={busy} onClick={browse}>Browse…</button>}
      {config.folder
        ? <button className="primary-button" disabled={busy} onClick={save} title={version.downloadName ? `Saves as ${version.downloadName}` : undefined}><Icon name="download" size={17}/> Save Word</button>
        : <a className="primary-button" href={`${LOCAL_API}/api/resumes/${version.jobId}/${version.index}/download`} title={version.downloadName ? `Downloads as ${version.downloadName}` : undefined}><Icon name="download" size={17}/> Download Word</a>}
    </div>
    {message && <p className={message.ok ? "save-message" : "stage4-warning save-message"}>{message.text}
      {message.ok && message.text.startsWith("Saved to") && <button className="quiet-link" onClick={openFolder}>Open folder</button>}</p>}
  </div>;
}

function UploadEdited({ jobId, onUploaded }: { jobId: string; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function upload() {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".docx") || file.size > 15_000_000) { setError("Choose a .docx smaller than 15 MB"); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const res = await fetch(`${LOCAL_API}/api/resumes/${jobId}/upload`, { method: "POST", headers: { "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "X-Job-Agent-Action": "local-user-approved" }, body: file });
      const data = await res.json() as { error?: string; filename?: string };
      if (!res.ok) throw new Error(data.error || `Upload failed (HTTP ${res.status})`);
      setMessage("Saved as a new version."); setFile(null); onUploaded();
    } catch (e) { setError(e instanceof Error ? e.message : "Upload failed"); } finally { setBusy(false); }
  }
  return <details className="studio-upload"><summary>Upload a version you edited in Word</summary>
    <p className="stage4-muted">Saved as a new version for this job; existing files are not changed.</p>
    <div className="studio-upload-row">
      <input type="file" accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={e => setFile(e.target.files?.[0] || null)}/>
      <button className="secondary-button" disabled={!file || busy} onClick={upload}>{busy ? "Uploading…" : "Save version"}</button>
    </div>
    {error && <p className="stage4-warning" role="alert">{error}</p>}
    {message && <p className="ja-extra-success" role="status">{message}</p>}
  </details>;
}
