---
type: regex
pattern: 'convert\.py(?:[^\n]|\\\n)*?(?:&&|;|\|)(?:[^\n]|\\\n)*?(?:\brm\b|-delete\b)|(?:;[ \t]*|^[ \t]*)do\b(?:(?!\bdone\b)[\s\S])*?convert\.py(?:(?!\bdone\b)[\s\S])*?(?:\brm\b|-delete\b)'
flags: m
match: not_contains
---
