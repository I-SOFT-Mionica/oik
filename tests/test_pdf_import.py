"""Tests for the PDF-import merge logic (pure Python, no Qt, no PDF)."""

from __future__ import annotations

from biracki_odbor.gui.dialogs.pdf_import_dialog import _merge_fragments, _n_cols


def _rows(n: int, n_cols: int = 3, *, header: list[str] | None = None) -> list[list[str]]:
    """Build n rows of n_cols cells. Row 0 is the header if provided."""
    out = []
    if header:
        out.append(header)
        for i in range(1, n):
            out.append([f"r{i}c{j}" for j in range(n_cols)])
    else:
        for i in range(n):
            out.append([f"r{i}c{j}" for j in range(n_cols)])
    return out


HEADER = ["А", "Б", "В"]


# ── _n_cols ───────────────────────────────────────────────────────────────────


def test_n_cols_basic() -> None:
    assert _n_cols([["a", "b"], ["c"]]) == 2


def test_n_cols_empty() -> None:
    assert _n_cols([]) == 0


# ── _merge_fragments — no merge cases ────────────────────────────────────────


def test_single_fragment_no_merge() -> None:
    frags = [(1, 1, _rows(5))]
    result = _merge_fragments(frags)
    assert len(result) == 1
    label, rows = result[0]
    assert "Страна 1" in label
    assert len(rows) == 5


def test_non_consecutive_pages_no_merge() -> None:
    frags = [
        (1, 1, _rows(5)),
        (3, 1, _rows(5)),   # page 3 — gap, not consecutive
    ]
    result = _merge_fragments(frags)
    # No merged entry (◆), just two individual entries.
    assert all("◆" not in lbl for lbl, _ in result)
    assert len(result) == 2


def test_different_col_counts_no_merge() -> None:
    frags = [
        (1, 1, _rows(5, n_cols=3)),
        (2, 1, _rows(5, n_cols=4)),   # different column count
    ]
    result = _merge_fragments(frags)
    assert all("◆" not in lbl for lbl, _ in result)
    assert len(result) == 2


# ── _merge_fragments — merge cases ───────────────────────────────────────────


def test_two_consecutive_pages_merged() -> None:
    frags = [
        (1, 1, _rows(10, header=HEADER)),
        (2, 1, _rows(8,  header=HEADER)),   # header repeats
    ]
    result = _merge_fragments(frags)
    merged = [(lbl, rows) for lbl, rows in result if "◆" in lbl]
    assert len(merged) == 1
    label, rows = merged[0]
    assert "1–2" in label
    # 10 rows from page 1 + 7 rows from page 2 (header dropped) = 17
    assert len(rows) == 17


def test_three_consecutive_pages_merged() -> None:
    frags = [
        (1, 1, _rows(10, header=HEADER)),
        (2, 1, _rows(10, header=HEADER)),
        (3, 1, _rows(6,  header=HEADER)),
    ]
    result = _merge_fragments(frags)
    merged = [(lbl, rows) for lbl, rows in result if "◆" in lbl]
    assert len(merged) == 1
    _, rows = merged[0]
    # 10 + 9 + 5 = 24  (each continuation drops its repeated header)
    assert len(rows) == 24


def test_merged_entry_comes_before_individual() -> None:
    frags = [
        (1, 1, _rows(5, header=HEADER)),
        (2, 1, _rows(5, header=HEADER)),
    ]
    result = _merge_fragments(frags)
    assert "◆" in result[0][0], "merged entry must be first"
    assert "Страна 1" in result[1][0]
    assert "Страна 2" in result[2][0]


def test_different_first_row_not_merged() -> None:
    """Continuation with a different first row is a new table — no merge."""
    p1 = [HEADER, ["a", "b", "c"], ["d", "e", "f"]]
    p2 = [["x", "y", "z"], ["1", "2", "3"]]   # different first row → different table
    frags = [(1, 1, p1), (2, 1, p2)]
    result = _merge_fragments(frags)
    assert all("◆" not in lbl for lbl, _ in result)
    assert len(result) == 2


def test_same_col_count_different_header_no_merge() -> None:
    """Two consecutive pages, same column count but different headers — no merge.

    This is the real-world case the fix targets: a PDF with multiple distinct
    tables (e.g. allocation by party on p.1, summary totals on p.2) where
    both happen to be 5-column tables should NOT be glued together.
    """
    header_a = ["Странка", "Листа", "Гласови", "Мандати", "Напомена"]
    header_b = ["Ред.бр.", "Назив", "Укупно", "Освојено", "Одбијено"]
    p1 = [header_a, ["СНС", "1", "12000", "5", ""], ["СПС", "2", "4000", "2", ""]]
    p2 = [header_b, ["1", "СНС", "5", "4", "1"], ["2", "СПС", "2", "2", "0"]]
    frags = [(1, 1, p1), (2, 1, p2)]
    result = _merge_fragments(frags)
    assert all("◆" not in lbl for lbl, _ in result)
    assert len(result) == 2


def test_two_separate_tables_same_page_not_merged() -> None:
    """Two tables on the same page with different tbl_idx should not merge."""
    frags = [
        (1, 1, _rows(5, header=HEADER)),
        (1, 2, _rows(3, header=HEADER)),   # tbl 2 on page 1
    ]
    result = _merge_fragments(frags)
    # Same page — not consecutive — no merge.
    assert all("◆" not in lbl for lbl, _ in result)


def test_partial_merge_with_unrelated_table() -> None:
    """Pages 1+2 merge; page 3 has a different-column table — stays separate."""
    frags = [
        (1, 1, _rows(10, n_cols=5, header=["A", "B", "C", "D", "E"])),
        (2, 1, _rows(8,  n_cols=5, header=["A", "B", "C", "D", "E"])),
        (3, 1, _rows(4,  n_cols=2)),   # different column count
    ]
    result = _merge_fragments(frags)
    merged = [rows for lbl, rows in result if "◆" in lbl]
    individual = [lbl for lbl, _ in result if "◆" not in lbl]
    assert len(merged) == 1
    assert len(merged[0]) == 10 + 7  # 10 + (8-1 header dropped)
    assert len(individual) == 3  # p1, p2, p3 as individual entries
