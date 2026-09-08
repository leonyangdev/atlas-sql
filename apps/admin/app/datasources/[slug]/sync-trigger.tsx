"use client";

/**
 * 同步触发按钮（客户端组件）
 *
 * 需要管理员 Token（从本地 sessionStorage 读取，或临时输入）。
 * 触发后显示任务 ID，并提示用户刷新页面查看进度。
 *
 * 权限边界：真实 RBAC 在 V4 实现；V0 阶段用 x-admin-token 简单鉴权。
 */

import { useState } from "react";
import { testConnection, triggerSync } from "../../../lib/api";

interface Props {
  slug: string;
}

type ActionState =
  | { type: "idle" }
  | { type: "loading"; action: "test" | "sync" }
  | { type: "success"; message: string }
  | { type: "error"; message: string };

export default function SyncTrigger({ slug }: Props) {
  const [token, setToken] = useState("");
  const [state, setState] = useState<ActionState>({ type: "idle" });

  async function handleTest() {
    if (!token) {
      setState({ type: "error", message: "请输入管理员 Token" });
      return;
    }
    setState({ type: "loading", action: "test" });
    try {
      const result = await testConnection(slug, token);
      if (result.ok) {
        setState({
          type: "success",
          message: `连接成功，延迟 ${result.latency_ms}ms`,
        });
      } else {
        setState({
          type: "error",
          message: `连接失败：${result.error_kind ?? "未知错误"}`,
        });
      }
    } catch (e) {
      setState({
        type: "error",
        message: e instanceof Error ? e.message : "请求失败",
      });
    }
  }

  async function handleSync() {
    if (!token) {
      setState({ type: "error", message: "请输入管理员 Token" });
      return;
    }
    setState({ type: "loading", action: "sync" });
    try {
      const result = await triggerSync(slug, token);
      setState({
        type: "success",
        message: `同步任务已触发，Job ID: ${result.job_id}（刷新页面查看进度）`,
      });
    } catch (e) {
      setState({
        type: "error",
        message: e instanceof Error ? e.message : "触发失败",
      });
    }
  }

  const isLoading = state.type === "loading";

  return (
    <div className="action-panel" aria-label="数据源操作">
      <div className="token-row">
        <label htmlFor="admin-token">管理员 Token</label>
        <input
          id="admin-token"
          type="password"
          placeholder="ATLAS_ADMIN_TOKEN"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="token-input"
          aria-describedby="token-hint"
        />
        <span id="token-hint" className="field-hint">
          对应环境变量 ATLAS_ADMIN_TOKEN
        </span>
      </div>

      <div className="btn-row">
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleTest}
          disabled={isLoading}
          aria-busy={isLoading && state.type === "loading" && state.action === "test"}
        >
          {isLoading && state.type === "loading" && state.action === "test"
            ? "测试中…"
            : "测试连接"}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleSync}
          disabled={isLoading}
          aria-busy={isLoading && state.type === "loading" && state.action === "sync"}
        >
          {isLoading && state.type === "loading" && state.action === "sync"
            ? "触发中…"
            : "触发同步"}
        </button>
      </div>

      {state.type === "success" && (
        <p className="status-msg success-msg" role="status">
          ✓ {state.message}
        </p>
      )}
      {state.type === "error" && (
        <p className="status-msg error-msg" role="alert">
          ✗ {state.message}
        </p>
      )}
    </div>
  );
}
