"""Read and sanitize Android UI text inside the Termux phone agent."""

from __future__ import annotations

import html
import json
import re
import subprocess
import xml.etree.ElementTree as element_tree
from typing import Any, Dict, List

from .termux_command_runner import run_process


MAX_UI_XML_BYTES = 1024 * 1024
MAX_UI_TEXTS = 60
MAX_UI_TEXT_LENGTH = 160
MAX_UI_RESULT_BYTES = 16 * 1024

UI_DUMP_COMMAND = (
    "p=/data/local/tmp/continuum-ui-$$.xml; "
    "trap 'rm -f \"$p\"' EXIT; "
    "uiautomator dump \"$p\" >/dev/null 2>&1 || exit 21; "
    "test -s \"$p\" || exit 22; "
    "cat \"$p\" || exit 23"
)

UI_DUMP_EMPTY_EXIT_CODE = 22

URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6_PATTERN = re.compile(r"(?<!\w)(?:[0-9a-f]{1,4}:){2,}[0-9a-f:]+(?!\w)", re.I)
PATH_PATTERN = re.compile(r"(?:/data|/storage|/sdcard|/proc|/system)/\S+", re.I)
SECRET_PATTERN = re.compile(
    r"\b(?:bearer|token|api[_ -]?key|authorization)\b\s*[:=]?\s*\S+",
    re.IGNORECASE,
)
LONG_HEX_PATTERN = re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE)
LONG_NUMBER_PATTERN = re.compile(r"\b\d{6,}\b")
DISALLOWED_XML_CHARACTER_PATTERN = re.compile(
    "[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)
NUMERIC_CHARACTER_REFERENCE_PATTERN = re.compile(
    r"&#(?:x(?P<hexadecimal>[0-9a-fA-F]+)|(?P<decimal>[0-9]+));"
)

UI_HIERARCHY_START = "<hierarchy"
UI_HIERARCHY_END = "</hierarchy>"


class UiReadError(RuntimeError):
    """Stable, non-sensitive UI-read failure."""


def read_ui_snapshot(timeout: int) -> Dict[str, Any]:
    xml_text = read_ui_xml(timeout)
    return parse_ui_snapshot(xml_text)


def read_ui_xml(timeout: int) -> str:
    try:
        completed = run_process(["rish", "-c", UI_DUMP_COMMAND], timeout)
    except FileNotFoundError as error:
        raise UiReadError("ui_dump_failed") from error
    except subprocess.TimeoutExpired as error:
        raise UiReadError("ui_dump_timed_out") from error

    if completed.returncode != 0:
        error_code = "ui_dump_failed"
        if completed.returncode == UI_DUMP_EMPTY_EXIT_CODE:
            error_code = "ui_dump_empty"
        raise UiReadError(error_code)

    xml_text = completed.stdout or ""
    if len(xml_text.encode("utf-8")) > MAX_UI_XML_BYTES:
        raise UiReadError("ui_output_too_large")
    if not xml_text.strip():
        raise UiReadError("ui_dump_empty")
    return xml_text


def parse_ui_snapshot(xml_text: str) -> Dict[str, Any]:
    hierarchy_xml = prepare_ui_hierarchy_xml(xml_text)
    try:
        root = element_tree.fromstring(hierarchy_xml)
    except element_tree.ParseError as error:
        raise UiReadError("ui_parse_failed") from error

    texts: List[str] = []
    redacted_count = 0
    truncated = False
    node_count = 0

    for node in root.iter("node"):
        node_count += 1
        for attribute_name in ("text", "content-desc"):
            value = node.attrib.get(attribute_name, "")
            sanitized, was_redacted = sanitize_ui_text(value)
            redacted_count += int(was_redacted)
            if not sanitized or sanitized in texts:
                continue
            if len(texts) >= MAX_UI_TEXTS:
                truncated = True
                continue
            texts.append(sanitized)

    snapshot = {
        "state_known": True,
        "node_count": node_count,
        "texts": texts,
        "text_count": len(texts),
        "redacted_count": redacted_count,
        "truncated": truncated,
    }
    while len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > MAX_UI_RESULT_BYTES:
        snapshot["texts"].pop()
        snapshot["text_count"] = len(snapshot["texts"])
        snapshot["truncated"] = True
    return snapshot


def prepare_ui_hierarchy_xml(xml_text: str) -> str:
    """Isolate UIAutomator XML from non-XML shell output."""
    hierarchy_start = xml_text.find(UI_HIERARCHY_START)
    if hierarchy_start < 0:
        raise UiReadError("ui_parse_failed")

    hierarchy_end = xml_text.rfind(UI_HIERARCHY_END)
    if hierarchy_end >= hierarchy_start:
        hierarchy_end += len(UI_HIERARCHY_END)
        hierarchy_xml = xml_text[hierarchy_start:hierarchy_end]
    else:
        hierarchy_xml = extract_self_closing_hierarchy(xml_text, hierarchy_start)

    hierarchy_xml = DISALLOWED_XML_CHARACTER_PATTERN.sub("", hierarchy_xml)
    return replace_disallowed_numeric_character_references(hierarchy_xml)


def extract_self_closing_hierarchy(xml_text: str, hierarchy_start: int) -> str:
    tag_end = xml_text.find(">", hierarchy_start)
    if tag_end < 0:
        raise UiReadError("ui_parse_failed")

    hierarchy_tag = xml_text[hierarchy_start : tag_end + 1]
    if not hierarchy_tag[:-1].rstrip().endswith("/"):
        raise UiReadError("ui_parse_failed")
    return hierarchy_tag


def replace_disallowed_numeric_character_references(xml_text: str) -> str:
    def replace_reference(match: re.Match[str]) -> str:
        hexadecimal = match.group("hexadecimal")
        number_base = 16 if hexadecimal is not None else 10
        number_text = hexadecimal or match.group("decimal")
        codepoint = int(number_text, number_base)
        if is_xml_character(codepoint):
            return match.group(0)
        return "\ufffd"

    return NUMERIC_CHARACTER_REFERENCE_PATTERN.sub(replace_reference, xml_text)


def is_xml_character(codepoint: int) -> bool:
    if codepoint in {0x09, 0x0A, 0x0D}:
        return True
    if 0x20 <= codepoint <= 0xD7FF:
        return True
    if 0xE000 <= codepoint <= 0xFFFD:
        return True
    return 0x10000 <= codepoint <= 0x10FFFF


def sanitize_ui_text(value: str) -> tuple[str, bool]:
    sanitized = html.unescape(value).strip()
    original = sanitized
    sanitized = URL_PATTERN.sub("[url_redacted]", sanitized)
    sanitized = EMAIL_PATTERN.sub("[email_redacted]", sanitized)
    sanitized = IPV4_PATTERN.sub("[ip_redacted]", sanitized)
    sanitized = IPV6_PATTERN.sub("[ip_redacted]", sanitized)
    sanitized = PATH_PATTERN.sub("[path_redacted]", sanitized)
    sanitized = SECRET_PATTERN.sub("[secret_redacted]", sanitized)
    sanitized = LONG_HEX_PATTERN.sub("[identifier_redacted]", sanitized)
    sanitized = LONG_NUMBER_PATTERN.sub("[number_redacted]", sanitized)
    if len(sanitized) > MAX_UI_TEXT_LENGTH:
        sanitized = sanitized[:MAX_UI_TEXT_LENGTH]
    return sanitized, sanitized != original
