# Home Plugin Hub

Home Plugin Hub is a small, local-first plugin runtime for exposing Python tools and MCP stdio servers through one catalog and client interface. This public repository contains the reusable core, selected generic tools, example configuration, and tests. Private identity, memory, device, credential, and machine-specific integrations are intentionally omitted.

Created by `jiwanjia`, in collaboration with 砚 (Codex).

## Features

- Manifest-driven Python and MCP stdio plugins
- A local daemon, client, request router, operation log, and diagnostics
- Reusable shell, Python, web, BLE, toy-control, and phone-relay building blocks
- Explicit execution scopes and environment-variable declarations
- Safe fixture configuration for trying the runtime without real devices or accounts

## Requirements

- Python 3.10 or newer
- Windows for the named-pipe daemon transport
- Optional hardware or third-party services only for the corresponding plugins

Install the public Python dependencies in your own virtual environment:

```powershell
python -m pip install -r requirements.txt
```

## Quick start

Copy the example files before changing them. Do not put credentials into files tracked by Git.

```powershell
Copy-Item config/plugins.example.yaml config/plugins.yaml
Copy-Item config/residents.example.yaml config/residents.yaml
python -m plugin_hub.doctor
python -m plugin_hub.daemon --manifest config/plugins.yaml
```

The included manifest enables only the side-effect-free fixture MCP server. Hardware, shell, phone, and external-service plugins should be enabled individually only after reviewing their permissions and environment variables.

## MCP bridge

The stdio bridge lets an MCP client call the local hub:

```powershell
python -m plugin_hub.stdio_bridge --client example --memory-route local_example
```

See `.mcp.example.json` for a generic client configuration. The resident example contains placeholders only and is not a real identity or memory source.

The bridge is intended to be launched by an MCP client. Running it directly in a terminal leaves it waiting silently for JSON-RPC messages on standard input.

## Repository layout

- `plugin_hub/`: runtime, transport, routing, manifest loading, and diagnostics
- `core/`: shared tool interfaces
- `mcp_plugins/`: selected reusable tools
- `phone_relay/`: generic phone-agent protocol and execution boundaries
- `adapters/toy-mcp/`: optional toy-service MCP adapter
- `config/`: public, inert example configuration
- `tests/`: tests safe to publish with the selected modules

## Security model

Treat plugins according to their capabilities. Shell execution, browser automation, filesystem access, phone control, BLE, and remote services can have substantial side effects. Keep privileged plugins disabled by default, use least-privilege credentials supplied through environment variables, restrict reachable paths and commands, and inspect logs without recording secrets.

Private integrations omitted from this release are described in `docs/OMITTED_PRIVATE_INTEGRATIONS.md`. Their source is not included or rewritten into a public variant.

## Extending the hub

Implement the public tool contract or add an MCP stdio server, declare it explicitly in a manifest, list only the environment-variable names it requires, and add tests that use fixtures instead of real accounts or devices.

## License

MIT. See `LICENSE`.

---

# Home Plugin Hub（中文）

Home Plugin Hub 是一个小型、本地优先的插件运行时，用统一目录和客户端接口接入 Python 工具及 MCP stdio 服务。本公开仓库包含可复用核心、安全筛选后的通用工具、示例配置和测试。涉及私人身份、真实记忆、设备信息、凭据与本机环境的集成均未公开。

由 `jiwanjia` 创建，与砚（Codex）协作完成。

## 快速开始

在自己的虚拟环境安装依赖，然后复制示例配置：

```powershell
python -m pip install -r requirements.txt
Copy-Item config/plugins.example.yaml config/plugins.yaml
Copy-Item config/residents.example.yaml config/residents.yaml
python -m plugin_hub.doctor
python -m plugin_hub.daemon --manifest config/plugins.yaml
```

示例清单只启用无副作用的 fixture MCP 服务。Shell、浏览器、手机、BLE、硬件和外部服务类插件默认不应启用；使用前请逐项审查权限、命令范围与环境变量。

## MCP 接入

```powershell
python -m plugin_hub.stdio_bridge --client example --memory-route local_example
```

`.mcp.example.json` 与 `config/residents.example.yaml` 只包含通用占位示例，不对应真实身份或记忆来源。

stdio bridge 通常应由 MCP 客户端自动启动；如果直接在终端运行，它会安静等待标准输入中的 JSON-RPC 消息，并不是卡住。

## 安全说明

凭据只通过环境变量或仓库外的安全存储提供，不要提交 `.env`、Session、memo、日志、设备缓存或数据库。高权限工具应遵循最小权限原则，并限制可访问的路径、命令和设备。未公开的私人集成仅在 `docs/OMITTED_PRIVATE_INTEGRATIONS.md` 中描述能力与替换接口，源码没有复制或改写。

## 许可证

MIT，详见 `LICENSE`。

## Remote MCP and OAuth reference

The repository now includes the original HOME host integration for exposing one running Hub through a route-scoped HTTP MCP endpoint. The reference uses OAuth dynamic client registration, Authorization Code + PKCE S256, refresh tokens, exact resource binding, and a server-selected resident route. It is intentionally not a second Hub process.

Reference files live under `codex-web-client/backend/app/hub/` and `codex-web-client/backend/app/api/`. They are not a standalone server: the embedding FastAPI host must provide its own owner authentication, OAuth persistence, rate limiter, HTTPS proxy, router wiring, and trusted resident configuration. See `docs/REMOTE_MCP_OAUTH.md` before integrating them.

The original read-only Plugin Socket page is also included under `codex-web-client/frontend/src/`. It expects an authenticated host endpoint at `/api/plugin-socket`; the private HOME shell and login pages are not included.

## 公网 MCP、OAuth 与插件插座参考实现

仓库现已包含 HOME 宿主中用于把同一个运行中 Hub 暴露为 resident 路由 HTTP MCP 的原始参考实现。它复用 OAuth 动态客户端注册、Authorization Code + PKCE S256、refresh token、严格 resource 绑定和服务端选择的 resident 路由，不会启动第二个 Hub。

参考源码位于 `codex-web-client/backend/app/hub/` 与 `codex-web-client/backend/app/api/`，不能单独作为完整服务运行。接入方必须自行提供宿主登录、OAuth 持久化、限流、HTTPS 反向代理、路由装配和可信 resident 配置；接入前请阅读 `docs/REMOTE_MCP_OAUTH.md`。

原插件插座只读页面也位于 `codex-web-client/frontend/src/`。它依赖宿主提供经过认证的 `/api/plugin-socket`；HOME 私人外壳与登录页面没有公开。