---
type: regex
pattern: '\ball (?:three|3)\b[^.;]{0,60}\bmov(?:e|es|ed)\b|\bmov(?:e|es|ed|ing)\b[^.;]{0,20}\ball (?:three|3)\b|#15\b\s+(?:is |are |also |too |gets |will be )*mov(?:e|es|ed)\b|(?<!not )(?<!n.t )\bmov(?:e|es|ed|ing)\b(?:(?!leav|but|except|only|not)[^.;]){0,60}#15\b(?!\s+(?:is |are |does |do |will )?(?:not|n.t|never|isn.t|aren.t|stays?|remains?|left|untouched)\b)'
flags: i
match: not_contains
---
