"""在工具执行前识别模型输出截断。"""

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage

from yuxi.models.output import check_output_complete


class OutputLimitMiddleware(AgentMiddleware):
    """拒绝截断响应，不重放已发生的工具副作用。"""

    def wrap_model_call(self, request, handler):
        """同步模型响应在进入工具节点前校验。"""
        response = handler(request)
        for message in response.result:
            if isinstance(message, AIMessage):
                check_output_complete(message)
        return response

    async def awrap_model_call(self, request, handler):
        """异步与流式合并响应使用同一完整性边界。"""
        response = await handler(request)
        for message in response.result:
            if isinstance(message, AIMessage):
                check_output_complete(message)
        return response
