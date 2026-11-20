#!/bin/bash
# Ballroom: setup from a checkout. No sudo: everything Ballroom touches belongs to your own account.
#
#   ./install.sh
#
# The plugin does not need this script: `omarchy plugin add` gives a working plugin, and the command writes its
# two user units itself the first time it starts them. This script copies a checkout into the plugin folder and
# puts the command on your PATH for the terminal. Idempotent. Remove it again with `ballroom-uninstall`.
set -euo pipefail
trap 'echo "install.sh: failed at line $LINENO (see the message above, if any)" >&2' ERR
[[ $EUID -ne 0 ]] || { echo "Run this as yourself, not with sudo: Ballroom lives in your own home directory." >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
PLUGIN_ID=rogertobler.ballroom
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
BIN="$HOME/.local/bin"

# Writing into ~/.config/omarchy/plugins/ makes omarchy-shell hot-reload, and the shell has crashed when that
# happened under an active screen lock. Refuse rather than leave a locked machine without a lock screen.
if command -v omarchy-hyprland-session-locked >/dev/null && omarchy-hyprland-session-locked 2>/dev/null; then
  echo "The screen is locked. Unlock it first: installing the widget reloads the shell." >&2
  exit 1
fi

echo "== 1/4 Requirements"
missing=()
# The command names /usr/bin/python3 itself, so a python3 from a version manager does not count.
[[ -x /usr/bin/python3 ]] || missing+=(/usr/bin/python3)
for c in pw-dump wpctl pw-metadata; do command -v "$c" >/dev/null || missing+=("$c"); done
if (( ${#missing[@]} )); then
  echo "  missing: ${missing[*]}" >&2
  echo "  python3 comes with Omarchy (yt-dlp needs it); pw-dump, wpctl and pw-metadata come with PipeWire and WirePlumber." >&2
  exit 1
fi
command -v cava >/dev/null || echo "  cava is not installed: no spectrum until it is (omarchy pkg add cava)"
command -v mpv  >/dev/null || echo "  mpv is not installed: no stage (radio, SoundCloud, DI.FM) until it is (omarchy pkg add mpv)"
command -v yt-dlp >/dev/null || echo "  yt-dlp is not installed: no SoundCloud on the stage until it is (omarchy pkg add yt-dlp)"

# Never overwrite a file that is not Ballroom's: the names are generic enough to collide with someone's own.
owned() { [[ ! -e "$1" ]] || head -n 5 "$1" 2>/dev/null | grep -q -- "$2"; }
for pair in "$BIN/ballroom|Ballroom command" "$BIN/ballroom-uninstall|Ballroom: removal" \
            "$HOME/.config/systemd/user/ballroom-eq.service|Description=Ballroom" "$HOME/.config/systemd/user/ballroom-stage.service|Description=Ballroom"; do
  owned "${pair%%|*}" "${pair##*|}" || { echo "${pair%%|*} exists and is not Ballroom's; move it away first" >&2; exit 1; }
done

echo "== 2/4 Plugin"
# The command, its two units and the remover travel with the plugin, exactly as `omarchy plugin add` puts them
# there. A folder that is a git checkout from the store belongs to `omarchy plugin update`: nothing is copied
# into it, and this script only adds the terminal link below.
same() { [[ "$(readlink -f "$SRC")" == "$(readlink -f "$PLUGIN_DIR" 2>/dev/null || echo /nonexistent)" ]]; }
if same; then
  :
elif [[ -d "$PLUGIN_DIR/.git" ]]; then
  echo "  $PLUGIN_DIR is a checkout from the store; nothing copied (update it with: omarchy plugin update $PLUGIN_ID)"
else
  install -d "$PLUGIN_DIR"
  # The command and its units first: a hot reload may start the new widget the moment its QML lands.
  install -m755 "$SRC/ballroom" "$PLUGIN_DIR/ballroom"
  install -m644 "$SRC/ballroom_cmd.py" "$PLUGIN_DIR/ballroom_cmd.py"
  install -m755 "$SRC/uninstall.sh" "$PLUGIN_DIR/uninstall.sh"
  for f in ballroom-eq.service ballroom-stage.service LICENSE README.md Model.js Service.qml BarWidget.qml preview.png manifest.json; do
    [[ -f "$SRC/$f" ]] && install -m644 "$SRC/$f" "$PLUGIN_DIR/$f"
  done
  echo "  plugin files -> $PLUGIN_DIR"
fi

echo "== 3/4 Terminal"
# A link, so the terminal and the panel always run the same file. `omarchy plugin remove` deletes the plugin
# folder and the remover with it, so a copy of the remover lives next to the link.
install -d "$BIN"
ln -sfn "$PLUGIN_DIR/ballroom" "$BIN/ballroom"
# The remover that belongs to the plugin the link points to, not to this checkout, which may be another version.
install -m755 "$PLUGIN_DIR/uninstall.sh" "$BIN/ballroom-uninstall"
echo "  $BIN/ballroom -> $PLUGIN_DIR/ballroom"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  note: $BIN is not on your PATH; the bar widget does not need it, the terminal does" ;; esac
# An update may have changed the graph Ballroom writes: an equalizer that is on gets rebuilt from it, and the
# command brings its units up to date on the way.
eq_note=""
if systemctl --user is-active --quiet ballroom-eq.service 2>/dev/null; then
  if "$PLUGIN_DIR/ballroom" eq restart >/dev/null 2>&1; then echo "  equalizer restarted"
  else eq_note="the equalizer could not be rebuilt; run: ballroom eq restart, and ballroom doctor if it fails again"; echo "  $eq_note" >&2; fi
fi

echo "== 4/4 Bar widget"
omarchy-shell -q shell rescanPlugins 2>/dev/null || true
# The rescan is asynchronous: enabling before the registry lists the plugin is refused with "unknown plugin",
# and `omarchy plugin enable` still exits 0. So wait until the shell knows it, enable, and then ask the shell
# whether it is really enabled instead of trusting the exit code.
# The list is JSON, and Ballroom's own entry names omarchy.audio as its source, so it is parsed, not grepped.
plugin_state() {
  omarchy-shell shell listPlugins 2>/dev/null | PLUGIN_ID="$PLUGIN_ID" /usr/bin/python3 -I -c '
import json, os, sys
try: data = json.load(sys.stdin)
except Exception: data = []
p = next((x for x in data if isinstance(x, dict) and x.get("id") == os.environ["PLUGIN_ID"]), None) if isinstance(data, list) else None
print("unknown" if not p else "enabled" if p.get("enabled") is True else "disabled")' 2>/dev/null
}
known() { [[ "$(plugin_state)" != unknown ]]; }
enabled() { [[ "$(plugin_state)" == enabled ]]; }
for _ in $(seq 1 50); do known && break; sleep 0.2; done
# Ballroom is a clone of the built-in audio widget: enabling it takes the built-in's place in the bar, and
# disabling it gives the built-in back.
omarchy plugin enable "$PLUGIN_ID" >/dev/null 2>&1 || true
for _ in $(seq 1 25); do enabled && break; sleep 0.2; done
if enabled; then echo "  enabled, in place of the built-in audio widget"
elif known; then echo "  the shell knows Ballroom but did not enable it; try: omarchy plugin enable $PLUGIN_ID"
else echo "  the shell did not pick the plugin up (is it running?); after: omarchy restart shell, run: omarchy plugin enable $PLUGIN_ID"; fi
"$PLUGIN_DIR/ballroom" apply >/dev/null 2>&1 || true

echo
[[ -z "$eq_note" ]] || echo "Note: $eq_note" >&2
echo "Done. Then: omarchy restart shell (Qt keeps the old QML files otherwise), and try  ballroom  or  ballroom help"
