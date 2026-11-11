"""Tes klien model memakai ``httpx.MockTransport``; tidak ada jaringan.

Kontrak yang diuji berasal dari ARCHITECTURE.md §4 dan PRD.md §11.
"""

from __future__ import annotations

import json

import httpx
import pytest

import swarmfold.llm as llm_module
from swarmfold.llm import ModelClient, ModelError, ToolCall

BASE_URL = "http://model.local:8080/v1"
API_KEY = "sk-rahasia-jangan-bocor"
MODEL = "ag/gemini-3.8-flash-high"


def _client(handler, **kwargs) -> ModelClient:
    return ModelClient(
        BASE_URL, API_KEY, MODEL, transport=httpx.MockTransport(handler), **kwargs
    )


def _ok_body(**message_fields) -> dict:
    message = {"role": "assistant", "content": "selesai"}
    message.update(message_fields)
    return {
        "id": "chatcmpl-1",
        # Gateway mengganti nama model; klien harus mengabaikannya.
        "model": "gemini-3.8-flash-n",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def _json_response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def test_request_memuat_stream_false_model_dan_bearer() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        seen["content_type"] = request.headers.get("content-type")
        seen["url"] = str(request.url)
        return _json_response(_ok_body())

    turn = _client(handler).chat([{"role": "user", "content": "halo"}])

    assert seen["body"]["stream"] is False
    assert seen["body"]["model"] == MODEL
    assert seen["body"]["messages"] == [{"role": "user", "content": "halo"}]
    assert "tools" not in seen["body"]
    assert seen["auth"] == f"Bearer {API_KEY}"
    assert seen["content_type"] == "application/json"
    assert seen["url"] == f"{BASE_URL}/chat/completions"
    assert turn.content == "selesai"
    assert turn.model_requested == MODEL
    assert turn.usage == {"prompt_tokens": 11, "completion_tokens": 7}
    assert turn.finish_reason == "stop"


def test_tools_dikirim_hanya_saat_diberikan() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _json_response(_ok_body())

    client = _client(handler)
    tools = [{"type": "function", "function": {"name": "run_cell", "parameters": {}}}]
    client.chat([{"role": "user", "content": "tulis cell"}], tools=tools)

    assert bodies[0]["tools"] == tools
    assert bodies[0]["tool_choice"] == "required"


def test_reasoning_content_tetap_terpisah_dari_content() -> None:
    body = _ok_body(reasoning_content="pertimbangan internal yang panjang")

    turn = _client(lambda request: _json_response(body)).chat(
        [{"role": "user", "content": "halo"}]
    )

    assert turn.content == "selesai"
    assert turn.reasoning_content == "pertimbangan internal yang panjang"
    assert "pertimbangan" not in turn.content


def test_dua_tool_call_dengan_argumen_json_string_diparse() -> None:
    calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "run_cell",
                "arguments": json.dumps({"code": "df.shape", "intent": "cek ukuran"}),
            },
        },
        {
            "id": "call_2",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"path": "notes/a.md", "content": "halo"}),
            },
        },
    ]
    body = _ok_body(content=None, tool_calls=calls)
    body["choices"][0]["finish_reason"] = "tool_calls"

    turn = _client(lambda request: _json_response(body)).chat(
        [{"role": "user", "content": "halo"}]
    )

    assert turn.content == ""
    assert turn.finish_reason == "tool_calls"
    assert turn.tool_calls == [
        ToolCall(id="call_1", name="run_cell", arguments={"code": "df.shape", "intent": "cek ukuran"}),
        ToolCall(id="call_2", name="write_file", arguments={"path": "notes/a.md", "content": "halo"}),
    ]


def test_argumen_tool_bukan_json_menyebut_nama_tool() -> None:
    body = _ok_body(
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "run_cell", "arguments": "{code: rusak"},
            }
        ]
    )

    with pytest.raises(ModelError) as excinfo:
        _client(lambda request: _json_response(body)).chat([{"role": "user", "content": "x"}])

    assert "run_cell" in str(excinfo.value)
    assert "JSON" in str(excinfo.value)


def test_dua_kali_500_lalu_200_retry_tepat_dua_kali() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        if count["n"] <= 2:
            return httpx.Response(500, text="gateway sibuk")
        return _json_response(_ok_body())

    turn = _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    # Tiga percobaan = dua retry.
    assert count["n"] == 3
    assert turn.content == "selesai"
    assert turn.latency_ms >= 0


def test_500_habis_retry_menjadi_model_error() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return httpx.Response(503, text="tidak tersedia")

    with pytest.raises(ModelError) as excinfo:
        _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    assert count["n"] == 3
    assert "503" in str(excinfo.value)
    assert "tidak tersedia" in str(excinfo.value)


def test_400_langsung_gagal_tanpa_retry() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return httpx.Response(400, text="model tidak dikenal")

    with pytest.raises(ModelError) as excinfo:
        _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    assert count["n"] == 1
    message = str(excinfo.value)
    assert "400" in message
    assert "model tidak dikenal" in message
    assert API_KEY not in message


def test_429_lalu_200_berhasil_tepat_dua_panggilan() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        if count["n"] == 1:
            return httpx.Response(429, text="terlalu banyak permintaan")
        return _json_response(_ok_body())

    turn = _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    assert count["n"] == 2
    assert turn.content == "selesai"


def test_429_retry_after_dipakai_tanpa_sleep_sungguhan(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", sleeps.append)
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        if count["n"] == 1:
            return httpx.Response(429, text="lambat", headers={"Retry-After": "7"})
        return _json_response(_ok_body())

    _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    # Header menggantikan jadwal retry_delays, bukan ditambahkan.
    assert sleeps == [7.0]


def test_429_habis_retry_menjadi_model_error() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return httpx.Response(429, text="batas laju")

    with pytest.raises(ModelError) as excinfo:
        _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    assert count["n"] == 3
    message = str(excinfo.value)
    assert "429" in message
    assert "batas laju" in message
    assert API_KEY not in message


def test_401_langsung_gagal_tanpa_retry() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return httpx.Response(401, text="kunci tidak sah")

    with pytest.raises(ModelError) as excinfo:
        _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    assert count["n"] == 1
    assert "401" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_body_sse_menjadi_model_error_yang_menyebut_json() -> None:
    sse = 'data: {"choices": [{"message": {"content": "halo"}}]}\n\ndata: [DONE]\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    with pytest.raises(ModelError) as excinfo:
        _client(handler).chat([{"role": "user", "content": "halo"}])

    assert "JSON" in str(excinfo.value)


def test_usage_hilang_menjadi_nol() -> None:
    body = _ok_body()
    del body["usage"]

    turn = _client(lambda request: _json_response(body)).chat(
        [{"role": "user", "content": "halo"}]
    )

    assert turn.usage == {"prompt_tokens": 0, "completion_tokens": 0}


def test_repr_tidak_memuat_api_key() -> None:
    client = _client(lambda request: _json_response(_ok_body()))

    text = repr(client)

    assert API_KEY not in text
    assert MODEL in text
    assert "model.local:8080" in text
    assert "/v1" not in text


def _empty_body() -> dict:
    """Balasan gateway yang diterima tetapi tidak memuat apa pun."""
    return {
        "id": "chatcmpl-kosong",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": None}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 110097, "completion_tokens": 0},
    }


def test_balasan_kosong_diulang_lalu_berhasil() -> None:
    # Run 2026-11-11-eec3dc mati di F5 karena tiga balasan kosong berurutan.
    # Balasan kosong bukan jawaban; ia gangguan gateway yang boleh diulang.
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        if count["n"] == 1:
            return _json_response(_empty_body())
        return _json_response(_ok_body())

    turn = _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    assert count["n"] == 2
    assert turn.content == "selesai"


def test_balasan_kosong_terus_menjadi_model_error() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return _json_response(_empty_body())

    with pytest.raises(ModelError) as excinfo:
        _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    assert count["n"] == 3
    assert "kosong" in str(excinfo.value)
    assert "110097" in str(excinfo.value)


def test_balasan_dengan_penalaran_saja_tidak_dianggap_kosong() -> None:
    count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        count["n"] += 1
        return _json_response(_ok_body(content=None, reasoning_content="mempertimbangkan"))

    turn = _client(handler, retry_delays=(0, 0)).chat([{"role": "user", "content": "halo"}])

    assert count["n"] == 1
    assert turn.reasoning_content == "mempertimbangkan"
