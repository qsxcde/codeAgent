"""SSE 解析器单元测试:边界帧、tool_calls 跨帧拼接、usage 独立帧、宽容处理。"""

from codeagent.ai.protocol.sse import SSEParser


def _frame(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False)


def test_content_and_finish_frames():
    parser = SSEParser()
    events = parser.feed(_frame({"choices": [{"delta": {"content": "你"}, "finish_reason": None}]}))
    assert len(events) == 1
    assert events[0].type == "content"
    assert events[0].text == "你"

    finish = parser.feed(_frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
    assert finish[0].type == "finish"
    assert finish[0].finish_reason == "stop"


def test_done_frame_returns_empty():
    parser = SSEParser()
    assert parser.feed("[DONE]") == []


def test_empty_and_non_json_frames_tolerated():
    parser = SSEParser()
    assert parser.feed("") == []
    assert parser.feed("   ") == []
    assert parser.feed("not-json") == []


def test_tool_call_arguments_accumulate_across_frames():
    """工具调用参数跨帧拼接:每一帧只来一段 arguments。"""
    parser = SSEParser()
    parser.feed(
        _frame(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"name": "read", "arguments": '{"file_'},
                                }
                            ]
                        }
                    }
                ]
            }
        )
    )
    parser.feed(
        _frame(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": 'path": "a.txt"}'}}
                            ]
                        }
                    }
                ]
            }
        )
    )
    calls = parser.assembled_tool_calls()
    assert len(calls) == 1
    assert calls[0]["name"] == "read"
    assert calls[0]["arguments"] == '{"file_path": "a.txt"}'
    assert parser.has_pending


def test_usage_in_independent_frame():
    """usage 可在独立帧(无 choices)出现。"""
    parser = SSEParser()
    events = parser.feed(
        _frame({"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
    )
    assert events[0].type == "usage"
    assert events[0].usage["total_tokens"] == 15


def test_thinking_content_extracted():
    """DeepSeek 的 reasoning_content 单独产出 thinking 事件。"""
    parser = SSEParser()
    events = parser.feed(_frame({"choices": [{"delta": {"reasoning_content": "让我想想"}}]}))
    assert events[0].type == "thinking"
    assert events[0].text == "让我想想"


def test_multiline_data_joined_before_parse():
    """SSE 规范:同一事件的 data 行用 \\n 拼接后再解析(不逐行截断)。

    模拟 OpenAICompatClient.stream 的拼接逻辑:多行 data → 一个完整 JSON。
    真实场景:供应商把一个长 JSON 帧拆成多行 data(行间换行在 JSON 结构边界)。
    """
    parser = SSEParser()
    # 模拟跨两行的 JSON(第一行是结构前半,第二行是结构后半,拼接后合法)
    line1 = '{"choices": [{"delta": {"content": "hello world"},'
    line2 = '"finish_reason": null}]}'
    joined = "\n".join([line1, line2])
    events = parser.feed(joined)
    assert len(events) == 1
    assert events[0].type == "content"
    assert events[0].text == "hello world"
