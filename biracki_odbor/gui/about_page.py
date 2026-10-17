"""О апликацији + Упутство page.

Layout (О апликацији tab):
  Left column  — Hero (icon + version + update checker + changelog), Лиценца, Контакт
  Right column — О програму (mission + 2×3 feature grid)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QFormLayout, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSplitter, QStackedWidget, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from biracki_odbor import __version__, _release_info
from biracki_odbor.updates import (
    DownloadWorker, LicensedManualChecker, UpdateInfo, manual_check_for_update,
)
from biracki_odbor.gui.worker import DEFAULT_STALL_TIMEOUT_SECONDS

log = logging.getLogger(__name__)

# ── Palette (mirrors design tokens) ──────────────────────────────────────────
_C = dict(
    primary="#2F5496", primary_hover="#3A66B0", primary_soft="#E8EEF8",
    workspace="#FFFFFF", secondary_bg="#F5F6FA",
    border="#C8CFE0", border_soft="#E2E6EF",
    text="#1F2A44", text_sec="#4A5468", text_muted="#8A92A6",
    success_bg="#E4F5E6", success_fg="#1F6F2F", success_bd="#B6D9BD",
    warn_bg="#FFF3D6", warn_fg="#8A5A00", warn_bd="#EAD08A",
)

# ── Changelog — add one entry per release (see memory: changelog process) ────
# Ordered newest-first. Only entries strictly newer than the CURRENTLY
# RUNNING version are ever shown (see _changelog_since below) — this is
# framed as "what you'd get by updating", not a permanent history, so
# once you're actually on a version, its own entry (and everything
# older) drops out of view.
_CHANGELOG: list[tuple[str, str, list[str]]] = [
    # (version, "D.M.YYYY.", [user-friendly bullets])
    ("0.77.2", "31.7.2026.", [
        "Лиценца: тест-лиценце се сада јасно означавају као „Тест лиценца“, не мешају се са стварном активном лиценцом",
    ]),
    ("0.77.1", "30.7.2026.", [
        "Проширени: број слота листе се више не мења када се нова листа накнадно региструје — спречава да већ поднети чланови буду приписани погрешној листи",
        "Увоз кандидата из Excel-а сада нуди додавање нових листа/кандидата уместо обавезне замене свих већ унетих",
    ]),
    ("0.77.0", "30.7.2026.", [
        "Проширени: шаблон за листе сада укључује већ унете листе и нуди падајуће листе за тип и ниво, ограничене на изборе конфигурисане за овај циклус",
        "Извоз кандидата сада отвара картицу Кандидати; картица Листе служи само као подлога за падајућу листу",
    ]),
    ("0.76.3", "30.7.2026.", [
        "Проширени: табела чланова у решењима више није празна, а тачка 1 сада исправно наводи проширени састав",
        "Проширени: чување Поставки избора више не брише датум и број седнице за проширени састав",
        "Проширени: подразумевани текст поруке при слању фајлова листама сада наводи проширени, а не стални састав",
        "Почетни екран сада остаје прикачен док се главни прозор потпуно не отвори",
    ]),
    ("0.76.2", "30.7.2026.", [
        "Проширени: образложење и правни основ решења сада наводе чланове закона за проширени састав уместо за стални",
        "При покретању апликације сада се приказује почетни екран уместо кратког празног прозора",
    ]),
    ("0.76.1", "29.7.2026.", [
        "Проширени: увезене пријаве листа сада се исправно уносе у збирну табелу",
        "Преведене преостале ознаке у Поставке ОИК → Систем",
    ]),
    ("0.76.0", "29.7.2026.", [
        "Проширени: збирна табела сада исправно приказује наслов Проширени уместо Стални",
        "Проширени: колоне у Корекцијама и Изменама сада исправно означене као Листа уместо Странка",
        "Отклоњена лажна грешка о непознатој функцији при сваком обједињавању проширеног састава",
        "Поставке ОИК → Систем реорганизоване у прегледне групе; ново дугме за пречицу до фасцикле извоза/увоза",
    ]),
    ("0.75.0", "28.7.2026.", [
        "Побољшана поузданост при генерисању Excel датотека са дугачким називима странака",
        "Назив листе при уносу у Учесницима сада подржава вишередан текст",
    ]),
    ("0.74.0", "28.7.2026.", [
        "Видите само ажурирања новија од ваше верзије",
        "Садржај 'Шта је ново' се ажурира са сервера без поновне инсталације",
    ]),
    ("0.73.1", "28.7.2026.", [
        "Заштита интегритета за стални састав, збирну табелу и начелников образац — препознавање и опоравак од измена насталих изван апликације",
        "Конвертор PDF докумената сада приказује ток посла уместо да делује заглављено",
        "Дугмад за одговор на е-пошту и извоз грешака при увозу пресељена у Фазу 2",
        "Отклоњен проблем где је покретање обједињавања за проширени састав остајало заглављено на 0%",
    ]),
    ("0.72.0", "14.7.2026.", [
        "Ново: начелник може званично да преузме непопуњене слотове након истека рока",
        "Уграђена матрица расподеле мандата са контролом квоте по листи, директно у апликацији",
        "Могућност подешавања подразумеване фасцикле за извоз и увоз докумената",
        "Поузданији проверавачи ажурирања и робустнији увоз расподеле",
    ]),
    ("0.67.1", "9.7.2026.", [
        "Поузданије праћење напретка при преузимању и инсталирању ажурирања",
        "Деинсталација сада уклања и податке проширеног састава и посматрача",
    ]),
    ("0.67.0", "9.7.2026.", [
        "Редизајн картице Избори — секције сада могу да се склопе ради прегледности",
        "Картица Измене сада служи само за преглед; подешавања за пријаву премештена су у Изборе",
        "Отклоњено пет мањих грешака у картицама Закони и Измене",
    ]),
    ("0.65.0", "8.7.2026.", [
        "Преведени преостали натписи у падајућим листама и наслову прозора",
    ]),
    ("0.64.0", "8.7.2026.", [
        "Довршен превод корисничког интерфејса на српски (ћирилица) након реорганизације подешавања избора",
    ]),
    ("0.63.0", "8.7.2026.", [
        "Поузданије преузимање ажурирања и исправљено проналажење превода у инсталираној верзији",
    ]),
    ("0.62.1", "8.7.2026.", [
        "Уклоњене непотребне ознаке датума и исправљено упутство за лозинку у подешавањима избора",
    ]),
    ("0.62.0", "8.7.2026.", [
        "Подешавања избора обједињена у мање, прегледније картице",
        "Ажурирања апликације сада могу да се преузму и инсталирају директно из апликације",
    ]),
    ("0.61.0", "7.7.2026.", [
        "Комплетан превод корисничког интерфејса на српски (ћирилица)",
        "Редизајнирана картица О апликацији са двоколонским распоредом",
    ]),
    ("0.60.1", "5.7.2026.", [
        "Додата претрага у прегледу свих чланова и исправљена ознака за измене",
    ]),
    ("0.60.0", "7.7.2026.", [
        "Потпуно нова картица О апликацији са прегледнијим двоколонским распоредом",
        "Увоз пријава из е-поште доступан и за проширени састав",
        "Побољшана поузданост у одређеним конфигурацијама поштанских клијената",
    ]),
]


def _version_tuple(v: str) -> tuple[int, ...]:
    """Parse 'X.Y.Z' into a comparable tuple.

    Only the LEADING digits of each dot-separated segment count (so
    "0-rc1" reads as 0, not 01) — a trailing pre-release suffix or
    malformed segment degrades to 0 rather than raising, so a version
    comparison glitch can't crash the About page.
    """
    parts = []
    for seg in v.split("."):
        digits = ""
        for ch in seg:
            if not ch.isdigit():
                break
            digits += ch
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _changelog_since(
    entries: list[tuple[str, str, list[str]]], installed_version: str,
) -> list[tuple[str, str, list[str]]]:
    """Entries strictly newer than `installed_version`.

    An operator on 0.60.0 sees every entry newer than that; an operator
    already on 0.72.0 sees only what shipped after 0.72.0 — never their
    own current version's entry or anything older.
    """
    installed = _version_tuple(installed_version)
    return [e for e in entries if _version_tuple(e[0]) > installed]


def _load_cached_changelog(path: Path) -> list[tuple[str, str, list[str]]]:
    """Best-effort read of the server-fetched changelog cache.

    Never raises — a missing/corrupt/unreadable cache just means the
    merge below falls back to the built-in `_CHANGELOG` list alone."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [
            (str(e["version"]), str(e["date"]), [str(b) for b in e["bullets"]])
            for e in raw.get("entries", [])
        ]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def _merge_changelog(
    local: list[tuple[str, str, list[str]]],
    remote: list[tuple[str, str, list[str]]],
) -> list[tuple[str, str, list[str]]]:
    """Merge the built-in list with server-fetched entries.

    Remote wins on a version collision — lets the blurb be corrected
    or expanded after release without shipping a new client build.
    Versions only in `local` (older releases predating this feature,
    or the running version before the server has caught up) are kept
    too. Result is sorted newest-first regardless of input order."""
    by_version = {v: (v, d, b) for v, d, b in local}
    for v, d, b in remote:
        by_version[v] = (v, d, b)
    return sorted(by_version.values(), key=lambda e: _version_tuple(e[0]), reverse=True)

# ── SVG icon paths (monoline, 24×24 viewBox) ─────────────────────────────────
_SVG = dict(
    doc=(
        '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
        '<path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>'
    ),
    law=(
        '<path d="M12 3v18"/><path d="M5 7h14"/>'
        '<path d="M5 7l-2 6a3 3 0 0 0 6 0z"/>'
        '<path d="M19 7l-2 6a3 3 0 0 0 6 0z"/>'
    ),
    pdf=(
        '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/>'
        '<path d="M14 3v6h6"/><path d="M8 15h2M8 12h2M14 15h2"/>'
    ),
    backup=(
        '<path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v5h-5"/>'
    ),
    mail=(
        '<rect x="3" y="5" width="18" height="14" rx="2"/>'
        '<path d="M3 7l9 6 9-6"/>'
    ),
    people=(
        '<circle cx="9" cy="8" r="3"/>'
        '<path d="M3 20a6 6 0 0 1 12 0"/>'
        '<path d="M16 6a3 3 0 0 1 0 6"/>'
        '<path d="M18 20a6 6 0 0 0-3-5.2"/>'
    ),
)

FEATURES: list[tuple[str, str, str]] = [
    ("doc",    "Генерисање решења о именовању",
               "Законски усклађена Word решења за стални, проширени и посматрачки ниво "
               "бирачких одбора, са потпуним аудит трагом свих накнадних измена."),
    ("law",    "Библиотека изборних закона",
               "Изборни закони и одлуке РИК-а уграђени у генерисање решења. "
               "Увек актуелни правни основи, доступни за претрагу у секцији Закони."),
    ("pdf",    "PDF → Excel конвертор",
               "Претвара дигиталне PDF пријаве у уредне Excel табеле "
               "са аутоматским препознавањем колона и ЈМБГ валидацијом."),
    ("backup", "Резервне копије",
               "Аутоматска дневна резервна копија са ротацијом. "
               "Ручни извоз на USB или спољни диск, са снимком тренутног стања "
               "пре сваког враћања."),
    ("mail",   "Интеграција са е-поштом",
               "Слање решења члановима и пријава странкама директно из програма "
               "— ваш мејл клијент отвара се са већ приложеним документима."),
    ("people", "Управљање саставима",
               "Увоз Excel пријава, агрегација чланова, детекција конфликата "
               "и акредитација посматрача са ЈМБГ валидацијом и контролом рокова."),
]

SUPPORT_EMAIL = "direktor@isoft.rs"


def _resources_root() -> Path:
    return Path(__file__).resolve().parent.parent / "resources"


def _svg_pixmap(key: str, box: int = 38, icon: int = 21,
                color: str = _C["primary"]) -> QPixmap:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{icon}" height="{icon}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.9" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f'{_SVG[key]}</svg>'
    ).encode()
    pm = QPixmap(box, box)
    pm.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg))
    p = QPainter(pm)
    offset = (box - icon) // 2
    from PySide6.QtCore import QRectF
    renderer.render(p, QRectF(offset, offset, icon, icon))
    p.end()
    return pm


def _hsep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _card(title: str = "", action: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    """Bordered card with optional header. Returns (frame, body_layout)."""
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame#card{{border:1px solid {_C['border']};border-radius:6px;"
        f"background:{_C['workspace']}}}"
    )
    frame.setObjectName("card")
    outer = QVBoxLayout(frame)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    if title:
        hdr = QFrame()
        hdr.setStyleSheet(
            f"QFrame{{border:none;border-bottom:1px solid {_C['border_soft']};"
            f"background:{_C['workspace']};border-radius:0}}"
        )
        hdr_row = QHBoxLayout(hdr)
        hdr_row.setContentsMargins(18, 11, 18, 11)
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color:{_C['text']};font-size:15px;font-weight:600;"
            f"border:none;background:transparent"
        )
        hdr_row.addWidget(lbl)
        hdr_row.addStretch()
        if action:
            hdr_row.addWidget(action)
        outer.addWidget(hdr)

    body = QWidget()
    body.setObjectName("_card_body")
    body.setStyleSheet("QWidget#_card_body{background:transparent;border:none}")
    body_lay = QVBoxLayout(body)
    body_lay.setContentsMargins(18, 16, 18, 16)
    body_lay.setSpacing(8)
    outer.addWidget(body)
    return frame, body_lay


def _def_row(label: str, value: str | QWidget, mono: bool = False) -> QHBoxLayout:
    """128 px right-aligned muted label + value. Mirrors DefRow from design."""
    row = QHBoxLayout()
    row.setSpacing(14)
    lbl = QLabel(label)
    lbl.setFixedWidth(128)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lbl.setStyleSheet(f"color:{_C['text_sec']};font-size:14px;border:none;background:transparent")
    row.addWidget(lbl)
    if isinstance(value, str):
        val = QLabel(value)
        if mono:
            val.setStyleSheet(
                f"font-family:Consolas,monospace;font-size:13px;"
                f"color:{_C['text']};border:none;background:transparent"
            )
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            val.setWordWrap(True)
        else:
            val.setStyleSheet(f"font-size:14px;color:{_C['text']};border:none;background:transparent")
        row.addWidget(val, stretch=1)
    else:
        row.addWidget(value, stretch=1)
    return row


def _pill(text: str, tone: str = "neutral") -> QLabel:
    palettes = {
        "info":    (_C["primary_soft"], _C["primary"],    "#BFD0EE"),
        "success": (_C["success_bg"],   _C["success_fg"], _C["success_bd"]),
        "warn":    (_C["warn_bg"],       _C["warn_fg"],    _C["warn_bd"]),
        "neutral": (_C["secondary_bg"], _C["text_sec"],   _C["border"]),
    }
    bg, fg, bd = palettes[tone]
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{fg};background:{bg};border:1px solid {bd};border-radius:999px;"
        f"padding:2px 10px;font-size:12px;font-weight:600"
    )
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return lbl


# ─────────────────────────────────────────────────────────────────────────────


class AboutPage(QWidget):
    tour_requested = Signal()

    def __init__(self, parent: QWidget | None = None, *, state=None) -> None:
        super().__init__(parent)
        self._state = state
        self._download_url: str = ""
        self._installer_url: str = ""
        self._download_worker: DownloadWorker | None = None
        self._download_timer: QTimer | None = None
        self._download_last_bytes = 0
        self._download_stall_since = 0.0
        self._checker = None
        self._changelog_open = False
        self._changelog_widget: QWidget | None = None
        self._changelog_worker = None
        self._changelog_thread = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(self._build_about_tab(), "О апликацији")
        tabs.addTab(self._build_guide_tab(), "Упутство")
        outer.addWidget(tabs)

        self._refresh_changelog_from_server()

    # ── Tab 1: О апликацији ───────────────────────────────────────────────

    def _build_about_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setObjectName("_about_inner")
        inner.setStyleSheet(f"QWidget#_about_inner{{background:{_C['secondary_bg']}}}")
        pad = QHBoxLayout(inner)
        pad.setContentsMargins(24, 20, 24, 20)
        pad.setSpacing(20)

        # ── Left column ──────────────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(18)

        left.addWidget(self._build_hero())
        left.addWidget(self._build_license_card())
        left.addWidget(self._build_diagnostics_card())
        left.addWidget(self._build_contact_card())
        left.addStretch()

        # ── Right column ─────────────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(0)
        right.addWidget(self._build_about_program_card())
        right.addStretch()

        pad.addLayout(left, stretch=1)
        pad.addLayout(right, stretch=1)

        scroll.setWidget(inner)
        return scroll

    # ── Hero card ─────────────────────────────────────────────────────────

    def _build_hero(self) -> QFrame:
        frame, body = _card()

        # ── Identity row ──
        id_row = QHBoxLayout()
        id_row.setSpacing(16)

        icon_lbl = QLabel()
        icon_path = _resources_root() / "icon.ico"
        if icon_path.exists():
            icon_lbl.setPixmap(QIcon(str(icon_path)).pixmap(QSize(64, 64)))
        icon_lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        icon_lbl.setStyleSheet("border:none;background:transparent")
        id_row.addWidget(icon_lbl)

        name_col = QVBoxLayout()
        name_col.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel("OIK — Бирачки одбор")
        title.setStyleSheet(
            f"font-size:20px;font-weight:600;color:{_C['primary']};"
            "border:none;background:transparent"
        )
        title_row.addWidget(title)
        title_row.addWidget(_pill(f"верзија {__version__}", "neutral"))
        title_row.addStretch()
        name_col.addLayout(title_row)

        sub = QLabel("Управљање бирачким одборима за општинске и градске изборне комисије.")
        sub.setStyleSheet(
            f"font-size:13px;color:{_C['text_sec']};border:none;background:transparent"
        )
        sub.setWordWrap(True)
        name_col.addWidget(sub)

        # Update checker row
        upd_row = QHBoxLayout()
        upd_row.setSpacing(10)
        self.btn_check = QPushButton("Провери ажурирање")
        self.btn_check.setObjectName("PrimaryButton")
        self.btn_check.clicked.connect(self._check_for_update)
        upd_row.addWidget(self.btn_check)
        self.btn_install = QPushButton("Преузми и инсталирај")
        self.btn_install.setObjectName("PrimaryButton")
        self.btn_install.setVisible(False)
        self.btn_install.clicked.connect(self._start_install)
        upd_row.addWidget(self.btn_install)
        self.btn_download = QPushButton("Преузми")
        self.btn_download.setObjectName("PrimaryButton")
        self.btn_download.setVisible(False)
        self.btn_download.clicked.connect(self._open_download_url)
        upd_row.addWidget(self.btn_download)
        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setStyleSheet(
            f"font-size:13px;color:{_C['success_fg']};font-weight:500;"
            "border:none;background:transparent"
        )
        upd_row.addWidget(self.lbl_update_status)
        upd_row.addStretch()
        name_col.addLayout(upd_row)

        # Progress row — hidden until a download is in progress
        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            f"QProgressBar{{border:1px solid {_C['border']};border-radius:6px;"
            f"background:{_C['secondary_bg']}}}"
            f"QProgressBar::chunk{{background:{_C['primary']};border-radius:5px}}"
        )
        prog_row.addWidget(self.progress_bar, stretch=1)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setVisible(False)
        self.lbl_progress.setStyleSheet(
            f"font-size:12px;color:{_C['text_muted']};border:none;background:transparent"
        )
        prog_row.addWidget(self.lbl_progress)
        name_col.addLayout(prog_row)

        id_row.addLayout(name_col, stretch=1)
        body.addLayout(id_row)

        # ── Changelog toggle ── only shown when there's something newer
        # than the currently running version to report (see
        # _changelog_since) — nothing to toggle open on an up-to-date
        # install, so the whole row + separator hide rather than show
        # an empty "Шта је ново" with nothing under it.
        from biracki_odbor import app_paths
        cached_remote = _load_cached_changelog(app_paths.changelog_cache_path())
        self._cl_entries = _changelog_since(_merge_changelog(_CHANGELOG, cached_remote), __version__)

        self._cl_sep = QFrame()
        self._cl_sep.setFrameShape(QFrame.Shape.HLine)
        self._cl_sep.setStyleSheet(f"color:{_C['border_soft']};border:none;border-top:1px solid {_C['border_soft']}")
        self._cl_sep.setVisible(bool(self._cl_entries))
        body.addWidget(self._cl_sep)

        self.btn_changelog = QPushButton()
        self.btn_changelog.setFlat(True)
        self.btn_changelog.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_changelog.setStyleSheet(
            f"text-align:left;padding:4px 0;font-size:14px;font-weight:600;"
            f"color:{_C['text']};border:none;background:transparent"
        )
        self.btn_changelog.setVisible(bool(self._cl_entries))
        self._update_changelog_button_text()
        self.btn_changelog.clicked.connect(self._toggle_changelog)
        body.addWidget(self.btn_changelog)

        self._changelog_widget = QWidget()
        self._changelog_widget.setStyleSheet("border:none;background:transparent")
        self._changelog_widget.setVisible(False)
        cl_lay = QVBoxLayout(self._changelog_widget)
        cl_lay.setContentsMargins(0, 6, 0, 0)
        cl_lay.setSpacing(14)
        self._changelog_layout = cl_lay
        self._rebuild_changelog_content()
        body.addWidget(self._changelog_widget)

        return frame

    def _update_changelog_button_text(self) -> None:
        arrow = "▾" if self._changelog_open else "▸"
        date = self._cl_entries[0][1] if self._cl_entries else ""
        show_hide = "Сакриј" if self._changelog_open else "Прикажи"
        self.btn_changelog.setText(f"{arrow}  Шта је ново · {date}          {show_hide}")

    def _toggle_changelog(self) -> None:
        self._changelog_open = not self._changelog_open
        self._changelog_widget.setVisible(self._changelog_open)
        self._update_changelog_button_text()

    def _rebuild_changelog_content(self) -> None:
        while self._changelog_layout.count():
            item = self._changelog_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for ver, date, notes in self._cl_entries:
            row = QHBoxLayout()
            row.setSpacing(14)
            row.setAlignment(Qt.AlignmentFlag.AlignTop)

            meta = QVBoxLayout()
            meta.setSpacing(2)
            vl = QLabel(ver)
            vl.setStyleSheet(
                f"font-family:Consolas,monospace;font-size:14px;font-weight:700;"
                f"color:{_C['text']};border:none;background:transparent"
            )
            meta.addWidget(vl)
            dl = QLabel(date)
            dl.setStyleSheet(
                f"font-size:12px;color:{_C['text_muted']};border:none;background:transparent"
            )
            meta.addWidget(dl)
            meta.addStretch()
            meta_w = QWidget()
            meta_w.setFixedWidth(90)
            meta_w.setStyleSheet("border:none;background:transparent")
            meta_w.setLayout(meta)
            row.addWidget(meta_w)

            notes_col = QVBoxLayout()
            notes_col.setSpacing(4)
            for note in notes:
                nl = QLabel(f"• {note}")
                nl.setWordWrap(True)
                nl.setStyleSheet(
                    f"font-size:13px;color:{_C['text_sec']};border:none;background:transparent"
                )
                notes_col.addWidget(nl)
            notes_w = QWidget()
            notes_w.setStyleSheet("border:none;background:transparent")
            notes_w.setLayout(notes_col)
            row.addWidget(notes_w, stretch=1)

            row_w = QWidget()
            row_w.setStyleSheet("border:none;background:transparent")
            row_w.setLayout(row)
            self._changelog_layout.addWidget(row_w)

    # ── License card ──────────────────────────────────────────────────────

    def _build_license_card(self) -> QFrame:
        if self._state is None:
            frame, body = _card("Лиценца")
            body.addWidget(QLabel("Лиценцирање није подешено."))
            return frame

        lic = self._state.license
        # The server has no formal test/production flag on a license --
        # `issued_to` is the only signal available client-side. A test
        # license (issued for internal QA, not a paying customer) must
        # not read as a real "Активна" license on the About page: the
        # exact-match check (not substring) avoids false-flagging a
        # real customer whose name happens to contain "test".
        is_test_license = lic.issued_to.strip().upper() == "TEST"
        if lic.mode.name == "LICENSED" and is_test_license:
            status_pill = _pill("● Тест лиценца", "warn")
        elif lic.mode.name == "LICENSED":
            status_pill = _pill("● Активна", "success")
        elif lic.mode.name == "DEMO":
            status_pill = _pill("● Демо", "warn")
        else:
            status_pill = _pill("Искључено", "neutral")

        frame, body = _card("Лиценца", status_pill)
        body.setSpacing(0)

        if lic.mode.name == "LICENSED":
            body.addLayout(_def_row("Издата за", lic.issued_to or "—"))
            body.addLayout(_def_row("Ажурирања до", lic.updates_until or "—"))
            body.addLayout(_def_row("Модули", ", ".join(lic.modules) if lic.modules else "Пун пакет"))
        elif lic.mode.name == "DEMO":
            reason_map = {
                "no_license_file": "Лиценца није активирана на овом рачунару.",
                "license_malformed": "Локална лиценца је оштећена.",
                "license_invalid_signature": "Потпис локалне лиценце није исправан.",
                "license_unreadable": "Локална лиценца није читљива.",
                "machine_mismatch": "Локална лиценца је издата за други рачунар.",
            }
            msg = QLabel(reason_map.get(lic.reason, "Демо режим активан."))
            msg.setWordWrap(True)
            msg.setStyleSheet(
                f"font-size:13px;color:{_C['warn_fg']};border:none;background:transparent"
            )
            body.addWidget(msg)
            if lic.issued_to:
                body.addLayout(_def_row("Издата за", lic.issued_to))

        body.addLayout(_def_row("Отисак машине", lic.machine_hid or "—", mono=True))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{_C['border_soft']};border:none;border-top:1px solid {_C['border_soft']};margin:6px 0")
        body.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_copy = QPushButton("Копирај HID")
        btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(lic.machine_hid or "")
        )
        btn_row.addWidget(btn_copy)
        if lic.mode.name == "DEMO":
            btn_act = QPushButton("Активирај лиценцу")
            btn_act.setObjectName("PrimaryButton")
            btn_act.clicked.connect(self._open_activation_dialog)
            btn_row.addWidget(btn_act)
        elif lic.mode.name == "LICENSED":
            btn_re = QPushButton("Поново активирај")
            btn_re.clicked.connect(self._open_activation_dialog)
            btn_row.addWidget(btn_re)
        btn_row.addStretch()
        body.addLayout(btn_row)

        return frame

    # ── Contact card ──────────────────────────────────────────────────────

    def _build_contact_card(self) -> QFrame:
        frame, body = _card("Контакт и подршка")

        icon_lbl = QLabel()
        icon_lbl.setPixmap(_svg_pixmap("mail"))
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setStyleSheet(
            f"background:{_C['primary_soft']};border-radius:8px;border:none"
        )
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        email_col = QVBoxLayout()
        email_col.setSpacing(1)
        hint = QLabel("Е-пошта за подршку")
        hint.setStyleSheet(
            f"font-size:12px;color:{_C['text_muted']};border:none;background:transparent"
        )
        email_col.addWidget(hint)
        email_lbl = QLabel(SUPPORT_EMAIL)
        email_lbl.setStyleSheet(
            f"font-family:Consolas,monospace;font-size:15px;font-weight:600;"
            f"color:{_C['primary']};border:none;background:transparent"
        )
        email_col.addWidget(email_lbl)

        contact_row = QHBoxLayout()
        contact_row.setSpacing(12)
        contact_row.addWidget(icon_lbl)
        contact_row.addLayout(email_col, stretch=1)
        btn_report = QPushButton("Пријави проблем")
        btn_report.setObjectName("PrimaryButton")
        btn_report.clicked.connect(self._open_support_draft)
        contact_row.addWidget(btn_report)
        body.addLayout(contact_row)

        note = QLabel(
            "iSoft — развој и одржавање. "
            "Дугме аутоматски отвара нацрт е-поруке са отиском машине и "
            "дневником апликације у прилогу."
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            f"font-size:12px;color:{_C['text_sec']};border:none;background:transparent;margin-top:6px"
        )
        body.addWidget(note)

        return frame

    def _build_diagnostics_card(self) -> QFrame:
        """Which TLS trust store this build actually ended up using, plus
        the installer link support hands out.

        The trust-store row is not decoration. The update download runs
        through `urllib`, whose CA source depends on whether certifi's
        cacert.pem survived PyInstaller packaging. When it does not, the
        app silently falls back to the Windows certificate store — which
        is exactly what rejects the server's chain on municipal PCs with
        stale root updates. Reading this row on a packaged build is how
        that gets verified, and it travels in the support e-mail.
        """
        from biracki_odbor.ssl_support import ca_bundle_status

        status = ca_bundle_status()
        pill = _pill("● У реду", "success") if status.is_bundled else _pill("● Резервно", "warn")
        frame, body = _card("Дијагностика", pill)
        body.setSpacing(0)

        trust = f"certifi {status.version} (уграђен)".strip() if status.is_bundled \
            else "системски (Windows)"
        body.addLayout(_def_row("Сертификати", trust))

        server = ""
        if self._state is not None:
            server = (self._state.app_settings.licensing_server_url or "").strip()
        body.addLayout(_def_row("Сервер", server or "—"))

        # Support's most-asked question is "send me the installer". The
        # server's download URL is public and resumable, so it can be
        # copied straight out of a running install — but it is only known
        # once a check has run, hence disabled rather than absent (a
        # button that appears later is harder to find than a greyed one).
        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self.btn_copy_link = QPushButton("Копирај линк за инсталацију")
        self.btn_copy_link.clicked.connect(self._copy_installer_link)
        row.addWidget(self.btn_copy_link)
        row.addStretch()
        body.addLayout(row)
        self._refresh_installer_link()

        if not status.is_bundled:
            note = QLabel(
                "Апликација користи системске сертификате. Ако преузимање"
                " ажурирања не успе, то је најчешћи узрок."
            )
            note.setWordWrap(True)
            note.setObjectName("MutedLabel")
            body.addWidget(note)

        return frame

    def _copy_installer_link(self) -> None:
        if not self._installer_url:
            return
        QApplication.clipboard().setText(self._installer_url)
        self.lbl_update_status.setText("Линк за инсталацију је копиран.")

    def _refresh_installer_link(self) -> None:
        """Keep the copy button in step with the last check's result."""
        button = getattr(self, "btn_copy_link", None)
        if button is None:
            return
        button.setEnabled(bool(self._installer_url))
        button.setToolTip(self._installer_url or "Доступно након провере ажурирања.")

    def _open_support_draft(self) -> None:
        from biracki_odbor import app_paths
        from biracki_odbor.integrations.email_client import (
            DraftSpec, any_available, create_drafts, EmailClientUnavailable,
        )

        from biracki_odbor.ssl_support import ca_bundle_status

        hid = self._state.license.machine_hid if self._state is not None else ""
        # Which trust store this machine used is otherwise unanswerable
        # without a remote session, and it is the first thing to check
        # when an update "finds a version but will not install it".
        ca = ca_bundle_status()
        trust = f"certifi {ca.version}" if ca.is_bundled else f"системски ({ca.detail})"
        body_text = (
            f"Верзија: {__version__}\n"
            f"Отисак машине: {hid}\n"
            f"Сертификати: {trust}\n\n"
            "Опис проблема:\n\n"
        )
        log_path = app_paths.log_dir() / "app.log"
        attachment = log_path if log_path.exists() else None

        spec = DraftSpec(
            to=SUPPORT_EMAIL,
            subject=f"OIK — пријава проблема (v{__version__})",
            body=body_text,
            attachment=attachment,
        )

        if any_available():
            try:
                create_drafts([spec], display_first=True)
                return
            except EmailClientUnavailable:
                pass

        import urllib.parse
        params = urllib.parse.urlencode(
            {"subject": spec.subject, "body": body_text}, quote_via=urllib.parse.quote,
        )
        QDesktopServices.openUrl(QUrl(f"mailto:{SUPPORT_EMAIL}?{params}"))

    # ── О програму card ───────────────────────────────────────────────────

    def _build_about_program_card(self) -> QFrame:
        frame, body = _card("О програму")

        mission = QLabel(
            "OIK аутоматизује цео животни циклус бирачких одбора — од увоза кандидатура "
            "и агрегације чланова, преко детекције конфликата, до генерисања законски "
            "усклађених решења за стални, проширени и посматрачки ниво — уз потпун "
            "ревизиони траг свих измена."
        )
        mission.setWordWrap(True)
        mission.setStyleSheet(
            f"font-size:14px;color:{_C['text_sec']};line-height:1.6;"
            "border:none;background:transparent;margin-bottom:10px"
        )
        body.addWidget(mission)

        grid_widget = QWidget()
        grid_widget.setStyleSheet("border:none;background:transparent")
        from PySide6.QtWidgets import QGridLayout
        grid = QGridLayout(grid_widget)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)

        for i, (icon_key, title, desc) in enumerate(FEATURES):
            cell = QFrame()
            cell.setStyleSheet(
                f"QFrame{{border:1px solid {_C['border_soft']};border-radius:6px;"
                f"background:{_C['secondary_bg']}}}"
            )
            cell_lay = QHBoxLayout(cell)
            cell_lay.setContentsMargins(13, 12, 13, 12)
            cell_lay.setSpacing(12)
            cell_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

            icon_box = QLabel()
            icon_box.setPixmap(_svg_pixmap(icon_key))
            icon_box.setFixedSize(38, 38)
            icon_box.setStyleSheet(
                f"background:{_C['primary_soft']};border-radius:8px;border:none"
            )
            icon_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell_lay.addWidget(icon_box)

            text_col = QVBoxLayout()
            text_col.setSpacing(3)
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet(
                f"font-size:14px;font-weight:600;color:{_C['text']};"
                "border:none;background:transparent"
            )
            title_lbl.setWordWrap(True)
            text_col.addWidget(title_lbl)
            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet(
                f"font-size:12px;color:{_C['text_sec']};border:none;background:transparent"
            )
            text_col.addWidget(desc_lbl)
            cell_lay.addLayout(text_col, stretch=1)

            grid.addWidget(cell, i // 2, i % 2)

        body.addWidget(grid_widget)
        return frame

    # ── Tab 2: Упутство ───────────────────────────────────────────────────

    def _build_guide_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)

        tour_row = QHBoxLayout()
        tour_row.setContentsMargins(12, 12, 12, 4)
        btn_tour = QPushButton("Покрени водич кроз програм")
        btn_tour.setObjectName("PrimaryButton")
        btn_tour.setToolTip(
            "Корак по корак кроз цео ток, на вашим подацима:"
            " РИК расподела → фајлови за странке → обједињавање → решења."
        )
        btn_tour.clicked.connect(self.tour_requested)
        tour_row.addWidget(btn_tour)
        tour_row.addStretch()
        lay.addLayout(tour_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        nav = QListWidget()
        nav.setObjectName("BorderedList")
        nav.setMinimumWidth(240)
        nav.setMaximumWidth(280)
        nav.setSpacing(2)

        stack = QStackedWidget()

        steps = [
            ("1. Почетак",             self._guide_setup()),
            ("2. Избори",              self._guide_elections()),
            ("3. Фајлови за странке",  self._guide_phase1()),
            ("4. Обједињавање",        self._guide_phase2()),
            ("5. Корекције",           self._guide_corrections()),
            ("6. Решења",              self._guide_phase3()),
            ("7. Измене",              self._guide_amendments()),
            ("8. Проширени састав",    self._guide_prosireni()),
            ("9. Посматрачи",          self._guide_observers()),
            ("10. Резервна копија",    self._guide_backup()),
        ]
        for title, page in steps:
            nav.addItem(QListWidgetItem(title))
            stack.addWidget(page)

        nav.currentRowChanged.connect(stack.setCurrentIndex)
        nav.setCurrentRow(0)

        splitter.addWidget(nav)
        splitter.addWidget(stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        lay.addWidget(splitter)
        return w

    @staticmethod
    def _css() -> str:
        return (
            "<style>"
            "body{font-family:Segoe UI,sans-serif;font-size:11pt;color:#1F2A44;margin:16px 24px}"
            "h2{color:#2F5496;margin-bottom:6px}"
            "h3{color:#333;margin-top:18px;margin-bottom:4px;"
            "border-bottom:1px solid #E2E6EF;padding-bottom:2px}"
            "ol,ul{margin-left:18px}"
            "li{margin-bottom:5px;line-height:1.5}"
            "code{background:#F0F2F7;padding:1px 4px;border-radius:3px;"
            "font-family:Consolas,monospace;font-size:10pt}"
            ".where{background:#E8EEF8;border-left:4px solid #2F5496;"
            "padding:6px 12px;margin:10px 0;border-radius:2px}"
            ".note{background:#FFF3D6;border-left:4px solid #E0A800;"
            "padding:6px 12px;margin:10px 0;border-radius:2px}"
            ".tip{background:#E4F5E6;border-left:4px solid #2E7D32;"
            "padding:6px 12px;margin:10px 0;border-radius:2px}"
            "p{margin:6px 0;line-height:1.5}"
            "</style>"
        )

    def _browser(self, html: str) -> QTextBrowser:
        b = QTextBrowser()
        b.setFrameShape(QFrame.Shape.NoFrame)
        b.setOpenExternalLinks(True)
        b.setHtml(self._css() + html)
        return b

    def _guide_setup(self) -> QTabWidget:
        t = QTabWidget()
        t.addTab(self._browser(
            "<h2>1а. Чаробњак за подешавање</h2>"
            "<p>Покреће се сам при првом покретању и тражи само оно што је неопходно.</p>"
            "<ol>"
            "<li><b>Комисија</b> — изаберите општину или град са листе. Шифра, падежи, пун назив "
            "комисије и АП Војводина попуњавају се сами; проверите их. Унесите име председника.</li>"
            "<li><b>Фасцикла за ваше фајлове</b> — овде иде све што програм извози.</li>"
            "<li><b>Бирачка места</b> — <b>Направи шаблон</b>, попуните Excel, сачувајте, па "
            "<b>Увези из Excel-а…</b>.</li>"
            "<li><b>Изборни циклус</b> — врста и датум избора.</li>"
            "</ol>"
            "<div class='tip'><b>Напомена:</b> Тип комисије (општинска, градска, градске општине) "
            "одређује се сам према изабраној општини и користи се у свим решењима.</div>"
        ), "Чаробњак")
        t.addTab(self._browser(
            "<h2>1б. Водич и пробни режим</h2>"
            "<p><b>Водич</b> затамни прозор и истакне само дугме које треба кликнути, корак по "
            "корак, на вашим подацима: РИК расподела &rarr; фајлови за странке &rarr; "
            "обједињавање &rarr; решења. Покреће се дугметом изнад овог упутства.</p>"
            "<p><b>Пробни (демо) режим</b> — без лиценце цео поступак ради, али само за прво "
            "бирачко место. У Обједињавању дугме <b>Попуни пробним подацима</b> попуњава "
            "фајлове странака измишљеним лицима.</p>"
        ), "Водич")
        return t

    def _guide_elections(self) -> QTabWidget:
        t = QTabWidget()
        t.addTab(self._browser(
            "<h2>2а. Изборни циклус</h2>"
            "<div class='where'><b>Где:</b> Избори &rarr; 1. Изборни циклус</div>"
            "<ol>"
            "<li>Датум и врсте избора. Рокови за предлоге рачунају се сами; можете их променити.</li>"
            "<li>Одлука РИК-а: број и датум.</li>"
            "<li><b>Увоз из РИК фајлова…</b> — учитава РИК-ову РАСПОДЕЛУ и сам проналази вашу "
            "општину: бирачка места, посланичке групе, квоте и ко предлаже које место.</li>"
            "<li>Посланичке групе: кратки и пуни називи, е-пошта и телефон.</li>"
            "<li><b>Сачувај поставке</b>.</li>"
            "</ol>"
            "<div class='note'><b>Нови изборни циклус…</b> прави резервну копију и почиње нови "
            "циклус; поставке комисије и бирачка места остају.</div>"
        ), "Изборни циклус")
        t.addTab(self._browser(
            "<h2>2б. Листе и члан РИК-а</h2>"
            "<div class='where'><b>Где:</b> Избори &rarr; 2. Листе</div>"
            "<p>Изборне листе и кандидати за проширени састав (може и увоз из Excel-а).</p>"
            "<div class='where'><b>Где:</b> Избори &rarr; 3. Члан РИК-а</div>"
            "<p>Чланови и заменици које у бирачке одборе именује РИК.</p>"
        ), "Листе")
        return t

    def _guide_phase1(self) -> QTextBrowser:
        return self._browser(
            "<h2>3. Фајлови за странке</h2>"
            "<div class='where'><b>Где:</b> Стални &rarr; 1. Странке</div>"
            "<ol>"
            "<li><b>Покрени</b> — по један закључан Excel фајл за сваку посланичку групу, са "
            "већ уписаним бирачким местима и функцијама. ЈМБГ се проверава већ при уносу.</li>"
            "<li><b>Пошаљи</b> — нацрти мејлова са фајлом у прилогу (Outlook или Thunderbird).</li>"
            "<li>Прегледајте и пошаљите нацрте из мејл клијента.</li>"
            "</ol>"
            "<div class='where'><b>Где:</b> Поставке ИК &rarr; 3. Систем (мејл клијент)</div>"
        )

    def _guide_phase2(self) -> QTextBrowser:
        return self._browser(
            "<h2>4. Обједињавање</h2>"
            "<div class='where'><b>Где:</b> Стални &rarr; 2. Обједињавање</div>"
            "<ol>"
            "<li>Увезите враћене фајлове: <b>Увези фајлове…</b> (са диска) или <b>Прими</b> "
            "(из поште — време пријема мејла памти се као време предаје).</li>"
            "<li><b>Покрени</b> — последње пријаве свих странака у збирну табелу, са грешкама.</li>"
            "<li><b>Састави повратни мејл…</b> — мејл странци са списком њених грешака.</li>"
            "</ol>"
            "<div class='note'><b>Важно:</b> Пријава после рока тражи вашу потврду. Фајлови са "
            "макроима или спољним везама се одбацују.</div>"
        )

    def _guide_corrections(self) -> QTabWidget:
        t = QTabWidget()
        t.addTab(self._browser(
            "<h2>5а. Конфликти</h2>"
            "<div class='where'><b>Где:</b> Стални &rarr; 3. Корекције &rarr; Конфликти</div>"
            "<p>Иста особа (исти ЈМБГ) коју предлаже више странака, или која је већ у "
            "проширеном саставу. Приказано је ко је први послао предлог; ви одлучујете ко остаје.</p>"
        ), "Конфликти")
        t.addTab(self._browser(
            "<h2>5б. Сви чланови и статус</h2>"
            "<div class='where'><b>Где:</b> Стални &rarr; 3. Корекције</div>"
            "<ul>"
            "<li><b>Сви чланови</b> — двоклик за измену; свака измена тражи напомену и бележи се.</li>"
            "<li><b>Деклинација места</b> — исправке падежа назива места.</li>"
            "<li><b>Статус</b> — стање по странкама; <b>Извези извештај о стању…</b>.</li>"
            "<li><b>Сачувај измене у збирну табелу</b> пре прелаза на решења.</li>"
            "</ul>"
        ), "Сви чланови")
        t.addTab(self._browser(
            "<h2>5в. Именовање начелника</h2>"
            "<div class='where'><b>Где:</b> Стални &rarr; 3. Корекције</div>"
            "<ol>"
            "<li>Кад прође рок: <b>Заустави пријем пријава</b>.</li>"
            "<li>Празна места попуњава начелник управе — Excel шаблон који се шаље и враћа, "
            "или ручно <b>Именуј</b>.</li>"
            "</ol>"
            "<div class='tip'><b>Напомена:</b> <b>Поново отвори пријем пријава</b> враћа корак назад.</div>"
        ), "Начелник")
        return t

    def _guide_phase3(self) -> QTabWidget:
        t = QTabWidget()
        t.addTab(self._browser(
            "<h2>6а. Генерисање</h2>"
            "<div class='where'><b>Где:</b> Стални &rarr; 4. Решења</div>"
            "<ol>"
            "<li>Лево: датум и број седнице, број решења, правни основ и образложење.</li>"
            "<li>Десно: преглед решења страна по страна. Изнад њега размак и проред — ако "
            "решење прелази на страну више, смањите размак.</li>"
            "<li><b>Покрени</b> — по један Word документ за свако бирачко место.</li>"
            "<li><b>Предато РИК-у</b> закључава решења; даље промене иду кроз Измене.</li>"
            "</ol>"
            "<div class='tip'><b>Напомена:</b> Ако сте нека решења већ мењали у Word-у, програм "
            "пита да ли да их пресними или задржи ваше измене.</div>"
        ), "Генерисање")
        t.addTab(self._browser(
            "<h2>6б. Слање члановима</h2>"
            "<div class='where'><b>Где:</b> Стални &rarr; 4. Решења &rarr; Пошаљи</div>"
            "<p>По један нацрт мејла за сваког члана који има е-пошту, са његовим решењем у "
            "прилогу. Нацрти се не шаљу сами — прегледајте их у мејл клијенту.</p>"
        ), "Слање члановима")
        return t

    def _guide_amendments(self) -> QTextBrowser:
        return self._browser(
            "<h2>7. Измене</h2>"
            "<p>Замена члана <i>после</i> предаје РИК-у добија засебно <b>решење о измени</b>.</p>"
            "<div class='where'><b>Где:</b> Стални &rarr; 5. Измене</div>"
            "<ol>"
            "<li>Измене унете у Корекцијама после предаје појављују се овде, по врстама: "
            "замена, исправка, престанак председника, престанак функције (члан 15).</li>"
            "<li>Изаберите ред и проверите податке и овлашћење.</li>"
            "<li><b>Генериши решење о измени…</b></li>"
            "</ol>"
            "<div class='tip'><b>Напомена:</b> Измене се нумеришу саме по бирачком месту.</div>"
        )

    def _guide_prosireni(self) -> QTextBrowser:
        return self._browser(
            "<h2>8. Проширени састав</h2>"
            "<div class='where'><b>Где:</b> Проширени састав (лева трака)</div>"
            "<p>Исти ток као стални састав (Листе, Обједињавање, Корекције, Решења, Измене), "
            "али предлоге дају подносиоци изборних листа (Избори &rarr; 2. Листе).</p>"
            "<ul>"
            "<li>Празна места су дозвољена — листа не мора да предложи за свако место.</li>"
            "<li>Исто лице не може бити у оба састава — види се у Конфликтима оба састава.</li>"
            "</ul>"
        )

    def _guide_observers(self) -> QTextBrowser:
        return self._browser(
            "<h2>9. Посматрачи</h2>"
            "<div class='where'><b>Где:</b> Посматрачи &rarr; 0. Легитимација</div>"
            "<p>Изглед легитимације: блокови и њихов редослед.</p>"
            "<div class='where'><b>Где:</b> Посматрачи &rarr; 1. Акредитација</div>"
            "<p>Организације и посматрачи (може увоз из Excel-а). ЈМБГ се проверава.</p>"
            "<div class='where'><b>Где:</b> Посматрачи &rarr; 2. Документи</div>"
            "<p><b>Генериши легитимације</b>, <b>Генериши збирну листу</b>, "
            "<b>Генериши листе по БМ</b>.</p>"
        )

    def _guide_backup(self) -> QTabWidget:
        t = QTabWidget()
        t.addTab(self._browser(
            "<h2>10а. Прављење резервне копије</h2>"
            "<p>Програм сам прави резервну копију једном дневно (фасцикла <code>backups</code>).</p>"
            "<div class='where'><b>Где:</b> Алати &rarr; Резервна копија</div>"
            "<ol>"
            "<li><b>Направи резервну копију</b>.</li>"
            "<li>Изаберите одредиште: USB, облак или мејл.</li>"
            "</ol>"
        ), "Прављење копије")
        t.addTab(self._browser(
            "<h2>10б. Враћање</h2>"
            "<div class='where'><b>Где:</b> Алати &rarr; Резервна копија</div>"
            "<ol>"
            "<li><b>Изабери .zip…</b> и прегледајте садржај копије.</li>"
            "<li><b>Врати из ове копије</b> — тренутно стање се пре тога сачува.</li>"
            "</ol>"
            "<div class='note'><b>Важно:</b> На новом рачунару изаберите враћање већ на првом "
            "екрану чаробњака за подешавање.</div>"
        ), "Враћање")
        return t

    # ── Server-hosted changelog (best-effort) ────────────────────────────

    def _refresh_changelog_from_server(self) -> None:
        """Background-fetch the server-hosted changelog so copy can be
        corrected/expanded post-release without shipping a new client
        build (see licensing/server_client.py:fetch_changelog).

        Silently no-ops with no `licensing_server_url` configured (dev
        builds) and silently falls back to the cached/built-in list on
        any failure — this is "what's new" marketing copy, never worth
        surfacing an error to the operator over."""
        if self._state is None:
            return
        server_url = self._state.app_settings.licensing_server_url
        if not server_url:
            return
        from biracki_odbor.gui.worker import start_worker
        from biracki_odbor.licensing.server_client import fetch_changelog
        self._changelog_worker, self._changelog_thread = start_worker(
            self, fetch_changelog, server_url, stall_timeout=15,
        )
        self._changelog_worker.finished.connect(self._on_changelog_fetched)
        self._changelog_worker.failed.connect(self._on_changelog_fetch_failed)

    def _on_changelog_fetched(self, entries: object) -> None:
        if not isinstance(entries, list) or not entries:
            return
        from biracki_odbor import app_paths
        try:
            payload = {"entries": [
                {"version": v, "date": d, "bullets": b} for v, d, b in entries
            ]}
            app_paths.changelog_cache_path().write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
            )
        except OSError as e:
            log.warning("failed to cache server changelog: %s", e)

        merged = _changelog_since(_merge_changelog(_CHANGELOG, entries), __version__)
        if merged == self._cl_entries:
            return
        self._cl_entries = merged
        self._cl_sep.setVisible(bool(self._cl_entries))
        self.btn_changelog.setVisible(bool(self._cl_entries))
        self._update_changelog_button_text()
        self._rebuild_changelog_content()

    def _on_changelog_fetch_failed(self, err: str) -> None:
        log.info("server changelog fetch failed, using cached/built-in list: %s", err)

    # ── Shared actions ────────────────────────────────────────────────────

    def _open_activation_dialog(self) -> None:
        from biracki_odbor import app_paths
        from biracki_odbor.gui.dialogs.activation_dialog import ActivationDialog
        from PySide6.QtWidgets import QDialog as _QD
        dlg = ActivationDialog(
            server_url=self._state.app_settings.licensing_server_url,
            license_dat_path=app_paths.license_dat_path(),
            machine_hid=self._state.license.machine_hid,
            parent=self,
        )
        if dlg.exec() == _QD.DialogCode.Accepted:
            self._state.reload_license()

    def _check_for_update(self) -> None:
        self.btn_check.setEnabled(False)
        self.btn_download.setVisible(False)
        self._download_url = ""
        self.lbl_update_status.setText("Провера у току…")
        self.lbl_update_status.setStyleSheet(
            f"font-size:13px;color:{_C['text_muted']};border:none;background:transparent"
        )
        if (
            self._state is not None
            and self._state.license.mode.name == "LICENSED"
            and self._state.app_settings.licensing_server_url
        ):
            from biracki_odbor import app_paths
            try:
                token = app_paths.license_dat_path().read_text(encoding="utf-8").strip()
            except OSError:
                token = ""
            self._checker = LicensedManualChecker(
                self._state.app_settings.licensing_server_url, token, self,
            )
            self._checker.finished.connect(self._on_check_finished)
            self._checker.status_text.connect(self._on_check_status)
            self._checker.token_refreshed.connect(self._state.reload_license)
            self._checker.start()
        else:
            self._checker = manual_check_for_update(self)
            self._checker.finished.connect(self._on_check_finished)
            # Without this a failed check arrives as finished(None) and
            # reads as "you have the latest version" — which is how the
            # certificate failure stayed invisible for months.
            self._checker.status_text.connect(self._on_check_status)

    def _on_check_finished(self, info: object) -> None:
        self.btn_check.setEnabled(True)
        if isinstance(info, UpdateInfo):
            self.lbl_update_status.setText(f"Доступно ажурирање: {info.latest}")
            self.lbl_update_status.setStyleSheet(
                f"font-size:13px;color:{_C['warn_fg']};font-weight:500;"
                "border:none;background:transparent"
            )
            if info.is_direct:
                self._installer_url = info.url
                self._refresh_installer_link()
                self._download_url = ""
                self.btn_install.setVisible(True)
                self.btn_download.setVisible(False)
            else:
                self._download_url = info.url
                self._installer_url = ""
                self._refresh_installer_link()
                self.btn_download.setVisible(True)
                self.btn_install.setVisible(False)
            log.info("manual update check: newer release %s available", info.latest)
        else:
            self.lbl_update_status.setText("● Имате најновију верзију")
            self.lbl_update_status.setStyleSheet(
                f"font-size:13px;color:{_C['success_fg']};font-weight:500;"
                "border:none;background:transparent"
            )
            self.btn_install.setVisible(False)
            self.btn_download.setVisible(False)
            log.info("manual update check: up to date")

    def _on_check_status(self, text: str) -> None:
        self.btn_check.setEnabled(True)
        self.lbl_update_status.setText(text)
        log.info("manual update check: %s", text)

    def notify_update_available(self, info: UpdateInfo) -> None:
        """Pre-populate update state from the startup checker."""
        self.lbl_update_status.setText(f"Доступно ажурирање: {info.latest}")
        self.lbl_update_status.setStyleSheet(
            f"font-size:13px;color:{_C['warn_fg']};font-weight:500;"
            "border:none;background:transparent"
        )
        if info.is_direct:
            self._installer_url = info.url
            self._refresh_installer_link()
            self._download_url = ""
            self.btn_install.setVisible(True)
            self.btn_download.setVisible(False)
        else:
            self._download_url = info.url
            self._installer_url = ""
            self._refresh_installer_link()
            self.btn_download.setVisible(True)
            self.btn_install.setVisible(False)

    def _stall_timeout_seconds(self) -> float:
        """Operator-configured timeout (Поставке ОИК → Систем), shared
        with gui/worker.py's stall detection. Falls back to the same
        180s default if no state is available."""
        if self._state is not None:
            return float(self._state.app_settings.worker_stall_timeout_seconds)
        return float(DEFAULT_STALL_TIMEOUT_SECONDS)

    def _start_install(self) -> None:
        if not self._installer_url:
            log.warning("install button clicked with no installer_url set")
            return
        log.info("starting installer download: %s", self._installer_url)
        self.btn_install.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.lbl_progress.setText("Преузимање…")
        self.lbl_progress.setVisible(True)
        self.lbl_update_status.setText("")
        from biracki_odbor.updates import cleanup_stale_installer_downloads
        cleanup_stale_installer_downloads()
        self._download_worker = DownloadWorker(self._installer_url, self)
        self._download_worker.start()
        log.info("download worker thread started, isRunning=%s", self._download_worker.isRunning())

        self._download_last_bytes = 0
        self._download_stall_since = time.monotonic()
        self._download_timer = QTimer(self)
        self._download_timer.setInterval(250)
        self._download_timer.timeout.connect(self._poll_download)
        self._download_timer.start()

    def _poll_download(self) -> None:
        worker = self._download_worker
        if worker is None:
            return

        done, total = worker.bytes_downloaded, worker.bytes_total
        if done != self._download_last_bytes:
            self._download_last_bytes = done
            self._download_stall_since = time.monotonic()
            self._on_download_progress(done, total)

        if not worker.isRunning():
            self._download_timer.stop()
            if worker.error:
                self._on_download_failed(worker.error)
            elif worker.result_path:
                self._on_download_finished(worker.result_path)
            else:
                self._on_download_failed("Преузимање је прекинуто.")
            return

        stall_timeout = self._stall_timeout_seconds()
        if stall_timeout and time.monotonic() - self._download_stall_since > stall_timeout:
            self._download_timer.stop()
            log.error(
                "download stalled: no progress for %ds at %d/%d bytes",
                int(stall_timeout), done, total,
            )
            self._on_download_failed("Преузимање је прекинуто — сервер не одговара.")

    def _on_download_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(int(done * 100 / total))
            self.lbl_progress.setText(
                f"{done / 1_048_576:.1f} MB / {total / 1_048_576:.1f} MB"
            )
        else:
            self.progress_bar.setMaximum(0)
            self.lbl_progress.setText(f"{done / 1_048_576:.1f} MB…")

    def _on_download_finished(self, path: str) -> None:
        import subprocess
        from PySide6.QtWidgets import QApplication
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)
        self.lbl_progress.setText("Покретање инсталера…")
        try:
            subprocess.Popen([path])
        except OSError as exc:
            self._on_download_failed(str(exc))
            return
        log.info("update installer launched: %s", path)
        QTimer.singleShot(800, QApplication.quit)

    def _on_download_failed(self, msg: str) -> None:
        self.progress_bar.setVisible(False)
        self.lbl_progress.setVisible(False)
        self.btn_install.setEnabled(True)
        self.btn_check.setEnabled(True)
        self.lbl_update_status.setText("Преузимање није успело.")
        self.lbl_update_status.setStyleSheet(
            "font-size:13px;color:#C62828;font-weight:500;"
            "border:none;background:transparent"
        )
        log.error("update download failed: %s", msg)
        from PySide6.QtWidgets import QMessageBox

        from biracki_odbor.updates import TLS_ERROR_MARKER
        if msg.startswith(TLS_ERROR_MARKER):
            # Naming the cause matters: the operator's next move is a
            # support call, and "certificate" points somewhere very
            # different from "check your internet connection".
            QMessageBox.warning(
                self,
                "Сертификат није прихваћен",
                "Овај рачунар не прихвата сертификат сервера, па"
                " преузимање ажурирања није успело.\n\n"
                "Најчешћи узрок су застарели корени сертификати на"
                " Windows-у. Инсталацију можете преузети ручно — линк"
                " копирајте дугметом у одељку Дијагностика.\n\n"
                f"Детаљи: {msg[len(TLS_ERROR_MARKER):]}",
            )
            return
        QMessageBox.warning(
            self,
            "Преузимање није успело",
            f"Преузимање инсталера није успело:\n{msg}\n\n"
            "Посетите GitHub Release страну и преузмите ручно.",
        )

    def _open_download_url(self) -> None:
        if self._download_url:
            QDesktopServices.openUrl(QUrl(self._download_url))
