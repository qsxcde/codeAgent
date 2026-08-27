"""usage behavior tests."""

from tests.session.behavior.fixtures import *  # noqa: F401,F403


def test_context_usage_properties_expose_latest_input_and_window():
    """会话暴露最近一次输入 token 与上下文窗口,不返回累计 usage。"""
    sess = _compact_session(
        FakeClient(response="答"),
        context_window=32_000,
    )

    assert sess.context_tokens is None
    assert sess.context_window == 32_000
    sess._last_input_tokens = 1_240
    assert sess.context_tokens == 1_240



async def test_successful_run_persists_usage():
    """成功轮:本轮聚合 usage(input/output/reasoning/cached)落库。"""
    store = MemoryStore()
    model = FakeClient(
        usage={
            "input_tokens": 100,
            "output_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 60},
        },
        responses=["回复"],
    )
    sess = _session(model, store=store)
    await (sess.run("hi"))
    total = store.load_usage(sess.session_id)
    assert total.input_tokens == 100
    assert total.output_tokens == 20
    assert total.cached_tokens == 60
    assert total.reasoning_tokens == 0



async def test_usage_aggregates_across_turns():
    """多轮成功:usage 跨轮累计(第二轮在首轮之上累加)。"""
    store = MemoryStore()
    model = FakeClient(
        usage={"input_tokens": 50, "output_tokens": 10},
        responses=["答1", "答2"],
    )
    sess = _session(model, store=store)
    await (sess.run("问1"))
    await (sess.run("问2"))
    total = store.load_usage(sess.session_id)
    assert total.input_tokens == 100
    assert total.output_tokens == 20



async def test_failed_turn_does_not_persist_usage():
    """失败轮:usage 不落库(与"未完成轮次永不落盘"同承诺)。"""
    store = MemoryStore()
    model = FakeClient(usage={"input_tokens": 99, "output_tokens": 1}, responses=["x"])
    sess = _session(model, store=store)
    # 强制失败:第一轮跑成功后清空 store,再用坏模型触发失败轮
    await (sess.run("成功"))
    assert store.load_usage(sess.session_id).input_tokens == 99

    class BoomModel(FakeClient):
        def _generate(self, messages, **kwargs):
            raise RuntimeError("boom")

    sess2 = _session(BoomModel(response="x"), store=store, session_id=sess.session_id)
    await (sess2.run("触发"))
    # 失败轮不追加:聚合仍是成功轮的值
    assert store.load_usage(sess.session_id).input_tokens == 99
    assert store.load_usage(sess.session_id).output_tokens == 1

