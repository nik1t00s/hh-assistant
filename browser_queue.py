"""Open a snapshot of current-run vacancies without blocking Tk's event loop."""
import webbrowser
import re
from urllib.parse import urlsplit


def canonical_url(url):
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url.strip())
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        match = re.fullmatch(r'/vacancy/(\d+)/?', parsed.path)
        if match and (host == 'hh.ru' or host.endswith('.hh.ru')):
            return 'https://hh.ru/vacancy/' + match[1]
        return parsed._replace(fragment='').geturl()
    except ValueError:
        return None


def suitable_urls(rows):
    """Latest verdict per URL wins; UI filters do not change the session snapshot."""
    latest = {}
    for row in rows:
        url = canonical_url(row.get("url", ""))
        if not url:
            continue
        latest[url] = row
    return [url for url, row in latest.items()
            if row.get("suitable") is True and row.get("verdict") != "REJECT"]


class BrowserQueue:
    INTERVAL_MS = 20_000
    BATCH_SIZE = 50

    def __init__(self, scheduler, on_update, opener=None):
        self.scheduler = scheduler
        self.on_update = on_update
        self.opener = opener or webbrowser.open_new_tab
        self.active = False
        self.paused = False
        self.batch_end = 0
        self.pending = None
        self.urls = []
        self.opened = 0
        self.generation = 0

    def start(self, urls):
        if self.active or self.paused or not urls:
            return
        self.urls = list(dict.fromkeys(url for raw in urls if (url := canonical_url(raw))))
        if not self.urls:
            return
        self.opened = 0
        self.batch_end = min(self.BATCH_SIZE, len(self.urls))
        self.active = True
        self.generation += 1
        self._next(self.generation)

    def resume(self):
        if not self.paused:
            return
        self.paused = False
        self.active = True
        self.batch_end = min(self.opened + self.BATCH_SIZE, len(self.urls))
        self.generation += 1
        self._next(self.generation)

    def pause(self):
        if not self.active:
            return
        self.active = False
        self.paused = True
        self.generation += 1
        if self.pending is not None:
            self.scheduler.after_cancel(self.pending)
            self.pending = None
        self.on_update(f"Пауза: открыто {self.opened} из {len(self.urls)}. Закройте просмотренные вкладки и нажмите «Продолжить».")

    def _next(self, generation):
        if not self.active or generation != self.generation:
            return
        self.pending = None
        try:
            if not self.opener(self.urls[self.opened]):
                raise RuntimeError("Браузер по умолчанию не принял ссылку.")
        except Exception:
            self.active = False
            self.paused = True
            self.on_update("Не удалось открыть браузер. Очередь на паузе; можно продолжить.")
            return
        self.opened += 1
        if self.opened == len(self.urls):
            self.active = False
            self.on_update(f"Открыты все вакансии: {self.opened}.")
            return
        if self.opened >= self.batch_end:
            self.pause()
            return
        self.pending = self.scheduler.after(self.INTERVAL_MS, lambda: self._next(generation))
        self.on_update(f"Открыто {self.opened} из {len(self.urls)} · следующая через 20 секунд")

    def cancel(self, notify=True):
        was_active = self.active or self.paused
        self.active = False
        self.paused = False
        self.generation += 1
        if self.pending is not None:
            self.scheduler.after_cancel(self.pending)
            self.pending = None
        if was_active and notify:
            self.on_update(f"Открытие остановлено: {self.opened} из {len(self.urls)}.")
