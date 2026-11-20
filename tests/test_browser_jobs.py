"""Every job is Grok's: the production asks with `slop relay job --kind midjourney|suno|browser|grok-imagine`, Grok
runs it (Grok Imagine on its own tool, Suno through Suno's connector, Midjourney and other sites in its signed-in
browser; skills grok-imagine, suno, midjourney) and the person only decides. The brief, the profile, the relay skill and
the stage guides all say so; nothing tells the person to paste, create or download."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
_spec = importlib.util.spec_from_file_location("build_recipe", SKILLS / "build_recipe.py")
BR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BR)

import test_relay as RT  # noqa: E402  (its fake engine and helpers)
K = RT.K


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_the_relay_takes_midjourney_suno_and_browser_jobs_for_grok(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    rc, out = K.run("relay", "job", "--kind", "midjourney", "--text", "close-up of a woman --ar 16:9 --v 8.2",
                    "--text", "wide shot of a city --ar 16:9 --v 8.2 --p abc123x", "--name", "plates")
    assert rc == 0 and "Grok runs it in its own browser" in out["text"], out
    assert "dropped --v 8.2" in out["text"] and "P button" in out["text"] and "abc123x" not in str(out)
    rc, out = K.run("relay", "job", "--kind", "suno", "--title", "Hook", "--style", "glassy synth pop",
                    "--instrumental")
    assert rc == 0, out
    rc, out = K.run("relay", "job", "--kind", "browser", "--url", "https://example.com",
                    "--note", "check the page title")
    assert rc == 0, out
    rc, r = K.run("relay", "read")
    assert rc == 0
    jobs = {j["job_kind"]: j for j in r["jobs"]}
    assert jobs["midjourney"]["text"] == ["close-up of a woman --ar 16:9", "wide shot of a city --ar 16:9"]
    assert jobs["midjourney"]["personalize"] is True
    assert jobs["midjourney"]["expect_count"] == 8 and jobs["midjourney"]["save"].endswith("midjourney")
    assert jobs["suno"]["style"] == "glassy synth pop" and jobs["suno"]["instrumental"] is True
    assert jobs["browser"]["url"] == "https://example.com"
    nxt = r["grok_next"]
    assert "skill midjourney" in nxt and "skill suno" in nxt and "your browser" in nxt and "the P button on" in nxt
    assert "to the person" not in nxt, "browser work never goes to the person"
    rc, out = K.run("relay", "done", jobs["browser"]["job"], "--note", "the title is Example Domain")
    assert rc == 0, out


def test_the_relay_refuses_incomplete_browser_jobs(tmp_path, monkeypatch):
    RT.setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0
    assert K.run("relay", "job", "--kind", "midjourney")[0] != 0
    assert K.run("relay", "job", "--kind", "suno", "--style", "pop")[0] != 0, "lyrics or --instrumental"
    assert K.run("relay", "job", "--kind", "browser", "--url", "https://example.com")[0] != 0, "a note says what to do"


def test_everyone_knows_browser_work_is_groks():
    brief = read(ROOT / "templates" / "production-brief.md")
    assert "Every job is Grok's" in brief and "--kind midjourney" in brief and "--kind suno" in brief
    assert "Never ask the person to paste, press Create, download" in brief
    assert "person steps" not in brief and "pastes, presses Create" not in brief
    prof = read(SKILLS / "profile.md")
    assert "Every job is yours" in prof and "midjourney, suno" in prof and "Suno: its connector" in prof
    relay = read(SKILLS / "claudia-relay" / "SKILL.md")
    assert "Each job in `jobs` is yours, never the person's." in relay
    for s in ("midjourney", "suno"):
        assert s in BR.ORDER and "never type a password" in read(SKILLS / s / "SKILL.md").lower()
    for f in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), SKILLS / "song" / "SKILL.md",
              SKILLS / "plates" / "SKILL.md"]:
        text = read(f)
        assert not re.search(r"(?i)never automated|owner presses Create|user presses Create|owner pastes|"
                             r"person pastes|you paste the", text), f.name
