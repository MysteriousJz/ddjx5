#!/usr/bin/env python3
"""
Split chapters visually by measured fit and produce a one-page proof.

What it does (per run):
- For each of the five translation files (left→right: goddard, anon, gia, crowley, gorn)
  it extracts the requested chapter (fallback to whole file if chapter not found),
  computes a character-based 50% split target, then finds a tasteful split point
  (prefer sentence boundary within a radius, else word boundary), and refines the
  top half by measuring rendered layout inside the actual column half-frame.
- If the top half overflows visually, the script iteratively moves the last sentence
  (or word) to the bottom half until the top fits. If forced, it will split a long
  paragraph and insert a continuation marker (user requested).
- Emits:
  - printed diagnostics to the console (counts, split info, whether mid-paragraph split),
  - per-file top/bottom text files named <file>_ch<N>_top.txt and ..._bottom.txt,
  - a PDF proof file split_proof_ch<N>.pdf showing the five columns (visible boundaries).

Defaults chosen per your instructions:
- font size: 11 pt (Comic Sans if available, else DejaVu/Helvetica)
- counting spaces for character totals
- target ratio: 0.5
- prefer sentence boundary within +/- 120 chars
- continuation marker when forced-splitting: " —"

Usage:
    python3 make_split_and_proof.py --chapter 1

Dependencies:
    reportlab

Place this script next to your five .txt files and run as above.
"""

import os
import re
import io
import sys
import argparse
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Frame, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------- User / layout configuration ----------
FILES = ["goddard.txt", "anon.txt", "gia.txt", "crowley.txt", "gorn.txt"]
OUT_PDF_TEMPLATE = "split_proof_ch{n}.pdf"
OUT_TOP_TEMPLATE = "{base}_ch{n}_top.txt"
OUT_BOT_TEMPLATE = "{base}_ch{n}_bottom.txt"

PAGE_W, PAGE_H = letter
MARGIN = 0.5 * inch                 # page margins
TEXT_W = PAGE_W - 2 * MARGIN
TEXT_H = PAGE_H - 2 * MARGIN

NUM_COLS = 5
SMALL_GAP = 0.125 * inch            # small horizontal gap between columns
VERT_CENTER_GAP = 0.5 * inch        # dead strip across middle (user requested)
COL_W = (TEXT_W - (NUM_COLS - 1) * SMALL_GAP) / NUM_COLS
FRAME_H = (TEXT_H - VERT_CENTER_GAP) / 2.0

FONT_SIZE = 11
LEADING = FONT_SIZE + 2

TARGET_RATIO = 0.5
SENTENCE_RADIUS = 120               # chars to search for a sentence boundary near split point
CONTINUATION_MARKER = " —"          # appended if forced paragraph split

# ---------- font registration ----------
def register_font_try():
    # try Comic Sans first on common locations, then DejaVu, then fallback
    candidates = [
        "Comic_Sans_MS.ttf", "ComicSansMS.ttf", "comic.ttf", "ComicSans.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Comic_Sans_MS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont("UserF", p))
                return "UserF"
            except Exception:
                continue
    # nothing found - use standard Helvetica
    return "Helvetica"

FONT_NAME = register_font_try()

# ---------- parsing helpers ----------
def parse_chapters_from_text(text):
    """
    Returns a dict mapping chapter number -> chapter text.
    Detects numeric-only headings (lines like '1' or '1.') or single-word spelled numbers
    ("One", "Two") followed by a blank line as chapter headings.
    If none are detected returns {1: text}.
    """
    lines = text.splitlines()
    indices = []
    keys = []
    for i, L in enumerate(lines):
        s = L.strip()
        if re.match(r'^\d{1,3}\.?$', s):
            indices.append(i)
            keys.append(int(re.match(r'^(\d{1,3})', s).group(1)))
            continue
        if s and len(s.split()) == 1 and i + 1 < len(lines) and lines[i+1].strip() == '':
            word = s.lower()
            numwords = {
                "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
                "twenty": 20
            }
            if word in numwords:
                indices.append(i)
                keys.append(numwords[word])
    if not indices:
        return {1: text.strip()}
    chapters = {}
    for idx, start_idx in enumerate(indices):
        start = start_idx + 1
        end = indices[idx + 1] if idx + 1 < len(indices) else len(lines)
        chap_text = "\n".join(lines[start:end]).strip()
        chapters[keys[idx]] = chap_text
    return chapters

def load_chapter_from_file(path, chapnum):
    text = open(path, encoding='utf-8').read()
    cmap = parse_chapters_from_text(text)
    if chapnum in cmap and cmap[chapnum].strip():
        return cmap[chapnum].strip()
    # fallback: if no named chapter then return whole text
    return text.strip()

# ---------- splitting helpers ----------
_SENTENCE_BOUNDARY_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?]["\'])\s+')

def split_paragraph_by_sentence(paragraph):
    """
    Split a paragraph into sentences using a sentence-boundary regex.
    Returns list of sentence strings (sentences keep their trailing punctuation).
    """
    # Use regex split that keeps punctuation part of sentence; _SENTENCE_BOUNDARY_RE splits at boundary.
    parts = _SENTENCE_BOUNDARY_RE.split(paragraph.strip())
    parts = [p for p in parts if p.strip()]
    return parts if parts else [paragraph]

def find_best_split_within(paragraph, desired_index, radius=SENTENCE_RADIUS):
    """
    Try to split 'paragraph' near desired_index (character offset) at a sensible boundary.
    1) Prefer sentence boundary nearest to desired_index inside ±radius.
    2) If none, prefer a whitespace (word) boundary nearest to desired_index inside ±radius.
    3) As last resort, hard split at desired_index.
    Returns (first_part, second_part) strings.
    """
    para = paragraph.strip()
    n = len(para)
    desired = max(0, min(n, desired_index))
    lo = max(0, desired - radius)
    hi = min(n, desired + radius)

    # sentence boundaries: find indexes of sentence ends (positions after which a split is valid)
    sent_splits = []
    for m in _SENTENCE_BOUNDARY_RE.finditer(para):
        pos = m.start() + 0  # split position
        sent_splits.append(pos)
    # choose sentence split within [lo, hi] closest to desired
    candidates = [s for s in sent_splits if lo <= s <= hi]
    if candidates:
        best = min(candidates, key=lambda p: abs(p - desired))
        return para[:best].rstrip(), para[best:].lstrip()
    # fallback to whitespace split
    white_positions = [m.start() for m in re.finditer(r'\s+', para)]
    candidates = [p for p in white_positions if lo <= p <= hi]
    if candidates:
        best = min(candidates, key=lambda p: abs(p - desired))
        return para[:best].rstrip(), para[best:].lstrip()
    # hard split
    return para[:desired].rstrip(), para[desired:].lstrip()

# ---------- rendering/measurement helpers ----------
def flowables_from_paragraphs(paragraphs, style, frame_w, frame_h, keep_together_threshold=True):
    """
    Convert paragraph strings to ReportLab flowables.
    For paragraphs that are shorter than frame_h in rendered height, wrap them in KeepTogether
    to avoid splitting across the half if possible. Otherwise return Paragraph (allow split).
    Returns list of flowables.
    """
    result = []
    for p in paragraphs:
        p_single = Paragraph(p.replace('\n', ' '), style)
        # measure height by wrapping
        w, h = p_single.wrap(frame_w - 8, frame_h)  # small padding
        if keep_together_threshold and h <= frame_h:
            result.append(KeepTogether([p_single]))
        else:
            result.append(p_single)
    return result

def simulate_frame_draw(flowables, frame_w, frame_h):
    """
    Simulate drawing flowables into an empty frame with given size and return boolean (fits_all)
    and leftover_flowables (the ones not drawn).
    """
    buf = io.BytesIO()
    tmpc = canvas.Canvas(buf, pagesize=letter)
    f = Frame(0, 0, frame_w, frame_h, leftPadding=6, rightPadding=6, topPadding=6, bottomPadding=6)
    # work on a mutable copy
    copy_list = [fv for fv in flowables]
    f.addFromList(copy_list, tmpc)
    # copy_list now contains leftovers (not drawn)
    fits_all = len(copy_list) == 0
    return fits_all, copy_list

# ---------- core algorithm ----------
def compute_char_target(paragraphs, ratio=TARGET_RATIO, count_spaces=True):
    if count_spaces:
        total = sum(len(p) for p in paragraphs)
    else:
        total = sum(len(p.replace(' ', '')) for p in paragraphs)
    target = int(round(total * ratio))
    return total, target

def split_chapter_text_smart(chap_text, frame_w, frame_h, fontname=FONT_NAME, fontsize=FONT_SIZE,
                             target_ratio=TARGET_RATIO, sentence_radius=SENTENCE_RADIUS,
                             continuation_marker=CONTINUATION_MARKER):
    """
    Given a single chapter text (string), compute a top/bottom split that aims for target_ratio
    in characters, prefers paragraph boundaries, and uses rendered measurement to refine.
    Returns:
        top_paragraphs: list[str]
        bottom_paragraphs: list[str]
        metadata: dict with diagnostic info
    """
    # normalize paragraphs by splitting on blank lines
    paras = [p.strip() for p in re.split(r'\n\s*\n', chap_text) if p.strip()]
    if not paras:
        return [], [], {"note": "empty"}

    total_chars, target_chars = compute_char_target(paras, ratio=target_ratio, count_spaces=True)

    # Walk paragraphs accumulating chars until we pass target
    acc = 0
    top_parts = []
    bottom_parts = []
    split_info = {
        "total_chars": total_chars,
        "target_chars": target_chars,
        "initial_paragraph_count": len(paras),
        "split_at_paragraph_index": None,
        "split_inside_paragraph": False
    }

    for i, p in enumerate(paras):
        p_len = len(p)
        if acc + p_len <= target_chars:
            top_parts.append(p)
            acc += p_len
            continue
        # Adding this full paragraph would exceed target. Try to split this paragraph if it's lengthy.
        remaining_desired = target_chars - acc
        if remaining_desired <= 0:
            # nothing more in top, push all remaining paras to bottom
            bottom_parts = paras[i:]
            split_info["split_at_paragraph_index"] = i
            break
        # attempt to split this paragraph near desired point
        first, second = find_best_split_within(p, remaining_desired, radius=sentence_radius)
        # if first is empty (no good split), put whole paragraph to bottom
        if not first.strip():
            bottom_parts = paras[i:]
            split_info["split_at_paragraph_index"] = i
            break
        # otherwise use first in top, second + rest in bottom
        top_parts.append(first + (continuation_marker if len(second.strip()) > 0 else ''))
        bottom_parts = [second] + paras[i+1:]
        split_info["split_at_paragraph_index"] = i
        split_info["split_inside_paragraph"] = True
        break
    else:
        # loop finished without break: all paras fit in top (rare). bottom empty.
        bottom_parts = []

    # If we didn't set split_at_paragraph_index (all top or top empty), set appropriately
    if split_info["split_at_paragraph_index"] is None:
        split_info["split_at_paragraph_index"] = len(top_parts)

    # Now refine by measuring with ReportLab and moving minimal units from top to bottom until fit.
    styles = getSampleStyleSheet()
    body = ParagraphStyle('body', parent=styles['BodyText'], fontName=fontname, fontSize=fontsize, leading=LEADING)

    # Convert top_parts to flowables
    def make_flowables_from_strings(str_paras):
        return flowables_from_paragraphs(str_paras, body, frame_w, frame_h, keep_together_threshold=True)

    top_flowables = make_flowables_from_strings(top_parts)
    fits, leftovers = simulate_frame_draw(top_flowables, frame_w, frame_h)
    # If it fits, we're done. If not, we must iteratively move the last sentence(s) to bottom.
    moved_count = 0
    safety = 0
    while not fits and top_parts and safety < 500:
        safety += 1
        # Take last paragraph string
        last_para = top_parts.pop()
        moved_count += 1
        # Try to move last sentence from last_para to the front of bottom_parts
        sentences = split_paragraph_by_sentence(last_para)
        if len(sentences) <= 1:
            # no clear sentence splits; split on whitespace into words and move a chunk
            words = last_para.split()
            if len(words) <= 1:
                # single unbreakable token: move whole paragraph to bottom
                bottom_parts.insert(0, last_para)
            else:
                # move approx half of words to bottom (prefer small move)
                take = max(1, len(words) // 6)  # move a small tail
                tail = " ".join(words[-take:])
                head = " ".join(words[:-take])
                if head.strip():
                    top_parts.append(head + continuation_marker)
                bottom_parts.insert(0, tail)
        else:
            # move the last sentence to bottom; if last_para ended with continuation marker, keep that marker convention
            # We'll move sentences until the top fits.
            # Move the last sentence
            tail_sentence = sentences.pop()
            head = " ".join(sentences).strip()
            if head:
                # if head is non-empty, put it back into top_parts (with continuation if tail remains)
                top_parts.append(head + continuation_marker)
            bottom_parts.insert(0, tail_sentence)
        # re-evaluate fit
        top_flowables = make_flowables_from_strings(top_parts)
        fits, leftovers = simulate_frame_draw(top_flowables, frame_w, frame_h)
    split_info["moved_units_due_to_rendering"] = moved_count
    split_info["render_fits_top"] = fits

    # If safety breached and still not fits, we will forced-split the last top paragraph aggressively:
    if not fits and top_parts:
        # forced break: split last paragraph at ~half
        last = top_parts.pop()
        half = len(last) // 2
        a, b = find_best_split_within(last, half, radius=half // 2)
        if a.strip():
            top_parts.append(a + continuation_marker)
        if b.strip():
            bottom_parts.insert(0, b)
        # One more measurement
        top_flowables = make_flowables_from_strings(top_parts)
        fits, leftovers = simulate_frame_draw(top_flowables, frame_w, frame_h)
        split_info["forced_split_done"] = True
    split_info["final_top_paragraph_count"] = len(top_parts)
    split_info["final_bottom_paragraph_count"] = len(bottom_parts)
    split_info["final_top_chars"] = sum(len(p) for p in top_parts)
    split_info["final_bottom_chars"] = sum(len(p) for p in bottom_parts)
    split_info["final_top_fits"] = fits

    return top_parts, bottom_parts, split_info

# ---------- output helpers ----------
def write_text_file(path, paragraphs):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(paragraphs))

def render_proof_pdf(chapter_num, tops_by_file, bots_by_file, out_pdf_path, fontname=FONT_NAME, fontsize=FONT_SIZE):
    c = canvas.Canvas(out_pdf_path, pagesize=letter)
    styles = getSampleStyleSheet()
    body = ParagraphStyle('body', parent=styles['BodyText'], fontName=fontname, fontSize=fontsize, leading=LEADING)
    # draw each column top and bottom
    xs = [MARGIN + i * (COL_W + SMALL_GAP) for i in range(NUM_COLS)]
    top_y = MARGIN + FRAME_H + VERT_CENTER_GAP
    bottom_y = MARGIN
    for i in range(NUM_COLS):
        # top frame
        top_frame = Frame(xs[i], top_y, COL_W, FRAME_H, leftPadding=6, rightPadding=6, topPadding=6, bottomPadding=6, showBoundary=1)
        bot_frame = Frame(xs[i], bottom_y, COL_W, FRAME_H, leftPadding=6, rightPadding=6, topPadding=6, bottomPadding=6, showBoundary=1)
        # create flowables and add
        top_flow = flowables_from_paragraphs(tops_by_file[i], body, COL_W, FRAME_H)
        bot_flow = flowables_from_paragraphs(bots_by_file[i], body, COL_W, FRAME_H)
        top_frame.addFromList(top_flow, c)
        bot_frame.addFromList(bot_flow, c)
    # draw a faint rect for center gap for clarity
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    dead_y = MARGIN + FRAME_H
    c.rect(MARGIN - 1, dead_y, TEXT_W + 2, VERT_CENTER_GAP, stroke=1, fill=0)
    c.showPage()
    c.save()

# ---------- main entry ----------
def run_for_chapter(chap_num, out_prefix=None):
    files_missing = [f for f in FILES if not os.path.exists(f)]
    if files_missing:
        print("Missing files:", files_missing)
        return

    tops_by_file = []
    bots_by_file = []
    metadata_by_file = []

    print("Running split/measure for chapter", chap_num)
    for fname in FILES:
        base = os.path.splitext(os.path.basename(fname))[0]
        chap_text = load_chapter_from_file(fname, chap_num)
        top_parts, bottom_parts, meta = split_chapter_text_smart(
            chap_text, frame_w=COL_W, frame_h=FRAME_H,
            fontname=FONT_NAME, fontsize=FONT_SIZE,
            target_ratio=TARGET_RATIO, sentence_radius=SENTENCE_RADIUS,
            continuation_marker=CONTINUATION_MARKER
        )
        # Ensure non-empty top for visibility: if top_parts empty, move first sentence from bottom to top
        if not top_parts and bottom_parts:
            # split first bottom para into sentence(s)
            sents = split_paragraph_by_sentence(bottom_parts[0])
            if sents:
                top_parts = [sents[0] + CONTINUATION_MARKER] if len(sents) > 1 else [sents[0]]
                # reduce the first bottom paragraph
                rem = " ".join(sents[1:]).strip()
                if rem:
                    bottom_parts[0] = rem
                else:
                    bottom_parts.pop(0)
                meta["top_was_empty_forced_fill"] = True

        tops_by_file.append(top_parts)
        bots_by_file.append(bottom_parts)
        metadata_by_file.append((fname, meta))

        # write top/bottom text files for inspection
        out_top = (out_prefix + "_" + base + f"_ch{chap_num}_top.txt") if out_prefix else OUT_TOP_TEMPLATE.format(base=base, n=chap_num)
        out_bot = (out_prefix + "_" + base + f"_ch{chap_num}_bottom.txt") if out_prefix else OUT_BOT_TEMPLATE.format(base=base, n=chap_num)
        write_text_file(out_top, top_parts)
        write_text_file(out_bot, bottom_parts)

    # print diagnostics
    print("\nDiagnostics per file (filename: key -> value):")
    for fname, meta in metadata_by_file:
        print("-" * 60)
        print(os.path.basename(fname))
        for k, v in meta.items():
            print(f"  {k}: {v}")
    # render PDF proof
    out_pdf = (out_prefix + f"_split_proof_ch{chap_num}.pdf") if out_prefix else OUT_PDF_TEMPLATE.format(n=chap_num)
    render_proof_pdf(chap_num, tops_by_file, bots_by_file, out_pdf, fontname=FONT_NAME, fontsize=FONT_SIZE)
    print("\nWrote proof pdf:", out_pdf)
    print("Also wrote *_top.txt and *_bottom.txt for each input file in the current directory.")

# ---------- CLI ----------
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Split chapter text into top/bottom halves by visual measurement and write a proof PDF.")
    p.add_argument("--chapter", "-c", type=int, default=1, help="chapter number to process")
    p.add_argument("--outprefix", "-o", default=None, help="optional prefix for output files")
    args = p.parse_args()
    run_for_chapter(args.chapter, out_prefix=args.outprefix)
