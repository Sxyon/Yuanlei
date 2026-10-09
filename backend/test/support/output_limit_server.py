"""只接收合成输入的输出上限协议接收端。"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

LONG_OUTPUT = "SYNTHETIC_LONG_OUTPUT " * 3000
REQUESTS = []
LOCK = Lock()


class OutputHandler(BaseHTTPRequestHandler):
    """发出受控结束原因，并捕获 SDK 最终请求。"""

    def log_message(self, *args):
        """测试服务不记录请求头或内容。"""

    def do_GET(self):  # noqa: N802
        """回读本测试服务已接收的合成请求。"""
        with LOCK:
            self._json({"requests": list(REQUESTS)})

    def do_POST(self):  # noqa: N802
        """分别响应原生 Anthropic 和 Chat Completions 协议。"""
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if request.get("model") != "output-test":
            self.send_error(422)
            return
        with LOCK:
            REQUESTS.append(request)
        serialized = json.dumps(request["messages"])
        case = next(
            (
                case
                for case in ("truncated_valid_tool", "truncated_tool", "context", "truncated", "tool")
                if f"OUTPUT_CASE:{case}" in serialized
            ),
            "normal",
        )
        anthropic = self.path.rstrip("/").endswith("/messages")
        has_tool_result = any(
            m.get("role") == "tool"
            or any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in m.get("content", [])
                if isinstance(m.get("content"), list)
            )
            for m in request["messages"]
        )
        tool = case in {"tool", "truncated_tool", "truncated_valid_tool"} and not has_tool_result
        truncated = case in {"truncated", "truncated_tool", "truncated_valid_tool", "context"}
        reason = (
            ("model_context_window_exceeded" if case == "context" else "max_tokens")
            if truncated
            else ("tool_use" if tool else "end_turn")
        )
        arguments = (
            '{"todos":'
            if case == "truncated_tool"
            else json.dumps({"todos": [{"content": "synthetic task", "status": "in_progress"}]})
        )
        tool_name, tool_id = "write_todos", "call-output"
        parent = re.search(r"OUTPUT_PARENT:([\w-]+)", serialized)
        tool_names = {item.get("function", {}).get("name") for item in request.get("tools", [])}
        parent_done = False
        if parent and "subagent_start" in tool_names:
            results = {m.get("tool_call_id"): m.get("content") for m in request["messages"] if m.get("role") == "tool"}
            truncated = False
            tool = "call-await" not in results
            parent_done = not tool
            reason = "tool_use" if tool else "end_turn"
            if "call-start" in results:
                tool_name, tool_id = "subagent_await", "call-await"
                arguments = json.dumps({"run_id": json.loads(results["call-start"])["run_id"]})
            else:
                tool_name, tool_id = "subagent_start", "call-start"
                arguments = json.dumps(
                    {
                        "subagent_slug": parent.group(1),
                        "description": "OUTPUT_CASE:truncated_tool TEST_TOKEN:"
                        + re.search(r"TEST_TOKEN:([\w-]+)", serialized).group(1),
                    }
                )
        text = LONG_OUTPUT if not tool else "partial tool"
        if parent_done:
            text = "子任务因输出截断失败；请检查部分输出后继续。"
        if anthropic:
            blocks = [{"type": "text", "text": text}]
            if tool:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": tool_name,
                        "input": {} if truncated else json.loads(arguments),
                    }
                )
            response = {
                "id": "msg-output",
                "type": "message",
                "role": "assistant",
                "model": "output-test",
                "content": blocks,
                "stop_reason": reason,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 32 if truncated else 6000},
            }
            if not request.get("stream"):
                self._json(response)
                return
            events = [
                (
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            **response,
                            "content": [],
                            "stop_reason": None,
                            "usage": {"input_tokens": 10, "output_tokens": 0},
                        },
                    },
                )
            ]
            for index, block in enumerate(blocks):
                start = {**block, "text": ""} if block["type"] == "text" else {**block, "input": {}}
                delta = (
                    {"type": "text_delta", "text": text}
                    if block["type"] == "text"
                    else {"type": "input_json_delta", "partial_json": arguments}
                )
                events.extend(
                    [
                        (
                            "content_block_start",
                            {"type": "content_block_start", "index": index, "content_block": start},
                        ),
                        ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": delta}),
                        ("content_block_stop", {"type": "content_block_stop", "index": index}),
                    ]
                )
            events.extend(
                [
                    (
                        "message_delta",
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": reason, "stop_sequence": None},
                            "usage": {"output_tokens": response["usage"]["output_tokens"]},
                        },
                    ),
                    ("message_stop", {"type": "message_stop"}),
                ]
            )
        else:
            finish = "length" if truncated else ("tool_calls" if tool else "stop")
            message = {"role": "assistant", "content": text}
            if tool:
                message["tool_calls"] = [
                    {
                        "id": tool_id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": arguments},
                    }
                ]
            base = {"id": "chat-output", "object": "chat.completion", "created": 0, "model": "output-test"}
            if not request.get("stream"):
                self._json(
                    {
                        **base,
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 6000, "total_tokens": 6010},
                    }
                )
                return
            if tool:
                message["tool_calls"][0]["index"] = 0
            events = [
                (None, {**base, "choices": [{"index": 0, "delta": message, "finish_reason": None}]}),
                (None, {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}),
            ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for event, data in events:
            prefix = f"event: {event}\n" if event else ""
            self.wfile.write(f"{prefix}data: {json.dumps(data)}\n\n".encode())
        if not anthropic:
            self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _json(self, data):
        """发送协议 JSON 结果。"""
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8766), OutputHandler).serve_forever()
