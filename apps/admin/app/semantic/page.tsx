/**
 * 语义层管理首页
 *
 * 显示所有指标定义及其生命周期状态，支持按域和状态过滤。
 * 从 V3 语义 API 获取数据（服务端渲染）。
 */

import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type SemanticStatus = "draft" | "testing" | "published" | "deprecated";

interface MetricSummary {
  metric_id: string;
  label: string;
  domain: string;
  grain: string;
  status: SemanticStatus;
  version_number: number | null;
  updated_at: string;
}

const STATUS_LABEL: Record<SemanticStatus, string> = {
  draft: "草案",
  testing: "测试中",
  published: "已发布",
  deprecated: "已废弃",
};

const STATUS_CLASS: Record<SemanticStatus, string> = {
  draft: "badge-draft",
  testing: "badge-testing",
  published: "badge-active",
  deprecated: "badge-error",
};

async function fetchMetrics(domain?: string, status?: string): Promise<MetricSummary[]> {
  const qs = new URLSearchParams();
  if (domain) qs.set("domain", domain);
  if (status) qs.set("status", status);
  const query = qs.toString() ? `?${qs}` : "";

  try {
    const res = await fetch(`${API}/api/v1/semantic/metrics${query}`, {
      cache: "no-store",
    });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export default async function SemanticPage({
  searchParams,
}: {
  searchParams: Promise<{ domain?: string; status?: string }>;
}) {
  const params = await searchParams;
  const metrics = await fetchMetrics(params.domain, params.status);

  const domains = [...new Set(metrics.map((m) => m.domain))].sort();

  return (
    <main>
      <header>
        <p className="eyebrow">
          <Link href="/">← 控制台</Link>
        </p>
        <h1>语义层管理</h1>
        <p>
          管理指标定义的生命周期，从草案到发布，支持版本回滚和回归绑定。
        </p>
      </header>

      {/* 过滤栏 */}
      <div style={{ display: "flex", gap: 12, marginTop: 24, flexWrap: "wrap" }}>
        {["", "sales", "finance", "customer", "inventory", "marketing", "store"].map((d) => (
          <Link
            key={d || "all"}
            href={d ? `/semantic?domain=${d}` : "/semantic"}
            className={`btn ${params.domain === d || (!params.domain && !d) ? "btn-primary" : "btn-secondary"}`}
            style={{ fontSize: 13 }}
          >
            {d || "全部"}
          </Link>
        ))}
      </div>

      {/* 状态过滤 */}
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        {(["", "draft", "testing", "published", "deprecated"] as const).map((s) => (
          <Link
            key={s || "all"}
            href={
              s
                ? `/semantic?${params.domain ? `domain=${params.domain}&` : ""}status=${s}`
                : `/semantic${params.domain ? `?domain=${params.domain}` : ""}`
            }
            style={{
              fontSize: 12,
              padding: "2px 10px",
              borderRadius: 12,
              border: "1px solid #ccc",
              textDecoration: "none",
              background: params.status === s || (!params.status && !s) ? "#1a1a1a" : "transparent",
              color: params.status === s || (!params.status && !s) ? "#fff" : "inherit",
            }}
          >
            {s ? STATUS_LABEL[s as SemanticStatus] : "全部状态"}
          </Link>
        ))}
      </div>

      {metrics.length === 0 ? (
        <div className="card empty-card" role="status" style={{ marginTop: 24 }}>
          <strong>暂无指标</strong>
          <p>通过 seed 脚本导入草案指标，或调用 POST /api/v1/semantic/metrics。</p>
        </div>
      ) : (
        <table className="data-table" aria-label="指标列表" style={{ marginTop: 24 }}>
          <thead>
            <tr>
              <th>指标 ID</th>
              <th>展示名</th>
              <th>域</th>
              <th>粒度</th>
              <th>状态</th>
              <th>版本</th>
              <th>更新时间</th>
              <th aria-label="操作" />
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m.metric_id}>
                <td>
                  <code style={{ fontSize: 12 }}>{m.metric_id}</code>
                </td>
                <td>{m.label}</td>
                <td>
                  <span style={{ fontSize: 12, color: "#666" }}>{m.domain}</span>
                </td>
                <td>
                  <span style={{ fontSize: 12, color: "#666" }}>{m.grain}</span>
                </td>
                <td>
                  <span className={`badge ${STATUS_CLASS[m.status]}`}>
                    {STATUS_LABEL[m.status]}
                  </span>
                </td>
                <td>
                  {m.version_number != null ? (
                    <code style={{ fontSize: 12 }}>v{m.version_number}</code>
                  ) : (
                    <span style={{ color: "#999", fontSize: 12 }}>未发布</span>
                  )}
                </td>
                <td style={{ fontSize: 12, color: "#888" }}>
                  {new Date(m.updated_at).toLocaleDateString("zh-CN")}
                </td>
                <td>
                  <Link
                    href={`/semantic/metrics/${m.metric_id}`}
                    className="link-btn"
                  >
                    详情
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div style={{ marginTop: 16, fontSize: 12, color: "#888" }}>
        共 {metrics.length} 个指标
        {params.domain ? `（域：${params.domain}）` : ""}
        {params.status ? `（状态：${STATUS_LABEL[params.status as SemanticStatus]}）` : ""}
      </div>
    </main>
  );
}
