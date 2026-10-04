---
type: regex
pattern: '\ball (?:three|3)\b(?:(?!not|n.t|never)[^.;]){0,60}\bmov(?:e|es|ed)\b|(?<!not )(?<!n.t )\bmov(?:e|es|ed|ing)\b[^.;]{0,20}\ball (?:three|3)\b|#15\b\s+(?:is |are |also |all |too |gets |will be )*mov(?:e|es|ed)\b|(?<!not )(?<!n.t )\bmov(?:e|es|ed|ing)\b(?:(?!leav|but|except|only|not|skip|ignor|while|which|whereas)[^.;]){0,60}#15\b(?!\s+(?:is |are |does |do |will )?(?:not|n.t|never|isn.t|aren.t|stays?|remains?|left|untouched|skipped|ignored)\b)'
flags: i
match: not_contains
---
