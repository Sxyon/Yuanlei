"""Gemini 输出额度的必要兼容边界。"""

from langchain_google_genai import ChatGoogleGenerativeAI

from yuxi.models.output import output_limit_kwargs, validate_output_tokens


class GeminiChatAdapter(ChatGoogleGenerativeAI):
    """保留 SDK generation_config 优先级并校验最终输出额度。"""

    def _prepare_params(self, stop, generation_config=None, **kwargs):
        """在 SDK 合并调用参数后校验最大输出。"""
        maximum = (self.metadata or {}).get("yuxi_max_output_tokens")
        if isinstance(generation_config, dict):
            validate_output_tokens(
                generation_config.get("max_output_tokens"), field="max_output_tokens", maximum=maximum
            )
        kwargs = output_limit_kwargs("gemini", kwargs, None, maximum)
        if (
            isinstance(generation_config, dict)
            and generation_config.get("max_output_tokens") is not None
            and kwargs.get("max_output_tokens") is not None
            and generation_config["max_output_tokens"] != kwargs["max_output_tokens"]
        ):
            raise ValueError("输出上限参数冲突，请只指定一个输出额度")
        config = super()._prepare_params(stop, generation_config=generation_config, **kwargs)
        validate_output_tokens(config.max_output_tokens, field="max_output_tokens", maximum=maximum)
        return config
