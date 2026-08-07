#!/usr/bin/env python3
"""
Master Tao Te Ching build pipeline for every discovered translation.

Stages:
1. Auto-discover translation HTML files in the repository root.
2. Parse and validate each translation.
3. Export plain-text chapter files.
4. Generate Books 5-8 from translators not used in Books 1-4.
5. Generate mega chapter comparison files.
6. Write a summary report.
"""

from __future__ import annotations

import html as html_lib
import io
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, Paragraph

import build_all_tao as tao


ROOT = Path(__file__).resolve().parents[1]
TXT_EXPORT_DIR = ROOT / "txt_exports"
MEGA_CHAPTER_DIR = ROOT / "mega_chapters"
REPORT_PATH = ROOT / "build_report.txt"
LOG_PATH = ROOT / "build_all_translations.log"

PAGE_W, PAGE_H = letter
MARGIN = 0.55 * inch
HEADER_BAND = 0.42 * inch
TEXT_W = PAGE_W - (2 * MARGIN)
TEXT_H = PAGE_H - (2 * MARGIN) - HEADER_BAND

NUM_COLS = 5
GUTTER = 0.12 * inch
MIDDLE_GAP = 0.42 * inch
COLUMN_W = (TEXT_W - (NUM_COLS - 1) * GUTTER) / NUM_COLS
SECTION_H = (TEXT_H - MIDDLE_GAP) / 2.0

BODY_FONT = "Times-Roman"
BODY_SIZE = 10.0
MIN_BODY_SIZE = 8.0
MAX_BODY_SIZE = 11.0
BODY_LINE_FACTOR = 1.2
HEADER_FONT = "Helvetica-Bold"
HEADER_SIZE = 9.5
HEADER_SMALL_SIZE = 7.0
MAX_LAYOUT_HEIGHT = 10000
MAX_SPLIT_ITERATIONS = 200
WORD_CHUNK_DIVISOR = 6
CONTINUATION_MARKER = "—"

CHAPTER_COUNT = 81

ORIGINAL_BOOKS = [
    {
        "name": "Book_1_Beck_Bahm_Anonymous_Crowley_Cronk.pdf",
        "translations": [
            "Sanderson Beck",
            "Archie J. Bahm",
            "Anonymous",
            "Aleister Crowley",
            "George Cronk",
        ],
    },
    {
        "name": "Book_2_Addiss_Blakney_Bullen_Cheng_Chen.pdf",
        "translations": [
            "Addiss & Lombardo",
            "Raymond B. Blakney",
            "David Bullen",
            "David Hong Cheng",
            "Ellen Marie Chen",
        ],
    },
    {
        "name": "Book_3_Cleary_Bryce_Clatfelder_Byrn_Chan.pdf",
        "translations": [
            "Thomas Cleary",
            "Derek Bryce",
            "Jim Clatfelder",
            "Tormond Byrn",
            "Wing-Tsit Chan",
        ],
    },
    {
        "name": "Book_4_Goddard_Gorn_Bynner_Chohan_Chen.pdf",
        "translations": [
            "Dwight Goddard",
            "Walter Gorn-Old",
            "Witter Bynner",
            "Chou-Wing Chohan",
            "Chao-Hsiu Chen",
        ],
    },
]

ORIGINAL_TRANSLATORS = {
    name for book in ORIGINAL_BOOKS for name in book["translations"]
}

TRANSLATOR_ALIASES = {
    "stephen addiss & stanley lombardo": "Addiss & Lombardo",
    "stephen addiss and stanley lombardo": "Addiss & Lombardo",
    "addiss & stanley lombardo": "Addiss & Lombardo",
    "addiss and lombardo": "Addiss & Lombardo",
    "addiss & lombardo": "Addiss & Lombardo",
}

DISCOVERY_HINTS = (
    "tao",
    "dao",
    "te king",
    "gutenberg",
)


@dataclass
class DiscoverySkip:
    file_name: str
    reason: str


@dataclass
class ParseFailure:
    name: str
    file_name: str
    reason: str


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("tao_all")
    logger.setLevel(logging.INFO)
    logger.handlers[:] = []

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("&", " and ")
    value = re.sub(r"[^0-9A-Za-z]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "translation"


def normalize_translator_name(raw_name: str) -> str:
    cleaned = unicodedata.normalize("NFKC", raw_name).strip()
    cleaned = cleaned.strip(" \t\r\n,;:-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*(?:Terebess Asia Online \(TAO\)|Terebess Asia Online|Terebess)\s*$", "", cleaned, flags=re.I).strip()
    alias_key = re.sub(r"[\s\-_]+", " ", cleaned).lower()
    return TRANSLATOR_ALIASES.get(alias_key, cleaned)


def parse_translator_name(path: Path) -> tuple[str | None, str]:
    stem = path.stem
    lower = stem.lower()
    if not any(hint in lower for hint in DISCOVERY_HINTS):
        return None, "filename does not look like a Tao Te Ching translation"

    patterns = [
        re.compile(
            r"(?i)\b(?:von|by)\s+(?P<name>.+?)(?:\s*-\s*Terebess\b|\s*,\s*Terebess\b|\s+Terebess\b|$)"
        ),
        re.compile(r"(?i)\bby\s+(?P<name>.+?)(?:\s*-\s*Internet\b|\s*-\s*Wayback\b|\s+Internet\b|$)"),
    ]
    for pattern in patterns:
        match = pattern.search(stem)
        if match:
            name = normalize_translator_name(match.group("name"))
            if not name:
                return None, "translator name was empty after cleanup"
            return name, "parsed from filename"

    if lower.startswith("das tao te king von "):
        name = normalize_translator_name(stem[len("Das Tao Te King von ") :])
        if name:
            return name, "parsed from filename"

    if lower.startswith("tao te ching, english by "):
        name = normalize_translator_name(stem[len("Tao Te Ching, English by ") :])
        if name and not name.lower().startswith("terebess"):
            return name, "parsed from filename"

    return None, "translator name could not be parsed from filename"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_export_path(translation: tao.Translation) -> None:
    translation.export_path = TXT_EXPORT_DIR / f"{slugify(translation.name)}.txt"


def discover_translation_sources(logger: logging.Logger):
    translations: dict[str, tao.Translation] = {}
    skipped: list[DiscoverySkip] = []

    for path in sorted(ROOT.glob("*.html")):
        name, reason = parse_translator_name(path)
        if not name:
            skipped.append(DiscoverySkip(path.name, reason))
            logger.info("Skipped %s: %s", path.name, reason)
            continue
        if name in translations:
            skipped.append(DiscoverySkip(path.name, f"duplicate translator after normalization: {name}"))
            logger.info("Skipped %s: duplicate translator after normalization: %s", path.name, name)
            continue

        translation = tao.Translation(name, path)
        normalize_export_path(translation)
        translations[name] = translation
        logger.info("Discovered %s -> %s", path.name, name)

    return translations, skipped


def validate_translation(translation: tao.Translation, logger: logging.Logger) -> bool:
    missing = [i + 1 for i, chapter in enumerate(translation.chapters) if not chapter.strip()]
    artifacts = []
    for index, chapter in enumerate(translation.chapters, 1):
        for line in chapter.splitlines():
            stripped = line.strip().lower()
            if stripped in {"up", "up.", "[no frames]", "no frames", "image"}:
                artifacts.append(index)
                break
            if "\ufffd" in line:
                artifacts.append(index)
                break
    if missing:
        logger.error("%s: missing chapters %s", translation.name, missing)
        return False
    if artifacts:
        logger.warning("%s: artifact scan flagged chapters %s", translation.name, sorted(set(artifacts)))
    logger.info("%s: validation passed", translation.name)
    return True


def export_translation_text(translation: tao.Translation, logger: logging.Logger) -> None:
    TXT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    with translation.export_path.open("w", encoding="utf-8") as handle:
        for number, chapter in enumerate(translation.chapters, 1):
            handle.write(f"{number}\n")
            handle.write(chapter.strip())
            handle.write("\n\n")
    logger.info("%s: wrote %s", translation.name, translation.export_path.name)


def paragraph_markup(text: str) -> str:
    return html_lib.escape(text, quote=False).replace("\n", "<br/>")


def build_body_style(font_size: float) -> ParagraphStyle:
    return ParagraphStyle(
        "body",
        parent=getSampleStyleSheet()["BodyText"],
        fontName=BODY_FONT,
        fontSize=font_size,
        leading=font_size * BODY_LINE_FACTOR,
        alignment=TA_LEFT,
        splitLongWords=0,
        spaceAfter=2,
    )


def fit_flowables(paragraphs, style, frame_w, frame_h) -> bool:
    frame = Frame(0, 0, frame_w, frame_h, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    flowables = [Paragraph(paragraph_markup(paragraph), style) for paragraph in paragraphs]
    remaining = list(flowables)
    tmp = canvas.Canvas(io.BytesIO(), pagesize=letter)
    frame.addFromList(remaining, tmp)
    return not remaining


def sentence_units(text: str) -> list[str]:
    units = []
    start = 0
    for match in re.finditer(r'(?<=[.!?])\s+', text):
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
        return [unit for unit in units if unit]
    return [word for word in text.split() if word]


def split_paragraph_head_tail(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
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


def split_paragraph_tail_head(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
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


def normalize_paragraphs(text: str) -> list[str]:
    paragraphs = [
        re.sub(r"\s*\n\s*", " ", part).strip()
        for part in re.split(r"\n\s*\n", text)
        if part.strip()
    ]
    return paragraphs if paragraphs else ([text.strip()] if text.strip() else [])


def choose_initial_split(chapter_text: str) -> tuple[list[str], list[str]]:
    paragraphs = normalize_paragraphs(chapter_text)
    if not paragraphs:
        return [], []

    total_words = sum(len(paragraph.split()) for paragraph in paragraphs)
    target_words = max(1, total_words // 2)
    top: list[str] = []
    bottom: list[str] = []
    consumed = 0

    for index, paragraph in enumerate(paragraphs):
        paragraph_words = len(paragraph.split())
        if consumed + paragraph_words < target_words:
            top.append(paragraph)
            consumed += paragraph_words
            continue
        if consumed + paragraph_words == target_words:
            top.append(paragraph)
            bottom = paragraphs[index + 1 :]
            break

        remaining_words = target_words - consumed
        first, second = split_paragraph_at_word_target(paragraph, remaining_words)
        if first:
            top.append(first)
            bottom = [second] + paragraphs[index + 1 :] if second else paragraphs[index + 1 :]
        else:
            bottom = paragraphs[index:]
        break
    else:
        bottom = []

    return top, bottom


def split_paragraph_at_word_target(paragraph: str, target_words: int) -> tuple[str, str]:
    target_words = max(1, target_words)
    words = paragraph.split()
    if len(words) <= 1:
        return split_paragraph_head_tail(paragraph)

    boundaries = [match.start() for match in re.finditer(r'(?<=[.!?])\s+', paragraph)]
    if boundaries:
        candidate_word_counts = []
        for boundary in boundaries:
            left = paragraph[:boundary].strip().split()
            candidate_word_counts.append((abs(len(left) - target_words), boundary))
        candidate_word_counts.sort(key=lambda item: (item[0], item[1]))
        split_at = candidate_word_counts[0][1]
        return paragraph[:split_at].rstrip(), paragraph[split_at:].lstrip()

    split_index = min(len(words), target_words)
    left = " ".join(words[:split_index]).strip()
    right = " ".join(words[split_index:]).strip()
    return left, right


def refine_split(top: list[str], bottom: list[str], style, frame_w, frame_h) -> tuple[list[str], list[str]]:
    top = list(top)
    bottom = list(bottom)
    safety = 0
    while safety < MAX_SPLIT_ITERATIONS:
        safety += 1
        top_fits = fit_flowables(top, style, frame_w, frame_h)
        bottom_fits = fit_flowables(bottom, style, frame_w, frame_h)
        if top_fits and bottom_fits:
            break
        if not top_fits and top:
            head, tail = split_paragraph_tail_head(top[-1])
            if head:
                top[-1] = head + (" " + CONTINUATION_MARKER if tail else "")
                if tail:
                    bottom.insert(0, tail)
            else:
                bottom.insert(0, top.pop())
            continue
        if not bottom_fits and bottom:
            head, tail = split_paragraph_head_tail(bottom[0])
            if head:
                top.append(head + (" " + CONTINUATION_MARKER if tail else ""))
                if tail:
                    bottom[0] = tail
                else:
                    bottom.pop(0)
            else:
                top.append(bottom.pop(0))
            continue
        break
    return top, bottom


def split_to_fit(
    chapter_text: str,
    frame_w: float,
    frame_h: float,
    logger: logging.Logger,
    translation_name: str,
    chapter_number: int,
):
    last_result = ([], [])
    for font_size in [MAX_BODY_SIZE, 10.5, 10.0, 9.5, 9.0, 8.5, MIN_BODY_SIZE]:
        style = build_body_style(font_size)
        top, bottom = choose_initial_split(chapter_text)
        top, bottom = refine_split(top, bottom, style, frame_w, frame_h)
        if fit_flowables(top, style, frame_w, frame_h) and fit_flowables(bottom, style, frame_w, frame_h):
            return font_size, top, bottom
        last_result = (top, bottom)
    logger.warning("%s chapter %s: using smallest font and best-effort split", translation_name, chapter_number)
    return MIN_BODY_SIZE, last_result[0], last_result[1]


def render_page(pdf, chapter_number: int, page_data):
    top_y = MARGIN + SECTION_H + MIDDLE_GAP
    bottom_y = MARGIN
    chapter_y = PAGE_H - 0.20 * inch
    name_y = PAGE_H - 0.33 * inch
    left_x = MARGIN

    pdf.setLineWidth(0.4)
    pdf.setStrokeColorRGB(0.55, 0.55, 0.55)

    pdf.setFont(HEADER_FONT, HEADER_SIZE)
    pdf.drawCentredString(PAGE_W / 2.0, chapter_y, f"Chapter {chapter_number}")

    for index, item in enumerate(page_data):
        translation_name, font_size, top_paragraphs, bottom_paragraphs = item
        x = left_x + index * (COLUMN_W + GUTTER)
        center_x = x + (COLUMN_W / 2.0)
        body_style = build_body_style(font_size)

        pdf.setFont("Helvetica", HEADER_SMALL_SIZE)
        pdf.drawCentredString(center_x, name_y, translation_name)

        top_frame = Frame(
            x,
            top_y,
            COLUMN_W,
            SECTION_H,
            leftPadding=2,
            rightPadding=2,
            topPadding=0,
            bottomPadding=4,
            showBoundary=1,
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
            showBoundary=1,
        )

        top_flowables = [Paragraph(paragraph_markup(paragraph), body_style) for paragraph in top_paragraphs]
        bottom_flowables = [Paragraph(paragraph_markup(paragraph), body_style) for paragraph in bottom_paragraphs]
        top_frame.addFromList(top_flowables, pdf)
        bottom_frame.addFromList(bottom_flowables, pdf)

        pdf.line(x, MARGIN + SECTION_H, x + COLUMN_W, MARGIN + SECTION_H)
        pdf.line(x, MARGIN + SECTION_H + MIDDLE_GAP, x + COLUMN_W, MARGIN + SECTION_H + MIDDLE_GAP)

    pdf.showPage()


def translation_lookup(translations: dict[str, tao.Translation]) -> dict[str, tao.Translation]:
    return dict(translations)


def build_pdf(output_path: Path, book: dict, translations: dict[str, tao.Translation], logger: logging.Logger) -> None:
    logger.info("Generating PDF: %s", output_path.name)
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    pdf.setTitle(book["name"])
    pdf.setAuthor("Tao Te Ching Build Pipeline")
    lookup = translation_lookup(translations)

    for chapter_number in range(1, CHAPTER_COUNT + 1):
        page_data = []
        for translation_name in book["translations"]:
            translation = lookup[translation_name]
            chapter_text = translation.chapter_text(chapter_number)
            font_size, top, bottom = split_to_fit(
                chapter_text,
                COLUMN_W,
                SECTION_H,
                logger,
                translation_name,
                chapter_number,
            )
            page_data.append((translation_name, font_size, top, bottom))
        render_page(pdf, chapter_number, page_data)

    pdf.save()
    logger.info("Generated %s", output_path.name)


def build_mega_chapters(translations: list[tao.Translation], logger: logging.Logger) -> int:
    MEGA_CHAPTER_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for chapter_number in range(1, CHAPTER_COUNT + 1):
        output_path = MEGA_CHAPTER_DIR / f"chapter_{chapter_number:03d}.txt"
        with output_path.open("w", encoding="utf-8") as handle:
            handle.write(f"===== Chapter {chapter_number} =====\n\n")
            for translation in translations:
                chapter_text = translation.chapter_text(chapter_number).strip()
                if not chapter_text:
                    continue
                handle.write(chapter_text)
                handle.write("\n\n")
        count += 1
    logger.info("Wrote %d mega chapter files", count)
    return count


def chunked(sequence: list[tao.Translation], size: int) -> list[list[tao.Translation]]:
    return [sequence[index : index + size] for index in range(0, len(sequence), size)]


def book_filename(book_number: int, translators: list[str]) -> str:
    parts = [slugify(name) for name in translators]
    filename = f"Book_{book_number}_{'_'.join(parts)}.pdf"
    if len(filename) > 120 and len(parts) > 3:
        filename = f"Book_{book_number}_{'_'.join(parts[:3])}.pdf"
    return filename


def build_new_books(translations: dict[str, tao.Translation], logger: logging.Logger) -> list[dict]:
    eligible = [translation for name, translation in translations.items() if name not in ORIGINAL_TRANSLATORS]
    eligible.sort(key=lambda translation: translation.name.casefold())
    selected = eligible[:20]

    books = []
    for offset, group in enumerate(chunked(selected, 5), start=5):
        names = [translation.name for translation in group]
        books.append(
            {
                "name": book_filename(offset, names),
                "translations": names,
            }
        )
    logger.info("Selected %d translators for Books 5-8", len(selected))
    return books


def write_report(
    discovered_total: int,
    successful: dict[str, tao.Translation],
    skipped: list[DiscoverySkip],
    parse_failures: list[ParseFailure],
    books_5_8: list[dict],
    export_count: int,
    mega_count: int,
    elapsed_seconds: float,
):
    lines = [
        "Tao Te Ching Expansion Report",
        "",
        f"Total HTML files scanned: {len(list(ROOT.glob('*.html')))}",
        f"Total translations discovered: {discovered_total}",
        f"Successfully parsed translations: {len(successful)}",
        f"Total text files exported: {export_count}",
        f"Total mega chapter files written: {mega_count}",
        f"Processing time: {elapsed_seconds:.2f}s",
        "",
        "Original books used translators:",
    ]
    for book in ORIGINAL_BOOKS:
        lines.append(f"- {book['name']}: {', '.join(book['translations'])}")
    lines.append("")
    lines.append("Books 5-8 used translators:")
    for index, book in enumerate(books_5_8, start=5):
        lines.append(f"- Book {index}: {', '.join(book['translations'])}")
    lines.append("")
    lines.append("Skipped files:")
    if skipped:
        for item in skipped:
            lines.append(f"- {item.file_name}: {item.reason}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Parse failures:")
    if parse_failures:
        for item in parse_failures:
            lines.append(f"- {item.file_name} ({item.name}): {item.reason}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Warnings:")
    if parse_failures or skipped:
        lines.append("- See skipped files and parse failures above.")
    else:
        lines.append("- none")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    start = time.perf_counter()
    logger = configure_logging()
    logger.info("Starting Tao Te Ching expansion build")

    translations, skipped = discover_translation_sources(logger)
    parse_failures: list[ParseFailure] = []
    successful: dict[str, tao.Translation] = {}

    for name in sorted(translations):
        translation = translations[name]
        try:
            tao.parse_translation(translation, logger)
            if not validate_translation(translation, logger):
                parse_failures.append(ParseFailure(name, translation.source_path.name, "validation failed"))
                continue
            export_translation_text(translation, logger)
            successful[name] = translation
        except Exception as exc:
            parse_failures.append(ParseFailure(name, translation.source_path.name, str(exc)))
            logger.exception("Failed to parse %s", name)

    selected_books = build_new_books(successful, logger)

    for book in selected_books:
        output_path = ROOT / book["name"]
        try:
            build_pdf(output_path, book, successful, logger)
        except Exception as exc:
            parse_failures.append(ParseFailure(", ".join(book["translations"]), output_path.name, str(exc)))
            logger.exception("Failed to generate %s", output_path.name)

    mega_count = build_mega_chapters([successful[name] for name in sorted(successful)], logger)
    elapsed_seconds = time.perf_counter() - start
    write_report(
        len(translations),
        successful,
        skipped,
        parse_failures,
        selected_books,
        len(successful),
        mega_count,
        elapsed_seconds,
    )
    logger.info("Done in %.2fs", elapsed_seconds)


if __name__ == "__main__":
    main()
