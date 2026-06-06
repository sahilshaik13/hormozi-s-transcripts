"""Strip Anna's Archive / book-export noise from Hormozi book .md files for RAG indexing."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import tools._bootstrap  # noqa: F401
from backend.paths import TRANSCRIPTS_DIR as TRANSCRIPTS

BOOK_FILES = [
    "$100 m offers_ how to make offers so good people feel stupid -- Alex Hormozy -- PT, 2021 -- Acquisition_com Publishing -- 9781737475705 -- da9eb4951114175a5e429e89b9488c20 -- Anna's Archive.md",
    "$100M Leads_ How to Get Strangers To Want To Buy Your Stuff -- Alex Hormozi -- $100M Leads, 2_, 2023 -- 1268dcce3c9050728de5cb669996bd84 -- Anna's Archive.md",
    "$100M Money Models_ How To Make Money -- Alex Hormozi -- 2025.md",
    "$100M Playbook_ Branding -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ Closing -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ Fast Cash -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ GOATed Ads -- Alex Hormozi -- 2025.md",
    "$100M Playbook_ Hooks -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ Lead Nurture -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ Lifetime Value -- Alex Hormozi -- 2025.md",
    "$100M Playbook_ Marketing Machine -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ Price Raise -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ Pricing -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ Proof Checklist -- Alex Hormozi -- $100M, 2025.md",
    "$100M Playbook_ Retention -- Alex Hormozi -- $100M, 2025.md",
]

HR = re.compile(r"^[-—]{3,}\s*$")
DOT_LEADER = re.compile(r"\.{5,}\s*\d+\s*$")
IMAGE_LINE = re.compile(
    r"^\[.*(?:Image of|QR code|SCAN ME|shows a).*\]\s*$|"
    r"^\[The image shows.*\]\s*$",
    re.IGNORECASE,
)
INLINE_ICON = re.compile(r"!\[[^\]]*\]\s*")
DISTRIBUTION = re.compile(r"NOT FOR DISTRIBUTION", re.I)
FREE_GIFT = re.compile(r"^\*?\*?FREE GIFT:", re.I)
ICON_DESC = re.compile(r"^#### Icons representing|^!\[[^\]]*icon\]", re.IGNORECASE)
PROMO_LINE = re.compile(
    r"scan the qr code|scan this qr|you can also scan|hate typing|"
    r"acquisition\.com/scale|acquisition\.com/training|acquisition\.com/avatar|"
    r"acquisition\.com/careers|acquisition\.com/podcast|acquisition\.com/media|"
    r"qr code for easy|qr code below|qr code with",
    re.IGNORECASE,
)
SKIP_SECTION = re.compile(
    r"(table of contents|^contents$|copyright|disclaimer|legal disclaimer|"
    r"thank yous?|a quick word|what others have said|"
    r"what people have said|free goodies|guiding principles|"
    r"free goodies:\s*calls to action|acquisition\.com volume)",
    re.IGNORECASE,
)
HTML_FRAG = re.compile(r"</?(?:td|tr|th|table|thead|tbody)\b|colspan|style=", re.I)
TESTIMONIAL_SECTION = re.compile(
    r"russell brunson|brooke castil|ryan daniel moran|ceo of clickfunnels",
    re.I,
)
CTA_SECTION = re.compile(r"do you want to scale your business", re.IGNORECASE)
DIAGRAM_HINT = re.compile(
    r"illustration of|rubik|you are here|red x mark|green check|"
    r"conveyor belt|thought bubble|nom nom nom|\[box labeled|"
    r":\d+\.\.\.:\d+",
    re.IGNORECASE,
)
PRO_TIP = re.compile(r"pro tip:\s*faster,\s*deeper learning", re.IGNORECASE)
SENTENCE = re.compile(r"[a-z]{4,}.*[.!?]", re.IGNORECASE)
LEGAL_HEADER = re.compile(r"^(?:#{1,6}\s*)?(?:legal disclaimer|disclaimer)\s*$", re.I)
LEGAL_START = re.compile(
    r"generic legal disclaimer|"
    r"^#{1,6}\s*legal disclaimer\s*$|"
    r"^#{1,6}\s*disclaimer\s*$|"
    r"^copyright ©|"
    r"^all rights reserved|"
    r"^hypothetical performance results",
    re.I,
)
LEGAL_BODY = re.compile(
    r"not engaged in rendering legal|"
    r"disclaim any liability|"
    r"no guarantee of specific outcomes or financial gains|"
    r"by reading this book, you acknowledge|"
    r"past performance does not guarantee future results|"
    r"information presented in this book is based on the author|"
    r"designed to provide helpful information on the subjects|"
    r"not meant to be used, nor should it be used|"
    r"hold harmless|"
    r"forward looking statements|"
    r"merchantability|"
    r"readers agree to release|"
    r"referred to herein as the|"
    r"made any guarantees that the strategies|"
    r"company is not liable|"
    r"hypothetical performance|"
    r"educational and informational purposes only|"
    r"reproduction or translation of any part|"
    r"no part of this publication may be reproduced|"
    r"competent professional should be sought|"
    r"reader.s responsibility to research and comply|"
    r"could become outdated over time|"
    r"financial markets and business climate",
    re.I,
)
TEACHING_DISCLAIMER = re.compile(
    r"\*\*(?:Important )?Disclaimer:\*\*.*(?:Figuring|reaching an audience|estimate)",
    re.I,
)


def resolve_path(name: str) -> Path | None:
    direct = TRANSCRIPTS / name
    if direct.exists():
        return direct
    prefix = name[:35]
    for p in TRANSCRIPTS.glob("*.md"):
        if p.name.startswith(prefix):
            return p
    return None


def header_text(line: str) -> str:
    return re.sub(r"^#+\s*", "", line).strip().lower()


def is_hr(line: str) -> bool:
    return bool(HR.match(line.strip()))


def strip_dot_leaders(line: str) -> str:
    return DOT_LEADER.sub("", line).rstrip()


def is_legal_disclaimer_start(line: str) -> bool:
    s = line.strip()
    if TEACHING_DISCLAIMER.search(s):
        return False
    return bool(LEGAL_START.search(s))


def is_legal_disclaimer_body(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if TEACHING_DISCLAIMER.search(s):
        return False
    if LEGAL_HEADER.match(s):
        return True
    return bool(LEGAL_BODY.search(s))


def is_promo_paragraph(line: str) -> bool:
    s = line.strip().lstrip(">").strip()
    if FREE_GIFT.match(s):
        return True
    if re.search(r"\[Image of", s, re.I):
        return True
    if DISTRIBUTION.search(s):
        return True
    # Drop short standalone promo/QR lines, not teaching paragraphs that mention a link.
    if len(s) < 220 and PROMO_LINE.search(s):
        return True
    if re.search(r"acquisition\.com/training", s, re.I) and re.search(
        r"qr code|scan the|free video for you|video training|video breakdown|watch it, just go",
        s,
        re.I,
    ):
        return True
    return False


def should_drop_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if is_hr(s):
        return False
    if IMAGE_LINE.match(s):
        return True
    if ICON_DESC.match(s):
        return True
    if is_promo_paragraph(line):
        return True
    if s.lower().startswith("private collection"):
        return True
    if re.search(r"copies sold in the \$100m series", s, re.I):
        return True
    if re.match(r"^#+\s*copyright", s, re.I):
        return True
    if re.match(r"^##\s*disclaimer\s*$", s, re.I):
        return True
    if s.startswith("Acquisition.com") and ("7710" in s or s == "Acquisition.com"):
        return True
    if re.match(r"^ACQUISITION\.COM\s*$", s, re.I):
        return True
    if re.match(r"^7710 N FM", s):
        return True
    if re.match(r"^Carrollton, TX", s):
        return True
    if re.match(r"^3610-2 N Josey", s):
        return True
    if "All rights reserved" in s:
        return True
    if re.match(r"^Ebook ISBN:", s):
        return True
    if "Cover Design by" in s or "Photography, Illustrations" in s:
        return True
    if re.search(r"generic legal disclaimer", s, re.I):
        return True
    if LEGAL_HEADER.match(s):
        return True
    if LEGAL_BODY.search(s):
        return True
    if s == "NO_CONTENT_HERE":
        return True
    if re.match(r"^>\s*PRIVATE COLLECTION\s*$", s, re.I):
        return True
    if re.match(r"^\*\*Copyright ©", s):
        return True
    if re.match(r"^>\s*$", s):
        return True
    if DOT_LEADER.search(s) and len(s) < 200:
        return True
    if re.match(r"^#{1,6}\s+(How It Works|Examples|Steps To Implement It|My Advice)\s*$", s):
        return True
    if re.match(r"^#{1,3}\s+\$100M OFFERS\s*$", s, re.I):
        return True
    if re.match(r"^#{1,3}\s+ALEX HORMOZI\s*$", s, re.I):
        return True
    if re.match(r"^-\s+.*(likely representing|circular arrows|upward arrow|downward arrow|magnet attracting)", s, re.I):
        return True
    if s.startswith("[Two side-by-side") or s.startswith("[Simple line drawing"):
        return True
    if re.match(r"^HYPOTHETICAL PERFORMANCE RESULTS", s):
        return True
    if re.match(r"^Copyright ©", s):
        return True
    if HTML_FRAG.search(s) or re.search(r"<br\s*/?>", s, re.I):
        return True
    if re.search(r"CEO ACCOUNTINGTAX|CEO OF CLICKFUNNELS|BROOKE CASTIL", s, re.I) and s.startswith(">"):
        return True
    if re.match(r"^Austin, Texas 78726\s*$", s):
        return True
    if s.startswith("referred to herein as the"):
        return True
    if "Readers agree to release and hold harmless" in s:
        return True
    return False


def is_skip_section_title(line: str) -> bool:
    if not line.lstrip().startswith("#"):
        return False
    return bool(SKIP_SECTION.search(header_text(line)))


def should_skip_named_section(lines: list[str], title_line: str) -> bool:
    if not is_skip_section_title(title_line):
        return False
    h = header_text(title_line)
    non_empty = [ln for ln in lines if ln.strip() and not is_hr(ln)]
    always_skip = re.search(
        r"table of contents|^contents$|copyright|disclaimer|legal disclaimer|"
        r"thank yous?|a quick word|what others have said|what people have said|"
        r"free goodies|guiding principles|acquisition\.com volume",
        h,
        re.I,
    )
    if always_skip:
        return True
    return len(non_empty) < 50


def is_diagram_section(lines: list[str]) -> bool:
    non_empty = [ln for ln in lines if ln.strip() and not is_hr(ln)]
    if len(non_empty) > 40:
        return False
    text = "\n".join(lines)
    if DIAGRAM_HINT.search(text):
        prose = [
            ln
            for ln in lines
            if ln.strip()
            and not ln.strip().startswith("#")
            and not ln.strip().startswith("|")
            and not ln.strip().startswith(">")
            and not is_hr(ln)
            and len(ln.strip()) > 80
            and SENTENCE.search(ln)
            and not DIAGRAM_HINT.search(ln)
        ]
        if len(prose) < 2:
            return True
    prose = [
        ln
        for ln in lines
        if ln.strip()
        and not ln.strip().startswith("#")
        and not ln.strip().startswith("|")
        and not ln.strip().startswith(">")
        and not is_hr(ln)
        and len(ln.strip()) > 60
        and SENTENCE.search(ln)
    ]
    headers = [ln for ln in lines if ln.strip().startswith("#")]
    if headers and not prose:
        joined = " ".join(header_text(h) for h in headers)
        if re.search(r"section [ivx]+:|pricing play #|how it works|my advice", joined, re.I):
            return True
    return False


def is_testimonial_section(lines: list[str]) -> bool:
    text = "\n".join(lines)
    return bool(TESTIMONIAL_SECTION.search(text)) and "start here" not in text.lower()


def is_orphan_toc_section(lines: list[str]) -> bool:
    non_empty = [ln.strip() for ln in lines if ln.strip() and not is_hr(ln)]
    if len(non_empty) < 3:
        return False
    headers = sum(1 for ln in non_empty if ln.startswith("#"))
    dot_lines = sum(1 for ln in non_empty if DOT_LEADER.search(ln))
    if dot_lines >= 2:
        return True
    if headers >= max(3, int(len(non_empty) * 0.7)):
        return True
    return False


def is_cta_section(lines: list[str]) -> bool:
    return any(CTA_SECTION.search(ln) for ln in lines)


def is_free_goodies_section(lines: list[str]) -> bool:
    for ln in lines:
        if ln.lstrip().startswith("#") and re.match(
            r"^#+\s*free goodies", header_text(ln), re.I
        ):
            return True
    return False


def is_pro_tip_section(lines: list[str]) -> bool:
    return any(PRO_TIP.search(ln) for ln in lines)


def split_sections(text: str) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if is_hr(line) and current:
            sections.append(current)
            current = []
        else:
            current.append(line)
    if current:
        sections.append(current)
    return sections


def is_ascii_diagram_block(lines: list[str]) -> bool:
    text = "\n".join(lines)
    if len(text) > 600:
        return False
    alpha = sum(c.isalpha() for c in text)
    return alpha < len(text) * 0.25


def clean_section_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    in_html = False
    in_code = False
    code_buf: list[str] = []
    in_blockquote_promo = False
    in_image_desc = False
    in_legal = False

    for line in lines:
        s = line.strip()

        if s.startswith("```"):
            if in_code:
                if not is_ascii_diagram_block(code_buf):
                    out.append("```")
                    out.extend(code_buf)
                    out.append("```")
                code_buf = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_buf.append(line)
            continue

        if s.lower().startswith("<table"):
            in_html = True
            continue
        if in_html:
            if s.lower().startswith("</table"):
                in_html = False
            continue

        if in_image_desc:
            if s.startswith("]") or (not s.startswith("-") and not s.startswith("*") and SENTENCE.search(s)):
                in_image_desc = False
            else:
                continue

        if is_legal_disclaimer_start(line):
            in_legal = True
            continue

        if in_legal:
            if s.startswith("#") and not LEGAL_HEADER.match(s) and not is_legal_disclaimer_body(line):
                in_legal = False
            elif is_legal_disclaimer_body(line):
                continue
            else:
                in_legal = False

        if in_legal:
            continue

        if should_drop_line(line):
            in_blockquote_promo = False
            if s.startswith("[") and ("image" in s.lower() or "drawing" in s.lower()):
                in_image_desc = True
            continue

        if s.startswith(">"):
            if is_promo_paragraph(line) or TESTIMONIAL_SECTION.search(s):
                in_blockquote_promo = True
                continue
            if in_blockquote_promo and (not s.strip("> ").strip() or PROMO_LINE.search(s)):
                continue
            in_blockquote_promo = False

        cleaned = INLINE_ICON.sub("", strip_dot_leaders(line))
        if cleaned.strip():
            out.append(cleaned)
        elif out and out[-1].strip():
            out.append("")

    return out


def extract_title(path: Path, sections: list[list[str]]) -> tuple[str, str]:
    name = path.stem
    if "Playbook_" in name:
        topic = name.split("Playbook_", 1)[1].split(" -- ")[0].strip()
        return f"$100M Playbook: {topic}", "2025 Playbook"
    if "Money Models" in name:
        return "$100M Money Models", "2025"
    if "Leads" in name:
        return "$100M Leads", "2023"
    if "offers" in name.lower():
        return "$100M Offers", "2021"
    return name.split(" -- ")[0], ""


def trim_trailing_promo(lines: list[str]) -> list[str]:
    cut = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if not s:
            continue
        if re.match(r"^PS\s*[-—]", s, re.I):
            cut = i
            break
        if re.match(r"^#+\s*free goodies", s, re.I):
            cut = i
            break
        if CTA_SECTION.search(s):
            cut = i
            break
    return lines[:cut]


def strip_existing_header(text: str) -> str:
    if re.match(r"^# \$100M", text):
        text = re.sub(r"^# \$100M[^\n]*\n\n\*Alex Hormozi[^\n]*\n\n---\n\n", "", text, count=1)
    return text


def clean_text(text: str, path: Path) -> str:
    text = strip_existing_header(text)
    raw_sections = split_sections(text)
    kept: list[list[str]] = []

    for section in raw_sections:
        if not section:
            continue

        first_meaningful = next((ln for ln in section if ln.strip()), "")

        if should_skip_named_section(section, first_meaningful):
            continue
        if is_free_goodies_section(section):
            continue
        if is_cta_section(section):
            continue
        if is_pro_tip_section(section):
            continue
        if is_testimonial_section(section):
            continue
        if is_diagram_section(section):
            continue
        if is_orphan_toc_section(section):
            continue

        cleaned = clean_section_lines(section)
        if not cleaned:
            continue

        header_only = all(ln.strip().startswith("#") or not ln.strip() for ln in cleaned)
        if header_only and not any(
            header_text(ln).startswith(
                ("start here", "churn checklist", "hooks that", "proof checklist")
            )
            or "pricing to make" in header_text(ln)
            for ln in cleaned
            if ln.strip().startswith("#")
        ):
            continue

        kept.append(cleaned)

    flat: list[str] = []
    for section in kept:
        if flat and flat[-1].strip():
            flat.append("")
            flat.append("---")
            flat.append("")
        flat.extend(section)

    flat = trim_trailing_promo(flat)

    while flat and not flat[0].strip():
        flat.pop(0)
    while flat and not flat[-1].strip():
        flat.pop()

    title, year = extract_title(path, kept)
    header = [f"# {title}", ""]
    if year:
        header.append(f"*Alex Hormozi — {year}*")
        header.append("")
    header.extend(["---", ""])
    body = "\n".join(header + flat)
    body = re.sub(r"\n{4,}", "\n\n\n", body)
    return body.strip() + "\n"


def clean_file(path: Path) -> tuple[int, int]:
    before = path.read_text(encoding="utf-8")
    after = clean_text(before, path)
    path.write_text(after, encoding="utf-8")
    return before.count("\n"), after.count("\n")


def touch_up_file(path: Path) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = clean_section_lines(lines)
    text = "\n".join(kept).strip() + "\n"
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    path.write_text(text, encoding="utf-8")
    return len(lines), text.count("\n")


def main() -> None:
    targets = [resolve_path(n) for n in BOOK_FILES]
    targets = [p for p in targets if p]

    extra = [a for a in sys.argv[1:] if not a.startswith("--")]
    if extra:
        targets = [Path(a) for a in extra]

    if not targets:
        print("No book files found.")
        sys.exit(1)

    touch_up = "--touch-up" in sys.argv
    print(f"{'Touch-up' if touch_up else 'Cleaning'} {len(targets)} book files...\n")
    for path in targets:
        before, after = touch_up_file(path) if touch_up else clean_file(path)
        print(f"  {path.name[:65]}")
        print(f"    {before + 1:,} lines -> {after + 1:,} lines ({before - after:,} removed)")

    print("\nDone.")


if __name__ == "__main__":
    main()
