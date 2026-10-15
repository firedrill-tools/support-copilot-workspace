"""Reject nonfinal model output before LangChain can dispatch proposal tools."""
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage,RemoveMessage
from langgraph.config import get_config


class ResponseBoundaryError(RuntimeError):
    def __init__(self, problem, observation):
        super().__init__(f"Support response did not complete: {problem}")
        self.observation = observation


class CompletedResponse(AgentMiddleware):
    def __init__(self, workspace):
        self.workspace = workspace

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
        rejected=[RemoveMessage(id=message.id) for message in state["messages"]
                  if isinstance(message,AIMessage) and message.id and self.problem(message)]
        return {"messages":rejected} if rejected else None

    async def abefore_model(self,state,runtime):
        return self.before_model(state,runtime)

    def after_model(self, state, runtime):
        message = state["messages"][-1]
        problem = self.problem(message)
        observation = {"source":"langchain_model_message", "sdk_message":message.model_dump(mode="json"),
            "sdk_usage":getattr(message,"usage_metadata",None), "reported_usage":None, "cost_usd":None,
            "accepted":problem is None,"protocol_error":problem}
        config = get_config()
        thread_id = config.get("configurable",{}).get("thread_id")
        self.workspace.observe_model(thread_id,observation)
        if problem:
            raise ResponseBoundaryError(problem,observation)

    async def aafter_model(self,state,runtime):
        return self.after_model(state,runtime)
