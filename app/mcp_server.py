# AI GC START
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from app.services.mcp_scheduler import ScheduledTaskManager, SUPPORTED_SCHEDULED_ACTIONS
from app.services.service_api import FeishuChatServiceApiClient


MCP_TRANSPORT = os.environ.get("FEISHU_CHAT_MCP_TRANSPORT", "stdio")
MCP_HOST = os.environ.get("FEISHU_CHAT_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("FEISHU_CHAT_MCP_PORT", "9000"))


def _api_client() -> FeishuChatServiceApiClient:
    return FeishuChatServiceApiClient()


scheduler_manager = ScheduledTaskManager(api_client_factory=_api_client)


@asynccontextmanager
async def _mcp_lifespan(_: FastMCP):
    await scheduler_manager.start()
    try:
        yield
    finally:
        await scheduler_manager.stop()


mcp = FastMCP(
    name="Feishu Chat Service MCP",
    instructions=(
        "This MCP server exposes Feishu Chat Service capabilities, including service creation, "
        "knowledge-base ingestion/search, OpenAI-compatible question answering and image analysis, "
        "Feishu chat summarization, Feishu message sending, and internal scheduled task management."
    ),
    host=MCP_HOST,
    port=MCP_PORT,
    json_response=True,
    lifespan=_mcp_lifespan,
)


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


@mcp.tool(
    name="ask_llm_question",
    description="Call the configured OpenAI-compatible model for question answering, optionally with knowledge-base retrieval.",
)
async def ask_llm_question(
    service_id: str,
    question: str,
    use_knowledge_base: bool = True,
    knowledge_limit: int = 5,
    system_prompt_override: str | None = None,
) -> dict[str, Any]:
    client = _api_client()
    return await client.ask_with_llm(
        service_id=service_id,
        question=question,
        use_knowledge_base=use_knowledge_base,
        knowledge_limit=knowledge_limit,
        system_prompt_override=system_prompt_override,
    )


@mcp.tool(
    name="analyze_image_with_llm",
    description="Call the configured OpenAI-compatible multimodal model to analyze an image by URL, base64, image_key, or message_id.",
)
async def analyze_image_with_llm(
    service_id: str,
    prompt: str,
    image_url: str | None = None,
    image_base64: str | None = None,
    image_mime_type: str | None = None,
    image_key: str | None = None,
    message_id: str | None = None,
    use_knowledge_base: bool = False,
    knowledge_query: str | None = None,
    knowledge_limit: int = 5,
    system_prompt_override: str | None = None,
    save_analysis_to_knowledge_base: bool = False,
    analysis_title: str | None = None,
) -> dict[str, Any]:
    client = _api_client()
    return await client.analyze_image_with_llm(
        service_id=service_id,
        prompt=prompt,
        image_url=image_url,
        image_base64=image_base64,
        image_mime_type=image_mime_type,
        image_key=image_key,
        message_id=message_id,
        use_knowledge_base=use_knowledge_base,
        knowledge_query=knowledge_query,
        knowledge_limit=knowledge_limit,
        system_prompt_override=system_prompt_override,
        save_analysis_to_knowledge_base=save_analysis_to_knowledge_base,
        analysis_title=analysis_title,
    )


@mcp.tool(
    name="summarize_feishu_chat",
    description="Summarize a Feishu group chat through the configured model and optionally send the summary to a target.",
)
async def summarize_feishu_chat(
    service_id: str,
    chat_id: str,
    limit: int = 100,
    use_knowledge_base: bool = False,
    knowledge_query: str | None = None,
    knowledge_limit: int = 5,
    summary_prompt: str | None = None,
    system_prompt_override: str | None = None,
    send_to_receive_id: str | None = None,
    send_to_receive_id_type: str = "chat_id",
    save_summary_to_knowledge_base: bool = False,
    summary_title: str | None = None,
) -> dict[str, Any]:
    client = _api_client()
    return await client.summarize_feishu_chat(
        service_id=service_id,
        chat_id=chat_id,
        limit=limit,
        use_knowledge_base=use_knowledge_base,
        knowledge_query=knowledge_query,
        knowledge_limit=knowledge_limit,
        summary_prompt=summary_prompt,
        system_prompt_override=system_prompt_override,
        send_to_receive_id=send_to_receive_id,
        send_to_receive_id_type=send_to_receive_id_type,
        save_summary_to_knowledge_base=save_summary_to_knowledge_base,
        summary_title=summary_title,
    )


@mcp.tool(
    name="list_supported_scheduled_actions",
    description="List the action types supported by the internal MCP scheduler.",
)
def list_supported_scheduled_actions() -> dict[str, Any]:
    return {"items": SUPPORTED_SCHEDULED_ACTIONS}


@mcp.tool(
    name="create_interval_scheduled_task",
    description="Create an interval-based task inside the MCP server to periodically invoke a service action.",
)
def create_interval_scheduled_task(
    name: str,
    service_id: str,
    action_type: str,
    payload: dict[str, Any],
    interval_seconds: int,
    enabled: bool = True,
    run_immediately: bool = False,
) -> dict[str, Any]:
    task = scheduler_manager.create_interval_task(
        name=name,
        service_id=service_id,
        action_type=action_type,
        payload=payload,
        interval_seconds=interval_seconds,
        enabled=enabled,
        run_immediately=run_immediately,
    )
    return {"task": task}


@mcp.tool(
    name="list_scheduled_tasks",
    description="List scheduled tasks currently managed by the MCP server.",
)
def list_scheduled_tasks(service_id: str | None = None) -> dict[str, Any]:
    return {"items": scheduler_manager.list_tasks(service_id=service_id)}


@mcp.tool(
    name="get_scheduled_task",
    description="Get a single scheduled task by task_id.",
)
def get_scheduled_task(task_id: str) -> dict[str, Any]:
    return {"task": scheduler_manager.get_task(task_id)}


@mcp.tool(
    name="pause_scheduled_task",
    description="Pause a scheduled task so it stops running until resumed.",
)
def pause_scheduled_task(task_id: str) -> dict[str, Any]:
    return {"task": scheduler_manager.pause_task(task_id)}


@mcp.tool(
    name="resume_scheduled_task",
    description="Resume a paused scheduled task and recalculate its next run time.",
)
def resume_scheduled_task(task_id: str) -> dict[str, Any]:
    return {"task": scheduler_manager.resume_task(task_id)}


@mcp.tool(
    name="delete_scheduled_task",
    description="Delete a scheduled task from the MCP server.",
)
def delete_scheduled_task(task_id: str) -> dict[str, Any]:
    scheduler_manager.delete_task(task_id)
    return {"status": "deleted", "task_id": task_id}


@mcp.tool(
    name="run_scheduled_task_now",
    description="Execute a scheduled task immediately and update its execution state.",
)
async def run_scheduled_task_now(task_id: str) -> dict[str, Any]:
    task = await scheduler_manager.run_task_now(task_id)
    return {"task": task}


def main() -> None:
    if MCP_TRANSPORT not in {"stdio", "sse", "streamable-http"}:
        raise ValueError("FEISHU_CHAT_MCP_TRANSPORT must be stdio, sse, or streamable-http.")
    mcp.run(transport=MCP_TRANSPORT)


if __name__ == "__main__":
    main()
# AI GC END
