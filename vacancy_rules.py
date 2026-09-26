"""Pure vacancy parsing and conservative deterministic filters."""
import html
import json
import re
from html.parser import HTMLParser


def strip_html(text):
    text = re.sub(r"</?(?:p|div|li|br|h[1-6])\b[^>]*>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def extract_jobposting_description(page_html):
    """Read objects, arrays and @graph, with either HTML attribute quoting style."""
    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self.blocks = []
            self.parts = None

        def handle_starttag(self, tag, attrs):
            if tag == "script" and dict(attrs).get("type", "").lower() == "application/ld+json":
                self.parts = []

        def handle_data(self, value):
            if self.parts is not None:
                self.parts.append(value)

        def handle_endtag(self, tag):
            if tag == "script" and self.parts is not None:
                self.blocks.append("".join(self.parts))
                self.parts = None

    def postings(value):
        if isinstance(value, list):
            for child in value:
                yield from postings(child)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if isinstance(types, list) and "JobPosting" in types:
                yield value
            yield from postings(value.get("@graph"))

    parser = Scripts()
    parser.feed(page_html)
    for block in parser.blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for posting in postings(data):
            description = posting.get("description")
            if isinstance(description, str) and description.strip():
                return strip_html(description)
    return ""


def short_profile(profile):
    """Краткая версия профиля для быстрого отсева по заголовкам: раздел
    «Резюме одним абзацем» / «Коротко, одним абзацем» (обе формулировки
    встречались в разных версиях profile.txt), если он есть, иначе
    начало текста."""
    m = re.search(
        r"(?:резюме|коротко)[^\n]{0,15}?одним абзацем[^\n]*\n+(.+?)(?=\n#|\Z)",
        profile, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return profile[:1500]


def score_cap(title, description):
    """Программный предохранитель от типичных ошибок слабых моделей:
    возвращает причину, по которой вердикт надо принудительно сделать
    REJECT, или None.

    Модели уровня 7B игнорируют такие правила в промпте, поэтому
    они продублированы кодом."""
    t = title.lower()
    if re.search(r"тестиров|автотест|\baqa\b|\bqa\b", t):
        return "автоматизация тестирования — не целевая роль"
    if re.search(r"руководитель\s+(отдела|направления|группы|департамента|"
                 r"службы)", t):
        return "руководящая позиция — не стартовый уровень"
    d = (description or "").lower()

    def optional_mention(match):
        """11.09.2026: до этой проверки регексы на «опыт от N лет» ловили
        и формулировки вида «будет плюсом опыт работы от 3 лет» — а это
        НЕ требование, значит не должно резать хорошую вакансию в REJECT.
        Пользователь явно попросил минимизировать риск потерять
        подходящую вакансию — смотрим окно вокруг совпадения на слова,
        превращающие требование в необязательный бонус."""
        window = d[max(0, match.start() - 60):match.end() + 40]
        return bool(re.search(
            r"приветствуется|будет\s+плюсом|как\s+плюс|плюсом\s+будет|"
            r"желательно|преимуществ|не\s+обязательно|опционально",
            window))

    m = re.search(
        r"опыт[^.!\n]{0,50}?от\s*([3-9])(?:-х)?\s*(?:лет|года)"
        r"|([3-9])\+\s*лет\s*опыта", d)
    if m and not optional_mention(m):
        years = int(m.group(1) or m.group(2))
        return f"в описании требуют опыт от {years} лет"
    # 31.08.2026: отдельно от общего "опыт от N лет" — требование ГОТОВОГО
    # опыта именно в этой должности («опыт работы сервис-менеджером от
    # года», «опыт работы руководителем проектов от года») дисквалифицирует
    # кандидата без коммерческого опыта даже при 1 годе, а не только при
    # 3+. Искл. "опыт работы с/в/на ..." — это про инструмент/сферу,
    # а не про предыдущую должность.
    m = re.search(
        r"опыт\s+работы\s+(?!с\s|со\s|в\s|на\s)\S*(?:ом|ем|ём)\b"
        r"[^.!\n]{0,30}?от\s+(?:\d+\s*)?(?:года|лет)", d,
    )
    if m and not optional_mention(m):
        return "требуется предыдущий опыт именно в этой должности (от года)"
    # То же самое, но когда требуемое поле названо не должностью, а
    # сферой через предлог: «опыт работы в ИБ/системной интеграции/
    # внедрении... от 1 года» — это именно тот «боевой опыт в ИБ»,
    # который profile.txt просит резать вниз, а не опыт с инструментом
    # («опыт работы с базами данных» и т.п., что не ловим специально).
    m = re.search(
        r"опыт\s+работы\s+(?:в\s+|со?\s+)?"
        r"(?:иб\b|информационн\w*\s+безопасност\w*|"
        r"системн\w*\s+интеграц\w*|внедрени\w*\s+(?:ит|иб))"
        r"[^.!\n]{0,60}?от\s+(?:\d+\s*)?(?:года|лет)", d,
    )
    if m and not optional_mention(m):
        return "требуется предыдущий опыт именно в ИБ/внедрении (от года)"
    # A shift pattern alone says nothing about nights. Leave ambiguous language
    # to the model; only an affirmative mention can trigger this guard.
    for clause in re.split(r"[.!?;\n]|\bно\b|\bоднако\b", d):
        if not re.search(r"\bвахт(?:а|ой|ы|е|у|ов\w*)\b", clause):
            continue
        if re.search(r"\bбез\b|\bне\b|\bнет\b|исключен|исключён|отсутств", clause):
            continue
        return "вахтовый метод работы"
    return None


def word_hit(words, title):
    """Первое слово/фраза из списка, найденное в заголовке.

    Каждое слово фразы совпадает по началу (окончания свободные):
    «менеджер проект» найдёт и «менеджера проектов». Слева — граница
    слова, иначе «водитель» находится внутри «руководителя»."""
    for w in words:
        pattern = r"(?<![a-zа-яё0-9])" + r"[а-яёa-z]*\s+".join(
            re.escape(part) for part in w.split())
        if re.search(pattern, title):
            return w
    return None
