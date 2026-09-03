"""Read and validate the single Home plugin manifest."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml


SUPPORTED_VERSION = 1
SUPPORTED_KINDS = {"python", "continuum", "mcp_stdio"}


class ManifestError(ValueError):
    """Raised when plugins.yaml cannot safely describe the Hub."""


@dataclass(frozen=True)
class PluginConfig:
    """Validated configuration for one plugin."""

    id: str
    kind: str
    enabled: bool
    entrypoint: str = ""
    command: str = ""
    args: List[str] = field(default_factory=list)
    env_vars: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class HubManifest:
    """Validated top-level Hub configuration."""

    version: int
    pipe_name: str
    plugins: List[PluginConfig]


def load_manifest(path: Path) -> HubManifest:
    """Load the manifest without resolving plugins or reading secrets."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"无法读取插件登记表: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"插件登记表 YAML 无效: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestError("插件登记表根节点必须是对象")

    version = raw.get("version")
    if version != SUPPORTED_VERSION:
        raise ManifestError(
            f"不支持的登记表版本: {version!r}，当前只支持 {SUPPORTED_VERSION}"
        )

    pipe_name = raw.get("pipe_name")
    if not isinstance(pipe_name, str) or not pipe_name.strip():
        raise ManifestError("pipe_name 必须是非空字符串")
    if not pipe_name.startswith("\\\\.\\pipe\\"):
        raise ManifestError(
            "pipe_name 必须是 Windows 本机命名管道路径"
        )

    raw_plugins = raw.get("plugins")
    if not isinstance(raw_plugins, list):
        raise ManifestError("plugins 必须是列表")

    plugins = _validate_plugins(raw_plugins)
    return HubManifest(
        version=version,
        pipe_name=pipe_name,
        plugins=plugins,
    )


def _validate_plugins(raw_plugins: List[Any]) -> List[PluginConfig]:
    plugins = []
    seen_ids = set()

    for position, raw_plugin in enumerate(raw_plugins):
        if not isinstance(raw_plugin, dict):
            raise ManifestError(f"plugins[{position}] 必须是对象")

        plugin = _validate_plugin(raw_plugin, position)
        if plugin.id in seen_ids:
            raise ManifestError(f"插件 id 重复: {plugin.id}")

        seen_ids.add(plugin.id)
        plugins.append(plugin)

    return plugins


def _validate_plugin(raw: Dict[str, Any], position: int) -> PluginConfig:
    plugin_id = raw.get("id")
    if not isinstance(plugin_id, str) or not plugin_id.strip():
        raise ManifestError(f"plugins[{position}].id 必须是非空字符串")

    kind = raw.get("kind")
    if kind not in SUPPORTED_KINDS:
        raise ManifestError(f"插件 {plugin_id} 使用了未知 kind: {kind!r}")

    enabled = raw.get("enabled")
    if not isinstance(enabled, bool):
        raise ManifestError(f"插件 {plugin_id} 的 enabled 必须是布尔值")

    entrypoint = _optional_string(raw, "entrypoint", plugin_id)
    command = _optional_string(raw, "command", plugin_id)
    args = _string_list(raw, "args", plugin_id)
    env_vars = _string_list(raw, "env_vars", plugin_id)

    if kind in {"python", "continuum"} and not entrypoint:
        raise ManifestError(f"插件 {plugin_id} 缺少 entrypoint")
    if kind == "mcp_stdio" and not command:
        raise ManifestError(f"插件 {plugin_id} 缺少 command")

    return PluginConfig(
        id=plugin_id,
        kind=kind,
        enabled=enabled,
        entrypoint=entrypoint,
        command=command,
        args=args,
        env_vars=env_vars,
    )


def _optional_string(raw: Dict[str, Any], key: str, plugin_id: str) -> str:
    value = raw.get(key, "")
    if not isinstance(value, str):
        raise ManifestError(f"插件 {plugin_id} 的 {key} 必须是字符串")
    return value


def _string_list(raw: Dict[str, Any], key: str, plugin_id: str) -> List[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ManifestError(f"插件 {plugin_id} 的 {key} 必须是字符串列表")
    return list(value)
