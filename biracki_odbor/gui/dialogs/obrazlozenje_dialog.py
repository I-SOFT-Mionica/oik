"""In-app editor for the обrazloženje template.

Replaces the previous "open obrazlozenje.json in Notepad" handoff —
lawyers shouldn't have to wrangle JSON braces and escape sequences.

UX shape:
  - One scrollable card per paragraph. Each card holds:
      • A QTextEdit for the paragraph's text in `**bold**` markdown form.
      • "Опционо" checkbox (corresponds to Paragraph.optional).
      • "Горе" / "Доле" / "Обриши" mini-buttons.
  - Add-paragraph button at the bottom.
  - Reset-to-seed button to recover the canonical legal text.
  - Save / Cancel at the very bottom.
  - Help bar at the top reminding the user of:
      • the `**bold**` syntax,
      • the available placeholders (`{rik_decision}`, `{municipality}`).

Save semantics: parse each text area through `parse_markdown_paragraph`
into Segment lists, then call `obrazlozenje.save(paragraphs)`. The
existing Phase 3 generator picks up changes on its next render() call
because `save()` invalidates the cache.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from biracki_odbor.gui.widgets.toggle_switch import ToggleSwitch

from biracki_odbor.config import obrazlozenje as obrazlozenje_mod


class _ParagraphCard(QFrame):
    """One editable paragraph + its controls. Owns no model; the dialog
    walks the layout at save-time to read text + flags out of each card."""

    def __init__(
        self,
        paragraph: obrazlozenje_mod.Paragraph,
        *,
        on_remove,
        on_move_up,
        on_move_down,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("ParagraphCard")
        self.paragraph_id = paragraph.id

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Top row: id label + mini-buttons.
        top = QHBoxLayout()
        id_label = QLabel(f"<b>id:</b> <code>{paragraph.id or '(нови)'}</code>")
        id_label.setTextFormat(Qt.RichText)
        top.addWidget(id_label)
        top.addStretch()
        self.cb_show = ToggleSwitch("Прикажи")
        self.cb_show.setChecked(not paragraph.optional)
        self.cb_show.setToolTip(
            "Укључи параграф у образложење. Искључени параграфи се "
            "не приказују у прегледу нити у финалном решењу."
        )
        self.cb_show.toggled.connect(lambda checked: self.editor.setVisible(checked))
        top.addWidget(self.cb_show)
        btn_up = QPushButton("▲")
        btn_up.setFixedWidth(28)
        btn_up.setToolTip("Помери горе")
        btn_up.clicked.connect(lambda: on_move_up(self))
        top.addWidget(btn_up)
        btn_down = QPushButton("▼")
        btn_down.setFixedWidth(28)
        btn_down.setToolTip("Помери доле")
        btn_down.clicked.connect(lambda: on_move_down(self))
        top.addWidget(btn_down)
        btn_remove = QPushButton("×")  # × — Latin-1 Supplement, always renderable
        btn_remove.setFixedWidth(28)
        btn_remove.setObjectName("DangerButton")
        btn_remove.setToolTip("Обриши параграф")
        btn_remove.clicked.connect(lambda: on_remove(self))
        top.addWidget(btn_remove)
        root.addLayout(top)

        # Text editor — render segments back to `**bold**` markdown form.
        self.editor = QPlainTextEdit()
        self.editor.setVisible(not paragraph.optional)
        self.editor.setPlaceholderText(
            'Текст параграфа. Користите **... ** за подебљане делове '
            'и {rik_decision} / {municipality} placeholder-е.'
        )
        self.editor.setPlainText(
            obrazlozenje_mod.render_paragraph_markdown(paragraph.segments)
        )
        # Reasonable initial height; user can stretch by resizing the dialog.
        self.editor.setMinimumHeight(80)
        root.addWidget(self.editor)

    def to_paragraph(self) -> obrazlozenje_mod.Paragraph:
        """Read the card back into a Paragraph (parses `**...**` to Segments)."""
        text = self.editor.toPlainText()
        segments = obrazlozenje_mod.parse_markdown_paragraph(text)
        return obrazlozenje_mod.Paragraph(
            id=self.paragraph_id,
            segments=segments,
            optional=not self.cb_show.isChecked(),
        )


class ObrazlozenjeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Уређивање текста образложења")
        self.resize(820, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Help bar + cheat-sheet button.
        help_row = QHBoxLayout()
        help_label = QLabel(
            "Свака картица је један параграф у образложењу."
            " Користите <b>**текст**</b> да означите подебљане делове."
            " Доступни placeholder-и: <code>{rik_decision}</code> и"
            " <code>{municipality}</code> — биће замењени стварним"
            " вредностима из Изборне конфигурације и ОИК поставки."
        )
        help_label.setTextFormat(Qt.RichText)
        help_label.setWordWrap(True)
        help_label.setObjectName("MutedLabel")
        help_row.addWidget(help_label, stretch=1)
        btn_cheat = QPushButton("?")
        btn_cheat.setFixedWidth(28)
        btn_cheat.setToolTip("Листа подржане синтаксе и placeholder-а")
        btn_cheat.clicked.connect(self._show_cheat_sheet)
        help_row.addWidget(btn_cheat)
        layout.addLayout(help_row)

        # Scrollable cards.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()
        self.scroll.setWidget(self._cards_host)
        layout.addWidget(self.scroll, stretch=1)

        # Bottom toolbar — add new paragraph + reset.
        bottom = QHBoxLayout()
        btn_add = QPushButton("+ Додај параграф")
        btn_add.clicked.connect(self._on_add)
        bottom.addWidget(btn_add)
        btn_reset = QPushButton("Врати на подразумевано")
        btn_reset.setToolTip(
            "Враћа канонски правни текст из програма."
            " Све корисничке измене ће бити изгубљене."
        )
        btn_reset.clicked.connect(self._on_reset_to_seed)
        bottom.addWidget(btn_reset)
        bottom.addStretch()
        layout.addLayout(bottom)

        # OK / Cancel.
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Сачувај")
        bb.button(QDialogButtonBox.Cancel).setText("Откажи")
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        # Populate from current state.
        for p in obrazlozenje_mod.load():
            self._append_card(p)

    # ── Cheat sheet ────────────────────────────────────────────────

    def _show_cheat_sheet(self) -> None:
        QMessageBox.information(
            self, "Синтакса образложења",
            "<h3>Подебљавање</h3>"
            "<p><code>**текст**</code> → <b>текст</b> у Word документу</p>"
            "<h3>Placeholder-и</h3>"
            "<p>Аутоматски се замењују при генерисању Решења:</p>"
            "<ul>"
            "<li><code>{rik_decision}</code> — број одлуке РИК-а</li>"
            "<li><code>{municipality}</code> — назив општине</li>"
            "<li><code>{dana_predlog}</code> — број дана пре избора за предлог</li>"
            "</ul>"
            "<h3>Параграфи</h3>"
            "<p>Свака картица је jedan параграф. Размак између картица постаје"
            " нови ред у образложењу. Параграфи означени као"
            " <i>Опционо</i> увек се рендерују — обришите картицу"
            " ако желите да је искључите за ове изборе.</p>",
        )

    # ── Card management ────────────────────────────────────────────

    def _append_card(self, paragraph: obrazlozenje_mod.Paragraph) -> None:
        card = _ParagraphCard(
            paragraph,
            on_remove=self._remove_card,
            on_move_up=self._move_card_up,
            on_move_down=self._move_card_down,
        )
        # Insert before the trailing stretch.
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

    def _cards(self) -> list[_ParagraphCard]:
        return [
            self._cards_layout.itemAt(i).widget()
            for i in range(self._cards_layout.count() - 1)  # skip the stretch
            if isinstance(self._cards_layout.itemAt(i).widget(), _ParagraphCard)
        ]

    def _on_add(self) -> None:
        new = obrazlozenje_mod.Paragraph(
            id=f"custom-{len(self._cards()) + 1}",
            segments=[obrazlozenje_mod.Segment("", bold=False)],
            optional=False,
        )
        self._append_card(new)
        # Scroll to bottom so the new card is visible.
        bar = self.scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _remove_card(self, card: _ParagraphCard) -> None:
        if QMessageBox.question(
            self, "Брисање параграфа",
            "Обрисати овај параграф? Сачувајте дијалог да трајно уклоните.",
        ) != QMessageBox.Yes:
            return
        self._cards_layout.removeWidget(card)
        card.deleteLater()

    def _move_card_up(self, card: _ParagraphCard) -> None:
        cards = self._cards()
        idx = cards.index(card)
        if idx == 0:
            return
        self._cards_layout.removeWidget(card)
        # Insert at position (idx - 1) among the cards; since the layout
        # also has the trailing stretch, this works correctly.
        self._cards_layout.insertWidget(idx - 1, card)

    def _move_card_down(self, card: _ParagraphCard) -> None:
        cards = self._cards()
        idx = cards.index(card)
        if idx >= len(cards) - 1:
            return
        self._cards_layout.removeWidget(card)
        self._cards_layout.insertWidget(idx + 1, card)

    def _on_reset_to_seed(self) -> None:
        if QMessageBox.question(
            self, "Врати на подразумевано",
            "Тренутни текст ће бити преписан стандардним правним"
            " образложењем из програма. Наставити?",
        ) != QMessageBox.Yes:
            return
        # Reset by clearing cards and repopulating from the in-code seed.
        while self._cards():
            card = self._cards()[0]
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        for p in obrazlozenje_mod.default_paragraphs():
            self._append_card(p)

    # ── Save ───────────────────────────────────────────────────────

    def _on_save(self) -> None:
        paragraphs = [c.to_paragraph() for c in self._cards()]
        # Drop entirely-empty paragraphs (no text in any segment).
        paragraphs = [
            p for p in paragraphs
            if any(s.text.strip() for s in p.segments)
        ]
        if not paragraphs:
            QMessageBox.warning(
                self, "Празно образложење",
                "Образложење не може да буде сасвим празно."
                " Додајте бар један параграф или притисните Откажи.",
            )
            return
        try:
            obrazlozenje_mod.save(paragraphs)
        except OSError as e:
            QMessageBox.critical(
                self, "Грешка при чувању",
                f"Не могу да упишем obrazlozenje.json: {e}",
            )
            return
        self.accept()
