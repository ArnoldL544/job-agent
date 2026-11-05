"use client";

import { useState } from "react";
import { SchedulePanel, TaskHistory } from "../AgentExtras";
import { DataMode, Icon, LocalTask, StartTask, TaskMonitor } from "../../lib/shared";

type Props = { dataMode: DataMode; task: LocalTask | null; taskError: string; taskBusy: boolean; startTask: StartTask; onTaskDone: () => void };

export default function FindJobsPage({ dataMode, task, taskError, taskBusy, startTask, onTaskDone }: Props) {
  const [maxEmails, setMaxEmails] = useState(20);
  const [confirmRead, setConfirmRead] = useState(false);
  if (dataMode !== "local") return <section className="panel stage5-controls">
    <div className="panel-title">Finding jobs needs the local app</div>
    <p className="stage4-muted">Reading Gmail and Handshake runs on your own computer. Start it with start.bat, then open http://localhost:3000.</p>
  </section>;
  const validCount = maxEmails >= 1 && maxEmails <= 50;
  return <div className="stage5-automation">
    <section className="panel stage5-controls">
      <div className="panel-title">Find new jobs from Gmail</div>
      <p className="stage4-muted">Reads your Handshake notification emails, opens each job to save its description, then scores it. A browser window may open; nothing is applied to automatically.</p>
      <label className="stage5-field">Emails to check (1–50)
        <input type="number" min="1" max="50" value={maxEmails} onChange={e => setMaxEmails(Number(e.target.value))}/>
      </label>
      <label className="stage5-check"><input type="checkbox" checked={confirmRead} onChange={e => setConfirmRead(e.target.checked)}/> I approve reading my Gmail for Handshake job notifications.</label>
      <button className="primary-button" disabled={taskBusy || !confirmRead || !validCount} onClick={() => { startTask({ action: "import", maxEmails, confirmRead: true }); setConfirmRead(false); }}>
        <Icon name="mail" size={16}/> {taskBusy ? "A task is running…" : "Find new jobs"}
      </button>
    </section>
    <TaskMonitor task={task} error={taskError} onDone={onTaskDone}/>
    <section className="panel stage5-controls">
      <div className="panel-title">Other tools</div>
      <p className="stage4-muted">Use these when jobs are already imported.</p>
      <div className="stage5-actions">
        <button className="secondary-button" disabled={taskBusy} onClick={() => startTask({ action: "extract" })}>Extract missing job descriptions</button>
        <button className="secondary-button" disabled={taskBusy} onClick={() => startTask({ action: "screen" })}>Rescore saved jobs</button>
      </div>
    </section>
    <SchedulePanel enabled/>
    <TaskHistory enabled/>
  </div>;
}
