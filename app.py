"""
多源漫画下载器 v2 — 全功能 PyQt5 GUI
19 项功能: 多源搜索、Raw过滤、灵活选择、任务管理器、收藏夹、速度显示等
"""
import os, sys, re, json, time
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt, QUrl, QTimer, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage, QFont, QIcon, QDesktopServices, QKeySequence
from PyQt5.QtWidgets import QShortcut

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sources import get_all_sources
from config import Config
from favorites import FavoritesManager
from download_manager import DownloadManager, TaskStatus, extract_chapter_number
from workers import MultiSearchWorker, InfoWorker, CoverWorker, HealthCheckWorker
from themes import DARK_THEME, LIGHT_THEME

APP_VERSION = "2.0.0"
UPDATE_CHECK_URL = ""  # placeholder for future github releases API


class MangaApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.sources = get_all_sources()
        self.config = Config()
        self.favorites = FavoritesManager()
        self.dl_manager = DownloadManager(
            self.config["chapter_concurrency"],
            self.config["image_concurrency"],
        )
        self.current_source = self.sources[0]
        self.current_chapters = []
        self.current_info = {}
        self._workers = []
        self._search_results = []
        self._chapter_filter = "all"  # all / translated / raw
        self._chapter_sort_asc = True

        self.setWindowTitle("漫画下载器 v2")
        self._restore_window()
        self._apply_theme()
        self._build_ui()
        self._setup_shortcuts()
        self._connect_dl_signals()

    # ===================== THEME =====================
    def _apply_theme(self):
        theme = self.config.get("theme", "dark")
        QApplication.instance().setStyleSheet(
            DARK_THEME if theme == "dark" else LIGHT_THEME)

    def _toggle_theme(self):
        cur = self.config.get("theme", "dark")
        new = "light" if cur == "dark" else "dark"
        self.config["theme"] = new
        self.config.save()
        self._apply_theme()

    # ===================== WINDOW STATE =====================
    def _restore_window(self):
        x = self.config.get("window_x", 100)
        y = self.config.get("window_y", 100)
        w = self.config.get("window_w", 1300)
        h = self.config.get("window_h", 850)
        self.setGeometry(x, y, w, h)
        self.setMinimumSize(1100, 700)

    def _save_window(self):
        g = self.geometry()
        self.config["window_x"] = g.x()
        self.config["window_y"] = g.y()
        self.config["window_w"] = g.width()
        self.config["window_h"] = g.height()
        self.config.save()

    # ===================== SHORTCUTS =====================
    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self._nav(0))
        QShortcut(QKeySequence("Ctrl+A"), self, self._select_all_chapters)
        QShortcut(QKeySequence("Escape"), self, self._cancel_search)

    def _cancel_search(self):
        self.search_input.clear()

    # ===================== BUILD UI =====================
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame(); header.setObjectName("header"); header.setFixedHeight(52)
        hl = QHBoxLayout(header); hl.setContentsMargins(20, 0, 20, 0)
        t = QLabel("Manga Downloader"); t.setObjectName("headerTitle"); hl.addWidget(t)
        hl.addStretch()
        theme_btn = QPushButton("Theme"); theme_btn.setObjectName("secondaryBtn")
        theme_btn.setFixedSize(70, 32); theme_btn.setToolTip("Dark / Light")
        theme_btn.clicked.connect(self._toggle_theme); hl.addWidget(theme_btn)
        v_lbl = QLabel(f"v{APP_VERSION}"); v_lbl.setObjectName("headerSub"); hl.addWidget(v_lbl)
        root.addWidget(header)

        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)

        # Sidebar
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(170)
        sl = QVBoxLayout(sidebar); sl.setContentsMargins(8, 14, 8, 14); sl.setSpacing(3)
        pages = ["  Search  ", "  Detail  ", "  Download ", "  Favorite ", "  Settings "]
        self.nav_btns = []
        for i, label in enumerate(pages):
            b = QPushButton(label); b.setObjectName("navBtn")
            b.setCheckable(True); b.setAutoExclusive(True)
            b.clicked.connect(lambda _, idx=i: self._nav(idx))
            sl.addWidget(b); self.nav_btns.append(b)
        self.nav_btns[0].setChecked(True)
        sl.addStretch()
        body.addWidget(sidebar)

        # Pages
        self.stacked = QStackedWidget()
        self.stacked.addWidget(self._page_search())
        self.stacked.addWidget(self._page_detail())
        self.stacked.addWidget(self._page_download())
        self.stacked.addWidget(self._page_favorites())
        self.stacked.addWidget(self._page_settings())
        body.addWidget(self.stacked, 1)
        root.addLayout(body, 1)

        # StatusBar
        sb = QStatusBar(); self.setStatusBar(sb)
        self.status_label = QLabel("就绪"); sb.addWidget(self.status_label, 1)
        self.speed_label = QLabel(""); sb.addPermanentWidget(self.speed_label)

    def _nav(self, idx):
        self.stacked.setCurrentIndex(idx)
        if idx < len(self.nav_btns):
            self.nav_btns[idx].setChecked(True)

    # ===================== PAGE: SEARCH =====================
    def _page_search(self):
        p = QWidget(); L = QVBoxLayout(p); L.setContentsMargins(24, 20, 24, 20); L.setSpacing(14)
        L.addWidget(self._lbl("搜索漫画", "sectionLabel"))

        # 搜索栏
        bar = QHBoxLayout()
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText("输入漫画名称，将从 6 个源并发搜索...")
        self.search_input.returnPressed.connect(self._do_search)
        bar.addWidget(self.search_input, 1)

        # 搜索历史下拉
        self.history_combo = QComboBox(); self.history_combo.setFixedWidth(160)
        self.history_combo.setToolTip("Search History"); self.history_combo.addItem("-- History --")
        for h in self.config.get_search_history():
            self.history_combo.addItem(h)
        self.history_combo.currentTextChanged.connect(self._on_history_select)
        bar.addWidget(self.history_combo)

        self.search_btn = QPushButton("搜索"); self.search_btn.setObjectName("primaryBtn")
        self.search_btn.setFixedWidth(90); self.search_btn.clicked.connect(self._do_search)
        bar.addWidget(self.search_btn)
        L.addLayout(bar)

        # 源筛选
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("按源筛选:")); filter_bar.addWidget(self._lbl("", "statsLabel"))
        self.source_filter = QComboBox(); self.source_filter.addItem("全部源")
        for s in self.sources: self.source_filter.addItem(f"{s.icon} {s.name}")
        self.source_filter.currentIndexChanged.connect(self._filter_search)
        filter_bar.addWidget(self.source_filter); filter_bar.addStretch()
        self.search_status = QLabel(""); self.search_status.setObjectName("statsLabel")
        filter_bar.addWidget(self.search_status)
        L.addLayout(filter_bar)

        # 搜索结果表格
        self.search_table = QTableWidget(); self.search_table.setColumnCount(4)
        self.search_table.setHorizontalHeaderLabels(["来源", "漫画名称", "类型", "操作"])
        h = self.search_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed); h.resizeSection(0, 110)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.Fixed); h.resizeSection(3, 80)
        self.search_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.search_table.setAlternatingRowColors(True)
        self.search_table.verticalHeader().setVisible(False)
        self.search_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        L.addWidget(self.search_table)

        # 直接URL
        url_bar = QHBoxLayout()
        url_bar.addWidget(self._lbl("或直接输入 URL:", "statsLabel"))
        self.direct_url = QLineEdit(); self.direct_url.setPlaceholderText("https://...")
        self.direct_url.returnPressed.connect(self._go_url)
        url_bar.addWidget(self.direct_url, 1)

        # 批量导入
        batch_btn = QPushButton("Batch Import"); batch_btn.setObjectName("secondaryBtn")
        batch_btn.setFixedWidth(100); batch_btn.clicked.connect(self._batch_import)
        url_bar.addWidget(batch_btn)
        go_btn = QPushButton("前往"); go_btn.setObjectName("secondaryBtn")
        go_btn.setFixedWidth(60); go_btn.clicked.connect(self._go_url)
        url_bar.addWidget(go_btn)
        L.addLayout(url_bar)
        return p

    # ===================== PAGE: DETAIL =====================
    def _page_detail(self):
        p = QWidget(); L = QHBoxLayout(p); L.setContentsMargins(24, 20, 24, 20); L.setSpacing(18)

        # Left - info
        left = QVBoxLayout(); left.setSpacing(10)
        self.cover_label = QLabel("封面预览"); self.cover_label.setFixedSize(220, 310)
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setStyleSheet("background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;color:#444;")
        left.addWidget(self.cover_label, 0, Qt.AlignHCenter)
        self.info_title = QLabel("选择漫画查看详情"); self.info_title.setObjectName("sectionLabel")
        self.info_title.setWordWrap(True); self.info_title.setAlignment(Qt.AlignCenter)
        left.addWidget(self.info_title)
        self.info_source = QLabel(""); self.info_source.setObjectName("accentLabel")
        self.info_source.setAlignment(Qt.AlignCenter); left.addWidget(self.info_source)
        self.info_genres = QLabel(""); self.info_genres.setObjectName("statsLabel")
        self.info_genres.setWordWrap(True); self.info_genres.setAlignment(Qt.AlignCenter)
        left.addWidget(self.info_genres)
        self.info_desc = QLabel(""); self.info_desc.setObjectName("statsLabel")
        self.info_desc.setWordWrap(True); self.info_desc.setMaximumHeight(60)
        left.addWidget(self.info_desc)

        # Favorite button
        self.fav_btn = QPushButton("+ Favorite"); self.fav_btn.setObjectName("secondaryBtn")
        self.fav_btn.clicked.connect(self._toggle_favorite); left.addWidget(self.fav_btn)

        left.addStretch()

        # Chapter action buttons
        btn_row1 = QHBoxLayout()
        for txt, fn in [("全选", self._select_all_chapters), ("取消", self._deselect_all),
                         ("反选", self._invert_selection)]:
            b = QPushButton(txt); b.setObjectName("secondaryBtn"); b.setFixedHeight(32)
            b.clicked.connect(fn); btn_row1.addWidget(b)
        left.addLayout(btn_row1)

        # Range select
        range_row = QHBoxLayout()
        range_row.addWidget(self._lbl("范围:", "statsLabel"))
        self.range_from = QSpinBox(); self.range_from.setMinimum(1); self.range_from.setFixedWidth(60)
        self.range_to = QSpinBox(); self.range_to.setMinimum(1); self.range_to.setMaximum(9999); self.range_to.setFixedWidth(60)
        range_row.addWidget(self.range_from); range_row.addWidget(QLabel("~")); range_row.addWidget(self.range_to)
        range_btn = QPushButton("选择"); range_btn.setObjectName("smallBtn"); range_btn.setFixedWidth(50)
        range_btn.clicked.connect(self._range_select); range_row.addWidget(range_btn)
        left.addLayout(range_row)

        self.dl_btn = QPushButton("Download Selected"); self.dl_btn.setObjectName("primaryBtn")
        self.dl_btn.setEnabled(False); self.dl_btn.clicked.connect(self._start_download)
        left.addWidget(self.dl_btn)

        lw = QWidget(); lw.setLayout(left); lw.setFixedWidth(260); L.addWidget(lw)

        # Right - chapter list
        right = QVBoxLayout(); right.setSpacing(10)

        # Filter + sort bar
        fb = QHBoxLayout()
        self.ch_header = QLabel("章节列表"); self.ch_header.setObjectName("sectionLabel")
        fb.addWidget(self.ch_header)
        fb.addStretch()
        for txt, val in [("全部", "all"), ("翻译版", "translated"), ("Raw", "raw")]:
            b = QPushButton(txt); b.setObjectName("filterBtn"); b.setCheckable(True)
            b.setAutoExclusive(True)
            if val == "all": b.setChecked(True)
            b.clicked.connect(lambda _, v=val: self._set_chapter_filter(v))
            fb.addWidget(b)
        sort_btn = QPushButton("Sort"); sort_btn.setObjectName("secondaryBtn")
        sort_btn.setFixedHeight(30); sort_btn.setFixedWidth(60); sort_btn.clicked.connect(self._toggle_sort)
        fb.addWidget(sort_btn)
        right.addLayout(fb)

        self.ch_table = QTableWidget(); self.ch_table.setColumnCount(5)
        self.ch_table.setHorizontalHeaderLabels(["✓", "#", "章节", "类型", "日期"])
        ch = self.ch_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.Fixed); ch.resizeSection(0, 36)
        ch.setSectionResizeMode(1, QHeaderView.Fixed); ch.resizeSection(1, 50)
        ch.setSectionResizeMode(2, QHeaderView.Stretch)
        ch.setSectionResizeMode(3, QHeaderView.Fixed); ch.resizeSection(3, 70)
        ch.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.ch_table.setAlternatingRowColors(True)
        self.ch_table.verticalHeader().setVisible(False)
        self.ch_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        right.addWidget(self.ch_table)

        self.ch_stats = QLabel(""); self.ch_stats.setObjectName("accentLabel")
        right.addWidget(self.ch_stats)
        rw = QWidget(); rw.setLayout(right); L.addWidget(rw, 1)
        return p

    # ===================== PAGE: DOWNLOAD =====================
    def _page_download(self):
        p = QWidget(); L = QVBoxLayout(p); L.setContentsMargins(24, 20, 24, 20); L.setSpacing(14)
        L.addWidget(self._lbl("下载管理", "sectionLabel"))

        self.dl_progress = QProgressBar(); self.dl_progress.setValue(0)
        self.dl_progress.setFormat("%v / %m 章节"); L.addWidget(self.dl_progress)

        info_row = QHBoxLayout()
        self.dl_status = QLabel("等待下载任务..."); self.dl_status.setObjectName("accentLabel")
        info_row.addWidget(self.dl_status)
        info_row.addStretch()
        self.dl_speed = QLabel(""); self.dl_speed.setObjectName("statsLabel")
        info_row.addWidget(self.dl_speed)
        L.addLayout(info_row)

        # Task table
        self.task_table = QTableWidget(); self.task_table.setColumnCount(6)
        self.task_table.setHorizontalHeaderLabels(["章节", "状态", "进度", "速度", "操作", ""])
        th = self.task_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in [(1, 70), (2, 100), (3, 80), (4, 60), (5, 60)]:
            th.setSectionResizeMode(i, QHeaderView.Fixed); th.resizeSection(i, w)
        self.task_table.setAlternatingRowColors(True)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        L.addWidget(self.task_table)

        btn_bar = QHBoxLayout()
        self.cancel_all_btn = QPushButton("Cancel All"); self.cancel_all_btn.setObjectName("dangerBtn")
        self.cancel_all_btn.clicked.connect(self._cancel_all); btn_bar.addWidget(self.cancel_all_btn)
        open_btn = QPushButton("Open Folder"); open_btn.setObjectName("secondaryBtn")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(self.config["download_dir"]))); btn_bar.addWidget(open_btn)
        btn_bar.addStretch()
        L.addLayout(btn_bar)

        log_lbl = QLabel("日志"); log_lbl.setObjectName("statsLabel"); L.addWidget(log_lbl)
        self.log_box = QTextEdit(); self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(180); L.addWidget(self.log_box)
        return p

    # ===================== PAGE: FAVORITES =====================
    def _page_favorites(self):
        p = QWidget(); L = QVBoxLayout(p); L.setContentsMargins(24, 20, 24, 20); L.setSpacing(14)

        top = QHBoxLayout()
        top.addWidget(self._lbl("Favorites", "sectionLabel"))
        top.addStretch()
        top.addWidget(QLabel("Group:"))
        self.fav_group_combo = QComboBox(); self.fav_group_combo.setFixedWidth(120)
        self.fav_group_combo.addItem("All")
        for g in self.favorites.get_groups(): self.fav_group_combo.addItem(g)
        self.fav_group_combo.currentTextChanged.connect(self._refresh_favorites)
        top.addWidget(self.fav_group_combo)
        L.addLayout(top)
        # Import/Export row
        ie_row = QHBoxLayout(); ie_row.addStretch()
        imp_btn = QPushButton("Import"); imp_btn.setObjectName("secondaryBtn")
        imp_btn.setFixedSize(80, 30); imp_btn.clicked.connect(self._import_favorites)
        ie_row.addWidget(imp_btn)
        exp_btn = QPushButton("Export"); exp_btn.setObjectName("secondaryBtn")
        exp_btn.setFixedSize(80, 30); exp_btn.clicked.connect(self._export_favorites)
        ie_row.addWidget(exp_btn)
        L.addLayout(ie_row)

        self.fav_table = QTableWidget(); self.fav_table.setColumnCount(5)
        self.fav_table.setHorizontalHeaderLabels(["漫画", "来源", "分组", "收藏时间", "操作"])
        fh = self.fav_table.horizontalHeader()
        fh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in [(1, 100), (2, 80), (3, 120), (4, 120)]:
            fh.setSectionResizeMode(i, QHeaderView.Fixed); fh.resizeSection(i, w)
        self.fav_table.setAlternatingRowColors(True)
        self.fav_table.verticalHeader().setVisible(False)
        self.fav_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        L.addWidget(self.fav_table)
        self._refresh_favorites()
        return p

    # ===================== PAGE: SETTINGS =====================
    def _page_settings(self):
        p = QWidget(); L = QVBoxLayout(p); L.setContentsMargins(24, 20, 24, 20); L.setSpacing(14)
        L.addWidget(self._lbl("设置", "sectionLabel"))

        # Download dir
        g1 = QGroupBox("下载目录"); g1l = QHBoxLayout(g1)
        self.dir_input = QLineEdit(self.config["download_dir"]); g1l.addWidget(self.dir_input, 1)
        db = QPushButton("浏览"); db.setObjectName("secondaryBtn"); db.setFixedWidth(70)
        db.clicked.connect(self._choose_dir); g1l.addWidget(db)
        L.addWidget(g1)

        # Concurrency
        g2 = QGroupBox("并发设置"); g2l = QHBoxLayout(g2)
        g2l.addWidget(QLabel("章节并发:"))
        self.ch_spin = QSpinBox(); self.ch_spin.setRange(1, 10)
        self.ch_spin.setValue(self.config["chapter_concurrency"]); g2l.addWidget(self.ch_spin)
        g2l.addWidget(QLabel("图片并发:"))
        self.img_spin = QSpinBox(); self.img_spin.setRange(1, 20)
        self.img_spin.setValue(self.config["image_concurrency"]); g2l.addWidget(self.img_spin)
        g2l.addStretch()
        L.addWidget(g2)

        # Proxy
        g3 = QGroupBox("代理设置"); g3l = QHBoxLayout(g3)
        self.proxy_mode = QComboBox()
        self.proxy_mode.addItems(["无代理", "HTTP", "SOCKS5"])
        mode_map = {"none": 0, "http": 1, "socks5": 2}
        self.proxy_mode.setCurrentIndex(mode_map.get(self.config["proxy_mode"], 0))
        g3l.addWidget(self.proxy_mode)
        self.proxy_host = QLineEdit(self.config["proxy_host"]); self.proxy_host.setFixedWidth(160)
        g3l.addWidget(self.proxy_host)
        g3l.addWidget(QLabel(":"))
        self.proxy_port = QSpinBox(); self.proxy_port.setRange(1, 65535)
        self.proxy_port.setValue(self.config["proxy_port"]); g3l.addWidget(self.proxy_port)
        g3l.addStretch()
        L.addWidget(g3)

        # Save config button
        save_btn = QPushButton("Save Settings"); save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save_settings); L.addWidget(save_btn)

        # Source health check
        g4 = QGroupBox("源健康检测"); g4l = QVBoxLayout(g4)
        self.health_labels = {}
        for s in self.sources:
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{s.icon} {s.name}"))
            lbl = QLabel("未检测"); lbl.setObjectName("statsLabel")
            self.health_labels[s.name] = lbl; row.addWidget(lbl)
            row.addStretch(); g4l.addLayout(row)
        hc_btn = QPushButton("Test All Sources"); hc_btn.setObjectName("secondaryBtn")
        hc_btn.clicked.connect(self._check_health); g4l.addWidget(hc_btn)
        L.addWidget(g4)

        # Stats
        g5 = QGroupBox("统计"); g5l = QVBoxLayout(g5)
        self.stats_label = QLabel("加载中..."); self.stats_label.setObjectName("statsLabel")
        g5l.addWidget(self.stats_label); L.addWidget(g5)
        self._update_stats()
        L.addStretch()
        return p

    # ===================== HELPERS =====================
    def _lbl(self, text, name):
        l = QLabel(text); l.setObjectName(name); return l

    def _set_status(self, t):
        self.status_label.setText(t)

    # ===================== SEARCH LOGIC =====================
    def _do_search(self):
        kw = self.search_input.text().strip()
        if not kw: return
        self.config.add_search_history(kw); self.config.save()
        self._refresh_history_combo()

        self.search_btn.setEnabled(False); self._search_results.clear()
        self.search_table.setRowCount(0); self.search_status.setText("搜索中... 0/6 源")
        self._set_status(f"搜索: {kw}")
        self._search_done_count = 0

        w = MultiSearchWorker(self.sources, kw)
        w.source_done.connect(self._on_source_search_done)
        w.source_error.connect(self._on_source_search_error)
        w.all_done.connect(self._on_all_search_done)
        self._workers.append(w); w.start()

    def _on_source_search_done(self, name, results):
        self._search_done_count += 1
        self._search_results.extend(results)
        self.search_status.setText(f"搜索中... {self._search_done_count}/6 源")
        self._render_search()

    def _on_source_search_error(self, name, err):
        self._search_done_count += 1
        self.search_status.setText(f"搜索中... {self._search_done_count}/6 源 ({name} 失败)")

    def _on_all_search_done(self):
        self.search_btn.setEnabled(True)
        self.search_status.setText(f"完成: {len(self._search_results)} 个结果")
        self._set_status(f"搜索完成: {len(self._search_results)} 个结果")

    def _filter_search(self):
        self._render_search()

    def _render_search(self):
        fi = self.source_filter.currentIndex()
        items = self._search_results
        if fi > 0:
            name = self.sources[fi - 1].name
            items = [r for r in items if r.get("_source_name") == name]

        self.search_table.setRowCount(len(items))
        for i, r in enumerate(items):
            src_lbl = QLabel(f" {r.get('_source_icon','')} {r.get('_source_name','')}")
            src_lbl.setObjectName("statsLabel")
            self.search_table.setCellWidget(i, 0, src_lbl)
            self.search_table.setItem(i, 1, QTableWidgetItem(r["title"]))
            self.search_table.setItem(i, 2, QTableWidgetItem(r.get("genres", "")))
            btn = QPushButton("查看"); btn.setObjectName("smallBtn"); btn.setFixedHeight(28)
            btn.clicked.connect(lambda _, r=r: self._load_detail_from_search(r))
            self.search_table.setCellWidget(i, 3, btn)

    def _refresh_history_combo(self):
        self.history_combo.clear(); self.history_combo.addItem("-- History --")
        for h in self.config.get_search_history():
            self.history_combo.addItem(h)

    def _on_history_select(self, text):
        if text and text != "-- History --":
            self.search_input.setText(text); self._do_search()

    # ===================== URL / BATCH =====================
    def _go_url(self):
        url = self.direct_url.text().strip()
        if not url: return
        for i, s in enumerate(self.sources):
            if s.base_url in url:
                self.current_source = s; break
        self._load_detail(url)

    def _batch_import(self):
        text, ok = QInputDialog.getMultiLineText(self, "批量导入",
            "每行一个漫画 URL:", "")
        if ok and text:
            urls = [u.strip() for u in text.strip().split("\n") if u.strip()]
            if urls:
                QMessageBox.information(self, "批量导入",
                    f"已识别 {len(urls)} 个 URL。\n将逐个加载第一个。")
                self.direct_url.setText(urls[0]); self._go_url()

    # ===================== DETAIL LOGIC =====================
    def _load_detail_from_search(self, r):
        src = r.get("_source_obj", self.current_source)
        if hasattr(src, 'name'):
            self.current_source = src
        self._load_detail(r["url"])

    def _load_detail(self, url):
        self._nav(1)
        self.info_title.setText("加载中..."); self.info_genres.setText("")
        self.info_desc.setText(""); self.cover_label.setPixmap(QPixmap())
        self.cover_label.setText("Loading..."); self.ch_table.setRowCount(0)
        self.dl_btn.setEnabled(False); self.ch_stats.setText("")
        self.info_source.setText(f"来源: {self.current_source.name}")
        self._set_status("加载漫画信息...")

        w = InfoWorker(self.current_source, url)
        w.finished.connect(self._on_detail_loaded)
        w.error.connect(lambda e: (self.info_title.setText("加载失败"),
                                    self._set_status(f"失败: {e}")))
        self._workers.append(w); w.start()

    def _on_detail_loaded(self, info, chapters):
        self.current_info = info; self.current_chapters = chapters
        self.info_title.setText(info["title"])
        self.info_genres.setText(info.get("genres", ""))
        self.info_desc.setText((info.get("description", "") or "")[:200])
        self.info_source.setText(f"来源: {self.current_source.name}")

        # Favorite button state
        is_fav = self.favorites.is_favorited(info.get("url", ""))
        self.fav_btn.setText("- Unfavorite" if is_fav else "+ Favorite")

        # Cover
        if info.get("cover"):
            cw = CoverWorker(self.current_source, info["cover"])
            cw.finished.connect(lambda px: self.cover_label.setPixmap(
                px.scaled(220, 310, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                if not px.isNull() else self.cover_label.setText("无封面"))
            self._workers.append(cw); cw.start()

        self._render_chapters()
        self.dl_btn.setEnabled(len(chapters) > 0)
        if chapters:
            nums = [float(extract_chapter_number(c["title"])) for c in chapters
                    if extract_chapter_number(c["title"]).replace(".", "").isdigit()]
            if nums:
                self.range_from.setMaximum(int(max(nums)))
                self.range_to.setMaximum(int(max(nums)))
                self.range_to.setValue(int(max(nums)))
        self._set_status(f"已加载: {info['title']}")

    def _render_chapters(self):
        filt = self._chapter_filter
        chs = self.current_chapters
        if filt == "translated":
            chs = [c for c in chs if "raw" not in c["title"].lower()]
        elif filt == "raw":
            chs = [c for c in chs if "raw" in c["title"].lower()]

        if not self._chapter_sort_asc:
            chs = list(reversed(chs))

        self.ch_table.setRowCount(len(chs))
        for i, ch in enumerate(chs):
            is_raw = "raw" in ch["title"].lower()
            ch_num = extract_chapter_number(ch["title"])

            # Checkbox
            cb = QCheckBox(); cb.setChecked(True)
            cb.stateChanged.connect(self._update_ch_stats)
            cbw = QWidget(); cbl = QHBoxLayout(cbw); cbl.addWidget(cb)
            cbl.setAlignment(Qt.AlignCenter); cbl.setContentsMargins(0, 0, 0, 0)
            self.ch_table.setCellWidget(i, 0, cbw)

            self.ch_table.setItem(i, 1, QTableWidgetItem(f"#{ch_num}"))
            self.ch_table.setItem(i, 2, QTableWidgetItem(ch["title"]))
            # Tag
            tag = QLabel("Raw" if is_raw else "翻译")
            tag.setObjectName("rawTag" if is_raw else "transTag")
            tag.setAlignment(Qt.AlignCenter)
            self.ch_table.setCellWidget(i, 3, tag)
            self.ch_table.setItem(i, 4, QTableWidgetItem(ch.get("date", "")))
            # Store original index
            self.ch_table.item(i, 2).setData(Qt.UserRole, self.current_chapters.index(ch))

        self.ch_header.setText(f"章节列表 ({len(chs)} 章)")
        self._update_ch_stats()

    def _set_chapter_filter(self, val):
        self._chapter_filter = val; self._render_chapters()

    def _toggle_sort(self):
        self._chapter_sort_asc = not self._chapter_sort_asc; self._render_chapters()

    def _update_ch_stats(self):
        total = self.ch_table.rowCount(); checked = 0
        for i in range(total):
            w = self.ch_table.cellWidget(i, 0)
            if w and w.findChild(QCheckBox) and w.findChild(QCheckBox).isChecked():
                checked += 1
        self.ch_stats.setText(f"已勾选 {checked} / 共 {total} 话")

    def _select_all_chapters(self):
        for i in range(self.ch_table.rowCount()):
            w = self.ch_table.cellWidget(i, 0)
            if w: w.findChild(QCheckBox).setChecked(True)

    def _deselect_all(self):
        for i in range(self.ch_table.rowCount()):
            w = self.ch_table.cellWidget(i, 0)
            if w: w.findChild(QCheckBox).setChecked(False)

    def _invert_selection(self):
        for i in range(self.ch_table.rowCount()):
            w = self.ch_table.cellWidget(i, 0)
            if w:
                cb = w.findChild(QCheckBox)
                cb.setChecked(not cb.isChecked())

    def _range_select(self):
        lo, hi = self.range_from.value(), self.range_to.value()
        for i in range(self.ch_table.rowCount()):
            item = self.ch_table.item(i, 1)
            if item:
                try:
                    num = float(item.text().replace("#", ""))
                    w = self.ch_table.cellWidget(i, 0)
                    if w: w.findChild(QCheckBox).setChecked(lo <= num <= hi)
                except ValueError:
                    pass

    # ===================== FAVORITE LOGIC =====================
    def _toggle_favorite(self):
        url = self.current_info.get("url", "")
        if not url: return
        if self.favorites.is_favorited(url):
            self.favorites.remove(url); self.fav_btn.setText("+ Favorite")
        else:
            self.favorites.add(
                self.current_info.get("title", ""),
                url,
                self.current_info.get("cover", ""),
                self.current_source.name,
            )
            self.fav_btn.setText("- Unfavorite")
        self._refresh_favorites()

    def _refresh_favorites(self, group=None):
        if not hasattr(self, 'fav_table'): return
        g = group or self.fav_group_combo.currentText()
        items = self.favorites.get_all() if g in ("All", "全部") else self.favorites.get_by_group(g)
        self.fav_table.setRowCount(len(items))
        for i, item in enumerate(items):
            self.fav_table.setItem(i, 0, QTableWidgetItem(item["title"]))
            self.fav_table.setItem(i, 1, QTableWidgetItem(item.get("source", "")))
            # Group combo in cell
            gc = QComboBox(); gc.addItems(self.favorites.get_groups())
            gc.setCurrentText(item.get("group", ""))
            gc.currentTextChanged.connect(lambda ng, url=item["url"]: (
                self.favorites.update_group(url, ng)))
            self.fav_table.setCellWidget(i, 2, gc)
            self.fav_table.setItem(i, 3, QTableWidgetItem(item.get("added_at", "")))
            # Buttons
            bw = QWidget(); bl = QHBoxLayout(bw); bl.setContentsMargins(2, 2, 2, 2)
            vb = QPushButton("查看"); vb.setObjectName("smallBtn"); vb.setFixedHeight(26)
            vb.clicked.connect(lambda _, u=item["url"], s=item.get("source"):
                               self._fav_view(u, s))
            bl.addWidget(vb)
            db = QPushButton("✕"); db.setFixedSize(26, 26)
            db.setStyleSheet("color:#ef5350;border:none;font-weight:bold;")
            db.clicked.connect(lambda _, u=item["url"]: (
                self.favorites.remove(u), self._refresh_favorites()))
            bl.addWidget(db)
            self.fav_table.setCellWidget(i, 4, bw)

    def _fav_view(self, url, source_name):
        for s in self.sources:
            if s.name == source_name:
                self.current_source = s; break
        self._load_detail(url)

    def _import_favorites(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入收藏", "", "JSON (*.json)")
        if path:
            self.favorites.import_from(path)
            self._refresh_favorites()
            QMessageBox.information(self, "导入", "收藏夹已导入!")

    def _export_favorites(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出收藏", "favorites.json", "JSON (*.json)")
        if path:
            self.favorites.export_to(path)
            QMessageBox.information(self, "导出", f"已导出到: {path}")

    # ===================== DOWNLOAD LOGIC =====================
    def _connect_dl_signals(self):
        self.dl_manager.task_updated.connect(self._on_task_updated)
        self.dl_manager.task_log.connect(self._on_task_log)
        self.dl_manager.all_done.connect(self._on_all_dl_done)
        self.dl_manager.speed_updated.connect(
            lambda s: self.dl_speed.setText(f"Speed: {s:.1f} KB/s"))

    def _start_download(self):
        selected = []
        for i in range(self.ch_table.rowCount()):
            w = self.ch_table.cellWidget(i, 0)
            if w and w.findChild(QCheckBox).isChecked():
                orig_idx = self.ch_table.item(i, 2).data(Qt.UserRole)
                if orig_idx is not None:
                    selected.append(self.current_chapters[orig_idx])
        if not selected:
            QMessageBox.warning(self, "提示", "请至少勾选一个章节"); return

        # Check duplicates
        dd = self.config["download_dir"]
        safe_t = re.sub(r'[<>:"/\\|?*]', '_', self.current_info["title"])
        dupes = []
        for ch in selected:
            from download_manager import format_chapter_dir
            cn = extract_chapter_number(ch["title"])
            ir = "raw" in ch["title"].lower()
            dn = format_chapter_dir(cn, ir)
            if os.path.exists(os.path.join(dd, safe_t, dn)):
                dupes.append(ch["title"])
        if dupes:
            r = QMessageBox.question(self, "重复下载",
                f"以下 {len(dupes)} 章已存在:\n" +
                "\n".join(dupes[:5]) +
                ("\n..." if len(dupes) > 5 else "") +
                "\n\n是否覆盖?", QMessageBox.Yes | QMessageBox.No)
            if r == QMessageBox.No: return

        self._nav(2)
        self.dl_manager.clear()
        self.dl_manager.chapter_concurrency = self.ch_spin.value()
        self.dl_manager.image_concurrency = self.img_spin.value()
        self.dl_manager.add_tasks(selected, self.current_info["title"],
                                   self.current_source, dd)
        self.dl_progress.setMaximum(len(selected)); self.dl_progress.setValue(0)
        self.log_box.clear()
        self.log_box.append(f"[START] {self.current_info['title']} - {len(selected)} chapters")
        self.dl_status.setText("下载中...")

        # Render task table
        self.task_table.setRowCount(len(self.dl_manager.tasks))
        for i, t in enumerate(self.dl_manager.tasks):
            self.task_table.setItem(i, 0, QTableWidgetItem(t.chapter_title))
            self.task_table.setItem(i, 1, QTableWidgetItem(t.status.value))
            self.task_table.setItem(i, 2, QTableWidgetItem("0/0"))
            self.task_table.setItem(i, 3, QTableWidgetItem(""))
            pb = QPushButton("II"); pb.setFixedSize(30, 26)
            pb.clicked.connect(lambda _, idx=i: self._toggle_pause(idx))
            self.task_table.setCellWidget(i, 4, pb)
            cb = QPushButton("✕"); cb.setFixedSize(30, 26)
            cb.setStyleSheet("color:#ef5350;border:none;font-weight:bold;")
            cb.clicked.connect(lambda _, idx=i: self.dl_manager.cancel_task(idx))
            self.task_table.setCellWidget(i, 5, cb)

        self.dl_manager.start()

    def _toggle_pause(self, idx):
        t = self.dl_manager.tasks[idx]
        if t.status == TaskStatus.PAUSED:
            self.dl_manager.resume_task(idx)
        elif t.status in (TaskStatus.DOWNLOADING, TaskStatus.WAITING):
            self.dl_manager.pause_task(idx)

    def _cancel_all(self):
        self.dl_manager.stop_all()

    def _on_task_updated(self, idx):
        if idx >= self.task_table.rowCount(): return
        t = self.dl_manager.tasks[idx]
        self.task_table.item(idx, 1).setText(t.status.value)
        self.task_table.item(idx, 2).setText(f"{t.progress}/{t.total}")
        self.task_table.item(idx, 3).setText(f"{t.speed:.0f}KB/s" if t.speed > 0 else "")
        # Update pause button
        pb = self.task_table.cellWidget(idx, 4)
        if pb:
            if t.status == TaskStatus.PAUSED: pb.setText("▶")
            elif t.status == TaskStatus.DOWNLOADING: pb.setText("⏸")
        # Count completed
        done = sum(1 for t in self.dl_manager.tasks
                   if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED))
        self.dl_progress.setValue(done)

    def _on_task_log(self, msg):
        self.log_box.append(msg)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def _on_all_dl_done(self):
        self.dl_status.setText("🎉 全部完成!")
        self.dl_speed.setText("")
        self._set_status("下载完成")
        QMessageBox.information(self, "完成", "所有下载任务已完成!")

    # ===================== SETTINGS LOGIC =====================
    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择下载目录", self.config["download_dir"])
        if d: self.dir_input.setText(d)

    def _save_settings(self):
        self.config["download_dir"] = self.dir_input.text().strip()
        self.config["chapter_concurrency"] = self.ch_spin.value()
        self.config["image_concurrency"] = self.img_spin.value()
        pm = ["none", "http", "socks5"][self.proxy_mode.currentIndex()]
        self.config["proxy_mode"] = pm
        self.config["proxy_host"] = self.proxy_host.text().strip()
        self.config["proxy_port"] = self.proxy_port.value()
        self.config.save()
        # Apply proxy to sources
        proxies = self.config.get_proxy_dict()
        for s in self.sources:
            s.session.proxies = proxies or {}
        self._set_status("设置已保存")
        QMessageBox.information(self, "设置", "设置已保存!")

    def _check_health(self):
        for name, lbl in self.health_labels.items():
            lbl.setText("检测中...")
        w = HealthCheckWorker(self.sources)
        w.result.connect(self._on_health_result)
        self._workers.append(w); w.start()

    def _on_health_result(self, name, ok, ms):
        lbl = self.health_labels.get(name)
        if lbl:
            if ok:
                lbl.setText(f"✅ {ms}ms")
                lbl.setStyleSheet("color:#059669;font-weight:bold;")
            else:
                lbl.setText("❌ 不可用")
                lbl.setStyleSheet("color:#ef5350;font-weight:bold;")

    def _update_stats(self):
        dd = self.config["download_dir"]
        if os.path.exists(dd):
            manga_count = len([d for d in os.listdir(dd)
                              if os.path.isdir(os.path.join(dd, d))])
            total_size = 0
            for root, dirs, files in os.walk(dd):
                for f in files:
                    total_size += os.path.getsize(os.path.join(root, f))
            size_mb = total_size / (1024 * 1024)
            self.stats_label.setText(
                f"📊 已下载: {manga_count} 部漫画  |  "
                f"占用: {size_mb:.1f} MB  |  "
                f"收藏: {len(self.favorites.get_all())} 部"
            )
        else:
            self.stats_label.setText("📊 下载目录不存在")

    # ===================== CLOSE =====================
    def closeEvent(self, event):
        self._save_window()
        self.dl_manager.stop_all()
        for w in self._workers:
            if hasattr(w, 'quit'): w.quit()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MangaApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
