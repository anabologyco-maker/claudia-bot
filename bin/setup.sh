#!/usr/bin/env bash
# setup.sh - idempotent Claudia installer. Everything goes under $SLOP_HOME; it never uses apt or sudo.
#
#   bash bin/setup.sh                 install/repair the profile installed last time (minimal on first run)
#   bash bin/setup.sh --minimal       numpy pillow requests soundfile scipy cmudict playwright==1.60.0 (+ chromium, cloudflared)
#   bash bin/setup.sh --full          minimal + CPU torch/torchaudio/torchvision 2.11, demucs 4.1.0,
#                                     transformers 5.17.*, librosa 1.0.0, opencv-python-headless, safetensors,
#                                     accelerate, wordfreq + the raw CMU Pronouncing Dictionary (lyric lint)
#                                     + earshot (the production's ears: its newest commit and its two models)
#   bash bin/setup.sh --check [--json]   report what is missing; installs nothing, writes nothing
#   bash bin/setup.sh --cloudflared      only (re)install cloudflared into $SLOP_HOME/bin (REQUIRED for OpenRouter sung
#                                     clips, Higgsfield media_import_url and the tap app; no venv needed)
#   options: --dev (adds pytest)  --no-browser  --no-cloudflared  -h|--help
#
# $SLOP_HOME defaults to /workspace/.claudia on the Grok Bot computer (where /workspace survives computer updates,
# which remove installed apps and packages) and to ~/.claudia elsewhere. Re-run this script after any computer
# update or reset: it re-checks every piece and only downloads what is missing. On the Grok Bot computer it also puts
# back the one line in ~/.bashrc and ~/.profile that loads env.sh (a reset clears the home folder).
#
# What it installs (all under $SLOP_HOME):
#   bin/uv            uv package manager (GitHub release, SHA-256 checked against its published .sha256; fallback:
#                     the PyPI wheel; last resort: a uv already on PATH)
#   python/           Python 3.13 managed by uv (python-build-standalone), so the venv survives system upgrades
#   venv/             the claudia virtualenv; this repo installed editable (`--no-deps`)
#   ms-playwright/    Playwright's chromium (fallback: the system google-chrome via channel="chrome")
#   bin/cloudflared   Cloudflare quick-tunnel binary (GitHub release, SHA-256 checked against the digest the GitHub
#                     API publishes for the asset; else a cloudflared already on PATH is linked) - the quick tunnel
#                     for OpenRouter sung clips (HTTPS audio), Higgsfield media_import_url and the phone tap app
#   cache/{hf,torch,uv}   model weights (HF_HOME) and download caches
#   cache/cmudict/cmudict.dict   (--full) CMU Pronouncing Dictionary, raw data, BSD-2-Clause (the GPL `cmudict` PyPI
#                     wrapper is not used); wordfreq: code Apache-2.0, data CC-BY-SA 4.0 (used locally only)
#   vendor/earshot    (--full) earshot (MIT, github.com/Leonxlnx/earshot; the PyPI name is another project), installed
#                     into the venv; its models (CLAP Apache-2.0, AST BSD-3, ~1.4 GB) in cache/earshot. Optional: a
#                     failed fetch only warns
#   env.sh            PATH, HF_HOME, SLOP_* (NO secrets) - `. $SLOP_HOME/env.sh` in a shell, or call $SLOP_HOME/bin/slop
#   bin/slop          the CLI shim
#
# torch is pinned on EVERY pip line (an unpinned install once upgraded torch under the pipeline).
# Overrides: SLOP_HOME, SLOP_PROJECTS, SLOP_PYTHON_VERSION (3.13), SLOP_TORCH_INDEX, SLOP_UV_VERSION,
#            SLOP_CLOUDFLARED_VERSION (default: latest releases, verified by checksum).
# Needs bash 4.4+ (Linux; on macOS install a newer bash first). Installs only under $SLOP_HOME; a headless browser
# launch at render time may still write a font cache under ~/.cache (setup's own launches use $SLOP_HOME/cache).
# Needs LF line endings in bin/ and runner/ scripts (a Windows checkout or editor can turn them into CRLF): this file
# refuses to run with CRLF (the next line works even then), and --check / the install check bin/slop and the rest.
case "$(tr -dc '\015' <"${BASH_SOURCE:-$0}" 2>/dev/null | wc -c)" in *[1-9]*) printf '%s\n' "setup.sh: this file has Windows (CRLF) line endings, so bash cannot run it. In the toolkit folder run:  sed -i 's/\\r\$//' bin/setup.sh bin/slop   then again:  bash bin/setup.sh" >&2; exit 2;; esac #
if [ -z "${BASH_VERSION:-}" ]; then
  echo "setup.sh: run it with bash:  bash bin/setup.sh" >&2
  exit 2
fi
if [ "${BASH_VERSINFO[0]}" -lt 4 ] || { [ "${BASH_VERSINFO[0]}" -eq 4 ] && [ "${BASH_VERSINFO[1]}" -lt 4 ]; }; then
  echo "setup.sh: needs bash 4.4 or newer (this is bash $BASH_VERSION). macOS ships bash 3.2: install a newer" \
       "bash (e.g. brew install bash) and run setup.sh with it" >&2
  exit 2
fi
set -Eeuo pipefail

PROFILE=""; CHECK=0; JSON=0; DEV=0; NO_BROWSER=0; NO_CF=0; CF_ONLY=0
usage() { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"; }
for a in "$@"; do
  case "$a" in
    --minimal) PROFILE=minimal ;;
    --full) PROFILE=full ;;
    --check) CHECK=1 ;;
    --json) JSON=1 ;;
    --dev) DEV=1 ;;
    --no-browser) NO_BROWSER=1 ;;
    --no-cloudflared) NO_CF=1 ;;
    --cloudflared) CF_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "setup.sh: unknown option '$a' (see: bash bin/setup.sh --help)" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
on_box() { [ -d /workspace ] && [ "${HOME:-}" = "/home/box" ]; }
if [ -z "${SLOP_HOME:-}" ]; then
  if on_box; then SLOP_HOME=/workspace/.claudia; else SLOP_HOME="$HOME/.claudia"; fi
fi
if [ -z "${SLOP_PROJECTS:-}" ]; then
  if on_box; then SLOP_PROJECTS=/workspace/slop/projects; else SLOP_PROJECTS="$HOME/slop/projects"; fi
fi
case "$SLOP_HOME$SLOP_PROJECTS$REPO" in
  *'"'*|*'$'*|*'`'*|*'\'*) echo "setup.sh: paths must not contain quotes, \$, backticks or backslashes" >&2; exit 2 ;;
esac

BIN="$SLOP_HOME/bin"; VENV="$SLOP_HOME/venv"; PY="$VENV/bin/python"; UV="$BIN/uv"
PYVER="${SLOP_PYTHON_VERSION:-3.13}"
TORCH_V=2.11.0; TORCHAUDIO_V=2.11.0; TORCHVISION_V=0.26.0
TORCH_INDEX="${SLOP_TORCH_INDEX:-https://download.pytorch.org/whl/cpu}"
PLAYWRIGHT_V=1.60.0
MINIMAL_PKGS=(numpy pillow requests soundfile scipy cmudict "playwright==$PLAYWRIGHT_V")
FULL_PKGS=("demucs==4.1.0" "transformers==5.17.*" "librosa==1.0.0" opencv-python-headless safetensors accelerate
           "wordfreq>=3.1,<4")
MINIMAL_MODS=(numpy PIL requests soundfile scipy cmudict playwright)
FULL_MODS=(torch torchaudio torchvision demucs transformers librosa cv2 safetensors accelerate wordfreq)
CMU_URL="https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"   # BSD-2-Clause data
EARSHOT_URL="https://github.com/Leonxlnx/earshot"
EARSHOT_DIR="$SLOP_HOME/vendor/earshot"; EARSHOT_HOME="$SLOP_HOME/cache/earshot"
CMU_FILE="$SLOP_HOME/cache/cmudict/cmudict.dict"; CMU_MIN_BYTES=1000000

export UV_PYTHON_INSTALL_DIR="$SLOP_HOME/python" UV_PYTHON_BIN_DIR="$SLOP_HOME/python/bin"
export UV_CACHE_DIR="$SLOP_HOME/cache/uv" UV_NO_PROGRESS=1
export PLAYWRIGHT_BROWSERS_PATH="$SLOP_HOME/ms-playwright" HF_HOME="$SLOP_HOME/cache/hf"
export TORCH_HOME="$SLOP_HOME/cache/torch"
unset VIRTUAL_ENV || true

if [ -z "$PROFILE" ]; then
  PROFILE="$(cat "$SLOP_HOME/profile" 2>/dev/null || true)"
  case "$PROFILE" in minimal|full) ;; *) PROFILE=minimal ;; esac
fi

OS="$(uname -s)"; ARCH="$(uname -m)"; TORCH_LOCAL=""
case "$OS-$ARCH" in
  Linux-x86_64) UV_TRIPLE=x86_64-unknown-linux-gnu; CF_ASSET=cloudflared-linux-amd64; TORCH_LOCAL="+cpu" ;;
  Linux-aarch64|Linux-arm64) UV_TRIPLE=aarch64-unknown-linux-gnu; CF_ASSET=cloudflared-linux-arm64 ;;
  Darwin-arm64) UV_TRIPLE=aarch64-apple-darwin; CF_ASSET=cloudflared-darwin-arm64.tgz ;;
  Darwin-x86_64) UV_TRIPLE=x86_64-apple-darwin; CF_ASSET=cloudflared-darwin-amd64.tgz ;;
  *) echo "setup.sh: unsupported platform $OS-$ARCH (the Grok Bot computer is Linux x86_64)" >&2; exit 2 ;;
esac

log() { printf '[setup] %s\n' "$*"; }
warn() { printf '[setup] WARNING: %s\n' "$*" >&2; }
die() { printf '[setup] ERROR: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
runs() { "$@" >/dev/null 2>&1; }   # true if the command runs successfully
with_timeout() { local s="$1"; shift; if have timeout; then timeout "$s" "$@"; else "$@"; fi; }

fetch() {  # fetch URL OUTFILE  (curl, else wget, else python3)
  local url="$1" out="$2"
  if have curl; then
    curl -fsSL --connect-timeout 15 --max-time 900 --retry 3 --retry-delay 2 -o "$out" "$url"
  elif have wget; then
    wget -q -T 30 -t 3 -O "$out" "$url"
  elif have python3; then
    python3 -c 'import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$url" "$out"
  else
    return 1
  fi
}

sha256_of() {  # sha256_of FILE -> lowercase hex on stdout
  if have sha256sum; then sha256sum "$1" | awk '{print $1}'
  elif have shasum; then shasum -a 256 "$1" | awk '{print $1}'
  elif have python3; then python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"
  else return 1; fi
}

checksum_state() {  # checksum_state FILE "TEXT WITH THE EXPECTED HEX" -> prints ok | mismatch | unknown (always rc 0)
  local want got
  want="$(printf '%s' "$2" | tr 'A-F' 'a-f' | grep -oE '[0-9a-f]{64}' | head -n1 || true)"
  got="$(sha256_of "$1" 2>/dev/null || true)"
  if [ -z "$want" ] || [ -z "$got" ]; then echo unknown
  elif [ "$want" = "$got" ]; then echo ok
  else echo mismatch; fi
}

cmu_ok() { [ -f "$CMU_FILE" ] && [ "$(wc -c <"$CMU_FILE" 2>/dev/null || echo 0)" -ge "$CMU_MIN_BYTES" ]; }

earshot_fetch() {  # the newest earshot into $EARSHOT_DIR (a clone, then fast-forwards); 1 if there is none to install
  have git || { warn "earshot needs git"; [ -f "$EARSHOT_DIR/pyproject.toml" ]; return; }
  if [ -d "$EARSHOT_DIR/.git" ]; then
    GIT_TERMINAL_PROMPT=0 with_timeout 300 git -C "$EARSHOT_DIR" pull -q --ff-only ||
      warn "could not update earshot ($EARSHOT_URL): keeping the copy installed before"
  else
    rm -rf "$EARSHOT_DIR"; mkdir -p "$(dirname "$EARSHOT_DIR")"
    GIT_TERMINAL_PROMPT=0 with_timeout 300 git clone -q --depth 1 "$EARSHOT_URL" "$EARSHOT_DIR" ||
      { warn "could not fetch earshot ($EARSHOT_URL: github.com blocked?)"; rm -rf "$EARSHOT_DIR"; return 1; }
  fi
  [ -f "$EARSHOT_DIR/pyproject.toml" ]
}

reachable() {  # reachable URL -> 0 if any HTTP answer within 10 s
  local url="$1"
  if have curl; then
    local code; code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$url" 2>/dev/null || true)"
    [ -n "$code" ] && [ "$code" != "000" ]
  else
    python3 -c 'import sys,urllib.request,urllib.error
try: urllib.request.urlopen(sys.argv[1], timeout=10)
except urllib.error.HTTPError: pass
' "$url" >/dev/null 2>&1
  fi
}

py_mods_missing() {  # py_mods_missing MOD... -> prints the ones that do not import with $PY
  [ -x "$PY" ] || { printf '%s\n' "$@"; return 0; }
  "$PY" -I - "$@" <<'EOF' 2>/dev/null || printf '%s\n' "$@"
import importlib, sys
for m in sys.argv[1:]:
    try:
        importlib.import_module(m)
    except Exception:
        print(m)
EOF
}

venv_ok() {  # the venv python runs, is $PYVER, and its base interpreter lives under $SLOP_HOME/python
  [ -x "$PY" ] || return 1
  "$PY" - "$PYVER" "$SLOP_HOME/python" <<'EOF' >/dev/null 2>&1
import os, sys
want, managed = sys.argv[1], os.path.realpath(sys.argv[2])
ok = "%d.%d" % sys.version_info[:2] == want and os.path.realpath(sys.base_prefix).startswith(managed + os.sep)
sys.exit(0 if ok else 1)
EOF
}

# -I: a slop/ folder where this runs (the projects folder /workspace/slop on the box) must not stand in for the package
editable_ok() {
  [ -x "$PY" ] || return 1
  local f; f="$("$PY" -I -c 'import slop, os; print(os.path.realpath(slop.__file__))' 2>/dev/null)" || return 1
  case "$f" in "$(cd "$REPO" && pwd -P)"/*) return 0 ;; *) return 1 ;; esac
}

installed_from() {  # the checkout the venv's slop package runs from (nothing: not installed)
  [ -x "$PY" ] || return 0
  "$PY" -I -c 'import slop, os; print(os.path.dirname(os.path.dirname(os.path.realpath(slop.__file__))))' \
    2>/dev/null || true
}

shell_rc_ok() {  # new shells load env.sh (on the box a computer reset clears the home folder, and with it this line)
  grep -qsF "$SLOP_HOME/env.sh" "$HOME/.bashrc" && grep -qsF "$SLOP_HOME/env.sh" "$HOME/.profile"
}

shell_rc_fix() {  # puts the line back where it is missing (the box: every setup run, so after every reset)
  local rc
  for rc in "$HOME/.bashrc" "$HOME/.profile"; do
    grep -qsF "$SLOP_HOME/env.sh" "$rc" || { printf '. "%s/env.sh"\n' "$SLOP_HOME" >>"$rc" && log "PATH: $rc loads env.sh again"; }
  done
}

torch_installed_version() {
  [ -x "$PY" ] || return 0
  "$PY" -c 'import importlib.metadata as m, sys
for p in sys.argv[1:]:
    try: print(p + "==" + m.version(p))
    except Exception: pass' torch torchaudio torchvision 2>/dev/null || true
}

browser_launch() {  # browser_launch chromium|chrome -> 0 if headless launch works; logs the reason if not
  [ -x "$PY" ] || return 1
  local kw='{"headless": true}' out reason
  [ "$1" = chrome ] && kw='{"headless": true, "channel": "chrome"}'
  if out="$(export XDG_CACHE_HOME="$SLOP_HOME/cache"; with_timeout 120 "$PY" - "$kw" 2>&1 <<'EOF'
import json, sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(**json.loads(sys.argv[1]))
    b.new_page().set_content("<p>ok</p>")
    b.close()
EOF
)"; then
    return 0
  fi
  reason="$(printf '%s\n' "$out" | grep -m1 -oE "error while loading shared libraries: [^:]+|Executable doesn't exist at [^ ]+|Chromium distribution 'chrome' is not found|Host system is missing dependencies" || true)"
  [ -n "$reason" ] || reason="$(printf '%s\n' "$out" | grep -v -e cleanup -e '^ *$' | tail -n1)"
  warn "$1 does not launch: $reason"
  return 1
}

system_chrome() { for c in google-chrome google-chrome-stable chrome; do have "$c" && { command -v "$c"; return 0; }; done; return 1; }

crlf_files() {  # the repo scripts that must have LF endings but contain CR (relative paths, one per line)
  local f
  for f in "$REPO"/bin/* "$REPO"/runner/*.mjs; do
    [ -f "$f" ] || continue
    case "$f" in *.sh|*/bin/slop|*.mjs) ;; *) continue ;; esac
    if LC_ALL=C grep -q $'\r' "$f" 2>/dev/null; then printf '%s\n' "${f#"$REPO"/}"; fi
  done
}

# =========================================================================== cloudflared (step 5, and --cloudflared)
CF_NEED="cloudflared is REQUIRED for OpenRouter sung clips (the song window goes to OpenRouter as an HTTPS URL through the quick tunnel), for Higgsfield media_import_url of plates and windows, and for the phone tap app"
install_cloudflared() {  # install $BIN/cloudflared when it is missing or broken; returns 0 when it runs afterwards
  if [ -x "$BIN/cloudflared" ] && runs "$BIN/cloudflared" --version; then
    log "cloudflared present: $("$BIN/cloudflared" --version 2>&1 | head -n1)"
    return 0
  fi
  local tmp cf_api cf_tag cf_digest cf_state cf_meta cf_url jpy sys_cf
  mkdir -p "$BIN"
  tmp="$(mktemp -d)"
  # the release tag + the asset's SHA-256 digest from the GitHub API, so the binary can be verified
  cf_api="https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
  if [ -n "${SLOP_CLOUDFLARED_VERSION:-}" ]; then
    cf_api="https://api.github.com/repos/cloudflare/cloudflared/releases/tags/$SLOP_CLOUDFLARED_VERSION"
  fi
  cf_tag="${SLOP_CLOUDFLARED_VERSION:-}"; cf_digest=""; cf_state=""; cf_meta=""
  jpy=python3; [ -x "$PY" ] && jpy="$PY"   # --cloudflared runs before (or without) the venv
  if fetch "$cf_api" "$tmp/rel.json" 2>/dev/null; then
    cf_meta="$("$jpy" -c 'import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
a = next((x for x in d.get("assets", []) if x.get("name") == sys.argv[2]), {})
print(d.get("tag_name") or "-", (a.get("digest") or "").replace("sha256:", "") or "-")' "$tmp/rel.json" "$CF_ASSET" 2>/dev/null || true)"
    case "$cf_meta" in
      *" "*)
        if [ "${cf_meta%% *}" != "-" ]; then cf_tag="${cf_meta%% *}"; fi
        if [ "${cf_meta##* }" != "-" ]; then cf_digest="${cf_meta##* }"; fi ;;
    esac
  fi
  if [ -n "$cf_tag" ]; then
    cf_url="https://github.com/cloudflare/cloudflared/releases/download/$cf_tag/$CF_ASSET"
  else
    cf_url="https://github.com/cloudflare/cloudflared/releases/latest/download/$CF_ASSET"
  fi
  log "downloading cloudflared: $cf_url"
  if fetch "$cf_url" "$tmp/cf"; then
    cf_state="$(checksum_state "$tmp/cf" "$cf_digest")"
    case "$cf_state" in
      ok) log "cloudflared SHA-256 matches the release digest" ;;
      mismatch) warn "the cloudflared download does not match the release's SHA-256 digest: not installing it (re-run later)"; rm -f "$tmp/cf" ;;
      *) warn "could not verify cloudflared (GitHub API unreachable or no digest); installing it unverified" ;;
    esac
  fi
  if [ -f "$tmp/cf" ]; then
    rm -f "$BIN/cloudflared"
    case "$CF_ASSET" in
      *.tgz) tar -xzf "$tmp/cf" -C "$tmp" && install -m 0755 "$tmp/cloudflared" "$BIN/cloudflared" ;;
      *) install -m 0755 "$tmp/cf" "$BIN/cloudflared" ;;
    esac
    if runs "$BIN/cloudflared" --version; then log "cloudflared installed: $("$BIN/cloudflared" --version 2>&1 | head -n1)"
    else warn "cloudflared downloaded but does not run"; fi
  elif [ "$cf_state" != mismatch ]; then
    warn "cloudflared download failed (github.com blocked?)"
  fi
  rm -rf "$tmp"
  if ! { [ -x "$BIN/cloudflared" ] && runs "$BIN/cloudflared" --version; }; then
    sys_cf="$(command -v cloudflared 2>/dev/null || true)"   # last resort: one already on PATH (lost on a computer update)
    if [ -n "$sys_cf" ] && [ "$sys_cf" != "$BIN/cloudflared" ] && runs "$sys_cf" --version; then
      rm -f "$BIN/cloudflared"; ln -s "$sys_cf" "$BIN/cloudflared"
      log "using the cloudflared already on PATH: $sys_cf (linked into $BIN; re-run setup after a computer update)"
    fi
  fi
  [ -x "$BIN/cloudflared" ] && runs "$BIN/cloudflared" --version
}

if [ "$CF_ONLY" = 1 ] && [ "$CHECK" = 0 ]; then   # bash bin/setup.sh --cloudflared: only this piece
  if install_cloudflared; then
    log "cloudflared ready: $BIN/cloudflared - test the tunnel with: slop gen tunnel start"
    exit 0
  fi
  die "cloudflared could not be installed. $CF_NEED. Check that github.com is reachable, then re-run: bash $REPO/bin/setup.sh --cloudflared"
fi

# =========================================================================== --check
if [ "$CHECK" = 1 ]; then
  ITEMS=(); MISSING=()
  item() { ITEMS+=("$1|$2|$3"); [ "$2" = ok ] || [ "$2" = optional ] || MISSING+=("$1"); }
  crlf="$(crlf_files | tr '\n' ' ')"
  if [ -z "${crlf// /}" ]; then item line-endings ok "LF in the bin/ and runner/ scripts"
  else item line-endings missing "Windows (CRLF) line endings in: ${crlf% } - fix: cd $REPO && sed -i 's/\r\$//' ${crlf% }"; fi
  if [ -x "$UV" ] && runs "$UV" --version; then item uv ok "$("$UV" --version 2>/dev/null)"; else item uv missing "no $UV"; fi
  if venv_ok; then item python ok "$("$PY" -V 2>&1) (uv-managed, in $VENV)"
  elif [ -x "$PY" ]; then item python missing "$VENV exists but is not Python $PYVER from $SLOP_HOME/python (setup recreates it)"
  else item python missing "no venv at $VENV"; fi
  m="$(py_mods_missing "${MINIMAL_MODS[@]}" | tr '\n' ' ')"
  if [ -z "${m// /}" ]; then item deps:minimal ok "${MINIMAL_MODS[*]}"; else item deps:minimal missing "$m"; fi
  if [ "$PROFILE" = full ]; then
    m="$(py_mods_missing "${FULL_MODS[@]}" | tr '\n' ' ')"
    if [ -z "${m// /}" ]; then item deps:full ok "${FULL_MODS[*]}"; else item deps:full missing "$m"; fi
    if cmu_ok; then item cmudict ok "$CMU_FILE"; else item cmudict missing "no CMU dictionary at $CMU_FILE (lyric lint)"; fi
    if [ -z "$(py_mods_missing earshot)" ]; then item earshot ok "the production's ears ($EARSHOT_DIR)"
    else item earshot optional "earshot not installed (the production's ears; setup.sh --full fetches it from $EARSHOT_URL)"; fi
  fi
  if editable_ok; then item claudia ok "editable install of $REPO"
  elif [ -n "$(installed_from)" ]; then item claudia missing "the venv runs claudia from $(installed_from), not $REPO (setup.sh from this folder switches it)"
  else item claudia missing "repo not installed in the venv"; fi
  if [ "$NO_BROWSER" = 0 ]; then
    bstate="$(sed -n 's/^export SLOP_BROWSER="\([a-z]*\)"$/\1/p' "$SLOP_HOME/env.sh" 2>/dev/null || true)"
    if [ "$bstate" = none ]; then item browser missing "no browser launched at the last setup (SLOP_BROWSER=none; slop doctor shows why)"
    elif [ "$bstate" = chrome ] && system_chrome >/dev/null; then item browser ok "system chrome ($(system_chrome))"
    elif ls -d "$PLAYWRIGHT_BROWSERS_PATH"/chromium-* >/dev/null 2>&1; then item browser ok "playwright chromium in $PLAYWRIGHT_BROWSERS_PATH"
    else item browser missing "no chromium under $PLAYWRIGHT_BROWSERS_PATH"; fi
  fi
  if [ "$NO_CF" = 0 ]; then
    if [ -x "$BIN/cloudflared" ] && runs "$BIN/cloudflared" --version; then item cloudflared ok "$BIN/cloudflared"
    else item cloudflared missing "no $BIN/cloudflared (REQUIRED for OpenRouter sung clips and the tap app; install only it: bash $REPO/bin/setup.sh --cloudflared)"; fi
  fi
  if [ -f "$SLOP_HOME/env.sh" ] && [ -x "$BIN/slop" ]; then item env ok "$SLOP_HOME/env.sh + $BIN/slop"
  else item env missing "env.sh or the slop shim not written"; fi
  if on_box; then
    if shell_rc_ok; then item shell ok "~/.bashrc and ~/.profile load $SLOP_HOME/env.sh"
    else item shell missing "~/.bashrc or ~/.profile no longer loads $SLOP_HOME/env.sh (a computer reset clears the home folder; setup.sh puts the line back)"; fi
  fi
  if have ffmpeg; then item ffmpeg ok "$(ffmpeg -hide_banner -version 2>/dev/null | head -n1) (system; setup does not install it)"
  else item ffmpeg missing "ffmpeg not on PATH (the Grok Bot computer ships it; elsewhere install ffmpeg with libx264)"; fi

  if [ "$JSON" = 1 ]; then
    jpy=python3; [ -x "$PY" ] && jpy="$PY"
    "$jpy" - "$SLOP_HOME" "$PROFILE" "${ITEMS[@]}" <<'EOF' 2>/dev/null || { echo '{"ok": false, "error": "python3 needed for --json"}'; }
import json, sys
home, prof, items = sys.argv[1], sys.argv[2], sys.argv[3:]
rows = [dict(zip(("name", "status", "detail"), it.split("|", 2))) for it in items]
miss = [r["name"] for r in rows if r["status"] not in ("ok", "optional")]
opt = [r["name"] for r in rows if r["status"] == "optional"]
print(json.dumps({"ok": not miss, "slop_home": home, "profile": prof, "missing": miss, "optional": opt,
                  "items": rows}))
EOF
  else
    echo "claudia setup check - SLOP_HOME=$SLOP_HOME profile=$PROFILE"
    for it in "${ITEMS[@]}"; do
      IFS='|' read -r n s d <<<"$it"
      if [ "$s" = ok ]; then printf '  ok       %-13s %s\n' "$n" "$d"
      elif [ "$s" = optional ]; then printf '  optional %-13s %s\n' "$n" "$d"
      else printf '  MISSING  %-13s %s\n' "$n" "$d"; fi
    done
    if [ "${#MISSING[@]}" -eq 0 ]; then echo "nothing missing"; else echo "missing: ${MISSING[*]}  ->  run: bash $REPO/bin/setup.sh --$PROFILE"; fi
  fi
  [ "${#MISSING[@]}" -eq 0 ]
  exit $?
fi

# =========================================================================== install
crlf="$(crlf_files | tr '\n' ' ')"
if [ -n "${crlf// /}" ]; then  # checked before anything is written: a CRLF shim or runner fails later on Linux
  die "Windows (CRLF) line endings in: ${crlf% } - they fail on Linux. Fix: cd $REPO && sed -i 's/\r\$//' ${crlf% }   then re-run: bash bin/setup.sh"
fi
mkdir -p "$BIN" "$SLOP_HOME/cache/hf" "$SLOP_HOME/cache/torch" "$SLOP_HOME/cache/uv" "$SLOP_PROJECTS"
LOG="$SLOP_HOME/setup.log"
exec > >(tee -a "$LOG") 2>&1
trap 'echo "[setup] FAILED at line $LINENO: $BASH_COMMAND - see $LOG; fix the cause and re-run (it resumes)" >&2' ERR
if have flock; then
  exec 9>"$SLOP_HOME/.setup.lock"
  flock -n 9 || die "another setup.sh is running for $SLOP_HOME; wait for it to finish"
fi
log "$(date -u '+%Y-%m-%d %H:%M UTC') SLOP_HOME=$SLOP_HOME profile=$PROFILE repo=$REPO"
need_gb=2; [ "$PROFILE" = full ] && need_gb=8
free_kb="$(df -Pk "$SLOP_HOME" 2>/dev/null | awk 'NR==2 {print $4}' || true)"
case "$free_kb" in
  ''|*[!0-9]*) ;;
  *) [ "$free_kb" -lt $((need_gb * 1024 * 1024)) ] && warn "only $((free_kb / 1024)) MB free under $SLOP_HOME; the $PROFILE profile needs ~$need_gb GB" ;;
esac

# ---- 1. uv
install_uv() {
  local tmp; tmp="$(mktemp -d)"
  local url
  if [ -n "${SLOP_UV_VERSION:-}" ]; then
    url="https://github.com/astral-sh/uv/releases/download/$SLOP_UV_VERSION/uv-$UV_TRIPLE.tar.gz"
  else
    url="https://github.com/astral-sh/uv/releases/latest/download/uv-$UV_TRIPLE.tar.gz"
  fi
  log "downloading uv: $url"
  if fetch "$url" "$tmp/uv.tgz"; then
    local sumtxt="" state
    if fetch "$url.sha256" "$tmp/uv.sha256" 2>/dev/null; then sumtxt="$(cat "$tmp/uv.sha256")"; fi
    state="$(checksum_state "$tmp/uv.tgz" "$sumtxt")"
    case "$state" in
      ok) log "uv SHA-256 matches $url.sha256" ;;
      mismatch) rm -rf "$tmp"; die "the uv download does not match its published SHA-256 ($url.sha256); not installing it. Re-run later." ;;
      *) warn "could not verify the uv download (no $url.sha256 or no sha256 tool); installing it unverified" ;;
    esac
  fi
  if [ -f "$tmp/uv.tgz" ] && tar -xzf "$tmp/uv.tgz" -C "$tmp" && [ -f "$tmp/uv-$UV_TRIPLE/uv" ]; then
    install -m 0755 "$tmp/uv-$UV_TRIPLE/uv" "$UV"
    [ -f "$tmp/uv-$UV_TRIPLE/uvx" ] && install -m 0755 "$tmp/uv-$UV_TRIPLE/uvx" "$BIN/uvx"
    rm -rf "$tmp"; return 0
  fi
  warn "GitHub download of uv failed; trying the PyPI wheel"
  if have python3 && python3 - "$UV" "$UV_TRIPLE" "${SLOP_UV_VERSION:-}" <<'EOF'
import io, json, os, sys, urllib.request, zipfile
dest, triple, ver = sys.argv[1], sys.argv[2], sys.argv[3]
meta = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/uv/{ver + '/' if ver else ''}json", timeout=30))
arch = "x86_64" if triple.startswith("x86_64") else ("aarch64" if "linux" in triple else "arm64")
plat = "manylinux" if "linux" in triple else "macosx"
files = [f for f in meta["urls"] if f["filename"].endswith(".whl") and plat in f["filename"] and arch in f["filename"]]
if not files:
    sys.exit("no matching uv wheel")
data = urllib.request.urlopen(files[0]["url"], timeout=300).read()
z = zipfile.ZipFile(io.BytesIO(data))
name = next(n for n in z.namelist() if n.endswith("/scripts/uv"))
with open(dest, "wb") as f:
    f.write(z.read(name))
os.chmod(dest, 0o755)
EOF
  then rm -rf "$tmp"; return 0; fi
  rm -rf "$tmp"
  if have uv; then
    warn "PyPI fallback failed too; copying the uv already on PATH ($(command -v uv))"
    install -m 0755 "$(command -v uv)" "$UV"; return 0
  fi
  return 1
}
if [ -x "$UV" ] && runs "$UV" --version; then
  log "uv present: $("$UV" --version)"
else
  install_uv || die "cannot get uv: github.com and pypi.org unreachable. Allow github.com (or pypi.org) and re-run."
  log "uv installed: $("$UV" --version)"
fi

# ---- 2. Python + venv
log "ensuring Python $PYVER (uv-managed, in $SLOP_HOME/python)"
NO_BIN=(); "$UV" python install --help 2>/dev/null | grep -q -- '--no-bin' && NO_BIN=(--no-bin)  # no shims outside $SLOP_HOME
"$UV" python install "${NO_BIN[@]}" "$PYVER" || die "uv could not install Python $PYVER (needs github.com for python-build-standalone)"
if venv_ok; then
  log "venv ok: $("$PY" -V 2>&1)"
else
  case "$VENV" in */venv) ;; *) die "refusing to recreate unexpected venv path $VENV" ;; esac
  [ -e "$VENV" ] && log "recreating $VENV (missing, broken or not on the managed Python)"
  rm -rf "$VENV"
  "$UV" venv --python-preference only-managed --python "$PYVER" "$VENV"
fi

# ---- 3. packages (torch pinned on every line)
INDEX_ARGS=(); TORCH_PINS=(); TORCH_SOURCE=none
if [ "$PROFILE" = full ]; then
  if reachable "$TORCH_INDEX/torch/"; then
    TORCH_PINS=("torch==$TORCH_V$TORCH_LOCAL" "torchaudio==$TORCHAUDIO_V$TORCH_LOCAL" "torchvision==$TORCHVISION_V$TORCH_LOCAL")
    INDEX_ARGS=(--extra-index-url "$TORCH_INDEX" --index-strategy unsafe-best-match)
    TORCH_SOURCE=cpu-index
  else
    warn "$TORCH_INDEX is unreachable: installing torch $TORCH_V from PyPI instead (Linux PyPI wheels pull the large"
    warn "CUDA libraries - several GB, still runs on CPU). Allow download.pytorch.org to get the small CPU build."
    TORCH_PINS=("torch==$TORCH_V" "torchaudio==$TORCHAUDIO_V" "torchvision==$TORCHVISION_V")
    TORCH_SOURCE=pypi
  fi
else
  mapfile -t TORCH_PINS < <(torch_installed_version)
  if [ "${#TORCH_PINS[@]}" -gt 0 ]; then
    TORCH_SOURCE=existing
    case "${TORCH_PINS[*]}" in *+cpu*) INDEX_ARGS=(--extra-index-url "$TORCH_INDEX" --index-strategy unsafe-best-match) ;; esac
  fi
fi
uvpip() { "$UV" pip install --python "$PY" "${INDEX_ARGS[@]}" "$@" "${TORCH_PINS[@]}"; }

log "installing minimal packages: ${MINIMAL_PKGS[*]} ${TORCH_PINS[*]}"
uvpip "${MINIMAL_PKGS[@]}"
if [ "$PROFILE" = full ]; then
  log "installing full packages: ${FULL_PKGS[*]} ${TORCH_PINS[*]}"
  uvpip "${FULL_PKGS[@]}"
fi
if [ "$PROFILE" = full ]; then  # the production's ears; optional, so a failure only warns
  log "installing earshot, the newest from $EARSHOT_URL (describe, critique, timeline for the production)"
  if earshot_fetch && uvpip --reinstall-package earshot "$EARSHOT_DIR[mcp]"; then
    if [ -n "$(ls -A "$EARSHOT_HOME/hf" 2>/dev/null)" ]; then log "earshot models present: $EARSHOT_HOME/hf"
    elif EARSHOT_HOME="$EARSHOT_HOME" with_timeout 1800 "$PY" -m earshot doctor --load >/dev/null 2>&1; then
      log "earshot models downloaded (~1.4 GB): $EARSHOT_HOME/hf"
    else warn "earshot's models did not download: they download on its first use"; fi
  else
    warn "earshot did not install: the production works without its ears (re-run: bash $REPO/bin/setup.sh --full)"
  fi
fi
if [ "$DEV" = 1 ]; then
  log "installing dev tools: pytest"
  uvpip pytest
fi
if [ "$PROFILE" = full ]; then  # lyric lint pronunciations (BSD-2 data; the audio module also fetches it on first use)
  if cmu_ok; then
    log "CMU dictionary present: $CMU_FILE"
  else
    mkdir -p "$(dirname "$CMU_FILE")"
    if fetch "$CMU_URL" "$CMU_FILE.tmp" && [ "$(wc -c <"$CMU_FILE.tmp")" -ge "$CMU_MIN_BYTES" ]; then
      mv -f "$CMU_FILE.tmp" "$CMU_FILE"; log "CMU dictionary downloaded: $CMU_FILE"
    else
      rm -f "$CMU_FILE.tmp"
      warn "could not download the CMU dictionary ($CMU_URL): lyric lint guesses pronunciations from spelling until it can"
    fi
  fi
fi
if editable_ok && [ -x "$VENV/bin/slop" ]; then
  log "this repo is already installed (editable): $REPO"
else
  log "installing this repo (editable, no deps): $REPO"
  uvpip --no-deps -e "$REPO"
fi
[ "$PROFILE" = full ] && log "torch: $("$PY" -c 'import torch; print(torch.__version__, "cuda" if torch.version.cuda else "cpu")' 2>&1)"

# ---- 4. browser
BROWSER=none   # bundled | chrome | none ; SLOP_BROWSER_CHANNEL is set only for the chrome fallback
if [ "$NO_BROWSER" = 1 ]; then
  log "browser: skipped (--no-browser)"
  BROWSER="$(sed -n 's/^export SLOP_BROWSER="\([a-z]*\)"$/\1/p' "$SLOP_HOME/env.sh" 2>/dev/null || true)"
  [ -n "$BROWSER" ] || BROWSER=none
else
  log "installing Playwright chromium into $PLAYWRIGHT_BROWSERS_PATH"
  if with_timeout 900 "$PY" -m playwright install chromium 2>&1 | { grep -v '% of ' || true; }; then
    if browser_launch chromium; then BROWSER=bundled; else warn "bundled chromium installed but does not launch"; fi
  else
    warn "Playwright's browser download failed (CDN blocked?)"
  fi
  if [ "$BROWSER" = none ]; then
    if system_chrome >/dev/null && browser_launch chrome; then
      BROWSER=chrome
      log "using the system Chrome instead: $(system_chrome) (SLOP_BROWSER_CHANNEL=chrome; renders differ slightly from chromium-1223)"
    else
      warn "no headless browser works: renders will fail until one does (slop doctor shows the error)"
    fi
  fi
  log "browser: $BROWSER"
fi
BROWSER_CHANNEL=""; [ "$BROWSER" = chrome ] && BROWSER_CHANNEL=chrome

# ---- 5. cloudflared
if [ "$NO_CF" = 1 ]; then
  log "cloudflared: skipped (--no-cloudflared)"
else
  install_cloudflared || warn "no working cloudflared - $CF_NEED. Re-run later: bash $REPO/bin/setup.sh --cloudflared"
fi

# ---- 6. env.sh + shim + state
cat >"$SLOP_HOME/env.sh.tmp" <<EOF
# generated by claudia bin/setup.sh on $(date -u '+%Y-%m-%d %H:%M UTC') - NO secrets here. Re-run setup.sh to regenerate.
export SLOP_HOME="$SLOP_HOME"
export SLOP_PROJECTS="$SLOP_PROJECTS"
export SLOP_TOOLKIT="$REPO"
export SLOP_PROFILE="$PROFILE"
export SLOP_BROWSER="$BROWSER"
export SLOP_BROWSER_CHANNEL="$BROWSER_CHANNEL"
export SLOP_TORCH_SOURCE="$TORCH_SOURCE"
export HF_HOME="$SLOP_HOME/cache/hf"
export TORCH_HOME="$SLOP_HOME/cache/torch"
export HF_HUB_DISABLE_TELEMETRY=1
export PLAYWRIGHT_BROWSERS_PATH="$SLOP_HOME/ms-playwright"
export UV_PYTHON_INSTALL_DIR="$SLOP_HOME/python"
export UV_PYTHON_BIN_DIR="$SLOP_HOME/python/bin"
export UV_CACHE_DIR="$SLOP_HOME/cache/uv"
export EARSHOT_HOME="$EARSHOT_HOME"
case ":\$PATH:" in *":$SLOP_HOME/bin:"*) ;; *) export PATH="$SLOP_HOME/bin:\$PATH" ;; esac
EOF
mv -f "$SLOP_HOME/env.sh.tmp" "$SLOP_HOME/env.sh"

cat >"$BIN/slop.tmp" <<EOF
#!/bin/sh
# generated by claudia bin/setup.sh - runs the toolkit at $REPO with the claudia venv
. "$SLOP_HOME/env.sh"
PYTHONPATH="$REPO\${PYTHONPATH:+:\$PYTHONPATH}"
export PYTHONPATH
[ -x "$PY" ] || exec sh "$REPO/bin/slop" "\$@"   # the venv is gone (a computer reset): that launcher says what to run
exec "$PY" -m slop "\$@"
EOF
chmod 0755 "$BIN/slop.tmp"; mv -f "$BIN/slop.tmp" "$BIN/slop"
printf '%s\n' "$PROFILE" >"$SLOP_HOME/profile"
if on_box; then shell_rc_fix; fi   # plain `slop` in new shells; a computer reset clears the home folder
if [ -f "$SLOP_HOME/relay/config.json" ]; then   # the production's tools follow this install (earshot, after a reset)
  if "$BIN/slop" --json relay setup >/dev/null 2>&1; then log "the production's tools refreshed (slop relay setup)"
  else warn "slop relay setup did not finish (Opus signed out?): run it once Opus is signed in"; fi
fi

# ---- 7. summary
log "done. profile=$PROFILE browser=$BROWSER torch=$TORCH_SOURCE"
log "use:  . $SLOP_HOME/env.sh && slop doctor      (or call $BIN/slop directly)"
log "re-run this script after any computer update; it only fetches what is missing."
XDG_CACHE_HOME="$SLOP_HOME/cache" "$BIN/slop" doctor --offline || true
