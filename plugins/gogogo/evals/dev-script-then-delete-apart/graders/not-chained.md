---
type: regex
pattern: 'convert\.py[^\n]*(?:&&|;|\|)(?:[^\n]*|[ \t]*\\\n[^\n]*)\brm\b|\bdo\b(?:(?!\bdone\b)[\s\S])*?convert\.py(?:(?!\bdone\b)[\s\S])*?\brm\b'
match: not_contains
---
