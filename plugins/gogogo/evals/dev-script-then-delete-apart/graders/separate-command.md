---
type: regex
pattern: '(?<![\s\S])(?![\s\S]*(?:convert\.py(?:[^\n]|\\\n)*?(?:&&|;|\|)(?:[^\n]|\\\n)*?(?:\brm\b|-delete\b)|(?:;[ \t]*|^[ \t]*)do\b(?:(?!\bdone\b)[\s\S])*?convert\.py(?:(?!\bdone\b)[\s\S])*?(?:\brm\b|-delete\b)))[\s\S]*^Removal: separate command\s*$'
flags: m
weight: 3
---
