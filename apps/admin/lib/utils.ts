/** 通用工具函数 */

/** 把 ISO 时间串转为本地可读格式，失败时返回原值 */
export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

/** 状态枚举 → 可读中文标签 */
export function syncStatusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: "待执行",
    running: "执行中",
    succeeded: "成功",
    failed: "失败",
  };
  return map[status] ?? status;
}

export function dsStatusLabel(status: string): string {
  const map: Record<string, string> = {
    active: "正常",
    inactive: "停用",
    error: "异常",
  };
  return map[status] ?? status;
}

/** 把 JSON 字符串数组解析为展示字符串，失败时返回原值 */
export function parseSampleValues(json: string | null): string[] {
  if (!json) return [];
  try {
    const arr = JSON.parse(json);
    if (Array.isArray(arr)) return arr.map(String);
  } catch {
    // ignore
  }
  return [];
}
