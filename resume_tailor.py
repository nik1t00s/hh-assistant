# -*- coding: utf-8 -*-
"""Резюме под вакансию — генерирует PDF-резюме, адаптированное под текст
конкретной вакансии, на основе фактов из resume_data.json и profile.txt.

Использует то же LM Studio, что и main.py (адрес/модель из config.json).
"""
import json
import os
import queue
import re
import threading
import tkinter as tk
from datetime import datetime
from html import escape

from llm_client import StreamingLLMClient
from settings import load_settings
from storage import write_json
from tkinter import messagebox, scrolledtext, ttk

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, Image, Paragraph,
                                 SimpleDocTemplate, Spacer, Table, TableStyle)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
PROFILE_PATH = os.path.join(APP_DIR, "profile.txt")
RESUME_DATA_PATH = os.path.join(APP_DIR, "resume_data.json")
RESULTS_DIR = os.path.join(APP_DIR, "results", "resumes")
PHOTO_PATH = next((p for p in (
    os.path.join(APP_DIR, "photo.jpg"), os.path.join(APP_DIR, "photo.jpeg"),
    os.path.join(APP_DIR, "photo.png")) if os.path.exists(p)), None)

ACCENT = colors.HexColor("#2f5d8a")
DARK = colors.HexColor("#1f2d3d")
GRAY = colors.HexColor("#666666")
SIDEBAR_BG = colors.HexColor("#f2f5f8")

STALL_TIMEOUT = 600  # сек без данных от модели — таймаут (не на весь ответ)

SYSTEM_PROMPT = """Ты помогаешь адаптировать резюме кандидата под конкретную вакансию.

ЖЁСТКОЕ ПРАВИЛО: используй ТОЛЬКО факты из блоков «ДАННЫЕ РЕЗЮМЕ» и «ПРОФИЛЬ
КАНДИДАТА» ниже. Никогда не выдумывай навыки, инструменты, обязанности,
достижения, места работы или образование, которых там нет. Разрешено:
переформулировать, менять порядок, расставлять акценты, выбирать подмножество
из уже перечисленного. Запрещено: добавлять новое.

Кандидат — выпускник без опыта работы по специальности (junior/entry-level).
Не завышай уровень должности и не приписывай экспертизу выше начального уровня.

ДАННЫЕ РЕЗЮМЕ (JSON):
{resume_data}

ПРОФИЛЬ КАНДИДАТА (кто он, что ищет, психотип, приоритеты):
{profile}

Верни ТОЛЬКО JSON без пояснений и без markdown-обёртки, строго такой структуры:
{{
  "target_title": "...",
  "summary": "...",
  "skills": {{
    "<название группы точно как в ДАННЫЕ РЕЗЮМЕ>": ["...", "..."]
  }},
  "experience": {{
    "<Должность> — <Компания>": ["...", "..."]
  }},
  "education_courses": {{
    "<школа точно как в ДАННЫЕ РЕЗЮМЕ>": ["...", "..."]
  }},
  "projects": "...",
  "additional": "..."
}}

Пояснения к полям:
- target_title: желаемая должность, близкая к названию вакансии, но правдиво
  отражающая уровень и опыт кандидата.
- summary: 3-5 предложений от первого лица — адаптированный раздел «Обо мне».
- skills: для каждой группы из ДАННЫЕ РЕЗЮМЕ — подмножество и порядок ИЗ
  ИСХОДНОГО СПИСКА этой группы (не больше 8 пунктов), самые релевантные
  вакансии — первыми. Ключи групп должны совпадать с исходными.
- experience: для каждого места работы — переформулированные пункты
  обязанностей с акцентом на релевантные вакансии аспекты (не больше пунктов,
  чем в исходных данных, без новых фактов). Ключ — "Должность — Компания".
- education_courses: для каждого места учёбы — подмножество и порядок ИЗ
  ИСХОДНОГО СПИСКА relevant_courses этой школы, самые релевантные вакансии —
  первыми. Ключ — точное название школы.
- projects: переформулированное описание раздела «Проекты» с акцентом на
  релевантные вакансии аспекты — те же факты (ссылка на GitHub, реальные
  проекты), без новых проектов.
- additional: адаптированный раздел «Дополнительно» (1-3 предложения)."""


# ----------------------------------------------------------------------
# Загрузка данных
# ----------------------------------------------------------------------

def load_config():
    return load_settings(CONFIG_PATH, {"lm_url": "http://localhost:1234/v1", "lm_model": ""},
                         with_secrets=False)


def load_profile():
    if not os.path.exists(PROFILE_PATH):
        return ""
    with open(PROFILE_PATH, encoding="utf-8") as f:
        return f.read().strip()


def load_resume_data():
    with open(RESUME_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------
# LM Studio
# ----------------------------------------------------------------------

class LLMClient(StreamingLLMClient):
    def resolve_model(self):
        return self.check()

    def tailor(self, resume_data, profile, vacancy_text):
        system = SYSTEM_PROMPT.format(
            resume_data=json.dumps(resume_data, ensure_ascii=False, indent=2),
            profile=profile or "(профиль не заполнен)")
        last_err = None
        for attempt in range(1, 4):
            t = 0.2 if attempt == 1 else 0.2 + 0.25 * attempt
            content = self._chat(system, vacancy_text, t, max_tokens=3000,
                                 seed=None if attempt == 1 else attempt * 777)
            data = self._parse(content)
            if data is not None:
                return data
            last_err = content[:120] if content else "пустой ответ"
            self.log(f"Не удалось разобрать ответ модели "
                     f"({last_err!r}) — попытка {attempt}/3…")
        raise RuntimeError(f"Модель не вернула корректный JSON после 3 "
                          f"попыток. Последний фрагмент: {last_err!r}")

    @staticmethod
    def _parse(content):
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
        required = {"target_title", "summary", "skills", "experience",
                   "additional"}
        if not isinstance(data, dict) or not required.issubset(data):
            return None
        if not all(isinstance(data[key], str) for key in
                   ("target_title", "summary", "additional")):
            return None
        if not all(isinstance(data.get(key, {}), dict) for key in
                   ("skills", "experience", "education_courses")):
            return None
        if not isinstance(data.get("projects", ""), str):
            return None
        return data


# ----------------------------------------------------------------------
# Слияние адаптированных полей с исходными фактами (без выдумок)
# ----------------------------------------------------------------------

def merge_tailored(resume_data, tailored):
    merged = json.loads(json.dumps(resume_data))  # deep copy
    merged["target_title"] = str(tailored.get("target_title") or
                                 resume_data["target_titles"][0]).strip()
    merged["summary"] = str(tailored.get("summary") or
                            resume_data["summary"]).strip()
    merged["additional"] = str(tailored.get("additional") or
                               resume_data["additional"]).strip()
    merged["projects"] = str(tailored.get("projects") or
                             resume_data.get("projects", "")).strip()

    tailored_skills = tailored.get("skills") or {}
    lower_map = {k.lower().strip(): k for k in tailored_skills}
    for group, original_items in resume_data["skill_groups"].items():
        key = lower_map.get(group.lower().strip())
        items = tailored_skills.get(key) if key else None
        if isinstance(items, list) and items:
            allowed = {value.casefold().strip(): value for value in original_items}
            selected = list(dict.fromkeys(allowed[str(i).casefold().strip()]
                                         for i in items if str(i).casefold().strip() in allowed))
            merged["skill_groups"][group] = (selected or original_items)[:8]
        else:
            merged["skill_groups"][group] = original_items[:8]

    tailored_exp = tailored.get("experience") or {}
    exp_lower_map = {k.lower().strip(): k for k in tailored_exp}
    for i, entry in enumerate(resume_data["experience"]):
        exp_key = f'{entry["title"]} — {entry["company"]}'
        key = exp_lower_map.get(exp_key.lower().strip())
        bullets = tailored_exp.get(key) if key else None
        if not bullets:
            # мягкое совпадение по компании, если модель изменила формулировку ключа
            for k in tailored_exp:
                if entry["company"].lower() in k.lower():
                    bullets = tailored_exp[k]
                    break
        if isinstance(bullets, list) and bullets:
            cap = len(entry["bullets"])
            merged["experience"][i]["bullets"] = [str(b).strip() for b in bullets][:cap]

    tailored_courses = tailored.get("education_courses") or {}
    course_lower_map = {k.lower().strip(): k for k in tailored_courses}
    for i, edu in enumerate(resume_data["education"]):
        original_courses = edu.get("relevant_courses") or []
        key = course_lower_map.get(edu["school"].lower().strip())
        courses = tailored_courses.get(key) if key else None
        if isinstance(courses, list) and courses:
            allowed = {value.casefold().strip(): value for value in original_courses}
            selected = list(dict.fromkeys(allowed[str(c).casefold().strip()]
                                         for c in courses if str(c).casefold().strip() in allowed))
            merged["education"][i]["relevant_courses"] = selected or original_courses
        else:
            merged["education"][i]["relevant_courses"] = original_courses

    return merged


# ----------------------------------------------------------------------
# Рендер PDF
# ----------------------------------------------------------------------

_FONTS_READY = False


def _ensure_fonts():
    global _FONTS_READY
    if _FONTS_READY:
        return
    windir = os.environ.get("WINDIR", "C:\\Windows")
    fonts_dir = os.path.join(windir, "Fonts")
    candidates = [
        ("Body", "arial.ttf", "Body-Bold", "arialbd.ttf",
         "Body-Italic", "ariali.ttf"),
        ("Body", "calibri.ttf", "Body-Bold", "calibrib.ttf",
         "Body-Italic", "calibrii.ttf"),
    ]
    for reg_name, reg_file, bold_name, bold_file, ital_name, ital_file in candidates:
        reg_path = os.path.join(fonts_dir, reg_file)
        bold_path = os.path.join(fonts_dir, bold_file)
        ital_path = os.path.join(fonts_dir, ital_file)
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont(reg_name, reg_path))
            pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            if os.path.exists(ital_path):
                pdfmetrics.registerFont(TTFont(ital_name, ital_path))
            else:
                pdfmetrics.registerFont(TTFont(ital_name, reg_path))
            _FONTS_READY = True
            return
    raise RuntimeError(
        "Не найдены шрифты Arial или Calibri в C:\\Windows\\Fonts — "
        "нужны для кириллицы в PDF.")


def build_pdf(data, out_path):
    def escaped(value):
        if isinstance(value, str):
            return escape(value)
        if isinstance(value, list):
            return [escaped(item) for item in value]
        if isinstance(value, dict):
            return {key: escaped(item) for key, item in value.items()}
        return value
    data = escaped(data)
    _ensure_fonts()

    name_style = ParagraphStyle("name", fontName="Body-Bold", fontSize=17,
                                textColor=DARK, spaceAfter=8)
    subtitle_style = ParagraphStyle("subtitle", fontName="Body-Italic",
                                    fontSize=9.5, textColor=GRAY,
                                    spaceAfter=0)
    heading_style = ParagraphStyle("heading", fontName="Body-Bold",
                                   fontSize=9.8, textColor=ACCENT,
                                   spaceBefore=7, spaceAfter=4,
                                   letterSpacing=0.5)
    side_heading_style = ParagraphStyle("side_heading", fontName="Body-Bold",
                                        fontSize=8.8, textColor=ACCENT,
                                        spaceBefore=7, spaceAfter=2)
    body_style = ParagraphStyle("body", fontName="Body", fontSize=9.2,
                                leading=13.2, textColor=DARK, spaceAfter=5)
    bullet_style = ParagraphStyle("bullet", fontName="Body", fontSize=9,
                                  leading=12.6, textColor=DARK,
                                  leftIndent=8, spaceAfter=3)
    job_title_style = ParagraphStyle("job_title", fontName="Body-Bold",
                                     fontSize=9.4, textColor=DARK,
                                     spaceBefore=4, spaceAfter=1.5)
    job_meta_style = ParagraphStyle("job_meta", fontName="Body-Italic",
                                    fontSize=8.3, textColor=GRAY,
                                    spaceAfter=4)
    side_item_style = ParagraphStyle("side_item", fontName="Body",
                                     fontSize=8.3, leading=11,
                                     textColor=DARK, leftIndent=6,
                                     spaceAfter=1.5)
    side_small_style = ParagraphStyle("side_small", fontName="Body",
                                      fontSize=8.1, leading=10.8,
                                      textColor=DARK, spaceAfter=2)

    contacts = data["contacts"]

    # Контент разбит на ДВЕ строки таблицы (а не одну), чтобы при переполнении
    # (ИИ почти не сократил факты) Table мог перенести нижнюю строку на
    # вторую страницу вместо падения/пустой первой страницы — обычная
    # 1-строчная Table через reportlab не умеет разбиваться сама по себе.

    # ---- строка A: обо мне + опыт  /  должность+контакты+навыки ----
    main_a = [
        Paragraph("ОБО МНЕ", heading_style),
        Paragraph(data["summary"], body_style),
        Paragraph("ОПЫТ РАБОТЫ", heading_style),
    ]
    for entry in data["experience"]:
        main_a.append(Paragraph(f'{entry["title"]} — {entry["company"]}',
                                job_title_style))
        main_a.append(Paragraph(entry["period"], job_meta_style))
        for b in entry["bullets"]:
            main_a.append(Paragraph(f"• {b}", bullet_style))

    side_a = [
        Paragraph("ЖЕЛАЕМАЯ ДОЛЖНОСТЬ", side_heading_style),
        Paragraph(data["target_title"], ParagraphStyle(
            "target", fontName="Body-Bold", fontSize=10.5, textColor=DARK,
            spaceAfter=2)),
        Paragraph("КОНТАКТЫ", side_heading_style),
        Paragraph(contacts.get("email", ""), side_small_style),
        Paragraph(contacts.get("phone", ""), side_small_style),
        Paragraph(contacts.get("telegram", ""), side_small_style),
        Paragraph(contacts.get("location", ""), side_small_style),
    ]
    for group, items in data["skill_groups"].items():
        side_a.append(Paragraph(group.upper(), side_heading_style))
        for it in items:
            side_a.append(Paragraph(f"• {it}", side_item_style))

    # ---- строка B: образование+проекты  /  языки+дополнительно ----
    main_b = [Paragraph("ОБРАЗОВАНИЕ", heading_style)]
    for edu in data["education"]:
        main_b.append(Paragraph(f'{edu["school"]}', job_title_style))
        main_b.append(Paragraph(edu["period"], job_meta_style))
        main_b.append(Paragraph(edu["program"], body_style))
        courses = edu.get("relevant_courses")
        if courses:
            main_b.append(Paragraph(
                "Релевантные направления обучения: " + ", ".join(courses),
                body_style))
    if data.get("projects"):
        main_b.append(Paragraph("ПРОЕКТЫ", heading_style))
        main_b.append(Paragraph(data["projects"], body_style))

    side_b = [Paragraph("ЯЗЫКИ", side_heading_style)]
    for lang in data["languages"]:
        side_b.append(Paragraph(f"• {lang}", side_item_style))

    # "Дополнительно" рендерится на всю ширину ПОСЛЕ двух колонок, а не в
    # узком сайдбаре: раньше при коротком главном столбце (частый случай,
    # если ИИ основательно сократил "Обо мне"/опыт) слева оставалась большая
    # пустая область, пока сайдбар продолжался — из-за длинного текста в
    # узкой колонке. Полноширинный блок читается цельно и не зависит от
    # того, насколько по высоте совпали столбцы.
    footer_flowables = []
    if data.get("additional"):
        footer_flowables = [
            Paragraph("ДОПОЛНИТЕЛЬНО", heading_style),
            Paragraph(data["additional"], body_style),
        ]

    main_w, side_w = 335, 175

    # Обычный случай (адаптированный ИИ текст почти всегда короче исходных
    # данных): цельная 1-строчная таблица — колонки текут непрерывно, без
    # искусственного разрыва между секциями. Это даёт самую чистую вёрстку
    # и работает вместе с автоподбором высоты страницы ниже.
    seamless_table = Table([[main_a + main_b, side_a + side_b]],
                           colWidths=[main_w, side_w])
    seamless_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 14),
        ("LEFTPADDING", (1, 0), (1, 0), 12),
        ("RIGHTPADDING", (1, 0), (1, 0), 10),
        ("TOPPADDING", (1, 0), (1, 0), 8),
        ("BOTTOMPADDING", (1, 0), (1, 0), 8),
        ("BACKGROUND", (1, 0), (1, 0), SIDEBAR_BG),
        ("TOPPADDING", (0, 0), (0, 0), 0),
    ]))

    # Аварийный запасной вариант (если ИИ почти не сократил факты и общий
    # объём не влезает даже в одну полную страницу A4): 2-строчная таблица,
    # которая может разбиться между строками на 2 страницы вместо падения
    # или пустой первой страницы. Ценой лёгкого разрыва между секциями.
    split_table = Table([[main_a, side_a], [main_b, side_b]],
                        colWidths=[main_w, side_w])
    split_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 14),
        ("LEFTPADDING", (1, 0), (1, -1), 12),
        ("RIGHTPADDING", (1, 0), (1, -1), 10),
        ("TOPPADDING", (1, 0), (1, -1), 8),
        ("BOTTOMPADDING", (1, 0), (1, -1), 8),
        ("BACKGROUND", (1, 0), (1, -1), SIDEBAR_BG),
        ("TOPPADDING", (0, 0), (0, 0), 0),
        ("BOTTOMPADDING", (0, 0), (0, 0), 0),
        ("TOPPADDING", (0, 1), (0, 1), 0),
    ]))

    left_margin, right_margin = 34, 34
    top_margin, bottom_margin = 22, 20
    content_w = main_w + side_w

    name_block = [Paragraph(data["name"], name_style),
                 Paragraph(data["subtitle"], subtitle_style)]
    if PHOTO_PATH:
        photo_size = 50
        photo = Image(PHOTO_PATH, width=photo_size, height=photo_size)
        header = Table([[name_block, photo]],
                       colWidths=[content_w - photo_size - 10, photo_size + 10])
        header.setStyle(TableStyle([
            ("VALIGN", (0, 0), (0, 0), "MIDDLE"),
            ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        header = name_block[0]
        header2 = name_block[1]

    header_flowables = ([header] if PHOTO_PATH else [header, header2]) + [
        Spacer(1, 3),
        HRFlowable(width="100%", thickness=1, color=ACCENT),
        Spacer(1, 2),
    ]

    # Автоподбор высоты страницы под фактический контент: при коротком
    # адаптированном резюме фиксированная высота A4 оставляла пустой хвост
    # внизу страницы, из-за чего вёрстка выглядела "оборванной".
    header_h = sum(f.wrap(content_w, 100000)[1] for f in header_flowables)
    # SimpleDocTemplate.build() hardcodes its Frame with reportlab's default
    # 6pt padding on every side (leftPadding=6 etc.), ignoring any
    # leftPadding/topPadding kwargs passed to the constructor — so the
    # actual usable height is 12pt less than margins alone would suggest.
    frame_padding = 12
    max_content_h = A4[1] - top_margin - bottom_margin - frame_padding

    footer_h = sum(f.wrap(content_w, 100000)[1] for f in footer_flowables)

    _, seamless_h = seamless_table.wrap(content_w, 100000)
    if header_h + seamless_h + footer_h + 14 <= max_content_h:
        needed_h = (top_margin + bottom_margin + frame_padding + header_h +
                   seamless_h + footer_h + 14)
        page_h = min(max(needed_h, 300), A4[1])
        doc = SimpleDocTemplate(
            out_path, pagesize=(A4[0], page_h),
            leftMargin=left_margin, rightMargin=right_margin,
            topMargin=top_margin, bottomMargin=bottom_margin)
        story = header_flowables + [seamless_table] + footer_flowables
    else:
        doc = SimpleDocTemplate(
            out_path, pagesize=A4,
            leftMargin=left_margin, rightMargin=right_margin,
            topMargin=top_margin, bottomMargin=bottom_margin)
        story = header_flowables + [split_table] + footer_flowables
    doc.build(story)


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------

def sanitize_filename(text):
    text = re.sub(r"[^\w\-. а-яА-ЯёЁ]", "_", text, flags=re.UNICODE)
    return re.sub(r"_+", "_", text).strip("_")[:60]


class App:
    def __init__(self, root):
        self.root = root
        root.title("Резюме под вакансию — HH Assistant")
        root.geometry("760x680")
        root.minsize(620, 520)

        self.queue = queue.Queue()
        self.busy = False

        pad = {"padx": 8, "pady": 6}

        ttk.Label(root, text="Текст вакансии (описание, требования, "
                             "обязанности) — вставьте сюда:").pack(
            anchor="w", **pad)
        self.txt_vacancy = scrolledtext.ScrolledText(root, height=16, wrap="word")
        self.txt_vacancy.pack(fill="both", expand=True, padx=8)

        row = ttk.Frame(root)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Компания/вакансия (для имени файла, "
                            "необязательно):").pack(side="left")
        self.var_label = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_label, width=30).pack(
            side="left", padx=8)

        btn_row = ttk.Frame(root)
        btn_row.pack(fill="x", **pad)
        self.btn_generate = ttk.Button(btn_row, text="Сгенерировать резюме",
                                       command=self.on_generate)
        self.btn_generate.pack(side="left")
        ttk.Button(btn_row, text="Открыть резюме-факты (resume_data.json)",
                  command=lambda: os.startfile(RESUME_DATA_PATH)).pack(
            side="left", padx=8)
        ttk.Button(btn_row, text="Открыть профиль (profile.txt)",
                  command=self.open_profile).pack(side="left")

        cfg = load_config()
        self.lbl_lm = ttk.Label(
            root, foreground="#666",
            text=f"LM Studio: {cfg['lm_url']} · модель: "
                 f"{cfg['lm_model'] or '(авто)'} — настраивается в "
                 f"главном приложении HH Assistant (main.py)")
        self.lbl_lm.pack(anchor="w", padx=8)

        ttk.Label(root, text="Журнал:").pack(anchor="w", padx=8, pady=(8, 0))
        self.log_box = scrolledtext.ScrolledText(root, height=8, wrap="word",
                                                 state="disabled")
        self.log_box.pack(fill="both", expand=False, padx=8, pady=(0, 8))

        self.root.after(150, self._poll_queue)

    def open_profile(self):
        if not os.path.exists(PROFILE_PATH):
            with open(PROFILE_PATH, "w", encoding="utf-8") as f:
                f.write("")
        os.startfile(PROFILE_PATH)

    def log(self, msg):
        self.queue.put(("log", msg))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", payload + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "done":
                    self.busy = False
                    self.btn_generate.configure(state="normal")
                    out_path = payload
                    if out_path:
                        os.startfile(out_path)
                elif kind == "error":
                    self.busy = False
                    self.btn_generate.configure(state="normal")
                    messagebox.showerror("Ошибка", payload)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_queue)

    def on_generate(self):
        if self.busy:
            return
        vacancy = self.txt_vacancy.get("1.0", "end").strip()
        if not vacancy:
            messagebox.showwarning("Пустая вакансия",
                                   "Вставьте текст вакансии.")
            return
        if not os.path.exists(RESUME_DATA_PATH):
            messagebox.showerror(
                "Нет данных резюме",
                f"Не найден {RESUME_DATA_PATH}. Он должен содержать факты "
                "вашего резюме (создаётся один раз).")
            return
        self.busy = True
        self.btn_generate.configure(state="disabled")
        label = self.var_label.get().strip()
        threading.Thread(target=self._worker, args=(vacancy, label),
                         daemon=True).start()

    def _worker(self, vacancy, label):
        try:
            cfg = load_config()
            profile = load_profile()
            resume_data = load_resume_data()

            self.log("Проверяю связь с LM Studio…")
            client = LLMClient(cfg["lm_url"], cfg["lm_model"], self.log)
            client.model = client.resolve_model()
            self.log(f"Модель: {client.model}. Адаптирую резюме под вакансию…")

            tailored = client.tailor(resume_data, profile, vacancy)
            merged = merge_tailored(resume_data, tailored)

            self.log(f"Желаемая должность: {merged['target_title']}")

            os.makedirs(RESULTS_DIR, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            base = sanitize_filename(label or merged["target_title"]) or "резюме"
            out_path = os.path.join(RESULTS_DIR, f"{base}_{stamp}.pdf")

            review_path = os.path.splitext(out_path)[0] + "_review.json"
            write_json(review_path, {"notice": "Черновик. Сверьте переформулированные факты перед откликом.",
                                     "original": resume_data, "draft": merged})
            self.log(f"Исходные факты и черновик для сверки: {review_path}")
            self.log("Собираю PDF-черновик…")
            build_pdf(merged, out_path)
            self.log(f"Готово: {out_path}")
            self.log("Проверьте текст перед откликом — ИИ мог "
                     "перефразировать неточно.")
            self.queue.put(("done", out_path))
        except Exception as e:  # noqa: BLE001
            self.log(f"Ошибка: {e}")
            self.queue.put(("error", str(e)))


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
