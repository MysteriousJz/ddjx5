#!/usr/bin/env python3
"""
tao_audio.py — Synthesize audio from normalised Tao Te Ching JSON files
               using Piper TTS.

What it does:
    Loads the JSON files produced by ``tao_normalize.py`` and synthesises
    speech using a Piper TTS voice model.  Three output modes are supported:

    per_chapter
        One WAV (or MP3) file per chapter half, named e.g.
        ``goddard_ch1_top.wav`` and ``goddard_ch1_bottom.wav``.

    full
        One WAV (or MP3) per translation containing all 81 chapters in order
        (top half of chapter 1, bottom of chapter 1, top of chapter 2, …),
        named e.g. ``goddard_full.wav``.

    random
        One WAV (or MP3) that assembles a "mixed" audiobook by shuffling
        the chapters across translations, named ``mixed.wav``.

Voice model:
    Requires a Piper-compatible ``.onnx`` model file and its companion
    ``.json`` config.  Download the recommended youthful female voice::

        # en_GB-cori-high (Cori, British English, high quality)
        wget https://huggingface.co/rhasspy/piper-voices/resolve/main/\\
             en/en_GB/cori/high/en_GB-cori-high.onnx
        wget https://huggingface.co/rhasspy/piper-voices/resolve/main/\\
             en/en_GB/cori/high/en_GB-cori-high.onnx.json

    Then run::

        python tao_audio.py --model en_GB-cori-high.onnx \\
                            --json goddard_normalized.json anon_normalized.json \\
                            --mode full --out-dir ./audio

    Alternatively set the PIPER_MODEL environment variable to the model path.

MP3 output:
    If ``pydub`` and ``ffmpeg`` are installed MP3 files are written instead
    of WAV files.  Install with::

        pip install pydub
        sudo apt-get install ffmpeg   # or equivalent for your OS

Dependencies:
    piper-tts   (pip install piper-tts)
    pydub       (optional, for MP3 output; pip install pydub)
    ffmpeg      (optional, required by pydub for MP3 encoding)
"""

import argparse
import io
import json
import logging
import os
import random
import re
import struct
import wave

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional MP3 support via pydub
# ---------------------------------------------------------------------------
try:
    from pydub import AudioSegment as _AudioSegment

    _PYDUB_AVAILABLE = True
except ImportError:
    _PYDUB_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
#: Default voice model (override with --model CLI flag or PIPER_MODEL env var).
DEFAULT_MODEL = "en_GB-cori-high.onnx"

#: Piper synthesis speed (1.0 = normal, <1 = slower, >1 = faster).
SPEECH_RATE = 1.0

#: Short pause (in samples at the model's sample rate) inserted between halves.
#: Piper models typically use 22 050 Hz; 0.4 s = 8 820 samples.
PAUSE_DURATION_SEC = 0.4

#: Default output directory.
DEFAULT_OUT_DIR = "audio"

#: Normalised JSON files produced by tao_normalize.py.
DEFAULT_JSON_FILES = [
    "goddard_normalized.json",
    "anon_normalized.json",
    "gia_normalized.json",
    "crowley_normalized.json",
    "gorn_normalized.json",
]


# ===========================================================================
# Audio I/O helpers
# ===========================================================================

def _load_voice(model_path: str):
    """Load and return a PiperVoice.  Raises informative errors on failure."""
    try:
        from piper.voice import PiperVoice
    except ImportError as exc:
        raise SystemExit(
            "piper-tts is not installed.  Run: pip install piper-tts"
        ) from exc

    config_path = model_path + ".json" if not model_path.endswith(".json") else None
    if config_path and not os.path.exists(config_path):
        config_path = None  # let PiperVoice find it automatically

    if not os.path.exists(model_path):
        raise FileNotFoundError(
            f"Piper model not found: {model_path}\n"
            "Download the model with:\n"
            "  wget https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "en/en_GB/cori/high/en_GB-cori-high.onnx\n"
            "  wget https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            "en/en_GB/cori/high/en_GB-cori-high.onnx.json"
        )

    log.info("Loading voice model: %s", model_path)
    return PiperVoice.load(model_path, config_path=config_path)


def _synth_to_wav_bytes(voice, text: str) -> bytes:
    """
    Synthesise *text* with *voice* and return raw WAV bytes (including header).
    """
    from piper.voice import SynthesisConfig

    syn_cfg = SynthesisConfig(length_scale=1.0 / SPEECH_RATE)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize_wav(text, wf, syn_config=syn_cfg)
    return buf.getvalue()


def _wav_params(wav_bytes: bytes) -> tuple[int, int, int]:
    """Return (sample_rate, sample_width_bytes, n_channels) from WAV header."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        return wf.getframerate(), wf.getsampwidth(), wf.getnchannels()


def _wav_pcm_frames(wav_bytes: bytes) -> bytes:
    """Extract raw PCM frame data from WAV bytes (strip header)."""
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        return wf.readframes(wf.getnframes())


def _silence_frames(n_samples: int, sample_width: int, n_channels: int) -> bytes:
    """Generate *n_samples* of silent PCM frames."""
    return b"\x00" * (n_samples * sample_width * n_channels)


def _concat_wav_chunks(chunks: list[bytes], sample_rate: int,
                       sample_width: int, n_channels: int) -> bytes:
    """Concatenate a list of raw PCM *chunks* into a single WAV file."""
    pause = _silence_frames(
        int(sample_rate * PAUSE_DURATION_SEC), sample_width, n_channels
    )
    all_pcm = pause.join(chunks)  # pause between each segment
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(all_pcm)
    return buf.getvalue()


def _save_audio(wav_bytes: bytes, out_path: str) -> str:
    """
    Save *wav_bytes* to *out_path*.

    If *out_path* ends with ``.mp3`` and pydub+ffmpeg are available, converts
    to MP3; otherwise writes WAV (renaming the extension if necessary).

    Returns the actual path that was written.
    """
    want_mp3 = out_path.lower().endswith(".mp3")
    if want_mp3 and _PYDUB_AVAILABLE:
        seg = _AudioSegment.from_wav(io.BytesIO(wav_bytes))
        seg.export(out_path, format="mp3")
        return out_path

    # Fall back to WAV
    if want_mp3:
        out_path = re.sub(r"\.mp3$", ".wav", out_path, flags=re.IGNORECASE)
        log.warning("pydub/ffmpeg not available; saving as WAV: %s", out_path)
    with open(out_path, "wb") as fh:
        fh.write(wav_bytes)
    return out_path


# ===========================================================================
# JSON loading
# ===========================================================================

def _load_json(path: str) -> dict[str, dict[str, str]]:
    """Load a normalised JSON file and return ``{chap_str: {top, bottom}}``."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data


def _translation_name(json_path: str) -> str:
    """Extract translation name from JSON file path (e.g. ``goddard``)."""
    base = os.path.basename(json_path)
    name = re.sub(r"_normalized\.json$", "", base, flags=re.IGNORECASE)
    name = re.sub(r"\.json$", "", name, flags=re.IGNORECASE)
    return name


def _text_for_synth(text: str) -> str:
    """
    Sanitise text before passing to Piper.

    - Replace brackets (used in placeholder text) with something speakable.
    - Collapse excess whitespace.
    """
    # Speak placeholder text in a neutral way
    text = re.sub(r"\[Chapter (\d+) missing[^\]]*\]",
                  r"Chapter \1 is not available in this translation.", text)
    text = re.sub(r"\[([^\]]+)\]", r"\1", text)
    # Collapse multiple spaces
    text = " ".join(text.split())
    return text.strip()


# ===========================================================================
# Synthesis modes
# ===========================================================================

def synthesize_audio(
    json_paths: list[str],
    voice,
    mode: str = "per_chapter",
    out_dir: str = DEFAULT_OUT_DIR,
    ext: str = "wav",
    seed: int | None = None,
    chapters: list[int] | None = None,
) -> list[str]:
    """
    Synthesise audio from normalised JSON files.

    Parameters
    ----------
    json_paths : list[str]
        Paths to normalised JSON files from ``tao_normalize.py``.
    voice :
        Loaded PiperVoice instance.
    mode : str
        One of ``"per_chapter"``, ``"full"``, or ``"random"``.
    out_dir : str
        Directory where output audio files are written.
    ext : str
        Output file extension: ``"wav"`` or ``"mp3"``.
    seed : int or None
        Random seed for ``"random"`` mode (for reproducibility).
    chapters : list[int] or None
        Subset of chapter numbers to process (default: all 1-81).

    Returns
    -------
    list[str]
        Paths of all files written.
    """
    os.makedirs(out_dir, exist_ok=True)
    ext = ext.lower().lstrip(".")
    chapter_nums = chapters or list(range(1, 82))
    written: list[str] = []

    # Load all JSON data upfront
    all_data: dict[str, dict[str, dict[str, str]]] = {}
    for jp in json_paths:
        name = _translation_name(jp)
        all_data[name] = _load_json(jp)
        log.info("Loaded %s (%d chapters)", jp, len(all_data[name]))

    translation_names = list(all_data.keys())

    # Detect WAV params from a quick synthesis of a short phrase
    log.info("Detecting audio format from voice model …")
    _probe_wav = _synth_to_wav_bytes(voice, "Tao.")
    sample_rate, sample_width, n_channels = _wav_params(_probe_wav)
    log.info("Audio: %d Hz, %d-byte samples, %d channel(s)",
             sample_rate, sample_width, n_channels)

    # ------------------------------------------------------------------
    if mode == "per_chapter":
        log.info("Mode: per_chapter — generating %d × %d × 2 files …",
                 len(translation_names), len(chapter_nums))
        for name, data in all_data.items():
            for chap_num in chapter_nums:
                chap_key = str(chap_num)
                entry = data.get(chap_key, {"top": "", "bottom": ""})
                for half in ("top", "bottom"):
                    text = _text_for_synth(entry.get(half, ""))
                    if not text:
                        continue
                    log.info("  Synthesising %s ch%s %s …", name, chap_key, half)
                    wav = _synth_to_wav_bytes(voice, text)
                    fname = f"{name}_ch{chap_num}_{half}.{ext}"
                    path = _save_audio(wav, os.path.join(out_dir, fname))
                    written.append(path)

    # ------------------------------------------------------------------
    elif mode == "full":
        log.info("Mode: full — generating %d audiobook(s) …", len(translation_names))
        for name, data in all_data.items():
            log.info("  %s: synthesising %d chapters …", name, len(chapter_nums))
            pcm_chunks: list[bytes] = []
            for chap_num in chapter_nums:
                chap_key = str(chap_num)
                entry = data.get(chap_key, {"top": "", "bottom": ""})
                for half in ("top", "bottom"):
                    text = _text_for_synth(entry.get(half, ""))
                    if not text:
                        continue
                    wav = _synth_to_wav_bytes(voice, text)
                    pcm_chunks.append(_wav_pcm_frames(wav))
            if pcm_chunks:
                combined = _concat_wav_chunks(
                    pcm_chunks, sample_rate, sample_width, n_channels
                )
                fname = f"{name}_full.{ext}"
                path = _save_audio(combined, os.path.join(out_dir, fname))
                log.info("  Wrote %s", path)
                written.append(path)

    # ------------------------------------------------------------------
    elif mode == "random":
        log.info("Mode: random — shuffling chapters across %d translations …",
                 len(translation_names))
        rng = random.Random(seed)
        # For each chapter number, pick a random translation
        assignment: list[tuple[int, str]] = []
        for chap_num in chapter_nums:
            name = rng.choice(translation_names)
            assignment.append((chap_num, name))
        log.info("  Chapter assignments (first 5): %s",
                 [(c, n) for c, n in assignment[:5]])
        pcm_chunks: list[bytes] = []
        for chap_num, name in assignment:
            chap_key = str(chap_num)
            entry = all_data[name].get(chap_key, {"top": "", "bottom": ""})
            for half in ("top", "bottom"):
                text = _text_for_synth(entry.get(half, ""))
                if not text:
                    continue
                log.info("  ch%d %s from %s …", chap_num, half, name)
                wav = _synth_to_wav_bytes(voice, text)
                pcm_chunks.append(_wav_pcm_frames(wav))
        if pcm_chunks:
            combined = _concat_wav_chunks(
                pcm_chunks, sample_rate, sample_width, n_channels
            )
            fname = f"mixed.{ext}"
            path = _save_audio(combined, os.path.join(out_dir, fname))
            log.info("Wrote %s", path)
            written.append(path)

    else:
        raise ValueError(
            f"Unknown mode: {mode!r}. Choose from 'per_chapter', 'full', 'random'."
        )

    return written


# ===========================================================================
# CLI entry point
# ===========================================================================

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Synthesise Tao Te Ching audiobooks from normalised JSON files "
            "using Piper TTS."
        )
    )
    p.add_argument(
        "--model",
        default=os.environ.get("PIPER_MODEL", DEFAULT_MODEL),
        help=(
            f"Path to Piper .onnx voice model (default: {DEFAULT_MODEL}). "
            "Can also be set via PIPER_MODEL environment variable."
        ),
    )
    p.add_argument(
        "--json",
        nargs="+",
        default=None,
        dest="json_paths",
        help=(
            "Normalised JSON file(s) from tao_normalize.py "
            "(default: all five standard *_normalized.json files)."
        ),
    )
    p.add_argument(
        "--mode",
        choices=["per_chapter", "full", "random"],
        default="per_chapter",
        help=(
            "Synthesis mode: "
            "'per_chapter' (one file per chapter half), "
            "'full' (one file per translation), "
            "'random' (one mixed-translation audiobook). "
            "Default: per_chapter."
        ),
    )
    p.add_argument(
        "--out-dir",
        default=DEFAULT_OUT_DIR,
        help=f"Output directory for audio files (default: {DEFAULT_OUT_DIR!r}).",
    )
    p.add_argument(
        "--mp3",
        action="store_true",
        help="Export as MP3 instead of WAV (requires pydub + ffmpeg).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for 'random' mode (ensures reproducible shuffle).",
    )
    p.add_argument(
        "--chapters",
        nargs="+",
        type=int,
        default=None,
        metavar="N",
        help="Restrict synthesis to specific chapter numbers (e.g. --chapters 1 2 3).",
    )
    return p


def main() -> None:
    """CLI entry point for tao_audio.py."""
    args = _build_arg_parser().parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Resolve JSON paths
    if args.json_paths:
        json_paths = [
            f if os.path.isabs(f) else os.path.join(script_dir, f)
            for f in args.json_paths
        ]
    else:
        json_paths = [
            os.path.join(script_dir, f)
            for f in DEFAULT_JSON_FILES
            if os.path.exists(os.path.join(script_dir, f))
        ]
        if not json_paths:
            raise SystemExit(
                "No normalised JSON files found.  Run tao_normalize.py first, or "
                "supply paths with --json."
            )

    # Resolve model path
    model_path = (
        args.model
        if os.path.isabs(args.model)
        else os.path.join(script_dir, args.model)
    )

    ext = "mp3" if args.mp3 else "wav"

    log.info("=" * 60)
    log.info("tao_audio.py — Audio Synthesis")
    log.info("=" * 60)
    log.info("Model  : %s", model_path)
    log.info("JSON   : %s", [os.path.basename(p) for p in json_paths])
    log.info("Mode   : %s", args.mode)
    log.info("Output : %s  (format: %s)", args.out_dir, ext.upper())
    if args.seed is not None:
        log.info("Seed   : %d", args.seed)
    if args.chapters:
        log.info("Chapters: %s", args.chapters)

    voice = _load_voice(model_path)

    written = synthesize_audio(
        json_paths=json_paths,
        voice=voice,
        mode=args.mode,
        out_dir=args.out_dir,
        ext=ext,
        seed=args.seed,
        chapters=args.chapters,
    )

    log.info("=" * 60)
    log.info("Done.  %d file(s) written to %s:", len(written), args.out_dir)
    for p in written[:10]:  # show first 10
        log.info("  %s", p)
    if len(written) > 10:
        log.info("  … and %d more.", len(written) - 10)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
