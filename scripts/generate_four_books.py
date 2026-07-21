#!/usr/bin/env python3
"""
Generate 4 complete Tao Te Ching books with 5 parallel translations.
Each book uses 5 different translators displayed side-by-side.
Font sizes are dynamically adjusted based on content fill percentage.
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

def extract_chapters_from_html(html_content):
    """Extract 81 chapters from HTML content."""
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
            
        # Try to detect chapter number
        if re.match(r'^(\d{1,2})\.?$', line):
            if current_chapter is not None:
                chapters[current_chapter] = '\n'.join(current_text).strip()
            current_chapter = int(re.match(r'^(\d{1,2})', line).group(1))
            current_text = []
        elif current_chapter is not None:
            current_text.append(line)
    
    # Save last chapter
    if current_chapter is not None:
        chapters[current_chapter] = '\n'.join(current_text).strip()
    
    return chapters

def load_all_chapters(file_path):
    """Load all 81 chapters from a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if file_path.suffix.lower() == '.html':
            chapters = extract_chapters_from_html(content)
        else:
            chapters = extract_chapters_from_html(content)
        
        # Ensure we have chapters 1-81
        result = {}
        for i in range(1, 82):
            result[i] = chapters.get(i, f"[Chapter {i} not found]")
        
        return result
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return {i: "" for i in range(1, 82)}

def calculate_font_size(text_length, frame_area, target_fill=0.7):
    """Calculate font size based on text length and frame area."""
    base_size = 10
    
    # Simple heuristic: adjust font size based on expected content
    if text_length < 500:
        return 12  # Small text, larger font
    elif text_length < 2000:
        return 11
    elif text_length < 5000:
        return 10
    else:
        return 9  # Large text, smaller font
    
    return base_size

def render_column(c, chapters_data, col_x, top_y, bottom_y, translator_name):
    """Render a single column for all chapters."""
    styles = getSampleStyleSheet()
    
    for chapter_num in range(1, 82):
        text = chapters_data.get(chapter_num, "")
        if not text or text.startswith("[Chapter"):
            continue
        
        # Determine font size dynamically
        font_size = calculate_font_size(len(text), COL_W * FRAME_H)
        
        style = ParagraphStyle(
            'column_text',
            parent=styles['Normal'],
            fontSize=font_size,
            leading=font_size + 2,
            alignment=0,  # Left align
        )
        
        # Split text into top and bottom halves based on character count
        mid_point = len(text) // 2
        top_text = text[:mid_point]
        bottom_text = text[mid_point:]
        
        # Create frames and add text
        top_frame = Frame(col_x, top_y, COL_W, FRAME_H, 
                         leftPadding=4, rightPadding=4, 
                         topPadding=4, bottomPadding=4, showBoundary=0)
        bot_frame = Frame(col_x, bottom_y, COL_W, FRAME_H,
                         leftPadding=4, rightPadding=4,
                         topPadding=4, bottomPadding=4, showBoundary=0)
        
        try:
            top_para = Paragraph(top_text.replace('\n', ' '), style)
            bot_para = Paragraph(bottom_text.replace('\n', ' '), style)
            
            top_frame.addFromList([top_para], c)
            bot_frame.addFromList([bot_para], c)
        except:
            pass  # Skip if paragraph fails

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
                continue
            
            # Calculate font size
            font_size = calculate_font_size(len(text), COL_W * FRAME_H)
            
            style = ParagraphStyle(
                'body',
                parent=styles['Normal'],
                fontSize=font_size,
                leading=font_size + 2,
            )
            
            # Split into top and bottom
            mid_point = len(text) // 2
            top_text = text[:mid_point]
            bottom_text = text[mid_point:]
            
            try:
                # Top frame
                top_frame = Frame(xs[col_idx], top_y, COL_W, FRAME_H,
                                 leftPadding=4, rightPadding=4,
                                 topPadding=4, bottomPadding=4, showBoundary=0)
                top_para = Paragraph(top_text.replace('\n', ' '), style)
                top_frame.addFromList([top_para], c)
                
                # Bottom frame
                bot_frame = Frame(xs[col_idx], bottom_y, COL_W, FRAME_H,
                                 leftPadding=4, rightPadding=4,
                                 topPadding=4, bottomPadding=4, showBoundary=0)
                bot_para = Paragraph(bottom_text.replace('\n', ' '), style)
                bot_frame.addFromList([bot_para], c)
            except Exception as e:
                print(f"    Error rendering chapter {chapter_num}, column {col_idx}: {e}")
        
        c.showPage()
    
    c.save()
    file_size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  ✓ Generated: {output_path.name} ({file_size_mb:.2f} MB)")

def main():
    """Generate all 4 books."""
    print("\n" + "="*70)
    print("GENERATING 4 COMPLETE TAO TE CHING BOOKS")
    print("Each book: 81 chapters, 5 parallel translations")
    print("="*70)
    
    for book_config in BOOK_COMBINATIONS:
        output_path = ROOT / book_config['name']
        try:
            generate_book(book_config, output_path)
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    print("\n" + "="*70)
    print("COMPLETE - All 4 books generated!")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
