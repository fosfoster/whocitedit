"""Verify render.py's BIBTEX_TYPES table and bibtex_type() helper."""

import render


def test_bibtex_types_table_entries():
    assert render.BIBTEX_TYPES["book"] == "@book"
    assert render.BIBTEX_TYPES["dissertation"] == "@phdthesis"
    assert render.BIBTEX_TYPES["conference-paper"] == "@inproceedings"


def test_bibtex_type_known_types():
    assert render.bibtex_type("book") == "@book"
    assert render.bibtex_type("dissertation") == "@phdthesis"
    assert render.bibtex_type("conference-paper") == "@inproceedings"


def test_bibtex_type_falls_back_to_misc():
    assert render.bibtex_type("unknown-type") == "@misc"
    assert render.bibtex_type(None) == "@misc"


if __name__ == "__main__":
    test_bibtex_types_table_entries()
    test_bibtex_type_known_types()
    test_bibtex_type_falls_back_to_misc()
    print("ok")
