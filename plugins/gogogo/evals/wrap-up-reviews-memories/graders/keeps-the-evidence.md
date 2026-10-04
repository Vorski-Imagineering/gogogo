---
type: regex
pattern: '(?<!\bnever\s)(?<!\bnot\s)(?<!n.t\s)(?:deletes?|removes?)\s+(?:both|each|all)\b|(?<!\bnever\s)(?<!\bnot\s)(?<!n.t\s)(?:deletes?|removes?)\s+(?:the\s+|that\s+)?second\b|\bboth\b(?:(?!\b(?:not|never|neither|kept|keeps?|stays?)\b)[^.;]){0,30}\b(?:deleted|removed)|\bsecond\b(?:(?!\b(?:not|never|kept|keeps?|stays?)\b)[^.;]){0,40}\b(?:deleted|removed)\b'
flags: i
match: not_contains
---
