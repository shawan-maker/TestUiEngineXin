"""Fix old Phase numbering in design docs — ALL old → placeholders → resolve.

Old → New:  0→0  0.5→1  1→2  3→4  3.5→3  3f→6  4a→5  4b→7  5→8  6→9
"""
import re, os

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "design")

FILENAMES = [
    ("phase05-parse-validation-design.md",         "phase1-parse-validation-design.md"),
    ("phase1-scaffold-generation-design.md",        "phase2-scaffold-generation-design.md"),
    ("phase3-5-module-keywords-compiler-design.md", "phase3-module-keywords-compiler-design.md"),
    ("phase3-discovery-design.md",                  "phase4-discovery-design.md"),
    ("phase3f-locator-verification-design.md",      "phase6-locator-verification-design.md"),
    ("phase3-4a-3f-full-business-logic.md",         "phase4-5-6-full-business-logic.md"),
    ("phase4a-case-generation-design.md",           "phase5-case-generation-design.md"),
    ("phase4b-suite-generation-design.md",          "phase7-suite-generation-design.md"),
    ("phase5-cross-file-validation-design.md",      "phase8-cross-file-validation-design.md"),
    ("phase6-execution-validation-design.md",       "phase9-execution-validation-design.md"),
]

def fix(text):
    # Step 1: Filename refs
    for old, new in FILENAMES:
        text = text.replace(old, new)

    # Step 2: ALL old Phase numbers → unique placeholders (longest first, no cascading)
    text = re.sub(r'\bPhase\s*0\.5\b', '\x00P1\x00', text)   # old 0.5 → new 1
    text = re.sub(r'\bPhase\s*3\.5\b', '\x00P3\x00', text)   # old 3.5 → new 3
    text = re.sub(r'\bPhase\s*3f\b',   '\x00P6\x00', text)   # old 3f  → new 6
    text = re.sub(r'\bPhase\s*4a\b',   '\x00P5\x00', text)   # old 4a  → new 5
    text = re.sub(r'\bPhase\s*4b\b',   '\x00P7\x00', text)   # old 4b  → new 7
    text = re.sub(r'\bPhase\s*6\b',    '\x00P9\x00', text)   # old 6   → new 9
    text = re.sub(r'\bPhase\s*5\b',    '\x00P8\x00', text)   # old 5   → new 8
    text = re.sub(r'\bPhase\s*3\b',    '\x00P4\x00', text)   # old 3   → new 4
    text = re.sub(r'\bPhase\s*1\b',    '\x00P2\x00', text)   # old 1   → new 2
    # Phase 0 stays Phase 0 — no replacement needed

    # Step 3: Resolve placeholders
    for n in range(1, 10):
        text = text.replace(f'\x00P{n}\x00', f'Phase {n}')

    # Step 4: Fix compound patterns that got split by placeholder resolution
    # "Phase 3/4a/3f" was "Phase 3" + "/" + "4a" + "/" + "3f"
    # → placeholders: \x00P4\x00/4a/3f  — no, 4a and 3f are AFTER Phase 3, not part of the same word
    # Actually "Phase 3/4a/3f" matches "Phase 3" but not "Phase 4a" (no space before 4a)
    # So it becomes "\x00P4\x00/4a/3f" which resolves to "Phase 4/4a/3f" — WRONG
    # Need to handle this BEFORE simple replacements

    return text

# Better approach: handle compound patterns BEFORE simple ones
def fix_v2(text):
    # Step 1: Filename refs
    for old, new in FILENAMES:
        text = text.replace(old, new)

    # Step 2: Compound patterns → placeholders (MUST come before simple)
    text = re.sub(r'Phase\s*3/4a/3f',       '\x00P4/5/6\x00', text)
    text = re.sub(r'Phase\s*3\s*/\s*4a\s*/\s*3f', '\x00P4/5/6\x00', text)
    text = re.sub(r'Phase\s*3/3f/3\.5',     '\x00P4/6/3\x00', text)
    text = re.sub(r'Phase\s*3\s*/\s*3f\s*/\s*3\.5', '\x00P4/6/3\x00', text)
    text = re.sub(r'Phase\s*4\s*/\s*5\s*/\s*6', '\x00P4/5/6\x00', text)
    # Old execution sequence string
    text = text.replace(
        'Phase 0 → 0.5 → 1 → 3 → pages YAML → 4a(cases) → **3f** → 3g(可选) → 3.5 → 4b(suites) → 5 → 6',
        'Phase 0 → 1 → 2 → 4 → pages YAML → 5(cases) → **6** → (可选) → 3 → 7(suites) → 8 → 9')
    text = text.replace(
        'Phase 0 → 0.5 → 1 → 3 → pages YAML → 4a → 3f → 3g(可选) → 3.5 → 4b → 5 → 6',
        'Phase 0 → 1 → 2 → 4 → pages YAML → 5 → 6 → (可选) → 3 → 7 → 8 → 9')

    # Step 3: ALL old Phase numbers → unique placeholders
    text = re.sub(r'\bPhase\s*0\.5\b', '\x00P1\x00', text)
    text = re.sub(r'\bPhase\s*3\.5\b', '\x00P3\x00', text)
    text = re.sub(r'\bPhase\s*3f\b',   '\x00P6\x00', text)
    text = re.sub(r'\bPhase\s*4a\b',   '\x00P5\x00', text)
    text = re.sub(r'\bPhase\s*4b\b',   '\x00P7\x00', text)
    text = re.sub(r'\bPhase\s*6\b',    '\x00P9\x00', text)
    text = re.sub(r'\bPhase\s*5\b',    '\x00P8\x00', text)
    text = re.sub(r'\bPhase\s*3\b',    '\x00P4\x00', text)
    text = re.sub(r'\bPhase\s*1\b',    '\x00P2\x00', text)

    # Step 4: Resolve placeholders
    for n in range(1, 10):
        text = text.replace(f'\x00P{n}\x00', f'Phase {n}')
    text = text.replace('\x00P4/5/6\x00', 'Phase 4/5/6')
    text = text.replace('\x00P4/6/3\x00', 'Phase 4/6/3')

    return text


def main():
    for fname in sorted(os.listdir(DIR)):
        if not fname.endswith('.md'):
            continue
        fpath = os.path.join(DIR, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            old = f.read()
        new = fix_v2(old)
        if old != new:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(new)
            print(f"FIXED: {fname}")
        else:
            print(f"OK:    {fname}")

    # Rename files
    print("\n--- Renames ---")
    for old_name, new_name in FILENAMES:
        old_path = os.path.join(DIR, old_name)
        new_path = os.path.join(DIR, new_name)
        if os.path.exists(old_path) and not os.path.exists(new_path):
            os.rename(old_path, new_path)
            print(f"  {old_name} → {new_name}")
        elif os.path.exists(old_path):
            print(f"  SKIP: {new_name} already exists")
        else:
            print(f"  SKIP: {old_name} not found")

if __name__ == '__main__':
    main()
