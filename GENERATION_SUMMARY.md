# Tao Te Ching Multi-Translation PDF & Text Generation

## Overview
This project generates 4 complete Tao Te Ching books and exports all 20 translations as plain text files with proper formatting.

## Generated Files

### Bilingual Audiobooks
`scripts/generate_bilingual_audiobooks.py` creates exactly six MP3 files:
three English editions (Arthur Waley, D.C. Lau, and Stephen Mitchell), each
paired with the same Chinese Text Project source. For every edition it creates:

- `<edition>_english_normal_chinese_slow.mp3`
- `<edition>_chinese_normal_english_slow.mp3`

Both files contain all 81 chapters. The first reads English at normal speed
and Chinese slowly; the second reads Chinese at normal speed and English
slowly. Run `python3 scripts/generate_bilingual_audiobooks.py` to create them
under `output/`.

### PDF Books (4 books with 5 parallel translations each)
1. **Book_1_Beck_Bahm_Anonymous_Crowley_Cronk.pdf**
   - Sanderson Beck
   - Archie J. Bahm
   - Anonymous
   - Aleister Crowley
   - George Cronk

2. **Book_2_Addiss_Blakney_Bullen_Cheng_Chen.pdf**
   - Addiss & Lombardo
   - Raymond B. Blakney
   - David Bullen
   - David Hong Cheng
   - Ellen Marie Chen

3. **Book_3_Cleary_Bryce_Clatfelder_Byrn_Chan.pdf**
   - Thomas Cleary
   - Derek Bryce
   - Jim Clatfelder
   - Tormond Byrn
   - Wing-Tsit Chan

4. **Book_4_Goddard_Cronk_Gorn_Bynner_Chohan.pdf**
   - Dwight Goddard
   - George Cronk
   - Walter Gorn-Old
   - Witter Bynner
   - Chou-Wing Chohan

### Text Exports (20 translations in txt_exports/ folder)
All translations exported as plain text files with:
- Chapter numbers preceding each chapter
- One chapter per paragraph block
- Clean plain text formatting (no HTML)
- All 81 chapters per translation

## Features

### PDF Features
- **5-Column Layout**: Each page displays 5 translations side-by-side
- **Visible Boundaries**: Black boxes around each column for clarity
- **Smart Text Splitting**: 50/50 word-based split between top and bottom halves
- **Natural Break Points**: Splits at sentence/paragraph boundaries, never mid-word
- **Dynamic Font Sizing**: Adjusts font size based on content length for optimal readability
- **81 Chapters**: One page per chapter for easy reference

### Text Export Features
- **Plain Text Format**: Clean, readable formatting
- **Chapter Numbers**: Each chapter prefixed with its number
- **Complete Content**: All 81 chapters per translator
- **UTF-8 Encoding**: Consistent character encoding across all files

## Generation Script

**Location**: `scripts/generate_complete_tao.py`

**Usage**:
```bash
python3 scripts/generate_complete_tao.py
```

**What it does**:
1. Loads all HTML source files
2. Extracts chapters with robust parsing (handles multiple HTML formats)
3. Generates 4 PDF books with visible column boundaries
4. Exports all 20 translations as plain text files
5. Reports progress for each step

## Technical Details

### Chapter Extraction
- Handles multiple HTML formatting styles
- Detects chapter numbers with patterns like "1.", "1 ", and standalone numbers
- Falls back to regex splitting for difficult formats
- Encoding detection (UTF-8, Latin-1, CP1252, etc.)

### Text Splitting
- Word-count based (not character-based) for true 50/50 balance
- Finds natural sentence/paragraph boundaries
- Prevents mid-word cuts for readability
- Smart fallback to first sentence if no natural break found

### PDF Layout
- Page size: Letter (8.5" × 11")
- Margins: 0.5" on all sides
- Column gap: 0.125"
- Vertical center gap: 0.5"
- Text area: 5 equal columns with visible boundaries

## Requirements

- Python 3.6+
- reportlab (PDF generation)
- pathlib (file handling)
- re (regex for text parsing)
- html (HTML entity decoding)

## Output Structure

```
/home/runner/work/ddjx5/ddjx5/
├── Book_1_Beck_Bahm_Anonymous_Crowley_Cronk.pdf
├── Book_2_Addiss_Blakney_Bullen_Cheng_Chen.pdf
├── Book_3_Cleary_Bryce_Clatfelder_Byrn_Chan.pdf
├── Book_4_Goddard_Cronk_Gorn_Bynner_Chohan.pdf
└── txt_exports/
    ├── Sanderson_Beck.txt
    ├── Archie_J._Bahm.txt
    ├── Anonymous.txt
    ├── Aleister_Crowley.txt
    ├── ... (20 total)
    └── Chou_Wing_Chohan.txt
```

## Notes

- All PDF pages follow a consistent 2-section layout (top and bottom halves)
- Text in each section is automatically sized for optimal fit
- Chapter titles appear at the top of each page
- Translations maintain proper spacing and paragraph structure
- All text files include complete 81-chapter content for each translator
