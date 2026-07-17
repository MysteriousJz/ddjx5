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
import unicodedata
import warnings
from pathlib import Path
from typing import Sequence

from reportlab.lib.enums import TA_LEFT
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
# Keep a fixed blank band between the upper and lower halves, matching the
# reference fixed-layout PDF.
MIDDLE_GAP = 0.42 * inch
SECTION_H = (TEXT_H - MIDDLE_GAP) / 2.0

BODY_FONT = "Times-Roman"
BODY_SIZE = 10.0
BODY_LEADING = 12.0
FONT_SIZE_ADJUSTMENT_FACTOR = 0.239
# Allow roughly ±23.9% size adjustment to keep each chapter balanced.
MIN_BODY_SIZE = BODY_SIZE * (1.0 - FONT_SIZE_ADJUSTMENT_FACTOR)
MAX_BODY_SIZE = BODY_SIZE * (1.0 + FONT_SIZE_ADJUSTMENT_FACTOR)
HEADER_FONT = "Helvetica-Bold"
HEADER_SIZE = 9.5
HEADER_SMALL_SIZE = 7.0

# Tolerance around the midpoint when choosing a natural split boundary.
SPLIT_RADIUS = 120
MAX_SPLIT_ITERATIONS = 200
FONT_SIZE_SEARCH_ITERATIONS = 12
SECTION_FILL_TARGET_RATIO = 0.618
TARGET_COMBINED_FILL_RATIO = SECTION_FILL_TARGET_RATIO * 2.0
# Large enough to measure wrapped paragraph heights without affecting layout.
MAX_LAYOUT_HEIGHT = 10_000
WORD_CHUNK_DIVISOR = 6
CONTINUATION_MARKER = "—"

CHAPTER_ANCHOR_RE = re.compile(
    r'<a\b[^>]*name\s*=\s*["\']?Kap(\d{1,2})["\']?[^>]*>',
    re.IGNORECASE,
)

# Replacement characters plus the ASCII control range that can appear in bad HTML extractions.
_INVALID_TEXT_RE = re.compile(r"[\uFFFD\u0000-\u0008\u000B\u000C\u000E-\u001F]")
_SENTENCE_BOUNDARY_RE = re.compile(r'[.!?]["\')\]]*\s+')


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
    fragment = _strip_tag_blocks(fragment, "script")
    fragment = _strip_tag_blocks(fragment, "style")
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


def _strip_tag_blocks(fragment: str, tag: str) -> str:
    """Remove an HTML tag block without relying on a risky regex tag filter."""
    lower = fragment.lower()
    open_tag = f"<{tag}"
    close_tag = f"</{tag}"
    search_from = 0
    while True:
        start = lower.find(open_tag, search_from)
        if start == -1:
            return fragment
        start_end = fragment.find(">", start)
        if start_end == -1:
            return fragment[:start]
        end = lower.find(close_tag, start_end + 1)
        if end == -1:
            return fragment[:start] + fragment[start_end + 1 :]
        end_end = fragment.find(">", end)
        if end_end == -1:
            return fragment[:start] + fragment[end + len(close_tag) :]
        fragment = fragment[:start] + fragment[end_end + 1 :]
        lower = fragment.lower()
        search_from = start


def sanitize_text(text: str) -> str:
    """Remove corrupted glyphs while preserving readable prose and diacritics."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    text = _INVALID_TEXT_RE.sub(" ", text)
    cleaned: list[str] = []
    for char in text:
        if char in "\n\r\t":
            cleaned.append(char)
            continue
        category = unicodedata.category(char)
        # L/N/P/Z/M are Letters, Numbers, Punctuation, Separators, and Marks.
        if category[0] in {"L", "N", "P", "Z", "M"}:
            cleaned.append(char)
        else:
            cleaned.append(" ")
    text = "".join(cleaned)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chapter_text_for_number(raw_html: str, chapter_number: int) -> str:
    segments = extract_chapter_segments(raw_html)
    if chapter_number not in segments:
        raise ValueError(f"Missing chapter {chapter_number}")
    return sanitize_text(strip_html_to_text(segments[chapter_number]))


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


def rendered_height(paragraphs: Sequence[str], style: ParagraphStyle, frame_w: float) -> float:
    """Measure the rendered height of paragraphs at a given width."""
    total = 0.0
    for paragraph in paragraphs:
        flowable = Paragraph(paragraph_markup(paragraph), style)
        _, height = flowable.wrap(frame_w, MAX_LAYOUT_HEIGHT)
        total += height
    return total


def cumulative_heights(paragraphs: Sequence[str], style: ParagraphStyle, frame_w: float) -> list[float]:
    total = 0.0
    heights: list[float] = []
    for paragraph in paragraphs:
        flowable = Paragraph(paragraph_markup(paragraph), style)
        _, height = flowable.wrap(frame_w, MAX_LAYOUT_HEIGHT)
        total += height
        heights.append(total)
    return heights


def sentence_units(text: str) -> list[str]:
    """Split text into sentence-like units while preserving punctuation."""
    units: list[str] = []
    start = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        end = match.end()
        units.append(text[start:end].strip())
        start = end
    tail = text[start:].strip()
    if tail:
        units.append(tail)
    return units


def split_units(text: str) -> list[str]:
    units = sentence_units(text)
    if len(units) > 1:
        return units
    return [word for word in text.split() if word]


def take_tail(text: str) -> tuple[str, str]:
    """Move the smallest sensible tail from a paragraph to the next section."""
    units = split_units(text)
    if len(units) <= 1:
        words = text.split()
        if len(words) <= 1:
            midpoint = max(1, len(text) // 2)
            return text[:midpoint].strip(), text[midpoint:].strip()
        take = max(1, len(words) // WORD_CHUNK_DIVISOR)
        head = " ".join(words[:-take]).strip()
        tail = " ".join(words[-take:]).strip()
        return head, tail

    head = " ".join(units[:-1]).strip()
    tail = units[-1].strip()
    return head, tail


def take_head(text: str) -> tuple[str, str]:
    """Move the smallest sensible head from a paragraph to the previous section."""
    units = split_units(text)
    if len(units) <= 1:
        words = text.split()
        if len(words) <= 1:
            midpoint = max(1, len(text) // 2)
            return text[:midpoint].strip(), text[midpoint:].strip()
        take = max(1, len(words) // WORD_CHUNK_DIVISOR)
        head = " ".join(words[:take]).strip()
        tail = " ".join(words[take:]).strip()
        return head, tail

    head = units[0].strip()
    tail = " ".join(units[1:]).strip()
    return head, tail


def style_for_size(font_size: float) -> ParagraphStyle:
    return ParagraphStyle(
        "body",
        fontName=BODY_FONT,
        fontSize=font_size,
        leading=font_size * 1.2,
        alignment=TA_LEFT,
        spaceAfter=3,
        splitLongWords=0,
    )


def natural_boundary_positions(text: str) -> list[tuple[int, int]]:
    """Return candidate split positions with priority and position."""
    candidates: list[tuple[int, int]] = []
    patterns = [
        (0, re.compile(r"\n\s*\n+")),
        (1, _SENTENCE_BOUNDARY_RE),
        (2, re.compile(r"[,;:]\s+")),
        (3, re.compile(r"\s+")),
    ]
    for priority, pattern in patterns:
        for match in pattern.finditer(text):
            candidates.append((priority, match.end()))
    # Prefer stronger boundaries first, then the one nearest the target, then the earliest.
    return candidates


def choose_split_position(text: str, target: int, radius: int = SPLIT_RADIUS) -> int:
    low = max(0, target - radius)
    high = min(len(text), target + radius)
    candidates = [cand for cand in natural_boundary_positions(text) if low <= cand[1] <= high]
    if candidates:
        # Sort by boundary strength first, then closeness to the target, then position.
        candidates.sort(key=lambda item: (item[0], abs(item[1] - target), item[1]))
        return candidates[0][1]

    if 0 < target < len(text):
        return target
    return max(0, min(len(text), target))


def chapter_units(chapter_text: str) -> list[str]:
    units: list[str] = []
    for paragraph in to_paragraphs(chapter_text):
        paragraph_units = split_units(paragraph)
        if paragraph_units:
            units.extend(paragraph_units)
    return units if units else [chapter_text.strip()]


def split_chapter_for_page(
    chapter_text: str,
    frame_w: float,
    frame_h: float,
    font_size: float,
) -> tuple[list[str], list[str]]:
    """Split a chapter into top and bottom sections that both render."""
    units = chapter_units(chapter_text)
    if len(units) == 1:
        head, tail = take_head(units[0])
        return ([head] if head else [units[0]], [tail] if tail else [])

    style = style_for_size(font_size)
    heights = cumulative_heights(units, style, frame_w)
    total_height = heights[-1]
    target = total_height / 2.0
    valid_splits: list[tuple[float, int]] = []
    for split_index in range(1, len(units)):
        top_height = heights[split_index - 1]
        bottom_height = total_height - top_height
        if top_height <= frame_h and bottom_height <= frame_h:
            valid_splits.append((abs(top_height - target), split_index))
    if valid_splits:
        _, split_index = min(valid_splits)
        return units[:split_index], units[split_index:]

    # Fallback: refine a midpoint split until it fits both halves.
    flat = "\n\n".join(to_paragraphs(chapter_text))
    target = round(len(flat) * 0.5)
    split_at = choose_split_position(flat, target)
    top = to_paragraphs(flat[:split_at].strip())
    bottom = to_paragraphs(flat[split_at:].strip())
    for _ in range(MAX_SPLIT_ITERATIONS):
        if top and bottom and fit_flowables(top, style, frame_w, frame_h) and fit_flowables(bottom, style, frame_w, frame_h):
            break
        if not top and bottom:
            head, tail = take_head(bottom[0])
            top = [head] if head else [bottom[0]]
            bottom = bottom[1:]
            if tail:
                bottom.insert(0, tail)
            continue
        if not bottom and top:
            head, tail = take_tail(top[-1])
            top.pop()
            if head:
                top.append(head + (f" {CONTINUATION_MARKER}" if tail else ""))
            if tail:
                bottom.insert(0, tail)
            continue
        if not fit_flowables(top, style, frame_w, frame_h) and top:
            head, tail = take_tail(top[-1])
            top.pop()
            if head:
                top.append(head + (f" {CONTINUATION_MARKER}" if tail else ""))
            if tail:
                bottom.insert(0, tail)
            continue
        if not fit_flowables(bottom, style, frame_w, frame_h) and bottom:
            head, tail = take_head(bottom[0])
            bottom.pop(0)
            if head:
                top.append(head + (f" {CONTINUATION_MARKER}" if tail else ""))
            if tail:
                bottom.insert(0, tail)
            continue
        break
    else:
        warnings.warn("Chapter split refinement reached the iteration limit without a clean fit.")
    if not bottom and top:
        head, tail = take_tail(top[-1])
        if tail:
            top[-1] = head
            bottom = [tail]
    return top, bottom


def chapter_number_order() -> list[int]:
    return CHAPTER_ORDER[:]


def load_all_chapters() -> list[dict[int, str]]:
    chapters_by_translation: list[dict[int, str]] = []
    for path in INPUT_FILES:
        raw = read_text(path)
        segments = extract_chapter_segments(raw)
        parsed = {number: sanitize_text(strip_html_to_text(segment)) for number, segment in segments.items()}
        chapters_by_translation.append(parsed)
    return chapters_by_translation


def make_body_style() -> ParagraphStyle:
    return style_for_size(BODY_SIZE)


def render_page(
    pdf: canvas.Canvas,
    chapter_number: int,
    per_translation: Sequence[tuple[str, float, list[str], list[str]]],
) -> None:
    left_x = MARGIN
    bottom_y = MARGIN
    top_y = MARGIN + SECTION_H + MIDDLE_GAP
    top_label_y = PAGE_H - 0.19 * inch
    top_small_y = PAGE_H - 0.31 * inch
    section_line_y = MARGIN + SECTION_H

    for index, (translation, font_size, top_paragraphs, bottom_paragraphs) in enumerate(per_translation):
        x = left_x + index * (COLUMN_W + GUTTER)
        center_x = x + (COLUMN_W / 2.0)
        body_style = style_for_size(font_size)

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
        pdf.line(x, section_line_y + MIDDLE_GAP, x + COLUMN_W, section_line_y + MIDDLE_GAP)

    pdf.showPage()


def build_pdf(output_path: Path) -> None:
    chapters_by_translation = load_all_chapters()
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    pdf.setTitle("Tao Te Ching Parallel Translation")
    pdf.setAuthor("Tao Te Ching Parallel Translation Generator")

    for chapter_number in chapter_number_order():
        page_data = []
        for translation, chapter_map in zip(TRANSLATIONS, chapters_by_translation):
            if chapter_number not in chapter_map:
                raise ValueError(f"{translation} is missing chapter {chapter_number}")
            chapter_text = chapter_map[chapter_number]
            units = chapter_units(chapter_text)
            size_low = MIN_BODY_SIZE
            size_high = MAX_BODY_SIZE
            target_total = SECTION_H * TARGET_COMBINED_FILL_RATIO

            def measure(size: float) -> float:
                return rendered_height(units, style_for_size(size), COLUMN_W)

            low_total = measure(size_low)
            high_total = measure(size_high)
            if target_total <= low_total:
                font_size = size_low
            elif target_total >= high_total:
                font_size = size_high
            else:
                low = size_low
                high = size_high
                font_size = high
                for _ in range(FONT_SIZE_SEARCH_ITERATIONS):
                    mid = (low + high) / 2.0
                    mid_total = measure(mid)
                    font_size = mid
                    if mid_total < target_total:
                        low = mid
                    else:
                        high = mid
            top, bottom = split_chapter_for_page(chapter_text, COLUMN_W, SECTION_H, font_size)
            page_data.append((translation, font_size, top, bottom))
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
