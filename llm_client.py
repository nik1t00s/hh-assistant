"""Shared LM Studio transport for both applications."""
import json
import re
import requests
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse


class LocalModelManager:
    """Switch only the configured local models, once per processing stage."""
    def __init__(self, base_url, models, log, stop_event, gpu=None, context_length=8192):
        if urlparse(base_url).hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise RuntimeError('Автозагрузка моделей доступна только для локального LM Studio.')
        self.cli = Path.home() / '.lmstudio' / 'bin' / ('lms.exe' if os.name == 'nt' else 'lms')
        self.models = set(filter(None, models))
        self.log, self.stop_event = log, stop_event
        self.gpu = gpu or {}
        self.context_length = context_length
        available = {m['modelKey'] for m in json.loads(self._run('ls', '--json')) if m.get('type') == 'llm'}
        if self.models - available:
            raise RuntimeError('Не установлены модели: ' + ', '.join(sorted(self.models - available)))
        self.active = None

    def _run(self, *args):
        if self.stop_event.is_set():
            raise RuntimeError('остановлено пользователем')
        result = subprocess.run([str(self.cli), *args], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=240,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError('LM Studio: ' + (result.stderr or result.stdout)[-500:])
        if self.stop_event.is_set():
            raise RuntimeError('остановлено пользователем')
        return result.stdout

    def activate(self, model):
        if self.stop_event.is_set():
            raise RuntimeError('остановлено пользователем')
        if self.active == model:
            return
        if model not in self.models:
            raise RuntimeError('Модель не входит в настроенную пару.')
        loaded = json.loads(self._run('ps', '--json'))
        for entry in loaded:
            if entry.get('type') != 'llm':
                continue
            if entry.get('status', '').lower() != 'idle':
                raise RuntimeError('LM Studio занят другим запросом. Дождитесь его завершения.')
            if entry.get('modelKey') not in self.models:
                raise RuntimeError('В LM Studio загружена другая модель. Выгрузите её перед поиском для освобождения памяти.')
        for entry in loaded:
            if entry.get('type') == 'llm' and entry.get('modelKey') != model:
                self._run('unload', entry['identifier'])
        matching = [entry for entry in loaded if entry.get('modelKey') == model]
        if matching and matching[0].get('contextLength') != self.context_length:
            self._run('unload', matching[0]['identifier'])
            matching = []
        if not matching:
            self.log(f'Загружаю модель: {model}…')
            args = ['load', model, '--identifier', model, '--context-length', str(self.context_length), '--parallel', '1', '-y']
            if model in self.gpu:
                args += ['--gpu', str(self.gpu[model])]
            self._run(*args)
        elif matching[0]['identifier'] != model:
            raise RuntimeError('Имя загруженного экземпляра отличается от настройки модели. Перезагрузите модель.')
        self.active = model


class StreamingLLMClient:
    # Таймаут ПАУЗЫ между чанками стрима (сек), а не общей длительности
    # ответа: пока модель шлёт хоть что-то (включая размышления),
    # соединение живёт сколько угодно долго — хоть на самой медленной
    # модели. Ошибка возникает, только если модель реально зависла
    # и молчит дольше этого времени.
    STALL_TIMEOUT = 600

    def __init__(self, base_url, model, log, stop_event=None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.log = log
        self.stop_event = stop_event

    def list_models(self):
        r = requests.get(f"{self.base_url}/models", timeout=10)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    def check(self):
        """Проверяет связь с LM Studio и выбирает модель.

        Настроенную модель ищет по точному имени или уникальной подстроке.
        Не заменяет неизвестную модель другой без ведома пользователя."""
        if getattr(self, 'manager', None):
            self.list_models()  # Confirm server availability without loading both models.
            return self.model
        models = self.list_models()
        if not models:
            raise RuntimeError("В LM Studio не загружена ни одна модель")
        want = (self.model or "").strip().lower()
        if want:
            if self.model in models:
                return self.model
            matches = [m for m in models if want in m.lower()]
            if len(matches) == 1:
                self.model = matches[0]
                return self.model
            if len(matches) > 1:
                raise RuntimeError('Название модели неоднозначно. Укажите полное имя.')
            raise RuntimeError(f'Модель «{self.model}» не найдена в LM Studio. Проверьте её название.')
        self.model = models[0]
        return self.model

    def _chat(self, system, user, temperature, max_tokens, seed=None):
        """Стриминговый запрос: без общего таймаута, только контроль
        того, что модель продолжает отвечать (STALL_TIMEOUT между чанками).

        frequency_penalty штрафует повторы — снижает риск, что модель
        зациклится и сожжёт весь max_tokens, ни разу не дав ответ
        (редкий, но воспроизводимый сбой у квантованных моделей)."""
        if getattr(self, 'manager', None):
            self.manager.activate(self.model)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "frequency_penalty": 0.3,
            "stream": True,
            # Reasoning is optional; only the final content is parsed as JSON.
            "reasoning_effort": getattr(self, 'reasoning_effort', 'none'),
            "stream_options": {"include_usage": True},
        }
        if seed is not None:
            payload["seed"] = seed
        schema = getattr(self, "response_schema", None)
        if schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "vacancy_facts", "strict": True, "schema": schema}}
        pieces = []
        self.last_usage = None
        self.last_reasoning_chars = 0
        self.last_finish = None  # finish_reason последнего запроса
        chunk_count = 0
        with requests.post(
            f"{self.base_url}/chat/completions", json=payload,
            stream=True, timeout=(10, self.STALL_TIMEOUT),
        ) as r:
            if r.status_code != 200:
                try:
                    detail = r.text[:300]
                except Exception:  # noqa: BLE001
                    detail = ""
                raise RuntimeError(
                    f"LM Studio вернул {r.status_code}: {detail}")
            # Читаем сырые байты и декодируем только целые строки:
            # граница HTTP-чанка может прийтись на середину многобайтового
            # UTF-8 символа (кириллица), что ломает JSON.
            for raw_line in r.iter_lines(decode_unicode=False):
                if self.stop_event is not None and self.stop_event.is_set():
                    raise RuntimeError("остановлено пользователем")
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data.strip() == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    if event.get('usage'):
                        self.last_usage = event['usage']
                    if not event.get('choices'):
                        continue
                    choice = event["choices"][0]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                chunk_count += 1
                if choice.get("finish_reason"):
                    self.last_finish = choice["finish_reason"]
                piece = choice.get("delta", {}).get("content")
                self.last_reasoning_chars += len(choice.get('delta', {}).get('reasoning_content') or '')
                if piece:
                    pieces.append(piece)
        self.last_chunks = chunk_count
        return self._clean("".join(pieces))

    @staticmethod
    def _clean(content):
        """Убирает <think>-блоки thinking-моделей."""
        content = re.sub(r"<think>.*?</think>", "", content or "",
                         flags=re.DOTALL)
        # незакрытый <think> — ответ оборвался внутри размышлений
        content = re.sub(r"<think>.*", "", content, flags=re.DOTALL)
        return content.strip()
