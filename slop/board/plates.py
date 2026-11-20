"""slop plates — the plate pipeline: prompt book + Midjourney paste batches, ingest, picking sheets, picks, vary.

  slop plates book [--batch B] [--only P,..] [--missing] [--plan basic|standard|pro|mega]
      plates/prompts.md (the book the owner reads before anything is generated; a subset book from --only/--missing is
      plates/prompts-<B>.md, so the full book is never overwritten by a re-roll), plates/mj/<B>.json (the batch: jobs
      with their exact prompts, used by ingest to identify downloads; a subset never reuses a batch that holds other
      plates), plates/mj/<B>.perm-<k>.txt (one paste each: up to 4/10/40 prompts in Midjourney permutation braces, every
      inner comma escaped as "\\,", the params after the braces), plates/mj/<B>.lines.txt (one prompt per line, the
      alternative) and plates/jobs.json (merged by plate) + plates/api/<plate>.txt (API image jobs, each with the exact
      `slop -p P gen image --plate P --prompt-file F` command; project board.api_candidates, default 2 images a plate).
      Pre-flight (research 11-gap-6 §7.2): lint (framing first, canon, no-text tail, <= 800 chars, the FAR variant on
      FS/WS/EWS plates), the Fast GPU-minute estimate (jobs x 1.3 min HD, 0.8 SD), the queue rule (never more than 10
      queued jobs on Basic/Standard). plates[] entries no shot or clip uses are skipped.
      Sung plates (the plate of a shot with motion tier sung or a motion shot on a sung clip, or of a planned sung
      window: the lip-sync start frames) get "her mouth fully visible, nothing in front of her mouth" (his/their from
      lead.pronoun) before the style tail; API jobs add "(no microphone, hand or hair)" (a canon headset: "(the headset
      microphone at her cheek, clear of her lips; no hand or hair)"); Midjourney prompts name no object there (MJ
      draws what a prompt names, negated or not). A microphone, a hand at the mouth or something over it in their
      prompt is a lint warning (the Studio run: a mic at her mouth held a clip to 26 %).
      --anchor PLATE[:K] (after the owner approved the lead at G3 and the plate is picked; no K = its pick): every lead
      plate's API job (a plate with a lead_on_screen shot, the anchor's own plate aside) gets "refs": [that image] and
      "anchor": "PLATE:K", its cmd gets `--ref PLATE:K`; jobs.json records {"anchor": {ref, plate, k, file, at,
      plates}, "anchored": [...]}. Sticky: a later book keeps it (a note when the pick has changed since); --no-anchor
      drops it (DECISIONS.md logs both). Refused when the project's image model takes no reference images. Midjourney
      plates never get one (identity stays text there).
  slop plates ingest DIR|ZIP|FILE [--batch B] [--map KEY=PLATE ...] [--force]
      downloads -> plates/cands/<plate>/<k>.jpg (+ plates/cands/index.json with source names and sha256, deduped).
      Recognised names: "<plate>-<k>.png" / "<plate>_<k>.jpg" (Grok GenerateImage / API outputs, older batch tools,
      Drive copies; plate names match in any case), "<plate>/<k>.png" (DIR may also be the plate's own folder; k is
      kept when free), with no board and no batch yet a plate-like "<name>-<k>.png" or "<name>/<k>.png" makes plate
      <name> (never DIR itself, a date, or a name a tool gives on its own: image-1, Screenshot-…); a folder named after
      a plate, Midjourney website downloads "<user>_<prompt words>_<job uuid>_<n>.png" (grouped by uuid; each job
      should have 4 images, else a warning), CDN "<uuid>/0_<n>.png", and names without a uuid such as
      "<user>_<prompt words>_<hash>.png" (grouped by the name without its trailing index). Refused: plates/cands/
      itself or a folder holding it (the project), and a candidate file without --plate/--map. A group is matched to a
      batch prompt by the prompt embedded in the file (PNG text, XMP dc:description, EXIF ImageDescription/UserComment)
      when present, else by the normalised prompt text found anywhere in the name if exactly one prompt fits — never by
      position. Unmatched groups (e.g. lead plates whose names only show the shared framing + canon) go on
      plates/unmatched.jpg; map them with --map <uuid-prefix | file name | file stem>=<plate> (the plate must be on the
      board or in a batch) and re-run (already ingested files are skipped by hash). Originals are kept byte for byte in
      plates/mj/<batch>/orig/ (plates/orig/ without --batch); the candidates are JPEG q95 copies.
  slop plates sheet [--plates P,..]        numbered picking sheets (<= 10 plates a sheet) -> plates/sheets/pick-NN.jpg
  slop plates pick PLATE K [PLATE K ...]   (also "p001#2, p004#4") -> plates/picks.json {plate: {file, cand_k, shot_ids}};
      refuses a candidate that a variant of the same plate already shows (it would put one image on two moments).
  slop plates vary [--dry]                 one image per shot: a plate on several shots that are not one continuous
      moment gives the later shots its other candidates as variant plates "<plate>~<k>"; two clips never start from the
      same frame (port of vary.py; the owner: "two seedance videos shouldnt start from the exact same frame"). It
      rewrites board/shots.json: on an approved board it warns that the board gate is stale (the owner sees the sheet).
  slop plates status                       per plate: candidates, pick, shots, prompt state.

Changes from the source: no credentialed browser and no MJ automation (human in the loop, research 11-gap-6 §7); the
profile code is only ever the user's own (project.json mj.profile) and never taken from params; identity is text
(project.json lead.canon / lead.far, placeholders {lead} {far} {possessive}); vary's state/shots ordering bug is fixed
(both files written together) and continuous followers move with their shot.
"""
from __future__ import annotations

import hashlib
import io
import re
import shlex
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

from ..config import SlopError, load_project
from .common import (FRAMINGS, TODO, WIDE_FRAMINGS, board_gate_stale, clip_kinds, framing_of, font, load_shots,
                     mouth_blockers, mouth_clause, pcmd, read_json, rel, save_shots, shot_clips, shot_plate,
                     sung_shot_ids, write_json, write_text)

PLAN_LIMIT = {"basic": 4, "standard": 10, "pro": 40, "mega": 40}
GPU_MIN = {"hd": 1.3, "sd": 0.8}         # Fast GPU-minutes per image job (MJ GPU page, research 11-gap-6 §4)
FAR_FRAMINGS = ("FS", "WS", "EWS")       # full-length framings take the short FAR canon variant
NO_TEXT = "no text, no letters, no logos"
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
UUID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)
# ingest before a board: names a download, a phone or an image tool gives on its own are never taken as new plates
GENERIC_NAME = re.compile(r"^(?:images?|img|photos?|pic|pictures?|screenshots?|screen-shot|downloads?|generated|grok|"
                          r"untitled|files?|outputs?|results?|dall-?e|chatgpt|gemini|midjourney|uploads?|gen)(?:[-.]|$)",
                          re.I)
FRAMING_WORDS = ("extreme close", "close-up", "close up", "closeup", "medium", "full-length", "full length", "full-body",
                 "full body", "wide", "aerial", "macro", "over-the-shoulder", "over the shoulder", "straight-down",
                 "low-angle", "high-angle", "two-shot", "profile", "insert", "establishing", "long shot", "cowboy",
                 "overhead", "top-down", "bird's-eye", "portrait", "photograph")
ORDER = ["ECU", "CU", "MCU", "MS", "MWS", "FS", "WS", "EWS", "OTS"]
ACC = "#D97757"


def _real(p: str | None) -> bool:
    return bool(p and p.strip() and TODO not in p)


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower().replace("'", "")))


def valid_profile(code) -> str:
    """The user's own Midjourney profile code from project.json, or '' (placeholders and junk are ignored)."""
    c = str(code or "").strip()
    return c if re.fullmatch(r"[A-Za-z0-9]{3,40}", c) else ""


# ------------------------------------------------------------------------------------------------ book
def plate_entries(S: dict, proj: dict) -> list[dict]:
    """Every plate key of the board with its prompt (plates[] entry, else the first shot that uses it)."""
    quick = str(proj.get("tier") or "") == "quick"
    by: dict[str, dict] = {}

    def entry(key: str) -> dict:
        return by.setdefault(key, {"plate": key, "prompt": "", "kind": None, "shots": [], "lead": False,
                                   "framings": [], "params": None, "aspect": None, "irefs": [], "iw": None})
    for p in S.get("plates", []):
        key = p.get("plate")
        if not key or "~" in key:
            continue
        e = entry(key)
        pr = p.get("mj_prompt") or p.get("img_prompt") or p.get("prompt")
        if pr:
            e["prompt"] = pr
            e["kind"] = "api" if (p.get("img_prompt") and not p.get("mj_prompt")) or p.get("tool") == "api" else "mj"
        e["lead"] = e["lead"] or bool(p.get("lead") or p.get("id_pass"))
        e["params"] = p.get("params") or e["params"]
        e["aspect"] = p.get("aspect") or e["aspect"]
        e["irefs"] = list(p.get("image_refs") or p.get("irefs") or [])
        e["iw"] = p.get("iw")
        for sid in p.get("used_by") or []:
            if sid not in e["shots"]:
                e["shots"].append(sid)
    for sh in sorted(S["shots"], key=lambda s: float(s.get("t0", 0))):
        key = shot_plate(sh, S)
        if not key or "~" in key:
            continue
        e = entry(key)
        if sh["id"] not in e["shots"]:
            e["shots"].append(sh["id"])
        pr = sh.get("mj_prompt") or sh.get("img_prompt")
        if pr and (not _real(e["prompt"])) and (_real(pr) or not e["prompt"]):
            e["prompt"] = pr
            e["kind"] = "api" if (sh.get("img_prompt") and not sh.get("mj_prompt")) else "mj"
        e["lead"] = e["lead"] or bool(sh.get("lead_on_screen"))
        if framing_of(sh):
            e["framings"].append(framing_of(sh))
    used = {shot_plate(sh, S) for sh in S["shots"]} | {c.get("plate") for c in S.get("seedance", []) if c.get("plate")}
    used = {k.split("~")[0] for k in used if k}
    for e in by.values():
        if e["kind"] is None:
            e["kind"] = "api" if quick else "mj"
    return [e for e in by.values() if e["plate"] in used or not used]


def sung_plates(pdir: Path | None, S: dict) -> set[str]:
    """Plate keys (variants folded to their base) that start a sung clip: the plate of every sung shot (motion tier
    sung, or a primary clip of kind sung) and the plate of every planned sung window that still has shots."""
    ids = sung_shot_ids(S, clip_kinds(pdir, S))
    out = {shot_plate(sh, S).split("~")[0] for sh in S["shots"] if sh.get("id") in ids and shot_plate(sh, S)}
    for c in S.get("seedance", []):
        if c.get("plate") and c.get("shots") and (c.get("kind") == "sung" or (c.get("kind") is None and c.get("sing"))):
            out.add(str(c["plate"]).split("~")[0])
    return out


def style_tail(proj: dict) -> tuple[str, list[str]]:
    """project.json look.style_tail (written by `slop taste apply`): a string or a list of phrases -> (the tail text,
    warnings). Midjourney parameters and braces are removed (they belong in mj.params / would be read as a
    permutation)."""
    raw = (proj.get("look") or {}).get("style_tail")
    if not raw:
        return "", []
    parts = [str(x) for x in raw] if isinstance(raw, (list, tuple)) else [str(raw)]
    tail = ", ".join(p.strip().strip(",").strip() for p in parts if str(p).strip())
    warns = []
    if re.search(r"(^|\s)--\w", tail):
        warns.append("project.json look.style_tail contains '--' parameters: they were left out of the prompt (put them "
                     "in project.json mj.params)")
        tail = re.sub(r"\s*--\w+(\s+(?!--)[^\s,]+)?", "", tail)
    if "{" in tail or "}" in tail:
        warns.append("project.json look.style_tail contains braces: removed (Midjourney reads them as permutations)")
        tail = tail.replace("{", "").replace("}", "")
    tail = re.sub(r",?\s*no text, no letters, no logos\.?", "", tail, flags=re.I)
    tail = re.sub(r"\s+", " ", re.sub(r",\s*,", ",", tail)).strip().strip(",").strip()
    return tail, warns


def expand(prompt: str, e: dict, proj: dict) -> tuple[str, list[str]]:
    """Canon placeholders -> text; the canon inserted after the framing when a lead plate lacks it; the no-text tail."""
    warn: list[str] = []
    lead = proj.get("lead") or {}
    canon = str(lead.get("canon") or "").strip().rstrip(",")
    far = str(lead.get("far") or "").strip().rstrip(",") or canon
    poss = str(lead.get("possessive") or "").strip()
    pr = prompt.strip()
    tight = min((f for f in e.get("framings") or [] if f in ORDER), key=ORDER.index, default="")
    if e.get("lead") and tight in FAR_FRAMINGS and far != canon and (
            "{lead}" in pr or "{her}" in pr or (canon and canon[:40] in pr)):
        warn.append(f"{e['plate']}: a {tight} (full-length) plate uses the full lead canon — write {{far}} (the short "
                    "full-length variant, project.json lead.far) instead: the long canon crowds out the scene")
    for ph, val in (("{lead}", canon), ("{her}", canon), ("{far}", far), ("{possessive}", poss), ("{lead's}", poss)):
        if ph in pr:
            if not val:
                warn.append(f"{e['plate']}: {ph} used but project.json lead has no text for it")
            pr = pr.replace(ph, val)
    if e["lead"] and canon and canon[:40] not in pr and far[:40] not in pr:
        use = far if tight in WIDE_FRAMINGS else canon
        body = re.sub(r",?\s*no text, no letters, no logos\.?$", "", pr, flags=re.I)
        m = re.match(r"^(.{0,90}?\bof)\s+", body, re.I)
        if m and any(w in m.group(1).lower() for w in FRAMING_WORDS):
            pr = f"{m.group(1)} {use}, {body[m.end():]}"
        else:
            pr = f"{body.rstrip(', ')}, {use}"
        warn.append(f"{e['plate']}: the lead canon was inserted automatically; better write {{lead}} where she appears")
    pr = re.sub(r",\s*,", ",", pr).strip().rstrip(",").strip()
    if e.get("sung"):                          # a lip-sync start frame: the mouth stays clear (docs/50 §4, slot 4)
        body = re.sub(r",?\s*no text, no letters, no logos\.?$", "", pr, flags=re.I).strip().rstrip(",").strip()
        clause = mouth_clause(proj, body, mj=e.get("kind") == "mj")    # MJ: the objects go in --no (mj_params)
        blocked = mouth_blockers(body)
        if blocked:
            warn.append(f"{e['plate']}: a sung plate (the lip-sync start frame) whose prompt puts "
                        f"{', '.join(repr(b) for b in blocked)} at the mouth — take it out of the prompt: anything in "
                        "front of the mouth breaks the lip sync")
        if "mouth fully visible" not in body.lower():
            pr = f"{body}, {clause}"           # before the style tail; the no-text tail is added back below
    tail, tw = style_tail(proj)
    warn += [f"{e['plate']}: {w}" for w in tw]
    if tail:                                   # the taste profile's style tail, before the no-text tail (docs/50)
        body = re.sub(r",?\s*no text, no letters, no logos\.?$", "", pr, flags=re.I).strip().rstrip(",").strip()
        if _norm(tail) not in _norm(body):
            pr = f"{body}, {tail}"             # the no-text tail is added back below
    if "no text" not in pr.lower():
        pr += ", " + NO_TEXT
    if re.search(r"(^|\s)--\w", pr):
        warn.append(f"{e['plate']}: the prompt contains '--' parameters; put them in the plate's params instead")
        pr = re.sub(r"\s--\w+(\s+(?!--)\S+)?", "", pr)
    if "{" in pr or "}" in pr:
        raise SlopError(f"plate {e['plate']}: the prompt still contains a brace after expanding placeholders — "
                        "Midjourney would read it as a permutation. Remove the braces from the prompt.")
    if not any(w in pr[:90].lower() for w in FRAMING_WORDS):
        warn.append(f"{e['plate']}: start the prompt with its framing (close-up of / medium shot of / extreme wide shot of …)")
    if len(pr) > 800:
        warn.append(f"{e['plate']}: prompt is {len(pr)} characters (> 800 may be rewritten by Midjourney's Long Prompt)")
    return pr, warn


MJ_VERSION = re.compile(r"\s*--(?:v|version|niji)\s+\d[\w.]*", re.I)
MJ_PROFILE = re.compile(r"\s*--(?:p|profile|personalize)\b(?:\s+(?!--)\S+)*", re.I)


def mj_line(text: str, mj: dict | None = None) -> tuple[str, list[str]]:
    """A Midjourney prompt (or just its parameters) as the person set Midjourney up -> (line, what changed). Never a
    version: Midjourney's default is its newest model (mj.version only when they asked for one). Never a profile
    code: personalization goes on with the P button (mj.personalize). --raw and --hd as they chose (mj.raw, mj.hd;
    a project without those keys keeps what the line says)."""
    mj = mj if isinstance(mj, dict) else {}
    line, did = " " + str(text or "").strip(), []
    found = [m.strip() for m in MJ_VERSION.findall(line)]
    line = MJ_VERSION.sub("", line)
    want = str(mj.get("version") or "").strip()
    if want:
        line += f" --v {want}"
        if found != [f"--v {want}"]:
            did.append(f"--v {want} (the version the person asked for)")
    elif found:
        did.append("dropped " + ", ".join(dict.fromkeys(found)) + " (Midjourney's default is its newest model)")
    if MJ_PROFILE.search(line):
        line = MJ_PROFILE.sub("", line)
        did.append("dropped the profile parameter (personalization is the P button)")
    for flag in ("raw", "hd"):
        if flag not in mj:
            continue
        has = re.search(rf"\s--{flag}\b", line) is not None
        if mj.get(flag) and not has:
            line += f" --{flag}"
            did.append(f"added --{flag} (mj.{flag} on)")
        elif not mj.get(flag) and has:
            line = re.sub(rf"\s*--{flag}\b", "", line)
            did.append(f"dropped --{flag} (mj.{flag} off)")
    return re.sub(r"\s+", " ", line).strip(), did


def mj_params(e: dict, proj: dict) -> str:
    mj = proj.get("mj") or {}
    base = mj_line(e.get("params") or mj.get("params") or "--ar 16:9", mj)[0]
    if e.get("aspect") and e["aspect"] != "16:9" and not e.get("params"):
        base = re.sub(r"--ar\s+\S+", f"--ar {e['aspect']}", base) if "--ar" in base else f"--ar {e['aspect']} {base}"
    if e.get("irefs") and e.get("iw") is not None and "--iw" not in base:
        base += f" --iw {e['iw']}"
    return re.sub(r"\s+", " ", base).strip()


def perm_escape(prompt: str) -> str:
    return prompt.replace("\\", "").replace(",", "\\,")


ANCHOR_RE = re.compile(r"^(?P<plate>[A-Za-z0-9][\w.~-]{0,79}?)(?:[:#](?P<k>\d{1,4}))?$")


def _lead_anchor(pdir: Path, anchor: str | None, no_anchor: bool, old: dict) -> tuple[dict | None, list[str]]:
    """The identity anchor for the lead plates' API jobs -> ({ref, plate, k, file, at} | None, notes).
    --anchor PLATE[:K]: candidate K (default: the plate's pick) of a plate the owner picked at G3; no flag: the anchor
    plates/jobs.json already has (sticky, so a re-book keeps it); --no-anchor drops it."""
    notes: list[str] = []
    oa = old.get("anchor") if isinstance(old.get("anchor"), dict) else None
    if anchor and no_anchor:
        raise SlopError("--anchor and --no-anchor: give one of them; nothing was written")
    if no_anchor:
        if oa:
            notes.append(f"lead anchor {oa.get('ref')} dropped (--no-anchor): lead plates are text-canon only again")
        return None, notes
    if not anchor:
        if oa and oa.get("file") and (pdir / oa["file"]).is_file():
            notes.append(f"lead anchor {oa.get('ref')} kept from plates/jobs.json (--no-anchor drops it)")
            now = _pick_k(pdir, str(oa.get("plate") or ""))
            if now is not None and oa.get("k") is not None and now != oa.get("k"):
                notes.append(f"the pick of {oa.get('plate')} is now #{now}, the anchor is still #{oa.get('k')}: if #{now} "
                             f"is the face the owner approved, re-anchor with `"
                             + pcmd(pdir, f"plates book --anchor {oa.get('plate')}") + "`")
            return {k: v for k, v in oa.items() if k != "plates"}, notes
        if oa:
            notes.append(f"lead anchor {oa.get('ref')} dropped: {oa.get('file')} is gone; re-anchor with `"
                         + pcmd(pdir, "plates book --anchor PLATE:K") + "`")
        return None, notes
    m = ANCHOR_RE.match(anchor.strip())
    if not m:
        raise SlopError(f"--anchor {anchor}: write PLATE or PLATE:K (the lead image the owner approved, e.g. "
                        "--anchor lead-cu:2); nothing was written")
    plate, k = m.group("plate"), int(m.group("k")) if m.group("k") else None
    base = plate.split("~")[0]
    if k is None and "~" in plate and plate.split("~", 1)[1].isdigit():
        k = int(plate.split("~", 1)[1])                # a variant key names its candidate (as `gen image --ref` reads it)
    c = _cands(pdir, base)
    if not c:
        raise SlopError(f"--anchor {anchor}: {base} has no candidates (`{pcmd(pdir, 'plates status')}` lists the plates); "
                        "nothing was written")
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    pk = (picks.get(plate) or picks.get(base) or {}) if isinstance(picks, dict) else {}
    pk = pk if isinstance(pk, dict) else {}
    if pk.get("cand_k") is None:
        raise SlopError(f"--anchor {anchor}: {plate} has no pick yet. The anchor is the lead image the owner approved "
                        f"(G3): send `{pcmd(pdir, 'plates sheet --plates ' + base)}`, record their choice with `"
                        f"{pcmd(pdir, 'plates pick ' + base + ' K')}`, then re-run `"
                        f"{pcmd(pdir, 'plates book --anchor ' + base)}`; nothing was written")
    if k is None:
        k = int(pk["cand_k"])
    elif k != int(pk["cand_k"]):
        notes.append(f"anchoring on {base}#{k}, not its pick #{pk['cand_k']}: make sure #{k} is the face the owner "
                     "approved")
    if k not in c:
        raise SlopError(f"--anchor {anchor}: {base} has no candidate #{k} (has {', '.join('#' + str(x) for x in c)}); "
                        "nothing was written")
    return {"ref": f"{base}:{k}", "plate": base, "k": k, "file": rel(pdir, c[k]), "at": time.strftime("%Y-%m-%d")}, notes


def _pick_k(pdir: Path, plate: str) -> int | None:
    """the candidate number the owner picked for plate (plates/picks.json), or None."""
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    pk = picks.get(plate) if isinstance(picks, dict) else None
    try:
        return int(pk["cand_k"]) if isinstance(pk, dict) and pk.get("cand_k") is not None else None
    except (TypeError, ValueError):
        return None


def _anchor_job(pdir: Path, j: dict, new: dict | None, old_refs: set[str]) -> None:
    """Point one API job at the anchor (or at none): what an earlier anchor wrote goes, the new one is added."""
    gone = set(old_refs) | ({j["anchor"]} if j.get("anchor") else set())
    refs = [r for r in j.get("refs") or [] if r not in gone]
    cmd = j.get("cmd")
    if cmd:
        for r in gone:
            cmd = cmd.replace(f" --ref {shlex.quote(r)}", "")
    j.pop("anchor", None)
    if new:
        refs.append(new["file"])
        j["anchor"] = new["ref"]
        if cmd:
            cmd += f" --ref {shlex.quote(new['ref'])}"
    if refs:
        j["refs"] = refs
    else:
        j.pop("refs", None)
    if cmd:
        j["cmd"] = cmd


def _check_anchor_model(proj: dict, anc: dict | None, given: bool) -> None:
    """refuse an anchor the project's image model cannot take (the registry says it has no input_references)."""
    if not anc:
        return
    try:
        from ..gen import images as gi
    except ImportError:                                # the gen module is not installed: the batch will check
        return
    model = (proj.get("models") or {}).get("image") or gi.DEFAULT_MODEL
    if gi.refs_max(model, cached_only=True) == 0:     # the book stays local; the batch re-checks before any spend
        raise SlopError(f"lead anchor {anc['ref']}: the project's image model {model} takes no reference images (its "
                        "OpenRouter listing has no input_references). Set one that does (`slop project set "
                        "models.image openai/gpt-image-2`; `slop gen models --kind image` shows refs<=N) and re-run, "
                        + ("or book without --anchor" if given else "or drop the anchor with --no-anchor")
                        + "; nothing was written")


def book(pdir: Path, batch: str = "b01", only: list[str] | None = None, missing: bool = False,
         plan: str | None = None, anchor: str | None = None, no_anchor: bool = False) -> dict:
    proj = load_project(pdir)
    S = load_shots(pdir)
    if not re.fullmatch(r"[A-Za-z0-9][\w-]{0,40}", batch):
        raise SlopError(f"batch name '{batch}': use letters, digits, '-' or '_' (e.g. b01)")
    plan = (plan or (proj.get("mj") or {}).get("plan") or "standard").lower()
    if plan not in PLAN_LIMIT:
        raise SlopError(f"--plan {plan}: one of {', '.join(PLAN_LIMIT)} (your Midjourney plan; it caps prompts per paste)")
    limit = PLAN_LIMIT[plan]
    entries = plate_entries(S, proj)
    sung = sung_plates(pdir, S)
    for e in entries:
        e["sung"] = e["plate"] in sung
    jp = pdir / "plates/jobs.json"
    old_doc = (read_json(jp, default={}) or {}) if jp.is_file() else {}
    old_doc = old_doc if isinstance(old_doc, dict) else {"jobs": old_doc if isinstance(old_doc, list) else []}
    anc, anc_notes = _lead_anchor(pdir, anchor, no_anchor, old_doc)
    _check_anchor_model(proj, anc, given=bool(anchor))
    oa = old_doc.get("anchor") if isinstance(old_doc.get("anchor"), dict) else {}
    old_refs = {x for x in (oa.get("ref"), oa.get("file")) if x}
    lead_api = {e["plate"] for e in entries if e["lead"] and e["kind"] == "api"}
    lead_mj = sorted(e["plate"] for e in entries if e["lead"] and e["kind"] != "api")
    if anc and anc["plate"] in {e["plate"] for e in entries} and not any(
            e["lead"] for e in entries if e["plate"] == anc["plate"]):
        anc_notes.append(f"the anchor {anc['ref']} is a plate whose shots do not show the lead (lead_on_screen): is it "
                         "really her/his approved image?")
    if only:
        unknown = [o for o in only if o not in {e["plate"] for e in entries}]
        if unknown:
            raise SlopError(f"--only: unknown plate(s) {', '.join(unknown)} (plate keys are in board/shots.json)")
        entries = [e for e in entries if e["plate"] in only]
    if missing:
        entries = [e for e in entries if not _cands(pdir, e["plate"])]
    subset = bool(only or missing)
    if subset:
        old = read_json(pdir / "plates/mj" / f"{batch}.json", default=None) or {}
        others = sorted({j.get("plate") for j in old.get("jobs", [])} - {e["plate"] for e in entries} - {None})
        if others:
            raise SlopError(f"batch {batch} already holds other plates ({', '.join(others[:6])}"
                            f"{' …' if len(others) > 6 else ''}): a re-roll needs a new batch name, e.g. "
                            f"`slop plates book --only {','.join(e['plate'] for e in entries[:3]) or 'P'} --batch "
                            f"{_next_batch(pdir, batch)}` (ingest identifies downloads by their batch)")
    todo = [e["plate"] for e in entries if not _real(e["prompt"])]
    ready = [e for e in entries if _real(e["prompt"])]
    if not ready:
        raise SlopError("no plate has a written prompt yet: write mj_prompt (or img_prompt) on the shot that owns each plate "
                        f"in board/shots.json ({len(todo)} still TODO), then re-run `slop plates book`")
    warns: list[str] = []
    mj_jobs, api_jobs = [], []
    if not valid_profile((proj.get("mj") or {}).get("profile")) and (proj.get("mj") or {}).get("profile"):
        warns.append("project.json mj.profile is not a profile code (placeholder?) — it is left out; put your own code "
                     "there or leave it empty")
    for e in ready:
        pr, w = expand(e["prompt"], e, proj)
        warns += w
        if e["kind"] == "api":
            n = int((proj.get("board") or {}).get("api_candidates", 2))
            pf = write_text(pdir / "plates/api" / f"{e['plate']}.txt", pr + chr(10))
            ar = e.get("aspect") or "16:9"
            api_jobs.append({"plate": e["plate"], "prompt": pr, "aspect": ar, "n": n, "prompt_file": rel(pdir, pf),
                             "model": (proj.get("models") or {}).get("image"), "shots": e["shots"], "batch": batch,
                             "cmd": pcmd(pdir, f"gen image --plate {e['plate']} --prompt-file {rel(pdir, pf)} "
                                               f"--aspect-ratio {ar} --n {n}"), **({"sung": True} if e["sung"] else {})})
        else:
            mj_jobs.append({"job": e["plate"], "plate": e["plate"], "kind": "plate", "prompt": pr,
                            "params": mj_params(e, proj), "srefs": [], "irefs": e["irefs"], "expect_images": 4,
                            "shots": e["shots"], "lead": e["lead"], **({"sung": True} if e["sung"] else {})})
    files = []
    blocks = []
    mjdir = pdir / "plates/mj"
    if mj_jobs:
        for old in mjdir.glob(f"{batch}.perm-*.txt"):
            old.unlink()
        packable = [j for j in mj_jobs if not j["irefs"]]
        groups: dict[str, list] = {}
        for j in packable:
            groups.setdefault(j["params"], []).append(j)
        k = 0
        for params, js in groups.items():
            for i in range(0, len(js), limit):
                chunk = js[i:i + limit]
                k += 1
                text = "{" + ", ".join(perm_escape(j["prompt"]) for j in chunk) + "} " + params
                f = write_text(mjdir / f"{batch}.perm-{k:02d}.txt", text + "\n")
                files.append(f)
                blocks.append({"file": rel(pdir, f), "expect": len(chunk), "plates": [j["plate"] for j in chunk],
                               "text": text})
        lines = "\n".join(f"{j['prompt']} {j['params']}" for j in mj_jobs) + "\n"
        files.append(write_text(mjdir / f"{batch}.lines.txt", lines))
        bj = {"batch": batch, "created": time.strftime("%Y-%m-%d"), "note": f"{proj.get('title') or pdir.name} plates",
              "plan": plan, "jobs": mj_jobs}
        files.append(write_json(mjdir / f"{batch}.json", bj))
    anchored: list[str] = []
    decision = None
    if api_jobs or (jp.is_file() and (anchor or no_anchor)):
        old_jobs = old_doc.get("jobs") or []
        mine = {j["plate"] for j in api_jobs}
        merged = [j for j in old_jobs if isinstance(j, dict) and j.get("plate") not in mine] + api_jobs
        for j in merged:                               # the anchor goes on every lead plate's job, the anchor's own aside
            if anc and j.get("plate") in lead_api and j.get("plate") != anc["plate"]:
                _anchor_job(pdir, j, anc, old_refs)
                anchored.append(j["plate"])
            elif j.get("anchor") or old_refs & set(j.get("refs") or []):
                _anchor_job(pdir, j, None, old_refs)
        anchored = sorted(set(anchored))
        doc = {"batch": batch}
        if anc:
            doc["anchor"] = {**{k: v for k, v in anc.items() if k != "plates"}, "plates": anchored}
        doc["anchored"] = anchored
        doc["jobs"] = merged
        files.append(write_json(jp, doc))
        if oa.get("ref") and not anc:
            decision = (f"lead identity anchor {oa['ref']} dropped ("
                        + ("--no-anchor" if no_anchor else f"{oa.get('file')} is gone")
                        + "): lead plates are text-canon only")
    if anc:
        if not anchored:
            anc_notes.append(f"lead anchor {anc['ref']}: no API job of a lead plate to anchor in this book")
        if lead_mj:
            anc_notes.append(f"{len(lead_mj)} lead plate(s) are Midjourney plates ({', '.join(lead_mj[:6])}): the anchor "
                             "is for API stills only (Midjourney identity stays text, docs/50 §5)")
        if anchor and anchored and oa.get("ref") != anc["ref"]:
            decision = (f"lead identity anchor {anc['ref']} ({anc['file']}): sent as a reference image "
                        f"(input_references) with {len(anchored)} lead plate job(s)")
    if decision:
        try:
            from ..core_cli import append_decision
            append_decision(pdir, decision)
        except (ImportError, SlopError):
            pass
    gpu = round(sum(GPU_MIN["hd" if re.search(r"(^|\s)--hd\b", j["params"]) else "sd"] * j["expect_images"] / 4
                    for j in mj_jobs), 1)
    md = _book_md(proj, pdir, batch, plan, limit, mj_jobs, api_jobs, blocks, todo, warns, gpu, anc=anc,
                  anchored=anchored)
    book_name = f"prompts-{batch}.md" if subset else "prompts.md"
    files.append(write_text(pdir / "plates" / book_name, md))
    text = (f"plates/{book_name}: {len(mj_jobs)} Midjourney job(s) in {len(blocks)} paste block(s) (plan {plan}, "
            f"<={limit} per paste; ≈{gpu:g} Fast GPU-minutes) and {len(api_jobs)} API job(s); {len(todo)} plate(s) "
            "still TODO." + (" (a subset book: plates/prompts.md, the full book, is unchanged)" if subset else "") + "\n"
            f"next: the owner reads plates/{book_name}; Midjourney: paste each block of plates/mj/"
            f"{batch}.perm-NN.txt (MJ must ask 'Run N prompts?' with the number in the book), download, then "
            f"`{pcmd(pdir, 'plates ingest <zip or folder> --batch ' + batch)}`."
            + (" API plates: after the owner's yes, run each job's `cmd` from plates/jobs.json (they write "
               "plates/cands/<plate>/<k>; spend is confirmed by `slop gen`)." if api_jobs else ""))
    tail = style_tail(proj)[0]
    if tail:
        text += f"\nstyle tail (project.json look.style_tail) appended to every prompt: \"{tail[:120]}\""
    sung_booked = sorted(j["plate"] for j in mj_jobs + api_jobs if j.get("sung"))
    if sung_booked:
        text += (f"\nsung plates ({len(sung_booked)}: {', '.join(sung_booked[:10])}{' …' if len(sung_booked) > 10 else ''}"
                 f") carry \"{mouth_clause(proj, mj=True)}\" — they are the lip-sync start frames (API jobs also say "
                 "what must not be there, or where a canon headset stays; Midjourney prompts name no object there, as "
                 "MJ draws what a prompt names: check every sung candidate's mouth before picking)")
    if anc and anchored:
        text += (f"\nlead anchor {anc['ref']} ({anc['file']}): {len(anchored)} lead plate job(s) send it as a reference "
                 f"image with the text canon ({', '.join(anchored[:8])}{' …' if len(anchored) > 8 else ''}). Plates that "
                 "already have candidates made without it get new ones; add --missing to the batch to skip them. "
                 f"Dry run: `{pcmd(pdir, 'gen image --jobs')}`.")
    if anc_notes:
        text += "\n" + "\n".join("note: " + n for n in anc_notes)
    if warns:
        text += "\nwarnings:\n" + "\n".join("  - " + w for w in warns[:12]) + (f"\n  … {len(warns) - 12} more" if len(warns) > 12 else "")
    return {"batch": batch, "book": f"plates/{book_name}", "subset": subset, "mj_jobs": len(mj_jobs), "style_tail": tail,
            "anchor": anc, "anchored": anchored, "anchor_notes": anc_notes,
            "api_jobs": len(api_jobs), "gpu_minutes": gpu, "blocks": [
                {k: v for k, v in b.items() if k != "text"} for b in blocks], "todo": todo, "warnings": warns,
            "files": [rel(pdir, f) for f in files], "text": text}


def _next_batch(pdir: Path, batch: str) -> str:
    m = re.match(r"^(.*?)(\d+)$", batch)
    stem, n, width = (m.group(1), int(m.group(2)), len(m.group(2))) if m else (batch + "-", 1, 2)
    while True:
        n += 1
        cand = f"{stem}{n:0{width}d}"
        if not (pdir / "plates/mj" / f"{cand}.json").is_file():
            return cand


def _book_md(proj, pdir, batch, plan, limit, mj_jobs, api_jobs, blocks, todo, warns, gpu: float = 0.0,
             anc: dict | None = None, anchored: list[str] | None = None) -> str:
    title = proj.get("title") or proj.get("name") or pdir.name
    out = [f"# Plate prompt book — {title}", "",
           f"Batch **{batch}** · {len(mj_jobs)} Midjourney job(s) (4 images each) · {len(api_jobs)} API job(s) · "
           f"Midjourney plan **{plan}** (<= {limit} prompts per paste).", ""]
    if anc and anchored:
        out += [f"**Lead anchor:** `{anc['file']}` ({anc['ref']}, the lead image the owner approved) goes with every lead "
                f"plate's API job as a reference image, next to the text canon: {', '.join(anchored)}.", ""]
    if mj_jobs:
        out += [f"Cost: about **{gpu:g} Fast GPU-minutes** ({len(mj_jobs)} jobs × 1.3 min for HD, 0.8 for SD). Check "
                "that your plan's remaining Fast time covers it before you paste.", ""]
    if todo:
        out += [f"Not in this book yet (prompt still TODO in board/shots.json): {', '.join(todo)}", ""]
    if mj_jobs:
        out += ["## Before you paste (midjourney.com)", "",
                "1. Settings: leave Version on Midjourney's default (its newest); Raw and HD are in the params; "
                f"**Personalization {'on (the P button)' if (proj.get('mj') or {}).get('personalize', True) else 'off'}**; "
                "**Fast** mode (permutations need Fast or Turbo).",
                f"2. Create a folder named exactly `{batch}` and open it, so the Imagine bar says \"Generating in {batch}\".",
                "3. Paste ONE block at a time. Midjourney asks \"Run N prompts?\": N must equal the number written above "
                "the block. If it differs, click **No** and tell the bot (a comma was not escaped)."
                + (" **Never more than 10 queued jobs** on the Basic/Standard plans: wait for the queue to drain before "
                   "the next block." if plan in ("basic", "standard") else ""),
                f"4. When every job has finished: Organize -> folder {batch} -> select all (expect 4 × jobs images) -> "
                "Download. Upload the zip(s); the bot runs `slop plates ingest`.", "",
                "## Paste blocks", ""]
        for i, b in enumerate(blocks, 1):
            out += [f"### Block {i} — Midjourney must ask: Run **{b['expect']}** prompts?  ({', '.join(b['plates'])})",
                    "", "```", b["text"], "```", ""]
        irefs = [j for j in mj_jobs if j["irefs"]]
        if irefs:
            out += ["### One at a time (these have image references: drag them into the **Images** slot)", ""]
            for j in irefs:
                out += [f"- {j['plate']}: refs {', '.join(j['irefs'])}", "", "```", f"{j['prompt']} {j['params']}", "```", ""]
        out += [f"Alternative without permutations: one prompt per paste from `plates/mj/{batch}.lines.txt`.", ""]
    out += ["## Plates", ""]
    for j in mj_jobs + api_jobs:
        kind = "API" if j in api_jobs else "MJ"
        out += [f"### {j['plate']} · {kind} · shots {', '.join(j['shots'])}" + (" · lead" if j.get("lead") else "")
                + (" · sung (mouth fully visible)" if j.get("sung") else "")
                + (f" · anchored on {j['anchor']}" if j.get("anchor") else ""), "", j["prompt"], ""]
        if kind == "MJ":
            out += [f"params: `{j['params']}`", ""]
        else:
            out += [f"run: `{j['cmd']}`", ""]
    if warns:
        out += ["## Lint", ""] + [f"- {w}" for w in warns] + [""]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ candidates
def _cands(pdir: Path, plate: str) -> dict[int, Path]:
    d = pdir / "plates/cands" / plate.split("~")[0]
    out = {}
    if d.is_dir():
        for f in d.iterdir():
            if f.suffix.lower() in IMG_EXT and f.stem.isdigit():
                out[int(f.stem)] = f
    return dict(sorted(out.items()))


def _known_plates(pdir: Path) -> tuple[set[str], dict[str, str]]:
    """Plate keys and their normalised prompts (from batch files and the board)."""
    keys: set[str] = set()
    prompts: dict[str, str] = {}
    try:
        S = load_shots(pdir)
        proj = load_project(pdir)
        sung = sung_plates(pdir, S)
        for e in plate_entries(S, proj):
            e["sung"] = e["plate"] in sung                 # the prompt as the book wrote it
            keys.add(e["plate"])
            if _real(e["prompt"]):
                try:
                    prompts[e["plate"]] = _norm(expand(e["prompt"], e, proj)[0])
                except SlopError:
                    prompts[e["plate"]] = _norm(e["prompt"])
    except SlopError:
        pass
    for f in sorted((pdir / "plates/mj").glob("*.json")) if (pdir / "plates/mj").is_dir() else []:
        b = read_json(f, default={}) or {}
        for j in b.get("jobs", []):
            key = j.get("plate") or j.get("job")
            if key:
                keys.add(key)
                prompts[key] = _norm(j.get("prompt", ""))
    return keys, prompts


def _api_plates(pdir: Path) -> tuple[set[str], bool]:
    """(the board's API-still plates, whether the project is Quick tier): their images' sizes are the model's."""
    try:
        proj = load_project(pdir)
    except SlopError:
        return set(), False
    quick = str(proj.get("tier") or "") == "quick"
    try:
        return {e["plate"] for e in plate_entries(load_shots(pdir), proj) if e["kind"] == "api"}, quick
    except SlopError:
        return set(), quick


def _match_prompt(text: str, prompts: dict[str, str]) -> str | None:
    """Plate whose normalised prompt is found in a download's filename text: the longest common prefix of the prompt
    with the name read from any word (so a user name with '_' in it does not matter); >= 16 characters, or the whole
    rest of the name when it is shorter (>= 8); unique, else nothing."""
    t = _norm(text)
    if not t:
        return None
    starts = [0] + [i + 1 for i, ch in enumerate(t) if ch == " "]
    best, best_n, best_tail, tie = None, 0, 0, False
    for key, p in prompts.items():
        if not p:
            continue
        n, tail = 0, 0
        for i in starts:
            c = t[i:]
            k = 0
            while k < min(len(c), len(p)) and c[k] == p[k]:
                k += 1
            if k > n:
                n, tail = k, len(c)
        if n > best_n:
            best, best_n, best_tail, tie = key, n, tail, False
        elif n == best_n and n > 0:
            tie = True
    need = min(16, max(8, best_tail))
    return best if best and best_n >= need and not tie else None


def _exif_texts(im) -> list:
    """EXIF ImageDescription (270) and UserComment (37510) of an image, as strings."""
    out = []
    try:
        ex = im.getexif()
    except Exception:   # noqa: BLE001
        return out
    vals = [ex.get(270)]
    try:
        vals.append(ex.get_ifd(0x8769).get(37510))
    except Exception:   # noqa: BLE001
        pass
    for v in vals:
        if isinstance(v, bytes):
            head = v[:8]
            body = v[8:] if head.rstrip(b"\0") in (b"ASCII", b"UNICODE", b"JIS", b"") and len(v) > 8 else v
            v = body.decode("utf-16" if head.startswith(b"UNICODE") else "utf-8", "ignore")
        if isinstance(v, str) and v.strip():
            out.append(v.strip("\0 "))
    return out


def _embedded_text(path: Path) -> str:
    """Prompt-like text a download may carry in its metadata (PNG text chunks, XMP description, EXIF
    ImageDescription / UserComment), else ''."""
    from PIL import Image
    try:
        with Image.open(path) as im:
            info = dict(im.info)
            exif = _exif_texts(im)
    except Exception:   # noqa: BLE001
        return ""
    texts = [x for x in exif if len(x) >= 30]
    for k, v in info.items():
        if isinstance(v, bytes):
            v = v.decode("utf-8", "ignore")
        if not isinstance(v, str) or len(v) < 30:
            continue
        if "xmp" in str(k).lower() or v.lstrip().startswith("<"):
            m = re.findall(r"<dc:description>(.*?)</dc:description>", v, re.S)
            v = " ".join(re.sub(r"<[^>]+>", " ", x) for x in m) if m else ""
        texts.append(v)
    return " ".join(texts)


def _match_embedded(text: str, prompts: dict[str, str]) -> str | None:
    t = _norm(text)
    if len(t) < 30:
        return None
    hits = [k for k, p in prompts.items() if p and (p in t or t.startswith(p[:max(30, len(p) - 40)]))]
    return hits[0] if len(hits) == 1 else None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest(pdir: Path, src: str, batch: str | None = None, maps: list[str] | None = None, force: bool = False,
           from_url: bool = False) -> dict:
    from PIL import Image
    from ..util import input_path, not_found
    srcp = input_path(pdir, src)                       # from the current folder, else inside the project
    if not srcp or not srcp.exists():
        raise SlopError(not_found(pdir, src, "download") + " (give the downloaded zip, the folder of images, or one image)")
    cands_root, sr = (pdir / "plates/cands").resolve(), srcp.resolve()
    inside = sr == cands_root or cands_root in sr.parents
    if srcp.is_dir() and (inside or (sr in cands_root.parents and cands_root.is_dir())):
        raise SlopError(f"{src} is " + ("a folder of plates/cands/" if inside else "a folder that holds plates/cands/")
                        + " (the candidates themselves): ingest the downloads or the generator's output folder instead "
                          "(e.g. uploads/gen); nothing was added")
    if srcp.is_file() and inside and not maps:
        raise SlopError(f"{src} is already a candidate (plates/cands/); nothing was added. To make it a candidate of "
                        f"another plate: `{pcmd(pdir, 'plates ingest ' + shlex.quote(str(src)) + ' --plate PLATE')}`")
    keys, prompts = _known_plates(pdir)
    by_lower = {k.lower(): k for k in keys}
    api_named, quick = _api_plates(pdir)
    if batch:
        bj = read_json(pdir / "plates/mj" / f"{batch}.json", default=None)
        if bj:
            prompts = {(j.get("plate") or j.get("job")): _norm(j.get("prompt", "")) for j in bj.get("jobs", [])}
    mapping = {}
    for m in maps or []:
        a, _, b = m.partition("=")
        if not b or not a.strip():
            raise SlopError(f"--map {m}: write KEY=PLATE (KEY = a job uuid prefix, a file name or a file stem)")
        target = b.strip()
        if keys and target.split("~")[0] not in keys:
            near = sorted(k for k in keys if k.startswith(target[:2]))[:8] or sorted(keys)[:8]
            raise SlopError(f"--map {m}: '{target}' is not a plate of this board or batch (e.g. {', '.join(near)}). "
                            "Check the key in plates/prompts.md or `slop plates status`.")
        mapping[a.strip().lower()] = target
    tmp = None
    try:
        if srcp.is_file() and srcp.suffix.lower() == ".zip":
            tmp = Path(tempfile.mkdtemp(prefix="slop-ingest-"))
            with zipfile.ZipFile(srcp) as z:
                for info in z.infolist():
                    name = Path(info.filename)
                    if info.is_dir() or name.suffix.lower() not in IMG_EXT or name.name.startswith("._"):
                        continue
                    out = tmp / Path(*[p for p in name.parts if p not in ("..", "/", "\\")])
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as fi, open(out, "wb") as fo:
                        shutil.copyfileobj(fi, fo)
            root = tmp
        else:
            root = srcp
        files = [root] if root.is_file() else sorted(f for f in root.rglob("*") if f.is_file() and f.suffix.lower() in IMG_EXT
                                                      and not f.name.startswith("._"))
        assign: list[tuple[str, int | None, Path]] = []
        named: set[Path] = set()                       # matched by a plate name (generator outputs, not MJ downloads)
        groups: dict[str, list[tuple[int, Path]]] = {}
        loose: dict[str, list[tuple[int, Path]]] = {}
        unmatched: list[Path] = []

        def plate_of(name: str, sep: str = "-") -> str | None:
            """a plate key for a name: the board's (any case); with no board and no batch at all, a plate-like name
            (a letter first, then letters, digits, '.', '-'; joined by '-' to its number) is taken as a new plate key
            unless it is a name a download or an image tool gives on its own (image-1, Screenshot-..., a date)."""
            if name.lower() in by_lower:
                return by_lower[name.lower()]
            if not keys and sep == "-" and re.fullmatch(r"[A-Za-z][A-Za-z0-9.-]{0,39}", name) \
                    and not UUID_RE.search(name) and not GENERIC_NAME.match(name) \
                    and not re.search(r"\d{4}-\d{2}-\d{2}|\d{6,}", name):
                return name
            return None
        top = root if root.is_dir() else root.parent    # the folder given (or the one file's own): never a new plate
        for f in files:
            stem = f.stem
            mk = mapping.get(f.name.lower()) or mapping.get(stem.lower())
            if mk:
                assign.append((mk, None, f))
                continue
            m = re.match(r"^(?P<key>.+?)(?P<sep>[-_])(?P<k>\d{1,2})$", stem)   # "<plate>-<k>.png" (Grok, API, Drive)
            key = plate_of(m.group("key"), m.group("sep")) if m else None
            if key:
                assign.append((key, int(m.group("k")), f))
                named.add(f)
                continue
            # "<plate>/<k>.png"; DIR may be the plate's own folder when the board has that plate (a zip's temporary
            # folder, or an unknown folder given as DIR, is never taken as a plate)
            par_ok = f.parent != top or (tmp is None and f.parent.name.lower() in by_lower)
            key = plate_of(f.parent.name) if par_ok and re.fullmatch(r"\d{1,3}", stem) else None
            if key:
                assign.append((key, int(stem), f))
                named.add(f)
                continue
            u = UUID_RE.search(stem) or UUID_RE.search(f.parent.name)
            if u:
                tail = stem[u.end():] if UUID_RE.search(stem) else stem
                n = re.search(r"(\d)(?!.*\d)", tail)
                groups.setdefault(u.group(1).lower(), []).append((int(n.group(1)) if n else 0, f))
                continue
            if f.parent != root and f.parent.name in keys:
                assign.append((f.parent.name, None, f))
                continue
            if stem in keys:
                assign.append((stem, None, f))
                continue
            mi = re.match(r"^(?P<body>.+?)[_-](?P<n>\d{1,2})$", stem)    # "<user>_<prompt words>_<hash>[_<n>]"
            loose.setdefault((mi.group("body") if mi else stem).lower(), []).append(
                (int(mi.group("n")) if mi else 0, f))
        for body, items in loose.items():          # no uuid: the embedded prompt, else the prompt words in the name
            key = _match_embedded(_embedded_text(items[0][1]), prompts)
            if key is None:
                key = _match_prompt(re.sub(r"[_-][0-9a-f]{6,}$", "", body), prompts)
            if key is None:
                unmatched += [f for _, f in sorted(items, key=lambda x: (x[0], x[1].name))]
                continue
            for _, f in sorted(items, key=lambda x: (x[0], x[1].name)):
                assign.append((key, None, f))
        unmatched_groups: dict[str, list[Path]] = {}
        group_warn: list[str] = []
        for uid, items in groups.items():
            key = next((v for k, v in mapping.items() if uid.startswith(k) and len(k) >= 6), None)
            if key is None:                       # the full prompt in the file's metadata, when the download has it
                key = _match_embedded(_embedded_text(items[0][1]), prompts)
            if key is None:                       # else the prompt words in the file name (unique or nothing)
                stem = items[0][1].stem
                u = UUID_RE.search(stem)
                key = _match_prompt(stem[:u.start()] if u else "", prompts) if u and u.start() > 0 else None
            if len(items) != 4:
                group_warn.append(f"job {uid[:8]} ({key or 'unmatched'}) has {len(items)} image(s), expected 4 — a partial "
                                  "download or the profile filter? (re-download that job, or re-paste it)")
            if key is None:
                unmatched_groups[uid] = [f for _, f in sorted(items, key=lambda x: (x[0], x[1].name))]
                continue
            for n, f in sorted(items, key=lambda x: (x[0], x[1].name)):
                assign.append((key, n + 1, f))
        # write
        idx_path = pdir / "plates/cands/index.json"
        index = read_json(idx_path, default={}) or {}
        added: dict[str, list[int]] = {}
        dups, broken, small = 0, [], []
        orig_dir = pdir / "plates/mj" / batch / "orig" if batch else pdir / "plates/orig"
        for key, want, f in assign:
            if "~" in key:
                key = key.split("~")[0]
            try:
                with Image.open(f) as im:
                    im.load()
                    rgb = im.convert("RGB")
            except Exception:   # noqa: BLE001 - truncated or not an image
                broken.append(f.name)
                continue
            buf = io.BytesIO()
            rgb.save(buf, "JPEG", quality=95)
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            ent = index.setdefault(key, {})
            if any(v.get("sha256") == sha for v in ent.values()) and not force:
                dups += 1
                continue
            d = pdir / "plates/cands" / key
            # numbers in use: images, and the sidecars `slop gen image` claims before its image lands
            taken = set(_cands(pdir, key)) | ({int(p.stem) for p in d.glob("*.json") if p.stem.isdigit()}
                                              if d.is_dir() else set())
            k = want if (want and (want not in taken or force)) else (max(list(taken) + [0] + [int(x) for x in ent]) + 1)
            d.mkdir(parents=True, exist_ok=True)
            for old in d.glob(f"{k}.*"):
                if old.suffix.lower() in IMG_EXT or old.suffix == ".json":   # the replaced image's sidecar goes too
                    old.unlink()
            (d / f"{k}.jpg").write_bytes(buf.getvalue())
            orig = _keep_original(f, orig_dir, sha, name=f"{key}-{f.name}" if f.stem.isdigit() else None)
            ent[str(k)] = {"src": f.name, "sha256": sha, "w": rgb.width, "h": rgb.height, "batch": batch,
                           "orig": rel(pdir, orig)}
            added.setdefault(key, []).append(k)
            generator = f in named and (key in api_named or (quick and key not in keys))
            if rgb.width / max(1, rgb.height) > 1.6 and rgb.width < 2000 and not generator:
                small.append(f"{key}/{k} {rgb.width}x{rgb.height}")    # MJ's HD switch; an API/Grok size is the model's
        write_json(idx_path, index)
        sheet = None
        if unmatched_groups or unmatched:
            sheet = _unmatched_sheet(pdir, unmatched_groups, unmatched)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    expected = []
    if batch:
        bj = read_json(pdir / "plates/mj" / f"{batch}.json", default={}) or {}
        expected = [j.get("plate") or j.get("job") for j in bj.get("jobs", [])]
    no_images = [p for p in expected if not _cands(pdir, p)]
    n_new = sum(len(v) for v in added.values())
    text = f"ingested {n_new} image(s) into {len(added)} plate(s) (plates/cands/<plate>/<k>.jpg); {dups} duplicate(s) skipped."
    if broken:
        text += f"\n{len(broken)} file(s) could not be read (truncated download?): {', '.join(broken[:6])}"
    if small and not from_url:                    # an API result's size is the model's, not Midjourney's HD switch
        text += f"\n{len(small)} image(s) are SD size (was HD off?): {', '.join(small[:6])}"
    if unmatched_groups or unmatched:
        text += (f"\n{len(unmatched_groups)} Midjourney job(s) and {len(unmatched)} file(s) could not be matched to a plate: "
                 f"see {rel(pdir, sheet)}. Look at them next to plates/prompts.md and re-run with "
                 "--map <uuid-prefix or file name>=<plate> for each.")
    if group_warn:
        text += "\n" + "\n".join(group_warn[:8]) + (f"\n… {len(group_warn) - 8} more" if len(group_warn) > 8 else "")
    if no_images:
        text += f"\nbatch jobs with no images yet: {', '.join(no_images)} (paste them again: plates/mj/{batch}.lines.txt)"
    text += (f"\nnext: `{pcmd(pdir, 'plates sheet')}` (numbered picking sheets) then `"
             + pcmd(pdir, "plates pick PLATE K") + "` for each plate (PLATE = the plate, K = the candidate number).")
    return {"added": added, "duplicates": dups, "broken": broken, "sd_size": small,
            "unmatched_jobs": {k: [f.name for f in v] for k, v in unmatched_groups.items()},
            "unmatched_files": [f.name for f in unmatched], "unmatched_sheet": rel(pdir, sheet) if sheet else None,
            "batch_jobs_without_images": no_images, "group_warnings": group_warn, "text": text}


def _keep_original(f: Path, orig_dir: Path, sha: str, name: str | None = None) -> Path:
    """The downloaded file byte for byte (research: keep originals); never overwrites a different file. name: the
    original's file name when f's own says too little (a "<plate>/<k>.png" output is kept as "<plate>-<k>.png")."""
    orig_dir.mkdir(parents=True, exist_ok=True)
    out = orig_dir / (name or f.name)
    base = Path(out.name)
    k = 1
    while out.exists():
        try:
            if hashlib.sha256(out.read_bytes()).hexdigest() == sha:
                return out
        except OSError:
            pass
        out = orig_dir / f"{base.stem}.{k}{base.suffix}"
        k += 1
    shutil.copy2(f, out)
    return out


def _unmatched_sheet(pdir: Path, groups: dict[str, list[Path]], files: list[Path]) -> Path:
    from PIL import Image, ImageDraw
    items = [(uid[:8], fs[0]) for uid, fs in groups.items()] + [(f.name[:24], f) for f in files]
    TW, TH, LAB = 480, 270, 34
    cols = 4
    rows = max(1, (len(items) + cols - 1) // cols)
    sh = Image.new("RGB", (TW * cols, (TH + LAB) * rows), "#111")
    d = ImageDraw.Draw(sh)
    for i, (label, f) in enumerate(items):
        x, y = (i % cols) * TW, (i // cols) * (TH + LAB)
        try:
            with Image.open(f) as im:
                im = im.convert("RGB")
                im.thumbnail((TW, TH))
                sh.paste(im, (x, y + LAB))
        except Exception:   # noqa: BLE001
            pass
        d.text((x + 8, y + 4), label, font=font(22, True), fill="#eee")
    out = pdir / "plates/unmatched.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    sh.save(out, quality=85)
    return out


# ------------------------------------------------------------------------------------------------ sheets / picks
def sheet(pdir: Path, plates: list[str] | None = None, per: int = 10) -> dict:
    from PIL import Image, ImageDraw
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    root = pdir / "plates/cands"
    if plates:
        keys = list(plates)
    else:
        keys = sorted(d.name for d in root.iterdir() if d.is_dir()) if root.is_dir() else []
    keys = [k for k in keys if _cands(pdir, k)]
    if not keys:
        raise SlopError("no candidates yet: ingest the downloads first (`slop plates ingest <zip or folder>`)")
    try:
        S = load_shots(pdir)
        shots_of: dict[str, list[str]] = {}
        for s in S["shots"]:
            p = shot_plate(s, S)
            if p:
                shots_of.setdefault(p.split("~")[0], []).append(s["id"])
    except SlopError:
        shots_of = {}
    TW, TH, LAB = 480, 270, 34
    outdir = pdir / "plates/sheets"
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("pick-*.jpg"):
        old.unlink()
    outs = []
    for g in range(0, len(keys), per):
        grp = keys[g:g + per]
        ncol = max(4, max(len(_cands(pdir, k)) for k in grp))
        sh = Image.new("RGB", (TW * ncol, (TH + LAB) * len(grp)), "#111")
        d = ImageDraw.Draw(sh)
        for r, key in enumerate(grp):
            y = r * (TH + LAB)
            pk = (picks.get(key) or {}).get("cand_k")
            d.text((8, y + 4), f"{key} · shots {', '.join(shots_of.get(key, [])[:6])}" + (f" · picked #{pk}" if pk else ""),
                   font=font(22, True), fill="#eee")
            for c, (k, f) in enumerate(_cands(pdir, key).items()):
                with Image.open(f) as im:
                    im = im.convert("RGB")
                    im.thumbnail((TW, TH))
                    sh.paste(im, (c * TW, y + LAB))
                if k == pk:
                    d.rectangle([c * TW, y + LAB, c * TW + TW - 1, y + LAB + TH - 1], outline=ACC, width=6)
                d.rectangle([c * TW + 6, y + LAB + 6, c * TW + 70, y + LAB + 46], fill="#111")
                d.text((c * TW + 12, y + LAB + 8), f"#{k}", font=font(28, True), fill=ACC)
        o = outdir / f"pick-{g // per + 1:02d}.jpg"
        sh.save(o, quality=86)
        outs.append(rel(pdir, o))
    return {"sheets": outs, "plates": len(keys),
            "text": f"{len(outs)} picking sheet(s) in plates/sheets/ for {len(keys)} plate(s). Send them to the owner (or "
                    "pick yourself and let the owner review on the storyboard); record picks with `"
                    + pcmd(pdir, "plates pick PLATE K") + "` (several at once: PLATE K PLATE K …)."}


def parse_pairs(args: list[str]) -> list[tuple[str, int]]:
    text = " ".join(args).replace(",", " ")
    pairs = re.findall(r"([A-Za-z0-9][\w.~-]*?)\s*(?:#|:|=|\s)\s*#?(\d+)\b", text)
    if not pairs:
        raise SlopError("give PLATE K pairs, e.g. `slop plates pick p001 2 p004 1` or `slop plates pick \"p001#2, p004#1\"`")
    return [(p, int(k)) for p, k in pairs]


def _shot_ids(S: dict | None, key: str) -> list[str]:
    if not S:
        return []
    return [s["id"] for s in sorted(S["shots"], key=lambda s: float(s["t0"])) if shot_plate(s, S) == key]


def pick(pdir: Path, args: list[str], all_first: bool = False) -> dict:
    picks_path = pdir / "plates/picks.json"
    picks = read_json(picks_path, default={}) or {}
    try:
        S = load_shots(pdir)
    except SlopError:
        S = None
    pairs = []
    if all_first:
        root = pdir / "plates/cands"
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if d.is_dir() and d.name not in picks and _cands(pdir, d.name):
                pairs.append((d.name, min(_cands(pdir, d.name))))
    if args:
        pairs += parse_pairs(args)
    if not pairs and all_first and not args and picks:
        # idempotent re-run: every plate with candidates is already picked (integration fix: this used to exit 1)
        unpicked = []
        if S:
            unpicked = sorted({shot_plate(s, S) for s in S["shots"] if shot_plate(s, S) and shot_plate(s, S) not in picks})
        return {"picked": [], "unpicked": unpicked,
                "text": "nothing new to pick: every plate with candidates already has a pick"
                        + (f"; {len(unpicked)} plate(s) of the board have no candidates yet ({', '.join(unpicked[:10])}) "
                           "— ingest them first" if unpicked else "")
                        + f".\nnext: `{pcmd(pdir, 'plates vary')}` (one image per shot), then `"
                        + pcmd(pdir, "board sheet") + "` for review."}
    if not pairs:
        raise SlopError("nothing to pick: give PLATE K pairs (or --all-first to take candidate 1 of every unpicked plate)")
    done = []
    live = None
    if S:
        live = {shot_plate(s, S) for s in S["shots"]} | {c.get("plate") for c in S.get("seedance", [])}
    for key, k in pairs:
        c = _cands(pdir, key)
        if k not in c:
            raise SlopError(f"{key} has no candidate #{k} (has {', '.join('#' + str(x) for x in c) or 'none — ingest first'})")
        base = key.split("~")[0]
        clash = sorted(o for o, v in picks.items() if o != key and o.split("~")[0] == base
                       and (v or {}).get("cand_k") == k and (live is None or o in live))
        if clash:
            taken = {int(v["cand_k"]) for o, v in picks.items() if o.split("~")[0] == base and o != key
                     and (v or {}).get("cand_k") is not None and (live is None or o in live)}
            free = [x for x in c if x not in taken]
            raise SlopError(f"{key}#{k} is already the image of {', '.join(clash)} (a variant made by `slop plates vary` "
                            "for another moment): one image would be on two moments. Pick another candidate"
                            + (f" (free: {', '.join('#' + str(x) for x in free)})" if free else
                               f" — none is free: generate more (`slop plates book --only {base} --batch <new>`)")
                            + f", or first give {clash[0]} another one (`slop plates pick {clash[0]} N`), then re-run "
                            "`slop plates vary`.")
        old = picks.get(key) or {}
        picks[key] = {**{x: v for x, v in old.items() if x in ("variant_of", "bad")}, "file": rel(pdir, c[k]),
                      "cand_k": k, "shot_ids": _shot_ids(S, key)}
        done.append(f"{key}#{k}")
    write_json(picks_path, picks)
    unpicked = []
    if S:
        unpicked = sorted({shot_plate(s, S) for s in S["shots"] if shot_plate(s, S) and shot_plate(s, S) not in picks})
    return {"picked": done, "unpicked": unpicked,
            "text": f"picked {', '.join(done)}; {len(unpicked)} plate(s) of the board still unpicked"
                    + (f" ({', '.join(unpicked[:10])})" if unpicked else "")
                    + f".\nnext: `{pcmd(pdir, 'plates vary')}` (one image per shot), then `"
                    + pcmd(pdir, "board sheet") + "` for review."}


def vary(pdir: Path, dry: bool = False) -> dict:
    S = load_shots(pdir)
    picks_path = pdir / "plates/picks.json"
    picks = read_json(picks_path, default={}) or {}
    shots = sorted(S["shots"], key=lambda s: float(s["t0"]))
    plates_by = {p.get("plate"): p for p in S.get("plates", []) if p.get("plate")}
    changes: list[str] = []
    problems: list[str] = []
    stale = None

    def continuous(a: dict, b: dict) -> bool:
        ca, cb = shot_clips(a), shot_clips(b)
        return abs(float(a["t1"]) - float(b["t0"])) < 1e-3 and bool(ca) and bool(cb) and ca[0] == cb[0]

    def used_ks(base: str) -> set[int]:
        live = {shot_plate(s, S) for s in shots}
        return {int(v["cand_k"]) for k, v in picks.items()
                if (k == base or v.get("variant_of") == base) and k in live and v.get("cand_k") is not None}

    def make_variant(base: str, k: int, ids: list[str]) -> str:
        vkey = f"{base}~{k}"
        c = _cands(pdir, base)
        picks[vkey] = {"file": rel(pdir, c[k]), "cand_k": k, "shot_ids": ids, "variant_of": base}
        src = plates_by.get(base) or {}
        if vkey not in plates_by:
            ent = {**{x: v for x, v in src.items() if x not in ("plate", "used_by", "mj_prompt", "img_prompt", "prompt")},
                   "plate": vkey, "variant_of": base, "used_by": []}
            S["plates"].append(ent)
            plates_by[vkey] = ent
        for sid in ids:
            if sid not in plates_by[vkey]["used_by"]:
                plates_by[vkey]["used_by"].append(sid)
            if src and sid in (src.get("used_by") or []):
                src["used_by"].remove(sid)
        return vkey

    groups: dict[str, list[dict]] = {}
    for s in shots:
        p = shot_plate(s, S)
        if p:
            groups.setdefault(p, []).append(s)
    for key, L in groups.items():
        runs: list[list[dict]] = []
        for s in L:
            if runs and continuous(runs[-1][-1], s):
                runs[-1].append(s)
            else:
                runs.append([s])
        if len(runs) < 2:
            continue
        base = key.split("~")[0]
        pk = picks.get(key)
        if not pk:
            problems.append(f"{key} is on {len(runs)} separate moments but has no pick yet: `slop plates pick {key} K` first")
            continue
        taken = used_ks(base)
        pool = [k for k in _cands(pdir, base) if k not in taken and k not in (pk.get("bad") or [])]
        for run in runs[1:]:
            ids = [s["id"] for s in run]
            if not pool:
                problems.append(f"{', '.join(ids)}: out of distinct images for {base} — generate more candidates "
                                f"(`slop plates book --only {base} --batch <new>`) or give the shot its own plate")
                continue
            k = pool.pop(0)
            vkey = f"{base}~{k}"
            changes.append(f"{', '.join(ids)}: {key} -> {vkey}")
            if not dry:
                make_variant(base, k, ids)
                for s in run:
                    s["plate"] = vkey
    # clips follow their first shot's plate, and no two clips start from the same frame
    by_id = {s["id"]: s for s in shots}
    starts: dict[str, str] = {}
    for c in sorted(S.get("seedance", []), key=lambda c: float(c.get("song_t0") or 0)):
        ids = sorted((i for i in c.get("shots", []) if i in by_id), key=lambda i: float(by_id[i]["t0"]))
        if ids and shot_plate(by_id[ids[0]], S):
            newp = shot_plate(by_id[ids[0]], S)
            if c.get("plate") != newp:
                changes.append(f"clip {c.get('clip')}: plate {c.get('plate')} -> {newp}")
                if not dry:
                    c["plate"] = newp
        p = c.get("plate")
        f = (picks.get(p) or {}).get("file") or p
        if not f:
            continue
        if f in starts:
            base = p.split("~")[0]
            pool = [k for k in _cands(pdir, base) if k not in used_ks(base)
                    and rel(pdir, _cands(pdir, base)[k]) not in starts]
            if not pool:
                problems.append(f"clip {c.get('clip')} starts from the same frame as {starts[f]} and {base} has no unused "
                                "candidate left — generate more candidates or continue from the previous clip")
                continue
            k = pool[0]
            changes.append(f"clip {c.get('clip')}: start {p} -> {base}~{k} (two clips never start from the same frame)")
            if not dry:
                c["plate"] = make_variant(base, k, [])
            f = rel(pdir, _cands(pdir, base)[k])
        starts[f] = c.get("clip")
    if not dry:
        from .draft import clip_cmd
        for c in S.get("seedance", []):            # keep each clip's `slop clip new` command in step with its start
            if not c.get("cmd"):
                continue
            first = by_id.get((c.get("shots") or [None])[0])
            cc = dict(c)
            if c.get("plate") and first is not None and shot_plate(first, S) != c["plate"] and not c.get("start"):
                f = (picks.get(c["plate"]) or {}).get("file")
                if f:
                    cc["start"] = f
            c["cmd"] = clip_cmd(pdir, cc)
        S["plates"] = [p for p in S["plates"] if p.get("used_by") or "~" not in str(p.get("plate"))
                       or any(c.get("plate") == p.get("plate") for c in S.get("seedance", []))]
        for key, v in picks.items():
            v["shot_ids"] = _shot_ids(S, key)
        save_shots(pdir, S)
        write_json(picks_path, picks)
        if changes:                                # the shots now show other images: an approved board needs the owner
            stale = board_gate_stale(pdir)
    text = (f"{'would make' if dry else 'made'} {len(changes)} change(s)" + (":\n  " + "\n  ".join(changes) if changes else "")
            + ("\nproblems:\n  " + "\n  ".join(problems) if problems else "")
            + (f"\nwarning: {stale}" if stale else "")
            + ("" if dry else f"\nnext: `{pcmd(pdir, 'board audit')}` (plates_unique gate), then `"
               + pcmd(pdir, "board sheet") + "`."))
    return {"changes": changes, "problems": problems, "dry": dry, "gate_stale": bool(stale),
            "warnings": [stale] if stale else [], "text": text}


def status(pdir: Path) -> dict:
    proj = load_project(pdir)
    S = load_shots(pdir)
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    rows = []
    for e in plate_entries(S, proj):
        c = _cands(pdir, e["plate"])
        rows.append({"plate": e["plate"], "kind": e["kind"], "prompt": "ready" if _real(e["prompt"]) else "TODO",
                     "candidates": len(c), "pick": (picks.get(e["plate"]) or {}).get("cand_k"), "shots": e["shots"]})
    variants = sorted(k for k in picks if "~" in k)
    lines = [f"{'PLATE':<12} {'KIND':<4} {'PROMPT':<6} {'CANDS':>5} {'PICK':>4}  SHOTS"]
    for r in rows:
        lines.append(f"{r['plate']:<12} {r['kind']:<4} {r['prompt']:<6} {r['candidates']:>5} {str(r['pick'] or '-'):>4}  "
                     f"{', '.join(r['shots'][:6])}")
    todo = sum(1 for r in rows if r["prompt"] == "TODO")
    nocand = sum(1 for r in rows if not r["candidates"])
    unp = sum(1 for r in rows if not r["pick"])
    lines.append(f"{len(rows)} plates · {todo} prompt TODO · {nocand} without candidates · {unp} unpicked · "
                 f"{len(variants)} variant plates")
    return {"plates": rows, "variants": variants, "text": "\n".join(lines)}


# ------------------------------------------------------------------------------------------------ ingest from URLs
URL_MAX_BYTES = 60 * 1024 * 1024
CT_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/webp": ".webp"}


def _download(url: str, dest: Path, timeout: float = 60.0) -> tuple[Path, str]:
    """GET one HTTPS image into dest (<= 60 MB) -> (path, content type). The single network call of `--url`."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "claudia"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            data = r.read(URL_MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise SlopError(f"download failed: HTTP {e.code} for {_public(url)} — signed result links expire; fetch a fresh "
                        "link from the generator (or download the file and run `slop plates ingest FILE --map "
                        "NAME=PLATE`)") from e
    except (urllib.error.URLError, OSError) as e:
        raise SlopError(f"download failed for {_public(url)}: {e} — check the network, or download the file and run "
                        "`slop plates ingest FILE --map NAME=PLATE`") from e
    if len(data) > URL_MAX_BYTES:
        raise SlopError(f"{_public(url)} is larger than {URL_MAX_BYTES // 2**20} MB — not a plate image")
    if ctype and not (ctype.startswith("image/") or ctype in ("application/octet-stream", "binary/octet-stream")):
        raise SlopError(f"{_public(url)} is {ctype}, not an image — give the image's own URL (it ends in .png/.jpg/"
                        ".webp, or the generator's result link)")
    dest.write_bytes(data)
    return dest, ctype


def _public(url: str) -> str:
    """A URL without its query string (signed links carry tokens: never echo or store them)."""
    from urllib.parse import urlsplit, urlunsplit
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def ingest_urls(pdir: Path, urls: list[str], plate: str, batch: str | None = None, force: bool = False,
                credits: float | None = None, job_id: str | None = None, model: str | None = None) -> dict:
    """Download HTTPS results (e.g. CloudFront links from the Higgsfield connector) as candidates of one plate.
    --credits N (and --job-id, --model) records the Higgsfield generation in the project ledger, once per job id
    (or per set of URLs), so `slop spend` counts the stills the bot made with the connector."""
    from urllib.parse import urlsplit
    if not plate:
        raise SlopError("--url needs --plate PLATE (the plate these images are candidates for, e.g. p004)")
    if credits is not None and not (0 <= float(credits) <= 100000):
        raise SlopError(f"--credits {credits:g}: give the credits the generation cost (0 or more; estimate_image_cost / "
                        "the job tells it); nothing was downloaded")
    keys, _ = _known_plates(pdir)
    base = plate.split("~")[0]
    if keys and base not in keys:
        near = sorted(k for k in keys if k.startswith(base[:2]))[:8] or sorted(keys)[:8]
        raise SlopError(f"--plate {plate}: not a plate of this board (e.g. {', '.join(near)}) — `slop plates status` "
                        "lists them; nothing was downloaded")
    bad = [u for u in urls if urlsplit(u).scheme != "https" or not urlsplit(u).netloc]
    if bad:
        raise SlopError(f"only https:// result links can be downloaded: {', '.join(_public(u) for u in bad[:3])} — for a "
                        "local file run `slop plates ingest FILE --map NAME=PLATE`; nothing was downloaded")
    tmp = Path(tempfile.mkdtemp(prefix="slop-url-"))
    try:
        files: list[tuple[Path, str]] = []
        for n, u in enumerate(urls, 1):
            ext = Path(urlsplit(u).path).suffix.lower()
            dest = tmp / f"{base}-dl{n:02d}{ext if ext in IMG_EXT else '.img'}"
            f, ctype = _download(u, dest)
            if f.suffix == ".img":
                f2 = f.with_suffix(CT_EXT.get(ctype, ".png"))
                f.rename(f2)
                f = f2
            files.append((f, u))
        maps = [f"{f.name}={base}" for f, _ in files]
        res = ingest(pdir, str(tmp), batch=batch, maps=maps, force=force, from_url=True)
        idx_path = pdir / "plates/cands/index.json"
        index = read_json(idx_path, default={}) or {}
        by_name = {f.name: _public(u) for f, u in files}
        for k, v in (index.get(base) or {}).items():
            if isinstance(v, dict) and v.get("src") in by_name and not v.get("url"):
                v["url"] = by_name[v["src"]]
        write_json(idx_path, index)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    res["downloaded"] = [_public(u) for u in urls]
    res["text"] = f"downloaded {len(urls)} image(s) for {base}.\n" + res["text"]
    if credits is not None or job_id:
        res.update(_ledger_still(pdir, base, res["downloaded"], credits, job_id, model))
        res["text"] += "\n" + res["ledger_text"]
    return res


def _ledger_still(pdir: Path, plate: str, urls: list[str], credits: float | None, job_id: str | None,
                  model: str | None) -> dict:
    """one ledger row for a Higgsfield still generation ingested by URL (idempotent: a row with the same job id OR the
    same URL set is the same generation, whichever the first ingest had)."""
    from .. import ledger
    from ..gen.higgsfield import USD_PER_CREDIT
    jid = (job_id or "").strip() or None
    for r in ledger.rows(pdir):
        if r.get("provider") != "higgsfield" or r.get("kind") != "image":
            continue
        if (jid and r.get("request_id") == jid) or (urls and (r.get("units") or {}).get("urls") == urls):
            return {"ledgered": False, "ledger_text": f"ledger: already recorded ({r.get('credits') or 0:g} credits"
                                                      + (f", job {jid}" if jid else "") + ")"}
    if credits is None:
        return {"ledgered": False, "ledger_text": "ledger: nothing recorded - add --credits N (what the generation cost) "
                                                  "so slop spend counts it"}
    row = ledger.record(pdir, provider="higgsfield", model=(model or "higgsfield-image").strip(), kind="image",
                        est_usd=0.0, credits=float(credits), status="delivered", request_id=jid,
                        units={"plate": plate, "images": len(urls), "urls": urls,
                               "usd_equiv": round(float(credits) * USD_PER_CREDIT, 2)},
                        note="Higgsfield still(s) ingested by URL (plates ingest --url)")
    txt = f"ledger: recorded {float(credits):g} Higgsfield credits for {plate}" + (f" (job {jid})" if jid else "")
    try:
        cap = float(((load_project(pdir).get("budget") or {}).get("higgsfield_credits")) or 0)
        spent = ledger.spent_credits(pdir)
        if cap and spent > cap + 1e-9:
            txt += (f"\n  ! the project's Higgsfield credits ({spent:g}) are now over its cap ({cap:g}): stop paid "
                    "generations and tell the owner")
    except (OSError, ValueError):
        pass
    return {"ledgered": True, "ledger_row": row, "ledger_text": txt}


# ------------------------------------------------------------------------------------------------ boxes
BOXES_REL = "plates/boxes.json"


def read_boxes(pdir: Path) -> dict:
    """plates/boxes.json -> {plate: {"boxes": {label: [u, v, w, h(, score)]}, "file": the picked file then}}."""
    raw = read_json(Path(pdir) / BOXES_REL, default={}) or {}
    out = {}
    for k, v in raw.items() if isinstance(raw, dict) else []:
        if isinstance(v, dict) and isinstance(v.get("boxes"), dict):
            out[k] = v
        elif isinstance(v, dict):                     # a bare {label: box} map
            out[k] = {"boxes": v}
    return out


def box(pdir: Path, plate: str, label: str | None = None, uv: str | None = None, score: float | None = None,
        rm: bool = False) -> dict:
    """Name a region of a plate's picked image (image space 0..1) so devices can point at it: `slop edit export`
    writes it to window.PLATES[plate].boxes, where an anchor {"box": label} (or the label itself) resolves to it."""
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    keys, _ = _known_plates(pdir)
    if plate not in picks and plate.split("~")[0] not in keys:
        raise SlopError(f"{plate} is not a plate of this board or a pick (`slop plates status` lists them); nothing was "
                        "changed")
    data = read_boxes(pdir)
    ent = data.get(plate) or {"boxes": {}}
    lead_label = str(((load_project(pdir).get("lead") or {}).get("label")) or "")
    if not label:
        if uv or rm:
            raise SlopError("give --label (what the box is: 'a face', 'the phone', 'subject'); nothing was changed")
        rows = [f"  {k}: {v}" for k, v in sorted(ent["boxes"].items())]
        return {"plate": plate, "boxes": ent["boxes"],
                "text": f"{plate}: {len(rows)} box(es)" + ("\n" + "\n".join(rows) if rows else
                                                            f" — add one: `slop plates box {plate} --label \"a face\" "
                                                            "--uv 0.42,0.18,0.16,0.22`")}
    label = label.strip()
    if not (1 <= len(label) <= 40) or any(c in label for c in "\"\\{}[]"):
        raise SlopError(f"--label '{label}': 1–40 characters, no quotes or brackets (e.g. 'a face', 'the phone'); "
                        "nothing was changed")
    if rm:
        if label not in ent["boxes"]:
            return {"plate": plate, "changed": False, "boxes": ent["boxes"],
                    "text": f"{plate} has no box '{label}' (no change)"}
        del ent["boxes"][label]
        data[plate] = ent
        write_json(pdir / BOXES_REL, data)
        return {"plate": plate, "changed": True, "boxes": ent["boxes"],
                "text": f"{plate}: removed box '{label}'. next: `{pcmd(pdir, 'edit export --no-frames')}`"}
    if not uv:
        raise SlopError(f"give --uv u,v,w,h: the box in image space, 0..1 of the picked image (u,v = its top-left "
                        f"corner); e.g. `slop plates box {plate} --label \"{label}\" --uv 0.42,0.18,0.16,0.22`; nothing "
                        "was changed")
    try:
        nums = [float(x) for x in re.split(r"[,\s]+", uv.strip()) if x]
    except ValueError as e:
        raise SlopError(f"--uv {uv!r}: four numbers u,v,w,h in 0..1; nothing was changed") from e
    if len(nums) != 4 or not all(0 <= x <= 1 for x in nums) or nums[2] <= 0 or nums[3] <= 0 \
            or nums[0] + nums[2] > 1.001 or nums[1] + nums[3] > 1.001:
        raise SlopError(f"--uv {uv}: four numbers u,v,w,h in 0..1 of the image, w and h > 0, u+w and v+h at most 1 "
                        "(e.g. 0.42,0.18,0.16,0.22); nothing was changed")
    b = [round(x, 4) for x in nums]
    if score is not None:
        if not 0 <= float(score) <= 1:
            raise SlopError("--score must be between 0 and 1; nothing was changed")
        b.append(round(float(score), 3))
    changed = ent["boxes"].get(label) != b
    ent["boxes"][label] = b
    pk = (picks.get(plate) or {}).get("file")
    if pk:
        ent["file"] = pk
    data[plate] = ent
    if changed or not (pdir / BOXES_REL).is_file():
        write_json(pdir / BOXES_REL, data)
    notes = []
    if not pk:
        notes.append(f"{plate} has no pick yet: the box must match the image you pick (`slop plates pick {plate} K`)")
    if label in ("subject", "lead") or (lead_label and label == lead_label):
        notes.append("this is the subject box: lead marks, 'lead' anchors, stills crops and through/match transitions "
                     "use it")
    return {"plate": plate, "label": label, "box": b, "changed": changed, "boxes": ent["boxes"],
            "text": f"{plate}: box '{label}' = {b}" + (" (no change)" if not changed else "")
                    + ("\n" + "\n".join(f"note: {n}" for n in notes) if notes else "")
                    + f"\nnext: `{pcmd(pdir, 'edit export --no-frames')}` (writes it to window.PLATES), then anchor "
                      f"devices with {{\"box\": \"{label}\"}}: `"
                    + pcmd(pdir, "board device add SHOT --kind cv.bracket --anchor " + shlex.quote("box:" + label))
                    + "` (SHOT = a shot on this plate)"}


__all__ = ["book", "ingest", "ingest_urls", "box", "read_boxes", "style_tail", "sheet", "pick", "vary", "status",
           "plate_entries", "expand", "mj_line", "mj_params", "perm_escape", "parse_pairs", "valid_profile", "FRAMINGS"]
