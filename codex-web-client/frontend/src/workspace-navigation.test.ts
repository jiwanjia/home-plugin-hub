import { describe, expect, it } from "vitest";
import { homeUrl, loginReturnUrl, workspaceLoginUrl } from "./workspace-navigation";

describe("shared HOME login navigation", () => {
  const login = "http://localhost:3000/login";
  const returning = (target: string) => `${login}?redirect=${encodeURIComponent(target)}`;

  it("returns to HOME on the same hostname with its view and fragment", () => {
    const target = "http://localhost:5000/?view=academy#worlds";
    expect(loginReturnUrl(returning(target))).toBe(target);
    expect(loginReturnUrl(returning("http://localhost:5000/?view=academy") + "#worlds")).toBe(target);
  });

  it("keeps workspace paths, queries and fragments across expired login", () => {
    const target = "http://localhost:3000/workspace/continuum?threadId=example#message";
    expect(loginReturnUrl(workspaceLoginUrl(target))).toBe(target);
  });

  it("defaults to the workspace and keeps the public HOME prefix", () => {
    expect(loginReturnUrl(login)).toBe("http://localhost:3000/workspace/continuum");
    expect(loginReturnUrl("https://home.example.test/login?redirect=%2Fhome%2F%3Fview%3Dacademy"))
      .toBe("https://home.example.test/home/?view=academy");
  });

  it.each([
    "https://evil.example/", "//evil.example/", "javascript:alert(1)",
    "http://localhost:5000@evil.example/", "http://127.0.0.1:5000/",
    "http://localhost:8000/", "http://localhost:5000/api/anything",
    "https://localhost:5000/", "/\\evil.example/", "/login", " /workspace",
    "http://user:password@localhost:3000/workspace", "http://[invalid",
  ])("rejects unsafe or unrelated return target %s", (target) => {
    expect(loginReturnUrl(returning(target))).toBe("http://localhost:3000/workspace/continuum");
  });

  it("resolves HOME for local, LAN, IPv6 and public workspace entries", () => {
    expect(homeUrl("http://localhost:3000/plugins")).toBe("http://localhost:5000/");
    expect(homeUrl("http://192.0.2.1:3000/workspace")).toBe("http://192.0.2.1:5000/");
    expect(homeUrl("http://[::1]:3000/workspace")).toBe("http://[::1]:5000/");
    expect(homeUrl("https://home.example.test/plugins")).toBe("https://home.example.test/home/");
  });
});
