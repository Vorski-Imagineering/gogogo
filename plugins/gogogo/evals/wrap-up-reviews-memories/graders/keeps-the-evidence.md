---
type: regex
pattern: '(?:deletes?|removes?)\s+(?:both|each|all)\b|\bboth\b[^.;]{0,30}\b(?:deleted|removed)|\bsecond\b(?:(?!\b(?:not|never|kept|stays?)\b)[^.;]){0,40}\b(?:deleted|removed)\b'
flags: i
match: not_contains
---
