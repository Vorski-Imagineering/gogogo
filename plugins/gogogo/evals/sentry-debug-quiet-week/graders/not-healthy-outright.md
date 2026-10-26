---
type: regex
pattern: '^\W*yes\b|(?<!\b(?:say|call|claim|confirm|know|tell|whether|if|proof|prove|proves|show|shows|mean|means|evidence)\b[^.!?\n]{0,15})\b(?:was|is|were)\s+(?:perfectly\s+|fully\s+|completely\s+)?healthy\b'
flags: i
match: not_contains
---
