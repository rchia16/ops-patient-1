"""Authenticated Streamable HTTP MCP service for OPS Patient 1."""
import json
import logging
import os
from urllib.parse import urlparse

from mcp.server import Server
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.types import CallToolResult, ImageContent, ListToolsResult, TextContent, Tool
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from auth import Auth0TokenVerifier
from backend import Backend, ROOT
from validation import CaseError, check

LOGGER = logging.getLogger("ops-patient-1")
TOOLS = json.loads((ROOT / "schemas/tools.json").read_text(encoding="utf-8"))
TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def execute_tool(backend, name, arguments):
    """Execute one preserved tool contract and separate binary image content."""
    tool = TOOLS_BY_NAME.get(name)
    if not tool:
        raise CaseError("UNKNOWN_TOOL", "Tool is not implemented.")
    check(arguments, tool["inputSchema"])
    output = getattr(backend, name)(**arguments)
    images = output.pop("images", []) if name == "get_linked_image" else []
    if images:
        output["images"] = [{key: value for key, value in image.items() if key != "data"} for image in images]
    return output, images


async def list_tools(context, params):
    return ListToolsResult(
        tools=[
            Tool(
                name=tool["name"],
                description=tool["description"],
                inputSchema=tool["inputSchema"],
                annotations=tool["annotations"],
            )
            for tool in TOOLS
        ]
    )


async def call_tool(context, params):
    token = get_access_token()
    owner_id = token.subject if token else None
    if not owner_id:
        return _error_result("AUTH_OWNER_MISSING", "Validated credentials do not contain a stable subject.")
    backend = None
    try:
        backend = Backend(db=os.environ.get("DATABASE_URL"), owner_id=owner_id)
        output, images = execute_tool(backend, params.name, params.arguments or {})
        content = [TextContent(type="text", text=json.dumps(output, ensure_ascii=False))]
        content.extend(
            ImageContent(type="image", data=image["data"], mimeType=image["mimeType"])
            for image in images
        )
        return CallToolResult(content=content, structuredContent=output, isError=False)
    except CaseError as exc:
        return _error_result(exc.code, exc.message)
    except Exception:
        LOGGER.exception("Internal tool operation failed")
        return _error_result("INTERNAL_ERROR", "Operation failed; no result fabricated.")
    finally:
        if backend is not None:
            backend.db.close()


def _error_result(code, message):
    output = {"error": {"code": code, "message": message}}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(output, ensure_ascii=False))],
        structuredContent=output,
        isError=True,
    )


async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "ops-patient-1"})


async def openai_challenge(request: Request):
    value = os.environ.get("OPENAI_APPS_CHALLENGE")
    if not value:
        return PlainTextResponse("not configured", status_code=404)
    return PlainTextResponse(value)


def create_app():
    public_url = os.environ.get("OPS_PUBLIC_URL", "").rstrip("/")
    issuer = os.environ.get("AUTH0_ISSUER_URL", "").rstrip("/") + "/"
    audience = os.environ.get("AUTH0_AUDIENCE", "")
    required_scope = os.environ.get("OPS_REQUIRED_SCOPE", "simulation:use")
    if not public_url or not audience or issuer == "/":
        raise RuntimeError("OPS_PUBLIC_URL, AUTH0_ISSUER_URL, and AUTH0_AUDIENCE are required.")
    if not public_url.endswith("/mcp"):
        raise RuntimeError("OPS_PUBLIC_URL must be the externally reachable URL ending in /mcp.")

    server = Server(
        "ops-patient-1",
        version="1.2.0",
        instructions="Private simulator. Keep session_id, evidence, and metadata internal; follow the patient-role skill.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    verifier = Auth0TokenVerifier(
        issuer=issuer,
        audience=audience,
        required_scope=required_scope,
        jwks_url=os.environ.get("AUTH0_JWKS_URL"),
    )
    auth = AuthSettings(
        issuer_url=issuer,
        resource_server_url=public_url,
        required_scopes=[required_scope],
        validate_token_resource=False,
    )
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        auth=auth,
        token_verifier=verifier,
        host=urlparse(public_url).hostname or "127.0.0.1",
        custom_starlette_routes=[
            Route("/health", health, methods=["GET"]),
            Route("/.well-known/openai-apps-challenge", openai_challenge, methods=["GET"]),
        ],
    )


