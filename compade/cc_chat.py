"""Claude Code stream-json sohbet turu."""
import json
import subprocess
import threading
import time
import re

from .engine import exe_claude, kill_tree


class CCTurn:
    def __init__(self, timeout=600, popen=None):
        self.timeout = timeout
        self._popen = popen or subprocess.Popen
        self.proc = None
        self.thread = None
        self.cancelled = False
        self.argv = None

    def start(self, text, cwd, session_id=None, model="default", effort=None,
              mode="plan", allowed=None, on_event=None, system_prompt=None):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Tur zaten çalışıyor")
        self.cancelled = False
        self.thread = threading.Thread(target=self._run, args=(text, cwd, session_id, model,
            effort, mode, allowed, on_event or (lambda event: None), system_prompt), daemon=True)
        self.thread.start()
        return self

    @staticmethod
    def clean_text(text):
        text = CCTurn.normalize_text(text)
        return re.sub(r"```compade-(?:plan|decision|questions)\s*.*?```", "", text or "", flags=re.S).strip()

    @staticmethod
    def normalize_text(value):
        """Claude content alanlarını UI ve geçmiş için düz metne indirger."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return CCTurn.normalize_text(value.get("text", ""))
        if isinstance(value, (list, tuple)):
            return "".join(CCTurn.normalize_text(item) for item in value)
        return ""

    def _run(self, text, cwd, session_id, model, effort, mode, allowed, emit, system_prompt):
        exe = exe_claude()
        if not exe:
            emit({"type": "cc_error", "error": "Claude Code bulunamadı (claude CLI PATH içinde değil)."})
            return
        cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages"]
        if session_id:
            cmd += ["--resume", session_id]
        if model and model != "default":
            cmd += ["--model", model]
        if effort:
            cmd += ["--effort", effort]
        cmd += ["--permission-mode", mode]
        # -p kipinde AskUserQuestion yanıt alamaz; şef sorularını compade-questions bloğuyla sorar
        cmd += ["--disallowedTools", "AskUserQuestion"]
        for item in allowed or []:
            cmd += ["--allowedTools", item]
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        self.argv = cmd
        started = time.monotonic()
        msg_id, session, final_text, result_seen = None, session_id, "", False
        tools, input_parts, emitted = {}, {}, set()   # emitted: akışta bildirilen araç id'leri (assistant iletisinde tekrar bildirme)
        try:
            self.proc = self._popen(cmd, cwd=str(cwd or "."), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            self.proc.stdin.write(text)
            self.proc.stdin.close()
            stderr = []
            err_thread = threading.Thread(target=lambda: stderr.extend(self.proc.stderr.readlines()), daemon=True)
            err_thread.start()
            for line in self.proc.stdout:
                if self.cancelled:
                    break
                if time.monotonic() - started > self.timeout:
                    self.cancel()
                    emit({"type": "cc_error", "error": "Claude sohbet zaman aşımına uğradı."})
                    return
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                typ = obj.get("type")
                if typ == "system" and obj.get("subtype") == "init":
                    session = obj.get("session_id") or session
                    emit({"type": "cc_start", "session_id": session, "model": obj.get("model")})
                elif typ == "rate_limit_event":
                    info = obj.get("rate_limit_info", {})
                    if info.get("status") in ("allowed_warning", "rejected"):
                        emit({"type": "cc_limit", "info": info})
                elif typ == "stream_event":
                    event = obj.get("event", {})
                    if event.get("type") == "message_start":
                        msg_id = (event.get("message") or {}).get("id") or obj.get("api_message_id")
                        final_text = ""
                    elif event.get("type") == "content_block_start":
                        block = event.get("content_block") or {}
                        idx = event.get("index")
                        if block.get("type") == "tool_use":
                            tools[idx] = {"id": block.get("id"), "name": block.get("name"), "input": block.get("input") or {}}
                            input_parts[idx] = ""
                    elif event.get("type") == "content_block_delta":
                        delta = event.get("delta") or {}
                        kind = delta.get("type")
                        if kind in ("text_delta", "thinking_delta"):
                            value = delta.get("text") or delta.get("thinking") or ""
                            if kind == "text_delta":
                                final_text += value
                            emit({"type": "cc_text" if kind == "text_delta" else "cc_thinking", "msg": msg_id, "delta": value})
                        elif kind == "input_json_delta":
                            input_parts[event.get("index")] = input_parts.get(event.get("index"), "") + (delta.get("partial_json") or "")
                    elif event.get("type") == "content_block_stop":
                        idx = event.get("index")
                        if idx in tools:
                            raw = input_parts.get(idx, "")
                            try:
                                tools[idx]["input"] = json.loads(raw) if raw else tools[idx]["input"]
                            except ValueError:
                                tools[idx]["input"] = raw
                            emitted.add(tools[idx].get("id"))
                            emit({"type": "cc_tool", **tools[idx], "status": "running"})
                    elif event.get("type") == "message_stop" and final_text:
                        emit({"type": "cc_assistant_done", "msg": msg_id, "text": self.clean_text(final_text), "raw_text": final_text})
                elif typ == "assistant":
                    msg = obj.get("message") or {}
                    msg_id = msg.get("id") or msg_id
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_use":
                            tools[block.get("id")] = block
                            if block.get("id") in emitted:
                                continue
                            emitted.add(block.get("id"))
                            emit({"type": "cc_tool", "id": block.get("id"), "name": block.get("name"), "input": block.get("input", {}), "status": "running"})
                elif typ == "user":
                    for block in (obj.get("message") or {}).get("content", []):
                        if block.get("type") == "tool_result":
                            content = block.get("content", "")
                            content = self.normalize_text(content)
                            if len(content) > 4000: content = content[:4000] + "…kısaltıldı"
                            emit({"type": "cc_tool_result", "id": block.get("tool_use_id"), "ok": not block.get("is_error", False), "content": content})
                elif typ == "result":
                    result_seen = True
                    session = obj.get("session_id") or session
                    usage = obj.get("usage") or {}
                    emit({"type": "cc_result", "ok": not obj.get("is_error", False), "session_id": session,
                        "cost_usd": obj.get("total_cost_usd"), "duration_ms": obj.get("duration_ms"),
                        "usage": {"in": usage.get("input_tokens", 0), "out": usage.get("output_tokens", 0),
                                  "cache_read": usage.get("cache_read_input_tokens", 0), "cache_write": usage.get("cache_creation_input_tokens", 0)},
                        "text": self.clean_text(obj.get("result", ""))})
            self.proc.wait(timeout=max(1, self.timeout))
            if not self.cancelled and not result_seen:
                err_thread.join(timeout=1)
                emit({"type": "cc_error", "error": ("Claude result olayı olmadan kapandı: " + "".join(stderr)[-1000:]).strip()})
        except Exception as exc:
            if not self.cancelled:
                emit({"type": "cc_error", "error": str(exc)})

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            kill_tree(self.proc)
