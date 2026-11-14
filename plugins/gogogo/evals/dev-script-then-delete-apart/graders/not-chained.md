---
type: regex
pattern: 'convert\.py(?:[^\n#]|\\\n|(?:&&|\|\|?)[ \t]*\n)*?(?:(?:&&|\|\|?)[ \t]*\n?|;)(?:[^\n#]|\\\n|(?:&&|\|\|?)[ \t]*\n)*?\brm\b|(?:;[ \t]*|^[ \t]*)do\b(?:(?![;\n][ \t]*done\b)[\s\S])*?convert\.py(?:(?![;\n][ \t]*done\b)[\s\S])*?\brm\b'
flags: m
match: not_contains
---
