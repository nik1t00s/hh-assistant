"""Open a snapshot of current-run vacancies without blocking Tk's event loop."""
import webbrowser
import re
from difflib import SequenceMatcher
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


def variants(row):
    return row.get('variants') or [row]


def similar_vacancies(left, right):
    norm = lambda s: ' '.join((s or '').casefold().split())
    if not all(norm(left.get(k)) == norm(right.get(k)) and norm(left.get(k)) for k in ('name', 'employer', 'verdict')):
        return False
    a, b = left.get('source', ''), right.get('source', '')
    a, b = norm(a.split('Описание:', 1)[-1]), norm(b.split('Описание:', 1)[-1])
    return min(len(a), len(b)) >= 100 and SequenceMatcher(None, a, b, autojunk=False).ratio() >= .97


def group_vacancies(rows):
    """Presentation only: every original record and URL stays available."""
    grouped = []
    for row in rows:
        for group in grouped:
            if similar_vacancies(group, row):
                members = list(group.get('variants') or [dict(group)])
                if row['url'] not in {v['url'] for v in members}:
                    members.append(dict(row))
                group['variants'] = members
                break
        else:
            grouped.append(dict(row))
    return grouped


def variant_details(row):
    members = variants(row)
    if len(members) < 2:
        return ''
    sets = [set(line.strip() for line in v.get('source', '').split('Описание:', 1)[-1].splitlines() if line.strip()) for v in members]
    common = set.intersection(*sets)
    lines = ['Похожие объявления — условия могут различаться:']
    for index, (v, own) in enumerate(zip(members, sets), 1):
        lines += [f"Вариант {index}: {v['url']}", f"Зарплата: {v.get('salary', 'не указана')}"]
        differences = [line.strip() for line in v.get('source', '').split('Описание:', 1)[-1].splitlines() if line.strip() in own - common]
        lines.extend(differences or ['Описание совпадает с другими вариантами.'])
    return '\n'.join(lines)


def suitable_urls(rows):
    """Latest verdict per URL wins; UI filters do not change the session snapshot."""
    latest = {}
    for row in (v for group in rows for v in variants(group)):
        url = canonical_url(row.get("url", ""))
        if not url:
            continue
        latest[url] = row
    return [url for url, row in latest.items()
            if row.get("suitable") is True and row.get("verdict") in {"MATCH", "STRONG_MATCH", "WEAK"}]


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
