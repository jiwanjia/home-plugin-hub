# Remote MCP and OAuth reference integration

This directory documents the original HOME integration that exposes one existing Home Plugin Hub to OAuth-capable applications. The checked-in source is a host-integration reference, not a standalone public authentication server.

## Architecture

```text
OAuth-capable App
  -> HTTPS reverse proxy
  -> FastAPI protected-resource metadata and OAuth issuer
  -> /api/hub/mcp/{route_id}
  -> HubMcpService
  -> existing HubClient
  -> the one already-running Home Plugin Hub
```

The HTTP door does not load plugins and does not start a second Hub. `tools/list` reflects the live Hub catalog. `tools/call` forwards the selected tool and injects trusted resident context chosen from the URL route; callers cannot provide or override resident identity.

## Included reference source

- `codex-web-client/backend/app/hub/oauth.py`: builds issuer, resource, and protected-resource metadata URLs.
- `codex-web-client/backend/app/hub/mcp_service.py`: maps a trusted MCP route to the existing Hub client.
- `codex-web-client/backend/app/api/hub_oauth.py`: publishes protected-resource metadata.
- `codex-web-client/backend/app/api/hub_mcp.py`: handles MCP initialize, tools/list, tools/call, and authorization challenges.
- `codex-web-client/backend/app/api/memory_capture_oauth.py`: shows the shared issuer accepting exact Memory and Hub resources while keeping tokens resource-bound.
- `plugin_hub/residents.py`: validates configured public route IDs and maps them to existing memory routes.
- `continuum/resident_scope.py`: immutable trusted scope used by the current resident registry.
- `codex-web-client/frontend/src/PluginSocketPage.tsx` and `plugin-socket.css`: read-only catalog UI reference.

## Required host contracts

The private host assembly is intentionally omitted. An integrating host must provide compatible objects on FastAPI application state:

- a configured `HubMcpService` and live `HubClient`;
- an OAuth store supporting dynamic clients, one-time codes, access tokens, refresh-token rotation, revocation, expiry, and exact resource binding;
- owner authentication and session handling;
- registration and tool-call rate limiters;
- trusted resident configuration loaded at startup;
- HTTPS origin handling and reverse-proxy headers;
- explicit router and lifespan wiring.

Do not accept resident IDs, memory namespaces, storage paths, or database locations from model tool arguments. Route selection belongs to trusted host configuration.

## OAuth flow represented by the source

1. The App reads protected-resource metadata for `/api/hub/mcp/{route_id}`.
2. The App dynamically registers an approved redirect URI.
3. The owner approves an Authorization Code request using PKCE S256.
4. The issuer creates a code bound to client, redirect URI, resource, scope, and challenge.
5. The App exchanges the code for opaque tokens.
6. The Hub endpoint accepts only a non-expired access token for its exact resource.
7. A token issued for a Memory MCP resource cannot open a Hub MCP resource, and the reverse is also rejected.

Production callback allowlists, Content Security Policy, proxy trust, credential hashing, database permissions, and exposed tool capabilities must be reviewed for each deployment. High-privilege tools should not be exposed merely because OAuth is present.

## Plugin Socket UI

The included React page fetches `/api/plugin-socket` and renders the authoritative Hub status grouped by Python, Continuum, MCP stdio, and future plugin kinds. The supplied backend endpoint is also a host reference: it expects the embedding application to enforce its own authenticated session before returning catalog status.
