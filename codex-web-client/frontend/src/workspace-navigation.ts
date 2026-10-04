/** HOME and workspace share a cookie on the browser's current hostname. */
export function homeUrl(workspaceUrl: string): string {
  const url = new URL(workspaceUrl);
  url.pathname = "/home/";
  if (url.port === "3000") {
    url.port = "5000";
    url.pathname = "/";
  }
  url.search = "";
  url.hash = "";
  return url.href;
}

export function workspaceLoginUrl(currentUrl: string): string {
  const current = new URL(currentUrl);
  const login = new URL("/login", current);
  login.searchParams.set("redirect", current.pathname + current.search + current.hash);
  return login.href;
}

export function loginReturnUrl(loginUrl: string): string {
  const login = new URL(loginUrl);
  const fallback = new URL("/workspace/continuum", login).href;
  const target = login.searchParams.get("redirect");
  if (!target || /[\\\u0000-\u0020\u007f]/.test(target) || target.startsWith("//")) {
    return fallback;
  }
  try {
    const destination = new URL(target, login);
    if (destination.username || destination.password || destination.pathname === "/login") {
      return fallback;
    }
    const sameOrigin = destination.origin === login.origin;
    const localHome = login.port === "3000"
      && destination.port === "5000"
      && destination.hostname === login.hostname
      && destination.protocol === login.protocol
      && ["/", "/index.html"].includes(destination.pathname);
    if (!sameOrigin && !localHome) return fallback;
    if (!["http:", "https:"].includes(destination.protocol)) return fallback;
    // Browsers carry the original HOME fragment across a server redirect.
    if (!destination.hash) destination.hash = login.hash;
    return destination.href;
  } catch {
    return fallback;
  }
}
