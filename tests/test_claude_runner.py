from feishu_claudecode_qiao.claude_runner import (
    ClaudeRunRequest,
    ClaudeRunResult,
    ConditionalClaudeRunner,
    FallbackClaudeRunner,
    OneShotClaudeRunner,
    PersistentClaudeRunner,
)
from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def test_one_shot_runner_delegates_to_callable_and_streams_text():
    seen_chunks = []

    def fake_call(prompt, session_id, *, cwd=None, permission_mode=None):
        assert prompt == "你好"
        assert session_id == "sid_1"
        assert cwd == "D:/work"
        assert permission_mode == "bypassPermissions"
        return "完成", "sid_2"

    runner = OneShotClaudeRunner(fake_call)
    result = runner.run(
        ClaudeRunRequest(
            prompt="你好",
            session_id="sid_1",
            cwd="D:/work",
            permission_mode="bypassPermissions",
            on_text=seen_chunks.append,
        )
    )

    assert result == ClaudeRunResult(text="完成", session_id="sid_2", error="")
    assert seen_chunks == ["完成"]


def test_one_shot_runner_returns_error_result_when_callable_fails():
    def fake_call(*args, **kwargs):
        raise RuntimeError("boom")

    runner = OneShotClaudeRunner(fake_call)
    result = runner.run(ClaudeRunRequest(prompt="hi"))

    assert result.text == ""
    assert result.session_id is None
    assert "boom" in result.error


def test_bridge_run_claude_respects_late_monkeypatch_of_call_claude(tmp_path, monkeypatch):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
        )
    )
    calls = []

    monkeypatch.setattr(
        bridge,
        "_call_claude",
        lambda prompt, session_id, **kwargs: calls.append((prompt, session_id, kwargs))
        or ("ok", "sid_2"),
    )

    reply, session_id = bridge._run_claude(
        "prompt",
        "sid_1",
        cwd="D:/work",
        permission_mode="bypassPermissions",
    )

    assert reply == "ok"
    assert session_id == "sid_2"
    assert calls == [
        (
            "prompt",
            "sid_1",
            {"cwd": "D:/work", "permission_mode": "bypassPermissions"},
        )
    ]


class RecordingRunner:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


def test_fallback_runner_uses_primary_when_it_succeeds():
    primary = RecordingRunner(ClaudeRunResult(text="primary", session_id="sid_p"))
    fallback = RecordingRunner(ClaudeRunResult(text="fallback", session_id="sid_f"))
    runner = FallbackClaudeRunner(primary, fallback)

    result = runner.run(ClaudeRunRequest(prompt="hi", session_key="chat:1"))

    assert result.text == "primary"
    assert result.session_id == "sid_p"
    assert len(primary.requests) == 1
    assert fallback.requests == []


def test_fallback_runner_uses_fallback_when_primary_errors():
    primary = RecordingRunner(ClaudeRunResult(text="", session_id="sid_1", error="sdk missing"))
    fallback = RecordingRunner(ClaudeRunResult(text="ok", session_id="sid_2"))
    runner = FallbackClaudeRunner(primary, fallback)

    result = runner.run(ClaudeRunRequest(prompt="hi", session_id="sid_1", session_key="chat:1"))

    assert result.text == "ok"
    assert result.session_id == "sid_2"
    assert len(primary.requests) == 1
    assert len(fallback.requests) == 1
    assert fallback.requests[0].prompt == "hi"
    assert fallback.requests[0].session_id == "sid_1"


class FakeSDKClient:
    created = []

    def __init__(self, *, options):
        self.options = options
        self.connected = False
        self.disconnected = False
        self.queries = []
        FakeSDKClient.created.append(self)

    async def connect(self):
        self.connected = True

    async def query(self, prompt):
        self.queries.append(prompt)

    def receive_response(self):
        async def iterator():
            yield {"type": "system", "session_id": "sid_sdk"}
            yield {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}}

        return iterator()

    async def disconnect(self):
        self.disconnected = True


class FakeSDKOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_persistent_runner_reuses_client_for_same_session_key():
    FakeSDKClient.created = []
    runner = PersistentClaudeRunner(
        client_cls=FakeSDKClient,
        options_cls=FakeSDKOptions,
        now=lambda: 100.0,
    )

    first = runner.run(ClaudeRunRequest(prompt="one", session_key="chat:1", cwd="D:/work"))
    second = runner.run(ClaudeRunRequest(prompt="two", session_key="chat:1", cwd="D:/work"))

    assert first.text == "hello"
    assert second.text == "hello"
    assert len(FakeSDKClient.created) == 1
    assert FakeSDKClient.created[0].queries == ["one", "two"]


def test_persistent_runner_returns_error_when_sdk_is_unavailable():
    runner = PersistentClaudeRunner(client_cls=None, options_cls=None, sdk_available=False)

    result = runner.run(ClaudeRunRequest(prompt="hi", session_key="chat:1"))

    assert result.text == ""
    assert "claude-agent-sdk" in result.error


def test_persistent_runner_closes_idle_workers():
    current_time = 0.0
    FakeSDKClient.created = []
    runner = PersistentClaudeRunner(
        client_cls=FakeSDKClient,
        options_cls=FakeSDKOptions,
        idle_ttl_seconds=10,
        now=lambda: current_time,
    )

    runner.run(ClaudeRunRequest(prompt="one", session_key="chat:1"))
    current_time = 20.0
    runner.cleanup_idle()

    assert FakeSDKClient.created[0].disconnected is True


def test_bridge_uses_persistent_runner_when_configured(tmp_path):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            claude_runner="persistent",
        )
    )

    assert isinstance(bridge.claude_runner, FallbackClaudeRunner)


def test_bridge_limits_persistent_runner_to_enabled_chats(tmp_path):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
            claude_runner="persistent",
            claude_persistent_enabled_chats=["chat:allowed"],
        )
    )

    assert isinstance(bridge.claude_runner, ConditionalClaudeRunner)
    assert bridge.claude_runner.enabled(ClaudeRunRequest(prompt="hi", session_key="chat:allowed"))
    assert not bridge.claude_runner.enabled(ClaudeRunRequest(prompt="hi", session_key="chat:other"))


def test_bridge_does_not_reuse_persistent_chat_worker_for_stateless_calls(tmp_path):
    bridge = Bridge(
        Config(
            feishu_app_id="cli_test",
            feishu_app_secret="secret",
            bridge_data_dir=str(tmp_path),
        )
    )
    requests = []

    class RecordingBridgeRunner:
        def run(self, request):
            requests.append(request)
            return ClaudeRunResult(text="ok", session_id=request.session_id or "new_sid")

    bridge.claude_runner = RecordingBridgeRunner()

    bridge._run_claude("work", "sid_1", session_key="chat:oc_1", chat_id="oc_1")
    bridge._run_claude("light", None, session_key="chat:oc_1", chat_id="oc_1")

    assert requests[0].session_key == "chat:oc_1"
    assert requests[0].session_id == "sid_1"
    assert requests[1].session_key == ""
    assert requests[1].session_id is None
    assert requests[1].chat_id == "oc_1"
