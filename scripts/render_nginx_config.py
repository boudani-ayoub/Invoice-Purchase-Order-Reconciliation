"""Render the reviewed Nginx example without accepting raw Nginx fragments."""

import argparse
import re
from pathlib import Path

TOKENS = {
    "PUBLIC_HOST",
    "TLS_CERTIFICATE",
    "TLS_PRIVATE_KEY",
    "CLIENT_BODY_TEMP",
    "ACCESS_LOG",
    "ERROR_LOG",
    "API_PORT",
    "WEB_PORT",
}
HOST = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
SAFE_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")


def _port(value: str) -> str:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("Ports must be between 1 and 65535")
    return str(port)


def render(template: str, values: dict[str, str]) -> str:
    if set(values) != TOKENS:
        raise ValueError("Nginx rendering requires the complete fixed setting set")
    if not HOST.fullmatch(values["PUBLIC_HOST"]):
        raise ValueError("Public host must be one lowercase DNS hostname")
    for key in (
        "TLS_CERTIFICATE",
        "TLS_PRIVATE_KEY",
        "CLIENT_BODY_TEMP",
        "ACCESS_LOG",
        "ERROR_LOG",
    ):
        if not SAFE_PATH.fullmatch(values[key]):
            raise ValueError(f"{key} must be a safe absolute path")
    values = {
        **values,
        "API_PORT": _port(values["API_PORT"]),
        "WEB_PORT": _port(values["WEB_PORT"]),
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("Nginx template contains an unknown placeholder")
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--client-body-temp", required=True)
    parser.add_argument("--access-log", required=True)
    parser.add_argument("--error-log", required=True)
    parser.add_argument("--api-port", default="8000")
    parser.add_argument("--web-port", default="3000")
    args = parser.parse_args()
    rendered = render(
        args.template.read_text(encoding="utf-8"),
        {
            "PUBLIC_HOST": args.host,
            "TLS_CERTIFICATE": args.certificate,
            "TLS_PRIVATE_KEY": args.private_key,
            "CLIENT_BODY_TEMP": args.client_body_temp,
            "ACCESS_LOG": args.access_log,
            "ERROR_LOG": args.error_log,
            "API_PORT": args.api_port,
            "WEB_PORT": args.web_port,
        },
    )
    args.output.write_text(rendered, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
