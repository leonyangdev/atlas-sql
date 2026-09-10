"use client";

/**
 * 新建数据源表单
 *
 * 字段说明：
 * - slug：URL 标识符，只允许小写字母、数字和连字符，后续操作（同步、查询）都用它定位
 * - credential_ref：凭据引用格式，只能是 env:VAR_NAME 或 vault:path/to/secret，
 *   密码不存数据库，系统运行时从环境变量或 Vault 读取
 * - 管理员 Token：x-admin-token 请求头，对应后端 ATLAS_ADMIN_TOKEN 环境变量
 */

import { useState } from "react";

interface FormState {
  slug: string;
  name: string;
  kind: string;
  host: string;
  port: string;
  database_name: string;
  credential_ref: string;
  description: string;
  adminToken: string;
}

type SubmitState =
  | { type: "idle" }
  | { type: "loading" }
  | { type: "success"; slug: string }
  | { type: "error"; message: string };

const INITIAL: FormState = {
  slug: "nova-retail",
  name: "NovaRetail 业务库",
  kind: "postgresql",
  host: "127.0.0.1",
  port: "5433",
  database_name: "nova_retail",
  credential_ref: "env:ATLAS_BUSINESS_OWNER_DATABASE_URL",
  description: "NovaRetail 零售集团业务库，包含 Sales / Product / Customer 等 7 个业务域",
  adminToken: "",
};

export default function NewDatasourceForm() {
  const [form, setForm] = useState<FormState>(INITIAL);
  const [state, setState] = useState<SubmitState>({ type: "idle" });

  function update(field: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (!form.adminToken) {
      setState({ type: "error", message: "请填写管理员 Token" });
      return;
    }

    setState({ type: "loading" });

    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
      const res = await fetch(`${apiBase}/api/v1/datasources`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-admin-token": form.adminToken,
        },
        body: JSON.stringify({
          slug: form.slug,
          name: form.name,
          kind: form.kind,
          host: form.host,
          port: Number(form.port),
          database_name: form.database_name,
          credential_ref: form.credential_ref,
          description: form.description || undefined,
        }),
      });

      if (!res.ok) {
        const body = await res.text();
        setState({ type: "error", message: `API ${res.status}: ${body}` });
        return;
      }

      const data = await res.json();
      setState({ type: "success", slug: data.slug });
    } catch (err) {
      setState({
        type: "error",
        message: err instanceof Error ? err.message : "请求失败，请检查网络和后端是否启动",
      });
    }
  }

  if (state.type === "success") {
    return (
      <div className="card" style={{ borderColor: "#1a4a2a", background: "#0a2a1a", marginTop: 32 }}>
        <p style={{ color: "#34d399", fontWeight: 600, marginBottom: 12 }}>
          ✓ 数据源 <code>{state.slug}</code> 登记成功
        </p>
        <p style={{ color: "#aebdd2", fontSize: 14, marginBottom: 20 }}>
          下一步：进入详情页，点击「触发同步」开始采集表和列的元数据。
        </p>
        <div style={{ display: "flex", gap: 12 }}>
          <a href={`/datasources/${state.slug}`} className="btn btn-primary">
            前往详情页 →
          </a>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              setForm(INITIAL);
              setState({ type: "idle" });
            }}
          >
            再登记一个
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="detail-section" noValidate>
      {/* 数据库连接信息 */}
      <h2>数据库连接</h2>
      <div className="form-grid">
        <Field
          label="标识（slug）"
          hint="用于 URL，只允许小写字母、数字和连字符，例如 nova-retail"
          required
        >
          <input
            className="form-input"
            type="text"
            placeholder="nova-retail"
            value={form.slug}
            onChange={(e) => update("slug", e.target.value)}
            pattern="^[a-z0-9_-]+$"
            required
          />
        </Field>

        <Field label="显示名称" required>
          <input
            className="form-input"
            type="text"
            placeholder="NovaRetail 业务库"
            value={form.name}
            onChange={(e) => update("name", e.target.value)}
            required
          />
        </Field>

        <Field label="数据库类型" required>
          <select
            className="form-input"
            value={form.kind}
            onChange={(e) => update("kind", e.target.value)}
          >
            <option value="postgresql">PostgreSQL</option>
            <option value="mysql">MySQL（暂不支持）</option>
            <option value="bigquery">BigQuery（暂不支持）</option>
            <option value="snowflake">Snowflake（暂不支持）</option>
          </select>
        </Field>

        <Field label="主机" required>
          <input
            className="form-input"
            type="text"
            placeholder="127.0.0.1"
            value={form.host}
            onChange={(e) => update("host", e.target.value)}
            required
          />
        </Field>

        <Field label="端口" required>
          <input
            className="form-input"
            type="number"
            placeholder="5432"
            value={form.port}
            onChange={(e) => update("port", e.target.value)}
            min={1}
            max={65535}
            required
          />
        </Field>

        <Field label="数据库名" required>
          <input
            className="form-input"
            type="text"
            placeholder="nova_retail"
            value={form.database_name}
            onChange={(e) => update("database_name", e.target.value)}
            required
          />
        </Field>

        <Field
          label="凭据引用"
          hint="格式：env:VAR_NAME 或 vault:path/to/secret。密码不存数据库，系统运行时从环境变量读取。"
          required
        >
          <input
            className="form-input"
            type="text"
            placeholder="env:ATLAS_BUSINESS_OWNER_DATABASE_URL"
            value={form.credential_ref}
            onChange={(e) => update("credential_ref", e.target.value)}
            required
          />
        </Field>

        <Field label="描述（可选）" fullWidth>
          <textarea
            className="form-input"
            rows={2}
            placeholder="简短描述这个数据源的用途"
            value={form.description}
            onChange={(e) => update("description", e.target.value)}
          />
        </Field>
      </div>

      {/* 管理员鉴权 */}
      <h2 style={{ marginTop: 32 }}>管理员鉴权</h2>
      <div className="form-grid">
        <Field
          label="管理员 Token"
          hint="对应后端环境变量 ATLAS_ADMIN_TOKEN"
          required
        >
          <input
            className="form-input"
            type="password"
            placeholder="dev-admin-token"
            value={form.adminToken}
            onChange={(e) => update("adminToken", e.target.value)}
            required
          />
        </Field>
      </div>

      {/* 错误提示 */}
      {state.type === "error" && (
        <p className="status-msg error-msg" role="alert">
          ✗ {state.message}
        </p>
      )}

      {/* 提交 */}
      <div className="btn-row" style={{ marginTop: 24 }}>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={state.type === "loading"}
          aria-busy={state.type === "loading"}
        >
          {state.type === "loading" ? "登记中…" : "登记数据源"}
        </button>
        <a href="/datasources" className="btn btn-secondary">
          取消
        </a>
      </div>
    </form>
  );
}

// ── 表单字段包装组件 ──────────────────────────────────────────────────────────

function Field({
  label,
  hint,
  required,
  fullWidth,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  fullWidth?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={fullWidth ? "form-field full-width" : "form-field"}>
      <label className="form-label">
        {label}
        {required && <span aria-hidden="true" style={{ color: "#f87171", marginLeft: 2 }}>*</span>}
      </label>
      {children}
      {hint && <p className="field-hint" style={{ marginTop: 4 }}>{hint}</p>}
    </div>
  );
}
