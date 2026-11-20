#!/bin/bash
# Ballroom: removal. Gives the bar its built-in audio widget back.
#
#   ballroom-uninstall [--purge]      --purge also deletes your Ballroom settings in ~/.config/ballroom
#
# Installed from the store, run it from the plugin folder before `omarchy plugin remove`:
#   ~/.config/omarchy/plugins/rogertobler.ballroom/uninstall.sh
set -euo pipefail
[[ $EUID -ne 0 ]] || { echo "Run this as yourself, not with sudo." >&2; exit 1; }
PLUGIN_ID=rogertobler.ballroom
PLUGIN_DIR="$HOME/.config/omarchy/plugins/$PLUGIN_ID"
BIN="$HOME/.local/bin"
PURGE=0; [[ "${1:-}" == --purge ]] && PURGE=1

if command -v omarchy-hyprland-session-locked >/dev/null && omarchy-hyprland-session-locked 2>/dev/null; then
  echo "The screen is locked. Unlock it first: removing the widget reloads the shell." >&2
  exit 1
fi

# Disabling first: that puts the built-in audio widget back, and the widget stops acting on the graph while
# the equalizer goes.
omarchy plugin disable "$PLUGIN_ID" >/dev/null 2>&1 && echo "disabled; the built-in audio widget is back" || true
# The command is the plugin's own copy; an older setup kept a copy in ~/.local/bin.
CMD="$PLUGIN_DIR/ballroom"; [[ -x "$CMD" ]] || CMD="$BIN/ballroom"
# Stopping the equalizer puts the sound straight on the device again, WirePlumber does that by itself. A preamp
# below zero would go with it and leave the sound louder, so the equalizer is switched off first: that brings
# the device down by the preamp before the filter goes neutral. If that fails, it keeps running and nothing
# else is removed: louder is the one way this must not fail.
if systemctl --user is-active --quiet ballroom-eq.service 2>/dev/null; then
  if ! [[ -x "$CMD" ]] || ! timeout 20 "$CMD" eq off >/dev/null 2>&1; then
    # The widget is what makes up for the preamp if the equalizer dies later, so it goes back on.
    omarchy plugin enable "$PLUGIN_ID" >/dev/null 2>&1 || true
    echo "could not switch the equalizer off first: it keeps running, Ballroom is enabled again, nothing was removed." >&2
    echo "Lower the volume, then: systemctl --user stop ballroom-eq.service, and run this again." >&2
    exit 1
  fi
fi
systemctl --user stop ballroom-eq.service 2>/dev/null && echo "equalizer stopped" || true
systemctl --user stop ballroom-stage.service 2>/dev/null || true
# Only Ballroom's own spectrum processes: the pattern is anchored to the whole command line.
pkill -u "$(id -u)" -f "^(/usr/bin/)?(python3( -I)?|bun) ($PLUGIN_DIR|$BIN)/ballroom spectrum( |\$)" 2>/dev/null || true

# A folder that is a git checkout was added with `omarchy plugin add` and is removed the same way.
if [[ -d "$PLUGIN_DIR/.git" ]]; then
  echo "the plugin folder is a checkout; remove it with: omarchy plugin remove $PLUGIN_ID"
elif [[ -d "$PLUGIN_DIR" ]]; then
  rm -rf -- "$PLUGIN_DIR" && echo "removed $PLUGIN_DIR"
fi
omarchy-shell -q shell rescanPlugins 2>/dev/null || true
# Only files that are Ballroom's are removed; a file with the same name from somewhere else stays and is named.
owned() { head -n 5 "$1" 2>/dev/null | grep -q -- "$2"; }
remove() { [[ -e "$1" ]] || return 0; if owned "$1" "$2"; then rm -f -- "$1"; else echo "left $1 alone: it is not Ballroom's"; fi; }
remove "$HOME/.config/systemd/user/ballroom-stage.service" "Description=Ballroom"
remove "$HOME/.config/systemd/user/ballroom-eq.service" "Description=Ballroom"
systemctl --user daemon-reload 2>/dev/null || true
echo "removed the equalizer and stage services"
# The terminal link points into the plugin folder; once that is gone it dangles and cannot be read.
if [[ -L "$BIN/ballroom" && "$(readlink "$BIN/ballroom")" == "$PLUGIN_DIR/ballroom" ]]; then rm -f -- "$BIN/ballroom"
else remove "$BIN/ballroom" "Ballroom command"; fi
if (( PURGE )); then rm -rf -- "$HOME/.config/ballroom" "$HOME/.cache/ballroom" && echo "removed your Ballroom settings, the DI.FM listen key and the cache"
else echo "kept your settings in ~/.config/ballroom, the DI.FM listen key among them (ballroom-uninstall --purge deletes them)"; fi
remove "$BIN/ballroom-uninstall" "Ballroom: removal"
echo "Done."
