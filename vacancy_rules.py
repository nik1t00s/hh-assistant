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
    grade_reason = explicit_seniority(title, description)
    if grade_reason:
        return grade_reason
    experience_reason = required_experience(description)
    if experience_reason:
        return experience_reason
    if re.search(r"руководитель\s+(отдела|направления|группы|департамента|"
                 r"службы)", t):
        return "руководящая позиция — не стартовый уровень"
    d = (description or "").lower()

    # Experience and QA suitability depend on the current profile and task level.
    # A shift pattern alone says nothing about nights. Leave ambiguous language
    # to the model; only an affirmative mention can trigger this guard.
    for clause in re.split(r"[.!?;\n]|\bно\b|\bоднако\b", d):
        if not re.search(r"\bвахт(?:а|ой|ы|е|у|ов\w*)\b", clause):
            continue
        if re.search(r"\bбез\b|\bне\b|\bнет\b|исключен|исключён|отсутств", clause):
            continue
        return "вахтовый метод работы"
    return None


def required_experience(description):
    """Conservative guard for explicit prior commercial/same-role experience."""
    text = (description or '').lower()
    if re.search(r'(?:рассмотрим|рассматриваем|готовы\s+рассмотреть|можно)\s+[^.!\n]{0,50}без\s+опыта', text):
        return None
    for clause in re.split(r'[.!?;\n]', text):
        if re.search(r'желател|будет\s+плюсом|преимуществ|не\s+обязател|не\s+требу|без\s+опыта', clause):
            continue
        scope = re.search(r'коммерческ\w*\s+опыт|опыт\s+коммерческ|'
                          r'опыт\s+(?:работы\s+)?в\s+аналогичн\w*\s+должност|'
                          r'опыт\s+работы\s+(?:координатором|администратором\s+проектов|'
                          r'менеджером\s+проектов|руководителем\s+проектов)', clause)
        duration = re.search(r'(?:от\s+|не\s+менее\s+)?(?:\d+(?:\s*[-–]\s*\d+)?\s*(?:лет|год\w*|месяц\w*)|одного\s+года|года)', clause)
        if scope and (duration or re.search(r'обязател|требуется|необходим', clause)):
            return 'явно требуется коммерческий опыт или опыт в аналогичной должности'
    return None


def explicit_seniority(title, description):
    """Only explicit role grades; unrelated mentions of senior colleagues are allowed."""
    grade = r'\b(?:middle|senior|мидд?л|сеньор|синьор)\b'
    junior = r'\b(?:junior|джуниор|джун|стаж[её]р\w*)\b'
    title = (title or '').lower()
    if re.search(grade, title) and not re.search(junior, title):
        return 'явный Middle/Senior-уровень — не стартовая позиция'
    patterns = [
        rf'(?:уровень|уровня|грейд|grade)\s*[:—–-]?\s*(?:от\s+)?{grade}',
        rf'{grade}\s*[-—–]?\s*(?:уровень|уровня|грейд)',
        rf'\b(?:ищем|требуется|нужен)\s+(?:специалист\w*\s+)?{grade}',
    ]
    for clause in re.split(r'[.!?;\n]', (description or '').lower()):
        if re.search(junior, clause):
            continue
        # Growth goals, colleagues and negated requirements are not the vacancy grade.
        if re.search(r'рост|расти|выраст|дораст|наставник|коллег|ментор|взаимодейств|'
                     r'не\s+(?:требуется|нужен|ниже)|необязател|не\s+обязател', clause):
            continue
        # A team's grade is not a requirement for the applicant. Keep explicit hiring clauses.
        if re.search(r'команд|отдел|разработчик|сотрудник', clause) and not re.search(
                r'ищем|требуется|нужен|кандидат|ваш\s+(?:уровень|грейд)|вас.*(?:уровень|грейд)', clause):
            continue
        if any(re.search(pattern, clause) for pattern in patterns):
            return 'в описании явно указан Middle/Senior-уровень'
    return None


def salary_cap(salary):
    """Reject only an unambiguous monthly net RUB upper bound below 40k."""
    text = (salary or '').lower().replace('\xa0', ' ').replace('\u202f', ' ')
    if 'на руки' not in text or not re.search(r'руб|₽|\brur\b|\brub\b', text):
        return None
    if not re.search(r'месяц|/мес\b', text):
        return None
    if re.search(r'час|смен|недел|сутк|день|дня|год|до вычета|налог', text):
        return None
    amounts = re.findall(r'\d+(?:[ ]\d{3})*(?:[,.]\d+)?', text)
    if not amounts:
        return None
    values = [float(value.replace(' ', '').replace(',', '.')) for value in amounts]
    if 'тыс' in text:
        values = [value * 1000 for value in values]
    # A lower bound alone does not limit the possible offer.
    if re.search(r'\bот\b', text) and not re.search(r'\bдо\b', text):
        return None
    if max(values) < 40000:
        return 'зарплата ниже 40 000 ₽ на руки'
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
