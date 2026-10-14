#!/usr/bin/env python3
"""Build the Claudia Grok Bot template recipe: skills/dist/recipe.json.

    python skills/build_recipe.py                  validate and write skills/dist/recipe.json (exit 1 on any problem)
    python skills/build_recipe.py --check          validate only; print the size report
    python skills/build_recipe.py --plugin-id ID   override the Higgsfield marketplace plugin id (default PLUGIN_ID_DEFAULT)
    python skills/build_recipe.py --release        also refuse the placeholder plugin id (use before publishing)
    add --json for one JSON object on stdout

Sources (all under skills/):
    <slug>/SKILL.md                 one per skill in ORDER; YAML front matter `name` (= the folder) and `description`
                                    (starts "Use when"); recipe content = the whole file, front matter included
    profile.md                      front matter `name: Claudia`; the body is the bot's instructions (profile.description)
    routines/<slug>.md              front matter `name`, `slug` (= the file name), `description`; the body is the content
    memory.md                       front matter `kind: log`; the body is the memory's content

The recipe follows the Grok Bot template schema (research notes §8.1): {profile{name, description}, memory[{kind,
content}], skills[{name, description, content}], routines[{name, slug, description, content}], plugins[{name,
description, pluginId}], gettingStarted{skill}}. Import is replayed by the model, so the text budget is enforced:
<= 6 KB per skill, <= 3 KB of profile, <= 80 KB for everything the importer re-emits (skill contents and their
descriptions again, profile, routines, memory, plugin descriptions). Every text is scrubbed (the hashed private-word
list in tests/scrublist.py plus the patterns below) and linted (owner text never in double quotes) before anything
is written.

Standard library only (runs on the bot's computer before or without the toolkit's venv).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent
ROOT = SKILLS_DIR.parent
DIST = SKILLS_DIR / "dist" / "recipe.json"

# the Grok side: sign-ins and delegation only (Opus on the box is the production)
ORDER = ["claudia-welcome", "claudia-setup", "claudia-relay", "hedra", "grok-imagine", "midjourney", "suno", "drive",
         "setup-accounts", "setup-agents", "claudia-toolkit"]
# kept in the repository, not shipped yet: the home-GPU link waits for the relay (the bot's computer cannot open a
# quick tunnel); the checklist offers it only with SLOP_GPU_LINK=1
PARKED = ["setup-gpu"]
# stage guides kept in the repository for the production (Opus reads them); not part of the Grok Bot template
PRODUCTION = ["mv-quick", "mv-studio", "mv-director", "song", "taste", "storyboard", "plates", "clips",
              "render-and-review", "browser-assist"]
GETTING_STARTED = "claudia-welcome"
PROFILE_NAME = "Claudia"
PLUGIN_PLACEHOLDER = "<TBD-HIGGSFIELD-PLUGIN-ID>"
# recorded on a Grok Bot account (research notes 00, "Later checks"); confirm once with SearchPlugins before publishing
PLUGIN_ID_DEFAULT = "5420454"
PLUGIN = {"name": "Higgsfield",
          "description": "Video, image and audio generation (Seedance, Kling, Veo, Wan and more) with the user's own "
                         "Higgsfield credits. Optional: Opus does not use it yet (its clips go through OpenRouter)."}

KB = 1024
MAX_SKILL = 6 * KB
MAX_PROFILE = 3 * KB
MAX_TOTAL = 80 * KB                     # everything the importer re-emits
MAX_RECIPE = 25 * KB * KB              # the platform refuses a larger blob
MAX_DESCRIPTION = 400

FRONT = re.compile(r"^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)")        # the platform's own front-matter regex
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# patterns on top of the hashed word list, which already covers private hosts and any tailnet DNS name (nothing private
# is spelled here)
SCRUB_PATTERNS = [
    (re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"), "a tailnet (CGNAT) address"),
    (re.compile(r"sk-or-v1-[0-9a-f]{8,}|\bsk-ant-[A-Za-z0-9_-]{8,}|\bsk-[A-Za-z0-9]{24,}"), "an API key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
    (re.compile(r"\b[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)\s*=\s*['\"]?[A-Za-z0-9_\-./+]{8,}"), "a secret value"),
    (re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "a job id (UUID)"),
    (re.compile(r"\bgen-vid-\d{6,}"), "an OpenRouter video job id"),
    (re.compile(r"(?i)midjourney\.com/jobs/[0-9a-f]|cdn\.midjourney\.com/[0-9a-f]{8}-"), "a Midjourney job id"),
    (re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!you\b|user\b|name\b)[^\\/\s\"'`<>]+"), "a Windows user folder"),
    (re.compile(r"(?<![\w.])/home/(?!box\b|user\b|you\b)[a-z_][a-z0-9_-]*"), "a private /home folder"),
    (re.compile(r"(?i)/mnt/[a-z]/users/"), "a Windows user folder seen from WSL"),
    (re.compile(r"(?i)\bworkshop[\\/]+(?:slop|claudia)"), "a local checkout path"),
    (re.compile(r"(?i)--p\s+(?!<)[a-z0-9]{5,}\b"), "a Midjourney profile code"),
]


def _scrublist():
    """tests/scrublist.py (the hashed private words); None when the tests are not shipped alongside."""
    path = ROOT / "tests" / "scrublist.py"
    if not path.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("claudia_scrublist", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def scrub_problems(label: str, text: str) -> list[str]:
    """Why `text` must not ship ('label: line N: reason'), never the offending word itself."""
    out = []
    sl = _scrublist()
    if sl is None:
        out.append(f"{label}: tests/scrublist.py not found - cannot check the private-word list")
    else:
        out += [f"{label}: {h}" for h in sl.private_hits(text)]
    for n, line in enumerate(text.splitlines(), 1):
        out += [f"{label}: line {n}: {why}" for rx, why in SCRUB_PATTERNS if rx.search(line)]
    return out


def lint_problems(label: str, text: str) -> list[str]:
    """Shell-safety rules for the commands a weaker model copies: the owner's words go in single quotes (bash expands
    $ and ` inside double quotes, so a quoted "$20" would be recorded as "0")."""
    return [f"{label}: line {n}: a <placeholder> in double quotes: write '<...>' (single quotes)"
            for n, line in enumerate(text.splitlines(), 1) if '"<' in line]


def front_matter(text: str) -> tuple[dict[str, str], str]:
    """({key: value}, body) for the simple `key: value` front matter the platform writes; body without it."""
    m = FRONT.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        k, sep, v = line.partition(":")
        if not sep:
            meta.setdefault("__bad__", line)
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = json.loads(v) if v[0] == '"' else v[1:-1]
        meta[k.strip()] = v
    return meta, text[m.end():]


def _plain_scalar_problem(key: str, value: str) -> str | None:
    """A front-matter value must survive any YAML reader as a plain scalar."""
    if ": " in value or " #" in value:
        return f"{key} contains ': ' or ' #' (YAML would split it): rephrase without them"
    if value[:1] in "!&*?|>%@`{[\"'-#,":
        return f"{key} starts with a YAML special character"
    return None


def nbytes(s: str) -> int:
    return len(s.encode("utf-8"))


def load_skills(problems: list[str]) -> list[dict]:
    skills = []
    dirs = sorted(p.parent.name for p in SKILLS_DIR.glob("*/SKILL.md"))
    extra = [d for d in dirs if d not in ORDER and d not in PRODUCTION and d not in PARKED]
    missing = [s for s in ORDER if s not in dirs]
    if extra:
        problems.append(f"skills not in ORDER (add them to build_recipe.ORDER or remove them): {', '.join(extra)}")
    if missing:
        problems.append(f"skills missing: {', '.join(missing)} (each needs skills/<slug>/SKILL.md)")
    for slug in [s for s in ORDER if s in dirs]:
        path = SKILLS_DIR / slug / "SKILL.md"
        text = path.read_text(encoding="utf-8")
        label = f"skills/{slug}/SKILL.md"
        if "\r" in text:
            problems.append(f"{label}: CRLF line endings (use LF)")
        meta, body = front_matter(text)
        name, desc = meta.get("name", ""), meta.get("description", "")
        if not meta:
            problems.append(f"{label}: no front matter (--- name/description ---)")
        if "__bad__" in meta:
            problems.append(f"{label}: front matter line without 'key: value': {meta['__bad__']!r}")
        if name != slug or not SLUG.match(name or "-"):
            problems.append(f"{label}: front matter name {name!r} must equal the folder name {slug!r}")
        if not desc.startswith("Use when"):
            problems.append(f"{label}: description must start with 'Use when' (it is how the bot picks the skill)")
        if len(desc) > MAX_DESCRIPTION:
            problems.append(f"{label}: description is {len(desc)} characters (max {MAX_DESCRIPTION})")
        for k in ("name", "description"):
            why = _plain_scalar_problem(k, meta.get(k, "") or "x")
            if why:
                problems.append(f"{label}: {why}")
        if not re.search(r"^# \S", body, flags=re.M):
            problems.append(f"{label}: no '# Title' line in the body (the platform takes the display title from it)")
        if nbytes(text) > MAX_SKILL:
            problems.append(f"{label}: {nbytes(text)} bytes (max {MAX_SKILL}): move detail into docs/ and point to it")
        problems += scrub_problems(label, text) + lint_problems(label, text)
        skills.append({"name": name or slug, "description": desc, "content": text})
    return skills


def load_profile(problems: list[str]) -> dict:
    path = SKILLS_DIR / "profile.md"
    if not path.is_file():
        problems.append("skills/profile.md missing")
        return {"name": PROFILE_NAME, "description": ""}
    text = path.read_text(encoding="utf-8")
    meta, body = front_matter(text)
    body = body.strip()
    if meta.get("name") != PROFILE_NAME:
        problems.append(f"skills/profile.md: front matter name must be {PROFILE_NAME!r}")
    if not body:
        problems.append("skills/profile.md: empty description")
    if nbytes(body) > MAX_PROFILE:
        problems.append(f"skills/profile.md: {nbytes(body)} bytes (max {MAX_PROFILE})")
    problems += scrub_problems("skills/profile.md", text) + lint_problems("skills/profile.md", text)
    return {"name": PROFILE_NAME, "description": body}


def load_routines(problems: list[str]) -> list[dict]:
    out = []
    for path in sorted((SKILLS_DIR / "routines").glob("*.md")) if (SKILLS_DIR / "routines").is_dir() else []:
        label = f"skills/routines/{path.name}"
        text = path.read_text(encoding="utf-8")
        meta, body = front_matter(text)
        body = body.strip()
        for k in ("name", "slug", "description"):
            if not meta.get(k):
                problems.append(f"{label}: front matter needs {k}")
        if meta.get("slug") != path.stem or not SLUG.match(meta.get("slug") or "-"):
            problems.append(f"{label}: slug must equal the file name ({path.stem})")
        if not body:
            problems.append(f"{label}: empty content")
        problems += scrub_problems(label, text) + lint_problems(label, text)
        out.append({"name": meta.get("name", ""), "slug": meta.get("slug", ""),
                    "description": meta.get("description", ""), "content": body})
    return out


def load_memory(problems: list[str]) -> list[dict]:
    path = SKILLS_DIR / "memory.md"
    if not path.is_file():
        problems.append("skills/memory.md missing")
        return []
    text = path.read_text(encoding="utf-8")
    meta, body = front_matter(text)
    body = body.strip()
    kind = meta.get("kind", "log")
    if kind not in ("log", "profile"):
        problems.append("skills/memory.md: kind must be log or profile")
    if not body:
        problems.append("skills/memory.md: empty content")
    problems += scrub_problems("skills/memory.md", text) + lint_problems("skills/memory.md", text)
    return [{"kind": kind, "content": body}]


def validate(recipe: dict) -> list[str]:
    """The template schema's rules (zod, research notes §8.1) plus this template's own budget."""
    p = []
    prof = recipe.get("profile") or {}
    if not prof.get("name") or not prof.get("description"):
        p.append("profile needs name and description")
    for k in ("memory", "skills", "routines", "plugins"):
        if not isinstance(recipe.get(k), list):
            p.append(f"{k} must be a list")
    for m in recipe.get("memory", []):
        if not m.get("content") or m.get("kind") not in (None, "profile", "log"):
            p.append("memory entries need content and kind profile|log")
    for s in recipe.get("skills", []):
        if not (s.get("name") and s.get("description") and s.get("content")):
            p.append(f"skill {s.get('name')!r} needs name, description and content")
    for r in recipe.get("routines", []):
        if not all(r.get(k) for k in ("name", "slug", "description", "content")):
            p.append(f"routine {r.get('slug')!r} needs name, slug, description and content")
    for pl in recipe.get("plugins", []):
        if not (pl.get("name") and pl.get("pluginId")):
            p.append("plugins need name and pluginId")
    names = [s.get("name") for s in recipe.get("skills", [])]
    if len(set(names)) != len(names):
        p.append("duplicate skill names")
    gs = (recipe.get("gettingStarted") or {}).get("skill")
    if gs not in names:
        p.append(f"gettingStarted.skill {gs!r} is not one of the skills")
    total = import_bytes(recipe)
    if total > MAX_TOTAL:
        p.append(f"recipe text is {total} bytes (max {MAX_TOTAL}): the importer re-emits all of it")
    if nbytes(json.dumps(recipe, ensure_ascii=False)) > MAX_RECIPE:
        p.append("recipe over 25 MiB")
    return p


def import_bytes(recipe: dict) -> int:
    """Everything the importer re-emits as model output: each skill's content AND its description (sent again as its
    own argument), the profile, routines, memory and plugin descriptions."""
    return (sum(nbytes(s.get("content", "")) + nbytes(s.get("description", "")) for s in recipe.get("skills", []))
            + nbytes((recipe.get("profile") or {}).get("description", ""))
            + sum(nbytes(r.get("content", "")) + nbytes(r.get("description", "")) for r in recipe.get("routines", []))
            + sum(nbytes(m.get("content", "")) for m in recipe.get("memory", []))
            + sum(nbytes(pl.get("description", "")) for pl in recipe.get("plugins", [])))


def build(plugin_id: str | None = None, release: bool = False) -> tuple[dict, list[str], dict]:
    """(recipe, problems, report). The recipe is complete even when problems exist (so they can all be listed)."""
    problems: list[str] = []
    skills = load_skills(problems)
    profile = load_profile(problems)
    routines = load_routines(problems)
    memory = load_memory(problems)
    pid = (plugin_id or "").strip() or PLUGIN_ID_DEFAULT
    if release and pid == PLUGIN_PLACEHOLDER:
        problems.append("plugins: the Higgsfield pluginId is still the placeholder; pass --plugin-id ID "
                        "(the bot finds it with SearchPlugins, or Bot details -> Integrations)")
    recipe = {"profile": profile, "memory": memory, "skills": skills, "routines": routines,
              "plugins": [{"name": PLUGIN["name"], "description": PLUGIN["description"], "pluginId": pid}],
              "gettingStarted": {"skill": GETTING_STARTED}}
    problems += validate(recipe)
    sizes = {s["name"]: nbytes(s["content"]) for s in skills}
    report = {"skills": sizes, "skills_total": sum(sizes.values()), "profile": nbytes(profile["description"]),
              "routines": {r["slug"]: nbytes(r["content"]) for r in routines},
              "memory": sum(nbytes(m["content"]) for m in memory),
              "plugin_id": ("placeholder" if pid == PLUGIN_PLACEHOLDER
                            else "default" if pid == PLUGIN_ID_DEFAULT else "set")}
    report["total"] = import_bytes(recipe)
    return recipe, problems, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build skills/dist/recipe.json (the Claudia Grok Bot template).")
    ap.add_argument("--check", action="store_true", help="validate only; write nothing")
    ap.add_argument("--plugin-id", help="the Higgsfield plugin id in the Grok Bot marketplace")
    ap.add_argument("--release", action="store_true", help="refuse the placeholder plugin id")
    ap.add_argument("--out", type=Path, default=DIST, help=f"output file (default {DIST.relative_to(ROOT)})")
    ap.add_argument("--json", action="store_true", help="one JSON object on stdout")
    a = ap.parse_args(argv)
    recipe, problems, report = build(a.plugin_id, a.release)
    wrote = None
    if not problems and not a.check:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(recipe, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        wrote = str(a.out)
    lines = [f"{k:18} {v:6} B" for k, v in report["skills"].items()]
    lines += [f"{'skills total':18} {report['skills_total']:6} B (max {MAX_TOTAL} B with the rest)",
              f"{'profile':18} {report['profile']:6} B (max {MAX_PROFILE} B)",
              f"{'all text':18} {report['total']:6} B (max {MAX_TOTAL} B; skill descriptions counted twice)",
              f"plugin id: {report['plugin_id']}" + (f" ({PLUGIN_ID_DEFAULT}; confirm it with SearchPlugins before "
                                                     "publishing)" if report["plugin_id"] == "default" else "")]
    if problems:
        lines += ["PROBLEMS:"] + [f"  - {x}" for x in problems] + ["nothing written; fix these and run it again"]
    elif wrote:
        lines.append(f"wrote {wrote}" + ("  (pluginId is the placeholder: pass --plugin-id before publishing)"
                                         if report["plugin_id"] == "placeholder" else ""))
    else:
        lines.append("ok (checked only; nothing written)")
    text = "\n".join(lines)
    if a.json:
        print(json.dumps({"ok": not problems, "problems": problems, "report": report, "wrote": wrote, "text": text}))
    else:
        print(text)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
