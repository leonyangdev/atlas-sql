"use client";

import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const categories = ["wrong_table", "wrong_column", "wrong_join", "wrong_value", "wrong_metric", "wrong_time", "wrong_aggregation", "syntax_error", "undetermined"];

interface Trace {
  trace_id: string; question: string; identity: string; status: string;
  error_code: string | null; model_version: string; prompt_version: string | null;
  total_tokens: number; execution_ms: number | null; failure_category: string | null;
  created_at: string; sql?: string | null; error_message?: string | null;
  data_version?: string; schema_version?: string; prompt_hash?: string | null;
  referenced_tables?: string[]; referenced_columns?: string[];
  stages?: Array<{name: string; status: string; duration_ms: number | null}>;
  review_note?: string | null;
}

export default function TracesPage() {
  const [token, setToken] = useState("");
  const [traces, setTraces] = useState<Trace[]>([]);
  const [selected, setSelected] = useState<Trace | null>(null);
  const [category, setCategory] = useState("undetermined");
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");

  async function call(path: string, init?: RequestInit) {
    const response = await fetch(`${API}${path}`, { ...init, headers: {"Content-Type": "application/json", "x-admin-token": token, ...init?.headers} });
    if (!response.ok) throw new Error(`API ${response.status}`);
    return response.json();
  }
  async function load() {
    try { setTraces(await call("/api/v1/admin/traces")); setMessage(""); }
    catch (error) { setMessage(error instanceof Error ? error.message : "加载失败"); }
  }
  async function open(id: string) {
    try { const value = await call(`/api/v1/admin/traces/${id}`); setSelected(value); setCategory(value.failure_category ?? "undetermined"); setNote(value.review_note ?? ""); }
    catch (error) { setMessage(error instanceof Error ? error.message : "加载失败"); }
  }
  async function save() {
    if (!selected) return;
    try {
      const value = await call(`/api/v1/admin/traces/${selected.trace_id}/review`, {method: "PATCH", body: JSON.stringify({failure_category: category, note})});
      setSelected(value); setMessage("复核结果已保存"); await load();
    } catch (error) { setMessage(error instanceof Error ? error.message : "保存失败"); }
  }

  return <main>
    <p className="eyebrow"><a href="/">ATLASSQL / ADMIN</a></p><h1>查询 Trace</h1>
    <div className="action-panel"><div className="token-row"><label>管理员令牌</label><input className="token-input" type="password" value={token} onChange={(e) => setToken(e.target.value)} /><button className="btn btn-primary" onClick={() => void load()}>加载</button></div>{message && <p className="status-msg">{message}</p>}</div>
    <div className="table-scroll"><table className="data-table"><thead><tr><th>时间</th><th>问题</th><th>状态</th><th>阶段</th><th>Token</th></tr></thead><tbody>{traces.map((trace) => <tr key={trace.trace_id} onClick={() => void open(trace.trace_id)}><td>{new Date(trace.created_at).toLocaleString("zh-CN")}</td><td>{trace.question}</td><td>{trace.status}</td><td>{trace.failure_category ?? trace.error_code ?? "—"}</td><td>{trace.total_tokens}</td></tr>)}</tbody></table></div>
    {selected && <section className="detail-section"><h2>Trace 详情</h2><dl className="info-grid"><dt>Trace ID</dt><dd><code>{selected.trace_id}</code></dd><dt>模型 / Prompt</dt><dd>{selected.model_version} / {selected.prompt_version ?? "—"}</dd><dt>数据版本</dt><dd>{selected.data_version} / {selected.schema_version}</dd><dt>来源表</dt><dd>{selected.referenced_tables?.join("、") || "—"}</dd><dt>错误</dt><dd>{selected.error_message ?? "—"}</dd></dl><pre className="code-hint">{selected.sql ?? "无候选 SQL"}</pre><h2>阶段耗时</h2><div>{selected.stages?.map((stage) => <p key={stage.name}>{stage.name} · {stage.status} · {stage.duration_ms ?? 0} ms</p>)}</div><div className="action-panel"><select value={category} onChange={(e) => setCategory(e.target.value)}>{categories.map((item) => <option key={item}>{item}</option>)}</select><input className="token-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="人工复核说明" /><button className="btn btn-primary" onClick={() => void save()}>保存归因</button></div></section>}
  </main>;
}
