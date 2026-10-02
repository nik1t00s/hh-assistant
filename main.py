# -*- coding: utf-8 -*-
"""Локальный поиск вакансий и оценка через LM Studio. См. README.md."""

import csv
import hashlib
import html
import json
import os
import queue
import random
import re
import threading
import time
import webbrowser
from datetime import datetime

from llm_client import StreamingLLMClient, LocalModelManager
from browser_queue import BrowserQueue, suitable_urls
from evidence_eval import FACT_PROMPT, FACT_SCHEMA, parse_facts, valid_facts, verify_facts, decide, audit_path, save_audit, numbered_source, materialize
from settings import load_settings, save_settings
from storage import EvaluationStore, atomic_text, evaluation_fingerprint
from vacancy_rules import (strip_html, extract_jobposting_description,
                           short_profile, score_cap, salary_cap, word_hit)

import requests
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
PROFILE_PATH = os.path.join(APP_DIR, "profile.txt")
RESULTS_DIR = os.path.join(APP_DIR, "results")
CACHE_DIR = os.path.join(APP_DIR, "cache")
SEEN_PATH = os.path.join(CACHE_DIR, "seen_ids.json")

# Обычные заголовки браузера — мы анонимный посетитель сайта.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
}

AREAS = {
    "Вся Россия": "113",
    "Москва": "1",
    "Санкт-Петербург": "2",
    "Екатеринбург": "3",
    "Новосибирск": "4",
}

EXPERIENCE = {
    "Любой": "",
    "Нет опыта": "noExperience",
    "1–3 года": "between1And3",
    "3–6 лет": "between3And6",
    "Более 6 лет": "moreThan6",
}

# Человекочитаемые названия требуемого опыта из данных вакансии.
EXP_LABEL = {
    "noExperience": "не требуется",
    "between1And3": "1–3 года",
    "between3And6": "3–6 лет",
    "moreThan6": "более 6 лет",
}

# Варианты жёсткого отсева по требуемому опыту (до нейросети).
EXP_FILTER = {
    "не отсеивать": (),
    "3+ лет": ("between3And6", "moreThan6"),
    "1–3 года и больше": ("between1And3", "between3And6", "moreThan6"),
}

# Личные настройки переопределяются локальным config.json.
DEFAULT_CONFIG = {'role_ids': ['107', '121', '113', '110'],
 'split_roles': True,
 'queries': 'системный администратор\n'
            'младший системный администратор\n'
            'администратор Linux\n'
            'Astra Linux\n'
            'инженер инфраструктуры\n'
            'сопровождение ИТ-инфраструктуры\n'
            'администратор серверов\n'
            'инженер внедрения\n'
            'сетевой инженер\n'
            'информационная безопасность junior\n'
            'специалист технической поддержки\n'
            'сопровождение информационных систем\n'
            'техническое сопровождение\n'
            'координатор проектов внедрения\n'
            'junior project manager\n'
            'деливери менеджер\n'
            'технический тимлид\n'
            'сервис-менеджер\n'
            'пресейл-инженер',
 'exclude_words': 'разработчик, developer, программист, backend, frontend, fullstack, data '
                  'scientist, тестировщик, qa, автотест, 1с, колл-центр, call-центр, '
                  'оператор, продавец, курьер, водитель, senior, старший, ведущий, главный, '
                  'начальник, бизнес-ассистент, бизнес ассистент, секретарь, официант, '
                  'грузчик, фармацевт, товаровед, сборщик, кладовщик, повар, хостес, '
                  'разнорабочий, кассир, бариста, выездной, риелтор, риэлтор, фотограф, врач, '
                  'приемщик, заправщик, велокурьер, ночной, бармен, рабочий, мерчендайзер, '
                  'кальянный, расклейщик, механик, полицейский, комплектовщик, сантехник, '
                  'электрик, слесарь, оптометрист, парикмахер, косметолог, стоматолог, '
                  'ортодонт, ветеринар, воспитатель, упаковщик, танцовщи, подолог, эпиляции, '
                  'тренер, рентгенолаборант',
 'include_words': 'автоматизац, внедрен, интеграц, process, project, менеджер проект, '
                  'проектн, координатор проект, руководител проект, тимлид, информационные '
                  'системы, сопровождение информационных, sysadmin, системный администратор, '
                  'devops',
 'exclude_companies': '',
 'habr_enabled': False,
 'superjob_enabled': False,
 'superjob_resume_url': '',
 'superjob_cookie': '',
 'telegram_enabled': False,
 'telegram_channels': '',
 'triage': True,
 'exp_filter': '3+ лет',
 'area': 'Москва',
 'experience': 'Любой',
 'remote_only': False,
 'remote_extra': True,
 'only_with_salary': False,
 'recs_enabled': False,
 'hh_resume_only': False,
 'resume_hash': '',
 'hh_cookie': '',
 'pages': 2,
 'min_delay': 3.0,
 'max_delay': 7.0,
 'lm_url': 'http://localhost:1234/v1',
 'lm_model': '',
 'lm_model_fast': ''}

DEFAULT_PROFILE = """\
=== КТО Я ===
(Опишите себя: специальность, опыт работы, ключевые навыки, технологии.)

=== ЧТО ИЩУ ===
(Желаемая должность, зарплатные ожидания, формат работы — удалёнка/офис,
график, что обязательно должно быть в вакансии.)

=== ПСИХОЛОГИЧЕСКИЙ ПРОФИЛЬ ===
(Что вам подходит по складу характера: темп работы, размер команды,
уровень стресса, рутина vs творчество, общение с людьми и т.п.)

=== СТОП-ФАКТОРЫ ===
(Чего точно не хочу: холодные звонки, командировки, ночные смены,
конкретные сферы и т.д.)
"""


# ----------------------------------------------------------------------
# Утилиты
# ----------------------------------------------------------------------

def load_config():
    return load_settings(CONFIG_PATH, DEFAULT_CONFIG)


def save_config(cfg):
    save_settings(CONFIG_PATH, cfg)


def format_salary(comp):
    """Форматирует блок compensation со страницы поиска hh.ru."""
    if not comp or not (comp.get("from") or comp.get("to")):
        return "не указана"
    parts = []
    if comp.get("from"):
        parts.append(f"от {comp['from']:,}".replace(",", " "))
    if comp.get("to"):
        parts.append(f"до {comp['to']:,}".replace(",", " "))
    cur = comp.get("currencyCode") or comp.get("currency") or ""
    cur = {"RUR": "руб."}.get(cur, cur)
    if comp.get("gross"):
        cur += " до вычета налогов"
    return (" ".join(parts) + f" {cur}").strip()


# ----------------------------------------------------------------------
# HH API
# ----------------------------------------------------------------------

class HHClient:
    """Читает HH: публичный поиск либо рекомендации с cookies аккаунта."""

    BASE = "https://hh.ru"

    def __init__(self, log, cookie=None):
        self.log = log
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        if cookie:
            self.session.headers["Cookie"] = cookie.strip()

    def _get(self, url, **kwargs):
        r = self.session.get(url, timeout=30, allow_redirects=True, **kwargs)
        if r.status_code == 403 or "captcha" in r.url:
            raise RuntimeError(
                "hh.ru временно ограничил доступ (капча). Подождите "
                "10–15 минут и увеличьте паузы между запросами."
            )
        if "account/login" in r.url:
            raise RuntimeError(
                "hh.ru перенаправил на страницу входа — cookie устарели. "
                "Скопируйте свежие cookie из браузера (вкладка «Аккаунт HH»)."
            )
        r.raise_for_status()
        return r

    @staticmethod
    def _initial_state(page_html):
        # JSON внутри шаблона приходит то как есть, то HTML-экранированным
        # (&#34; вместо кавычек) — пробуем оба варианта.
        for m in re.finditer(
            r'id="HH-Lux-InitialState"[^>]*>(.*?)</template>',
            page_html, re.DOTALL,
        ):
            raw = m.group(1)
            for candidate in (raw, html.unescape(raw)):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        raise RuntimeError(
            "Не нашёл данные на странице поиска — возможно, hh.ru "
            "изменил формат страницы."
        )

    def search(self, query, area, experience, remote_only, only_with_salary,
               page, roles=None, resume=None):
        """Возвращает (список вакансий, номер последней страницы).

        Источник: текст (query), профессиональные категории HH (roles)
        или рекомендации под резюме (resume — hash резюме, нужны cookie)."""
        params = {"page": page, "items_on_page": "100"}
        if resume:
            # рекомендации: HH сам сортирует по соответствию резюме
            params["resume"] = resume
        else:
            params["area"] = area
            params["order_by"] = "publication_time"
        if query:
            params["text"] = query
        if roles:
            params["professional_role"] = list(roles)
        if experience:
            params["experience"] = experience
        if remote_only:
            params["work_format"] = "REMOTE"
        if only_with_salary:
            params["only_with_salary"] = "true"
        r = self._get(f"{self.BASE}/search/vacancy", params=params)
        state = self._initial_state(r.text)
        result = state.get("vacancySearchResult") if isinstance(state, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("vacancies"), list):
            raise RuntimeError("HH: формат выдачи изменился, список вакансий не найден.")

        items = []
        for v in result.get("vacancies", []):
            vid = v.get("vacancyId")
            if not vid:
                continue
            links = v.get("links") or {}
            items.append({
                "id": str(vid),
                "name": v.get("name", "Без названия"),
                "employer": (v.get("company") or {}).get("name", "?"),
                "salary": format_salary(v.get("compensation")),
                "experience": v.get("workExperience", ""),
                "url": links.get("desktop", f"{self.BASE}/vacancy/{vid}"),
            })
        paging = result.get("paging") or {}
        last_page = (paging.get("lastPage") or {}).get("page", page)
        return items, int(last_page)

    def description(self, url):
        """Полное описание вакансии из JSON-LD (schema.org JobPosting)."""
        r = self._get(url)
        return extract_jobposting_description(r.text)


class HabrClient:
    """Читает публичные страницы career.habr.com без авторизации —
    так же анонимно, как HHClient читает hh.ru. Только текстовый поиск:
    у Хабр Карьеры нет категорий вроде professional_role у HH."""

    BASE = "https://career.habr.com"

    def __init__(self, log):
        self.log = log
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)

    def _get(self, url, **kwargs):
        # У career.habr.com сервер иногда отвечает заметно дольше hh.ru —
        # таймаут больше, чтобы не принимать медленный ответ за сбой.
        r = self.session.get(url, timeout=45, allow_redirects=True, **kwargs)
        if r.status_code == 403 or "captcha" in r.url:
            raise RuntimeError(
                "career.habr.com временно ограничил доступ. Подождите "
                "10–15 минут и увеличьте паузы между запросами."
            )
        r.raise_for_status()
        return r

    @staticmethod
    def _map_experience(seniority_text):
        """Грейд Хабра («Junior»/«Middle»/«Senior») — в шкалу опыта hh.ru,
        чтобы общий фильтр по опыту работал одинаково на обоих источниках."""
        t = (seniority_text or "").lower()
        if "senior" in t:
            return "moreThan6"
        if "middle" in t or "миддл" in t:
            return "between3And6"
        if "junior" in t or "джуниор" in t:
            return "noExperience"
        return ""

    def search(self, query, page):
        """Возвращает (список вакансий, номер следующей страницы).

        В отличие от HH, точное число страниц не сообщается — Worker
        просто идёт дальше, пока страница не вернёт ноль вакансий."""
        params = {"q": query, "type": "all", "page": page + 1}
        r = self._get(f"{self.BASE}/vacancies", params=params)
        html_text = r.text

        starts = [m.start() for m in
                 re.finditer(r'class="vacancy-card__backdrop-link"', html_text)]
        items = []
        for i, pos in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(html_text)
            block = html_text[pos:end]

            m_id = re.search(r'href="/vacancies/(\d+)"', block)
            m_title = re.search(
                r'vacancy-card__title-link"[^>]*>([^<]+)<', block)
            if not m_id or not m_title:
                continue
            vid = m_id.group(1)

            m_company = re.search(
                r'vacancy-card__company">.*?href="/companies/[^"]*"[^>]*>'
                r'([^<]+)<', block, re.DOTALL)
            m_salary = re.search(
                r'predicted-salary__title[^"]*">([^<]+)<', block)
            m_grade = re.search(
                r'icon-grade.*?chip-with-icon__text">([^<]+)<',
                block, re.DOTALL)

            items.append({
                "id": f"habr-{vid}",
                "name": m_title.group(1).strip(),
                "employer": m_company.group(1).strip() if m_company else "?",
                "salary": (m_salary.group(1).strip()
                          if m_salary else "не указана"),
                "experience": self._map_experience(
                    m_grade.group(1) if m_grade else ""),
                "url": f"{self.BASE}/vacancies/{vid}",
            })
        # своей нумерации страниц Хабр не отдаёт — просто пробуем следующую,
        # пока не придёт пустая страница (это проверяет вызывающий код).
        return items, page + 1

    def description(self, url):
        """Полное описание вакансии из JSON-LD (тот же формат, что у HH)."""
        r = self._get(url)
        return extract_jobposting_description(r.text)


class SuperJobClient:
    """Читает публичные страницы superjob.ru без авторизации.

    08.10.2026: карточки на странице поиска отрисованы через React с
    захэшированными CSS-классами (меняются от сборки к сборке), но сами
    вакансии внутри отмечены стабильными тестовыми классами вида
    f-test-vacancy-item-<id>, f-test-link-..., f-test-text-company-item-
    salary — по ним и парсим, а не по хэш-классам. Реальную постраничную
    навигацию (следующая страница результатов) через обычные запросы
    найти не удалось — похоже, она подгружается внутренним API
    фронтенда, который не reverse-engineer'ил. Поэтому читаем ТОЛЬКО
    первую страницу на каждый запрос (обычно 15-20 вакансий) — честное
    ограничение, не баг."""

    BASE = "https://www.superjob.ru"
    TOWN_MOSCOW = "4"

    def __init__(self, log, cookie=None):
        self.log = log
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        if cookie:
            self.session.headers["Cookie"] = cookie.strip()

    def _get(self, url, **kwargs):
        r = self.session.get(url, timeout=30, allow_redirects=True, **kwargs)
        r.raise_for_status()
        return r

    @staticmethod
    def _parse_cards(page_html):
        """Общий разбор карточек вакансии — и для обычного поиска, и
        для блока рекомендаций на главной (разметка одна и та же)."""
        ids = re.findall(r'f-test-vacancy-item-(\d+)', page_html)
        blocks = re.split(r'f-test-vacancy-item-\d+', page_html)[1:]

        items = []
        for vid, block in zip(ids, blocks):
            block = block[:3000]
            m_title = re.search(
                r'f-test-link-[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                block, re.DOTALL)
            if not m_title:
                continue
            m_salary = re.search(
                r'f-test-text-company-item-salary">(.*?)</div>',
                block, re.DOTALL)
            m_alt = re.search(r'alt="([^"]+)"', block)
            items.append({
                "id": f"sj-{vid}",
                "name": strip_html(m_title.group(2)),
                "employer": m_alt.group(1) if m_alt else "?",
                "salary": (strip_html(m_salary.group(1))
                          if m_salary else "не указана"),
                # У SuperJob нет отдельного тега требуемого опыта, как у
                # HH — решает нейросеть/score_cap по тексту описания.
                "experience": "",
                "url": m_title.group(1),
            })
        return items

    def search(self, query, page):
        """Возвращает (список вакансий, номер последней страницы) —
        last_page всегда 0, страница дальше первой не поддерживается."""
        if page > 0:
            return [], 0
        params = {"keywords": query, "town": self.TOWN_MOSCOW}
        r = self._get(f"{self.BASE}/vacancy/search/", params=params)
        return self._parse_cards(r.text), 0

    def search_recs(self, page):
        """Персональные «рекомендованные вакансии» — виджет на главной
        странице, виден только авторизованным (нужны cookie). Отдаёт
        всего несколько вакансий (не полноценная лента с пагинацией,
        как у HH) — честно, но это реально персонально под резюме, не
        общий поиск."""
        if page > 0:
            return [], 0
        r = self._get(f"{self.BASE}/")
        return self._parse_cards(r.text), 0

    def description(self, url):
        """Полное описание вакансии из JSON-LD (тот же формат, что у HH)."""
        r = self._get(url)
        return extract_jobposting_description(r.text)


class TelegramClient:
    """Читает публичные посты Telegram-каналов через t.me/s/ — веб-превью
    без входа в аккаунт, работает только для каналов с открытой ссылкой
    t.me/<имя> (закрытые/приватные каналы так не читаются).

    Вакансия здесь — не структурированная запись как у HH/Хабра/
    SuperJob, а обычный пост: отдельно зарплаты и требуемого опыта нет,
    только сплошной текст. Не каждый пост в канале — вакансия вообще
    (бывает реклама и анонсы) — это разбирает уже нейросеть на полной
    проверке, здесь только грубый отсев слишком коротких постов."""

    def __init__(self, log):
        self.log = log
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        # 16.10.2026: t.me/s/ по умолчанию отдаёт только ~20 последних
        # постов, но у неё есть настоящая пагинация вглубь истории —
        # ?before=<id самого старого показанного поста>. Курсор храним
        # тут (по каналу), а не по числовому page — сбрасываем на page=0
        # (Worker каждый «круг» проходит источник заново с page=0).
        self._before_cursor = {}

    def _get(self, url, **kwargs):
        r = self.session.get(url, timeout=30, allow_redirects=True, **kwargs)
        r.raise_for_status()
        return r

    @staticmethod
    def _extract_post(channel, msg_id, page_html):
        m_block = re.search(
            r'data-post="' + re.escape(f"{channel}/{msg_id}") + r'"'
            r'(.*?)(?=data-post="|\Z)', page_html, re.DOTALL)
        if not m_block:
            return None
        m_text = re.search(
            r'tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            m_block.group(1), re.DOTALL)
        if not m_text:
            return None
        return strip_html(re.sub(r'<br\s*/?>', '\n', m_text.group(1)))

    def search(self, channel, page):
        """Возвращает (список постов, номер следующей страницы) — как у
        Хабра, точного числа страниц нет, идём вглубь истории канала
        через ?before=, пока страница не вернёт ноль постов (это уже
        начало канала) — до общего лимита cfg["pages"]."""
        if page == 0:
            self._before_cursor.pop(channel, None)
            r = self._get(f"https://t.me/s/{channel}")
        else:
            before = self._before_cursor.get(channel)
            if before is None:
                return [], page
            r = self._get(f"https://t.me/s/{channel}",
                          params={"before": before})
        page_html = r.text

        ids = sorted({int(i) for i in re.findall(
            r'data-post="' + re.escape(channel) + r'/(\d+)"', page_html)})
        if not ids:
            return [], page
        self._before_cursor[channel] = ids[0]

        items = []
        for msg_id in ids:
            text = self._extract_post(channel, str(msg_id), page_html)
            if not text or len(text) < 80:
                continue  # слишком короткий пост — вряд ли вакансия
            title = text.split("\n", 1)[0][:120].strip()
            items.append({
                "id": f"tg-{channel}-{msg_id}",
                "name": title or f"Пост в {channel}",
                "employer": f"Telegram: {channel}",
                "salary": "не указана",
                "experience": "",
                "url": f"https://t.me/{channel}/{msg_id}",
            })
        return items, page + 1

    def description(self, url):
        m = re.search(r"t\.me/([^/]+)/(\d+)", url)
        if not m:
            return ""
        channel, msg_id = m.group(1), m.group(2)
        r = self._get(f"https://t.me/s/{channel}/{msg_id}")
        return self._extract_post(channel, msg_id, r.text) or ""


# ----------------------------------------------------------------------
# LM Studio
# ----------------------------------------------------------------------

SYSTEM_PROMPT = """\
Ты оцениваешь соответствие вакансии профилю кандидата, который срочно
ищет первую работу — каждая пропущенная подходящая вакансия стоит
дорого.

ПРОФИЛЬ КАНДИДАТА:
{profile}

ПРАВИЛА ОЦЕНКИ — применяй по порядку, решает ПЕРВОЕ подошедшее правило:

1. Если в тексте вакансии ЯВНО присутствует хотя бы один стоп-фактор
   из профиля — ставь REJECT. БЕЗ ИСКЛЮЧЕНИЙ: не взвешивай стоп-фактор
   против плюсов вакансии. Не важно, насколько хорошо подходит всё
   остальное, насколько привлекательна должность или компания, есть
   ли обучение и наставник — один явный стоп-фактор перевешивает любые
   плюсы, и вывод должен быть REJECT, а не «подходит, но есть нюанс».
   Не додумывай стоп-факторы, которых в тексте нет — но раз нашёл
   явный, не смягчай вывод.
   СНАЧАЛА проверь уровень и IT-контекст. Явно требуемый Middle/Middle+,
   Senior, Lead или руководящий уровень — REJECT, даже если должность
   названа «администратор проектов» и задачи включают Jira/координацию.
   Название Junior не отменяет обязательные требования из описания.
   Упоминание senior-наставника или будущего роста не является уровнем
   самой вакансии. Диапазон Junior/Middle с допуском Junior не отклоняй
   только по слову Middle.
   Если компания не IT и сама роль явно HR, маркетинг или другая не-IT
   функция — REJECT. Общее слово «проекты» не делает роль IT-проектом.
   Если в описании прямо требуется коммерческий опыт или опыт в аналогичной
   должности, которого у кандидата нет, — REJECT, даже для Junior и даже при
   совпадении задач. Университетский опыт не заменяет коммерческий IT-стаж.
   Исключения: опыт желателен/будет плюсом либо явно допускаются новички
   без опыта. Одно обучение НЕ означает отмену обязательного стажа.
   Тег HH «1–3 года» сам по себе не отказ. Общий рабочий опыт и опыт
   использования инструментов не приравнивай к коммерческому опыту в роли.
   Редкие поездки обсуждаемы; неизвестную частоту не считать регулярной.
   Отсутствие сведений об оформлении, зарплате или наставнике — неизвестность,
   а не доказательство плохих условий. Не выдумывай отсутствующие данные.
   Если профиль задаёт минимум зарплаты, сравнивай только сопоставимые
   суммы: на руки за месяц. Диапазон с допустимым верхним пределом,
   зарплата до налогов или без указанной периодичности требуют уточнения.
2. Если стоп-факторов нет, но остаётся реальная неопределённость (не
   хватает данных в описании, роль на стыке направлений, не до конца
   ясно, впишется ли кандидат) — вот тут действует принцип «при
   сомнении показывай»: ставь WEAK, а не REJECT. Ошибка «показал
   лишнюю вакансию» стоит кандидату 30 секунд просмотра, ошибка
   «отклонил подходящую» — вакансию он вообще не увидит. Но WEAK — это
   про неопределённость, а НЕ про смягчение уже найденного по правилу 1
   стоп-фактора: если стоп-фактор явно есть, это всегда REJECT, а не
   WEAK, сколько бы плюсов у вакансии ни было.
3. Если явных проблем нет и вакансия попадает в одно из направлений
   профиля — STRONG_MATCH или MATCH, по тому, насколько точное
   попадание.

Плюс к score (в рамках STRONG_MATCH/MATCH/WEAK): прямое попадание в
одно из направлений, обучение и наставник, разнообразные задачи,
понятная перспектива роста, быстрый выход на работу (короткий цикл
найма).

Тег требуемого опыта на hh.ru (например «1–3 года») сам по себе не
причина для REJECT. Оцени задачи и дефицит опыта по правилу 1.
Запасные направления из профиля показывай как WEAK (score не выше 59).
Jira, документация, рутина и тестирование внутри проектной роли сами
по себе не являются минусом. Обосновывай выбор конкретными условиями,
не называй базовые навыки идеальным соответствием сложному стеку.

Поле "direction" — какой рабочей области вакансия соответствует лучше всего. Пиши ОДНИМ словом строго
из списка: "координация" (направление 1), "техподдержка"
(направление 2), "данные" (направление 3), "оргроли" (направление
4). Если ни одно не подходит — null.

Отвечай ТОЛЬКО валидным JSON без пояснений и markdown, строго в виде:
{{"verdict": "STRONG_MATCH|MATCH|WEAK|REJECT", "score": <число 0-100>, "direction": "координация|техподдержка|данные|оргроли|null", "reason": "<краткое объяснение на русском, 1-2 предложения>"}}
"""

TRIAGE_PROMPT = """\
Ты помогаешь отсеять ЯВНО неподходящие вакансии по заголовкам,
чтобы не тратить время на их полное изучение.

ПРОФИЛЬ КАНДИДАТА:
{profile}

Тебе дадут список вакансий в формате: id | должность.
Не оценивай опыт, зарплату, оформление и отрасль работодателя по заголовку.
Координатор, администратор, ассистент, помощник, аналитик, поддержка, сопровождение, инженер, технический писатель, Junior/Middle и смешанные роли всегда проходят дальше.
Верни id ТОЛЬКО тех вакансий, которые ТОЧНО НЕ подходят кандидату —
совсем другая профессия или сфера (например: врач, визажист, повар,
стройка и ремонт, физический труд, продажи по скрипту, недвижимость).
Если есть хоть малейший шанс, что вакансия близка к ролям кандидата
(продукт, проекты, координация, аналитика, информационные системы), —
НЕ включай её id: такая вакансия пойдёт на полную проверку по описанию.

Отвечай ТОЛЬКО валидным JSON без пояснений:
{{"exclude_ids": ["id1", "id2", ...]}}
Если исключать нечего — {{"exclude_ids": []}}
"""


class EvaluationExhausted(RuntimeError):
    """Нет пригодного ответа после повторов; повторяем при следующем запуске."""


class LLMClient(StreamingLLMClient):
    def evaluate(self, profile, vacancy_text):
        self.last_evidence = None
        lines, numbered = numbered_source(vacancy_text)
        self.response_schema = FACT_SCHEMA
        try:
            content = self._chat_retrying(
                FACT_PROMPT, numbered, temperature=0.1, max_tokens=4000,
                validator=valid_facts)
        finally:
            self.response_schema = None
        raw = parse_facts(content)
        facts, issues = verify_facts(materialize(raw, lines), vacancy_text)
        attempts = [json.loads(json.dumps(raw))]
        # Repair unsupported evidence once; never silently accept an invalid claim.
        if issues and decide(facts, issues)[0] == 'REVIEW':
            self.response_schema = FACT_SCHEMA
            try:
                content = self._chat_retrying(
                    FACT_PROMPT + '\nПовторная проверка. Исправь ссылки на строки и учитывай разделы. '
                    'Неподтверждённые поля: ' + ', '.join(i.split(':')[0] for i in issues) +
                    '. Не повторяй ошибочную классификацию. Опыт с инструментами — tools; '
                    'наставничество не означает no_experience. Вот предыдущий ответ: ' +
                    json.dumps(raw, ensure_ascii=False),
                    numbered, temperature=0.1, max_tokens=4000, validator=valid_facts)
                repaired = parse_facts(content)
                for key in {i.split(':')[0] for i in issues}:
                    raw[key] = repaired[key]
                attempts.append(repaired)
                facts, issues = verify_facts(materialize(raw, lines), vacancy_text)
            finally:
                self.response_schema = None
        result = decide(facts, issues)
        self.last_evidence = dict(raw=raw, attempts=attempts, verified=facts, issues=issues, result=result,
                                 usage=getattr(self, 'last_usage', None),
                                 reasoning_chars=getattr(self, 'last_reasoning_chars', 0))
        return result

    @classmethod
    def _valid_evaluation(cls, content):
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return False
        try:
            data = json.loads(match.group(0))
            score = data.get("score")
            return (isinstance(data.get("verdict"), str)
                    and data["verdict"] in cls._VERDICTS
                    and isinstance(score, (int, float)) and not isinstance(score, bool)
                    and 0 <= score <= 100
                    and (data.get("direction") is None or
                         isinstance(data["direction"], str) and
                         data["direction"].strip().lower() in cls._DIRECTIONS | {"null"})
                    and cls._reason_is_meaningful(content))
        except (ValueError, TypeError, AttributeError):
            return False

    @staticmethod
    def _has_complete_field(content, key):
        """Проверяет, что ответ — действительно завершённый JSON-объект
        с полем key, а не оборванный на середине фрагмент. Генерация
        иногда обрывается непредсказуемо (не из-за max_tokens): ответ
        получается непустым («```json» и всё), но бессмысленным —
        такой фрагмент раньше принимался как «успех» и портил оценку
        (0 вместо настоящей на явно подходящей вакансии)."""
        return bool(re.search(
            rf'"{key}"\s*:\s*[^,\}}]+.*?\}}', content, re.DOTALL))

    @staticmethod
    def _reason_is_meaningful(content):
        """_has_complete_field("reason") пропускает и `"reason": ""` —
        пустая строка тоже "непустой фрагмент, за которым есть }". Модель
        изредка выдаёт валидный JSON с абсолютно пустым reason при
        нормальном score — такой балл невозможно перепроверить (нет
        обоснования вообще). Явно требуем содержательный текст."""
        m = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"',
                      content, re.DOTALL)
        return bool(m and len(m.group(1).strip()) >= 15)

    def _chat_retrying(self, system, user, temperature, max_tokens,
                       attempts=3, validator=None):
        """_chat с повтором, если ответ пуст или не прошёл validator
        (по умолчанию — любой непустой ответ считается успехом).

        Изредка модель срывается в незакрытую генерацию (руинед-луп) и
        жжёт весь max_tokens, либо обрывает ответ на середине по другой
        причине (не связанной с лимитом токенов) — тогда content
        непустой, но это мусорный фрагмент вроде «```json» без самого
        JSON. При низкой temperature и включённом кэше префикса
        (--parallel 1 в LM Studio) повтор с ТЕМИ ЖЕ параметрами
        детерминированно повторяет тот же срыв — проверено: два подряд
        провала дали идентичное число чанков. Поэтому каждая следующая
        попытка меняет temperature и seed, чтобы это была другая
        генерация, а не эхо первой."""
        last_err = None
        for attempt in range(1, attempts + 1):
            t = temperature if attempt == 1 else min(1.0, temperature + 0.25 * attempt)
            seed = None if attempt == 1 else random.randint(0, 2**31 - 1)
            content = self._chat(system, user, t, max_tokens, seed=seed)
            if content and (validator is None or validator(content)):
                return content
            if content:
                last_err = f"ответ обрезан/неполон ({content[:60]!r})"
            else:
                last_err = (f"пустой ответ (finish_reason="
                           f"{getattr(self, 'last_finish', None)}, "
                           f"чанков={getattr(self, 'last_chunks', 0)})")
            if attempt < attempts:
                self.log(f"Модель дала {last_err} — повторяю попытку "
                         f"{attempt + 1}/{attempts} с другой температурой…")
        raise EvaluationExhausted(f"модель вернула {last_err} после "
                                  f"{attempts} попыток")

    def triage(self, profile, items):
        """Быстрый отсев по заголовкам. Модель называет только ЯВНО
        неподходящие вакансии; всё остальное идёт на полную проверку.
        Возвращает множество id, которые стоит проверить полностью.
        При сбое разбора ответа пачка проходит дальше целиком
        (лучше лишняя проверка, чем потеря)."""
        survivors = set()
        chunk_size = 25
        for start in range(0, len(items), chunk_size):
            chunk = items[start:start + chunk_size]
            chunk_ids = {i["id"] for i in chunk}
            lines = "\n".join(
                f'{i["id"]} | {i["name"]}'
                for i in chunk
            )
            content = self._chat_retrying(
                TRIAGE_PROMPT.format(profile=profile), lines,
                temperature=0.1, max_tokens=1500,
                validator=lambda c: self._has_complete_field(
                    c, "exclude_ids"),
            )

            excluded = None
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                    excluded = {str(x) for x in data.get("exclude_ids", [])}
                except (json.JSONDecodeError, TypeError):
                    excluded = None
            if excluded is None:
                excluded = set()  # не разобрали ответ — ничего не отсеиваем
            protected = {i['id'] for i in chunk if re.search(
                r'координатор|администратор|ассистент|помощник|аналитик|поддержк|проект|проджект|продукт|'
                r'сопровожд|инженер|техническ\w*\s+писател|заявк|офис|закуп|'
                r'информационн\w*\s+безопасност|кибербезопасност|'
                r'coordinat|admin|assistant|analyst|support|project|product|junior|стаж[её]р',
                i['name'], re.I)}
            # A small model's exclusion is only advisory. Unknown professions
            # must survive even if the model confidently names their IDs.
            clearly_unrelated = {i['id'] for i in chunk if re.search(
                r'повар|врач|медсестр|\bводител|курьер|грузчик|сварщик|визажист|'
                r'парикмахер|уборщик|кадров|рекрут|маркетинг|маркетолог|'
                r'бренд.менеджер|блогер|\bugc\b|суперинтендант|\bteacher\b',
                i['name'], re.I)}
            excluded &= clearly_unrelated
            survivors |= (chunk_ids - excluded) | protected
        return survivors

    _VERDICTS = {"STRONG_MATCH", "MATCH", "WEAK", "REJECT", "REVIEW"}
    _DIRECTIONS = {"координация", "техподдержка", "данные", "оргроли"}
    # Какое из готовых резюме подходит под направление — решается кодом,
    # не моделью: одним полем меньше, о котором надо думать при чтении
    # результатов, и нет риска, что модель напишет direction и resume
    # непоследовательно друг с другом.
    _DIRECTION_TO_RESUME = {
        "координация": "координатор",
        "техподдержка": "техподдержка/сисадмин",
        "данные": "общее",
        "оргроли": "общее",
    }

    @classmethod
    def _finalize(cls, verdict, score, direction, reason, reason_from_regex):
        verdict = verdict if verdict in cls._VERDICTS else "WEAK"
        try:
            score = max(0, min(100, int(float(score or 0))))
        except (TypeError, ValueError):
            score = 0
        direction = direction if direction in cls._DIRECTIONS else None
        resume = cls._DIRECTION_TO_RESUME.get(direction, "общее")
        reason = reason_from_regex or (reason or "").strip()
        return verdict, score, direction, reason, resume

    @classmethod
    def _parse(cls, content):
        # Причину всегда достаём отдельным regex'ом — ПЕРВОЕ валидное
        # значение "reason", не через json.loads. Модель изредка дублирует
        # ключ "reason" вторым, часто пустым значением («"reason": ""»);
        # по правилам JSON при дублирующемся ключе побеждает ПОСЛЕДНЕЕ —
        # json.loads тогда молча возвращает пустую причину при абсолютно
        # валидном балле, хотя модель изначально написала осмысленный
        # текст. Регексом ищем именно первое (содержательное) вхождение.
        m_reason = re.search(r'"reason"\s*:\s*"((?:[^"\\]|\\.)*)"',
                             content, re.DOTALL)
        reason_from_regex = m_reason.group(1).strip() if m_reason else ""
        if reason_from_regex:
            try:
                reason_from_regex = json.loads('"' + reason_from_regex + '"')
            except ValueError:
                pass
        # Модель может обернуть JSON в текст или ```-блок — достаём первый {...}
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                direction = str(data.get("direction", "") or "").strip().lower()
                return cls._finalize(
                    str(data.get("verdict", "")).strip().upper(),
                    data.get("score", 0),
                    direction or None,
                    str(data.get("reason", "")),
                    reason_from_regex,
                )
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        # Строгий json.loads мог упасть из-за буквального переноса строки
        # внутри значения "reason" (модель не экранировала \n) — достаём
        # остальные поля отдельными прицельными regex'ами вместо json.loads
        # на всём блоке.
        m_verdict = re.search(r'"verdict"\s*:\s*"([A-Za-z_]+)"', content)
        m_score = re.search(r'"score"\s*:\s*([\d.]+)', content)
        m_direction = re.search(r'"direction"\s*:\s*"([^"]*)"', content)
        if m_verdict or m_score:
            return cls._finalize(
                m_verdict.group(1).upper() if m_verdict else "",
                m_score.group(1) if m_score else 0,
                m_direction.group(1).strip().lower() if m_direction else None,
                reason_from_regex,
                reason_from_regex,
            )
        # Совсем не удалось разобрать — по-прежнему лучше вернуть что-то,
        # чем упасть; но это уже не должно происходить благодаря
        # validator'у в _chat_retrying, отсеивающему оборванные ответы.
        # WEAK, а не REJECT: неразобранный ответ — не сигнал об отказе.
        return cls._finalize(
            "WEAK", 0, None,
            reason_from_regex or content.strip()[:300],
            reason_from_regex,
        )


# ----------------------------------------------------------------------
# Запись результатов
# ----------------------------------------------------------------------

class ResultWriter:
    def __init__(self, profile_hash=""):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        self.profile_hash = profile_hash
        self.suitable_path = os.path.join(RESULTS_DIR, "suitable.md")
        self.rejected_path = os.path.join(RESULTS_DIR, "rejected.md")
        self.skipped_path = os.path.join(RESULTS_DIR, "skipped.md")
        self.failed_path = os.path.join(RESULTS_DIR, "failed.md")
        self.csv_path = os.path.join(RESULTS_DIR, "results.csv")
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", encoding="utf-8-sig", newline="") as f:
                csv.writer(f, delimiter=";").writerow(
                    ["дата", "оценка", "вердикт", "должность", "компания",
                     "зарплата", "ссылка", "почему", "id", "профиль",
                     "направление", "резюме"]
                )

    def write(self, item, score, verdict, direction, resume, reason,
              suitable):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = (
            f"- **{score}/100 ({verdict})** — [{item['name']}]({item['url']}) "
            f"— {item['employer']}, {item['salary']} "
            f"_(направление {direction or '—'}, резюме {resume})_\n"
            f"  - {reason}\n"
        )
        path = (os.path.join(RESULTS_DIR, "review.md") if verdict == "REVIEW" else
                self.suitable_path if suitable else self.rejected_path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        with open(self.csv_path, "a", encoding="utf-8-sig", newline="") as f:
            csv.writer(f, delimiter=";").writerow(
                [now, score, verdict, item["name"], item["employer"],
                 item["salary"], item["url"], reason, item["id"],
                 self.profile_hash, direction or "", resume]
            )

    def write_skipped(self, item, why):
        """Отсеянные на быстрых фильтрах — одной строкой, для контроля."""
        with open(self.skipped_path, "a", encoding="utf-8") as f:
            f.write(
                f"- [{item['name']}]({item['url']}) — {item['employer']}, "
                f"{item['salary']} _({why})_\n"
            )

    def write_failed(self, item, error):
        """Нейросеть не смогла оценить вакансию после всех попыток —
        сюда, чтобы можно было посмотреть её вручную. Вакансия всё равно
        переоценится автоматически при следующем запуске."""
        with open(self.failed_path, "a", encoding="utf-8") as f:
            f.write(
                f"- [{item['name']}]({item['url']}) — {item['employer']}, "
                f"{item['salary']} _(ошибка оценки: {error})_\n"
            )


# ----------------------------------------------------------------------
# Рабочий поток
# ----------------------------------------------------------------------

class Worker(threading.Thread):
    def __init__(self, cfg, profile, out_queue, stop_event):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.profile = profile
        self.q = out_queue
        self.stop_event = stop_event

    def log(self, msg):
        self.q.put(("log", msg))
        # Дублируем журнал в файл — для разбора «что случилось в прогоне».
        try:
            os.makedirs(RESULTS_DIR, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(os.path.join(RESULTS_DIR, "log.txt"), "a",
                      encoding="utf-8") as f:
                f.write(f"[{stamp}] {msg}\n")
        except OSError:
            pass

    def _role_names(self):
        """Имена категорий: из кэша, а если его нет (например, после
        очистки cache/) — подгружает справочник заново с api.hh.ru,
        как это делает диалог выбора категорий в интерфейсе."""
        path = os.path.join(CACHE_DIR, "professional_roles.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            try:
                r = requests.get("https://api.hh.ru/professional_roles",
                                headers=BROWSER_HEADERS, timeout=20)
                r.raise_for_status()
                data = r.json()
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except requests.RequestException as e:
                self.log(f"Не удалось получить названия категорий: {e}")
                return {}
        try:
            return {str(r["id"]): r["name"]
                    for g in data.get("categories", [])
                    for r in g.get("roles", [])}
        except (KeyError, AttributeError):
            return {}

    def pause(self):
        """Случайная пауза в человеческом темпе."""
        delay = random.uniform(self.cfg["min_delay"], self.cfg["max_delay"])
        end = time.time() + delay
        while time.time() < end:
            if self.stop_event.is_set():
                return
            time.sleep(0.2)

    def run(self):
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 — показываем любую ошибку в GUI
            self.log(f"ОШИБКА: {e}")
        finally:
            if getattr(self, "store", None) is not None:
                try:
                    if getattr(self, "writer", None) is not None:
                        self._write_top(self.writer, self.cfg)
                except OSError as exc:
                    self.log(f"Не удалось обновить top.md: {exc}")
                finally:
                    self.store.close()
            self.q.put(("done", None))

    def _run(self):
        cfg = self.cfg
        hh = HHClient(self.log)
        llm = LLMClient(cfg["lm_url"], cfg["lm_model"], self.log,
                        self.stop_event)
        llm.reasoning_effort = cfg.get('lm_reasoning_effort', 'none')
        manager = None
        fast_name = cfg.get("lm_model_fast", "").strip()
        if cfg.get('manage_local_models'):
            manager = LocalModelManager(cfg['lm_url'],
                [llm.model, fast_name if cfg['triage'] else ''], self.log,
                self.stop_event, cfg.get('model_gpu', {}), cfg.get('model_context', 8192))
            llm.manager = manager

        self.log("Проверяю связь с LM Studio…")
        model = llm.check()
        self.log(f"Модель оценки: {model}")
        llm_fast = llm
        fast_name = cfg.get("lm_model_fast", "").strip()
        if cfg["triage"] and fast_name:
            llm_fast = LLMClient(cfg["lm_url"], fast_name, self.log,
                                 self.stop_event)
            llm_fast.manager = manager
            self.log(f"Модель отсева: {llm_fast.check()}")

        profile_hash = evaluation_fingerprint(
            self.profile, cfg, llm.model, llm_fast.model,
            [SYSTEM_PROMPT, TRIAGE_PROMPT, FACT_PROMPT, "evidence-rules-v5"])
        self.store = EvaluationStore(os.path.join(CACHE_DIR, "evaluations.sqlite3"),
                                     profile_hash)
        writer = ResultWriter(profile_hash)
        self.writer = writer
        seen = self.store.completed_ids()
        attempted = set()  # Failed/incomplete entries retry on the next launch.
        self._write_top(writer, cfg)
        last_top_update = time.monotonic()
        self.log(f"Уже завершено с текущими правилами и моделями: {len(seen)} вакансий — "
                 "их повторно не проверяю. После изменения правил или модели "
                 "вакансии оцениваются заново; старая история сохраняется.")
        area = AREAS.get(cfg["area"], "113")
        experience = EXPERIENCE.get(cfg["experience"], "")
        queries = [q.strip() for q in cfg["queries"].splitlines() if q.strip()]
        # Источники поиска. Категории и запросы HH — ПЕРВЫМИ: это основной,
        # ограниченный по объёму охват, который должен успеть отработать
        # в рамках одной сессии. Рекомендации HH — почти бездонный источник
        # (HH подмешивает новые вакансии почти каждый прогон) и с медленной
        # моделью может занять часы. Хабр Карьера — САМЫЙ ПОСЛЕДНИЙ: эта
        # площадка ориентирована на готовых специалистов, стажировок и
        # junior-позиций начального уровня там почти нет.
        passes = []
        hh_auth = None
        resume_only = bool(cfg.get("recs_enabled") and cfg.get("hh_resume_only"))
        habr = (HabrClient(self.log)
                if cfg.get("habr_enabled") and not resume_only else None)
        if resume_only:
            self.log("Режим «только рекомендации под резюме»: категории, "
                     "запросы и Хабр Карьера пропущены — бесконечно "
                     "опрашиваю только рекомендации HH под резюме.")
        if not resume_only:
            passes.extend((f"запрос «{q}»", {"query": q}) for q in queries)
        if cfg["role_ids"] and not resume_only:
            if cfg.get("split_roles"):
                names = self._role_names()
                for rid in cfg["role_ids"]:
                    passes.append(
                        (f"категория «{names.get(rid, rid)}»",
                         {"roles": [rid]}))
            else:
                passes.append((f"категории HH ({len(cfg['role_ids'])} шт.)",
                               {"roles": cfg["role_ids"]}))
            if cfg.get("remote_extra"):
                passes.append(("категории HH, удалёнка по всей России",
                               {"roles": cfg["role_ids"], "area": "113",
                                "remote": True}))
        if cfg.get("recs_enabled"):
            hash_m = re.search(r"[0-9a-f]{30,45}",
                               cfg.get("resume_hash", "") or "")
            cookie = (cfg.get("hh_cookie", "") or "").strip()
            if hash_m and cookie:
                hh_auth = HHClient(self.log, cookie=cookie)
                passes.append(("рекомендации HH под резюме",
                               {"resume": hash_m.group(0), "auth": True}))
            else:
                self.log("Рекомендации HH пропущены: не заданы cookie "
                         "или ссылка на резюме (вкладка «Аккаунт HH»).")
        if habr:
            # Хабр Карьера — последний источник: аудитория площадки
            # смещена к готовым специалистам (мало стажировок/junior-
            # позиций начального уровня без опыта), поэтому не должен
            # отнимать время у более профильных проходов по hh.ru.
            passes.extend(
                (f"Хабр Карьера: «{q}»", {"query": q, "source": "habr"})
                for q in queries)
        superjob = (
            SuperJobClient(self.log, cookie=cfg.get("superjob_cookie"))
            if (cfg.get("superjob_enabled")
                or cfg.get("superjob_cookie", "").strip())
               and not resume_only
            else None)
        if superjob and cfg.get("superjob_enabled") and not resume_only:
            passes.extend(
                (f"SuperJob: «{q}»", {"query": q, "source": "superjob"})
                for q in queries)
        if superjob and cfg.get("superjob_cookie", "").strip():
            passes.append(("рекомендации SuperJob под резюме",
                           {"source": "superjob_recs"}))
        telegram_channels = [c.strip().lstrip("@").split("t.me/")[-1]
                             for c in cfg.get("telegram_channels", "")
                                        .splitlines() if c.strip()]
        telegram = (TelegramClient(self.log)
                   if cfg.get("telegram_enabled") and not resume_only
                      and telegram_channels
                   else None)
        if telegram:
            passes.extend(
                (f"Telegram: @{ch}", {"channel": ch, "source": "telegram"})
                for ch in telegram_channels)
        exclude = [w.strip().lower()
                   for w in cfg["exclude_words"].split(",") if w.strip()]
        include = [w.strip().lower()
                   for w in cfg["include_words"].split(",") if w.strip()]
        bad_companies = [w.strip().lower()
                         for w in cfg["exclude_companies"].split(",")
                         if w.strip()]

        checked = suitable_count = skipped_count = 0
        processed_since_break = 0

        if not passes:
            raise RuntimeError("Нет доступных источников: проверьте настройки поиска и рекомендации.")

        while True:
            pending = []
            queued_ids = set()
            self.log("Собираю вакансии и проверяю названия…")
            for qi, (label, source) in enumerate(passes):
                if self.stop_event.is_set():
                    break
                self.log(f"— Источник {qi + 1}/{len(passes)}: {label}")
                src_skipped = skipped_count
                src_new = 0

                src_kind = source.get("source")
                if src_kind == "habr":
                    client = habr
                elif src_kind in ("superjob", "superjob_recs"):
                    client = superjob
                elif src_kind == "telegram":
                    client = telegram
                else:
                    client = hh_auth if source.get("auth") else hh
                for page in range(cfg["pages"]):
                    if self.stop_event.is_set():
                        break
                    try:
                        if src_kind in ("habr", "superjob"):
                            items, last_page = client.search(
                                source.get("query", ""), page)
                        elif src_kind == "superjob_recs":
                            items, last_page = client.search_recs(page)
                        elif src_kind == "telegram":
                            items, last_page = client.search(
                                source["channel"], page)
                        elif source.get("resume"):
                            items, last_page = client.search(
                                "", "", "", False, False, page,
                                resume=source["resume"],
                            )
                        else:
                            items, last_page = client.search(
                                source.get("query", ""),
                                source.get("area", area), experience,
                                source.get("remote", cfg["remote_only"]),
                                cfg["only_with_salary"], page,
                                roles=source.get("roles"),
                            )
                    except (requests.RequestException, RuntimeError) as e:
                        self.log(f"Источник пропущен: {e}")
                        break
                    if not items:
                        self.log("Больше вакансий нет.")
                        break
                    new_items = list({i["id"]: i for i in items
                                      if i["id"] not in seen and i["id"] not in attempted
                                      and i["id"] not in queued_ids}.values())
                    src_new += len(new_items)
                    self.log(f"Страница {page + 1}: всего {len(items)}, "
                             f"новых {len(new_items)}")
                    if not new_items:
                        if page >= last_page:
                            break
                        self.pause()
                        continue

                    # Ступень 1: быстрые фильтры. Целевые слова проверяются
                    # РАНЬШЕ стоп-слов: «RPA-разработчик» должен выжить,
                    # хотя «разработчик» — стоп-слово. Утечку сеньоров
                    # страхуют фильтр опыта и промпт оценки.
                    blocked_exp = EXP_FILTER.get(cfg.get("exp_filter", ""), ())
                    bypass, gray = [], []
                    for item in new_items:
                        if item.get("experience") in blocked_exp:
                            seen.add(item["id"])
                            skipped_count += 1
                            why = f"требуется опыт {EXP_LABEL[item['experience']]}"
                            writer.write_skipped(item, why)
                            self.store.mark(item["id"], "skipped", why)
                            continue
                        company_hit = word_hit(bad_companies,
                                               item["employer"].lower())
                        if company_hit:
                            seen.add(item["id"])
                            skipped_count += 1
                            writer.write_skipped(
                                item, f"компания «{company_hit}» в чёрном списке")
                            self.store.mark(item["id"], "skipped", f"компания: {company_hit}")
                            continue
                        title = item["name"].lower()
                        if word_hit(include, title):
                            bypass.append(item)
                            continue
                        hit = word_hit(exclude, title)
                        if hit:
                            seen.add(item["id"])
                            skipped_count += 1
                            writer.write_skipped(item, f"стоп-слово «{hit}»")
                            self.store.mark(item["id"], "skipped", f"стоп-слово: {hit}")
                        else:
                            gray.append(item)

                    if bypass:
                        self.log(f"По целевым словам сразу на полную "
                                 f"проверку: {len(bypass)}")
                    kept = list(bypass)

                    # Ступень 2: «серые» заголовки — нейросети, пачкой.
                    if cfg["triage"] and gray:
                        self.log(f"Быстрый отсев по заголовкам "
                                 f"({len(gray)} шт.)…")
                        try:
                            ok_ids = llm_fast.triage(
                                short_profile(self.profile), gray)
                        except (requests.RequestException,
                                RuntimeError) as e:
                            self.log(f"Отсев не удался ({e}) — все идут "
                                     "на полную проверку.")
                            ok_ids = {i["id"] for i in gray}
                        for item in gray:
                            if item["id"] in ok_ids:
                                kept.append(item)
                            else:
                                seen.add(item["id"])
                                skipped_count += 1
                                writer.write_skipped(
                                    item, "отсев по заголовку")
                                self.store.mark(item["id"], "skipped", "отсев по заголовку")
                    elif gray:
                        kept.extend(gray)
                    self.log(f"К полной проверке: {len(kept)} "
                             f"из {len(new_items)}")
                    self.q.put(("stats",
                                (skipped_count, checked, suitable_count)))

                    pending.extend(kept)
                    queued_ids.update(i["id"] for i in kept)

                    if page >= last_page:
                        break
                    self.pause()

                self.log(f"Сбор источника «{label}»: новых {src_new}, "
                         f"отсеяно {skipped_count - src_skipped}.")
                if qi + 1 < len(passes):
                    self.pause()

            self.log(f"Сбор завершён. Полная проверка: {len(pending)} вакансий.")
            # One evaluation stage avoids reloading the large model per page.
            for item in pending:
                if self.stop_event.is_set():
                    break
                self.pause()
                if self.stop_event.is_set():
                    break

                attempted.add(item["id"])
                try:
                    if item["id"].startswith("habr-"):
                        desc_client = habr
                    elif item["id"].startswith("sj-"):
                        desc_client = superjob
                    elif item["id"].startswith("tg-"):
                        desc_client = telegram
                    else:
                        desc_client = hh
                    description = desc_client.description(
                        item["url"])
                except (requests.RequestException, RuntimeError, ValueError) as e:
                    self._record_issue(writer, item, "incomplete", str(e))
                    continue
                if not description.strip():
                    self._record_issue(writer, item, "incomplete",
                                       "Описание не найдено; нужна повторная загрузка.")
                    continue

                checked += 1
                vacancy_text = (
                    f"Должность: {item['name']}\n"
                    f"Компания: {item['employer']}\n"
                    f"Зарплата: {item['salary']}\n"
                    f"Тег HH (не требование из описания): "
                    f"{EXP_LABEL.get(item.get('experience'), 'не указан')}"
                    f"\n\nОписание: {description}"
                )

                self.log(f"Оцениваю: {item['name']} "
                         f"({item['employer']})…")
                saved_description = audit_path(CACHE_DIR, profile_hash, item, vacancy_text)
                save_audit(saved_description, item, vacancy_text, profile_hash,
                           llm.model, self.profile, status="pending")
                try:
                    verdict, score, direction, reason, resume = (
                        llm.evaluate(self.profile, vacancy_text))
                except (EvaluationExhausted, requests.RequestException, RuntimeError) as e:
                    save_audit(saved_description, item, vacancy_text, profile_hash,
                               llm.model, self.profile, status="failed", error=str(e))
                    if self.stop_event.is_set():
                        break
                    self._record_issue(writer, item, "failed", str(e))
                    continue

                save_audit(saved_description, item, vacancy_text, profile_hash,
                           llm.model, self.profile, status="evaluated",
                           evidence=getattr(llm, "last_evidence", None))
                suitable = None if verdict == "REVIEW" else verdict != "REJECT"
                if suitable:
                    suitable_count += 1
                writer.write(item, score, verdict, direction,
                             resume, reason, suitable)
                self.store.mark(item["id"], "evaluated", reason)
                seen.add(item["id"])
                if time.monotonic() - last_top_update >= 30:
                    self._write_top(writer, cfg)
                    last_top_update = time.monotonic()
                self.q.put(("result", {
                    "score": score, "verdict": verdict,
                    "direction": direction, "resume": resume,
                    "name": item["name"],
                    "employer": item["employer"],
                    "salary": item["salary"], "url": item["url"],
                    "suitable": suitable, "reason": reason,
                }))
                self.q.put(("stats",
                            (skipped_count, checked, suitable_count)))

                processed_since_break += 1
                if processed_since_break >= 10:
                    processed_since_break = 0
                    rest = random.uniform(15, 30)
                    self.log(f"Длинная пауза {rest:.0f} с "
                             "(человеческий темп)…")
                    end = time.time() + rest
                    while (time.time() < end
                           and not self.stop_event.is_set()):
                        time.sleep(0.2)


            self._write_top(writer, cfg)
            self.log(
                f"Готово. Отсеяно на быстрых фильтрах: {skipped_count}, "
                f"проверено полностью: {checked}, подходящих: {suitable_count}. "
                f"Файлы — в папке results (top.md — лучшие сверху)."
            )

            if self.stop_event.is_set():
                break

            # Приложение оставляют работать без присмотра — вместо того
            # чтобы завершиться после одного прохода, опрашиваем все
            # источники заново по кругу (hh.ru подмешивает новые вакансии
            # постоянно). Пауза между кругами — чтобы не долбить сайт
            # вхолостую сразу после «Готово», а не потому что круг
            # предполагается быстрым: сам круг по всем источникам обычно
            # и так занимает часы.
            poll_wait = 300
            self.log(f"Круг по всем источникам завершён. Жду {poll_wait} с "
                     "перед следующим кругом (Стоп — чтобы прервать)…")
            wait_end = time.time() + poll_wait
            while (time.time() < wait_end
                   and not self.stop_event.is_set()):
                time.sleep(0.2)

    def _record_issue(self, writer, item, status, reason):
        self.store.mark(item["id"], status, reason)
        writer.write_failed(item, reason)
        self.log(f"Нужна проверка: {item['name']}: {reason} "
                 "Повторная попытка — при следующем запуске.")
        self.q.put(("result", {
            "score": None, "name": item["name"], "employer": item["employer"],
            "salary": item["salary"], "url": item["url"], "suitable": None,
            "direction": None, "resume": None, "reason": reason,
        }))

    # Приоритет направлений при равном балле (правило сортировки из
    # профиля: «выше — вакансии направлений 1 и 2»). Свежесть и
    # размер компании из тех же правил здесь не учтены — скрапер не
    # хранит дату публикации вакансии и не классифицирует размер
    # компании, так что честной опоры для этих двух критериев нет.
    _DIRECTION_RANK = {"координация": 0, "техподдержка": 1, "данные": 2,
                       "оргроли": 3}

    def _write_top(self, writer, cfg):
        """Последняя оценка каждой вакансии по текущей версии правил и моделей.
        Старые строки CSV сохраняются для истории, но не участвуют в top.md.
        """
        rows = {}
        try:
            with open(writer.csv_path, encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter=";")
                next(reader, None)
                for r in reader:
                    if len(r) < 8:
                        continue
                    _, score, verdict, name, employer, salary, url, reason \
                        = r[:8]
                    row_hash = r[9] if len(r) > 9 else ""
                    direction = r[10] if len(r) > 10 else ""
                    resume = r[11] if len(r) > 11 else ""
                    try:
                        score = int(score)
                    except ValueError:
                        continue
                    if row_hash != writer.profile_hash:
                        rows.pop(url, None)
                        continue
                    # Файл дописывается хронологически — последняя
                    # встреченная строка для URL и есть самая свежая.
                    rows[url] = {
                        "score": score, "verdict": verdict,
                        "direction": direction or None, "resume": resume,
                        "name": name, "employer": employer,
                        "salary": salary, "url": url, "reason": reason,
                    }
        except OSError:
            return
        top = sorted(
            (v for v in rows.values() if v["verdict"] in {"MATCH", "STRONG_MATCH", "WEAK"}),
            key=lambda v: (-v["score"],
                           self._DIRECTION_RANK.get(v["direction"], 4)))
        path = os.path.join(RESULTS_DIR, "top.md")
        with atomic_text(path) as f:
            f.write("# Подходящие вакансии, лучшие сверху\n\n")
            f.write(f"Обновлено: {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
            for v in top:
                dir_tag = (f", направление {v['direction']}"
                          if v["direction"] else "")
                f.write(
                    f"- **{v['score']}/100 ({v['verdict']})** — "
                    f"[{v['name']}]({v['url']}) — {v['employer']}, "
                    f"{v['salary']}{dir_tag}, резюме {v['resume'] or '—'}\n"
                    f"  - {v['reason']}\n")
        self.log(f"Обновлён results/top.md ({len(top)} вакансий).")


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------

class App:
    def __init__(self, root):
        self.root = root
        root.title("HH Assistant — подбор вакансий с локальной нейросетью")
        root.geometry("1000x760")
        root.minsize(880, 620)

        self.cfg = load_config()
        self.queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.result_data = {}
        self.browser_queue = BrowserQueue(root, self._browser_queue_update)

        self._build_ui()
        self._ensure_profile()
        for key, warning in self.cfg.get("_credential_errors", {}).items():
            account = "HH" if key == "hh_cookie" else "SuperJob"
            self.log(f"Cookies {account}: {warning} Обычный поиск доступен без cookies.")
        self.root.after(150, self._poll_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_close(self):
        self.browser_queue.cancel(notify=False)
        if self.worker is not None and self.worker.is_alive():
            self.stop_event.set()
            self.lbl_status.configure(text="Завершаю запрос и сохраняю результаты…")
            self.root.after(150, self.on_close)
            return
        self.root.destroy()

    # -- построение интерфейса ------------------------------------------

    def _build_ui(self):
        from desktop_ui import DesktopUI
        self.ui = DesktopUI(self, AREAS, EXPERIENCE, EXP_FILTER)

    # -- служебное --------------------------------------------------------

    def _ensure_profile(self):
        if not os.path.exists(PROFILE_PATH):
            with open(PROFILE_PATH, "w", encoding="utf-8") as f:
                f.write(DEFAULT_PROFILE)
            self.log("Создан файл profile.txt — заполните его перед первым "
                     "запуском (кнопка «Мой профиль…»).")
        else:
            self.log("Профиль загружен из profile.txt.")
        self.log("Обычный поиск читает публичные страницы. "
                 "Рекомендации используют сессию аккаунта из cookies.")
        if self.cfg.get("recs_enabled") and self.cfg.get("hh_resume_only"):
            self.log("Активен только HH по резюме: категории, запросы, "
                     "Хабр, SuperJob и Telegram отключены этим режимом.")

    # Приоритет направлений при равном балле — тот же порядок, что и в
    # Worker._DIRECTION_RANK (top.md), чтобы список в приложении и файл
    # сортировались одинаково.
    _DIRECTION_RANK = {"координация": 0, "техподдержка": 1, "данные": 2,
                       "оргроли": 3}

    def _read_history_rows(self):
        """Читает ТОЛЬКО results/results.csv — то есть всё, что накопилось
        с момента последнего «сброса логов» (архивные results/archive-*/
        сознательно не трогаем: это прошлые отрезки ДО сброса, пользователь
        явно попросил не тащить их сюда). Возвращает список вакансий,
        REJECT исключён сразу — смотреть на явно неподходящие смысла нет.
        Лучшие сверху. Чистая функция, таблицу в GUI не трогает —
        используется только окном истории.

        Не фильтрует по отпечатку текущего профиля (в отличие от
        top.md/_write_top) — внутри одного «отрезка после сброса»
        профиль обычно не успевает поменяться несколько раз, а если и
        меняется — пользователь и так видит всё целиком и разберётся
        сам, а не гадает, почему часть истории пропала."""
        csv_path = os.path.join(RESULTS_DIR, "results.csv")

        # Старые прогоны (до перехода на нынешнюю систему оценки
        # 03.09.2026) писали шкалу 0-10 и вердикт текстом ("подходит"/
        # "не подходит") — оставляю пересчёт на случай, если такая
        # строка когда-то попадёт в текущий results.csv.
        old_verdict_map = {"подходит": "MATCH", "не подходит": "REJECT"}

        rows = {}
        try:
            with open(csv_path, encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter=";")
                next(reader, None)
                for r in reader:
                    if len(r) < 8:
                        continue
                    (_, score, verdict, name, employer, salary, url,
                     reason) = r[:8]
                    direction = r[10] if len(r) > 10 else ""
                    resume = r[11] if len(r) > 11 else ""
                    try:
                        score_i = int(score)
                    except ValueError:
                        continue
                    if verdict in old_verdict_map:
                        score_i = min(100, score_i * 10)
                        verdict = old_verdict_map[verdict]
                    # Файл дописывается хронологически — последняя
                    # встреченная строка для URL и есть самая свежая.
                    if verdict == "REJECT":
                        rows.pop(url, None)
                        continue
                    rows[url] = {
                        "score": score_i, "verdict": verdict,
                        "name": name, "employer": employer,
                        "salary": salary, "url": url, "reason": reason,
                        "direction": direction or None,
                        "resume": resume,
                        "suitable": None if verdict == "REVIEW" else True,
                    }
        except OSError:
            return []
        return sorted(
            rows.values(),
            key=lambda v: (-v["score"],
                           self._DIRECTION_RANK.get(v["direction"], 4)))

    def on_open_history(self):
        """Отдельное окно «История» — весь накопленный results.csv +
        все архивы под текущий профиль, отдельно от живой вкладки
        «Результаты», которая по-прежнему заполняется только во время
        прогона (как раньше). С фильтрами по направлению и вердикту —
        как в Excel по столбцам."""
        rows = self._read_history_rows()

        win = tk.Toplevel(self.root)
        win.title(f"История — {len(rows)} вакансий")
        win.geometry("900x640")

        filter_row = ttk.Frame(win)
        filter_row.pack(fill="x", padx=4, pady=(4, 0))

        ttk.Label(filter_row, text="Направление:").pack(
            side="left", padx=(0, 4))
        direction_values = ["Все"] + sorted(
            {v["direction"] or "—" for v in rows})
        var_direction = tk.StringVar(value="Все")
        cmb_direction = ttk.Combobox(
            filter_row, textvariable=var_direction,
            values=direction_values, state="readonly", width=14)
        cmb_direction.pack(side="left", padx=(0, 12))

        ttk.Label(filter_row, text="Вердикт:").pack(side="left", padx=(0, 4))
        var_verdict = tk.StringVar(value="Все")
        cmb_verdict = ttk.Combobox(
            filter_row, textvariable=var_verdict,
            values=["Все", "STRONG_MATCH", "MATCH", "WEAK", "REVIEW"],
            state="readonly", width=14)
        cmb_verdict.pack(side="left")

        lbl_count = ttk.Label(filter_row, text="")
        lbl_count.pack(side="right")

        table_frame = ttk.Frame(win)
        table_frame.pack(fill="both", expand=True, padx=4, pady=4)
        cols = ("score", "verdict", "direction", "resume", "name",
                "employer", "salary")
        tree = ttk.Treeview(table_frame, columns=cols, show="headings")
        for col, title, width in [
            ("score", "Балл", 60), ("verdict", "Вердикт", 90),
            ("direction", "Направл.", 60), ("resume", "Резюме", 60),
            ("name", "Должность", 300), ("employer", "Компания", 180),
            ("salary", "Зарплата", 150),
        ]:
            tree.heading(col, text=title)
            tree.column(col, width=width,
                        anchor="center" if col == "score" else "w")
        vsb = ttk.Scrollbar(table_frame, orient="vertical",
                            command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        tree.tag_configure("good", background="#f5f9f3")
        tree.tag_configure("bad", background="#fbf9ef")

        reason_frame = ttk.LabelFrame(
            win, text="Почему такая оценка (выберите строку; "
                      "двойной клик — открыть вакансию)")
        reason_frame.pack(fill="x", padx=4, pady=4)
        txt_reason = tk.Text(reason_frame, height=4, wrap="word",
                             state="disabled", relief="flat")
        txt_reason.pack(fill="x", padx=4, pady=4)

        row_data = {}

        def render(*_args):
            tree.delete(*tree.get_children())
            row_data.clear()
            want_dir = var_direction.get()
            want_verdict = var_verdict.get()
            shown = 0
            for v in rows:
                if (want_dir != "Все"
                        and (v["direction"] or "—") != want_dir):
                    continue
                if want_verdict != "Все" and v["verdict"] != want_verdict:
                    continue
                tag = ("good" if v["verdict"] in ("STRONG_MATCH", "MATCH")
                       else "bad")
                iid = tree.insert(
                    "", "end",
                    values=(f'{v["score"]}/100', v["verdict"],
                            v["direction"] or "—", v["resume"] or "—",
                            v["name"], v["employer"], v["salary"]),
                    tags=(tag,))
                row_data[iid] = v
                shown += 1
            lbl_count.configure(text=f"Показано: {shown} из {len(rows)}")

        cmb_direction.bind("<<ComboboxSelected>>", render)
        cmb_verdict.bind("<<ComboboxSelected>>", render)
        render()

        def on_select(_event):
            sel = tree.selection()
            if not sel or sel[0] not in row_data:
                return
            data = row_data[sel[0]]
            text = data["reason"] or "(без объяснения)"
            if data.get("resume"):
                text = f'Резюме: {data["resume"]} · {text}'
            txt_reason.configure(state="normal")
            txt_reason.delete("1.0", "end")
            txt_reason.insert("1.0", text)
            txt_reason.configure(state="disabled")

        def on_double(_event):
            sel = tree.selection()
            if sel and sel[0] in row_data:
                webbrowser.open(row_data[sel[0]]["url"])

        tree.bind("<<TreeviewSelect>>", on_select)
        tree.bind("<Double-1>", on_double)

    def log(self, msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", f"[{stamp}] {msg}\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _collect_config(self):
        dmin, dmax = self.var_dmin.get(), self.var_dmax.get()
        if dmin > dmax:
            dmin, dmax = dmax, dmin
        self.cfg.update({
            "queries": self.txt_queries.get("1.0", "end").strip(),
            "exclude_words": " ".join(
                self.txt_exclude.get("1.0", "end").split()),
            "include_words": " ".join(
                self.txt_include.get("1.0", "end").split()),
            "exclude_companies": " ".join(
                self.txt_companies.get("1.0", "end").split()),
            "triage": self.var_triage.get(),
            "split_roles": self.var_split.get(),
            "habr_enabled": self.var_habr.get(),
            "superjob_enabled": self.var_superjob.get(),
            "telegram_enabled": self.var_telegram.get(),
            "telegram_channels": self.txt_telegram.get("1.0", "end").strip(),
            "exp_filter": self.var_exp_filter.get(),
            "area": self.var_area.get(),
            "experience": self.var_exp.get(),
            "remote_only": self.var_remote.get(),
            "remote_extra": self.var_remote_extra.get(),
            "only_with_salary": self.var_salary.get(),
            "recs_enabled": self.var_recs.get(),
            "hh_resume_only": self.var_resume_only.get(),
            "resume_hash": self.var_resume.get().strip(),
            "hh_cookie": self.txt_cookie.get("1.0", "end").strip(),
            "superjob_resume_url": self.var_sj_resume.get().strip(),
            "superjob_cookie": self.txt_sj_cookie.get("1.0", "end").strip(),
            "pages": self.var_pages.get(),
            "min_delay": max(1.0, dmin),
            "max_delay": max(1.0, dmax),
            "lm_url": self.var_lm_url.get().strip(),
            "lm_model": self.var_model.get().strip(),
            "lm_model_fast": self.var_model_fast.get().strip(),
        })
        save_config(self.cfg)
        return dict(self.cfg)

    # -- обработчики -------------------------------------------------------

    def on_check_lm(self):
        url = self.var_lm_url.get().strip()
        try:
            llm = LLMClient(url, self.var_model.get().strip(), self.log)
            models = llm.list_models()
            self.cmb_model["values"] = models
            self.cmb_model_fast["values"] = [""] + models
            chosen = llm.check()
            self.var_model.set(chosen)
            self.log(f"LM Studio доступен. Моделей: {len(models)}, "
                     f"выбрана: {chosen}")
            messagebox.showinfo(
                "LM Studio",
                f"Связь есть. Доступно моделей: {len(models)}.\n"
                f"Выбрана: {chosen}\n\n"
                "Другую можно выбрать в списке «Модель».")
        except Exception as e:  # noqa: BLE001
            self.log(f"LM Studio недоступен: {e}")
            messagebox.showerror(
                "LM Studio",
                "Не удалось подключиться.\n\nОткройте LM Studio, загрузите "
                "модель и включите сервер:\nвкладка «Developer» → "
                f"«Start Server».\n\nОшибка: {e}")

    def _update_roles_label(self):
        n = len(self.cfg.get("role_ids", []))
        self.lbl_roles.configure(
            text=f"выбрано: {n}" if n else "не выбраны (поиск только "
                                           "по доп. запросам)")

    def _load_roles_dict(self):
        """Справочник категорий HH: из кэша или с api.hh.ru (открытый
        справочный эндпоинт, авторизации не требует)."""
        cache_path = os.path.join(CACHE_DIR, "professional_roles.json")
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)["categories"]
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        r = requests.get("https://api.hh.ru/professional_roles",
                         headers=BROWSER_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return data["categories"]

    def on_pick_roles(self):
        try:
            groups = self._load_roles_dict()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(
                "Категории", f"Не удалось получить справочник категорий "
                             f"с hh.ru:\n{e}")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Категории вакансий HH")
        dlg.geometry("620x680")
        dlg.transient(self.root)
        dlg.grab_set()

        canvas = tk.Canvas(dlg, highlightthickness=0)
        vsb = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)

        btns = ttk.Frame(dlg)
        btns.pack(side="bottom", fill="x", padx=8, pady=6)
        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0))
        vsb.pack(side="right", fill="y")

        def on_wheel(event):
            canvas.yview_scroll(-event.delta // 120, "units")
        canvas.bind_all("<MouseWheel>", on_wheel)

        selected = set(self.cfg.get("role_ids", []))
        role_vars = {}
        for group in groups:
            ttk.Label(inner, text=group["name"],
                      font=("", 9, "bold")).pack(anchor="w",
                                                 padx=4, pady=(10, 2))
            for role in group["roles"]:
                rid = str(role["id"])
                # одна и та же категория бывает в нескольких группах —
                # используем общую переменную, галочки синхронизируются
                var = role_vars.setdefault(
                    rid, tk.BooleanVar(value=rid in selected))
                ttk.Checkbutton(inner, text=role["name"],
                                variable=var).pack(anchor="w", padx=20)

        def close():
            canvas.unbind_all("<MouseWheel>")
            dlg.destroy()

        def ok():
            self.cfg["role_ids"] = [rid for rid, v in role_vars.items()
                                    if v.get()]
            save_config(self.cfg)
            self._update_roles_label()
            close()

        ttk.Button(btns, text="Готово", command=ok).pack(side="right",
                                                         padx=4)
        ttk.Button(btns, text="Отмена", command=close).pack(side="right")
        dlg.protocol("WM_DELETE_WINDOW", close)

    def on_open_profile(self):
        os.startfile(PROFILE_PATH)

    def on_open_results(self):
        os.makedirs(RESULTS_DIR, exist_ok=True)
        os.startfile(RESULTS_DIR)

    def on_open_top(self):
        top_path = os.path.join(RESULTS_DIR, "top.md")
        if os.path.exists(top_path):
            os.startfile(top_path)
        else:
            messagebox.showinfo(
                "top.md", "Файл появится после первого прогона.")

    def on_open_vacancy(self, _event):
        sel = self.tree.selection()
        if sel and sel[0] in self.result_data:
            webbrowser.open(self.result_data[sel[0]]["url"])

    def on_open_all_vacancies(self):
        if self.browser_queue.active:
            self.browser_queue.pause()
            return
        if self.ui.running:
            return
        if self.browser_queue.paused:
            self.browser_queue.resume()
            return
        urls = suitable_urls(self.result_data.values())
        if urls:
            self.browser_queue.start(urls)

    def _browser_queue_update(self, message):
        self.lbl_status.configure(text=message)
        self.ui.update_bulk_button()

    def on_select_result(self, _event):
        sel = self.tree.selection()
        if not sel or sel[0] not in self.result_data:
            return
        data = self.result_data[sel[0]]
        if hasattr(self, "ui"):
            self.ui.show_detail(data)
        text = data["reason"] or "(без объяснения)"
        if data.get("resume"):
            text = f'Резюме: {data["resume"]} · {text}'
        self.txt_reason.configure(state="normal")
        self.txt_reason.delete("1.0", "end")
        self.txt_reason.insert("1.0", text)
        self.txt_reason.configure(state="disabled")

    def on_start(self):
        try:
            cfg = self._collect_config()
        except (RuntimeError, OSError, ValueError, tk.TclError) as exc:
            messagebox.showerror("Настройки", str(exc))
            return
        if cfg["pages"] < 1:
            messagebox.showwarning("Поиск", "Количество страниц должно быть больше нуля.")
            return
        resume_only = cfg.get("recs_enabled") and cfg.get("hh_resume_only")
        if resume_only and not (cfg.get("hh_cookie") and re.search(
                r"[0-9a-f]{30,45}", cfg.get("resume_hash", ""))):
            detail = cfg.get("_credential_errors", {}).get("hh_cookie", "")
            messagebox.showwarning("Поиск", "Для режима рекомендаций нужны cookies и ссылка на резюме.\n"
                                   + detail + "\nДля обычного поиска отключите рекомендации под резюме.")
            return
        if not (cfg["role_ids"] or cfg["queries"].strip() or cfg.get("recs_enabled")
                or (cfg.get("telegram_enabled") and cfg.get("telegram_channels", "").strip())
                or cfg.get("superjob_cookie")):
            messagebox.showwarning(
                "Поиск", "Выберите категории вакансий или введите "
                         "хотя бы один поисковый запрос.")
            return
        try:
            with open(PROFILE_PATH, encoding="utf-8") as f:
                profile = f.read().strip()
        except OSError:
            profile = ""
        if not profile or "(Опишите себя" in profile:
            messagebox.showwarning(
                "Профиль",
                "Сначала заполните profile.txt — без него нейросеть не "
                "знает, что вам подходит.\nКнопка «Мой профиль…».")
            return

        self.browser_queue.cancel(notify=False)
        self.stop_event.clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.start(12)
        self.lbl_status.configure(text="Работаю…")
        self.ui.set_running(True)
        self.worker = Worker(cfg, profile, self.queue, self.stop_event)
        self.worker.start()
        self.log("Запуск…")

    def on_stop(self):
        self.stop_event.set()
        self.log("Останавливаю после текущей вакансии…")

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "result":
                    self.ui.add_result(payload)
                elif kind == "stats":
                    skipped, checked, suitable = payload
                    self.ui.set_stats(skipped, checked, suitable)
                    self.lbl_status.configure(
                        text=f"Отсеяно быстрыми фильтрами: {skipped}   ·   "
                             f"Проверено нейросетью: {checked}   ·   "
                             f"Подходит: {suitable}")
                elif kind == "done":
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    self.progress.stop()
                    self.ui.set_running(False)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    try:
        App(root)
    except (RuntimeError, OSError, ValueError) as exc:
        messagebox.showerror("Запуск", str(exc))
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
