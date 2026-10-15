"""Reject nonfinal model output before LangChain can dispatch proposal tools."""
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage,RemoveMessage
from langgraph.config import get_config
from .evidence import correlation


class ResponseBoundaryError(RuntimeError):
    def __init__(self, problem, observation):
        super().__init__(f"Support response did not complete: {problem}")
        self.observation = observation


class CompletedResponse(AgentMiddleware):
    def __init__(self, workspace, *, require_provider=False):
        self.workspace = workspace
        self.require_provider = require_provider

    @staticmethod
    def problem(message):
        metadata = getattr(message,"response_metadata",{})
        finish = metadata.get("finish_reason")
        problem = None
        if not isinstance(message,AIMessage):
            problem = "missing_assistant_message"
        elif message.additional_kwargs.get("refusal") or message.invalid_tool_calls:
            problem = "refused_or_invalid_tool_output"
        elif message.tool_calls:
            if finish != "tool_calls":
                problem = "tool_response_not_completed"
            elif len(message.tool_calls) != 1:
                problem = "parallel_tool_calls_not_supported"
        elif finish != "stop" or not message.text.strip():
            problem = "answer_not_completed"
        return problem

    def before_model(self,state,runtime):
        # Rejected tool calls were never dispatched. Remove them from future
        # provider context so a later user turn has no unanswered tool-call ID.
        # Their original SDK message remains in the durable observation log.
        rejected_ids=self.workspace.rejected_message_ids(get_config().get("configurable",{}).get("thread_id"))
        rejected=[RemoveMessage(id=message.id) for message in state["messages"]
                  if isinstance(message,AIMessage) and message.id and (self.problem(message) or message.id in rejected_ids)]
        return {"messages":rejected} if rejected else None

    async def abefore_model(self,state,runtime):
        return self.before_model(state,runtime)

    def after_model(self, state, runtime):
        message = state["messages"][-1]
        problem = self.problem(message)
        context=correlation()
        provider=self.workspace.latest_provider(context["thread_id"],context["run_id"]) if self.require_provider else None
        if self.require_provider:
            if provider is None:
                problem=problem or "missing_http_observation"
            elif provider["http_status"]!=200 or provider.get("provider_error") or provider["capture_error"] or provider["capture_truncated"]:
                problem=problem or "invalid_http_observation"
            elif provider["error_type"] not in (None,"GeneratorExit"):
                problem=problem or "transport_did_not_complete"
            elif (provider["stream"] and not provider["done_marker"]) or (not provider["stream"] and not provider["transport_complete"]):
                problem=problem or "transport_did_not_complete"
        observation = {"source":"langchain_model_message", "sdk_message":message.model_dump(mode="json"),
            **context,"provider_observation_id":provider["id"] if provider else None,
            "sdk_usage":getattr(message,"usage_metadata",None), "reported_usage":provider["reported_usage"] if provider else None,
            "usage":provider["usage"] if provider else None,"cost_usd":None,
            "accepted":problem is None,"protocol_error":problem}
        config = get_config()
        thread_id = config.get("configurable",{}).get("thread_id")
        observation=self.workspace.observe_model(thread_id,observation)
        if problem:
            raise ResponseBoundaryError(problem,observation)

    async def aafter_model(self,state,runtime):
        return self.after_model(state,runtime)
