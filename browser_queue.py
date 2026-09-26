"""Open a snapshot of current-run vacancies without blocking Tk's event loop."""
import webbrowser
from urllib.parse import urlsplit


def suitable_urls(rows):
    """Latest verdict per URL wins; UI filters do not change the session snapshot."""
    latest = {}
    for row in rows:
        url = row.get("url", "")
        if not isinstance(url, str):
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        latest[url] = row
    return [url for url, row in latest.items()
            if row.get("suitable") is True and row.get("verdict") != "REJECT"]


class BrowserQueue:
    INTERVAL_MS = 20_000

    def __init__(self, scheduler, on_update, opener=None):
        self.scheduler = scheduler
        self.on_update = on_update
        self.opener = opener or webbrowser.open_new_tab
        self.active = False
        self.pending = None
        self.urls = []
        self.opened = 0
        self.generation = 0

    def start(self, urls):
        if self.active or not urls:
            return
        self.urls = list(urls)
        self.opened = 0
        self.active = True
        self.generation += 1
        self._next(self.generation)

    def _next(self, generation):
        if not self.active or generation != self.generation:
            return
        self.pending = None
        try:
            if not self.opener(self.urls[self.opened]):
                raise RuntimeError("Браузер по умолчанию не принял ссылку.")
        except Exception:
            self.active = False
            self.on_update("Не удалось открыть браузер. Очередь остановлена.")
            return
        self.opened += 1
        if self.opened == len(self.urls):
            self.active = False
            self.on_update(f"Открыты все вакансии: {self.opened}.")
            return
        self.pending = self.scheduler.after(self.INTERVAL_MS, lambda: self._next(generation))
        self.on_update(f"Открыто {self.opened} из {len(self.urls)} · следующая через 20 секунд")

    def cancel(self, notify=True):
        was_active = self.active
        self.active = False
        self.generation += 1
        if self.pending is not None:
            self.scheduler.after_cancel(self.pending)
            self.pending = None
        if was_active and notify:
            self.on_update(f"Открытие остановлено: {self.opened} из {len(self.urls)}.")
