import { describe, expect, it } from "vitest";

import { pluginGroups } from "./PluginSocketPage";

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
