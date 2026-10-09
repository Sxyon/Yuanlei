"""Anthropic 调用时的输出额度边界。"""

from langchain_anthropic import ChatAnthropic

from yuxi.models.output import output_limit_kwargs, validate_output_tokens


class AnthropicChatAdapter(ChatAnthropic):
    """保留 SDK 行为，在最终请求处校验显式覆盖。"""

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        """调用时覆盖同样归一别名并受模型能力约束。"""
        maximum = (self.metadata or {}).get("yuxi_max_output_tokens")
        kwargs = output_limit_kwargs("anthropic", kwargs, None, maximum)
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        validate_output_tokens(payload.get("max_tokens"), field="max_tokens", maximum=maximum)
        return payload
