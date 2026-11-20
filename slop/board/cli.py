"""CLI for the storyboard and plates: `slop board ...` and `slop plates ...` (router contract: register(subparsers)).

Every leaf command also accepts --project/-p and --json after the action (e.g. `slop board audit -p my-song --json`),
so an operator does not have to remember to put them before the command.
"""
from __future__ import annotations

import argparse

from ..config import SlopError, load_project, resolve_project, save_project


def leaf(sub, name: str, help_: str) -> argparse.ArgumentParser:
    p = sub.add_parser(name, help=help_, description=help_)
    p.add_argument("--project", "-p", default=argparse.SUPPRESS, help="project name or path")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable JSON on stdout")
    return p


def _help(parser: argparse.ArgumentParser):
    def f(args) -> dict:
        return {"text": parser.format_help()}
    return f


# ------------------------------------------------------------------------------------------------ board
def cmd_draft(a) -> dict:
    from . import draft
    return draft.run(resolve_project(a.project), force=a.force, out=a.out, pace=a.pace)


SET_FLAGS = ("set", "framing", "action", "img_prompt", "mj_prompt", "camera", "treatment", "transition_in", "line",
             "type_mode", "type_text", "type_placement", "subject_uv", "notes", "tier", "clip")


def cmd_set(a) -> dict:
    from . import shotedit
    fields = {k: getattr(a, k) for k in SET_FLAGS if getattr(a, k, None) is not None}
    if a.lead is not None:
        fields["lead"] = a.lead
    return shotedit.cmd_set(resolve_project(a.project), a.shot, fields, switch_generator=a.switch_generator)


def cmd_fill(a) -> dict:
    from . import shotedit
    return shotedit.cmd_fill(resolve_project(a.project), a.file, check=a.check, switch_generator=a.switch_generator)


def cmd_dev_add(a) -> dict:
    from . import shotedit
    return shotedit.device_add(resolve_project(a.project), a.shot, a.kind, line=a.line, anchor=a.anchor, key=a.key,
                               params=a.param, params_json=a.params, at=a.at, until=a.until, example=a.example,
                               priority=a.priority, replace=a.replace)


def cmd_dev_rm(a) -> dict:
    from . import shotedit
    return shotedit.device_rm(resolve_project(a.project), a.shot, index=a.index, kind=a.kind, line=a.line,
                              all_=a.all)


def cmd_dev_list(a) -> dict:
    from . import shotedit
    return shotedit.device_list(resolve_project(a.project), a.shot)


def cmd_dev_kinds(a) -> dict:
    from . import shotedit
    return shotedit.device_kinds(a.kind)


def cmd_audit(a) -> dict:
    from . import audit
    return audit.run(resolve_project(a.project), a.shots)


def cmd_sheet(a) -> dict:
    from . import sheet
    return sheet.build(resolve_project(a.project), a.shots, a.flags)


def cmd_approve(a) -> dict:
    """Re-run the audit (board/shots.json), then record the owner's approval through core's `record_gate`, which
    stores what it covers (the board's content signature: the approval goes stale when shots.json changes) and logs
    it in DECISIONS.md — the same path as `slop gate board --approve`."""
    from . import audit
    from .common import pcmd
    pdir = resolve_project(a.project)
    rep = audit.run(pdir)
    if not rep["ok"]:
        raise SlopError(f"the board does not pass its gates yet ({', '.join(rep['failed'])}); fix them before recording "
                        "the owner's approval:\n" + rep["text"])
    note = getattr(a, "note", None)
    try:
        from ..core_cli import record_gate
    except ImportError:
        record_gate = None
    if record_gate is not None:
        r = record_gate(pdir, "board_approved", True, note=note)
        covers = r.get("covers") or {}
        return {"approved": True, "changed": r.get("changed"), "covers": covers, "decision": r.get("decision"),
                "text": f"{r.get('text')} (gates.board_approved = true in project.json; covers "
                        f"{', '.join(f'{k} {v}' for k, v in covers.items()) or 'board/shots.json'} — any later change "
                        f"to the board needs the owner again). next: `{pcmd(pdir, 'plates book')}`."}
    proj = load_project(pdir)                      # core not installed: set the gate and log the decision ourselves
    changed = not proj.setdefault("gates", {}).get("board_approved")
    proj["gates"]["board_approved"] = True
    save_project(pdir, proj)
    if changed:
        import time
        with open(pdir / "DECISIONS.md", "a", encoding="utf-8") as f:
            f.write(f"- {time.strftime('%Y-%m-%d %H:%M')} - GATE board_approved approved" + (f" - {note}" if note else "")
                    + "\n")
    return {"approved": True, "changed": changed,
            "text": "recorded: gates.board_approved = true in project.json (logged in DECISIONS.md). next: "
                    "`slop plates book`."}


# ------------------------------------------------------------------------------------------------ plates
def cmd_book(a) -> dict:
    from . import plates
    only = [x.strip() for x in a.only.split(",") if x.strip()] if a.only else None
    return plates.book(resolve_project(a.project), batch=a.batch, only=only, missing=a.missing, plan=a.plan,
                       anchor=getattr(a, "anchor", None), no_anchor=bool(getattr(a, "no_anchor", False)))


def cmd_ingest(a) -> dict:
    from . import plates
    pdir = resolve_project(a.project)
    if a.url:
        if a.src:
            raise SlopError("give either a file/folder/zip or --url, not both")
        return plates.ingest_urls(pdir, a.url, a.plate, batch=a.batch, force=a.force, credits=a.credits,
                                  job_id=a.job_id, model=a.model)
    if a.credits is not None or a.job_id:
        raise SlopError("--credits / --job-id ledger a Higgsfield result: they go with --url (slop plates ingest --url "
                        "RESULT_URL --plate P --credits N --job-id ID)")
    if not a.src:
        raise SlopError("give the downloaded zip, a folder of images or one image (`slop plates ingest DOWNLOAD.zip "
                        "--batch b01`), or result links: `slop plates ingest --url https://… --plate p004`")
    if a.plate:
        from ..util import input_path
        src = input_path(pdir, a.src)                  # from the current folder, else inside the project
        names = [src.name] if src and src.is_file() else []
        if not names:
            if not src or not src.exists():
                from ..util import not_found
                raise SlopError(not_found(pdir, a.src, "image"))
            raise SlopError("--plate with a folder: use --map NAME=PLATE per file (or one image file with --plate)")
        return plates.ingest(pdir, a.src, batch=a.batch, maps=list(a.map) + [f"{names[0]}={a.plate}"], force=a.force)
    return plates.ingest(pdir, a.src, batch=a.batch, maps=a.map, force=a.force)


def cmd_box(a) -> dict:
    from . import plates
    return plates.box(resolve_project(a.project), a.plate, label=a.label, uv=a.uv, score=a.score, rm=a.rm)


def cmd_psheet(a) -> dict:
    from . import plates
    ps = [x.strip() for x in a.plates.split(",") if x.strip()] if a.plates else None
    return plates.sheet(resolve_project(a.project), ps)


def cmd_pick(a) -> dict:
    from . import plates
    return plates.pick(resolve_project(a.project), a.pairs, all_first=a.all_first)


def cmd_vary(a) -> dict:
    from . import plates
    return plates.vary(resolve_project(a.project), dry=a.dry)


def cmd_pstatus(a) -> dict:
    from . import plates
    return plates.status(resolve_project(a.project))


def register(sub) -> None:
    b = sub.add_parser("board", help="storyboard: draft, set/fill shot fields, devices, audit, contact sheet, approve",
                       description="Storyboard (board/shots.json): draft -> the lead writes the TODOs (`board set`, "
                                   "`board fill`, `board device add`) -> audit -> sheet -> owner approval.")
    bs = b.add_subparsers(dest="board_cmd", metavar="ACTION")
    b.set_defaults(func=_help(b))
    p = leaf(bs, "draft", "write a DRAFT board/shots.json from analysis/{beats,words}.json (cuts on beats, pace per "
                          "section, clips within budget, TODO markers for the lead)")
    p.add_argument("--force", action="store_true", help="replace an existing board/shots.json (a .bak copy is kept)")
    p.add_argument("--out", help="write the draft to this file instead of board/shots.json (--force to replace it); "
                                  "a relative path is inside the project, e.g. board/shots.redraft.json")
    p.add_argument("--pace", choices=["quick", "studio", "director"],
                   help="seconds a shot per section for this draft (docs/40 §6.1; default: project.json board.pace, "
                        "else the project's tier: quick ≈ 4–7 s, studio ≈ 2.5–5 s, director = EV's cut)")
    p.set_defaults(func=cmd_draft)

    p = leaf(bs, "set", "write one shot's fields (or several: s004,s007 or s004-s009) — validated against the engine; "
                        "a bad value changes nothing")
    p.add_argument("shot", help="shot id (s004), a list (s004,s007) or a range (s004-s009)")
    p.add_argument("--set", help="the place, concrete (\"a night market under sodium lamps\")")
    p.add_argument("--framing", help="ECU | CU | MCU | MS | MWS | WS | FS | EWS | OTS (or close-up, medium shot, …)")
    p.add_argument("--action", help="what happens, one concrete sentence")
    p.add_argument("--img-prompt", dest="img_prompt", help="the plate prompt for API images (framing words first; "
                   "{lead} for her canon; no '--' params)")
    p.add_argument("--mj-prompt", dest="mj_prompt", help="the plate prompt for Midjourney (same grammar)")
    p.add_argument("--camera", help="camera words: push · pull · pan/truck left/right · tilt/crane · orbit · static · "
                                    "handheld")
    p.add_argument("--treatment", help="2.5D family: layers | relight | contours | scan | rack | stills | diagram | push "
                                       "| occlusion | motion (code-drawn) | xerox (print look) | auto")
    p.add_argument("--transition-in", dest="transition_in", help="cut | through | whip | match | iris | flap | fade | "
                                                                 "flashCut | push | … (or prose: \"whip left\")")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--lead", dest="lead", action="store_const", const=True, default=None, help="the lead is on screen")
    g.add_argument("--no-lead", dest="lead", action="store_const", const=False, help="the lead is not on screen")
    p.add_argument("--line", help="which typed lyric line --type-* change (needed when the shot types several)")
    p.add_argument("--type-mode", dest="type_mode", help="subtitle | coverline | masthead | stack | mass (applied to "
                                                         "every shot typing the line)")
    p.add_argument("--type-text", dest="type_text", help="the line's on-screen text note")
    p.add_argument("--type-placement", dest="type_placement", help="left | right | center | top | bottom")
    p.add_argument("--subject-uv", dest="subject_uv", help="the subject's box u,v,w,h (0..1 of the image) for the "
                                                           "lead mark when the plate has no depth map")
    p.add_argument("--notes", help="free notes ('' clears)")
    p.add_argument("--tier", help="motion tier: still | plate3d (2.5D) | motion | sung; still/plate3d unlink the shot's "
                                  "clip (it plays its plate); motion/sung on a shot that plays a clip of the other kind "
                                  "needs --clip (a clip of that kind, or none)")
    p.add_argument("--clip", help="link a clip to the shot (one made after the board: s001-s002 --tier motion --clip "
                                  "c08); checked: it exists, its kind matches the tier (a motion shot plays a motion "
                                  "clip, a sung shot a sung one; no --tier = the clip's kind), its window covers the "
                                  "shot; the board's clip plan follows; 'none' unlinks. `edit edl` then plays it")
    p.add_argument("--switch-generator", action="store_true",
                   help="write the OTHER generator's prompt on purpose (a Midjourney plate on an API board or the "
                        "reverse); without it board set refuses the prompt field the board does not use")
    p.set_defaults(func=cmd_set)

    p = leaf(bs, "fill", "many shots at once from a TSV (header row: id, set, framing, action, img_prompt, …) or JSONL "
                         "file; one bad row fails the whole fill (nothing written). An empty cell leaves the field as "
                         "it is. A devices column/key REPLACES the shot's whole devices list ([] clears it; to add one "
                         "device use `board device add`).")
    p.add_argument("file", help="the TSV or JSONL file")
    p.add_argument("--check", action="store_true", help="validate only; write nothing (then run the same fill without "
                                                        "--check)")
    p.add_argument("--switch-generator", action="store_true",
                   help="allow the prompt column of the generator the board does not use (see board set)")
    p.set_defaults(func=cmd_fill)

    dv = bs.add_parser("device", help="the explaining graphics: add | rm | list | kinds",
                       description="Devices on a shot (devices[]): add one (validated against the engine's device "
                                   "library), remove, list, or list the library's kinds.")
    ds = dv.add_subparsers(dest="device_cmd", metavar="DEVICE_ACTION")
    dv.set_defaults(func=_help(dv))
    p = leaf(ds, "add", "add one device to a shot (e.g. --kind callout --line 3 --anchor uv:0.62,0.4 --param word=walk "
                        "--param 'rows=[\"LINE 04\", \"WALK\"]')")
    p.add_argument("shot")
    p.add_argument("--kind", required=True, help="a device kind (`slop board device kinds`)")
    p.add_argument("--line", help="the lyric line this device explains (the graphics gate counts it; not for camera "
                                  "moves, which draw nothing)")
    p.add_argument("--anchor", help="lead | subject | a slot (top-left, right, auto…) | uv:U,V[,W,H] | rect:X,Y,W,H | "
                                    "box:LABEL | JSON")
    p.add_argument("--key", help="timing key: W word · B beat · H hit · F fixed seconds · T clip take time")
    p.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                   help="one param (repeatable); the value is JSON when it parses (numbers, true, [..], {..}), else "
                        "text — word, word_end, at and until always stay text unless they start with [ or {")
    p.add_argument("--params", help="all params as one JSON object")
    p.add_argument("--at", help="start time spec (seconds, a word, shot.t0, or JSON like {\"beats\": 2})")
    p.add_argument("--until", help="end time spec")
    p.add_argument("--priority", type=float, help="budget tie-break (higher wins)")
    p.add_argument("--example", action="store_true", help="start from the device's catalogue example (params, key, "
                                                          "anchor); replace its on-screen text with --param")
    p.add_argument("--replace", type=int, metavar="I", help="replace devices[I] (from `device list SHOT`) instead of "
                                                            "adding — to change a device's params")
    p.set_defaults(func=cmd_dev_add)
    p = leaf(ds, "rm", "remove a device from a shot (by --index from `device list`, or --kind / --line)")
    p.add_argument("shot")
    p.add_argument("--index", type=int)
    p.add_argument("--kind")
    p.add_argument("--line")
    p.add_argument("--all", action="store_true", help="remove every match")
    p.set_defaults(func=cmd_dev_rm)
    p = leaf(ds, "list", "the devices on a shot (or on every shot), each checked against the engine")
    p.add_argument("shot", nargs="?")
    p.set_defaults(func=cmd_dev_list)
    p = leaf(ds, "kinds", "the engine's device library (read from engine/src/devices: every drawable device and "
                          "camera move); --kind K for one in full")
    p.add_argument("--kind")
    p.set_defaults(func=cmd_dev_kinds)
    p = leaf(bs, "audit", "run every storyboard gate -> board/audit.json + a table (exit 1 while a gate fails)")
    p.add_argument("--shots", help="audit this shots.json instead of board/shots.json (its report goes next to it as "
                                   "<name>.audit.json; board/audit.json is left alone)")
    p.set_defaults(func=cmd_audit)
    p = leaf(bs, "sheet", "contact sheet for owner approval -> board/board.pdf + board/board-pNN.jpg")
    p.add_argument("--shots", help="use this shots.json instead of board/shots.json")
    p.add_argument("--flags", help='JSON file {plate: "note"} to badge plates "FACE? note"')
    p.set_defaults(func=cmd_sheet)
    p = leaf(bs, "approve", "record the owner's approval (gates.board_approved, logged in DECISIONS.md) — only when "
                            "every gate passes; the same as `slop gate board --approve`")
    p.add_argument("--note", help="the owner's words, logged with the approval")
    p.set_defaults(func=cmd_approve)

    pl = sub.add_parser("plates", help="plates: prompt book + Midjourney paste batches, ingest, pick, vary",
                        description="Plates: book -> (owner reads) -> paste/generate -> ingest -> sheet -> pick -> vary.")
    ps = pl.add_subparsers(dest="plates_cmd", metavar="ACTION")
    pl.set_defaults(func=_help(pl))
    p = leaf(ps, "book", "plates/prompts.md + Midjourney permutation paste blocks + API jobs from the board's prompts")
    p.add_argument("--batch", default="b01", help="batch name (default b01; use a new one for re-rolls)")
    p.add_argument("--only", help="comma-separated plate keys")
    p.add_argument("--missing", action="store_true", help="only plates that have no candidates yet")
    p.add_argument("--plan", choices=["basic", "standard", "pro", "mega"],
                   help="Midjourney plan: prompts per paste 4/10/40/40 (default project.json mj.plan or standard)")
    p.add_argument("--anchor", metavar="PLATE[:K]",
                   help="identity anchor, after the owner approved the lead (G3): the picked image (or candidate K) goes "
                        "as a reference image into every lead plate's API job; kept by later books")
    p.add_argument("--no-anchor", action="store_true", help="drop the identity anchor from plates/jobs.json")
    p.set_defaults(func=cmd_book)
    p = leaf(ps, "ingest", "downloads (zip, folder or image) or HTTPS result links (--url … --plate P) -> "
                           "plates/cands/<plate>/<k>.jpg")
    p.add_argument("src", nargs="?", help="the downloaded zip, a folder of images, or one image")
    p.add_argument("--url", action="append", default=[], help="an HTTPS image link (e.g. a CloudFront result from the "
                                                               "Higgsfield connector); repeatable; needs --plate")
    p.add_argument("--plate", help="the plate the --url images (or one image file) are candidates for")
    p.add_argument("--batch", help="the batch these images belong to (its prompts identify Midjourney downloads)")
    p.add_argument("--map", action="append", default=[], metavar="KEY=PLATE",
                   help="assign an unmatched job uuid prefix or file name to a plate (repeatable)")
    p.add_argument("--force", action="store_true", help="overwrite candidate numbers that already exist")
    p.add_argument("--credits", type=float, help="--url from Higgsfield: the credits the generation cost (from its "
                                                 "estimate_image_cost / job) - recorded in the project ledger (spend)")
    p.add_argument("--job-id", help="--url from Higgsfield: the generation's job id (ledgered once per job)")
    p.add_argument("--model", help="--url from Higgsfield: the model that made the still (for the ledger)")
    p.set_defaults(func=cmd_ingest)
    p = leaf(ps, "sheet", "numbered picking sheets -> plates/sheets/pick-NN.jpg")
    p.add_argument("--plates", help="comma-separated plate keys (default: every plate with candidates)")
    p.set_defaults(func=cmd_psheet)
    p = leaf(ps, "pick", "record picks: PLATE K [PLATE K ...] (or \"p001#2, p004#1\") -> plates/picks.json")
    p.add_argument("pairs", nargs="*", help="plate key and candidate number pairs")
    p.add_argument("--all-first", action="store_true", help="pick candidate 1 for every unpicked plate")
    p.set_defaults(func=cmd_pick)
    p = leaf(ps, "vary", "one image per shot: repeated plates get the other candidates; no two clips share a start frame")
    p.add_argument("--dry", action="store_true", help="only show what would change")
    p.set_defaults(func=cmd_vary)
    p = leaf(ps, "status", "per plate: prompt state, candidates, pick, shots")
    p.set_defaults(func=cmd_pstatus)
    p = leaf(ps, "box", "name a region of a plate's picked image (--label 'a face' --uv u,v,w,h, 0..1) so devices can "
                        "anchor to it; no --label lists the plate's boxes")
    p.add_argument("plate")
    p.add_argument("--label", help="what the box is: 'a face', 'the phone', 'subject' (= the lead box)")
    p.add_argument("--uv", help="u,v,w,h in 0..1 of the image (u,v = top-left corner)")
    p.add_argument("--score", type=float, help="optional confidence 0..1")
    p.add_argument("--rm", action="store_true", help="remove the box with this --label")
    p.set_defaults(func=cmd_box)
