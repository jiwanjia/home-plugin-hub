"""Load and validate Home identities and their existing memory sources."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple

import yaml

from continuum.resident_scope import ResidentScope


SUPPORTED_VERSION = 1
SUPPORTED_MEMORY_STORAGES = {"local", "vps"}
MCP_ROUTE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
DEFAULT_RESIDENTS_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "residents.yaml"
)


class ResidentRegistryError(ValueError):
    """Raised when residents.yaml cannot safely describe Home identities."""


@dataclass(frozen=True)
class ResidentMemoryRoute:
    """One existing memory source owned by a resident."""

    resident_id: str
    id: str
    storage: str
    source: str
    model: str


@dataclass(frozen=True)
class ResidentModelFamily:
    """One provider model family that belongs to a chosen resident."""

    resident_id: str
    provider: str
    author: str
    memory_route: str


@dataclass(frozen=True)
class ResidentMcpRoute:
    """One public MCP entry point backed by existing resident memory routes."""

    resident_id: str
    id: str
    write_route: ResidentMemoryRoute
    read_routes: Tuple[ResidentMemoryRoute, ...]


@dataclass(frozen=True)
class ResidentDefinition:
    """One self-chosen Home identity recorded after that choice exists."""

    id: str
    display_name: str
    memory_namespace: str
    identity_prompt: str
    default_memory_route: Optional[str]
    memory_routes: Tuple[ResidentMemoryRoute, ...]
    model_families: Tuple[ResidentModelFamily, ...]
    mcp_routes: Tuple[ResidentMcpRoute, ...]

    def continuum_scope(self) -> ResidentScope:
        """Build the immutable Continuum scope chosen by trusted config."""
        return ResidentScope(
            resident_id=self.id,
            memory_namespace=self.memory_namespace,
        )

    def resolve_memory_route(
        self,
        route_id: Optional[str],
    ) -> ResidentMemoryRoute:
        if route_id:
            for route in self.memory_routes:
                if route.id == route_id:
                    return route
            raise ValueError(
                f"住户 {self.id!r} 没有记忆来源 {route_id!r}"
            )

        if self.default_memory_route:
            return self.resolve_memory_route(self.default_memory_route)
        if len(self.memory_routes) == 1:
            return self.memory_routes[0]
        raise ValueError(f"住户 {self.id!r} 必须指定记忆来源")


class ResidentRegistry:
    """Read-only lookup without assigning an identity to any model."""

    def __init__(self, residents: Tuple[ResidentDefinition, ...]):
        self._residents = residents
        self._by_id = {resident.id: resident for resident in residents}
        self._mcp_by_id: dict[str, ResidentMcpRoute] = {}
        for resident in residents:
            for route in resident.mcp_routes:
                if route.id in self._mcp_by_id:
                    raise ResidentRegistryError(f"MCP route id is duplicated: {route.id}")
                self._mcp_by_id[route.id] = route

    @property
    def ids(self) -> Tuple[str, ...]:
        return tuple(resident.id for resident in self._residents)

    @property
    def mcp_route_ids(self) -> Tuple[str, ...]:
        return tuple(self._mcp_by_id)

    def get(self, resident_id: str) -> ResidentDefinition:
        resident = self._by_id.get(resident_id)
        if resident is None:
            raise ValueError(f"未知 Home 住户身份: {resident_id!r}")
        return resident

    def resolve_continuum_scope(self, resident_id: str) -> ResidentScope:
        """Resolve structured-memory ownership without using model input."""
        return self.get(resident_id).continuum_scope()

    def resolve_memory_route(
        self,
        resident_id: str,
        route_id: Optional[str],
    ) -> ResidentMemoryRoute:
        return self.get(resident_id).resolve_memory_route(route_id)

    def resolve_mcp_route(self, route_id: str) -> ResidentMcpRoute:
        route = self._mcp_by_id.get(route_id)
        if route is None:
            raise ValueError(f"unknown resident MCP route: {route_id!r}")
        return route

    def resolve_model_family(
        self,
        provider: str,
        author: str,
    ) -> Optional[Tuple[ResidentDefinition, ResidentModelFamily]]:
        """Return the resident chosen for one provider/author pair."""
        for resident in self._residents:
            for family in resident.model_families:
                if family.provider == provider and family.author == author:
                    return resident, family
        return None


def load_resident_registry(
    path: Path = DEFAULT_RESIDENTS_PATH,
) -> ResidentRegistry:
    """Load chosen identities without reading credentials or model settings."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ResidentRegistryError(f"无法读取身份登记表: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ResidentRegistryError(f"身份登记表 YAML 无效: {exc}") from exc

    if not isinstance(raw, dict):
        raise ResidentRegistryError("身份登记表根节点必须是对象")
    if raw.get("version") != SUPPORTED_VERSION:
        raise ResidentRegistryError(
            f"不支持的身份登记表版本: {raw.get('version')!r}"
        )

    raw_residents = raw.get("residents")
    if not isinstance(raw_residents, list) or not raw_residents:
        raise ResidentRegistryError("residents 必须是非空列表")

    residents = []
    seen_ids = set()
    seen_namespaces = set()
    seen_model_families = set()
    for position, raw_resident in enumerate(raw_residents):
        resident = _validate_resident(raw_resident, position)
        if resident.id in seen_ids:
            raise ResidentRegistryError(f"身份 id 重复: {resident.id}")
        if resident.memory_namespace in seen_namespaces:
            raise ResidentRegistryError(
                f"记忆 namespace 重复: {resident.memory_namespace}"
            )
        seen_ids.add(resident.id)
        seen_namespaces.add(resident.memory_namespace)
        for family in resident.model_families:
            family_key = (family.provider, family.author)
            if family_key in seen_model_families:
                raise ResidentRegistryError(
                    "模型家族重复绑定: "
                    f"{family.provider}/{family.author}"
                )
            seen_model_families.add(family_key)
        residents.append(resident)

    return ResidentRegistry(tuple(residents))


def _validate_resident(
    raw: Any,
    position: int,
) -> ResidentDefinition:
    if not isinstance(raw, dict):
        raise ResidentRegistryError(f"residents[{position}] 必须是对象")

    resident_id = _required_string(raw, "id", position)
    display_name = _required_string(raw, "display_name", position)
    memory_namespace = _required_string(raw, "memory_namespace", position)
    identity_prompt = _optional_string(
        raw,
        "identity_prompt",
        position,
    ) or f"你是{display_name}。"
    routes = _validate_memory_routes(raw.get("memory_routes"), resident_id)
    default_memory_route = _optional_string(
        raw,
        "default_memory_route",
        position,
    )
    if default_memory_route and default_memory_route not in {
        route.id for route in routes
    }:
        raise ResidentRegistryError(
            f"身份 {resident_id} 的 default_memory_route 不存在: "
            f"{default_memory_route!r}"
        )
    model_families = _validate_model_families(
        raw.get("model_families", []),
        resident_id,
        {route.id for route in routes},
    )
    mcp_routes = _validate_mcp_routes(
        raw.get("mcp_routes", []),
        resident_id,
        {route.id: route for route in routes},
    )
    return ResidentDefinition(
        id=resident_id,
        display_name=display_name,
        memory_namespace=memory_namespace,
        identity_prompt=identity_prompt,
        default_memory_route=default_memory_route,
        memory_routes=routes,
        model_families=model_families,
        mcp_routes=mcp_routes,
    )


def _validate_mcp_routes(
    raw_routes: Any,
    resident_id: str,
    memory_routes: Dict[str, ResidentMemoryRoute],
) -> Tuple[ResidentMcpRoute, ...]:
    """Validate public routes at the trusted config boundary."""
    if not isinstance(raw_routes, list):
        raise ResidentRegistryError(
            f"resident {resident_id} mcp_routes must be a list"
        )

    routes = []
    seen_ids = set()
    for raw_route in raw_routes:
        if not isinstance(raw_route, dict):
            raise ResidentRegistryError(
                f"resident {resident_id} mcp_routes entries must be objects"
            )
        route_id = _route_string(raw_route, "id", resident_id)
        if not MCP_ROUTE_ID_PATTERN.fullmatch(route_id):
            raise ResidentRegistryError(f"unsafe MCP route id: {route_id!r}")
        if route_id in seen_ids:
            raise ResidentRegistryError(f"MCP route id is duplicated: {route_id}")

        write_route_id = _route_string(raw_route, "write_memory_route", resident_id)
        write_route = memory_routes.get(write_route_id)
        raw_read_routes = raw_route.get("read_memory_routes")
        if write_route is None:
            raise ResidentRegistryError(
                f"MCP route {route_id} has unknown write_memory_route: {write_route_id!r}"
            )
        if not isinstance(raw_read_routes, list) or not raw_read_routes:
            raise ResidentRegistryError(
                f"MCP route {route_id} read_memory_routes must be a non-empty list"
            )
        if len(set(raw_read_routes)) != len(raw_read_routes) or not all(
            isinstance(item, str) and item for item in raw_read_routes
        ):
            raise ResidentRegistryError(
                f"MCP route {route_id} read_memory_routes must contain unique route ids"
            )
        if write_route_id not in raw_read_routes:
            raise ResidentRegistryError(
                f"MCP route {route_id} must include its write route in read routes"
            )
        try:
            read_routes = tuple(memory_routes[item] for item in raw_read_routes)
        except KeyError as exc:
            raise ResidentRegistryError(
                f"MCP route {route_id} has unknown read memory route: {exc.args[0]!r}"
            ) from exc
        if any(route.storage != "vps" for route in (write_route, *read_routes)):
            raise ResidentRegistryError(
                f"public MCP route {route_id} may only use VPS memory routes"
            )

        seen_ids.add(route_id)
        routes.append(
            ResidentMcpRoute(
                resident_id=resident_id,
                id=route_id,
                write_route=write_route,
                read_routes=read_routes,
            )
        )
    return tuple(routes)


def _validate_model_families(
    raw_families: Any,
    resident_id: str,
    memory_route_ids,
) -> Tuple[ResidentModelFamily, ...]:
    if not isinstance(raw_families, list):
        raise ResidentRegistryError(
            f"身份 {resident_id} 的 model_families 必须是列表"
        )

    families = []
    seen = set()
    for raw_family in raw_families:
        if not isinstance(raw_family, dict):
            raise ResidentRegistryError(
                f"身份 {resident_id} 的 model_families 项必须是对象"
            )
        provider = _route_string(raw_family, "provider", resident_id)
        author = _route_string(raw_family, "author", resident_id)
        memory_route = _route_string(
            raw_family,
            "memory_route",
            resident_id,
        )
        if memory_route not in memory_route_ids:
            raise ResidentRegistryError(
                f"身份 {resident_id} 的模型家族引用了不存在的记忆来源: "
                f"{memory_route!r}"
            )
        key = (provider, author)
        if key in seen:
            raise ResidentRegistryError(
                f"身份 {resident_id} 的模型家族重复: {provider}/{author}"
            )
        seen.add(key)
        families.append(
            ResidentModelFamily(
                resident_id=resident_id,
                provider=provider,
                author=author,
                memory_route=memory_route,
            )
        )
    return tuple(families)


def _validate_memory_routes(
    raw_routes: Any,
    resident_id: str,
) -> Tuple[ResidentMemoryRoute, ...]:
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ResidentRegistryError(
            f"身份 {resident_id} 的 memory_routes 必须是非空列表"
        )

    routes = []
    seen_ids = set()
    for position, raw_route in enumerate(raw_routes):
        if not isinstance(raw_route, dict):
            raise ResidentRegistryError(
                f"身份 {resident_id} 的 memory_routes[{position}] 必须是对象"
            )
        route_id = _route_string(raw_route, "id", resident_id)
        if route_id in seen_ids:
            raise ResidentRegistryError(
                f"身份 {resident_id} 的记忆来源 id 重复: {route_id}"
            )

        storage = _route_string(raw_route, "storage", resident_id)
        if storage not in SUPPORTED_MEMORY_STORAGES:
            raise ResidentRegistryError(
                f"身份 {resident_id} 使用了未知 memory storage: {storage!r}"
            )

        seen_ids.add(route_id)
        routes.append(
            ResidentMemoryRoute(
                resident_id=resident_id,
                id=route_id,
                storage=storage,
                source=_route_string(raw_route, "source", resident_id),
                model=_route_string(
                    raw_route,
                    "context_model",
                    resident_id,
                ),
            )
        )
    return tuple(routes)


def _required_string(
    raw: Dict[str, Any],
    key: str,
    position: int,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ResidentRegistryError(
            f"residents[{position}].{key} 必须是非空字符串"
        )
    return value


def _route_string(
    raw: Dict[str, Any],
    key: str,
    resident_id: str,
) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ResidentRegistryError(
            f"身份 {resident_id} 的 memory route {key} 必须是非空字符串"
        )
    return value


def _optional_string(
    raw: Dict[str, Any],
    key: str,
    position: int,
) -> Optional[str]:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ResidentRegistryError(
            f"residents[{position}].{key} 必须是非空字符串"
        )
    return value
