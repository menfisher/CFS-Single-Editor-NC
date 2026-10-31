import base64
import json
import re
import tempfile
import unittest
from pathlib import Path

import fitz

from app.database import initialize_database, set_request_db_path
from app.routes.address_book import (
    _address_book_pdf_contact_preview,
    _address_book_pdf_fields_from_context,
)
from app.services.address_book_pdf_service import (
    _FIELD_SEPARATOR_CONTINUED_LABEL,
    _PAGE_FRAME_SIDE_INSET_PT,
    _field_separator_title_lines,
    _separator_elder_contact,
    _separator_elder_name,
    _separator_phone_text,
    _text_width,
    build_address_book_pdf,
)


_LAYOUT = {
    "book_title": "Test Book",
    "trim_width_in": 3.5,
    "trim_height_in": 5.5,
    "margin_left_in": 0.14,
    "margin_right_in": 0.14,
    "margin_top_in": 0.14,
    "margin_bottom_in": 0.14,
    "base_font_size_pt": 7,
    "title_font_size_pt": 12,
    "toc_font_size_pt": 9,
    "line_height": 1.2,
    "font_family": "Arial",
}


def _page_texts(pdf: bytes) -> list[str]:
    document = fitz.open(stream=pdf, filetype="pdf")
    return [page.get_text() for page in document]


def _tiny_cover_jpeg() -> tuple[str, int, int]:
    document = fitz.open()
    page = document.new_page(width=32, height=32)
    image = page.get_pixmap()
    payload = base64.b64encode(image.tobytes("jpeg")).decode("ascii")
    document.close()
    return f"data:image/jpeg;base64,{payload}", 32, 32


def _fields() -> list[dict]:
    return [
        {
            "name": "AL Central",
            "meetings": [
                {
                    "name": "Birmingham (GRAHAM)",
                    "home_last_name": "GRAHAM",
                    "contacts": [
                        {"name": "Ada Lovelace"},
                        {
                            "name": "GRAHAM, Mark & Stephanie",
                            "given_name": "Mark",
                            "family_name": "GRAHAM",
                            "mtg_home_elder_flag": "2",
                            "phones": [
                                {"value": "205-555-0000", "type": "home"},
                                {"value": "205-555-1212", "type": "mobile", "owner_given_name": "Mark"},
                                {"value": "205-555-9999", "type": "mobile", "owner_given_name": "Stephanie"},
                            ],
                        },
                    ],
                },
                {
                    "name": "MS S & AL Coast, New Orleans (GOODWIN)",
                    "home_last_name": "GOODWIN",
                    "contacts": [
                        {
                            "name": "GOODWIN, Jane",
                            "given_name": "Jane",
                            "family_name": "GOODWIN",
                            "mtg_home_elder_flag": "2",
                            "phones": [{"value": "228-555-7777", "type": "mobile"}],
                        },
                    ],
                },
                {
                    "name": "Opelika (MASK)",
                    "home_last_name": "MASK",
                    "contacts": [
                        {"name": "Alan Turing"},
                        {
                            "name": "MASK, John & Mary",
                            "given_name": "John",
                            "family_name": "MASK",
                            "mtg_home_elder_flag": "2",
                            "phones": [{"value": "334-555-3434", "type": "home"}],
                        },
                    ],
                },
            ],
        },
        {
            "name": "LA South",
            "meetings": [
                {
                    "name": "Lake Charles (SAVOY)",
                    "home_last_name": "SAVOY",
                    "contacts": [
                        {"name": "Grace Hopper"},
                        {
                            "name": "SAVOY, James",
                            "given_name": "James",
                            "family_name": "Savoy",
                            "mtg_home_elder_flag": "2",
                            "phones": [
                                {"value": "337-555-1111", "type": "work"},
                                {"value": "337-555-5656", "type": "cell"},
                            ],
                        },
                    ],
                },
            ],
        },
    ]


def _build(settings: dict, fields: list[dict] | None = None, **kwargs) -> bytes:
    defaults = {"meeting_page_mode": "one_meeting", "include_bible_study_union_info": 0}
    defaults.update(settings)
    return build_address_book_pdf(
        fields=_fields() if fields is None else fields,
        meeting_preview_sections=[],
        settings=defaults,
        layout=_LAYOUT,
        print_order_mode="alphabetical",
        print_order_json="",
        **kwargs,
    )


def _home_and_elder_picker_fields() -> list[dict]:
    return [
        {
            "name": "AL Central",
            "meetings": [
                {
                    "name": "Birmingham",
                    "contacts": [
                        {
                            "name": "HOME, Alice",
                            "given_name": "Alice",
                            "family_name": "HOME",
                            "mtg_home_elder_flag": "1",
                            "phones": [
                                {
                                    "value": "205-555-0001",
                                    "type": "mobile",
                                    "owner_given_name": "Alice",
                                }
                            ],
                        },
                        {
                            "name": "ELDER, Bob",
                            "given_name": "Bob",
                            "family_name": "ELDER",
                            "mtg_home_elder_flag": "2",
                            "phones": [
                                {
                                    "value": "205-555-0002",
                                    "type": "mobile",
                                    "owner_given_name": "Bob",
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    ]


def _overflow_field(name: str, meeting_count: int = 40) -> dict:
    meetings = []
    for index in range(meeting_count):
        meetings.append(
            {
                "name": f"Meeting {index:02d}",
                "contacts": [
                    {
                        "name": f"ELDER, Person{index:02d}",
                        "given_name": f"Person{index:02d}",
                        "family_name": "ELDER",
                        "mtg_home_elder_flag": "2",
                        "phones": [
                            {
                                "value": f"336-555-{index:04d}",
                                "type": "mobile",
                                "owner_given_name": f"Person{index:02d}",
                            }
                        ],
                    },
                    {"name": f"Visitor {index:02d}"},
                ],
            }
        )
    return {"name": name, "meetings": meetings}


def _separator_title_lines(page) -> list[dict]:
    lines: list[dict] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(span.get("text", "") for span in spans).strip()
            y0 = min(span["bbox"][1] for span in spans)
            if y0 > 70:
                continue
            x0 = min(span["bbox"][0] for span in spans)
            x1 = max(span["bbox"][2] for span in spans)
            lines.append({"text": text, "x0": x0, "x1": x1, "y0": y0})
    lines.sort(key=lambda item: item["y0"])
    if len(lines) >= 2 and lines[1]["text"].strip() == _FIELD_SEPARATOR_CONTINUED_LABEL:
        return lines[:2]
    return lines[:1]


def _numbered_footers(texts: list[str]) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    pattern = re.compile(r"^(Table of Contents|.+?) - Page (\d+)\s*$", re.MULTILINE)
    for text in texts:
        matches = pattern.findall(text)
        if not matches:
            continue
        label, number = matches[-1]
        found.append((label.strip(), int(number)))
    return found


class FieldSeparatorPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        set_request_db_path(Path(self._tempdir.name) / "app.sqlite3")
        initialize_database()

    def tearDown(self) -> None:
        set_request_db_path(None)
        self._tempdir.cleanup()

    def test_content_page_numbers_follow_toc_without_skipping(self) -> None:
        footers = _numbered_footers(_page_texts(_build({})))
        toc_count = sum(1 for label, _ in footers if label == "Table of Contents")
        self.assertGreaterEqual(toc_count, 1)
        content = [(label, number) for label, number in footers if label != "Table of Contents"]
        self.assertTrue(content)
        self.assertEqual(content[0][1], toc_count + 1)
        numbers = [number for _, number in footers]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_cover_does_not_skip_a_numbered_page(self) -> None:
        data, width, height = _tiny_cover_jpeg()
        footers = _numbered_footers(
            _page_texts(
                _build(
                    {},
                    cover_image_data=data,
                    cover_image_width=width,
                    cover_image_height=height,
                )
            )
        )
        toc_count = sum(1 for label, _ in footers if label == "Table of Contents")
        content = [(label, number) for label, number in footers if label != "Table of Contents"]
        self.assertEqual(content[0][1], toc_count + 1)
        numbers = [number for _, number in footers]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))

    def test_separator_page_lists_field_and_meetings_and_is_numbered(self) -> None:
        texts = _page_texts(_build({"field_separator_pages": 1}))
        footers = _numbered_footers(texts)
        toc_count = sum(1 for label, _ in footers if label == "Table of Contents")
        separator_pages = [
            text
            for text in texts
            if "Table of Contents" not in text
            and "Ada Lovelace" not in text
            and "Grace Hopper" not in text
            and "Index - Page" not in text
        ]
        self.assertTrue(separator_pages)
        first_separator = separator_pages[0]
        self.assertIn("AL Central", first_separator)
        self.assertIn("Birmingham", first_separator)
        self.assertIn("Opelika", first_separator)
        self.assertIn("MS S & AL Coast, New Orleans", first_separator)
        self.assertIn("Mark Graham", first_separator)
        self.assertIn("John Mask", first_separator)
        self.assertIn("Jane Goodwin", first_separator)
        self.assertNotIn("Stephanie", first_separator)
        self.assertNotIn("GRAHAM", first_separator)
        self.assertIn("205-555-1212", first_separator)
        self.assertNotIn("205-555-0000", first_separator)
        self.assertNotIn("205-555-9999", first_separator)
        self.assertIn("334-555-3434", first_separator)
        self.assertNotIn("Ada Lovelace", first_separator)
        self.assertRegex(first_separator, r"AL Central - Page \d+")
        content = [(label, number) for label, number in footers if label != "Table of Contents"]
        self.assertTrue(content)
        self.assertEqual(content[0][1], toc_count + 1)
        first_meeting = next(index for index, text in enumerate(texts) if "Ada Lovelace" in text)
        separator_index = next(index for index, text in enumerate(texts) if text == first_separator)
        self.assertGreater(first_meeting, separator_index)
        numbers = [number for _, number in footers]
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
        second = next(
            text
            for text in separator_pages
            if "LA South" in text and "Lake Charles" in text
        )
        self.assertIn("James Savoy", second)
        self.assertIn("337-555-5656", second)
        self.assertNotIn("337-555-1111", second)
        self.assertNotIn("Grace Hopper", second)
        self.assertRegex(second, r"LA South - Page \d+")

    def test_separator_page_aligns_meetings_elders_and_phones(self) -> None:
        document = fitz.open(stream=_build({"field_separator_pages": 1}), filetype="pdf")
        page = next(item for item in document if "Mark Graham" in item.get_text() and "Ada Lovelace" not in item.get_text())
        words = page.get_text("words")
        left_margin = (_LAYOUT["margin_left_in"] * 72) + _PAGE_FRAME_SIDE_INSET_PT
        right_margin = page.rect.width - (_LAYOUT["margin_right_in"] * 72) - _PAGE_FRAME_SIDE_INSET_PT
        title_top = min(word[1] for word in words if word[4] == "AL" or word[4] == "Central")
        self.assertAlmostEqual(title_top, 0.375 * 72, delta=14)
        birmingham = next(word for word in words if word[4] == "Birmingham")
        opelika = next(word for word in words if word[4] == "Opelika")
        self.assertAlmostEqual(birmingham[0], left_margin, delta=2)
        self.assertAlmostEqual(opelika[0], left_margin, delta=2)
        graham = next(word for word in words if word[4] == "Mark")
        mask = next(word for word in words if word[4] == "John")
        self.assertAlmostEqual(graham[0], mask[0], delta=2)
        self.assertGreater(graham[0], birmingham[0] + 4)
        self.assertGreater(graham[1], birmingham[1])
        graham_phone = next(word for word in words if "205-555-1212" in word[4])
        mask_phone = next(word for word in words if "334-555-3434" in word[4])
        self.assertAlmostEqual(graham_phone[2], right_margin, delta=3)
        self.assertAlmostEqual(mask_phone[2], right_margin, delta=3)
        self.assertAlmostEqual(graham_phone[1], graham[1], delta=2)
        digit_marks = [
            word
            for word in words
            if word[4].isdigit() and len(word[4]) <= 2 and word[1] < birmingham[1] + 80
        ]
        self.assertFalse(digit_marks)
        graham_dots = [
            word
            for word in words
            if set(word[4]) <= {"."} and len(word[4]) > 1 and abs(word[1] - graham_phone[1]) < 2
        ]
        self.assertTrue(graham_dots)
        self.assertLess(graham_phone[0] - max(word[2] for word in graham_dots), 6)
        sizes = [
            span["size"]
            for block in page.get_text("dict")["blocks"]
            if block.get("type") == 0
            for line in block.get("lines", [])
            for span in line.get("spans", [])
            if "Birmingham" in span.get("text", "") or "Mark Graham" in span.get("text", "")
        ]
        self.assertTrue(sizes)
        self.assertTrue(all(abs(size - _LAYOUT["toc_font_size_pt"]) < 0.6 for size in sizes))

    def test_meeting_pages_have_no_corner_page_marks(self) -> None:
        document = fitz.open(stream=_build({"field_separator_pages": 1}), filetype="pdf")
        meeting_page = next(item for item in document if "Ada Lovelace" in item.get_text())
        words = meeting_page.get_text("words")
        top_digits = [
            word
            for word in words
            if word[4].isdigit() and len(word[4]) <= 2 and word[1] < 40
        ]
        self.assertFalse(top_digits)

    def test_separator_pages_draw_a_margin_frame_around_the_text(self) -> None:
        document = fitz.open(stream=_build({"field_separator_pages": 1}), filetype="pdf")
        separator = next(
            item for item in document if "Mark Graham" in item.get_text() and "Ada Lovelace" not in item.get_text()
        )
        meeting_page = next(item for item in document if "Ada Lovelace" in item.get_text())
        left_edge = _LAYOUT["margin_left_in"] * 72
        right_edge = separator.rect.width - (_LAYOUT["margin_right_in"] * 72)
        top_edge = _LAYOUT["margin_top_in"] * 72

        def tall_verticals(page) -> list[float]:
            xs: list[float] = []
            for drawing in page.get_drawings():
                for item in drawing.get("items") or []:
                    if item[0] != "l":
                        continue
                    start, end = item[1], item[2]
                    if abs(start.x - end.x) < 0.6 and abs(start.y - end.y) > 80:
                        xs.append(start.x)
            return xs

        separator_xs = tall_verticals(separator)
        self.assertTrue(any(abs(value - left_edge) < 1.5 for value in separator_xs))
        self.assertTrue(any(abs(value - right_edge) < 1.5 for value in separator_xs))
        separator_ys = [
            drawing["rect"].y0
            for drawing in separator.get_drawings()
            if drawing.get("rect") is not None
        ]
        self.assertTrue(any(abs(value - top_edge) < 1.5 for value in separator_ys))
        birmingham = next(word for word in separator.get_text("words") if word[4] == "Birmingham")
        self.assertGreater(birmingham[0], left_edge + 3)
        self.assertLess(birmingham[2], right_edge - 3)
        self.assertFalse(tall_verticals(meeting_page))

    def test_separator_prefers_elder_over_meeting_home(self) -> None:
        meeting = _home_and_elder_picker_fields()[0]["meetings"][0]
        elder = _separator_elder_contact(meeting)
        self.assertEqual(_separator_elder_name(elder), "Bob Elder")
        self.assertEqual(_separator_phone_text(elder), "205-555-0002")

    def test_separator_falls_back_to_meeting_home_when_elder_is_blank(self) -> None:
        meeting = {
            "name": "Birmingham",
            "home_last_name": "HOME",
            "contacts": [
                {
                    "name": "HOME, Alice",
                    "given_name": "Alice",
                    "family_name": "HOME",
                    "mtg_home_elder_flag": "1",
                    "phones": [{"value": "205-555-0001", "type": "mobile"}],
                },
                {"name": "Ada Lovelace"},
            ],
        }
        elder = _separator_elder_contact(meeting)
        self.assertEqual(_separator_elder_name(elder), "Alice Home")
        self.assertEqual(_separator_phone_text(elder), "205-555-0001")

    def test_preview_path_prints_elder_not_meeting_home_on_separator(self) -> None:
        previewed = _address_book_pdf_fields_from_context(
            {"field_list_picker_json": json.dumps({"fields": _home_and_elder_picker_fields()})}
        )
        meeting = previewed[0]["meetings"][0]
        self.assertEqual(meeting["home_last_name"], "HOME")
        flags = [contact.get("mtg_home_elder_flag") for contact in meeting["contacts"]]
        self.assertIn("1", flags)
        self.assertIn("2", flags)
        texts = _page_texts(_build({"field_separator_pages": 1}, fields=previewed))
        separator = next(
            text
            for text in texts
            if "AL Central" in text
            and "Birmingham" in text
            and "Table of Contents" not in text
            and "HOME, Alice" not in text
        )
        self.assertIn("Bob Elder", separator)
        self.assertIn("205-555-0002", separator)
        self.assertNotIn("Alice Home", separator)
        self.assertNotIn("Alice", separator)
        self.assertNotIn("205-555-0001", separator)

    def test_contact_preview_keeps_elder_flag_and_phone_owner(self) -> None:
        previewed = _address_book_pdf_contact_preview(
            {
                "name": "ELDER, Bob",
                "given_name": "Bob",
                "family_name": "ELDER",
                "mtg_home_elder_flag": "2",
                "phones": [
                    {
                        "value": "205-555-0002",
                        "type": "mobile",
                        "owner_given_name": "Bob",
                    }
                ],
            }
        )
        self.assertEqual(previewed["mtg_home_elder_flag"], "2")
        self.assertEqual(previewed["given_name"], "Bob")
        self.assertEqual(previewed["family_name"], "ELDER")
        self.assertEqual(previewed["phones"][0]["owner_given_name"], "Bob")

    def test_long_continued_field_title_moves_continued_under_name(self) -> None:
        size = float(_LAYOUT["toc_font_size_pt"])
        font = str(_LAYOUT["font_family"])
        long_name = "NC Central Field/Greensboro High Point"
        short_name = "AL Central"
        frame_width = (_LAYOUT["trim_width_in"] * 72) - (
            (_LAYOUT["margin_left_in"] * 72 + _PAGE_FRAME_SIDE_INSET_PT) * 2
        )
        long_combined = f"{long_name} {_FIELD_SEPARATOR_CONTINUED_LABEL}"
        short_combined = f"{short_name} {_FIELD_SEPARATOR_CONTINUED_LABEL}"
        self.assertGreater(_text_width(long_combined, size, font, bold=True), frame_width)
        self.assertLessEqual(_text_width(short_combined, size, font, bold=True), frame_width)

        long_lines = _field_separator_title_lines(
            long_name,
            continued=True,
            size=size,
            max_width=frame_width,
            font_family=font,
        )
        self.assertGreaterEqual(len(long_lines), 2)
        self.assertEqual(long_lines[-1], _FIELD_SEPARATOR_CONTINUED_LABEL)
        self.assertEqual(" ".join(long_lines[:-1]), long_name)

        short_lines = _field_separator_title_lines(
            short_name,
            continued=True,
            size=size,
            max_width=frame_width,
            font_family=font,
        )
        self.assertEqual(short_lines, [short_combined])

    def test_overflow_separator_keeps_continued_on_its_own_line(self) -> None:
        long_name = "NC Central Field/Greensboro High Point"
        short_name = "AL Central"
        document = fitz.open(
            stream=_build(
                {"field_separator_pages": 1},
                fields=[_overflow_field(long_name), _overflow_field(short_name)],
            ),
            filetype="pdf",
        )
        long_continued = next(
            page
            for page in document
            if long_name in page.get_text()
            and _FIELD_SEPARATOR_CONTINUED_LABEL in page.get_text()
            and "Visitor" not in page.get_text()
        )
        short_continued = next(
            page
            for page in document
            if short_name in page.get_text()
            and _FIELD_SEPARATOR_CONTINUED_LABEL in page.get_text()
            and "Visitor" not in page.get_text()
        )
        long_titles = _separator_title_lines(long_continued)
        short_titles = _separator_title_lines(short_continued)
        self.assertGreaterEqual(len(long_titles), 2)
        self.assertEqual(long_titles[1]["text"].strip(), _FIELD_SEPARATOR_CONTINUED_LABEL)
        self.assertEqual(long_titles[0]["text"].strip(), long_name)
        name_mid = (long_titles[0]["x0"] + long_titles[0]["x1"]) / 2
        continued_mid = (long_titles[1]["x0"] + long_titles[1]["x1"]) / 2
        self.assertAlmostEqual(name_mid, continued_mid, delta=2)
        right_frame = long_continued.rect.width - (_LAYOUT["margin_right_in"] * 72)
        self.assertLess(long_titles[0]["x1"], right_frame - 2)
        self.assertLess(long_titles[1]["x1"], right_frame - 2)
        self.assertEqual(len(short_titles), 1)
        self.assertEqual(short_titles[0]["text"].strip(), f"{short_name} {_FIELD_SEPARATOR_CONTINUED_LABEL}")
