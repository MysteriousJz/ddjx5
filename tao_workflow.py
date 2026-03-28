#!/usr/bin/env python3
"""
tao_workflow.py — Complete Tao Te Ching multi-translation assembly workflow.

Stages:
    1. Normalize  : Parse five raw .txt translation files into clean chapter dicts
                    {1: "chapter text", ..., 81: "chapter text"}.
    2. Analyze    : For each chapter in each translation, use ReportLab to measure
                    rendered height and find an optimal top/bottom split that fits the
                    column half-frame.
    3. Assemble   : Generate a single 81-page PDF with 5 columns (one per translation),
                    top and bottom half-frames per column, laid out in signature order
                    ready for hand-binding (ascending top, descending bottom).

Usage:
    python tao_workflow.py

Dependencies:
    reportlab        (pip install reportlab)

Place this script in the same directory as the five .txt translation files:
    goddard.txt, anon.txt, gia.txt, crowley.txt, gorn.txt
"""

import io
import logging
import os
import re
import sys

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, KeepTogether, Paragraph

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Layout constants  (match ee.py defaults)
# ---------------------------------------------------------------------------
FILES = ["goddard.txt", "anon.txt", "gia.txt", "crowley.txt", "gorn.txt"]
OUT_PDF = "tao_te_ching_bound.pdf"

PAGE_W, PAGE_H = letter          # 8.5 × 11 inches
MARGIN = 0.5 * inch
TEXT_W = PAGE_W - 2 * MARGIN    # 7.5 inches
TEXT_H = PAGE_H - 2 * MARGIN    # 10 inches

NUM_COLS = 5
SMALL_GAP = 0.125 * inch        # horizontal gap between columns
VERT_CENTER_GAP = 0.5 * inch    # dead strip at page centre (binding gutter)
COL_W = (TEXT_W - (NUM_COLS - 1) * SMALL_GAP) / NUM_COLS
FRAME_H = (TEXT_H - VERT_CENTER_GAP) / 2.0

FONT_SIZE = 11
LEADING = FONT_SIZE + 2         # 13 pt

TARGET_RATIO = 0.5
SENTENCE_RADIUS = 120
CONTINUATION_MARKER = " \u2014"   # em-dash appended at forced splits

# Binding constants
NUM_SIGNATURES = 9
PAGES_PER_SIG = 9               # 9 pages × 9 signatures = 81 pages / chapters

# ---------------------------------------------------------------------------
# Word-to-number map (supports "One" ... "Eighty-One")
# ---------------------------------------------------------------------------
WORD_TO_NUM: dict = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
    "twenty-one": 21, "twenty-two": 22, "twenty-three": 23,
    "twenty-four": 24, "twenty-five": 25, "twenty-six": 26,
    "twenty-seven": 27, "twenty-eight": 28, "twenty-nine": 29,
    "thirty": 30, "thirty-one": 31, "thirty-two": 32,
    "thirty-three": 33, "thirty-four": 34, "thirty-five": 35,
    "thirty-six": 36, "thirty-seven": 37, "thirty-eight": 38,
    "thirty-nine": 39, "forty": 40, "forty-one": 41,
    "forty-two": 42, "forty-three": 43, "forty-four": 44,
    "forty-five": 45, "forty-six": 46, "forty-seven": 47,
    "forty-eight": 48, "forty-nine": 49, "fifty": 50,
    "fifty-one": 51, "fifty-two": 52, "fifty-three": 53,
    "fifty-four": 54, "fifty-five": 55, "fifty-six": 56,
    "fifty-seven": 57, "fifty-eight": 58, "fifty-nine": 59,
    "sixty": 60, "sixty-one": 61, "sixty-two": 62,
    "sixty-three": 63, "sixty-four": 64, "sixty-five": 65,
    "sixty-six": 66, "sixty-seven": 67, "sixty-eight": 68,
    "sixty-nine": 69, "seventy": 70, "seventy-one": 71,
    "seventy-two": 72, "seventy-three": 73, "seventy-four": 74,
    "seventy-five": 75, "seventy-six": 76, "seventy-seven": 77,
    "seventy-eight": 78, "seventy-nine": 79,
    "eighty": 80, "eighty-one": 81,
}

# ---------------------------------------------------------------------------
# Font registration
# ---------------------------------------------------------------------------
def _register_font() -> str:
    """Try to register Comic Sans (preferred), then DejaVu Sans, then fall back to Helvetica."""
    candidates = [
        "Comic_Sans_MS.ttf", "ComicSansMS.ttf", "comic.ttf", "ComicSans.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Comic_Sans_MS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("UserF", path))
                log.info("Registered font from %s", path)
                return "UserF"
            except Exception:
                continue
    return "Helvetica"


FONT_NAME = _register_font()

# ===========================================================================
# SPLITTING / MEASUREMENT HELPERS
# (inline implementations that do not depend on ee.py)
# ===========================================================================

# Use a simple sentence-boundary pattern that works with standard re.
# We look for whitespace that follows a sentence-ending punctuation char.
_SENT_END_RE = re.compile(r'(?<=[.?!])["\']?\s+')


def _split_paragraph_by_sentence(para: str) -> list:
    """Split *para* into sentences; keep trailing punctuation with each sentence."""
    parts = _SENT_END_RE.split(para.strip())
    return [p for p in parts if p.strip()] or [para]


def _find_best_split(para: str, desired: int, radius: int = SENTENCE_RADIUS):
    """
    Split *para* near character offset *desired*.
    Prefer sentence boundary, then word boundary, then hard cut.
    Returns (first_part, second_part).
    """
    p = para.strip()
    n = len(p)
    desired = max(0, min(n, desired))
    lo, hi = max(0, desired - radius), min(n, desired + radius)

    sent_positions = [m.start() for m in _SENT_END_RE.finditer(p)]
    cands = [s for s in sent_positions if lo <= s <= hi]
    if cands:
        best = min(cands, key=lambda x: abs(x - desired))
        return p[:best].rstrip(), p[best:].lstrip()

    ws_positions = [m.start() for m in re.finditer(r'\s+', p)]
    cands = [s for s in ws_positions if lo <= s <= hi]
    if cands:
        best = min(cands, key=lambda x: abs(x - desired))
        return p[:best].rstrip(), p[best:].lstrip()

    return p[:desired].rstrip(), p[desired:].lstrip()


def _flowables_from_paragraphs(paragraphs, style, frame_w, frame_h,
                                keep_together=True):
    """Convert paragraph strings to ReportLab flowables."""
    result = []
    for p in paragraphs:
        fl = Paragraph(p.replace('\n', ' '), style)
        result.append(fl)
    return result


def _simulate_frame(flowables, frame_w, frame_h):
    """
    Simulate drawing *flowables* into a frame of size (frame_w, frame_h).
    Returns (all_fit: bool, leftover_flowables: list).
    Uses the same padding as _draw_column_half to ensure consistent measurement.
    """
    buf = io.BytesIO()
    tmpc = canvas.Canvas(buf, pagesize=letter)
    f = Frame(0, 0, frame_w, frame_h,
              leftPadding=4, rightPadding=4, topPadding=4, bottomPadding=4)
    copy_list = list(flowables)
    f.addFromList(copy_list, tmpc)
    return len(copy_list) == 0, copy_list


def _strip_marker(text: str, marker: str = CONTINUATION_MARKER) -> str:
    """Remove a trailing continuation marker from *text* if present."""
    s = text.rstrip()
    m = marker.rstrip()
    if s.endswith(m):
        return s[: -len(m)].rstrip()
    return s


def _split_chapter_text_smart(chap_text, frame_w, frame_h,
                               fontname=None, fontsize=FONT_SIZE,
                               target_ratio=TARGET_RATIO,
                               sentence_radius=SENTENCE_RADIUS,
                               continuation_marker=CONTINUATION_MARKER):
    """
    Compute a top/bottom split of *chap_text* that aims for *target_ratio*
    in characters, prefers paragraph/sentence boundaries, and uses rendered
    measurement to refine the split until the top half fits.

    Returns:
        top_parts   : list[str]  — paragraph strings for the top half
        bot_parts   : list[str]  — paragraph strings for the bottom half
        meta        : dict       — diagnostic info
    """
    if fontname is None:
        fontname = FONT_NAME

    paras = [p.strip() for p in re.split(r'\n\s*\n', chap_text) if p.strip()]
    if not paras:
        return [], [], {"note": "empty"}

    total = sum(len(p) for p in paras)
    target = int(round(total * target_ratio))
    meta = {"total_chars": total, "target_chars": target,
            "split_inside_paragraph": False}

    # Walk paragraphs accumulating chars until we pass target.
    # NOTE: we do NOT add continuation markers here; they are only appended
    # at the very end so the refinement loop doesn't create self-referential splits.
    acc = 0
    top_parts = []
    bot_parts = []
    for i, p in enumerate(paras):
        p_len = len(p)
        if acc + p_len <= target:
            top_parts.append(p)
            acc += p_len
            continue
        remaining = target - acc
        if remaining <= 0:
            bot_parts = paras[i:]
            break
        first, second = _find_best_split(p, remaining, sentence_radius)
        if not first.strip():
            bot_parts = paras[i:]
            break
        top_parts.append(first)        # no marker yet
        bot_parts = [second] + paras[i + 1:]
        meta["split_inside_paragraph"] = True
        break
    else:
        bot_parts = []

    # ReportLab style for measurement
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"],
                          fontName=fontname, fontSize=fontsize, leading=LEADING)

    def _flo(strs):
        return _flowables_from_paragraphs(strs, body, frame_w, frame_h)

    fits, _ = _simulate_frame(_flo(top_parts), frame_w, frame_h)
    safety = 0
    while not fits and top_parts and safety < 100:
        safety += 1
        # Strategy 1: try moving the whole last paragraph to bottom
        last = _strip_marker(top_parts[-1], continuation_marker)
        top_candidate = top_parts[:-1]
        if top_candidate:
            fits_candidate, _ = _simulate_frame(_flo(top_candidate), frame_w, frame_h)
            if fits_candidate:
                # Moving the whole paragraph makes it fit
                top_parts.pop()
                bot_parts.insert(0, last)
                fits = True
                break
        # Strategy 2: try moving the last sentence of the last paragraph
        last = _strip_marker(top_parts.pop(), continuation_marker)
        sents = _split_paragraph_by_sentence(last)
        # Filter out any lone continuation markers (strip once, reuse)
        marker_stripped = continuation_marker.strip()
        sents = [s for s in sents if (ss := s.strip()) and ss != marker_stripped]
        if not sents:
            continue
        if len(sents) == 1:
            # Cannot split by sentence; move the whole paragraph
            bot_parts.insert(0, sents[0])
        else:
            tail = sents.pop()
            head = " ".join(sents).strip()
            if head:
                top_parts.append(head)
            bot_parts.insert(0, tail)
        fits, _ = _simulate_frame(_flo(top_parts), frame_w, frame_h)

    # Forced split if still overflowing
    if not fits and top_parts:
        last = _strip_marker(top_parts.pop(), continuation_marker)
        half = len(last) // 2
        a, b = _find_best_split(last, half, max(1, half // 2))
        if a.strip():
            top_parts.append(a + continuation_marker)
        if b.strip():
            bot_parts.insert(0, b)
        fits, _ = _simulate_frame(_flo(top_parts), frame_w, frame_h)
        meta["forced_split_done"] = True
    elif top_parts and meta.get("split_inside_paragraph"):
        # Add continuation marker to the last top paragraph only if a split occurred
        top_parts[-1] = top_parts[-1] + continuation_marker

    meta["final_top_chars"] = sum(len(p) for p in top_parts)
    meta["final_bot_chars"] = sum(len(p) for p in bot_parts)
    meta["final_top_fits"] = fits
    return top_parts, bot_parts, meta


# ===========================================================================
# STAGE 1 — NORMALIZATION
# ===========================================================================

_RE_DIGIT_HEADING = re.compile(r"^\s*(\d{1,3})\.?\s*$")
_RE_NUMBERED_TITLE = re.compile(r"^\s*(\d{1,3})\.\s*\S")  # e.g. "1. THE NATURE…" or "49.THE"
_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_HTML_ENTITY = re.compile(r"&[a-zA-Z]+;|&#?\d+;")


def _clean_text(raw: str) -> str:
    """Strip HTML tags, HTML entities, and normalise whitespace."""
    text = _RE_HTML_TAG.sub(" ", raw)
    text = _RE_HTML_ENTITY.sub(" ", text)
    lines = [" ".join(ln.split()) for ln in text.splitlines()]
    return "\n".join(lines)


def _parse_chapters(text: str) -> dict:
    """
    Parse *text* into ``{chapter_number: chapter_body}``.

    Recognises four heading styles (in priority order):
      A) "N. TITLE…"   — e.g. crowley.txt  ("1. THE NATURE OF THE TAO")
      B) "N" or "N."   — bare digit line, e.g. goddard.txt / gorn.txt
      C) "WordNumber"  — single capitalised English number word, e.g. gia.txt
      D) fallback: entire file as chapter 1.

    Navigation artefacts like stand-alone "up" lines are discarded.
    """
    lines = text.splitlines()
    indices = []
    keys = []

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or line.lower() == "up":
            continue

        # Style A: "N. SOME TITLE"
        m = _RE_NUMBERED_TITLE.match(line)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 81:
                indices.append(i)
                keys.append(n)
                continue

        # Style B: bare digit (possibly with trailing dot)
        m2 = _RE_DIGIT_HEADING.match(line)
        if m2:
            n = int(m2.group(1))
            if 1 <= n <= 81:
                indices.append(i)
                keys.append(n)
                continue

        # Style C: single word that is a known English number
        if re.match(r"^[A-Za-z][a-z-]*$", line):
            wn = WORD_TO_NUM.get(line.lower())
            if wn is not None:
                indices.append(i)
                keys.append(wn)
                continue

    if not indices:
        return {1: text.strip()}

    chapters = {}
    for idx, start_line in enumerate(indices):
        content_start = start_line + 1
        content_end = indices[idx + 1] if idx + 1 < len(indices) else len(lines)
        body_lines = []
        for ln in lines[content_start:content_end]:
            stripped = ln.strip()
            if stripped.lower() == "up":
                continue
            body_lines.append(stripped)
        body = "\n".join(body_lines).strip()
        chapters[keys[idx]] = body

    return chapters


def normalize_tao_files(file_list: list) -> list:
    """
    Stage 1 — Normalization.

    For each file in *file_list*, read raw text, clean HTML artefacts, parse
    chapter headings, and return a dict ``{1: text, ..., 81: text}``.  Missing
    chapters are filled with a placeholder.  Extra chapters beyond 81 are
    discarded.

    Returns a list of dicts in the same order as *file_list*.
    """
    result = []

    for fpath in file_list:
        base = os.path.basename(fpath)
        if not os.path.exists(fpath):
            log.warning("File not found: %s — using all placeholders", fpath)
            placeholder = {
                n: f"[Chapter {n} missing — file {base} not found]"
                for n in range(1, 82)
            }
            result.append(placeholder)
            continue

        log.info("Normalising %s ...", base)
        with open(fpath, encoding="utf-8", errors="replace") as f:
            raw = f.read()
        cleaned = _clean_text(raw)
        chapters = _parse_chapters(cleaned)

        # Normalise to exactly chapters 1-81
        normalised = {}
        for n in range(1, 82):
            text = chapters.get(n, "").strip()
            if text:
                normalised[n] = text
            else:
                normalised[n] = f"[Chapter {n} missing in this translation]"
                log.warning("%s: chapter %d not found — placeholder inserted", base, n)

        found = sum(1 for v in normalised.values() if not v.startswith("[Chapter"))
        log.info("%s: %d / 81 chapters found", base, found)
        result.append(normalised)

    return result


# ===========================================================================
# STAGE 2 — ANALYSIS / SPLITTING
# ===========================================================================

def analyze_chapter_fits(
    chapters_dict: dict,
    frame_w: float = COL_W,
    frame_h: float = FRAME_H,
) -> dict:
    """
    Stage 2 — Analysis.

    For each chapter in *chapters_dict*, compute an optimal top/bottom split
    using rendered measurement.

    Returns::

        {
          1: {"top": "...", "bottom": "...", "fits": True,
              "chars_top": N, "chars_bottom": M},
          ...
        }
    """
    fits_data = {}

    for chap_num in range(1, 82):
        text = chapters_dict.get(chap_num, f"[Chapter {chap_num} missing]")
        top_parts, bot_parts, meta = _split_chapter_text_smart(
            text, frame_w=frame_w, frame_h=frame_h,
        )

        # If top is empty, pull first sentence into it for visual balance
        if not top_parts and bot_parts:
            sents = _split_paragraph_by_sentence(bot_parts[0])
            if sents:
                top_parts = [sents[0] + (CONTINUATION_MARKER if len(sents) > 1 else "")]
                rem = " ".join(sents[1:]).strip()
                if rem:
                    bot_parts[0] = rem
                else:
                    bot_parts.pop(0)

        fits_data[chap_num] = {
            "top": "\n\n".join(top_parts),
            "bottom": "\n\n".join(bot_parts),
            "fits": meta.get("final_top_fits", True),
            "chars_top": meta.get("final_top_chars", sum(len(p) for p in top_parts)),
            "chars_bottom": meta.get("final_bot_chars", sum(len(p) for p in bot_parts)),
        }

    return fits_data


# ===========================================================================
# STAGE 3 — ASSEMBLY
# ===========================================================================

def _build_page_order() -> list:
    """
    Compute (chapter_number,) for each of the 81 PDF pages.

    Each PDF page shows one chapter; its text is split top/bottom within each
    column.  Pages are ordered sequentially (page N = chapter N) so that when
    the book is assembled into 9 signatures of 9 leaves, chapters flow
    consecutively through the book.

    Binding note — for hand-sewing into 9 signatures:
      Signature 1 : PDF pages  1 –  9  (chapters  1 –  9)
      Signature 2 : PDF pages 10 – 18  (chapters 10 – 18)
      ...
      Signature 9 : PDF pages 73 – 81  (chapters 73 – 81)

    Within each signature the top halves read ascending (ch 1,2,…,9) and the
    bottom halves read descending (ch 9,8,…,1) because the signatures are
    folded; chapters "meet" at the centre fold.  Print double-sided on 8.5×11
    paper, fold each group of 9 sheets, and sew together.
    """
    return list(range(1, 82))  # 81 chapter numbers, one per page


def _make_body_style() -> ParagraphStyle:
    styles = getSampleStyleSheet()
    return ParagraphStyle(
        "tao_body",
        parent=styles["BodyText"],
        fontName=FONT_NAME,
        fontSize=FONT_SIZE,
        leading=LEADING,
        spaceAfter=2,
    )


def _draw_column_half(c, paragraphs_text, style, x, y, w, h,
                      show_boundary=False):
    """Render *paragraphs_text* into a Frame at (x, y) with size (w, h)."""
    paras = [p.strip() for p in re.split(r'\n\s*\n', paragraphs_text) if p.strip()]
    flows = _flowables_from_paragraphs(paras, style, w, h, keep_together=True)
    frame = Frame(x, y, w, h,
                  leftPadding=4, rightPadding=4, topPadding=4, bottomPadding=4,
                  showBoundary=1 if show_boundary else 0)
    frame.addFromList(flows, c)


def assemble_bound_pdf(
    chapter_fits_list: list,
    out_path: str = OUT_PDF,
    file_list: list = FILES,
    show_boundary: bool = False,
) -> None:
    """
    Stage 3 — Assembly.

    Parameters
    ----------
    chapter_fits_list : list of dicts
        One dict per translation (in same order as *file_list*).
        Each dict: ``{chap_num: {"top": str, "bottom": str, ...}}``.
    out_path : str
        Output PDF path.
    file_list : list[str]
        Source file names (for metadata / column labels).
    show_boundary : bool
        Draw visible frame borders (useful for debugging).
    """
    page_order = _build_page_order()
    style = _make_body_style()

    c = canvas.Canvas(out_path, pagesize=letter)

    # Column x-positions (left edge of each column frame)
    col_xs = [MARGIN + i * (COL_W + SMALL_GAP) for i in range(NUM_COLS)]
    # y-positions: top half sits above centre gap, bottom half below it
    top_y = MARGIN + FRAME_H + VERT_CENTER_GAP
    bot_y = MARGIN

    total_pages = len(page_order)
    log.info("Assembling %d pages into %s ...", total_pages, out_path)

    for page_idx, chap_num in enumerate(page_order):
        page_num = page_idx + 1
        log.info("  Page %d / %d  (chapter %d)", page_num, total_pages, chap_num)

        for col_idx in range(NUM_COLS):
            x = col_xs[col_idx]
            col_fits = chapter_fits_list[col_idx] if col_idx < len(chapter_fits_list) else {}
            entry = col_fits.get(chap_num, {})

            # Top half: first portion of chapter text
            top_text = entry.get("top", f"[ch {chap_num} top]")
            _draw_column_half(c, top_text, style, x, top_y, COL_W, FRAME_H, show_boundary)

            # Bottom half: second portion of chapter text
            bot_text = entry.get("bottom", f"[ch {chap_num} bottom]")
            _draw_column_half(c, bot_text, style, x, bot_y, COL_W, FRAME_H, show_boundary)

        # Faint centre-gap rectangle (visual guide for binding gutter)
        c.setStrokeColorRGB(0.80, 0.80, 0.80)
        gap_y = MARGIN + FRAME_H
        c.rect(MARGIN - 1, gap_y, TEXT_W + 2, VERT_CENTER_GAP, stroke=1, fill=0)

        # Chapter number and page footer
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        footer = f"Chapter {chap_num}  |  {page_num}"
        c.drawCentredString(PAGE_W / 2, MARGIN / 2, footer)

        c.showPage()

    c.save()
    log.info("PDF written: %s  (%d pages)", out_path, total_pages)


# ===========================================================================
# MAIN WORKFLOW
# ===========================================================================

def main() -> None:
    """Run all three stages sequentially and produce the bound PDF."""
    # Resolve file paths relative to the script's directory so the script can
    # be run from any working directory.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_paths = [os.path.join(script_dir, f) for f in FILES]

    # ---- Stage 1: Normalise ------------------------------------------------
    log.info("=" * 60)
    log.info("STAGE 1 -- Normalisation")
    log.info("=" * 60)
    all_chapter_dicts = normalize_tao_files(file_paths)

    # ---- Stage 2: Analyse --------------------------------------------------
    log.info("=" * 60)
    log.info("STAGE 2 -- Analysis (rendering + splitting)")
    log.info("=" * 60)
    all_fits = []
    for i, chap_dict in enumerate(all_chapter_dicts):
        base = os.path.basename(file_paths[i])
        log.info("Analysing %s ...", base)
        fits = analyze_chapter_fits(chap_dict, frame_w=COL_W, frame_h=FRAME_H)
        all_fits.append(fits)
        overflow_count = sum(1 for v in fits.values() if not v.get("fits", True))
        log.info("  %s: %d chapters analysed, %d with top overflow",
                 base, len(fits), overflow_count)

    # ---- Stage 3: Assemble -------------------------------------------------
    log.info("=" * 60)
    log.info("STAGE 3 -- Assembly (PDF generation)")
    log.info("=" * 60)
    out_path = os.path.join(script_dir, OUT_PDF)
    assemble_bound_pdf(all_fits, out_path=out_path, file_list=file_paths)

    log.info("=" * 60)
    log.info("Done.  Output: %s", out_path)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
