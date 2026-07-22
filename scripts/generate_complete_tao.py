#!/usr/bin/env python3
"""
Generate 4 complete Tao Te Ching books with 5 parallel translations.
Each book uses 5 different translators displayed side-by-side with visible boundaries.
Also exports all translations as plain text files.
"""

from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
import re
import html as html_lib

ROOT = Path(__file__).resolve().parents[1]

# Page layout constants
PAGE_W, PAGE_H = letter
MARGIN = 0.5 * inch
TEXT_W = PAGE_W - 2 * MARGIN
TEXT_H = PAGE_H - 2 * MARGIN

NUM_COLS = 5
SMALL_GAP = 0.125 * inch
VERT_CENTER_GAP = 0.5 * inch
COL_W = (TEXT_W - (NUM_COLS - 1) * SMALL_GAP) / NUM_COLS
FRAME_H = (TEXT_H - VERT_CENTER_GAP) / 2.0

# 4 different combinations of 5 translators
BOOK_COMBINATIONS = [
    {
        "name": "Book_1_Beck_Bahm_Anonymous_Crowley_Cronk.pdf",
        "translators": ["Sanderson Beck", "Archie J. Bahm", "Anonymous", "Aleister Crowley", "George Cronk"],
        "files": [
            "Tao Te Ching, English by Sanderson Beck - Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Archie J. Bahm - Terebess Asia Online (TAO).html",
            "Tao Te Ching by Anonymous - Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Aleister Crowley - Terebess Asia Online (TAO).html",
            "Das Tao Te King von George Cronk.html",
        ]
    },
    {
        "name": "Book_2_Addiss_Blakney_Bullen_Cheng_Chen.pdf",
        "translators": ["Addiss & Lombardo", "Raymond B. Blakney", "David Bullen", "David Hong Cheng", "Ellen Marie Chen"],
        "files": [
            "Tao Te Ching, English by Stephen Addiss & Stanley Lombardo - Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Raymond B. Blakney, Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by David Bullen - Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by David Hong Cheng - Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Ellen Marie Chen - Terebess Asia Online (TAO).html",
        ]
    },
    {
        "name": "Book_3_Cleary_Bryce_Clatfelder_Byrn_Chan.pdf",
        "translators": ["Thomas Cleary", "Derek Bryce", "Jim Clatfelder", "Tormond Byrn", "Wing-Tsit Chan"],
        "files": [
            "Tao Te Ching, English by Thomas Cleary - Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Derek Bryce - Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Jim Clatfelder, Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Tormond Byrn, Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Wing-Tsit Chan - Terebess Asia Online (TAO).html",
        ]
    },
    {
        "name": "Book_4_Goddard_Cronk_Gorn_Bynner_Chohan.pdf",
        "translators": ["Dwight Goddard", "George Cronk", "Walter Gorn-Old", "Witter Bynner", "Chou-Wing Chohan"],
        "files": [
            "Das Tao Te King von Dwight Goddard.html",
            "Das Tao Te King von George Cronk.html",
            "Das Tao Te King von Walter Gorn-Old.html",
            "Tao Te Ching by Witter Bynner, Terebess Asia Online (TAO).html",
            "Tao Te Ching, English by Chou-Wing Chohan - Terebess Asia Online (TAO).html",
        ]
    },
]

def get_file_encoding(file_path):
    """Detect and return the correct encoding for a file."""
    # Try encodings in order of likelihood
    encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252', 'windows-1252']
    
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
                content = f.read(5000)  # Test read first 5000 chars
                # Basic validation - should have some text
                if len(content.strip()) > 100:
                    return encoding
        except:
            continue
    
    return 'latin-1'  # Fallback for problematic files

def extract_chapters_from_html(html_content):
    """Extract 81 chapters from HTML content with robust parsing."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '\n', html_content)
    text = html_lib.unescape(text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    lines = text.split('\n')
    chapters = {}
    current_chapter = None
    current_text = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Try to detect chapter number at line start: "1", "1.", "1. Title", etc
        match = re.match(r'^(\d{1,2})\.\s+', line)
        if match:
            num = int(match.group(1))
            if 1 <= num <= 81:  # Valid chapter number
                if current_chapter is not None and current_text:
                    chapters[current_chapter] = '\n'.join(current_text).strip()
                current_chapter = num
                # Remove the number and period from the line
                remaining = re.sub(r'^\d{1,2}\.\s+', '', line).strip()
                current_text = [remaining] if remaining else []
                continue
        
        # Try to detect standalone chapter number: just "1", "2", etc on a line
        if re.match(r'^(\d{1,2})$', line):
            match = re.match(r'^(\d{1,2})$', line)
            num = int(match.group(1))
            if 1 <= num <= 81:
                if current_chapter is not None and current_text:
                    chapters[current_chapter] = '\n'.join(current_text).strip()
                current_chapter = num
                current_text = []
                continue
        
        # Add non-chapter-number lines to current chapter
        if current_chapter is not None:
            current_text.append(line)
    
    # Save last chapter
    if current_chapter is not None and current_text:
        chapters[current_chapter] = '\n'.join(current_text).strip()
    
    # If we didn't find enough chapters, try splitting pattern
    if len(chapters) < 20:
        chapters = {}
        parts = re.split(r'\n\s*(\d{1,2})\s*(?:\.\s+|$)\n', text)
        
        for i in range(1, len(parts) - 1, 2):
            try:
                chapter_num = int(parts[i])
                if 1 <= chapter_num <= 81:
                    chapter_content = parts[i + 1].strip()
                    chapter_content = re.sub(r'^\.?\s+', '', chapter_content).strip()
                    if chapter_content:
                        chapters[chapter_num] = chapter_content
            except (ValueError, IndexError):
                pass
    
    # Ensure we have all chapters 1-81, fill missing ones with empty strings
    result = {}
    for i in range(1, 82):
        result[i] = chapters.get(i, "")
    
    return result

def load_all_chapters(file_path):
    """Load all 81 chapters from a file with proper encoding handling."""
    try:
        encoding = get_file_encoding(file_path)
        with open(file_path, 'r', encoding=encoding, errors='replace') as f:
            content = f.read()
        
        chapters = extract_chapters_from_html(content)
        return chapters
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return {i: "" for i in range(1, 82)}

def calculate_font_size(text_length, frame_area, target_fill=0.7):
    """Calculate font size based on text length and frame area."""
    if text_length < 500:
        return 12  # Small text, larger font
    elif text_length < 2000:
        return 11
    elif text_length < 5000:
        return 10
    else:
        return 9  # Large text, smaller font

def find_natural_split(text, target_words=None):
    """
    Split text into two parts at roughly 50/50 by word count.
    Finds natural breaks (periods, paragraphs) to avoid cutting mid-sentence.
    Returns (top_text, bottom_text)
    """
    if not text or not text.strip():
        return "", ""
    
    # Count total words
    words = text.split()
    if target_words is None:
        target_words = len(words) // 2
    
    if target_words == 0 or len(words) <= 1:
        return text, ""
    
    # Find sentence/paragraph boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    current_words = 0
    split_point = 0
    
    for i, sentence in enumerate(sentences):
        sentence_word_count = len(sentence.split())
        
        # If adding this sentence would exceed target, check if we're closer to target now or after
        if current_words + sentence_word_count > target_words:
            # Decide: use current split or add this sentence
            words_if_before = current_words
            words_if_after = current_words + sentence_word_count
            
            if abs(words_if_after - target_words) < abs(words_if_before - target_words):
                # Adding this sentence gets us closer
                current_words = words_if_after
                split_point = i + 1
            break
        else:
            current_words += sentence_word_count
            split_point = i + 1
    
    if split_point == 0:
        # No split found, use first sentence or first half of words
        first_sentence_end = text.find('.')
        if first_sentence_end > 0:
            return text[:first_sentence_end + 1], text[first_sentence_end + 1:].strip()
        else:
            # Fallback: split by words
            mid_idx = len(words) // 2
            split_idx = len(' '.join(words[:mid_idx]))
            return text[:split_idx], text[split_idx:].strip()
    
    # Reconstruct top and bottom from sentences
    top_text = ' '.join(sentences[:split_point]).strip()
    bottom_text = ' '.join(sentences[split_point:]).strip()
    
    return top_text, bottom_text

def generate_book(book_config, output_path):
    """Generate a complete book with all 81 chapters."""
    print(f"\nGenerating: {book_config['name']}")
    
    # Load all chapters from all files
    all_chapters = []
    for file_name in book_config['files']:
        file_path = ROOT / file_name
        if not file_path.exists():
            print(f"  WARNING: {file_name} not found")
            all_chapters.append({i: "" for i in range(1, 82)})
        else:
            chapters = load_all_chapters(file_path)
            all_chapters.append(chapters)
            print(f"  ✓ Loaded: {file_name}")
    
    # Create PDF with one page per chapter
    c = canvas.Canvas(str(output_path), pagesize=letter)
    styles = getSampleStyleSheet()
    
    for chapter_num in range(1, 82):
        # Add chapter header
        c.setFont("Helvetica-Bold", 14)
        c.drawString(MARGIN, PAGE_H - MARGIN + 0.2*inch, f"Chapter {chapter_num}")
        
        # Calculate positions
        xs = [MARGIN + i * (COL_W + SMALL_GAP) for i in range(NUM_COLS)]
        top_y = MARGIN + FRAME_H + VERT_CENTER_GAP
        bottom_y = MARGIN
        
        # Render each column
        for col_idx, (chapters_data, translator_name) in enumerate(zip(all_chapters, book_config['translators'])):
            text = chapters_data.get(chapter_num, "")
            if not text or text.startswith("[Chapter"):
                text = ""
            
            # Calculate font size
            font_size = calculate_font_size(len(text), COL_W * FRAME_H)
            
            style = ParagraphStyle(
                'body',
                parent=styles['Normal'],
                fontSize=font_size,
                leading=font_size + 2,
            )
            
            # Split into top and bottom using natural breaks (not mid-word)
            if text:
                top_text, bottom_text = find_natural_split(text)
            else:
                top_text = ""
                bottom_text = ""
            
            try:
                # Top frame with visible boundary
                top_frame = Frame(xs[col_idx], top_y, COL_W, FRAME_H,
                                 leftPadding=4, rightPadding=4,
                                 topPadding=4, bottomPadding=4, showBoundary=1)
                if top_text:
                    top_para = Paragraph(top_text.replace('\n', ' '), style)
                    top_frame.addFromList([top_para], c)
                else:
                    top_frame.addFromList([], c)
                
                # Bottom frame with visible boundary
                bot_frame = Frame(xs[col_idx], bottom_y, COL_W, FRAME_H,
                                 leftPadding=4, rightPadding=4,
                                 topPadding=4, bottomPadding=4, showBoundary=1)
                if bottom_text:
                    bot_para = Paragraph(bottom_text.replace('\n', ' '), style)
                    bot_frame.addFromList([bot_para], c)
                else:
                    bot_frame.addFromList([], c)
            except Exception as e:
                print(f"    Error rendering chapter {chapter_num}, column {col_idx}: {e}")
        
        c.showPage()
    
    c.save()
    file_size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ Generated: {output_path.name} ({file_size_mb:.2f} MB)")

def export_translation_to_txt(file_name, translator_name, output_path):
    """Export a single translation to a plain text file with chapter numbers."""
    file_path = ROOT / file_name
    
    if not file_path.exists():
        print(f"  ERROR: {file_name} not found")
        return False
    
    try:
        chapters = load_all_chapters(file_path)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for chapter_num in range(1, 82):
                text = chapters.get(chapter_num, "")
                if text:
                    f.write(f"{chapter_num}\n")
                    f.write(text)
                    f.write("\n\n")
        
        print(f"  ✓ Exported: {output_path.name}")
        return True
    except Exception as e:
        print(f"  ERROR exporting {file_name}: {e}")
        return False

def main():
    """Generate all 4 books and export all translations as text files."""
    print("\n" + "="*70)
    print("GENERATING 4 COMPLETE TAO TE CHING BOOKS")
    print("Each book: 81 chapters, 5 parallel translations with visible boundaries")
    print("="*70)
    
    # Generate PDFs
    for book_config in BOOK_COMBINATIONS:
        output_path = ROOT / book_config['name']
        try:
            generate_book(book_config, output_path)
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    # Export all translations as text files
    print("\n" + "="*70)
    print("EXPORTING ALL 20 TRANSLATIONS AS PLAIN TEXT FILES")
    print("="*70)
    
    all_files = []
    for book_config in BOOK_COMBINATIONS:
        for file_name, translator_name in zip(book_config['files'], book_config['translators']):
            all_files.append((file_name, translator_name))
    
    for file_name, translator_name in all_files:
        # Create output filename based on translator name
        output_name = translator_name.replace(" & ", "_and_").replace(" ", "_").replace("-", "_") + ".txt"
        output_path = ROOT / "txt_exports" / output_name
        
        # Create txt_exports directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        print(f"\nExporting: {translator_name}")
        export_translation_to_txt(file_name, translator_name, output_path)
    
    print("\n" + "="*70)
    print("COMPLETE - All 4 books generated with visible boundaries!")
    print("All 20 translations exported to txt_exports/ folder!")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
