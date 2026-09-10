"use client";

import { FormEvent, useRef, useState } from "react";
import { format } from "sql-formatter";

const EXAMPLE_QUESTIONS = [
  // Sales 域 — 有完整数据
  "各门店的总销售额是多少，按销售额从高到低排列",
  "2026 年上半年每个月的有效订单量是多少",
  "每个区域的有效订单量是多少",
  "各门店 2026 年 Q1 的客单价是多少",
  "退款率最高的 5 个品类是哪些",
  "各品类销售数量排名",
  // 跨域（V3）— 有真实数据支撑
  "查询每个城市的线上销售额（仅线上渠道）",
  "各仓库当前可用库存数量",
  "2026 年各月订单量趋势",
  "退款金额最高的 5 个门店是哪些",
] as const;

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type QueryStatus =
  | "processing"
  | "succeeded"
  | "clarification_required"
  | "rejected"
  | "failed";

interface QueryColumn {
  name: string;
  data_type: string;
}

/** V3 指标定义简要信息，由后端 SemanticRegistry 注入 */
interface MetricDefinitionBrief {
  metric_id: string;
  label: string;
  expression: string;
  required_filters: string[];
  time_role: string;
  warning: string | null;
  time_rule_note: string | null;
}

interface QueryResult {
  question: string;
  session_id: string;
  trace_id: string;
  status: QueryStatus;
  sql: string | null;
  columns: QueryColumn[];
  rows: Array<Array<string | number | boolean | null>>;
  error: { code: string; message: string } | null;
  truncated: boolean;
  execution_ms: number | null;
  summary: string | null;
  referenced_tables: string[];
  referenced_columns: string[];
  metric_definitions: MetricDefinitionBrief[];
}

function sessionId(): string {
  const key = "atlas-query-session";
  const existing = window.localStorage.getItem(key);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.localStorage.setItem(key, created);
  return created;
}

async function requestQuery(question: string): Promise<QueryResult> {
  const response = await fetch(`${API_BASE}/api/v1/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-atlas-identity": "public" },
    body: JSON.stringify({ question, session_id: sessionId() }),
  });
  if (!response.ok) throw new Error(`请求失败（HTTP ${response.status}）`);
  let result = (await response.json()) as QueryResult;

  for (let attempt = 0; result.status === "processing" && attempt < 30; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1_000));
    const polled = await fetch(`${API_BASE}/api/v1/query/${result.trace_id}`, {
      headers: { "x-atlas-identity": "public" },
    });
    if (!polled.ok) throw new Error(`状态查询失败（HTTP ${polled.status}）`);
    result = (await polled.json()) as QueryResult;
  }
  return result;
}

function formatCell(value: string | number | boolean | null, type: string): string {
  if (value === null) return "NULL";
  if (typeof value === "boolean") return value ? "是" : "否";
  const normalizedType = type.toLowerCase();
  if (normalizedType.includes("date") && !normalizedType.includes("timestamp")) {
    return String(value);
  }
  if (normalizedType.includes("time") && typeof value === "string") {
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.valueOf())) {
      return new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "medium",
        timeZone: "Asia/Shanghai",
      }).format(parsed);
    }
  }
  return String(value);
}

function statusTitle(result: QueryResult): string {
  if (result.status === "clarification_required") return "需要补充信息";
  if (result.status === "rejected") return "当前范围暂不支持";
  if (result.status === "failed") return "查询没有完成";
  return "正在处理";
}

/** 渲染指标口径说明卡片 */
function MetricDefinitionCard({ metric }: { metric: MetricDefinitionBrief }) {
  return (
    <div className="metric-card">
      <div className="metric-header">
        <span className="metric-label">{metric.label}</span>
        <code className="metric-id">{metric.metric_id}</code>
      </div>
      <pre className="metric-expression">{metric.expression}</pre>
      {metric.required_filters.length > 0 && (
        <div className="metric-filters">
          <span className="metric-filters-title">强制过滤</span>
          <ul>
            {metric.required_filters.map((f, i) => (
              <li key={i}><code>{f}</code></li>
            ))}
          </ul>
        </div>
      )}
      {metric.time_rule_note && (
        <p className="metric-time-note">⏱ {metric.time_rule_note}</p>
      )}
      {metric.warning && (
        <p className="metric-warning">⚠️ {metric.warning}</p>
      )}
    </div>
  );
}

export default function DataAnalystHome() {
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [networkError, setNetworkError] = useState<string | null>(null);
  const requestSequence = useRef(0);

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const normalized = question.trim();
    if (!normalized || submitting) return;
    setSubmitting(true);
    setNetworkError(null);
    setResult(null);
    const sequence = ++requestSequence.current;
    try {
      const next = await requestQuery(normalized);
      if (sequence === requestSequence.current) setResult(next);
    } catch (error) {
      if (sequence === requestSequence.current) {
        setNetworkError(error instanceof Error ? error.message : "网络请求失败");
      }
    } finally {
      if (sequence === requestSequence.current) setSubmitting(false);
    }
  }

  async function fillExample(text: string) {
    setQuestion(text);
    setSubmitting(true);
    setNetworkError(null);
    setResult(null);
    const sequence = ++requestSequence.current;
    try {
      const next = await requestQuery(text);
      if (sequence === requestSequence.current) setResult(next);
    } catch (error) {
      if (sequence === requestSequence.current) {
        setNetworkError(error instanceof Error ? error.message : "网络请求失败");
      }
    } finally {
      if (sequence === requestSequence.current) setSubmitting(false);
    }
  }

  return (
    <main>
      <header>
        <p className="eyebrow">ATLASSQL / V3 语义问数</p>
        <h1>用一句话查询业务数据</h1>
        <p className="lead">
          V3 支持全域指标查询（销售、财务、客户、库存、营销）。指标口径版本化管理，SQL 生成遵循统一业务规则。
        </p>
      </header>

      <form onSubmit={submit} className="query-form">
        <label htmlFor="question">你的问题</label>
        <div className="example-chips" role="list" aria-label="示例问题">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              className="chip"
              disabled={submitting}
              onClick={() => void fillExample(q)}
            >
              {q}
            </button>
          ))}
        </div>
        <textarea
          id="question"
          value={question}
          maxLength={2000}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：2026 年上半年各品类毛利率是多少？"
          disabled={submitting}
        />
        <div className="form-footer">
          <span>{question.length} / 2000</span>
          <button type="submit" disabled={submitting || !question.trim()}>
            {submitting ? "正在分析…" : "开始查询"}
          </button>
        </div>
      </form>

      {submitting && (
        <section className="state-card loading" aria-live="polite">
          正在生成并安全校验 SQL…
        </section>
      )}

      {networkError && (
        <section className="state-card error" role="alert">
          <h2>请求失败</h2>
          <p>{networkError}</p>
          <button onClick={() => void submit()} disabled={submitting}>保留问题并重试</button>
        </section>
      )}

      {result?.status === "succeeded" && (
        <section className="result-card" aria-live="polite">
          <div className="result-heading">
            <div><p className="label">结果摘要</p><h2>{result.summary}</h2></div>
            <span>{result.execution_ms ?? 0} ms</span>
          </div>

          {result.rows.length === 0 ? (
            <div className="empty-result">没有符合当前条件的记录。这不等同于指标数值为零。</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>{result.columns.map((column) => (
                    <th key={column.name}>{column.name}<small>{column.data_type}</small></th>
                  ))}</tr>
                </thead>
                <tbody>
                  {result.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>{row.map((cell, columnIndex) => (
                      <td
                        key={`${rowIndex}-${columnIndex}`}
                        className={cell === null ? "null" : undefined}
                      >
                        {formatCell(cell, result.columns[columnIndex]?.data_type ?? "text")}
                      </td>
                    ))}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {result.truncated && (
            <p className="notice">结果已达到返回上限，仅显示前 {result.rows.length} 行。</p>
          )}

          {/* V3：指标口径说明 */}
          {result.metric_definitions.length > 0 && (
            <details className="metric-definitions-section">
              <summary>
                查看指标口径说明
                <span className="metric-count">{result.metric_definitions.length} 个指标</span>
              </summary>
              <div className="metric-definitions-list">
                {result.metric_definitions.map((m) => (
                  <MetricDefinitionCard key={m.metric_id} metric={m} />
                ))}
              </div>
            </details>
          )}

          <details>
            <summary>查看 SQL 与数据来源</summary>
            <pre><code>{result.sql ? format(result.sql, { language: "sql", tabWidth: 2 }) : ""}</code></pre>
            <dl>
              <div><dt>表</dt><dd>{result.referenced_tables.join("、") || "无"}</dd></div>
              <div><dt>字段</dt><dd>{result.referenced_columns.join("、") || "无"}</dd></div>
              <div><dt>Trace ID</dt><dd><code>{result.trace_id}</code></dd></div>
            </dl>
          </details>
        </section>
      )}

      {result && result.status !== "succeeded" && (
        <section className={`state-card ${result.status}`} role="status">
          <h2>{statusTitle(result)}</h2>
          <p>{result.error?.message ?? "查询仍在处理中，请稍后重试。"}</p>
          <p className="trace">Trace ID：<code>{result.trace_id}</code></p>
          {result.status === "failed" && (
            <button onClick={() => void submit()}>保留问题并重试</button>
          )}
        </section>
      )}
    </main>
  );
}
