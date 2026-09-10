"use client";

/**
 * 指标详情页
 *
 * 展示指标定义、版本历史和版本对比；提供状态转移、发布、回滚操作。
 */

import { useState, useEffect } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

interface MetricDetail {
  metric_id: string;
  label: string;
  domain: string;
  grain: string;
  status: string;
  version_number: number | null;
  updated_at: string;
  expression: string;
  required_filters: string[];
  synonyms: string[];
  is_sensitive: boolean;
  time_rule_note: string | null;
  warning: string | null;
}

interface VersionRecord {
  version_number: number;
  published_by: string;
  published_at: string;
  change_note: string | null;
  regression_run_id: string | null;
}

const STATUS_LABEL: Record<string, string> = {
  draft: "草案",
  testing: "测试中",
  published: "已发布",
  deprecated: "已废弃",
};

const NEXT_TRANSITIONS: Record<string, { label: string; target: string }[]> = {
  draft: [{ label: "提交测试", target: "testing" }],
  testing: [
    { label: "回退草案", target: "draft" },
    { label: "发布", target: "published" },
  ],
  published: [],
  deprecated: [],
};

export default function MetricDetailPage({
  params,
}: {
  params: Promise<{ metric_id: string }>;
}) {
  const [metricId, setMetricId] = useState<string>("");
  const [metric, setMetric] = useState<MetricDetail | null>(null);
  const [versions, setVersions] = useState<VersionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [adminToken, setAdminToken] = useState("");

  // publish form state
  const [publishNote, setPublishNote] = useState("");
  const [regressionId, setRegressionId] = useState("");
  const [skipRegression, setSkipRegression] = useState(false);

  // rollback
  const [rollbackVersion, setRollbackVersion] = useState<number | "">("");

  useEffect(() => {
    params.then((p) => setMetricId(p.metric_id));
  }, [params]);

  useEffect(() => {
    if (!metricId) return;
    loadData();
  }, [metricId]);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [mRes, vRes] = await Promise.all([
        fetch(`${API}/api/v1/semantic/metrics/${metricId}`),
        fetch(`${API}/api/v1/semantic/metrics/${metricId}/versions`),
      ]);
      if (!mRes.ok) throw new Error(`加载失败：${mRes.status}`);
      setMetric(await mRes.json());
      setVersions(vRes.ok ? await vRes.json() : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "未知错误");
    } finally {
      setLoading(false);
    }
  }

  async function doTransition(target: string) {
    setActionMsg(null);
    if (target === "published") {
      await doPublish();
      return;
    }
    const res = await fetch(`${API}/api/v1/semantic/metrics/${metricId}/transition`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-admin-token": adminToken },
      body: JSON.stringify({ target_status: target, operator: "admin" }),
    });
    const data = await res.json();
    if (res.ok) {
      setActionMsg(`✓ 状态已变更为「${STATUS_LABEL[target]}」`);
      await loadData();
    } else {
      setActionMsg(`✗ ${data.detail}`);
    }
  }

  async function doPublish() {
    const res = await fetch(`${API}/api/v1/semantic/metrics/${metricId}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-admin-token": adminToken },
      body: JSON.stringify({
        published_by: "admin",
        regression_run_id: regressionId || null,
        change_note: publishNote || null,
        require_regression: !skipRegression,
      }),
    });
    const data = await res.json();
    if (res.ok) {
      setActionMsg(`✓ 已发布 v${data.version_number}`);
      await loadData();
    } else {
      setActionMsg(`✗ ${data.detail}`);
    }
  }

  async function doRollback() {
    if (!rollbackVersion) return;
    const res = await fetch(`${API}/api/v1/semantic/metrics/${metricId}/rollback`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-admin-token": adminToken },
      body: JSON.stringify({ target_version: rollbackVersion, operator: "admin" }),
    });
    const data = await res.json();
    if (res.ok) {
      setActionMsg(`✓ 已回滚到 v${rollbackVersion}`);
      await loadData();
    } else {
      setActionMsg(`✗ ${data.detail}`);
    }
  }

  if (loading) return <main><p style={{ padding: 32 }}>加载中…</p></main>;
  if (error) return <main><p style={{ padding: 32, color: "red" }}>{error}</p></main>;
  if (!metric) return null;

  const transitions = NEXT_TRANSITIONS[metric.status] || [];

  return (
    <main>
      <header>
        <p className="eyebrow">
          <Link href="/semantic">← 语义层</Link>
        </p>
        <h1>
          {metric.label}
          <span style={{ fontSize: 14, fontWeight: 400, marginLeft: 12, color: "#666" }}>
            {metric.metric_id}
          </span>
        </h1>
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 8 }}>
          <span className={`badge badge-${metric.status === "published" ? "active" : metric.status === "deprecated" ? "error" : "draft"}`}>
            {STATUS_LABEL[metric.status]}
          </span>
          {metric.version_number != null && (
            <code style={{ fontSize: 13 }}>v{metric.version_number}</code>
          )}
          <span style={{ fontSize: 13, color: "#888" }}>域：{metric.domain}</span>
          {metric.is_sensitive && (
            <span style={{ fontSize: 12, color: "red", background: "#fff0f0", padding: "1px 8px", borderRadius: 8 }}>
              受限
            </span>
          )}
        </div>
      </header>

      {/* 定义详情 */}
      <section style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 15, marginBottom: 8 }}>表达式</h2>
        <pre style={{ background: "#f5f5f5", padding: 12, borderRadius: 6, fontSize: 13, overflowX: "auto" }}>
          {metric.expression}
        </pre>

        {metric.required_filters.length > 0 && (
          <>
            <h2 style={{ fontSize: 15, marginTop: 16, marginBottom: 8 }}>强制过滤</h2>
            <ul style={{ fontSize: 13, margin: 0, paddingLeft: 20 }}>
              {metric.required_filters.map((f, i) => (
                <li key={i} style={{ fontFamily: "monospace" }}>{f}</li>
              ))}
            </ul>
          </>
        )}

        {metric.time_rule_note && (
          <>
            <h2 style={{ fontSize: 15, marginTop: 16, marginBottom: 8 }}>时间口径</h2>
            <p style={{ fontSize: 13, color: "#555" }}>{metric.time_rule_note}</p>
          </>
        )}

        {metric.warning && (
          <div style={{ background: "#fffbea", border: "1px solid #f0c040", padding: "8px 12px", borderRadius: 6, marginTop: 16, fontSize: 13 }}>
            ⚠️ {metric.warning}
          </div>
        )}

        {metric.synonyms.length > 0 && (
          <>
            <h2 style={{ fontSize: 15, marginTop: 16, marginBottom: 8 }}>同义词</h2>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {metric.synonyms.map((s) => (
                <span key={s} style={{ fontSize: 12, background: "#e8f0fe", padding: "2px 10px", borderRadius: 12 }}>
                  {s}
                </span>
              ))}
            </div>
          </>
        )}
      </section>

      {/* 操作区 */}
      <section style={{ marginTop: 32, padding: 20, background: "#f9f9f9", borderRadius: 8 }}>
        <h2 style={{ fontSize: 15, marginBottom: 12 }}>生命周期操作</h2>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 13, display: "block", marginBottom: 4 }}>管理员 Token</label>
          <input
            type="password"
            value={adminToken}
            onChange={(e) => setAdminToken(e.target.value)}
            placeholder="ATLAS_ADMIN_TOKEN"
            style={{ padding: "6px 10px", borderRadius: 4, border: "1px solid #ccc", width: 280, fontSize: 13 }}
          />
        </div>

        {/* 发布表单（仅 testing 状态显示） */}
        {metric.status === "testing" && (
          <div style={{ marginBottom: 12 }}>
            <input
              type="text"
              value={regressionId}
              onChange={(e) => setRegressionId(e.target.value)}
              placeholder="回归测试 ID（require_regression=true 时必填）"
              style={{ padding: "6px 10px", borderRadius: 4, border: "1px solid #ccc", width: 360, fontSize: 13, display: "block", marginBottom: 6 }}
            />
            <input
              type="text"
              value={publishNote}
              onChange={(e) => setPublishNote(e.target.value)}
              placeholder="变更说明（可选）"
              style={{ padding: "6px 10px", borderRadius: 4, border: "1px solid #ccc", width: 360, fontSize: 13, display: "block", marginBottom: 6 }}
            />
            <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6, color: "#e55" }}>
              <input type="checkbox" checked={skipRegression} onChange={(e) => setSkipRegression(e.target.checked)} />
              跳过回归检查（仅开发环境）
            </label>
          </div>
        )}

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {transitions.map(({ label, target }) => (
            <button
              key={target}
              onClick={() => doTransition(target)}
              className={target === "published" ? "btn btn-primary" : "btn btn-secondary"}
              style={{ fontSize: 13 }}
            >
              {label}
            </button>
          ))}
        </div>

        {actionMsg && (
          <p style={{ marginTop: 10, fontSize: 13, color: actionMsg.startsWith("✓") ? "#27ae60" : "#e74c3c" }}>
            {actionMsg}
          </p>
        )}
      </section>

      {/* 版本历史 */}
      {versions.length > 0 && (
        <section style={{ marginTop: 32 }}>
          <h2 style={{ fontSize: 15, marginBottom: 12 }}>版本历史</h2>
          <table className="data-table" aria-label="版本历史">
            <thead>
              <tr>
                <th>版本</th>
                <th>发布人</th>
                <th>发布时间</th>
                <th>回归 ID</th>
                <th>变更说明</th>
              </tr>
            </thead>
            <tbody>
              {[...versions].reverse().map((v) => (
                <tr key={v.version_number}>
                  <td>
                    <code style={{ fontSize: 12 }}>v{v.version_number}</code>
                    {metric.version_number === v.version_number && (
                      <span style={{ marginLeft: 6, fontSize: 11, color: "#27ae60" }}>当前</span>
                    )}
                  </td>
                  <td style={{ fontSize: 13 }}>{v.published_by}</td>
                  <td style={{ fontSize: 12, color: "#888" }}>
                    {new Date(v.published_at).toLocaleString("zh-CN")}
                  </td>
                  <td style={{ fontSize: 12, fontFamily: "monospace" }}>
                    {v.regression_run_id ?? <span style={{ color: "#ccc" }}>—</span>}
                  </td>
                  <td style={{ fontSize: 12, color: "#555" }}>
                    {v.change_note ?? <span style={{ color: "#ccc" }}>—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* 回滚区 */}
          {versions.length > 1 && metric.version_number != null && (
            <div style={{ marginTop: 16, display: "flex", gap: 10, alignItems: "center" }}>
              <select
                value={rollbackVersion}
                onChange={(e) => setRollbackVersion(e.target.value ? Number(e.target.value) : "")}
                style={{ padding: "6px 10px", borderRadius: 4, border: "1px solid #ccc", fontSize: 13 }}
              >
                <option value="">选择回滚目标版本…</option>
                {versions
                  .filter((v) => v.version_number !== metric.version_number)
                  .map((v) => (
                    <option key={v.version_number} value={v.version_number}>
                      v{v.version_number} ({new Date(v.published_at).toLocaleDateString("zh-CN")})
                    </option>
                  ))}
              </select>
              <button
                onClick={doRollback}
                disabled={!rollbackVersion}
                className="btn btn-secondary"
                style={{ fontSize: 13 }}
              >
                回滚
              </button>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
