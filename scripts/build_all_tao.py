#!/usr/bin/env python3
"""
Robust Tao Te Ching build pipeline.

Stages:
1. Parse each HTML source into a Translation object.
2. Validate that every translation has 81 clean chapters.
3. Export plain-text chapter files.
4. Generate four parallel-layout PDF books.

The parser uses BeautifulSoup with the lxml parser and falls back to
text-boundary heuristics when chapter anchors are inconsistent.
"""

from __future__ import print_function

import argparse
import html as html_lib
import io
import logging
import re
import sys
import unicodedata
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit(
        "BeautifulSoup is required. Install bs4 and lxml before running this script."
    ) from exc

try:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Frame, Paragraph
except ImportError as exc:
    raise SystemExit(
        "ReportLab is required. Install reportlab before running this script."
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
TXT_EXPORT_DIR = ROOT / "txt_exports"
LOG_PATH = ROOT / "build_log.txt"

PAGE_W, PAGE_H = letter
MARGIN = 0.55 * inch
TEXT_W = PAGE_W - (2 * MARGIN)
TEXT_H = PAGE_H - (2 * MARGIN)

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

CHAPTER_ANCHOR_RE = re.compile(r'<a\b[^>]*name\s*=\s*["\']?Kap0*(\d{1,2})["\']?[^>]*>', re.I)
CHAPTER_LINE_RE = re.compile(r"^\s*(?:chapter\s*)?(\d{1,2})(?:[.\):\-]|\s+)?\s*(.*)$", re.I)
SENTENCE_BOUNDARY_RE = re.compile(r'(?<=[.!?])\s+')
INVALID_TEXT_RE = re.compile(r"[\uFFFD\u0000-\u0008\u000B\u000C\u000E-\u001F]")


class Translation(object):
    def __init__(self, name, source_path):
        self.name = name
        self.source_path = source_path
        self.export_path = TXT_EXPORT_DIR / self._export_filename(name)
        self.chapters = []
        self.parse_method = None
        self.warnings = []

    @staticmethod
    def _export_filename(name):
        return name.replace(" & ", "_and_").replace(" ", "_").replace("-", "_") + ".txt"

    def chapter_text(self, chapter_number):
        return self.chapters[chapter_number - 1]


BOOKS = [
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


SOURCE_FILES = {
    "Sanderson Beck": ROOT / "Tao Te Ching, English by Sanderson Beck - Terebess Asia Online (TAO).html",
    "Archie J. Bahm": ROOT / "Tao Te Ching, English by Archie J. Bahm - Terebess Asia Online (TAO).html",
    "Anonymous": ROOT / "Tao Te Ching by Anonymous - Terebess Asia Online (TAO).html",
    "Aleister Crowley": ROOT / "Tao Te Ching, English by Aleister Crowley - Terebess Asia Online (TAO).html",
    "George Cronk": ROOT / "Das Tao Te King von George Cronk.html",
    "Addiss & Lombardo": ROOT / "Tao Te Ching, English by Stephen Addiss & Stanley Lombardo - Terebess Asia Online (TAO).html",
    "Raymond B. Blakney": ROOT / "Tao Te Ching, English by Raymond B. Blakney, Terebess Asia Online (TAO).html",
    "David Bullen": ROOT / "Tao Te Ching, English by David Bullen - Terebess Asia Online (TAO).html",
    "David Hong Cheng": ROOT / "Tao Te Ching, English by David Hong Cheng - Terebess Asia Online (TAO).html",
    "Ellen Marie Chen": ROOT / "Tao Te Ching, English by Ellen Marie Chen - Terebess Asia Online (TAO).html",
    "Thomas Cleary": ROOT / "Tao Te Ching, English by Thomas Cleary - Terebess Asia Online (TAO).html",
    "Derek Bryce": ROOT / "Tao Te Ching, English by Derek Bryce - Terebess Asia Online (TAO).html",
    "Jim Clatfelder": ROOT / "Tao Te Ching, English by Jim Clatfelder, Terebess Asia Online (TAO).html",
    "Tormond Byrn": ROOT / "Tao Te Ching, English by Tormond Byrn, Terebess Asia Online (TAO).html",
    "Wing-Tsit Chan": ROOT / "Tao Te Ching, English by Wing-Tsit Chan - Terebess Asia Online (TAO).html",
    "Dwight Goddard": ROOT / "Das Tao Te King von Dwight Goddard.html",
    "Walter Gorn-Old": ROOT / "Das Tao Te King von Walter Gorn-Old.html",
    "Witter Bynner": ROOT / "Tao Te Ching by Witter Bynner, Terebess Asia Online (TAO).html",
    "Chou-Wing Chohan": ROOT / "Tao Te Ching, English by Chou-Wing Chohan - Terebess Asia Online (TAO).html",
    "Chao-Hsiu Chen": ROOT / "Tao Te Ching, English by Chao-Hsiu Chen - Terebess Asia Online (TAO).html",
}


def configure_logging():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("tao_build")
    logger.setLevel(logging.INFO)
    logger.handlers[:] = []

    file_handler = logging.FileHandler(str(LOG_PATH), mode="w", encoding="utf-8")
    stream_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def read_source_text(path):
    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    best_text = None
    best_score = None
    for encoding in encodings:
        try:
            text = path.read_text(encoding=encoding, errors="replace")
        except Exception:
            continue
        score = text.count("\ufffd") * 100
        if "Kap01" in text or "Kap1" in text:
            score -= 50
        if best_score is None or score < best_score:
            best_text = text
            best_score = score
        if score <= 0:
            break
    if best_text is None:
        raise IOError("Unable to read source file: {0}".format(path))
    return best_text


def strip_html_blocks(fragment, tag_name):
    soup = BeautifulSoup(fragment, "lxml")
    for tag in soup.find_all(tag_name):
        tag.decompose()
    return str(soup)


def sanitize_text(text):
    text = unicodedata.normalize("NFKC", text)
    text = text.translate({ord("“"): '"', ord("”"): '"', ord("‘"): "'", ord("’"): "'"})
    text = INVALID_TEXT_RE.sub(" ", text)
    cleaned_lines = []
    for raw_line in text.replace("\r", "\n").splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            cleaned_lines.append("")
            continue
        low = line.lower()
        if low in {"up", "up.", "[no frames]", "no frames", "image", "wayback machine"}:
            continue
        if low.startswith("image ") or low == "image":
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_nav_artifacts(fragment):
    soup = BeautifulSoup(fragment, "lxml")
    for tag in soup.find_all(["script", "style", "noscript", "iframe", "object", "embed"]):
        tag.decompose()
    for tag in soup.find_all("img"):
        tag.decompose()
    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip().lower()
        text = anchor.get_text(" ", strip=True).lower()
        if href == "#top" or text == "up":
            anchor.decompose()
    return soup


def extract_chapters_primary(raw_html):
    matches = list(CHAPTER_ANCHOR_RE.finditer(raw_html))
    chapters = {}
    if not matches:
        return chapters
    for index, match in enumerate(matches):
        number = int(match.group(1))
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_html)
        fragment = raw_html[start:end]
        chapters[number] = fragment
    return chapters


def text_from_fragment(fragment, chapter_number):
    soup = remove_nav_artifacts(fragment)
    text = soup.get_text("\n", strip=False)
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = sanitize_text(text)
    text = strip_leading_heading(text, chapter_number)
    text = sanitize_text(text)
    return text


def strip_leading_heading(text, chapter_number):
    lines = text.splitlines()
    result = []
    heading_removed = False
    for line in lines:
        stripped = line.strip()
        if not stripped and not result:
            continue
        if not heading_removed:
            match = CHAPTER_LINE_RE.match(stripped)
            if match and int(match.group(1)) == chapter_number:
                remainder = match.group(2).strip()
                if remainder:
                    result.append(remainder)
                heading_removed = True
                continue
            if stripped == str(chapter_number) or stripped == "{0}.".format(chapter_number):
                heading_removed = True
                continue
        result.append(line)
    return "\n".join(result).strip()


def parse_chapters_from_text_boundaries(raw_text):
    soup = remove_nav_artifacts(raw_text)
    text = soup.get_text("\n", strip=False)
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = sanitize_text(text)
    lines = [line.strip() for line in text.splitlines()]
    headings = []
    for index, line in enumerate(lines):
        match = CHAPTER_LINE_RE.match(line)
        if match:
            number = int(match.group(1))
            if 1 <= number <= 81:
                headings.append((number, index, match.group(2).strip()))
    chapters = {}
    if not headings:
        return chapters
    for idx, (number, start_index, remainder) in enumerate(headings):
        end_index = headings[idx + 1][1] if idx + 1 < len(headings) else len(lines)
        chunk = []
        if remainder:
            chunk.append(remainder)
        chunk.extend(lines[start_index + 1:end_index])
        chapter_text = "\n".join(chunk).strip()
        chapter_text = sanitize_text(chapter_text)
        chapters[number] = chapter_text
    return chapters


def parse_translation(translation, logger):
    raw_html = read_source_text(translation.source_path)
    primary_fragments = extract_chapters_primary(raw_html)
    parsed = {}
    if len(primary_fragments) >= 70:
        for number in sorted(primary_fragments):
            parsed[number] = text_from_fragment(primary_fragments[number], number)
        translation.parse_method = "anchor fragments"
    else:
        logger.info("%s: primary parse weak (%d fragments), trying fallback.", translation.name, len(primary_fragments))
        parsed = parse_chapters_from_text_boundaries(raw_html)
        translation.parse_method = "text boundaries"

    chapters = []
    for number in range(1, 82):
        chapter_text = parsed.get(number, "").strip()
        chapter_text = sanitize_text(chapter_text)
        chapters.append(chapter_text)
    translation.chapters = chapters
    translation.warnings = []
    for idx, chapter in enumerate(chapters, 1):
        if not chapter:
            translation.warnings.append("missing chapter {0}".format(idx))
    return translation


def validate_translation(translation, logger):
    missing = [index + 1 for index, chapter in enumerate(translation.chapters) if not chapter.strip()]
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
        logger.error("%s: validation failed, missing chapters %s", translation.name, missing)
        return False
    if artifacts:
        logger.warning("%s: artifact scan flagged chapters %s", translation.name, sorted(set(artifacts)))
    logger.info("%s: validation passed, 81 chapters found", translation.name)
    return True


def write_translation_export(translation, logger):
    TXT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    with translation.export_path.open("w", encoding="utf-8") as handle:
        for number, chapter in enumerate(translation.chapters, 1):
            handle.write("{0}\n".format(number))
            handle.write(chapter.strip())
            handle.write("\n\n")
    logger.info("%s: wrote %s", translation.name, translation.export_path.name)


def normalize_paragraphs(text):
    paragraphs = [re.sub(r"\s*\n\s*", " ", part).strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    return paragraphs if paragraphs else ([text.strip()] if text.strip() else [])


def paragraph_markup(text):
    return html_lib.escape(text, quote=False).replace("\n", "<br/>")


def build_body_style(font_size):
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


def fit_flowables(paragraphs, style, frame_w, frame_h):
    frame = Frame(0, 0, frame_w, frame_h, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    flowables = [Paragraph(paragraph_markup(paragraph), style) for paragraph in paragraphs]
    remaining = list(flowables)
    tmp = canvas.Canvas(io.BytesIO(), pagesize=letter)
    frame.addFromList(remaining, tmp)
    return not remaining


def split_units(text):
    sentence_units = []
    start = 0
    for match in SENTENCE_BOUNDARY_RE.finditer(text):
        end = match.end()
        sentence_units.append(text[start:end].strip())
        start = end
    tail = text[start:].strip()
    if tail:
        sentence_units.append(tail)
    if len(sentence_units) > 1:
        return [unit for unit in sentence_units if unit]
    return [word for word in text.split() if word]


def split_paragraph_head_tail(text):
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


def split_paragraph_tail_head(text):
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


def choose_initial_split(chapter_text):
    paragraphs = normalize_paragraphs(chapter_text)
    if not paragraphs:
        return [], []

    total_words = sum(len(paragraph.split()) for paragraph in paragraphs)
    target_words = max(1, total_words // 2)
    top = []
    bottom = []
    consumed = 0

    for index, paragraph in enumerate(paragraphs):
        paragraph_words = len(paragraph.split())
        if consumed + paragraph_words < target_words:
            top.append(paragraph)
            consumed += paragraph_words
            continue
        if consumed + paragraph_words == target_words:
            top.append(paragraph)
            bottom = paragraphs[index + 1:]
            break

        remaining_words = target_words - consumed
        first, second = split_paragraph_at_word_target(paragraph, remaining_words)
        if first:
            top.append(first)
            if second:
                bottom = [second] + paragraphs[index + 1:]
            else:
                bottom = paragraphs[index + 1:]
        else:
            bottom = paragraphs[index:]
        break
    else:
        bottom = []

    return top, bottom


def split_paragraph_at_word_target(paragraph, target_words):
    target_words = max(1, target_words)
    words = paragraph.split()
    if len(words) <= 1:
        return split_paragraph_head_tail(paragraph)

    boundaries = []
    for match in SENTENCE_BOUNDARY_RE.finditer(paragraph):
        boundaries.append(match.start())
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


def split_to_fit(chapter_text, frame_w, frame_h, logger, translation_name, chapter_number):
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


def refine_split(top, bottom, style, frame_w, frame_h):
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


def render_page(pdf, chapter_number, page_data):
    top_y = MARGIN + SECTION_H + MIDDLE_GAP
    bottom_y = MARGIN
    header_y = PAGE_H - 0.19 * inch
    subheader_y = PAGE_H - 0.31 * inch
    left_x = MARGIN

    pdf.setLineWidth(0.4)
    pdf.setStrokeColorRGB(0.55, 0.55, 0.55)

    for index, item in enumerate(page_data):
        translation_name, font_size, top_paragraphs, bottom_paragraphs = item
        x = left_x + index * (COLUMN_W + GUTTER)
        center_x = x + (COLUMN_W / 2.0)
        body_style = build_body_style(font_size)

        pdf.setFont(HEADER_FONT, HEADER_SIZE)
        pdf.drawCentredString(center_x, header_y, "Chapter {0}".format(chapter_number))
        pdf.setFont("Helvetica", HEADER_SMALL_SIZE)
        pdf.drawCentredString(center_x, subheader_y, translation_name)

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


def build_translation_registry(logger):
    translations = {}
    for name, path in SOURCE_FILES.items():
        if not path.exists():
            raise IOError("Missing source file: {0}".format(path))
        translations[name] = Translation(name, path)
        logger.info("Loaded source: %s", path.name)
    return translations


def parse_all_translations(translations, logger):
    for name in sorted(translations):
        logger.info("Parsing %s", name)
        parse_translation(translations[name], logger)
        logger.info("%s: parsed via %s", name, translations[name].parse_method)


def validate_all_translations(translations, logger):
    all_ok = True
    for name in sorted(translations):
        ok = validate_translation(translations[name], logger)
        all_ok = all_ok and ok
    return all_ok


def export_all_text(translations, logger):
    for name in sorted(translations):
        write_translation_export(translations[name], logger)


def translation_lookup(translations):
    lookup = {}
    for name, translation in translations.items():
        lookup[name] = translation
    return lookup


def build_pdf(output_path, book, translations, logger):
    logger.info("Generating PDF: %s", output_path.name)
    pdf = canvas.Canvas(str(output_path), pagesize=letter)
    pdf.setTitle(book["name"])
    pdf.setAuthor("Tao Te Ching Build Pipeline")
    chapter_numbers = list(range(1, 82))
    lookup = translation_lookup(translations)

    for chapter_number in chapter_numbers:
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
    size_mb = output_path.stat().st_size / (1024.0 * 1024.0)
    logger.info("Generated %s (%.2f MB)", output_path.name, size_mb)


def build_all(logger):
    translations = build_translation_registry(logger)
    parse_all_translations(translations, logger)
    if not validate_all_translations(translations, logger):
        raise SystemExit("Validation failed; refusing to export or build PDFs.")

    export_all_text(translations, logger)
    logger.info("Exported %d text files", len(translations))

    for book in BOOKS:
        output_path = ROOT / book["name"]
        build_pdf(output_path, book, translations, logger)

    logger.info("Build complete")


def main():
    parser = argparse.ArgumentParser(description="Build Tao Te Ching exports and PDFs.")
    args = parser.parse_args()
    logger = configure_logging()
    logger.info("Starting Tao Te Ching build")
    logger.info("Output log: %s", LOG_PATH.name)
    build_all(logger)


if __name__ == "__main__":
    main()
