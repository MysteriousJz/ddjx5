#!/usr/bin/env python3
"""Generate six bilingual Tao Te Ching audiobooks from three English editions.

The script deliberately keeps extraction and synthesis separate so the text can
be checked without loading Piper.  Every audiobook uses the same Chinese Text
Project source, paired with one of the three English exports below.
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import re
import tempfile
import wave
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHINESE_SOURCE = ROOT / "Dao De Jing - Chinese Text Project.html"
TRANSLATIONS = {
    "arthur_waley": ("Arthur Waley", ROOT / "txt_exports/Arthur_Waley.txt"),
    "dc_lau": ("D.C. Lau", ROOT / "txt_exports/D_C_Lau.txt"),
    "stephen_mitchell": ("Stephen Mitchell", ROOT / "txt_exports/Stephen_Mitchell.txt"),
}
EXPECTED_TRANSLATION_COUNT = 3
SLOW_SPEED = 0.7
NORMAL_SPEED = 1.0
PAUSE_BETWEEN_VERSES = 0.3
PAUSE_BETWEEN_CHAPTERS = 1.0
SAMPLE_RATE = 22050
BITRATE = "192k"
log = logging.getLogger(__name__)


def _split(text: str, punctuation: str) -> list[str]:
    """Split at sentence punctuation while retaining punctuation in each unit."""
    return [part.strip() for part in re.split(f"(?<=[{punctuation}])", text) if part.strip()]


class _ChineseParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chapter: int | None = None
        self.in_target = False
        self.in_nested = 0
        self.parts: dict[int, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            match = re.fullmatch(r"n(\d+)", attrs_dict.get("id", "") or "")
            self.chapter = int(match.group(1)) - 11591 if match else None
            if self.chapter is not None and not 1 <= self.chapter <= 81:
                self.chapter = None
        elif tag == "td" and self.chapter is not None:
            classes = (attrs_dict.get("class") or "").split()
            if "ctext" in classes and "opt" not in classes:
                self.in_target = True
                self.in_nested = 0
        elif self.in_target:
            self.in_nested += 1

    def handle_endtag(self, tag: str) -> None:
        if self.in_target and tag == "td" and self.in_nested == 0:
            self.in_target = False
        elif self.in_target and self.in_nested:
            self.in_nested -= 1
        elif tag == "tr":
            self.chapter = None

    def handle_data(self, data: str) -> None:
        if self.in_target:
            self.parts.setdefault(self.chapter, []).append(data)  # type: ignore[arg-type]


def extract_chinese(path: Path = CHINESE_SOURCE) -> dict[int, list[str]]:
    parser = _ChineseParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return {n: _split(html.unescape("".join(parser.parts.get(n, []))), "。；")
            for n in range(1, 82)}


def extract_english(path: Path) -> dict[int, list[str]]:
    """Parse numbered exports and split their chapter prose into verses."""
    chapters: dict[int, list[str]] = {}
    current: int | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        match = re.fullmatch(r"(\d{1,2})\.?", line)
        if match and 1 <= int(match.group(1)) <= 81:
            chapter = int(match.group(1))
            # Some exports contain an appended, alternate edition.  Keep the
            # first complete occurrence rather than replacing it.
            if chapter in chapters:
                current = None
            else:
                current = chapter
                chapters[current] = []
        elif current is not None and line:
            chapters[current].append(line)
    return {n: _split(" ".join(chapters.get(n, [])), ".;") for n in range(1, 82)}


def pair_verses(chinese: list[str], english: list[str]) -> list[tuple[str, str]]:
    """Pair verses and merge surplus units when punctuation styles differ."""
    if not chinese or not english:
        return []
    if len(chinese) == len(english):
        return list(zip(chinese, english))
    log.warning("Verse count mismatch: Chinese=%d English=%d", len(chinese), len(english))
    target = len(chinese)
    if len(english) > target:
        # Preserve all text by joining adjacent English units into target groups.
        groups = [english[i * len(english) // target:(i + 1) * len(english) // target]
                  for i in range(target)]
        english = [" ".join(group) for group in groups]
    else:
        groups = [chinese[i * len(chinese) // len(english):(i + 1) * len(chinese) // len(english)]
                  for i in range(len(english))]
        chinese = ["".join(group) for group in groups]
    return list(zip(chinese, english))


def _silence(seconds: float, sample_width: int = 2, channels: int = 1) -> bytes:
    return b"\0" * int(SAMPLE_RATE * max(seconds, 0) * sample_width * channels)


def _synthesize(voice, text: str, speed: float) -> tuple[bytes, int, int, int]:
    from piper.voice import SynthesisConfig
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as output:
        voice.synthesize_wav(text, output,
                             syn_config=SynthesisConfig(length_scale=1.0 / speed))
    raw = buf.getvalue()
    with wave.open(io.BytesIO(raw), "rb") as source:
        return source.readframes(source.getnframes()), source.getframerate(), source.getsampwidth(), source.getnchannels()


def build_audiobook(chinese: dict[int, list[str]], english: dict[int, list[str]],
                    voices, output: Path, slow_mode_target: str, title: str,
                    chapters: list[int]) -> None:
    """Stream one audiobook to a temporary WAV, then encode tagged MP3."""
    import io
    from pydub import AudioSegment

    first: tuple[bytes, int, int, int] | None = None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with wave.open(str(temp_path), "wb") as wav:
            for chapter_index, chapter in enumerate(chapters):
                verses = pair_verses(chinese[chapter], english[chapter])
                for verse_index, (zh, en) in enumerate(verses):
                    for segment_index, (text, speed, voice) in enumerate((
                        (zh, SLOW_SPEED if slow_mode_target == "chinese" else NORMAL_SPEED, voices[0]),
                        (en, SLOW_SPEED if slow_mode_target == "english" else NORMAL_SPEED, voices[1]),
                    )):
                        try:
                            frames, rate, width, channels = _synthesize(voice, text, speed)
                            if first is None:
                                first = (frames, rate, width, channels)
                                wav.setnchannels(channels); wav.setsampwidth(width); wav.setframerate(rate)
                            wav.writeframes(frames)
                        except Exception:
                            log.exception("TTS failed; inserting silence for chapter %d", chapter)
                            if first is None:
                                first = (b"", SAMPLE_RATE, 2, 1)
                                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(SAMPLE_RATE)
                            wav.writeframes(_silence(0.5, wav.getsampwidth(), wav.getnchannels()))
                        if segment_index == 1 and verse_index < len(verses) - 1:
                            wav.writeframes(_silence(PAUSE_BETWEEN_VERSES,
                                                     wav.getsampwidth(), wav.getnchannels()))
                if first is not None and chapter_index < len(chapters) - 1:
                    wav.writeframes(_silence(PAUSE_BETWEEN_CHAPTERS,
                                             wav.getsampwidth(), wav.getnchannels()))
        audio = AudioSegment.from_wav(str(temp_path)).set_frame_rate(SAMPLE_RATE).set_channels(1)
        if audio.max_dBFS != float("-inf"):
            audio = audio.apply_gain(-3.0 - audio.max_dBFS)
        output.parent.mkdir(parents=True, exist_ok=True)
        audio.export(str(output), format="mp3", bitrate=BITRATE,
                     tags={"title": title, "artist": "Lao Tzu",
                           "album": "Tao Te Ching Bilingual Audiobook",
                           "date": "2026", "genre": "Spoken Word"})
    finally:
        temp_path.unlink(missing_ok=True)


def _load_voice(model: Path):
    from piper.voice import PiperVoice
    config = Path(str(model) + ".json")
    return PiperVoice.load(str(model), config_path=str(config) if config.exists() else None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output")
    parser.add_argument("--chinese-model", type=Path, default=ROOT / "chZH/zh_CN-huayan-medium.onnx")
    parser.add_argument("--english-model", type=Path, default=ROOT / "alba/en_GB-alba-medium.onnx")
    parser.add_argument("--chapters", nargs="+", type=int, metavar="N",
                        help="Optional chapter subset for a quick test.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if len(TRANSLATIONS) != EXPECTED_TRANSLATION_COUNT:
        raise SystemExit(
            f"Expected exactly {EXPECTED_TRANSLATION_COUNT} English editions; "
            f"configured {len(TRANSLATIONS)}"
        )
    chinese = extract_chinese()
    english = {key: extract_english(path) for key, (_, path) in TRANSLATIONS.items()}
    if len([n for n in chinese if chinese[n]]) != 81:
        raise SystemExit("Chinese source did not yield all 81 chapters")
    zh_voice, en_voice = _load_voice(args.chinese_model), _load_voice(args.english_model)
    chapters = args.chapters or list(range(1, 82))
    for key, (name, _) in TRANSLATIONS.items():
        for slow_mode_target, suffix in (("chinese", "english_normal_chinese_slow"),
                                         ("english", "chinese_normal_english_slow")):
            # A subset is intentionally supported for validation, but production
            # output always uses the complete 81-chapter sequence.
            zh_data = {n: chinese[n] for n in chapters}
            en_data = {n: english[key][n] for n in chapters}
            output = args.output_dir / f"{key}_{suffix}.mp3"
            build_audiobook(zh_data, en_data, (zh_voice, en_voice), output, slow_mode_target,
                            f"Tao Te Ching - {name} - {suffix}", chapters)


if __name__ == "__main__":
    main()
