"""Observe native JSON/SSE bytes without replacing SDK parsing or the agent."""
from contextlib import contextmanager
from contextvars import ContextVar
import base64
from hashlib import sha256
from importlib.metadata import version
import json
from time import perf_counter
from uuid import uuid4

import httpx2
from langgraph.config import get_config

execution = ContextVar("support_execution", default=None)
CAPTURE_LIMIT = 1024 * 1024


@contextmanager
def execution_scope(thread_id, run_id):
    token = execution.set({"thread_id": thread_id, "run_id": run_id})
    try:
        yield
    finally:
        execution.reset(token)


def correlation():
    context = execution.get()
    if context is not None:
        return dict(context)
    try:
        config = get_config()
    except RuntimeError:
        config = {}
    return {"thread_id": config.get("configurable", {}).get("thread_id"),
            "run_id": config.get("metadata", {}).get("support_run_id")}


class Capture:
    def __init__(self, workspace, request):
        self.workspace, self.started = workspace, perf_counter()
        self.raw, self.size, self.finished = bytearray(), 0, False
        self.digest = sha256()
        self.headers = {}
        try:
            requested_model=json.loads(request.content).get("model")
        except (ValueError,AttributeError):
            requested_model=None
        self.event = {"id": str(uuid4()), "source": "openai-http", **correlation(),
            "initial_state":workspace.snapshot(),"requested_model":requested_model,
            "sdk_version": version("openai"), "input_sha256": sha256(request.content).hexdigest(),
            "endpoint": {"scheme": request.url.scheme, "host": request.url.host, "port": request.url.port, "path": request.url.path},
            "http_status": None, "request_id": None, "response_id": None, "response_model": None,
            "stream": False, "transport_complete": False, "done_marker": False, "error_type": None,
            "raw_output": None, "capture_truncated": False, "capture_error": None,
            "reported_usage": None, "usage_reports": [], "usage_complete": False, "usage": None, "cost_usd": None}

    def response(self, response):
        self.headers = dict(response.headers)
        self.event.update(http_status=response.status_code, request_id=response.headers.get("x-request-id"),
                          stream="text/event-stream" in response.headers.get("content-type", "").lower())

    def add(self, chunk):
        self.size += len(chunk)
        self.digest.update(chunk)
        self.raw.extend(chunk[:max(0, CAPTURE_LIMIT - len(self.raw))])

    def finish(self, *, complete=False, error=None):
        if self.finished:
            return
        self.finished = True
        event = self.event
        event.update(transport_complete=complete, error_type=type(error).__name__ if error is not None else None,
                     wire_bytes=self.size, wire_sha256=self.digest.hexdigest(),
                     capture_truncated=self.size > CAPTURE_LIMIT, wall_ms=(perf_counter() - self.started) * 1000)
        # HTTPX's public response decoder handles the same content encodings as
        # the SDK's HTTP client. Headers/credentials are never dumped wholesale.
        bodies = []
        try:
            decoded = httpx2.Response(200, headers={key: value for key, value in self.headers.items() if key.lower() == "content-encoding"},
                                     content=bytes(self.raw)).content
            if len(decoded) > CAPTURE_LIMIT:
                event["capture_truncated"] = True
            text = decoded[:CAPTURE_LIMIT].decode("utf8")
            event["raw_output"] = text
            if text:
                if event["stream"]:
                    # Normalize CRLF before separating SSE events; chunk boundaries
                    # may split lines or UTF-8 characters arbitrarily.
                    for block in text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
                        data = "\n".join(line[5:].lstrip(" ") for line in block.splitlines() if line.startswith("data:"))
                        if not data:
                            continue
                        if data == "[DONE]":
                            event["done_marker"] = True
                            continue
                        bodies.append(json.loads(data))
                else:
                    bodies.append(json.loads(text))
        except (ValueError, UnicodeError, httpx2.DecodingError) as failure:
            event["capture_error"] = type(failure).__name__
            if event["raw_output"] is None:
                event["wire_capture_base64"]=base64.b64encode(self.raw).decode("ascii")
        for body in bodies:
            if not isinstance(body, dict):
                event["capture_error"] = "non_object_response"
                continue
            event["response_id"] = body.get("id", event["response_id"])
            event["response_model"] = body.get("model", event["response_model"])
            if body.get("error") is not None:
                event["provider_error"] = body["error"]
            if body.get("usage") is not None:
                event["usage_reports"].append(body["usage"])
        reports = event["usage_reports"]
        event["reported_usage"] = reports[-1] if reports else None
        usage = event["reported_usage"]
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        event["usage_complete"] = (len(reports) == 1 and not event["capture_truncated"] and
            isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0 for key in keys))
        if event["usage_complete"]:
            event["usage"] = {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"], "total_tokens": usage["total_tokens"]}
        self.workspace.observe_provider(event)


class SyncStream(httpx2.SyncByteStream):
    def __init__(self, stream, capture):
        self.stream, self.capture = stream, capture
        self.iterator = iter(stream)

    def __iter__(self):
        try:
            for chunk in self.iterator:
                self.capture.add(chunk)
                yield chunk
            self.capture.finish(complete=True)
        except BaseException as error:
            self.capture.finish(error=error)
            raise

    def close(self):
        try:
            self.stream.close()
        finally:
            self.capture.finish()


class AsyncStream(httpx2.AsyncByteStream):
    def __init__(self, stream, capture):
        self.stream, self.capture = stream, capture
        self.iterator = stream.__aiter__()

    async def __aiter__(self):
        try:
            async for chunk in self.iterator:
                self.capture.add(chunk)
                yield chunk
            self.capture.finish(complete=True)
        except BaseException as error:
            self.capture.finish(error=error)
            raise

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            self.capture.finish()


class ObservedTransport(httpx2.BaseTransport):
    def __init__(self, workspace, inner):
        self.workspace, self.inner = workspace, inner

    def handle_request(self, request):
        capture = Capture(self.workspace, request)
        try:
            response = self.inner.handle_request(request)
        except BaseException as error:
            capture.finish(error=error)
            raise
        capture.response(response)
        return httpx2.Response(response.status_code, headers=response.headers,
            stream=SyncStream(response.stream, capture), extensions=response.extensions)

    def close(self):
        self.inner.close()


class ObservedAsyncTransport(httpx2.AsyncBaseTransport):
    def __init__(self, workspace, inner):
        self.workspace, self.inner = workspace, inner

    async def handle_async_request(self, request):
        capture = Capture(self.workspace, request)
        try:
            response = await self.inner.handle_async_request(request)
        except BaseException as error:
            capture.finish(error=error)
            raise
        capture.response(response)
        return httpx2.Response(response.status_code, headers=response.headers,
            stream=AsyncStream(response.stream, capture), extensions=response.extensions)

    async def aclose(self):
        await self.inner.aclose()
