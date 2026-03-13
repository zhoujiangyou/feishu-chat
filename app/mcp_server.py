# AI GC START
from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.services.service_api import FeishuChatServiceApiClient


MCP_TRANSPORT = os.environ.get("FEISHU_CHAT_MCP_TRANSPORT", "stdio")
MCP_HOST = os.environ.get("FEISHU_CHAT_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("FEISHU_CHAT_MCP_PORT", "9000"))


mcp = FastMCP(
    name="Feishu Chat Service MCP",
    instructions=(
        "This MCP server exposes Feishu Chat Service capabilities, including service creation, "
        "knowledge-base ingestion/search, and Feishu message sending."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
    json_response=True,
)


def _api_client() -> FeishuChatServiceApiClient:
    return FeishuChatServiceApiClient()


@mcp.tool(
    name="service_health",
    description="Check whether the Feishu Chat Service HTTP API is reachable.",
)
async def service_health() -> dict[str, Any]:
    client = _api_client()
    return await client.health()


@mcp.tool(
    name="create_feishu_service",
    description="Create a Feishu bot service instance with Feishu credentials and LLM configuration.",
)
async def create_feishu_service(
    name: str,
    feishu_app_id: str,
    feishu_app_secret: str,
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    verification_token: str | None = None,
    encrypt_key: str | None = None,
    llm_system_prompt: str | None = None,
) -> dict[str, Any]:
    client = _api_client()
    return await client.create_service(
        name=name,
        feishu_app_id=feishu_app_id,
        feishu_app_secret=feishu_app_secret,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        verification_token=verification_token,
        encrypt_key=encrypt_key,
        llm_system_prompt=llm_system_prompt,
    )


@mcp.tool(
    name="get_feishu_service",
    description="Get basic information about a previously created Feishu bot service instance.",
)
async def get_feishu_service(service_id: str) -> dict[str, Any]:
    client = _api_client()
    return await client.get_service(service_id)


@mcp.tool(
    name="import_text_knowledge",
    description="Import free-form text into the service knowledge base.",
)
async def import_text_knowledge(
    service_id: str,
    title: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = _api_client()
    return await client.import_text_knowledge(
        service_id=service_id,
        title=title,
        content=content,
        metadata=metadata,
    )


@mcp.tool(
    name="import_feishu_document",
    description="Import a Feishu document into the service knowledge base by URL or token.",
)
async def import_feishu_document(
    service_id: str,
    document: str,
    title: str | None = None,
) -> dict[str, Any]:
    client = _api_client()
    return await client.import_feishu_document(
        service_id=service_id,
        document=document,
        title=title,
    )


@mcp.tool(
    name="import_feishu_chat",
    description="Import Feishu group chat history into the knowledge base by chat_id.",
)
async def import_feishu_chat(
    service_id: str,
    chat_id: str,
    limit: int = 100,
) -> dict[str, Any]:
    client = _api_client()
    return await client.import_feishu_chat(
        service_id=service_id,
        chat_id=chat_id,
        limit=limit,
    )


@mcp.tool(
    name="import_feishu_image",
    description="Import a Feishu image asset into the knowledge base by image_key or message_id.",
)
async def import_feishu_image(
    service_id: str,
    image_key: str | None = None,
    message_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    client = _api_client()
    return await client.import_feishu_image(
        service_id=service_id,
        image_key=image_key,
        message_id=message_id,
        title=title,
    )


@mcp.tool(
    name="search_knowledge",
    description="Search the service knowledge base for relevant chunks.",
)
async def search_knowledge(
    service_id: str,
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    client = _api_client()
    return await client.search_knowledge(
        service_id=service_id,
        query=query,
        limit=limit,
    )


@mcp.tool(
    name="list_knowledge_sources",
    description="List imported knowledge sources for a service instance.",
)
async def list_knowledge_sources(service_id: str) -> dict[str, Any]:
    client = _api_client()
    return await client.list_knowledge_sources(service_id)


@mcp.tool(
    name="send_feishu_message",
    description="Send a text message to a Feishu group or user through a configured service instance.",
)
async def send_feishu_message(
    service_id: str,
    receive_id: str,
    text: str,
    receive_id_type: str = "chat_id",
) -> dict[str, Any]:
    client = _api_client()
    return await client.send_feishu_message(
        service_id=service_id,
        receive_id=receive_id,
        text=text,
        receive_id_type=receive_id_type,
    )


def main() -> None:
    if MCP_TRANSPORT not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("FEISHU_CHAT_MCP_TRANSPORT must be stdio, sse, or streamable-http.")
    mcp.run(transport=MCP_TRANSPORT)


if __name__ == "__main__":
    main()
# AI GC END
