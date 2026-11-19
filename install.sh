#!/bin/bash
# Ballroom: setup. No sudo: everything Ballroom touches belongs to your own account.
#
#   ./install.sh
#
# Idempotent: run it again after an update. Remove it again with `ballroom-uninstall`.
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
for c in bun pw-dump wpctl pw-metadata; do command -v "$c" >/dev/null || missing+=("$c"); done
if (( ${#missing[@]} )); then
  echo "  missing: ${missing[*]}" >&2
  echo "  bun comes from the Arch repository (sudo pacman -S bun); pw-dump, wpctl and pw-metadata come with PipeWire and WirePlumber." >&2
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

echo "== 2/4 Command"
install -Dm755 "$SRC/ballroom" "$BIN/ballroom"
# `omarchy plugin remove` deletes the plugin folder and the uninstaller with it, so a copy lives next to the command.
install -Dm755 "$SRC/uninstall.sh" "$BIN/ballroom-uninstall"
echo "  $BIN/ballroom"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  note: $BIN is not on your PATH; the bar widget does not need it, the terminal does" ;; esac

echo "== 3/4 Equalizer and stage services"
# A user unit that runs the equalizer as its own PipeWire client. It is only started by `ballroom eq on`.
install -Dm644 "$SRC/ballroom-eq.service" "$HOME/.config/systemd/user/ballroom-eq.service"
install -Dm644 "$SRC/ballroom-stage.service" "$HOME/.config/systemd/user/ballroom-stage.service"
if systemctl --user daemon-reload 2>/dev/null; then
  echo "  $HOME/.config/systemd/user/ballroom-eq.service"
  # An update may have changed the graph Ballroom writes: an equalizer that is on gets rebuilt from it.
  if systemctl --user is-active --quiet ballroom-eq.service; then "$BIN/ballroom" eq restart >/dev/null 2>&1 && echo "  equalizer restarted" || true; fi
else
  echo "  systemd --user is not reachable: the equalizer will not run until it is"
fi

echo "== 4/4 Bar widget"
if [[ "$(readlink -f "$SRC")" != "$(readlink -f "$PLUGIN_DIR" 2>/dev/null || echo /nonexistent)" ]]; then
  install -d "$PLUGIN_DIR"
  for f in manifest.json BarWidget.qml Service.qml Model.js preview.png; do
    [[ -f "$SRC/$f" ]] && install -m644 "$SRC/$f" "$PLUGIN_DIR/$f"
  done
  echo "  plugin files -> $PLUGIN_DIR"
fi
omarchy-shell -q shell rescanPlugins 2>/dev/null || true
# The rescan is asynchronous: enabling before the registry lists the plugin is refused with "unknown plugin",
# and `omarchy plugin enable` still exits 0. So wait until the shell knows it, enable, and then ask the shell
# whether it is really enabled instead of trusting the exit code.
# The list is JSON, and Ballroom's own entry names omarchy.audio as its source, so it is parsed, not grepped.
plugin_state() {
  omarchy-shell shell listPlugins 2>/dev/null | PLUGIN_ID="$PLUGIN_ID" bun -e '
    let list = []; try { list = JSON.parse(await Bun.stdin.text()); } catch {}
    const p = Array.isArray(list) ? list.find((x) => x && x.id === process.env.PLUGIN_ID) : null;
    console.log(!p ? "unknown" : p.enabled === true ? "enabled" : "disabled");' 2>/dev/null
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
ballroom apply >/dev/null 2>&1 || "$BIN/ballroom" apply >/dev/null 2>&1 || true

echo
echo "Done. Then: omarchy restart shell (Qt keeps the old QML files otherwise), and try  ballroom  or  ballroom help"
