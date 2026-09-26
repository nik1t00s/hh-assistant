"""Desktop presentation, separate from search and evaluation logic."""
import tkinter as tk
from tkinter import ttk, messagebox
from browser_queue import suitable_urls

BG = "#f3f5f1"
PAPER = "#ffffff"
INK = "#203b36"
MUTED = "#697b73"
LINE = "#e0e7df"
ACCENT = "#287568"
NAV = "#183b34"
VERDICTS = {"STRONG_MATCH": "Отлично подходит", "MATCH": "Подходит",
            "WEAK": "Есть вопросы", "REJECT": "Не подходит"}


def label(parent, text="", size=10, color=INK, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color,
                    font=("Segoe UI", size, "bold" if bold else "normal"),
                    anchor="w", justify="left", **kwargs)


def card(parent, title=None, hint=None):
    border = tk.Frame(parent, bg=PAPER, highlightbackground=LINE, highlightthickness=1)
    border.pack(fill="x", pady=(0, 16))
    body = tk.Frame(border, bg=PAPER, padx=20, pady=18)
    body.pack(fill="both", expand=True)
    if title:
        label(body, title, 12, bold=True).pack(anchor="w")
    if hint:
        label(body, hint, 9, MUTED, wraplength=740).pack(anchor="w", pady=(4, 12))
    return body


def text_input(parent, value="", height=3):
    widget = tk.Text(parent, height=height, width=20, wrap="word", bg="#f8faf7",
                     fg=INK, insertbackground=ACCENT, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=LINE,
                     highlightcolor=ACCENT, font=("Segoe UI", 10), padx=12, pady=9,
                     selectbackground="#d9eae1", selectforeground=INK, undo=True)
    widget.insert("1.0", value)
    widget.pack(fill="x", pady=(6, 12))
    return widget


class ScrollPage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, bd=0, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        if not self.winfo_ismapped() or isinstance(event.widget, (tk.Text, ttk.Treeview, ttk.Combobox, ttk.Spinbox)):
            return
        current = event.widget
        while current is not None:
            if current is self:
                self.canvas.yview_scroll(-int(event.delta / 120), "units")
                return "break"
            current = getattr(current, "master", None)


class DesktopUI:
    def __init__(self, app, areas, experiences, exp_filters):
        self.app = app
        self.root = app.root
        self.pages = {}
        self.nav_buttons = {}
        self.running = False
        self.compact = None
        self._theme()
        self.root.configure(bg=BG)
        width = min(1320, self.root.winfo_screenwidth() - 70)
        height = min(880, self.root.winfo_screenheight() - 90)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(1000, 680)
        self._shell()
        self._overview()
        self._search(areas, experiences, exp_filters)
        self._sources()
        self._model()
        self._journal()
        for variable in (app.var_recs, app.var_resume_only, app.var_habr,
                         app.var_superjob, app.var_telegram, app.var_model):
            variable.trace_add("write", lambda *_: self.update_summary())
        self.update_summary()
        self.show("Обзор")
        self.refresh_results()
        self.root.bind("<Configure>", self._resize, add="+")

    def _theme(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=BG, foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG)
        style.configure("TButton", padding=(14, 9), background=PAPER, bordercolor=LINE,
                        lightcolor=PAPER, darkcolor=PAPER, focuscolor=ACCENT)
        style.map("TButton", background=[("active", "#eaf0e7"), ("disabled", "#edf0eb")],
                  foreground=[("disabled", "#9ca89f")])
        style.configure("Accent.TButton", background=ACCENT, foreground="white",
                        bordercolor=ACCENT, font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#1d5f55"), ("disabled", "#bdccc2")],
                  foreground=[("disabled", "white")])
        style.configure("TEntry", fieldbackground="#f8faf7", padding=9, bordercolor=LINE)
        style.configure("TCombobox", fieldbackground="#f8faf7", padding=8, bordercolor=LINE,
                        arrowcolor=ACCENT)
        style.map("TCombobox", fieldbackground=[("readonly", "#f8faf7")],
                  selectbackground=[("readonly", "#f8faf7")], selectforeground=[("readonly", INK)])
        style.configure("TSpinbox", fieldbackground="#f8faf7", padding=7, bordercolor=LINE)
        style.configure("Card.TCheckbutton", background=PAPER, padding=(0, 6))
        style.map("Card.TCheckbutton", background=[("active", PAPER)])
        style.configure("Treeview", background=PAPER, fieldbackground=PAPER, foreground=INK,
                        rowheight=44, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#edf2eb", foreground=MUTED,
                        padding=(10, 12), font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#dcebe1")], foreground=[("selected", "#153e33")])
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=LINE,
                        borderwidth=0, thickness=3)
        style.configure("Vertical.TScrollbar", background="#d8e1d7", troughcolor=BG,
                        borderwidth=0, arrowsize=10, bordercolor=BG, lightcolor=BG, darkcolor=BG)
        style.configure("Horizontal.TScrollbar", background="#d8e1d7", troughcolor=BG,
                        borderwidth=0, arrowsize=10, bordercolor=BG, lightcolor=BG, darkcolor=BG)
        for direction, sticky in (("Vertical", "ns"), ("Horizontal", "we")):
            style.layout(f"{direction}.TScrollbar", [(f"{direction}.Scrollbar.trough", {
                "sticky": sticky, "children": [(f"{direction}.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"})]})])

    def _shell(self):
        app = self.app
        sidebar = tk.Frame(self.root, bg=NAV, width=210)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=NAV, padx=24, pady=30)
        brand.pack(fill="x")
        label(brand, "hh /", 28, "#c3dfb7", True).pack(anchor="w")
        label(brand, "assistant", 16, "white", True).pack(anchor="w")
        label(brand, "Твой поиск. Твои правила.", 9, "#a8bfb0").pack(anchor="w", pady=(8, 26))
        label(sidebar, "    ПРОСТРАНСТВО", 8, "#8faa9b", True).pack(anchor="w", padx=10, pady=(0, 10))
        for index, name in enumerate(("Обзор", "Поиск и фильтры", "Источники", "Модель", "Журнал"), 1):
            button = tk.Button(sidebar, text=f"{index:02}    {name}", anchor="w", relief="flat", bd=0,
                               bg=NAV, fg="#bed0c4", activebackground="#2a5145", activeforeground="white",
                               font=("Segoe UI", 10), padx=17, pady=14, cursor="hand2",
                               command=lambda page=name: self.show(page))
            button.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[name] = button
        footer = tk.Frame(sidebar, bg=NAV, padx=22, pady=24)
        footer.pack(side="bottom", fill="x")
        tk.Button(footer, text="Мой профиль  ↗", anchor="w", bg=NAV, fg="white",
                  activebackground=NAV, activeforeground="#c3dfb7", relief="flat", bd=0,
                  font=("Segoe UI", 10), cursor="hand2", command=app.on_open_profile).pack(fill="x")
        self.model_badge = label(footer, "LM Studio", 9, "#9eb6a6", wraplength=160)
        self.model_badge.pack(anchor="w", pady=(15, 0))
        main = tk.Frame(self.root, bg=BG, padx=28, pady=22)
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", pady=(0, 18))
        self.breadcrumb = label(header, "ОБЗОР", 9, MUTED, True)
        self.breadcrumb.pack(side="left")
        app.btn_start = ttk.Button(header, text="Начать поиск  →", style="Accent.TButton", command=app.on_start)
        app.btn_start.pack(side="right")
        app.btn_stop = ttk.Button(header, text="Остановить", command=app.on_stop, state="disabled")
        app.btn_stop.pack(side="right", padx=(0, 10))
        bottom = tk.Frame(main, bg=BG)
        bottom.pack(side="bottom", fill="x", pady=(14, 0))
        app.progress = ttk.Progressbar(bottom, mode="indeterminate")
        app.lbl_status = ttk.Label(bottom, text="Готов к работе", anchor="w", font=("Segoe UI", 9))
        app.lbl_status.pack(fill="x")
        self.container = tk.Frame(main, bg=BG)
        self.container.pack(fill="both", expand=True)
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)

    def page(self, name, title, subtitle, scroll=True):
        page = ScrollPage(self.container) if scroll else tk.Frame(self.container, bg=BG)
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[name] = page
        body = page.body if scroll else page
        title_label = label(body, title, 25, bold=True)
        title_label.pack(anchor="w")
        subtitle_label = label(body, subtitle, 10, MUTED, wraplength=800)
        subtitle_label.pack(anchor="w", pady=(6, 22))
        if name == "Обзор":
            self.hero_title = title_label
            self.hero_subtitle = subtitle_label
        return body

    def show(self, name):
        if name not in self.pages:
            return
        self.pages[name].tkraise()
        self.breadcrumb.configure(text=f"РАБОЧЕЕ ПРОСТРАНСТВО  /  {name.upper()}")
        for page, button in self.nav_buttons.items():
            button.configure(bg="#315749" if page == name else NAV,
                             fg="white" if page == name else "#bed0c4")

    def _overview(self):
        app = self.app
        body = self.page("Обзор", "Твой следующий шаг", "Вакансии по твоим правилам. Всё важное — в одном месте.", scroll=False)
        metrics = tk.Frame(body, bg=BG)
        metrics.pack(fill="x", pady=(0, 20))
        self.metrics = []
        self.metric_boxes = []
        self.metric_hints = []
        for col, title in enumerate(("ПРОВЕРЕНО", "ПОДХОДИТ", "ОТСЕЯНО")):
            box = tk.Frame(metrics, bg=PAPER, padx=18, pady=13, highlightthickness=1, highlightbackground=LINE)
            box.grid(row=0, column=col, sticky="nsew", padx=(0, 12) if col < 2 else 0)
            self.metric_boxes.append(box)
            metrics.columnconfigure(col, weight=1)
            label(box, title, 8, MUTED, True).pack(anchor="w")
            number = label(box, "—", 25, ACCENT, True)
            number.pack(anchor="w", pady=(4, 0))
            hint = label(box, "за текущий запуск", 9, MUTED)
            hint.pack(anchor="w")
            self.metric_hints.append(hint)
            self.metrics.append(number)
        toolbar = tk.Frame(body, bg=BG)
        toolbar.pack(fill="x", pady=(0, 12))
        label(toolbar, "Вакансии", 14, bold=True).pack(side="left")
        self.count = label(toolbar, "", 9, MUTED)
        self.count.pack(side="left", padx=12)
        ttk.Button(toolbar, text="История ↗", command=app.on_open_history).pack(side="right")
        self.bulk_button = ttk.Button(toolbar, text="Открыть все вакансии", state="disabled",
                                      command=app.on_open_all_vacancies)
        self.bulk_button.pack(side="right", padx=(0, 10))
        filters = tk.Frame(body, bg=BG)
        filters.pack(fill="x", pady=(0, 12))
        self.query = tk.StringVar()
        ttk.Entry(filters, textvariable=self.query, width=24).pack(side="left", fill="x", expand=True)
        self.filter = tk.StringVar(value="Подходящие")
        ttk.Combobox(filters, textvariable=self.filter, state="readonly", width=16,
                     values=("Подходящие", "Все", "На проверку", "Отклонённые")).pack(side="left", padx=(10, 0))
        self.query.trace_add("write", lambda *_: self.refresh_results())
        self.filter.trace_add("write", lambda *_: self.refresh_results())
        label(body, "Текущий поиск · прошлые результаты доступны в истории", 9, MUTED).pack(anchor="w", pady=(0, 12))
        content = tk.Frame(body, bg=BG)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=0, minsize=270)
        content.rowconfigure(0, weight=1)
        table = tk.Frame(content, bg=PAPER, highlightthickness=1, highlightbackground=LINE)
        table.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        cols = ("score", "verdict", "direction", "resume", "name", "employer", "salary")
        app.tree = ttk.Treeview(table, columns=cols, displaycolumns=("name", "employer", "score"),
                                show="headings", selectmode="browse", height=5)
        for col, title, width in (("name", "ДОЛЖНОСТЬ", 250), ("employer", "КОМПАНИЯ", 145), ("score", "БАЛЛ", 70)):
            app.tree.heading(col, text=title)
            app.tree.column(col, width=width, minwidth=60, stretch=col != "score", anchor="center" if col == "score" else "w")
        vertical = ttk.Scrollbar(table, orient="vertical", command=app.tree.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=app.tree.xview)
        app.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        horizontal.pack(side="bottom", fill="x")
        vertical.pack(side="right", fill="y")
        app.tree.pack(fill="both", expand=True)
        for tag, bg, fg in (("good", PAPER, INK), ("bad", "#fcf5f1", "#866151"),
                            ("weak", "#fbf9ef", "#7b7049"), ("unknown", "#fbf9ef", "#7b7049")):
            app.tree.tag_configure(tag, background=bg, foreground=fg)
        app.tree.bind("<<TreeviewSelect>>", app.on_select_result)
        app.tree.bind("<Double-1>", app.on_open_vacancy)
        self.empty = label(table, "Пока здесь тихо\n\nНачни поиск — подходящие вакансии\nпоявятся в этом списке.", 11, MUTED)
        self.empty.configure(justify="center", anchor="center")
        detail = tk.Frame(content, bg=PAPER, width=280, padx=18, pady=18,
                          highlightthickness=1, highlightbackground=LINE)
        detail.grid(row=0, column=1, sticky="nsew")
        detail.grid_propagate(False)
        detail.pack_propagate(False)
        self.open_button = ttk.Button(detail, text="Открыть вакансию ↗", style="Accent.TButton",
                                      state="disabled", command=lambda: app.on_open_vacancy(None))
        self.open_button.pack(side="bottom", fill="x", pady=(12, 0))
        detail_scroll = ScrollPage(detail)
        detail_scroll.configure(bg=PAPER)
        detail_scroll.canvas.configure(bg=PAPER)
        detail_scroll.body.configure(bg=PAPER)
        detail_scroll.pack(fill="both", expand=True)
        self.detail_scroll = detail_scroll
        detail = detail_scroll.body
        self.detail_verdict = label(detail, "ПОДРОБНОСТИ", 9, ACCENT, True)
        self.detail_verdict.pack(anchor="w")
        self.detail_title = label(detail, "Выбери вакансию", 14, bold=True, wraplength=216)
        self.detail_title.pack(anchor="w", pady=(12, 8))
        self.detail_meta = label(detail, "Здесь будут условия и объяснение оценки.", 10, MUTED, wraplength=216)
        self.detail_meta.pack(anchor="w", pady=(0, 14))
        reason_box = tk.Frame(detail, bg=PAPER)
        reason_box.pack(fill="both", expand=True)
        app.txt_reason = tk.Text(reason_box, width=22, height=12, bg=PAPER, fg=MUTED,
                                  font=("Segoe UI", 10), bd=0, wrap="word", state="disabled",
                                  highlightthickness=0, cursor="arrow")
        app.txt_reason.pack(side="left", fill="both", expand=True)
        self.mode = label(body, "", 9, MUTED)
        self.mode.pack(anchor="w", pady=(12, 0))

    def _field(self, parent, title, attr, key, height=3):
        label(parent, title, 10, bold=True).pack(anchor="w", pady=(7, 0))
        setattr(self.app, attr, text_input(parent, self.app.cfg.get(key, ""), height))

    def _check(self, parent, title, attr, key):
        variable = tk.BooleanVar(value=self.app.cfg.get(key, False))
        setattr(self.app, attr, variable)
        ttk.Checkbutton(parent, text=title, variable=variable, style="Card.TCheckbutton").pack(anchor="w")

    def _entry(self, parent, title, attr, key, values=None):
        label(parent, title, 10, bold=True).pack(anchor="w", pady=(8, 5))
        variable = tk.StringVar(value=self.app.cfg.get(key, ""))
        setattr(self.app, attr, variable)
        if values is None:
            widget = ttk.Entry(parent, textvariable=variable)
        else:
            widget = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        widget.pack(fill="x", pady=(0, 10))
        return widget

    def _save_button(self, parent):
        ttk.Button(parent, text="Сохранить настройки", style="Accent.TButton", command=self.save).pack(anchor="w", pady=(0, 18))

    def _search(self, areas, experiences, exp_filters):
        a = self.app
        body = self.page("Поиск и фильтры", "Чуть ближе к твоей работе", "Задай направление. Поиск сохранит эти настройки для следующего запуска.")
        section = card(body, "Что ищем", "Категории дают широкий охват, а запросы помогают найти конкретные роли.")
        row = tk.Frame(section, bg=PAPER)
        row.pack(fill="x", pady=(0, 12))
        a.lbl_roles = label(row, "", 10)
        a.lbl_roles.pack(side="left")
        ttk.Button(row, text="Выбрать категории", command=a.on_pick_roles).pack(side="right")
        a._update_roles_label()
        self._field(section, "Поисковые запросы · по одному на строку", "txt_queries", "queries", 4)
        self._check(section, "Искать каждую категорию отдельно", "var_split", "split_roles")
        section = card(body, "Условия", "Выбери регион и формат работы.")
        self._entry(section, "Регион", "var_area", "area", list(areas))
        self._entry(section, "Опыт в выдаче HH", "var_exp", "experience", list(experiences))
        self._entry(section, "Сразу исключать по тегу опыта", "var_exp_filter", "exp_filter", list(exp_filters))
        self._check(section, "Только удалённая работа", "var_remote", "remote_only")
        self._check(section, "Дополнительно искать удалёнку по всей России", "var_remote_extra", "remote_extra")
        self._check(section, "Только вакансии с зарплатой", "var_salary", "only_with_salary")
        section = card(body, "Точный отсев", "Слова и названия компаний указывай через запятую.")
        self._field(section, "Стоп-слова в названии", "txt_exclude", "exclude_words")
        self._field(section, "Целевые слова · сразу на полную проверку", "txt_include", "include_words")
        self._field(section, "Компании-исключения", "txt_companies", "exclude_companies", 2)
        section = card(body, "Темп поиска", "Паузы помогают снизить нагрузку на сайты.")
        for title, attr, key, cls, maximum in (("Страниц на источник", "var_pages", "pages", tk.IntVar, 100),
                                               ("Минимальная пауза, с", "var_dmin", "min_delay", tk.DoubleVar, 120),
                                               ("Максимальная пауза, с", "var_dmax", "max_delay", tk.DoubleVar, 120)):
            row = tk.Frame(section, bg=PAPER)
            row.pack(fill="x", pady=5)
            label(row, title).pack(side="left")
            variable = cls(value=a.cfg[key])
            setattr(a, attr, variable)
            ttk.Spinbox(row, from_=1, to=maximum, width=8, textvariable=variable).pack(side="right")
        self._save_button(body)

    def _sources(self):
        a = self.app
        body = self.page("Источники", "Больше мест. Больше возможностей.", "Подключи площадки, на которых хочешь искать работу.")
        section = card(body, "HeadHunter", "Публичный поиск работает без входа. Для персональных рекомендаций нужна сессия аккаунта.")
        self._check(section, "Рекомендации HH под моё резюме", "var_recs", "recs_enabled")
        self._check(section, "Только рекомендации HH", "var_resume_only", "hh_resume_only")
        label(section, "Этот режим отключает категории, запросы и все остальные площадки.", 9, MUTED, wraplength=730).pack(anchor="w", pady=(0, 12))
        self._entry(section, "Ссылка на резюме или его hash", "var_resume", "resume_hash")
        self._field(section, "Cookies HH", "txt_cookie", "hh_cookie", 2)
        self._hide_secret(a.txt_cookie)
        label(section, "Cookies хранятся в системном хранилище. Не передавай их другим людям.", 9, MUTED, wraplength=720).pack(anchor="w")
        ttk.Button(section, text="Как получить cookies", command=self.cookie_help).pack(anchor="w", pady=(10, 0))
        section = card(body, "Другие площадки")
        self._check(section, "Хабр Карьера", "var_habr", "habr_enabled")
        self._check(section, "SuperJob · первая страница каждого запроса", "var_superjob", "superjob_enabled")
        self._entry(section, "Ссылка на резюме SuperJob · пока только хранится", "var_sj_resume", "superjob_resume_url")
        self._field(section, "Cookies SuperJob · необязательно", "txt_sj_cookie", "superjob_cookie", 2)
        self._hide_secret(a.txt_sj_cookie)
        self._check(section, "Публичные Telegram-каналы", "var_telegram", "telegram_enabled")
        self._field(section, "Каналы · по одному на строку", "txt_telegram", "telegram_channels", 4)
        self._save_button(body)

    def _hide_secret(self, widget):
        # Text keeps its existing get/insert API; an elided tag conceals content.
        widget.tag_add("secret", "1.0", "end")
        widget.tag_configure("secret", elide=True)
        saved = bool(widget.get("1.0", "end").strip())
        widget.configure(height=1, state="disabled")
        status = label(widget.master, "Содержимое скрыто" if saved else "Покажи поле, чтобы добавить cookies", 9, MUTED)
        status.pack(anchor="w")
        shown = tk.BooleanVar(value=False)
        def toggle():
            widget.tag_remove("secret", "1.0", "end")
            if not shown.get():
                widget.tag_add("secret", "1.0", "end")
            widget.configure(height=3 if shown.get() else 1, state="normal" if shown.get() else "disabled")
            status.configure(text="После изменений сохрани настройки" if shown.get() else "Содержимое скрыто")
        ttk.Checkbutton(widget.master, text="Показать / изменить cookies", variable=shown,
                        style="Card.TCheckbutton", command=toggle).pack(anchor="w", pady=(0, 10))

    def _model(self):
        a = self.app
        body = self.page("Модель", "Твой помощник по отбору", "Подключи LM Studio и выбери модель, которая будет читать вакансии.")
        section = card(body, "Подключение")
        self._entry(section, "Адрес сервера", "var_lm_url", "lm_url")
        ttk.Button(section, text="Проверить связь", command=a.on_check_lm).pack(anchor="w", pady=(0, 12))
        for title, attr, key, combo in (("Модель для полной оценки", "var_model", "lm_model", "cmb_model"),
                                        ("Быстрая модель · пусто = основная", "var_model_fast", "lm_model_fast", "cmb_model_fast")):
            label(section, title, bold=True).pack(anchor="w", pady=(8, 5))
            variable = tk.StringVar(value=a.cfg[key])
            setattr(a, attr, variable)
            widget = ttk.Combobox(section, textvariable=variable)
            widget.pack(fill="x", pady=(0, 12))
            setattr(a, combo, widget)
        self._check(section, "Быстрый отсев заголовков перед полной оценкой", "var_triage", "triage")
        section = card(body, "Перед началом", "Запусти сервер в LM Studio и загрузи выбранную модель. Контекст должен вмещать профиль и описание вакансии.")
        label(section, "Если модель перестала отвечать, ожидание может занять до 10 минут.\nПрофиль передаётся на указанный выше сервер.", 10, MUTED, wraplength=740).pack(anchor="w")
        self._save_button(body)

    def _journal(self):
        a = self.app
        body = self.page("Журнал", "Что происходит сейчас", "Подробности поиска и сообщения, к которым можно вернуться.", scroll=False)
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=(0, 15))
        ttk.Button(row, text="Папка результатов ↗", command=a.on_open_results).pack(side="left")
        ttk.Button(row, text="Лучшие вакансии ↗", command=a.on_open_top).pack(side="left", padx=10)
        box = tk.Frame(body, bg=PAPER, highlightthickness=1, highlightbackground=LINE)
        box.pack(fill="both", expand=True)
        a.log_widget = tk.Text(box, bg=PAPER, fg=MUTED, font=("Consolas", 10), relief="flat",
                               wrap="word", state="disabled", padx=18, pady=16, highlightthickness=0)
        scroll = ttk.Scrollbar(box, command=a.log_widget.yview)
        a.log_widget.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        a.log_widget.pack(fill="both", expand=True)

    def update_summary(self):
        a = self.app
        only = a.var_recs.get() and a.var_resume_only.get()
        self.mode.configure(text="Режим: только рекомендации HH" if only else "Режим: поиск по выбранным источникам")
        self.model_badge.configure(text="Модель\n" + (a.var_model.get() or "не выбрана"))

    def save(self):
        try:
            self.app._collect_config()
            self.app.lbl_status.configure(text="Настройки сохранены")
        except (RuntimeError, OSError, ValueError, tk.TclError) as exc:
            messagebox.showerror("Настройки", str(exc), parent=self.root)

    @staticmethod
    def cookie_help():
        messagebox.showinfo("Cookies аккаунта", "На сайте открой F12 → Network и обнови страницу.\n"
                            "Выбери запрос страницы, затем Request Headers → Cookie.\n"
                            "Скопируй значение в соответствующее поле приложения.")

    def add_result(self, data, refresh=True):
        verdict = data.get("verdict", "")
        tag = "unknown" if data.get("suitable") is None else (
            "good" if verdict in ("MATCH", "STRONG_MATCH") else "weak" if verdict == "WEAK" else "bad")
        score = "—" if data.get("score") is None else str(data["score"])
        iid = self.app.tree.insert("", 0, values=(score, VERDICTS.get(verdict, "На проверку"),
                                  data.get("direction") or "—", data.get("resume") or "—",
                                  data["name"], data["employer"], data["salary"]), tags=(tag,))
        self.app.result_data[iid] = data
        if refresh:
            self.refresh_results()

    def refresh_results(self):
        if not hasattr(self.app, "tree"):
            return
        a = self.app
        selected = a.tree.selection()
        query = self.query.get().strip().casefold()
        wanted = self.filter.get()
        visible = []
        for iid, row in reversed(list(a.result_data.items())):
            verdict = row.get("verdict")
            matches = (not query or query in (row["name"] + " " + row["employer"]).casefold())
            matches &= (wanted == "Все" or
                        wanted == "Подходящие" and row.get("suitable") is True or
                        wanted == "На проверку" and (row.get("suitable") is None or verdict == "WEAK") or
                        wanted == "Отклонённые" and verdict == "REJECT")
            if matches:
                a.tree.move(iid, "", "end")
                visible.append(iid)
            else:
                a.tree.detach(iid)
        self.count.configure(text=f"{len(visible)} из {len(a.result_data)}")
        self.update_bulk_button()
        if visible:
            self.empty.place_forget()
            if not selected or selected[0] not in visible:
                a.tree.selection_set(visible[0])
                a.on_select_result(None)
        else:
            self.empty.configure(text="Ничего не найдено\n\nПопробуй другой запрос или фильтр." if a.result_data else
                                 "Ищем новые вакансии\n\nРезультаты появятся здесь\nпо мере проверки." if self.running else
                                 "Пока здесь тихо\n\nНачни поиск — вакансии\nпоявятся в этом списке.")
            self.empty.place(relx=.5, rely=.5, anchor="center")
            a.tree.selection_remove(*a.tree.selection())
            self.open_button.configure(state="disabled")
            self.detail_title.configure(text="Выбери вакансию")
            self.detail_meta.configure(text="Здесь будут условия и объяснение оценки.")
            self.detail_verdict.configure(text="ПОДРОБНОСТИ")
            a.txt_reason.configure(state="normal")
            a.txt_reason.delete("1.0", "end")
            a.txt_reason.configure(state="disabled")

    def show_detail(self, data):
        self.detail_scroll.canvas.yview_moveto(0)
        self.detail_title.configure(text=data["name"])
        self.detail_verdict.configure(text=VERDICTS.get(data.get("verdict"), "На проверку").upper())
        self.detail_meta.configure(text=f"{data['employer']}\n{data['salary']}\n{data.get('direction') or 'Направление не определено'}")
        self.open_button.configure(state="normal")

    def update_bulk_button(self):
        if self.app.browser_queue.active:
            self.bulk_button.configure(text="Остановить открытие", state="normal")
        else:
            enabled = not self.running and bool(suitable_urls(self.app.result_data.values()))
            self.bulk_button.configure(text="Открыть все вакансии", state="normal" if enabled else "disabled")

    def set_stats(self, skipped, checked, suitable):
        for widget, value in zip(self.metrics, (checked, suitable, skipped)):
            widget.configure(text=str(value))

    def set_running(self, running):
        self.running = running
        self.app.btn_start.configure(text="Поиск идёт…" if running else "Начать поиск  →")
        if running:
            # All results have already been persisted by Worker. Reset only the
            # session view, including rows detached by filters, never the history.
            for iid in tuple(self.app.result_data):
                self.app.tree.delete(iid)
            self.app.result_data.clear()
            self.query.set("")
            self.filter.set("Подходящие")
            self.app.progress.pack(fill="x", pady=(0, 9), before=self.app.lbl_status)
            self.set_stats(0, 0, 0)
            self.show("Обзор")
        else:
            self.app.progress.pack_forget()
            self.app.lbl_status.configure(text="Поиск завершён · подробности в журнале")
        self.refresh_results()

    def _resize(self, event):
        if event.widget is not self.root:
            return
        self.app.tree.configure(displaycolumns=("name", "score") if event.width < 1150 else ("name", "employer", "score"))
        compact = event.height < 790
        if compact == self.compact:
            return
        self.compact = compact
        self.hero_title.configure(font=("Segoe UI", 20 if compact else 25, "bold"))
        self.hero_subtitle.pack_configure(pady=(4, 10) if compact else (6, 22))
        for box, number, hint in zip(self.metric_boxes, self.metrics, self.metric_hints):
            box.configure(pady=7 if compact else 13)
            number.configure(font=("Segoe UI", 19 if compact else 25, "bold"))
            hint.configure(font=("Segoe UI", 8 if compact else 9))
