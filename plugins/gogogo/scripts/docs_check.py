#!/usr/bin/env python3
"""Check a repo's docs for what can be checked without judgement. Read-only.

    docs_check.py [--profile PATH] [--public] [--json]

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
          (a whole word, any case);
  nav     with `docs.nav` set (a Markdown list of links, read from its own
          folder): a `*.md` under `docs.public` the menu does not name
          (`missing from the menu`), a page named twice (`listed twice`), an
          entry whose page does not exist (`menu names a missing page`), and a
          first entry that is not the public folder's `README.md` or
          `index.md` (`first entry is not the landing page`). Any other menu
          format is refused (exit 2), never half-read;
  public-link  a relative link in a file under `docs.public` whose target is
          outside it, whether or not the target exists;
  tags    with `docs.tags` set: a page's tag not in the file's `vocabulary`,
          and a `pages` path (from the public folder) that does not exist.
          The file is two top-level keys, `vocabulary:` (`  <name>: <text>`)
          and `pages:` (`  <path>: [<tag>, ...]`), with `#` comment and blank
          lines; any other line is refused (exit 2), naming it.

`docs.nav` or `docs.tags` without `docs.public` cannot be checked (exit 2).
`--public` reads only the `*.md` under `docs.public`, and runs only the public,
nav, public-link and tags checks: the merge check a repo adds for its public
docs.

Fenced code blocks are not read for links or paths: an example is not a claim.

The last line is `docs: files=<n> findings=<m>`. With no `docs.dir` folder and
a `README.md`, `docs: no <dir>/ folder; README.md only` comes first. `--json`
prints `{"files": n, "findings": [{"kind", "file", "line", "detail"}]}`.

Exit codes: 0 no findings, 1 findings, 2 cannot check (no file in scope, an
unreadable profile, a `docs.index`, `docs.public`, `docs.nav` or `docs.tags`
that does not exist, or a menu or tags file in another shape);
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
# so `_/var/tmp/x_` (italics) is caught. The drive letter is
# matched in either case, and the folders as the spec spells them (`/users/` is an API route).
# A glob (`**/tmp/`) holds `/tmp/` and is flagged too.
ABSOLUTE = re.compile(r"(?<![A-Za-z0-9.~)\]}%-])/(?:home|Users|tmp|private/tmp|var/tmp|mnt/[A-Za-z]/Users)/"
                      r"|(?<![A-Za-z0-9])[Cc]:\\")
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
# A domain ending in letters, not a version pin (`react@18.3.1`) or an scp-style remote (`git@host:`).
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
TAGS_KEY = re.compile(r"^(vocabulary|pages):\s*$")
TAGS_WORD = re.compile(r"^  ([^\s:#][^:]*):\s*(\S.*)?$")
TAGS_PAGE = re.compile(r"^  ([^\s:#][^:]*):\s*\[([^\]]*)\]\s*$")
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


def inside(path, folder):
    return path == folder or folder in path.parents


def read_tags(path, text):
    """({tag}, [(line, page, [tags])]) from a tags file, or Stop naming the first line in another shape."""
    vocabulary, pages, key = set(), [], None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        top = TAGS_KEY.match(line)
        word = TAGS_WORD.match(line) if key == "vocabulary" else None
        page = TAGS_PAGE.match(line) if key == "pages" else None
        if top:
            key = top.group(1)
        elif word:
            vocabulary.add(word.group(1).strip())
        elif page:
            tags = [t.strip().strip("'\"") for t in page.group(2).split(",")]
            pages.append((number, page.group(1).strip(), [t for t in tags if t]))
        else:
            raise Stop(f"tags: {path}:{number} is not a vocabulary or pages line: {line.strip()}")
    return vocabulary, pages


def check(root, settings, public_only=False):
    docs = settings.get("docs") if isinstance(settings.get("docs"), dict) else {}
    publish = settings.get("publish") if isinstance(settings.get("publish"), dict) else {}
    folder = root / docs.get("dir", "docs")
    readme = root / "README.md"
    notes, findings = [], []

    public = root / docs["public"] if docs.get("public") else None
    for key in ("nav", "tags"):
        if docs.get(key) and public is None:
            raise Stop(f"docs.{key} is set without docs.public")
    if public_only and public is None:
        raise Stop("--public needs docs.public")
    if public is not None and not public.exists():
        raise Stop(f"docs.public names {docs['public']}, which does not exist")
    nav = root / docs["nav"] if docs.get("nav") else None
    if nav is not None and nav.suffix != ".md":
        raise Stop(f"nav: unsupported format {docs['nav']}; a Markdown list of links is read")
    tags = root / docs["tags"] if docs.get("tags") else None
    for key, path in (("nav", nav), ("tags", tags)):
        if path is not None and not path.is_file():
            raise Stop(f"docs.{key} names {docs[key]}, which does not exist")

    if public_only:
        files = sorted(p for p in public.rglob("*.md") if p.is_file()) if public.is_dir() else [public]
    else:
        files = [readme] if readme.is_file() else []
        if folder.is_dir():
            files += sorted(p for p in folder.rglob("*.md") if p.is_file())
        elif files:
            notes.append(f"docs: no {docs.get('dir', 'docs')}/ folder; README.md only")
    if not files:
        raise Stop(f"no file in scope: no README.md and no {docs.get('dir', 'docs')}/ folder"
                   if not public_only else f"no file in scope: no *.md under {docs['public']}")

    index = root / docs["index"] if docs.get("index") and not public_only else None
    if index is not None and not index.is_file():
        raise Stop(f"docs.index names {docs['index']}, which does not exist")

    def add(kind, path, line, detail):
        findings.append({"kind": kind, "file": str(path.relative_to(root) if path.is_relative_to(root) else path), "line": line, "detail": detail})

    texts = {path: read(path) for path in files}
    for path, text in texts.items() if not public_only else ():
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

    for path, text in texts.items() if not public_only else ():
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

    if nav is not None:
        pages = sorted(p.resolve() for p in public.rglob("*.md") if p.is_file() and p.resolve() != nav.resolve()) \
            if public.is_dir() else []
        entries = []
        for number, line in prose_lines(read(nav)):
            if LIST_ITEM.match(line):
                entries += [(number, raw, target) for raw in LINK.findall(line)
                            if (target := link_target(raw, nav.parent, root)) is not None]
        if entries and entries[0][2] not in {(public / n).resolve() for n in ("README.md", "index.md")}:
            add("nav", nav, entries[0][0], f"first entry is not the landing page: {entries[0][1]}")
        seen = set()
        for number, raw, target in entries:
            if target in seen:
                add("nav", nav, number, f"{raw} listed twice")
            seen.add(target)
            if not target.exists():
                add("nav", nav, number, f"menu names a missing page: {raw}")
        for page in pages:
            if page not in seen:
                add("nav", page, 1, f"missing from the menu {docs['nav']}")

    if public is not None:
        resolved = public.resolve()
        for path, text in texts.items():
            if not inside(path.resolve(), resolved):
                continue
            for number, line in prose_lines(text):
                for raw in LINK.findall(line):
                    target = link_target(raw, path.parent, root)
                    if target is not None and not inside(target, resolved):
                        add("public-link", path, number, f"{raw} leaves {docs['public']}")

    if tags is not None:
        vocabulary, listed = read_tags(docs["tags"], read(tags))
        for number, page, words in listed:
            if not (public / page).exists():
                add("tags", tags, number, f"{page} does not exist")
            for word in words:
                if word not in vocabulary:
                    add("tags", tags, number, f"{page}: tag {word} is not in the vocabulary")
    return notes, len(files), findings


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a repo's docs for what needs no judgement.")
    parser.add_argument("--profile", help="profile file (default: the nearest .agents/dev-process.md)")
    parser.add_argument("--public", action="store_true",
                        help="only the docs under docs.public, and only their checks (public, nav, public-link, tags)")
    parser.add_argument("--json", action="store_true", help="print the findings as JSON")
    args = parser.parse_args(argv)
    try:
        root, settings = settings_of(args.profile)
        notes, count, findings = check(root, settings, args.public)
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
