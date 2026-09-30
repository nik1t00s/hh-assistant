"""Shared LM Studio transport for both applications."""
import json
import re
import requests


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

        Настроенную модель ищет по точному имени или подстроке
        (можно написать просто «gemma»); иначе берёт первую доступную."""
        models = self.list_models()
        if not models:
            raise RuntimeError("В LM Studio не загружена ни одна модель")
        want = (self.model or "").strip().lower()
        if want:
            for m in models:
                if want in m.lower():
                    self.model = m
                    return self.model
            self.log(f"Модель «{self.model}» не найдена в LM Studio, "
                     f"использую {models[0]}")
        self.model = models[0]
        return self.model

    def _chat(self, system, user, temperature, max_tokens, seed=None):
        """Стриминговый запрос: без общего таймаута, только контроль
        того, что модель продолжает отвечать (STALL_TIMEOUT между чанками).

        frequency_penalty штрафует повторы — снижает риск, что модель
        зациклится и сожжёт весь max_tokens, ни разу не дав ответ
        (редкий, но воспроизводимый сбой у квантованных моделей)."""
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
            # "Размышляющие" модели (напр. gemma-4-12b-qat) по умолчанию
            # шлют весь текст, включая финальный JSON, в отдельное поле
            # reasoning_content, а не в content — этот код читает только
            # content, поэтому такой ответ выглядел как пустой. Ноль
            # снимает режим размышлений и одновременно решает случаи,
            # когда модель "размышляет" бесконечно, не доходя до ответа.
            "reasoning_effort": "none",
        }
        if seed is not None:
            payload["seed"] = seed
        schema = getattr(self, "response_schema", None)
        if schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "vacancy_facts", "strict": True, "schema": schema}}
        pieces = []
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
                    choice = json.loads(data)["choices"][0]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                chunk_count += 1
                if choice.get("finish_reason"):
                    self.last_finish = choice["finish_reason"]
                piece = choice.get("delta", {}).get("content")
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
