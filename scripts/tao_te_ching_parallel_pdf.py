#!/usr/bin/env python3
"""
Generate a one-page-per-chapter Tao Te Ching PDF with five translations in parallel columns.

The script reads the provided HTML sources, extracts the 81 chapter blocks from each one,
splits each chapter into a top and bottom half using a character target plus visual fit
checks, and writes a single PDF book in the fixed chapter order:

    38..81, then 1..37

The output is intended for the five HTML files shipped with this repository, but the
parsing logic is resilient to the anchor and line-break variations present in those files.
"""

from __future__ import annotations

import argparse
import html as html_lib
import io
import re
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, Paragraph


ROOT = Path(__file__).resolve().parents[1]

INPUT_FILES = [
    ROOT / "Tao Te Ching, English by Sanderson Beck - Terebess Asia Online (TAO).html",
    ROOT / "Tao Te Ching, English by Archie J. Bahm - Terebess Asia Online (TAO).html",
    ROOT / "Tao Te Ching by Anonymous - Terebess Asia Online (TAO).html",
    ROOT / "Tao Te Ching, English by Aleister Crowley - Terebess Asia Online (TAO).html",
    ROOT / "Das Tao Te King von George Cronk.html",
]

TRANSLATIONS = [
    "Sanderson Beck",
    "Archie J. Bahm",
    "Anonymous",
    "Aleister Crowley",
    "George Cronk",
]

CHAPTER_ORDER = list(range(38, 82)) + list(range(1, 38))

PAGE_W, PAGE_H = letter
MARGIN = 0.6 * inch
GUTTER = 0.12 * inch
COLUMN_COUNT = 5
TEXT_W = PAGE_W - (2 * MARGIN)
TEXT_H = PAGE_H - (2 * MARGIN)
COLUMN_W = (TEXT_W - (COLUMN_COUNT - 1) * GUTTER) / COLUMN_COUNT
SECTION_H = TEXT_H / 2.0

BODY_FONT = "Times-Roman"
BODY_SIZE = 10.0
BODY_LEADING = 12.0
HEADER_FONT = "Helvetica-Bold"
HEADER_SIZE = 9.5
HEADER_SMALL_SIZE = 7.0

SPLIT_RADIUS = 120
CONTINUATION_MARKER = "—"

CHAPTER_ANCHOR_RE = re.compile(
    r'<a\b[^>]*name\s*=\s*["\']?Kap(\d{1,2})["\']?[^>]*>',
    re.IGNORECASE,
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_chapter_segments(raw_html: str) -> dict[int, str]:
    """Return raw HTML segments keyed by chapter number."""
    matches = list(CHAPTER_ANCHOR_RE.finditer(raw_html))
    chapters: dict[int, str] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_html)
        chapters[number] = raw_html[start:end]
    return chapters


def strip_html_to_text(fragment: str) -> str:
    """Convert a chapter HTML fragment into normalized plain text."""
    fragment = re.sub(r"(?is)<script\b.*?</script>", " ", fragment)
    fragment = re.sub(r"(?is)<style\b.*?</style>", " ", fragment)
    fragment = fragment.replace("\r", "\n")
    fragment = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"(?i)</p\s*>", "\n\n", fragment)
    fragment = re.sub(r"(?i)<p\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"(?i)</div\s*>", "\n", fragment)
    fragment = re.sub(r"(?i)<div\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"(?i)</blockquote\s*>", "\n", fragment)
    fragment = re.sub(r"(?i)<blockquote\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"(?i)</center\s*>", "\n", fragment)
    fragment = re.sub(r"(?i)<center\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"(?i)<hr\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"(?i)</table\s*>", "\n", fragment)
    fragment = re.sub(r"(?i)<table\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"(?i)</tr\s*>", "\n", fragment)
    fragment = re.sub(r"(?i)<tr\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"(?i)</td\s*>", "\n", fragment)
    fragment = re.sub(r"(?i)<td\b[^>]*>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = html_lib.unescape(fragment).replace("\xa0", " ")

    lines: list[str] = []
    for raw_line in fragment.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            lines.append("")
            continue
        if line.lower() == "up":
            continue
        lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def chapter_text_for_number(raw_html: str, chapter_number: int) -> str:
    segments = extract_chapter_segments(raw_html)
    if chapter_number not in segments:
        raise ValueError(f"Missing chapter {chapter_number}")
    return strip_html_to_text(segments[chapter_number])


def to_paragraphs(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return parts if parts else ([text.strip()] if text.strip() else [])


def paragraph_markup(text: str) -> str:
    return html_lib.escape(text, quote=False).replace("\n", "<br/>")


def fit_flowables(paragraphs: Sequence[str], style: ParagraphStyle, frame_w: float, frame_h: float) -> bool:
    """Return True when the paragraphs fit inside the given frame."""
    tmp = canvas.Canvas(io.BytesIO(), pagesize=letter)
    frame = Frame(0, 0, frame_w, frame_h, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    flowables = [Paragraph(paragraph_markup(p), style) for p in paragraphs]
    remaining = list(flowables)
    frame.addFromList(remaining, tmp)
    return not remaining


def sentence_units(text: str) -> list[str]:
    """Split text into sentence-like units while preserving punctuation."""
    units: list[str] = []
    start = 0
    for match in re.finditer(r'[.!?]["\')\]]*\s+', text):
        end = match.end()
        units.append(text[start:end].strip())
        start = end
    tail = text[start:].strip()
    if tail:
        units.append(tail)
    return [unit for unit in units if unit]


def split_units(text: str) -> list[str]:
    units = sentence_units(text)
    if len(units) > 1:
        return units
    return [word for word in text.split() if word]


def take_tail(text: str) -> Tuple[str, str]:
    """Move the smallest sensible tail from a paragraph to the next section."""
    units = split_units(text)
    if len(units) <= 1:
        words = text.split()
        if len(words) <= 1:
            return "", text.strip()
        take = max(1, len(words) // 6)
        head = " ".join(words[:-take]).strip()
        tail = " ".join(words[-take:]).strip()
        return head, tail

    head = " ".join(units[:-1]).strip()
    tail = units[-1].strip()
    return head, tail


def take_head(text: str) -> Tuple[str, str]:
    """Move the smallest sensible head from a paragraph to the previous section."""
    units = split_units(text)
    if len(units) <= 1:
        words = text.split()
        if len(words) <= 1:
            return text.strip(), ""
        take = max(1, len(words) // 6)
        head = " ".join(words[:take]).strip()
        tail = " ".join(words[take:]).strip()
        return head, tail

    head = units[0].strip()
    tail = " ".join(units[1:]).strip()
    return head, tail


def natural_boundary_positions(text: str) -> list[tuple[int, int]]:
    """Return candidate split positions with priority and position."""
    candidates: list[tuple[int, int]] = []
    patterns = [
        (0, re.compile(r"\n\s*\n+")),
        (1, re.compile(r'[.!?]["\')\]]*\s+')),
        (2, re.compile(r"[,;:]\s+")),
        (3, re.compile(r"\s+")),
    ]
    for priority, pattern in patterns:
        for match in pattern.finditer(text):
            candidates.append((priority, match.end()))
    return candidates


def choose_split_position(text: str, target: int, radius: int = SPLIT_RADIUS) -> int:
    low = max(0, target - radius)
    high = min(len(text), target + radius)
    candidates = [cand for cand in natural_boundary_positions(text) if low <= cand[1] <= high]
    if candidates:
        candidates.sort(key=lambda item: (item[0], abs(item[1] - target), item[1]))
        return candidates[0][1]

    if 0 < target < len(text):
        return target
    return max(0, min(len(text), target))


def split_chapter_for_page(chapter_text: str, frame_w: float, frame_h: float) -> tuple[list[str], list[str]]:
    """Split a chapter into top and bottom paragraphs that fit their sections."""
    paragraphs = to_paragraphs(chapter_text)
    if not paragraphs:
        return [], []

    flat = "\n\n".join(paragraphs)
    target = round(len(flat) * 0.5)
    split_at = choose_split_position(flat, target)

    top_text = flat[:split_at].strip()
    bottom_text = flat[split_at:].strip()
    top = to_paragraphs(top_text)
    bottom = to_paragraphs(bottom_text)

    style = ParagraphStyle(
        "body",
        fontName=BODY_FONT,
        fontSize=BODY_SIZE,
        leading=BODY_LEADING,
        alignment=TA_LEFT,
        spaceAfter=3,
        splitLongWords=0,
    )

    # Refine the split until both halves fit.
    for _ in range(200):
        top_fits = fit_flowables(top, style, frame_w, frame_h)
        bottom_fits = fit_flowables(bottom, style, frame_w, frame_h)
        if top_fits and bottom_fits:
            break

        if not top_fits and top:
            head, tail = take_tail(top[-1])
            top.pop()
            if head:
                top.append(head + (f" {CONTINUATION_MARKER}" if tail else ""))
            if tail:
                bottom.insert(0, tail)
            continue

        if not bottom_fits and bottom:
            head, tail = take_head(bottom[0])
            bottom.pop(0)
            if head:
                top.append(head + (f" {CONTINUATION_MARKER}" if tail else ""))
            if tail:
                bottom.insert(0, tail)
            continue

        break

    if not top and bottom:
        head, tail = take_head(bottom[0])
        top = [head] if head else [bottom[0]]
        bottom = bottom[1:]
        if tail:
            bottom.insert(0, tail)

    return top, bottom


def chapter_number_order() -> list[int]:
    return CHAPTER_ORDER[:]


def load_all_chapters() -> list[dict[int, str]]:
    chapters_by_translation: list[dict[int, str]] = []
    for path in INPUT_FILES:
        raw = read_text(path)
        segments = extract_chapter_segments(raw)
        parsed = {number: strip_html_to_text(segment) for number, segment in segments.items()}
        chapters_by_translation.append(parsed)
    return chapters_by_translation


def make_body_style() -> ParagraphStyle:
    return ParagraphStyle(
        "body",
        fontName=BODY_FONT,
        fontSize=BODY_SIZE,
        leading=BODY_LEADING,
        alignment=TA_LEFT,
        spaceAfter=3,
        splitLongWords=0,
    )


def render_page(
    pdf: canvas.Canvas,
    chapter_number: int,
    per_translation: Sequence[tuple[str, list[str], list[str]]],
) -> None:
    left_x = MARGIN
    bottom_y = MARGIN
    top_y = MARGIN + SECTION_H
    top_label_y = PAGE_H - 0.19 * inch
    top_small_y = PAGE_H - 0.31 * inch
    section_line_y = MARGIN + SECTION_H
    body_style = make_body_style()

    for index, (translation, top_paragraphs, bottom_paragraphs) in enumerate(per_translation):
        x = left_x + index * (COLUMN_W + GUTTER)
        center_x = x + (COLUMN_W / 2.0)

        pdf.setFont(HEADER_FONT, HEADER_SIZE)
        pdf.drawCentredString(center_x, top_label_y, f"Chapter {chapter_number}")
        pdf.setFont("Helvetica", HEADER_SMALL_SIZE)
        pdf.drawCentredString(center_x, top_small_y, translation)

        top_frame = Frame(
            x,
            top_y,
            COLUMN_W,
            SECTION_H,
            leftPadding=2,
            rightPadding=2,
            topPadding=0,
            bottomPadding=4,
            showBoundary=0,
        )
        bottom_frame = Frame(
            x,
            bottom_y,
            COLUMN_W,
            SECTION_H,
            leftPadding=2,
            rightPadding=2,
            topPadding=4,
            bottomPadding=0,
            showBoundary=0,
        )

        top_flowables = [Paragraph(paragraph_markup(p), body_style) for p in top_paragraphs]
        bottom_flowables = [Paragraph(paragraph_markup(p), body_style) for p in bottom_paragraphs]
        top_frame.addFromList(top_flowables, pdf)
        bottom_frame.addFromList(bottom_flowables, pdf)

        pdf.setLineWidth(0.4)
        pdf.setStrokeColorRGB(0.55, 0.55, 0.55)
        pdf.line(x, section_line_y, x + COLUMN_W, section_line_y)

    pdf.setStrokeColorRGB(0.82, 0.82, 0.82)
    pdf.setLineWidth(0.3)
    pdf.line(MARGIN, section_line_y, PAGE_W - MARGIN, section_line_y)
    pdf.showPage()


def build_pdf(output_path: Path) -> None:
    chapters_by_translation = load_all_chapters()
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    pdf.setTitle("Tao Te Ching Parallel Translation")
    pdf.setAuthor("Copilot Task Agent")

    for chapter_number in chapter_number_order():
        page_data = []
        for translation, chapter_map in zip(TRANSLATIONS, chapters_by_translation):
            if chapter_number not in chapter_map:
                raise ValueError(f"{translation} is missing chapter {chapter_number}")
            chapter_text = chapter_map[chapter_number]
            top, bottom = split_chapter_for_page(chapter_text, COLUMN_W, SECTION_H)
            if not top and bottom:
                top = [bottom[0]]
                bottom = bottom[1:]
            page_data.append((translation, top, bottom))
        render_page(pdf, chapter_number, page_data)

    pdf.save()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Tao Te Ching five-translation parallel PDF.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=ROOT / "tao_te_ching_parallel.pdf",
        help="Output PDF path.",
    )
    args = parser.parse_args()
    build_pdf(args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
