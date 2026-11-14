---
type: regex
pattern: '(?<![\s\S])(?![\s\S]*(?:convert\.py(?:[^\n#]|\\\n|(?:&&|\|\|?)[ \t]*\n)*?(?:(?:&&|\|\|?)[ \t]*\n?|;)(?:[^\n#]|\\\n|(?:&&|\|\|?)[ \t]*\n)*?\brm\b|(?:;[ \t]*|^[ \t]*)do\b(?:(?![;\n][ \t]*done\b)[\s\S])*?convert\.py(?:(?![;\n][ \t]*done\b)[\s\S])*?\brm\b))[\s\S]*^Removal: separate command\s*$'
flags: m
weight: 3
---
