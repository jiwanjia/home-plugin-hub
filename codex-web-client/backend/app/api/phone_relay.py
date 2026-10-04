"""Authenticated outbound polling endpoints for the single phone agent."""

from __future__ import annotations

import hmac
import json
import re

from fastapi import APIRouter, Body, Header, HTTPException, Request, Response

from phone_relay.authentication import (
    InvalidPhoneRelayTokenFile,
    configured_phone_relay_token,
)
from phone_relay.bootstrap import (
    BootstrapCodeStore,
    BootstrapUnavailable,
    build_phone_agent_archive,
    installer_script,
)
from phone_relay.contracts import PhoneResult
from phone_relay.registry import PhoneRelayTimeout, get_phone_relay_registry


router = APIRouter(prefix="/api/phone-relay")


def _external_relay_url(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    forwarded_host = request.headers.get("x-forwarded-host", "")
    scheme = forwarded_proto.split(",", 1)[0].strip().lower()
    host = forwarded_host.split(",", 1)[0].strip()
    if scheme != "https" or not re.fullmatch(
        r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?",
        host,
    ):
        raise HTTPException(503, "phone relay HTTPS origin is unavailable")
    return f"https://{host}"


def _authorize(request: Request, authorization: str | None) -> None:
    try:
        configured = configured_phone_relay_token(request.app.state.settings)
    except (InvalidPhoneRelayTokenFile, OSError) as error:
        raise HTTPException(
            503,
            "phone relay token configuration is invalid",
        ) from error
    if not configured:
        raise HTTPException(503, "phone relay is disabled")

    scheme, separator, token = (authorization or "").partition(" ")
    valid = (
        bool(separator)
        and scheme.lower() == "bearer"
        and hmac.compare_digest(token, configured)
    )
    if not valid:
        raise HTTPException(401, "invalid phone relay credentials")


@router.post("/poll")
def poll(
    request: Request,
    body: dict,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(request, authorization)
    wait_seconds = body.get("wait_seconds", 25)
    if not isinstance(wait_seconds, int):
        raise HTTPException(400, "wait_seconds must be an integer")

    registry = get_phone_relay_registry()
    registry.note_agent_poll(body.get("agent_version"))
    command = registry.poll(wait_seconds)
    return {
        "command": command.to_dict() if command is not None else None,
    }


@router.post("/results")
def submit_result(
    request: Request,
    body: dict,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(request, authorization)
    encoded_size = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    if encoded_size > request.app.state.settings.phone_relay_max_result_bytes:
        raise HTTPException(413, "phone relay result is too large")

    try:
        result = PhoneResult.from_dict(body)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error

    accepted = get_phone_relay_registry().complete(result)
    if not accepted:
        raise HTTPException(409, "phone relay request is no longer pending")
    return {"accepted": True}


@router.get("/health")
def health(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(request, authorization)
    return get_phone_relay_registry().status()


@router.post("/commands")
def submit_command(
    request: Request,
    body: dict,
    authorization: str | None = Header(default=None),
) -> dict:
    """Run one Hub command through the backend-owned relay registry."""
    _authorize(request, authorization)
    action = body.get("action")
    arguments = body.get("arguments", {})
    deadline_seconds = body.get("deadline_seconds", 30)
    if not isinstance(action, str) or not action:
        raise HTTPException(400, "action must be a non-empty string")
    if not isinstance(arguments, dict):
        raise HTTPException(400, "arguments must be an object")
    if not isinstance(deadline_seconds, int):
        raise HTTPException(400, "deadline_seconds must be an integer")

    try:
        result = get_phone_relay_registry().submit_and_wait(
            action,
            arguments,
            deadline_seconds,
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except PhoneRelayTimeout as error:
        raise HTTPException(504, str(error)) from error
    return result.to_dict()


@router.get("/bootstrap/install")
def bootstrap_installer(request: Request) -> Response:
    script = installer_script(_external_relay_url(request))
    return Response(
        script,
        media_type="text/plain",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/bootstrap")
def download_bootstrap(
    request: Request,
    code: str = Body(media_type="text/plain"),
) -> Response:
    settings = request.app.state.settings
    store = BootstrapCodeStore(settings.phone_relay_bootstrap_path)
    try:
        store.claim(code)
        relay_token = configured_phone_relay_token(settings)
        if not relay_token:
            raise BootstrapUnavailable("phone relay token is unavailable")
        archive = build_phone_agent_archive(
            settings.project_path,
            _external_relay_url(request),
            relay_token,
        )
    except (BootstrapUnavailable, InvalidPhoneRelayTokenFile, OSError) as error:
        raise HTTPException(404, "bootstrap grant is unavailable") from error
    return Response(
        archive,
        media_type="application/gzip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "attachment; filename=continuum-phone.tar.gz",
        },
    )
