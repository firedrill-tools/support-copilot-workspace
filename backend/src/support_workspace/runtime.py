"""Own native clients and conversation checkpoints for one application lifespan."""
from contextlib import AsyncExitStack
import asyncio
import os
from urllib.parse import urlsplit

import httpx2
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from openai import OpenAI, AsyncOpenAI

from .agent import build_agent
from .evidence import ObservedTransport, ObservedAsyncTransport, execution_scope


class AgentRuntime:
    def __init__(self, workspace, *, sync_transport=None, async_transport=None):
        key = os.getenv("OPENAI_API_KEY")
        if not key or not key.strip():
            raise RuntimeError("OPENAI_API_KEY required for the support copilot")
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
        if not self.model_name.strip() or any(char.isspace() for char in self.model_name):
            raise ValueError("OPENAI_MODEL must be a model identifier")
        self.endpoint = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        url = urlsplit(self.endpoint)
        if not url.hostname or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"})) or url.username or url.password or url.query or url.fragment:
            raise ValueError("OPENAI_BASE_URL requires HTTPS or loopback HTTP without URL credentials/query/fragment")
        self.workspace, self.key = workspace, key
        self.sync_transport, self.async_transport = sync_transport, async_transport
        self.stack, self.closed = AsyncExitStack(), False
        self.checkpointer = None
        self.entered = False

    async def __aenter__(self):
        if self.entered or self.closed:
            raise RuntimeError("Support runtime cannot be entered twice")
        self.entered = True
        try:
            self.run_lock = asyncio.Lock()
            http = self.stack.enter_context(httpx2.Client(timeout=30, follow_redirects=False,
                transport=ObservedTransport(self.workspace, self.sync_transport if self.sync_transport is not None else httpx2.HTTPTransport(retries=0))))
            self.client = self.stack.enter_context(OpenAI(api_key=self.key, base_url=self.endpoint, max_retries=0, timeout=30, http_client=http))
            asynchronous = await self.stack.enter_async_context(httpx2.AsyncClient(timeout=30, follow_redirects=False,
                transport=ObservedAsyncTransport(self.workspace, self.async_transport if self.async_transport is not None else httpx2.AsyncHTTPTransport(retries=0))))
            self.async_client = await self.stack.enter_async_context(AsyncOpenAI(api_key=self.key, base_url=self.endpoint, max_retries=0, timeout=30, http_client=asynchronous))
            model = ChatOpenAI(model=self.model_name, api_key=self.key, base_url=self.endpoint,
                client=self.client.chat.completions, root_client=self.client,
                async_client=self.async_client.chat.completions, root_async_client=self.async_client,
                use_responses_api=False, timeout=30, max_retries=0, max_tokens=4096, store=False, cache=False, stream_usage=True,
                model_kwargs={"parallel_tool_calls": False})
            self.checkpointer = self.stack.enter_context(MemorySaver())
            self.graph = build_agent(self.workspace, model=model, checkpointer=self.checkpointer, require_provider=True)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, exc_type, exc_value, traceback):
        try:
            if self.checkpointer is not None:
                threads = {item.config["configurable"]["thread_id"] for item in self.checkpointer.list(None)}
                for thread_id in threads:
                    self.checkpointer.delete_thread(thread_id)
        finally:
            try:
                await self.stack.__aexit__(exc_type, exc_value, traceback)
            finally:
                self.closed = True

    def invoke(self, state, *, thread_id, run_id):
        if self.closed:
            raise RuntimeError("Support runtime is closed")
        with execution_scope(thread_id, run_id):
            return self.graph.invoke(state, config={"configurable": {"thread_id": thread_id}})

    async def ainvoke(self, state, *, thread_id, run_id):
        if self.closed:
            raise RuntimeError("Support runtime is closed")
        with execution_scope(thread_id, run_id):
            return await self.graph.ainvoke(state, config={"configurable": {"thread_id": thread_id}})
