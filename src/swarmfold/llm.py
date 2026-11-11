"""Klien model HTTP langsung ke endpoint OpenAI-compatible, tanpa SDK.

Mengikuti ARCHITECTURE.md §4 dan PRD.md §11:

- selalu mengirim ``"stream": false``; gateway menjadikan SSE sebagai default dan
  akan membalas ``data: ...`` bila parameter ini tidak ada;
- ``timeout`` 600 detik karena satu panggilan terukur ± 140-160 detik;
- ``reasoning_content`` disimpan terpisah dan tidak pernah digabung ke ``content``;
- nama model yang dicatat adalah nama dari permintaan, bukan dari respons;
- retry untuk ``httpx.TransportError``, HTTP 5xx, dan status transien 408/429,
  maksimum ``max_retries`` kali dengan jeda 5 dan 15 detik; 4xx lain tidak
  pernah di-retry;
- ``Retry-After`` (bilangan bulat detik) pada respons 408/429 menggantikan jeda
  berikutnya, dibatasi 120 detik agar header nakal tidak menghentikan run.

API key tidak pernah masuk ke pesan error, log, atau ``repr``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

# Potongan body error yang boleh muncul di pesan; cukup untuk diagnosa, tidak
# cukup untuk membocorkan apa pun yang besar.
_BODY_PREVIEW = 300

# Status yang menandakan gangguan sementara di gateway, bukan permintaan salah.
_TRANSIENT_STATUS = frozenset({408, 429})

# Batas atas ``Retry-After``: gateway yang membalas angka besar tidak boleh
# membuat run 100+ panggilan tertahan berjam-jam.
_RETRY_AFTER_CAP_S = 120.0


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ModelTurn:
    content: str
    reasoning_content: str | None
    tool_calls: list[ToolCall]
    usage: dict
    latency_ms: int
    model_requested: str
    finish_reason: str | None


class ModelError(RuntimeError):
    """Panggilan model gagal dan tidak bisa dipulihkan dengan retry."""


def _host_only(url: str) -> str:
    """Host (dan port) saja, tanpa path, query, atau kredensial."""
    parts = urlsplit(url if "//" in url else "//" + url)
    host = parts.hostname or ""
    if parts.port is not None:
        return f"{host}:{parts.port}"
    return host


class ModelClient:
    """Satu panggilan ``chat`` = satu request HTTP (dengan retry internal).

    ``latency_ms`` pada :class:`ModelTurn` mengukur seluruh waktu dinding dari
    percobaan pertama sampai respons sukses diterima, termasuk jeda retry. Ini
    angka yang dipakai untuk estimasi waktu run, bukan latensi satu percobaan.

    Status 408 (request timeout) dan 429 (rate limit) bersifat **transien**:
    keduanya di-retry seperti 5xx, karena satu batas laju dari gateway tidak
    boleh mengakhiri run panjang. Bila respons transien membawa header
    ``Retry-After`` berupa bilangan bulat detik, nilai itu dipakai sebagai jeda
    berikutnya, dibatasi ``_RETRY_AFTER_CAP_S`` detik. 4xx lain (400, 401, 403,
    404, 422) tetap gagal seketika karena mengulang tidak akan menolong.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float = 600.0,
        max_retries: int = 2,
        retry_delays: tuple[float, ...] = (5.0, 15.0),
        empty_delays: tuple[float, ...] = (10.0, 30.0, 60.0),
        transport: httpx.BaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_s = timeout_s
        self._max_retries = max(0, int(max_retries))
        self._retry_delays = tuple(retry_delays)
        self._empty_delays = tuple(empty_delays)
        self._transport = transport

    def __repr__(self) -> str:
        return f"ModelClient(model={self._model!r}, host={_host_only(self._base_url)!r})"

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ModelTurn:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            # Wajib: tanpa ini gateway membalas SSE, bukan JSON.
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            # Loop ini digerakkan tool: turn tanpa tool call tidak menambah apa pun,
            # dan model yang memilih menjawab prosa akan menghentikan run. Gateway
            # OpenAI-compatible menerima "required", jadi minta tool secara eksplisit.
            payload["tool_choice"] = "required"

        body = json.dumps(payload, ensure_ascii=False)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"

        started = time.perf_counter()
        http_failures = 0
        empty_responses = 0
        with httpx.Client(transport=self._transport, timeout=self._timeout_s) as client:
            while True:
                try:
                    response = client.post(url, content=body, headers=headers)
                except httpx.TransportError as exc:
                    if http_failures >= self._max_retries:
                        raise ModelError(
                            f"koneksi ke model gagal setelah {http_failures + 1} percobaan: "
                            f"{type(exc).__name__}: {exc}"
                        ) from exc
                    time.sleep(self._delay(http_failures))
                    http_failures += 1
                    continue

                if response.status_code >= 500 or response.status_code in _TRANSIENT_STATUS:
                    if http_failures >= self._max_retries:
                        raise ModelError(self._http_message(response))
                    if response.status_code in _TRANSIENT_STATUS:
                        time.sleep(self._retry_after(response, http_failures))
                    else:
                        time.sleep(self._delay(http_failures))
                    http_failures += 1
                    continue

                if response.status_code >= 400:
                    # 4xx lain adalah kesalahan permintaan; mengulang tidak akan menolong.
                    raise ModelError(self._http_message(response))

                latency_ms = int(round((time.perf_counter() - started) * 1000))
                turn = self._parse(response, latency_ms)
                if turn.content.strip() or turn.reasoning_content or turn.tool_calls:
                    return turn
                # Pesan yang benar-benar kosong (tanpa prosa, tanpa penalaran,
                # tanpa tool call) bukan jawaban: itu model yang tidak
                # menghasilkan apa pun. Run 2026-11-11-eec3dc mati di F5 dan
                # 3286e5 mati di F2 karena tiga balasan kosong berurutan,
                # padahal permintaan yang sama dengan prompt 140 ribu token
                # dijawab normal. Dua percobaan ulang menutup gangguan sesaat;
                # bila tetap kosong, giliran kosong dikembalikan ke loop supaya
                # ia men-nudge dengan pesan baru, yang mengubah prompt dan
                # memutus determinisme balasan kosong (b7f451: empat percobaan
                # identik, empat-empatnya kosong).
                empty_responses += 1
                if empty_responses > len(self._empty_delays):
                    return turn
                time.sleep(self._empty_delays[empty_responses - 1])

        # Tidak tercapai: loop selalu return atau raise.
        raise ModelError("panggilan model berakhir tanpa respons")  # pragma: no cover

    def _delay(self, retry_index: int) -> float:
        if not self._retry_delays:
            return 0.0
        if retry_index < len(self._retry_delays):
            return self._retry_delays[retry_index]
        return self._retry_delays[-1]

    def _retry_after(self, response: httpx.Response, retry_index: int) -> float:
        """Jeda berikutnya: ``Retry-After`` bila valid, selain itu jadwal biasa."""
        raw = response.headers.get("retry-after")
        if raw is not None:
            try:
                seconds = int(raw.strip())
            except ValueError:
                # Format tanggal HTTP atau sampah: abaikan, pakai jadwal biasa.
                pass
            else:
                if seconds >= 0:
                    return min(float(seconds), _RETRY_AFTER_CAP_S)
        return self._delay(retry_index)

    @staticmethod
    def _http_message(response: httpx.Response) -> str:
        preview = response.text[:_BODY_PREVIEW]
        return f"model endpoint membalas HTTP {response.status_code}: {preview!r}"

    def _parse(self, response: httpx.Response, latency_ms: int) -> ModelTurn:
        try:
            data = response.json()
        except ValueError as exc:
            preview = response.text[:120].replace("\n", " ")
            raise ModelError(
                "respons bukan JSON (gateway mengabaikan stream: false dan membalas SSE?): "
                f"{preview!r}"
            ) from exc

        if not isinstance(data, dict):
            raise ModelError(f"respons bukan JSON objek: {str(data)[:120]!r}")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelError(f"respons tidak memuat choices: {str(data)[:_BODY_PREVIEW]!r}")

        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}

        raw_content = message.get("content")
        content = "" if raw_content is None else str(raw_content)
        raw_reasoning = message.get("reasoning_content")
        reasoning = None if raw_reasoning is None else str(raw_reasoning)

        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise ModelError("tool_calls pada respons bukan daftar")
        tool_calls = [self._parse_tool_call(raw) for raw in raw_calls]

        usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        usage = {
            "prompt_tokens": int(usage_raw.get("prompt_tokens") or 0),
            "completion_tokens": int(usage_raw.get("completion_tokens") or 0),
        }

        raw_finish = choice.get("finish_reason")
        return ModelTurn(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
            usage=usage,
            latency_ms=latency_ms,
            # Nama dari respons diabaikan: gateway menggantinya.
            model_requested=self._model,
            finish_reason=None if raw_finish is None else str(raw_finish),
        )

    @staticmethod
    def _parse_tool_call(raw: Any) -> ToolCall:
        if not isinstance(raw, dict):
            raise ModelError(f"tool_call bukan objek: {str(raw)[:120]!r}")

        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        name = str(function.get("name") or "")
        if not name:
            raise ModelError("tool_call tanpa nama fungsi")

        arguments_raw = function.get("arguments")
        if arguments_raw is None or arguments_raw == "":
            arguments: dict = {}
        elif isinstance(arguments_raw, dict):
            # Sebagian gateway mengirim objek, bukan string JSON.
            arguments = arguments_raw
        elif isinstance(arguments_raw, str):
            try:
                arguments = json.loads(arguments_raw)
            except json.JSONDecodeError as exc:
                raise ModelError(
                    f"argumen tool {name!r} bukan JSON valid: {arguments_raw[:_BODY_PREVIEW]!r}"
                ) from exc
            if not isinstance(arguments, dict):
                raise ModelError(
                    f"argumen tool {name!r} bukan objek JSON: {arguments_raw[:_BODY_PREVIEW]!r}"
                )
        else:
            raise ModelError(f"argumen tool {name!r} bukan string JSON: {type(arguments_raw).__name__}")

        return ToolCall(id=str(raw.get("id") or ""), name=name, arguments=arguments)
