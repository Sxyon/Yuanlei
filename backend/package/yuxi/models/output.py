"""模型输出额度校验与供应商结束原因。"""

from langchain_core.exceptions import ModelError
from langchain_core.messages import AIMessage

OUTPUT_PARAMETERS = ("max_tokens", "max_completion_tokens", "max_output_tokens")


def validate_output_tokens(value, *, field: str, maximum: int | None = None) -> None:
    """在配置或调用边界拒绝非法输出额度。"""
    if value is None:
        return
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} 必须是正整数或 null")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field}={value} 超过模型最大输出 {maximum}")


def output_limit_kwargs(provider_type: str, kwargs: dict, default: int | None, maximum: int | None) -> dict:
    """统一输出参数别名，保留显式调用优先级。"""
    result = dict(kwargs)
    nested = dict(result.get("model_kwargs") or {})
    values = [source.pop(key) for source in (result, nested) for key in OUTPUT_PARAMETERS if key in source]
    explicit = [value for value in values if value is not None]
    for value in explicit:
        validate_output_tokens(value, field="输出上限", maximum=maximum)
    if len(set(explicit)) > 1:
        raise ValueError("输出上限参数冲突，请只指定一个输出额度")
    value = explicit[0] if explicit else default
    validate_output_tokens(value, field="输出上限", maximum=maximum)
    if "model_kwargs" in result:
        result["model_kwargs"] = nested
    extra = result.get("extra_body") or {}
    if any(key in extra for key in OUTPUT_PARAMETERS):
        raise ValueError("输出上限请使用调用参数，不要放入 extra_body")
    if value is not None:
        key = "max_output_tokens" if provider_type == "gemini" else "max_tokens"
        if provider_type in {"openai", "openrouter"} and "max_completion_tokens" in kwargs:
            key = "max_completion_tokens"
        result[key] = value
    return result


class ModelOutputTruncated(ModelError):
    """携带部分响应，阻止截断工具执行和自动重试。"""

    def __init__(self, message: AIMessage, reason: str):
        self.message = message
        self.reason = reason
        self.code = "model_context_window_exceeded" if reason == "model_context_window_exceeded" else "output_truncated"
        detail = "上下文窗口已耗尽" if self.code == "model_context_window_exceeded" else "本次模型输出达到生成上限"
        super().__init__(f"{detail}（{reason}），已保留部分输出。请检查已有产物并调整模型输出配置后继续。")


def check_output_complete(message: AIMessage) -> None:
    """按结束原因识别截断，不把正常工具调用当作失败。"""
    metadata = message.response_metadata
    reason = metadata.get("stop_reason") or metadata.get("finish_reason")
    if reason in {"max_tokens", "length", "MAX_TOKENS", "model_context_window_exceeded"}:
        raise ModelOutputTruncated(message, reason)
