"use client";

import { useEffect, useMemo, useState } from "react";
import "./agent-extras.css";

const API = "http://127.0.0.1:8765";
const ACTION_HEADERS = { "Content-Type": "application/json", "X-Job-Agent-Action": "local-user-approved" };

type Application = {jobId: string; status: string; deadline: string; note: string; updatedAt: string; saved?: boolean};
type Applications = Record<string, Application>;
type Frequency = "daily" | "weekly";
type Schedule = {enabled:boolean; frequency:Frequency; hour:number; minute:number; weekday:number; maxEmails:number; lastRunDate:string; lastError:string};
type TaskRecord = {id:string; action:string; status:string; startedAt:number; endedAt:number | null; returnCode:number | null; logs:string[]};
const STATUSES = ["Discovered", "Saved", "Applied", "Interview", "Offer", "Rejected", "Withdrawn"];
const weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

async function apiPost<T>(path:string, payload:object): Promise<T> {
  const res = await fetch(API + path, {method:"POST", headers: ACTION_HEADERS, body: JSON.stringify(payload)});
  const data = await res.json() as T & {error?: string};
  if (!res.ok) throw new Error(data.error || `API returned HTTP ${res.status}`);
  return data;
}

export function ApplicationTracker({jobId, enabled}:{jobId:string; enabled:boolean}) {
  const [details, setDetails] = useState<Application>({jobId, status:"Discovered", deadline:"", note:"", updatedAt:""});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    fetch(API + "/api/tracker", {signal:controller.signal, cache:"no-store"})
      .then(res => res.ok ? res.json() as Promise<{applications:Applications}> : Promise.reject(new Error(`HTTP ${res.status}`)))
      .then(data => { if (!controller.signal.aborted) setDetails(data.applications?.[jobId] || {jobId,status:"Discovered",deadline:"",note:"",updatedAt:""}); })
      .catch(() => { if (!controller.signal.aborted) setError("Could not read application tracker. Restart the updated Python API."); });
    return () => controller.abort();
  }, [jobId, enabled]);
  if (!enabled) return null;
  async function save() {
    setBusy(true); setSaved(""); setError("");
    try {
      const result = await apiPost<{application:Application}>("/api/tracker", details);
      setDetails(result.application); setSaved("Saved privately on this computer.");
      window.dispatchEvent(new Event("job-agent-tracker-updated"));
    } catch (e) { setError(e instanceof Error ? e.message : "Save failed"); }
    finally { setBusy(false); }
  }
  return <section className="panel ja-extra-card">
    <div className="ja-extra-heading"><h3>Application tracker</h3><span className="ja-extra-caption">Private · Never applies automatically</span></div>
    <div className="ja-extra-grid">
      <label>Application status<select value={details.status} onChange={e=>setDetails(v=>({...v,status:e.target.value}))}>{STATUSES.map(x=><option key={x}>{x}</option>)}</select></label>
      <label>Application deadline<input type="date" value={details.deadline} onChange={e=>setDetails(v=>({...v,deadline:e.target.value}))}/></label>
    </div>
    <label className="ja-extra-wide">Private notes<textarea rows={3} maxLength={4000} value={details.note} onChange={e=>setDetails(v=>({...v,note:e.target.value}))} placeholder="Interview date, next follow-up, recruiter notes..."/></label>
    {error && <p role="alert" className="ja-extra-error">{error}</p>}
    {saved && <p role="status" className="ja-extra-success">{saved}</p>}
    <button className="primary-button" onClick={save} disabled={busy}>{busy ? "Saving..." : "Save application"}</button>
  </section>;
}

export function DeadlineOverview({enabled}:{enabled:boolean}) {
  const [all, setAll] = useState<Applications>({});
  const [error, setError] = useState("");
  // Updated only after an effect fetch completes; never read the clock while rendering.
  const [todayUtcDay, setTodayUtcDay] = useState<number | null>(null);
  useEffect(()=>{
    if (!enabled) return;
    let active=true;
    const refresh=()=>fetch(API + "/api/tracker", {cache:"no-store"})
      .then(x=>x.ok?x.json() as Promise<{applications:Applications}>:Promise.reject())
      .then(x=>{if(active){
        setAll(x.applications || {});
        const now = new Date();
        setTodayUtcDay(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
        setError("");
      }})
      .catch(()=>{if(active)setError("Tracker unavailable");});
    void refresh();
    window.addEventListener("job-agent-tracker-updated",refresh);
    return()=>{active=false;window.removeEventListener("job-agent-tracker-updated",refresh);};
  },[enabled]);
  const due = useMemo(()=>{
    if (todayUtcDay === null) return [];
    return Object.values(all).flatMap(x=>{
      if (!x.deadline || ["Applied","Interview","Offer","Rejected","Withdrawn"].includes(x.status)) return [];
      const [y,m,d]=x.deadline.split("-").map(Number);
      // Compare calendar dates in UTC to avoid DST-related off-by-one errors.
      const days=Math.round((Date.UTC(y,m-1,d)-todayUtcDay)/86400000);
      return days<=7 ? [{...x,days}] : [];
    }).sort((a,b)=>a.days-b.days);
  },[all,todayUtcDay]);
  if(!enabled) return null;
  const open = due.filter(x=>x.days>=0);
  return <section className="panel ja-extra-card ja-deadlines">
    <div className="ja-extra-heading"><h3>Deadlines & applications</h3></div>
    <p className="ja-extra-caption">{Object.values(all).filter(x=>x.status!=="Discovered").length} tracked applications · {open.length} approaching in 7 days</p>
    {error && <p className="ja-extra-error">{error}</p>}
    {due.length===0?<p className="ja-extra-caption">No upcoming deadlines entered. Open a job to set one.</p>:
      <div className="ja-deadline-list">{due.slice(0,6).map(x=><div key={x.jobId}><strong>Job {x.jobId}</strong><span className={x.days<0?"ja-extra-error":""}>{x.days<0?`Overdue ${Math.abs(x.days)}d`:x.days===0?"Due today":`Due in ${x.days}d`} · {x.deadline}</span></div>)}</div>}
  </section>;
}

export function SchedulePanel({enabled}:{enabled:boolean}) {
  const [schedule,setSchedule]=useState<Schedule>({enabled:false,frequency:"weekly",hour:9,minute:0,weekday:0,maxEmails:20,lastRunDate:"",lastError:""});
  const [approved,setApproved]=useState(false);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  useEffect(()=>{
    if(!enabled)return;
    fetch(API+"/api/schedule",{cache:"no-store"}).then(x=>x.ok?x.json() as Promise<{schedule:Schedule}>:Promise.reject()).then(x=>setSchedule(x.schedule)).catch(()=>setError("Schedule API unavailable"));
  },[enabled]);
  if(!enabled)return null;
  async function submit(enable:boolean){
    setSaving(true);setMessage("");setError("");
    try {
      const value=await apiPost<{schedule:Schedule}>("/api/schedule",{...schedule,enabled:enable,confirmRead:enable&&approved});
      setSchedule(value.schedule);setApproved(false);setMessage(enable?"Schedule enabled while the local Python API is running.":"Schedule disabled.");
    }catch(e){setError(e instanceof Error?e.message:"Save failed");}
    finally{setSaving(false);}
  }
  return <section className="panel ja-extra-card">
    <div className="ja-extra-heading"><h3>Scheduled Handshake discovery</h3><span className="ja-extra-caption">{schedule.enabled?"Enabled (local only)":"Disabled by default"}</span></div>
    <p className="ja-extra-caption">Runs Gmail → JD → screening at your selected local time <strong>only while api_local.py stays running</strong>. No cloud scheduler has been enabled.</p>
    <div className="ja-extra-grid">
      <label>Frequency<select value={schedule.frequency} onChange={e=>setSchedule(s=>({...s,frequency:e.target.value as Frequency}))}><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>
      {schedule.frequency==="weekly"&&<label>Day<select value={schedule.weekday} onChange={e=>setSchedule(s=>({...s,weekday:Number(e.target.value)}))}>{weekdays.map((day,i)=><option key={day} value={i}>{day}</option>)}</select></label>}
      <label>Hour (0–23)<input type="number" min={0} max={23} value={schedule.hour} onChange={e=>setSchedule(s=>({...s,hour:Number(e.target.value)}))}/></label>
      <label>Minute<input type="number" min={0} max={59} value={schedule.minute} onChange={e=>setSchedule(s=>({...s,minute:Number(e.target.value)}))}/></label>
      <label>Max emails<input type="number" min={1} max={50} value={schedule.maxEmails} onChange={e=>setSchedule(s=>({...s,maxEmails:Number(e.target.value)}))}/></label>
    </div>
    <label className="ja-checkbox"><input type="checkbox" checked={approved} onChange={e=>setApproved(e.target.checked)}/> I explicitly authorize recurring Gmail reads at this schedule. I can disable this at any time.</label>
    {schedule.lastRunDate && <p className="ja-extra-caption">Last scheduled start: {schedule.lastRunDate}</p>}
    {schedule.lastError && <p className="ja-extra-error">Last schedule error: {schedule.lastError}</p>}
    {error&&<p className="ja-extra-error">{error}</p>}{message&&<p className="ja-extra-success">{message}</p>}
    <div className="ja-extra-actions"><button className="primary-button" disabled={saving||!approved} onClick={()=>submit(true)}>Enable schedule</button><button className="secondary-button" disabled={saving||!schedule.enabled} onClick={()=>submit(false)}>Disable schedule</button></div>
  </section>;
}

export function TaskHistory({enabled}:{enabled:boolean}) {
  const [rows,setRows] = useState<TaskRecord[]>([]);
  const [error,setError] = useState("");
  const [open,setOpen] = useState("");
  useEffect(()=>{if(!enabled)return;
    fetch(API+"/api/tasks/history",{cache:"no-store"}).then(x=>x.ok?x.json() as Promise<{history:TaskRecord[]}>:Promise.reject())
      .then(x=>setRows(Array.isArray(x.history)?x.history:[])).catch(()=>setError("Cannot read task history"));
  },[enabled]);
  if(!enabled)return null;
  return <section className="panel ja-extra-card"><div className="ja-extra-heading"><h3>Recent Agent runs</h3><span className="ja-extra-caption">Last 30 completed local tasks</span></div>
    {error&&<p className="ja-extra-error">{error}</p>}
    {!rows.length?<p className="ja-extra-caption">No completed run history yet.</p>:rows.slice(0,10).map(task=><div key={task.id} className="ja-history-row"><button className="ja-history-head" onClick={()=>setOpen(x=>x===task.id?"":task.id)}><span><strong>{task.action}</strong> · {new Date(task.startedAt*1000).toLocaleString()}</span><span>{task.status} {open===task.id?"−":"+"}</span></button>{open===task.id&&<pre>{task.logs?.join("\n")||"No log output"}</pre>}</div>)}
  </section>;
}
