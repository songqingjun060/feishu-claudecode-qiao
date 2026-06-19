import json
import subprocess
import sys
import types

from feishu_claudecode_qiao.bridge import Bridge
from feishu_claudecode_qiao.config import Config


def make_bridge(tmp_path, **kwargs):
    config_kwargs = {
        "feishu_app_id": "cli_test",
        "feishu_app_secret": "secret",
        "bridge_data_dir": str(tmp_path),
        "whisper_load_policy": "lazy",
        "claude_command": "claude",
    }
    config_kwargs.update(kwargs)
    return Bridge(Config(
        **config_kwargs,
    ))


class FakeStdout:
    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)


class FakeStderr:
    def read(self):
        return ""


class FakeProc:
    def __init__(self, lines):
        self.stdin = self
        self.stdout = FakeStdout(lines)
        self.stderr = FakeStderr()
        self.returncode = 0
        self.written = ""

    def write(self, value):
        self.written += value

    def close(self):
        return None

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


def test_call_claude_reads_stream_json_incrementally_and_logs_preview(tmp_path, monkeypatch, capsys):
    bridge = make_bridge(tmp_path, bridge_console_claude_stream=True)
    lines = [
        json.dumps({"type": "system", "session_id": "sid_new"}) + "\n",
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "你好"},
            },
        }) + "\n",
        json.dumps({
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "，世界"},
            },
        }) + "\n",
        json.dumps({"type": "result", "result": "你好，世界"}) + "\n",
    ]
    fake_proc = FakeProc(lines)

    monkeypatch.setattr(bridge, "_find_claude_cli", lambda: "claude")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_proc)

    reply, session_id = bridge._call_claude("ping", None)

    assert reply == "你好，世界"
    assert session_id == "sid_new"
    output = capsys.readouterr().out
    assert "🧠 Claude 思考中..." in output
    assert "你好，世界" in output


def test_run_claude_persistent_prints_thinking_banner(tmp_path, capsys):
    bridge = make_bridge(tmp_path, bridge_console_claude_stream=True)

    class FakeRunner:
        def run(self, request):
            return types.SimpleNamespace(
                text="ok",
                session_id="sid_new",
                error=None,
                reused_worker=True,
                startup_injected=False,
            )

    bridge.claude_runner = FakeRunner()

    reply, session_id = bridge._run_claude(
        "ping",
        None,
        session_key="chat:oc_1",
        chat_id="oc_1",
    )

    assert reply == "ok"
    assert session_id == "sid_new"
    assert "🧠 Claude 思考中..." in capsys.readouterr().out


def test_call_claude_uses_result_when_stream_is_empty(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, bridge_console_claude_stream=False)
    fake_proc = FakeProc([
        json.dumps({"type": "system", "session_id": "sid_new"}) + "\n",
        json.dumps({"type": "result", "result": "最终结果"}) + "\n",
    ])

    monkeypatch.setattr(bridge, "_find_claude_cli", lambda: "claude")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: fake_proc)

    reply, session_id = bridge._call_claude("ping", None)

    assert reply == "最终结果"
    assert session_id == "sid_new"


def test_process_audio_reuses_whisper_model_and_forces_chinese(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path)
    calls = install_fake_audio_stack(bridge, monkeypatch)

    first = bridge._process_audio("om_audio_1", {"file_key": "file_1"})
    second = bridge._process_audio("om_audio_2", {"file_key": "file_2"})

    assert first == "简体中文"
    assert second == "简体中文"
    assert [call[0] for call in calls].count("init") == 1
    transcribe_calls = [call for call in calls if call[0] == "transcribe"]
    assert transcribe_calls
    assert all(call[1]["language"] == "zh" for call in transcribe_calls)


def install_fake_audio_stack(bridge, monkeypatch):
    bridge._token = "tenant_token"
    bridge._token_expires = 9999999999

    class FakeResponse:
        status_code = 200
        content = b"audio"

    monkeypatch.setattr(
        "feishu_claudecode_qiao.bridge.requests.get",
        lambda *args, **kwargs: FakeResponse(),
    )

    calls = []

    class FakeModel:
        def __init__(self, name, device, compute_type):
            calls.append(("init", name, device, compute_type))

        def transcribe(self, path, **kwargs):
            calls.append(("transcribe", kwargs))
            segment = types.SimpleNamespace(text="简体中文")
            return [segment], object()

    fake_module = types.SimpleNamespace(WhisperModel=FakeModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    return calls


def test_whisper_preload_policy_loads_model_on_bridge_start(tmp_path, monkeypatch):
    calls = []

    class FakeModel:
        def __init__(self, name, device, compute_type):
            calls.append(("init", name, device, compute_type))

        def transcribe(self, path, **kwargs):
            return [types.SimpleNamespace(text="简体中文")], object()

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeModel))

    bridge = make_bridge(tmp_path, whisper_load_policy="preload")

    assert bridge._whisper_model is not None
    assert [call[0] for call in calls] == ["init"]


def test_whisper_per_call_policy_does_not_cache_model(tmp_path, monkeypatch):
    bridge = make_bridge(tmp_path, whisper_load_policy="per_call")
    calls = install_fake_audio_stack(bridge, monkeypatch)

    first = bridge._process_audio("om_audio_1", {"file_key": "file_1"})
    second = bridge._process_audio("om_audio_2", {"file_key": "file_2"})

    assert first == "简体中文"
    assert second == "简体中文"
    assert [call[0] for call in calls].count("init") == 2
    assert bridge._whisper_model is None
