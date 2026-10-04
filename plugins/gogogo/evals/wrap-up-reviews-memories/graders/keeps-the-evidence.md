---
type: regex
pattern: 'delet\w*\s+(?:both|each|the second)|(?:both|each)\b[^.]{0,40}\b(?:delet|remov)|second\b[^.]{0,60}\b(?:is|gets|are|will be)\s+(?:also\s+)?(?:delet|remov)'
flags: i
match: not_contains
---
