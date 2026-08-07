#!/usr/bin/env python3
"""
tao_normalize.py — Normalize and split Tao Te Ching translation files into
                   per-chapter top/bottom JSON exports for audio synthesis.

What it does:
    1. Reads each of the five raw translation .txt files.
    2. Strips HTML artefacts and normalises whitespace.
    3. Detects chapter boundaries (four heading formats: bare digit, "N. TITLE",
       English word-number, navigation "up" dividers).
    4. Splits each chapter body into a ``top`` half and a ``bottom`` half by
       character count (targeting 50/50, max MAX_HALF_CHARS per half).
    5. Writes one JSON file per translation, e.g.::

           goddard_normalized.json
           anon_normalized.json
           gia_normalized.json
           crowley_normalized.json
           gorn_normalized.json

       Each JSON has the structure::

           {
             "1": {"top": "...", "bottom": "..."},
             "2": {"top": "...", "bottom": "..."},
             ...
             "81": {"top": "...", "bottom": "..."}
           }

Usage:
    python tao_normalize.py                  # processes all five files
    python tao_normalize.py --out-dir ./out  # custom output directory

Dependencies:
    Standard library only (os, re, json, argparse, logging).
    Place this script in the same directory as the five .txt files.
"""

import argparse
import json
import logging
import os
import re

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
#: Raw translation files (in column order: goddard, anon, gia, crowley, gorn).
FILES: list[str] = [
    "goddard.txt",
    "anon.txt",
    "gia.txt",
    "crowley.txt",
    "gorn.txt",
]

#: Maximum characters per top or bottom half.
#: Chapters longer than 2×MAX_HALF_CHARS are truncated at sentence boundaries.
MAX_HALF_CHARS: int = 750

#: Sentence-end pattern used when splitting text at boundaries.
_SENT_END_RE = re.compile(r'(?<=[.?!])["\']?\s+')

# ---------------------------------------------------------------------------
# English number-word → integer mapping (One … Eighty-One)
# ---------------------------------------------------------------------------
WORD_TO_NUM: dict[str, int] = {
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
# Heading detection regexes
# ---------------------------------------------------------------------------
_RE_DIGIT_HEADING = re.compile(r"^\s*(\d{1,3})\.?\s*$")
_RE_NUMBERED_TITLE = re.compile(r"^\s*(\d{1,3})\.\s*\S")  # "1. THE TAO" or "49.THE"
_RE_HTML_TAG = re.compile(r"<[^>]+>")
_RE_HTML_ENTITY = re.compile(r"&[a-zA-Z]+;|&#?\d+;")


# ===========================================================================
# Internal helpers
# ===========================================================================

def _clean_text(raw: str) -> str:
    """Strip HTML tags, HTML entities, and collapse intra-line whitespace."""
    text = _RE_HTML_TAG.sub(" ", raw)
    text = _RE_HTML_ENTITY.sub(" ", text)
    lines = [" ".join(ln.split()) for ln in text.splitlines()]
    return "\n".join(lines)


def _parse_chapters(text: str) -> dict[int, str]:
    """
    Parse *text* into ``{chapter_number: chapter_body}``.

    Recognised heading styles (checked in priority order):
      A) "N. TITLE…"   — e.g. crowley.txt ("1. THE NATURE OF THE TAO")
      B) "N" or "N."   — bare digit line (goddard.txt, gorn.txt)
      C) "WordNumber"  — single English number word (gia.txt: "One", "Two" …)
      D) Fallback: treat entire file as chapter 1.

    Lines consisting only of "up" are silently discarded.
    """
    lines = text.splitlines()
    indices: list[int] = []
    keys: list[int] = []

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

        # Style C: single English word-number
        if re.match(r"^[A-Za-z][a-z-]*$", line):
            wn = WORD_TO_NUM.get(line.lower())
            if wn is not None:
                indices.append(i)
                keys.append(wn)
                continue

    if not indices:
        return {1: text.strip()}

    chapters: dict[int, str] = {}
    for idx, start_line in enumerate(indices):
        content_start = start_line + 1
        content_end = indices[idx + 1] if idx + 1 < len(indices) else len(lines)
        body_lines = [
            ln.strip()
            for ln in lines[content_start:content_end]
            if ln.strip().lower() != "up"
        ]
        body = "\n".join(body_lines).strip()
        chapters[keys[idx]] = body

    return chapters


def _find_sentence_split(text: str, desired: int, radius: int = 120) -> int:
    """
    Return the best character offset near *desired* (±*radius*) at a
    sentence boundary, then word boundary, then exactly *desired*.
    """
    n = len(text)
    desired = max(0, min(n, desired))
    lo = max(0, desired - radius)
    hi = min(n, desired + radius)

    sent_positions = [m.start() for m in _SENT_END_RE.finditer(text)]
    cands = [p for p in sent_positions if lo <= p <= hi]
    if cands:
        return min(cands, key=lambda x: abs(x - desired))

    ws_positions = [m.start() for m in re.finditer(r"\s+", text)]
    cands = [p for p in ws_positions if lo <= p <= hi]
    if cands:
        return min(cands, key=lambda x: abs(x - desired))

    return desired


def _split_chapter(body: str, max_half: int = MAX_HALF_CHARS) -> tuple[str, str]:
    """
    Split *body* into (top, bottom) halves.

    Strategy:
      1. Join all lines/paragraphs into a single string (paragraph breaks
         become double-spaces for natural TTS pacing).
      2. Always split at the 50% character point (snapped to the nearest
         sentence boundary ±120 chars) — even for short chapters.
      3. If either half exceeds *max_half* chars, truncate at a sentence
         boundary near *max_half* (audio chunks should stay compact).
      4. Very short chapters (< 20 chars) go entirely to top with empty bottom.

    Returns (top_text, bottom_text).
    """
    # Collapse paragraphs into a flat string; preserve paragraph rhythm as
    # double-spaces for natural TTS pacing.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    flat = "  ".join(" ".join(p.split()) for p in paragraphs)

    if not flat:
        return ("", "")

    total = len(flat)

    # Very short: no meaningful split possible
    if total < 20:
        return (flat.strip(), "")

    # Always target the 50% point (never skip the split)
    desired = total // 2
    split_at = _find_sentence_split(flat, desired)

    # Guard: split_at must not leave the top empty or the bottom empty.
    # If the snap landed at the very start, push forward by a quarter.
    if split_at < max(10, total // 10):
        split_at = _find_sentence_split(flat, total // 3, radius=200)
    # If the snap landed at the very end, pull back by a quarter.
    if split_at > total - max(10, total // 10):
        split_at = _find_sentence_split(flat, 2 * total // 3, radius=200)

    top = flat[:split_at].strip()
    bottom = flat[split_at:].strip()

    # Enforce max_half on each side by truncating at a sentence boundary
    if len(top) > max_half:
        cut = _find_sentence_split(top, max_half, radius=150)
        top = top[:cut].strip()

    if len(bottom) > max_half:
        cut = _find_sentence_split(bottom, max_half, radius=150)
        bottom = bottom[:cut].strip()

    return (top, bottom)


# ===========================================================================
# Public API
# ===========================================================================

def normalize_and_split(
    files_list: list[str],
    max_half: int = MAX_HALF_CHARS,
) -> dict[str, dict[str, dict[str, str]]]:
    """
    Parse, normalise, and split each file in *files_list*.

    Returns a dict keyed by translation name (file basename without extension)::

        {
          "goddard": {
            "1": {"top": "...", "bottom": "..."},
            ...
            "81": {"top": "...", "bottom": "..."}
          },
          "anon": { ... },
          ...
        }

    Missing chapters are represented with placeholder text so the result
    always contains exactly keys ``"1"`` through ``"81"`` for each translation.
    """
    result: dict[str, dict[str, dict[str, str]]] = {}

    for fpath in files_list:
        base = os.path.basename(fpath)
        name = os.path.splitext(base)[0]

        if not os.path.exists(fpath):
            log.warning("File not found: %s — using placeholders", fpath)
            result[name] = {
                str(n): {
                    "top": f"[Chapter {n} missing — file {base} not found]",
                    "bottom": "",
                }
                for n in range(1, 82)
            }
            continue

        log.info("Normalising %s ...", base)
        with open(fpath, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()

        cleaned = _clean_text(raw)
        chapters = _parse_chapters(cleaned)

        translation: dict[str, dict[str, str]] = {}
        for n in range(1, 82):
            body = chapters.get(n, "").strip()
            if not body:
                log.warning("%s: chapter %d not found — placeholder inserted", base, n)
                body = f"[Chapter {n} missing in this translation]"

            top, bottom = _split_chapter(body, max_half=max_half)
            translation[str(n)] = {"top": top, "bottom": bottom}

        found = sum(
            1 for v in translation.values()
            if not v["top"].startswith("[Chapter")
        )
        log.info("%s: %d / 81 chapters found and split", base, found)
        result[name] = translation

    return result


def write_json_files(
    normalised: dict[str, dict[str, dict[str, str]]],
    out_dir: str = ".",
    suffix: str = "_normalized",
) -> list[str]:
    """
    Write one JSON file per translation into *out_dir*.

    Returns the list of written file paths.
    """
    os.makedirs(out_dir, exist_ok=True)
    written: list[str] = []
    for name, chapters in normalised.items():
        out_path = os.path.join(out_dir, f"{name}{suffix}.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(chapters, fh, ensure_ascii=False, indent=2)
        log.info("Wrote %s (%d chapters)", out_path, len(chapters))
        written.append(out_path)
    return written


# ===========================================================================
# CLI entry point
# ===========================================================================

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Normalize Tao Te Ching translation files and export top/bottom JSON splits."
    )
    p.add_argument(
        "--files",
        nargs="+",
        default=None,
        help="Translation .txt files to process (default: all five standard files).",
    )
    p.add_argument(
        "--out-dir",
        default=".",
        help="Directory to write output JSON files (default: current directory).",
    )
    p.add_argument(
        "--max-half",
        type=int,
        default=MAX_HALF_CHARS,
        help=f"Maximum characters per top/bottom half (default: {MAX_HALF_CHARS}).",
    )
    return p


def main() -> None:
    """CLI entry point — run normalization and write JSON output files."""
    args = _build_arg_parser().parse_args()

    # Resolve file paths relative to the script's own directory so the script
    # can be run from any working directory.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if args.files:
        file_list = [
            f if os.path.isabs(f) else os.path.join(script_dir, f)
            for f in args.files
        ]
    else:
        file_list = [os.path.join(script_dir, f) for f in FILES]

    log.info("=" * 60)
    log.info("tao_normalize.py — Normalization + Split")
    log.info("=" * 60)
    log.info("Files: %s", [os.path.basename(f) for f in file_list])
    log.info("Output dir: %s", args.out_dir)
    log.info("Max half chars: %d", args.max_half)

    normalised = normalize_and_split(file_list, max_half=args.max_half)
    written = write_json_files(normalised, out_dir=args.out_dir)

    log.info("=" * 60)
    log.info("Done. Written %d JSON files:", len(written))
    for path in written:
        log.info("  %s", path)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
