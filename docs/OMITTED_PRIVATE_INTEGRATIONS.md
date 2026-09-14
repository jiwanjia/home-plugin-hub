# Omitted private integrations

This public release deliberately omits complete source files when they contain or are tightly coupled to private identity, memory, credentials, machine-specific paths, household defaults, device addresses, or private runtime data. The source files were not sanitized, copied, split, or rewritten for publication.

The omitted capability groups are:

- Resident memory and production memory routing
- Private identity and Continuum context readers
- Memo and reminder storage
- Browser-session capture and history search
- Direct filesystem generation and file operations tied to local policy
- ADB and device-specific phone control
- Termux and private phone-agent launch configuration

## Public replacement points

Implementations can be supplied without changing the hub core:

- Use the manifest to register a Python entry point or MCP stdio server.
- Declare required environment-variable names, never their values.
- Keep identity and memory providers behind client and route identifiers.
- Put machine paths, device addresses, and credentials in untracked local configuration.
- Validate all commands and paths at the adapter boundary and apply least privilege.
- Test with fixtures or emulators rather than real accounts, memories, or devices.

These descriptions document extension boundaries only; they do not reproduce private implementation details.
## Remote MCP host boundary

The repository includes the original Hub-specific HTTP MCP, OAuth metadata, resource-validation, resident-route, and Plugin Socket UI reference files. It does not include the complete private FastAPI host that wires those files together.

You must supply your own account model, session policy, OAuth database initialization, owner credential storage, deployment configuration, TLS/reverse proxy, production resident data, and router/lifespan assembly. The reference code must not be treated as a ready-to-deploy public authentication service until those boundaries are implemented and reviewed for the target environment.
