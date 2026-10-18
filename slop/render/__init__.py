"""slop render — drive the JS engine (engine/index.html) in headless Chromium and deliver the video.

Commands (slop/render/cli.py): `slop render info | frames | stills | sheet | lyrics | encode | check | vertical | clean`.

Port of the reference pipeline's engine/render.py + tools/flashcheck.py + tools/history_check.py. Intentional changes:
- the page is the shared toolkit engine (engine/index.html) opened with the project's file URL; project data comes from
  <project>/engine/*.js (written by `slop edit export`) and, when one is missing, from the contract JSON files
  (analysis/beats.json, analysis/hits.json, board/shots.json, edit/edl.json, analysis/words.json, plates/picks.json),
  injected into the page before it runs;
- frames are the browser's own JPEG (q .95) written atomically — the original re-encoded them through PIL;
- no remote render host: everything renders locally on CPU (SwiftShader); workers default to min(4, cpus // 2), capped
  by available RAM (~3.5 GiB per worker, 3 GiB kept for Grok's browser);
- `frames --every N` renders every Nth frame (drafts and motion sampling; the original had no sampling option);
- encode adds a `setparams` filter so the BT.709 / sRGB-transfer tags are on the frames as well as the stream, and
  verifies with ffprobe the tags, size, frame count and duration (± 1 frame of the song); a master needs every frame
  from f00000 to the song's end (previews that start later offset the audio to match); the review copy is CRF 20,
  maxrate 8M, `-tune grain` as in the reference pipeline;
- stale frames: render/frames/.inputs.json fingerprints what the frames were drawn from (engine code, project.json,
  the project's data files, injected fallbacks, media sizes/mtimes, size, renderer, time map); `frames` discards and
  redraws stale frames, `encode` refuses them for a master (the original avoided reuse by rendering every cut into a
  new versioned folder);
- missing media / fonts stop `frames`, `stills`, `sheet`, `vertical` (and make `info` ok:false) with the list and the
  fix; `--allow-missing` draws placeholders for previews and `encode` refuses a master from them (the original threw);
- `--timemap` renders the final song's length (the time map's end, else the audio), clipping --to with a warning;
- the lyric gate counts words analysis/words.json could not time (t0 null) as missing; `lyrics` and `sheet` take
  --size / --vertical so the 9:16 layout can be gated; `sheet` and `check` refuse to invent a duration;
- the vertical cut re-renders at 1080×1920 (the engine lays out for portrait); `--method crop` is a fast PREVIEW
  that crops the master frames around the subject from PLATES boxes, written to out/vertical-crop.mp4 (draft);
- ARCHITECTURE §5 calls the lyric gate `slop render lyrics-gate`; the command is `slop render lyrics`;
- delivery for chat (no original counterpart): `encode --share` makes out/share.mp4 — a verified copy of the master
  when the master is current (made from the frames on disk and the song in audio/) and already fits under --max-mib
  (default 190; Grok chat takes ≤ 200 MiB), else a two-pass x264 encode whose bitrate comes from the duration, never
  above the CURRENT master's (an older master is ignored), with the master's colour tags, verified with ffprobe
  including its size; `clean` deletes the frames once the master verifies, never while another job of the project
  runs, and leaves the workflows' render/scratch/ alone (render/clean.py); `check --layers` checks the ≥ 3 ordered
  layers rule on every shot's mid-point (render/layers.py, counted by the engine: ENGINE.frameLayers; chapter code
  declares its own layers with ENGINE.noteLayer) -> render/layers.json, render/layers-vertical.json for 9:16;
  `sheet --chapter X --review` is the chapter review sheet (render/chapter.py); long steps report to
  $SLOP_PROGRESS_FILE (slop/progress.py: only a command's end writes done / stopped / failed);
- memory (measured, full-length film at the box's limits, e2e/INTEGRATION.md §timings-full): the engine page caps its
  decoded-image cache by bytes (core.js, default 320 MiB, SLOP_CACHE_MIB / project.json cache_mib), runs a GC after it
  drops images (Chromium starts with --js-flags=--expose-gc), and refuses no plate when Chromium refuses a decode()
  (several large plates decoding at once); worker defaults follow the CPUs and the cgroup memory limit this process
  actually has (taskset / containers), not the host's, counting the cgroup's page cache as free (it is reclaimable).
Browser: Playwright's bundled Chromium; when it is not installed, the system Chrome (channel "chrome") — set
SLOP_BROWSER_CHANNEL / SLOP_CHROME_PATH / PLAYWRIGHT_BROWSERS_PATH in $SLOP_HOME/env.sh to choose (applied before the
Playwright driver starts; PLAYWRIGHT_BROWSERS_PATH defaults to $SLOP_HOME/ms-playwright when setup.sh put Chromium there).
Licences: Playwright (Apache-2.0) and Chromium (BSD-3-Clause) are runtime tools; the engine ships only SIL OFL 1.1 fonts
(engine/fonts/licenses/); depth maps it draws must come from Depth-Anything-V2-Small (Apache-2.0) — the engine draws
depth only when it is labelled V2-Small and refuses any other model (the Large/Base weights are CC-BY-NC-4.0). No model
runs here; no network calls.
"""
