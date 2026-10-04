import React, { useEffect, useMemo, useState } from "react";

type ToolStatus = {
  name: string;
  description: string;
  plugin_id: string;
};

type PluginStatus = {
  id: string;
  kind: "python" | "continuum" | "mcp_stdio" | string;
  enabled: boolean;
  status: string;
  tools: ToolStatus[];
  last_error: string;
};

type PhoneAgentStatus = {
  online: boolean;
  agent_version: string | null;
  pending_count: number;
  queued_count: number;
};

type SocketStatus = {
  online: boolean;
  plugin_count: number;
  tool_count: number;
  failed_count: number;
  plugins: PluginStatus[];
  phone_agent: PhoneAgentStatus;
  error?: { code: string; message: string };
};

type PhoneAgentView = {
  stateClass: "online" | "offline" | "loading";
  label: string;
  detail: string;
};

const groupLabels: Record<string, string> = {
  python: "本地插件",
  continuum: "Continuum 服务",
  mcp_stdio: "外部 MCP",
};

function pluginGroups(plugins: PluginStatus[]) {
  const order = ["python", "continuum", "mcp_stdio"];
  const knownGroups = order.map((kind) => ({
    kind,
    label: groupLabels[kind],
    plugins: plugins.filter((plugin) => plugin.kind === kind),
  }));
  const otherPlugins = plugins.filter((plugin) => !order.includes(plugin.kind));
  if (otherPlugins.length) {
    knownGroups.push({
      kind: "other",
      label: "其他插件",
      plugins: otherPlugins,
    });
  }
  return knownGroups;
}

function phoneAgentView(status?: PhoneAgentStatus): PhoneAgentView {
  if (!status) {
    return {
      stateClass: "loading",
      label: "手机 Agent 状态读取中…",
      detail: "",
    };
  }

  const version = status.agent_version
    ? `版本 ${status.agent_version}`
    : "版本未知";
  const queue = `等待 ${status.pending_count} · 排队 ${status.queued_count}`;
  return {
    stateClass: status.online ? "online" : "offline",
    label: status.online ? "手机 Agent 在线" : "手机 Agent 离线",
    detail: `${version} · ${queue}`,
  };
}

export function PluginSocketPage() {
  const [status, setStatus] = useState<SocketStatus | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadStatus() {
    setLoading(true);
    try {
      const response = await fetch("/api/plugin-socket");
      if (response.status === 401) {
        location.href = "/login";
        return;
      }
      setStatus(await response.json());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  const groups = useMemo(
    () => pluginGroups(status?.plugins || []),
    [status],
  );
  const phoneAgent = phoneAgentView(status?.phone_agent);

  return (
    <main className="plugin-socket-page">
      <header className="plugin-socket-header">
        <div>
          <a href="/workspace/continuum">← 返回工作区</a>
          <h1>Home Plugin Socket</h1>
          <p>所有住户共用的唯一工具清单</p>
        </div>
        <button type="button" onClick={loadStatus} disabled={loading}>
          {loading ? "读取中…" : "刷新状态"}
        </button>
      </header>

      <section className="plugin-socket-summary" aria-label="插座汇总">
        <div className={status?.online ? "online" : "offline"}>
          <span />
          {status?.online ? "Hub 在线" : "Hub 离线"}
        </div>
        <dl>
          <div><dt>插件</dt><dd>{status?.plugin_count ?? "—"}</dd></div>
          <div><dt>工具</dt><dd>{status?.tool_count ?? "—"}</dd></div>
          <div><dt>异常</dt><dd>{status?.failed_count ?? "—"}</dd></div>
        </dl>
      </section>

      <section
        className={`phone-agent-status ${phoneAgent.stateClass}`}
        aria-label="手机 Agent 状态"
      >
        <span className="phone-agent-status-dot" aria-hidden="true" />
        <div>
          <b>{phoneAgent.label}</b>
          {phoneAgent.detail && <small>{phoneAgent.detail}</small>}
        </div>
      </section>

      {status?.error && (
        <aside className="plugin-socket-error" role="alert">
          <b>{status.error.code}</b>
          <span>{status.error.message}</span>
        </aside>
      )}

      {groups.map((group) => (
        <section className="plugin-socket-group" key={group.kind}>
          <h2>{group.label}<small>{group.plugins.length}</small></h2>
          <div className="plugin-socket-grid">
            {group.plugins.map((plugin) => (
              <article className="plugin-card" key={plugin.id}>
                <header>
                  <div>
                    <h3>{plugin.id}</h3>
                    <small>{plugin.kind}</small>
                  </div>
                  <span className={`plugin-state ${plugin.status.toLowerCase()}`}>
                    {plugin.status}
                  </span>
                </header>
                <p>{plugin.tools.length} 个工具</p>
                <ul>
                  {plugin.tools.map((tool) => (
                    <li key={tool.name} title={tool.description}>
                      {tool.name}
                    </li>
                  ))}
                </ul>
                {plugin.last_error && (
                  <div className="plugin-card-error">{plugin.last_error}</div>
                )}
              </article>
            ))}
            {!group.plugins.length && (
              <p className="plugin-socket-empty">尚未登记</p>
            )}
          </div>
        </section>
      ))}
    </main>
  );
}

export { phoneAgentView, pluginGroups };
