import { describe, expect, it } from "vitest";

import { phoneAgentView, pluginGroups } from "./PluginSocketPage";

describe("plugin socket groups", () => {
  it("keeps local, Continuum, and external MCP plugins separate", () => {
    const groups = pluginGroups([
      {
        id: "shell",
        kind: "python",
        enabled: true,
        status: "OK",
        tools: [],
        last_error: "",
      },
      {
        id: "continuum_memory",
        kind: "continuum",
        enabled: true,
        status: "OK",
        tools: [],
        last_error: "",
      },
      {
        id: "home_fixture",
        kind: "mcp_stdio",
        enabled: true,
        status: "OK",
        tools: [],
        last_error: "",
      },
    ]);

    expect(groups.map((group) => group.plugins[0]?.id)).toEqual([
      "shell",
      "continuum_memory",
      "home_fixture",
    ]);
  });

  it("keeps future plugin kinds visible in the directory", () => {
    const groups = pluginGroups([
      {
        id: "future_plugin",
        kind: "future_kind",
        enabled: true,
        status: "OK",
        tools: [],
        last_error: "",
      },
    ]);

    expect(groups.at(-1)?.label).toBe("其他插件");
    expect(groups.at(-1)?.plugins[0]?.id).toBe("future_plugin");
  });
});

describe("phone agent status", () => {
  it("shows live online state and operational counts", () => {
    expect(phoneAgentView({
      online: true,
      agent_version: "0.2.4",
      pending_count: 1,
      queued_count: 2,
    })).toEqual({
      stateClass: "online",
      label: "手机 Agent 在线",
      detail: "版本 0.2.4 · 等待 1 · 排队 2",
    });
  });

  it("shows an explicit offline state", () => {
    expect(phoneAgentView({
      online: false,
      agent_version: null,
      pending_count: 0,
      queued_count: 0,
    })).toEqual({
      stateClass: "offline",
      label: "手机 Agent 离线",
      detail: "版本未知 · 等待 0 · 排队 0",
    });
  });
});
