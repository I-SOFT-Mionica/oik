"""Placeholder pages for sidebar sections that aren't implemented yet.

`Прошириен састав` and `Посматрачи` are on the pre-v1 wishlist (see
TODO.md §1 and §2). They appear in the sidebar so users see the planned
shape of the app, but click-through lands here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPage(QWidget):
    def __init__(self, title: str, description: str = "") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.setSpacing(16)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("TitleLabel")
        title_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_lbl)

        msg = QLabel(
            description or (
                "Биће доступно у каснијој верзији (пре-v1.0)."
                "\n\nТренутна верзија подржава само стални састав бирачких"
                " одбора. Проширени састав и посматрачи су у плану."
            )
        )
        msg.setObjectName("MutedLabel")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignCenter)
        layout.addWidget(msg)

        layout.addStretch(1)
