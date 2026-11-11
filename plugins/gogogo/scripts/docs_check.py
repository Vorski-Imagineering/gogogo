#!/usr/bin/env python3
"""Check a repo's docs for what can be checked without judgement. Read-only.

    docs_check.py [--profile PATH] [--json]

The files in scope are `README.md` at the repo root, when present, and every
`*.md` under the profile's `docs.dir` (absent: `docs`). The repo root is the
folder that holds the profile's `.agents/`. Each finding is one line,
`<kind> <file>:<line>: <detail>`, by these checks in this order:

  link    a relative Markdown link whose target (URL-decoded, `#anchor`
          dropped) does not exist; links with `://` or `mailto:` are skipped;
  index   with `docs.index` set, a file under `docs.dir` (other than the
          index) that the index does not link to;
  path    a backticked token holding `/` that names something under the repo
          (no space, `<` or `*`, and its first segment exists at the root)
          and does not exist; a trailing `:<line>` or `::<test>` is dropped;
  public  with `docs.public` set, a line in a file under it holding an
          absolute path (`/home/`, `/Users/`, `/tmp/`, `/private/tmp/`,
          `/var/tmp/`, `/mnt/<drive>/Users/`, `C:\\`), an IPv4
          address, an email address, or a `publish.private_names` entry
          (a whole word, any case).

Fenced code blocks are not read for links or paths: an example is not a claim.

The last line is `docs: files=<n> findings=<m>`. With no `docs.dir` folder and
a `README.md`, `docs: no <dir>/ folder; README.md only` comes first. `--json`
prints `{"files": n, "findings": [{"kind", "file", "line", "detail"}]}`.

Exit codes: 0 no findings, 1 findings, 2 cannot check (no file in scope, an
unreadable profile, or a `docs.index` or `docs.public` that does not exist);
the reason is on stderr. No evidence never passes. Standard library only.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import profile_check  # noqa: E402

EXIT_OK, EXIT_FINDINGS, EXIT_STOP = 0, 1, 2
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
TICKED = re.compile(r"`([^`\n]+)`")
# The prefixes Design 1.4 names, and the three a person added; not when the character
# before shows a relative path, a host, an address or a placeholder goes on (`src/home/`,
# `x.example/tmp/`, `[::1]/tmp/`, `X_(y)/tmp/`, `${HOME}/tmp/`, `%TEMP%/tmp/`). `_` is left out,
# so `_/var/tmp/x_` (italics) is caught. A glob (`**/tmp/`) holds `/tmp/` and is flagged too.
ABSOLUTE = re.compile(r"(?<![A-Za-z0-9.~)\]}%-])/(?:home|Users|tmp|private/tmp|var/tmp|mnt/[A-Za-z]/Users)/"
                      r"|(?<!\w)C:\\")
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# A domain ending in letters, not a version pin (`react@18.3.1`) or an scp-style remote (`git@host:`).
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b(?![:\w-]|\.\w)")


class Stop(Exception):
    """The docs cannot be checked; the message says why."""


def settings_of(profile):
    path = Path(profile) if profile else profile_check.find_profile()
    try:
        settings, _ = profile_check.split_profile(path.read_text(encoding="utf-8"))
    except (OSError, profile_check.ProfileError) as exc:
        raise Stop(f"profile: cannot read {path}: {exc}") from None
    return path.resolve().parent.parent, settings


def prose_lines(text):
    """(line number, line) for each line outside fenced code blocks."""
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            yield number, line


def link_target(raw, folder, root):
    """The path a relative link points at, or None when it is not a relative file link.
    A link starting `/` is from the repo root, as GitHub reads it."""
    if "://" in raw or raw.startswith("mailto:"):
        return None
    target = unquote(raw.split("#", 1)[0])
    if not target:
        return None
    return (root / target.lstrip("/")).resolve() if target.startswith("/") else (folder / target).resolve()


def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Stop(f"cannot read {path}: {exc}") from None


def path_token(token):
    """A backticked token read as a repo path, or None."""
    if "/" not in token or token.startswith("/") or " " in token or "<" in token or "*" in token:
        return None
    token = re.sub(r"::.*$", "", token)
    return re.sub(r":\d+(?:-\d+)?$", "", token)


def check(root, settings):
    docs = settings.get("docs") if isinstance(settings.get("docs"), dict) else {}
    publish = settings.get("publish") if isinstance(settings.get("publish"), dict) else {}
    folder = root / docs.get("dir", "docs")
    readme = root / "README.md"
    notes, findings = [], []

    files = [readme] if readme.is_file() else []
    if folder.is_dir():
        files += sorted(p for p in folder.rglob("*.md") if p.is_file())
    elif files:
        notes.append(f"docs: no {docs.get('dir', 'docs')}/ folder; README.md only")
    if not files:
        raise Stop(f"no file in scope: no README.md and no {docs.get('dir', 'docs')}/ folder")

    index = root / docs["index"] if docs.get("index") else None
    if index is not None and not index.is_file():
        raise Stop(f"docs.index names {docs['index']}, which does not exist")
    public = root / docs["public"] if docs.get("public") else None
    if public is not None and not public.exists():
        raise Stop(f"docs.public names {docs['public']}, which does not exist")

    def add(kind, path, line, detail):
        findings.append({"kind": kind, "file": str(path.relative_to(root) if path.is_relative_to(root) else path), "line": line, "detail": detail})

    texts = {path: read(path) for path in files}
    for path, text in texts.items():
        for number, line in prose_lines(text):
            for raw in LINK.findall(line):
                target = link_target(raw, path.parent, root)
                if target is not None and not target.exists():
                    add("link", path, number, f"{raw} does not exist")

    if index is not None:
        listed = {link_target(raw, index.parent, root)
                  for raw in LINK.findall(texts[index] if index in texts else read(index))}
        for path in files:
            if path.resolve() != index.resolve() and folder in path.parents and path.resolve() not in listed:
                add("index", path, 1, f"not linked from {docs['index']}")

    for path, text in texts.items():
        for number, line in prose_lines(text):
            for token in TICKED.findall(line):
                name = path_token(token)
                if name and (root / name.split("/")[0]).exists() and not (root / name).exists():
                    add("path", path, number, f"`{token}` does not exist")

    if public is not None:
        names = [n for n in publish.get("private_names") or [] if isinstance(n, str) and n]
        private = [re.compile(rf"(?<!\w){re.escape(n)}(?!\w)", re.I) for n in names]
        for path, text in texts.items():
            if path != public and public not in path.parents:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                for pattern, what in ((ABSOLUTE, "an absolute path"), (IPV4, "an IP address"),
                                      (EMAIL, "an email address"), *((p, "a private name") for p in private)):
                    if pattern.search(line):
                        add("public", path, number, f"holds {what}")
    return notes, len(files), findings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a repo's docs for what needs no judgement.")
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
    parser.add_argument("--json", action="store_true", help="print the findings as JSON")
    args = parser.parse_args(argv)
    try:
        root, settings = settings_of(args.profile)
        notes, count, findings = check(root, settings)
    except Stop as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(json.dumps({"files": 0, "findings": []}) if args.json else "docs: files=0 findings=0")
        return EXIT_STOP
    if args.json:
        print(json.dumps({"files": count, "findings": findings}))
    else:
        for line in notes:
            print(line)
        for f in findings:
            print(f"{f['kind']} {f['file']}:{f['line']}: {f['detail']}")
        print(f"docs: files={count} findings={len(findings)}")
    return EXIT_FINDINGS if findings else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
