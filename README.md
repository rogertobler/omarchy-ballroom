<div align="center">

# Ballroom

**The sound of your machine in one place.**

Every output and input, the level of every application and every device, an equalizer per device, and a stage
for radio, SoundCloud and DI.FM, in one panel in the bar. Built on PipeWire and WirePlumber, with nothing of its
own between your applications and your speakers.

[![License: MIT](https://img.shields.io/badge/License-MIT-00E28A.svg?style=flat-square)](LICENSE)
![Omarchy](https://img.shields.io/badge/Omarchy-4.5.x-1a1a1a?style=flat-square)
![PipeWire](https://img.shields.io/badge/PipeWire-1.6-4A86C8?style=flat-square)
![Interface](https://img.shields.io/badge/bar%20%2B%20terminal-both-C08BFF?style=flat-square)

</div>

---

A ballroom is the room where the music of a house plays. That is what this is for your machine: one place where
you see what plays, where it goes and how loud it is, and change it.

Ballroom takes the place of Omarchy's built-in audio widget while it is enabled. It does what that widget does,
and the things you would otherwise install five plugins for, which then get in each other's way: per device
levels and caps, routes per application, Bluetooth codecs, an equalizer, a spectrum and a player.

## Install

From the store, or by hand:

```sh
omarchy plugin add https://github.com/rogertobler/omarchy-ballroom --enable
```

That is all it needs. The command `ballroom` ships in the plugin folder, and the widget runs it from there. It
writes its two user units to `~/.config/systemd/user` itself the first time it starts the equalizer or the stage.
Ballroom has no system part: everything it touches belongs to your account.

For the `ballroom` command in a terminal, run the installer from the plugin folder once. It copies nothing,
links `~/.local/bin/ballroom` to the command there and puts `ballroom-uninstall` next to it:

```sh
~/.config/omarchy/plugins/rogertobler.ballroom/install.sh
```

From a checkout of your own, the installer also copies the plugin into
`~/.config/omarchy/plugins/rogertobler.ballroom` and enables it. Run it as yourself, without `sudo`:

```sh
git clone https://github.com/rogertobler/omarchy-ballroom
cd omarchy-ballroom
./install.sh
omarchy restart shell
```

The restart afterwards is needed because Qt keeps the old QML files otherwise. A plugin folder that is a git
checkout from the store is never copied over: the installer only adds the link, and `omarchy plugin update`
updates the plugin.

The installer refuses to run while the screen is locked, because writing a plugin reloads the shell. It does not
replace a `~/.local/bin/ballroom`, `ballroom-uninstall` or unit of the same name that belongs to another program,
and neither does the command.

### Ballroom replaces the built-in audio widget

Ballroom is a clone of `omarchy.audio` (`clonedFrom` in its manifest) and keeps its module and IPC names. While
Ballroom is enabled, the shell puts it where the built-in widget was and hands it every call meant for the audio
widget. `omarchy plugin disable rogertobler.ballroom` gives the built-in widget back, and so does the
uninstaller. Nothing of the built-in widget is changed.

## Requirements

Needed, all of them part of Omarchy:

- **`python3`**, which the `ballroom` command is written in, and which Omarchy has for `yt-dlp`.
- **`pw-dump`, `wpctl` and `pw-metadata`**, which come with PipeWire and WirePlumber.

Optional, the installer and `ballroom doctor` name what is missing:

- **`cava`** for the spectrum. Without it there is no spectrum, and nothing else changes.
- **`mpv`** for the stage. Without it there is no radio, SoundCloud or DI.FM.
- **`yt-dlp`** for SoundCloud on the stage.

`mpv` and `yt-dlp` come with Omarchy; `cava` is one `omarchy pkg add cava` away. `ballroom doctor` lists what is
missing at any time.

## In the bar

| Action | Does |
|---|---|
| click | opens the panel |
| right click | mutes the default output |
| middle click | mutes the default input |
| wheel | output volume, in steps of 5 % |

While something plays that can be paused (the stage, a browser, a music player), a pause button sits beside the
icon. One click pauses all of it, the next plays again exactly what it paused, and a player you paused elsewhere
is left alone. A right click stops. Every icon in the bar has a tooltip that says the level, what plays and who is
listening, and in its last line what its clicks do. A small spectrum sits next to the icon while something plays.

## The panel

Five sections. Each one can be switched off or moved on the settings page, and all but Playing fold shut under
their own line:

- **Output, with its devices.** The default output's level and mute at the top, and below it, indented, every
  plugged in output with its own level and mute. A click on a device makes it the default.
- **Input, with its devices.** The same for microphones, with a live level bar in every row while the panel is
  open. A muted input is never read.
- **Equalizer.** On and off, the preset of the default output, the curve, the bands, the preamp and AutoEQ
  import. See below.
- **Playing, with the transport.** Every stream that plays, with its own level and mute and a dropdown that sends
  it to an output. The stage's own stream is one of these rows and carries the transport: back, play and pause,
  next, stop, and a seek bar for tracks.
- **Library: radio, SoundCloud, DI.FM.** Search, results, favorites and recently played, per source.

The panel works from the keyboard as well: the arrows move the cursor and change a level, `enter` acts on the row,
`m` mutes the row under the cursor, `f` keeps a library row as a favorite, `e` switches the equalizer, `s` opens
the settings page, and Esc closes the page and then the panel. The sliders in the panel do not turn with the
mouse wheel, so scrolling the panel never changes a level.

## Routes, per setup

The dropdown on a stream starts with **DEFAULT**, followed by the outputs. DEFAULT means the stream follows the
default output; an output means a rule: this application plays there.

A rule belongs to the **setup** it was chosen in: the set of outputs that are plugged in at that moment. An
application sent to a monitor at the desk is not sent anywhere at another table, where a different rule may hold
or none, and then it follows the default. Docking and undocking switch between setups by themselves.

```sh
ballroom route                    # all rules, per setup
ballroom route Firefox Speaker    # Firefox plays on Speaker in this setup
ballroom route Firefox follow     # Firefox follows the default again in this setup
```

## Unplugging and undocking

A port with nothing in it stays in the graph, and a stream sent to it stays there, playing into nothing. So
Ballroom lets every stream on an unplugged output follow the default, and brings a stream with a rule back once
its output is plugged in again.

When the default output itself is unplugged, Ballroom moves the default to the plugged in output WirePlumber ranks
highest, brought down to its cap first, and moves it back once the output you had chosen returns. It moves it back
only if the default still sits where Ballroom put it: a default you chose in the meantime is yours. Some machines
never report a display port as unplugged when a dock is pulled; while no external display is connected, Ballroom
treats every display port as unplugged. With two external displays, pulling only the one that carries the sound
is not noticed on such a machine. A setup is the set of outputs present, so a virtual output that a program
creates (a recorder, a combined sink) makes a setup of its own while it exists.

## Caps: not too loud on arrival

Every output has a cap, the highest level it may arrive at. By default it is **50 % for headphones** and none for
speakers; the kind of a device comes from what PipeWire reports and can be set by hand.

The cap applies when an output arrives, never while you listen: when a device appears or is plugged in, when it
becomes the default through Ballroom, and when Ballroom moves the default on undocking. A headset you turned up to
70 % stays at 70 % for as long as it stays connected. After a login every output counts as arriving.

The cap needs the shell: the widget runs `ballroom apply` when something arrives. WirePlumber makes a new
headset the default by itself and at the level it remembers, so the cap comes a fraction of a second after the
headset is there, not before.

```sh
ballroom device classcap headphones 40     # the cap for every headphone without one of its own, 5 to 100, or none
ballroom device cap Headphones 60          # one device's own cap; - drops it, none means no cap
ballroom device kind "HDMI 1" speakers     # headphones, speakers or auto
```

Arriving devices are noticed by the widget, so caps on arrival need the shell to be running.

## Bluetooth

Ballroom shows and switches the sound side of a Bluetooth headset: the codec in music mode, music or call mode,
and whether WirePlumber may switch to call mode by itself when an application opens the microphone. While a
headset switches, the other outputs are held muted, so the sound never comes out of the wrong speaker; exactly the
outputs Ballroom muted are unmuted afterwards. If the headset does not come back, they stay muted and Ballroom
says so, with `ballroom mute OUTPUT off` as the way out. Pairing and connecting stay with Omarchy's Bluetooth panel.

## The equalizer

One equalizer in front of the default output, with one preset per device: switching from speakers to headphones
switches the preset with it.

- Built in presets: Flat, Bass, Treble, Vocal, Loudness. Your own presets are saved under a name; changing a
  built in preset makes a copy called Custom.
- `ballroom eq import FILE` takes an AutoEQ `ParametricEQ.txt` as a preset.
- Up to 16 peaking filters and 4 low and 4 high shelves per preset, each from 20 Hz to 20 kHz, plus and minus
  24 dB.
- The preamp is automatic by default: the curve's highest point is taken off, so the sound never clips.
- Balance, mono and swapped channels sit in the equalizer's own settings in the panel, and in
  `ballroom eq balance`, `eq mono` and `eq swap`. Any of them that is set shows under the equalizer with a RESET
  beside it, so a side turned by accident does not go unnoticed. They work while the equalizer is on.

**Off** sets every filter to neutral and keeps the equalizer running, and brings the output down by the preamp,
so the loudness stays where it was. **On** brings it back up, unless you changed the level in the meantime. Every
real change of a band makes one short click, so the panel sends a band when you let go of it, not while you drag.

## The stage

A player without a window, for three sources:

- **Radio** from the community directory at radio-browser.info, forty stations at a time.
- **SoundCloud** through `yt-dlp`: search, and the likes, playlists, uploads and reposts of a profile. With the
  session of a browser that is signed in to SoundCloud, your private likes and tracks show as well. No browser is
  read until you choose one: in the panel, or with `ballroom sc cookies auto` (the one signed in) or
  `ballroom sc cookies BROWSER`. `ballroom sc cookies -` (or "Without a browser" in the panel) turns it off again.
- **DI.FM** and its sister stations (RadioTunes, JazzRadio, ClassicalRadio, RockRadio, ZenRadio), with a
  **DI.FM Premium** listen key only. The free streams of these stations play an announcement in other players,
  so Ballroom does not offer them.

The stage plays through `mpv`, which runs as the user unit `ballroom-stage.service` and is started the first time
something plays. Its sound is a stream called Ballroom like any other: its level, its route and the equalizer
apply to it. A live stream is stopped for a pause and tuned in again live, rather than falling behind the station
by the length of the pause.

### The DI.FM listen key

```sh
ballroom di key set       # asks for it with a hidden prompt, or reads the first line of stdin
ballroom di key           # says whether one is set, never shows it
ballroom di key -         # removes it
```

Your listen key is on your account page at di.fm. Ballroom never takes it as an argument, because an argument
lands in the shell history and in the process list, which every local user can read. It is checked with DI.FM
first and kept only if it is accepted, in `~/.config/ballroom/audioaddict.json`, readable by you only. The panel
hands it over the same way. It goes to `mpv` over its socket, never on a command line, and every text Ballroom
prints has it masked.

## Scenes and diagnosis

A **scene** keeps how the desk is set: the default output and input, the level and mute of every device, the
equalizer and its preset, the mode and codec of Bluetooth devices, and what the stage plays. `ballroom scene use`
brings it back step by step, reads every step back, and names what it skipped because a device is not there. A
scene may mute a microphone, and never unmutes one.

`ballroom doctor` checks the services, the clock, xruns, the defaults, the equalizer, foreign filters and drop in
configuration fragments in front of the output, and the optional tools, and says what is wrong in one line each.

## Settings

All settings are on the panel's settings page, behind the cog or `s`: the name the panel shows, the pause button
in the bar, the spectrum and its bars and colour, the spectrum and level bars of the inputs, which sections the
panel shows and in which order, the SoundCloud name and browser, and the status interval. The page is built from
the plugin's manifest, so it shows the same rows with the same bounds as the command checks. The values live on
Ballroom's entry in `~/.config/omarchy/shell.json`, where the shell keeps every widget's settings.

## Key bindings

Every verb that changes what you hear takes `--osd` and then shows the result on Omarchy's on screen display, the
way the media keys do: `vol`, `mute`, `out`, `in`, `eq on` and `eq off`, `play`, `pause`, `stop`, `toggle` and
`scene use`. In `~/.config/hypr/bindings.conf`, for example:

```
bindd = SUPER, F9, Next output, exec, ballroom out next --osd
bindd = SUPER, F10, Equalizer off, exec, ballroom eq off --osd
```

## What is where

| Place | Holds |
|---|---|
| `~/.config/omarchy/plugins/rogertobler.ballroom/` | the plugin: the widget, the `ballroom` command, the two unit files and `uninstall.sh` |
| `~/.local/bin/ballroom`, `~/.local/bin/ballroom-uninstall` | only with the installer: a link to the command, and the uninstaller |
| `~/.config/systemd/user/ballroom-eq.service` | the equalizer, a PipeWire process of its own, written and started by `ballroom eq on` |
| `~/.config/systemd/user/ballroom-stage.service` | the stage, a headless `mpv`, written and started by `ballroom play` |
| `~/.config/ballroom/` | your settings, see below |
| `~/.cache/ballroom/` | the DI.FM channel lists, refreshed once a day, and the compiled command in `pyc/` |
| `$XDG_RUNTIME_DIR/ballroom/` | what lasts one login, see below |

In `~/.config/ballroom/`, every file readable by you only:

| File | Holds |
|---|---|
| `devices.json` | per device: name, hidden, kind, cap, preset; and the caps per kind |
| `rules.json` | the routes, per setup |
| `rules.v1.json` | a routes file from before routes were kept per setup, moved aside the first time a route is chosen |
| `undocked.json` | which output you had chosen, while Ballroom holds the default elsewhere after undocking |
| `sound.json` | equalizer on or off, balance, mono, swap |
| `presets.json` | your own presets |
| `eq.conf` | the equalizer's PipeWire configuration, written by Ballroom, overwritten on every rebuild |
| `stage.json` | favorites and recently played |
| `scenes.json` | your scenes |
| `audioaddict.json` | the DI.FM listen key |

A file that cannot be read is moved aside as `NAME.invalid.<time>.json` and defaults apply, so you can still see
what was in it.

In `$XDG_RUNTIME_DIR/ballroom/`, gone at logout: `lock` (one writer at a time), `unit-lock` and `reload-<unit>`
(putting the two units in place, and a reload still owed), `mpv.sock` (the stage),
`outputs-seen.json` (the outputs that were there at the last check, so that only new ones are capped),
`eq-live.json`, `eq-compensation.json` and `eq-failed.json` (the equalizer's preamp and the level it took off),
`stage-now.json`, `stage-results.json`, `stage-sc.json` and `stage-di-now.json` (what plays, the last search, a
SoundCloud list, the DI.FM title), and a
`cava-<pid>.conf` per running spectrum. Ballroom refuses to run without `XDG_RUNTIME_DIR` rather than fall back to
`/tmp`.

## Permissions and privacy

- No root, no sudoers file, no system unit, no WirePlumber or PipeWire configuration fragment. Two user units.
- The microphone is never opened on the side. Input levels and the input spectrum run only while the panel is
  open, stop when it closes, and never read a muted input.
- The DI.FM listen key never appears as a process argument, in a message, in a stream title or in the graph.
- To read your SoundCloud session, Ballroom opens the browser's cookie store read only and looks at the host
  column only, never at a cookie value. `yt-dlp` decrypts the session. To learn your profile name once
  (`ballroom sc whoami`), `yt-dlp` has to write the browser's whole cookie jar to a file: Ballroom creates that
  file itself in the runtime directory, readable by you only, deletes it as soon as the SoundCloud rows are read
  and before Ballroom sends its own request with the session, and sweeps one left behind by a killed run. Of the
  rows it reads, only those a browser itself would send to `soundcloud.com/you` go into that request: the domain
  `soundcloud.com` exactly, a path that covers `/you`, not expired. The name it finds is kept, so this happens once.
- A browser session is used only after you chose that browser. Left unset, or set off with
  `ballroom sc cookies -`, no `yt-dlp` call and no request reads one.
- Ballroom's directories are created readable by you only and refused when they are a link or belong to someone
  else.
- The command runs its tools from a fixed path, not from your `PATH`, and the widget runs it with a cleared
  environment, a deadline and a limit on how much it may print.

## Update

```sh
cd omarchy-ballroom && git pull && ./install.sh && omarchy restart shell
```

Added from the store: `omarchy plugin update rogertobler.ballroom`, then `omarchy restart shell`. The command
brings its unit files up to date the next time it starts one. An update may change the equalizer's graph:
`~/.config/omarchy/plugins/rogertobler.ballroom/ballroom eq restart` rebuilds an equalizer that is on, and the
installer does that for you.

Coming from 0.1, where the command was a copy in `~/.local/bin` that needed `bun`: run the installer once more,
from your checkout or from the plugin folder. It replaces that copy with a link, so the terminal and your key
bindings run the same command as the panel. Until then the old copy and the panel do not wait for each other when
both write at the same moment. `ballroom doctor` warns while an old copy is left.

## Uninstall

```sh
ballroom-uninstall            # keeps your settings in ~/.config/ballroom
ballroom-uninstall --purge    # also removes your settings, the DI.FM listen key and the cache
```

Added from the store, run the uninstaller from the plugin folder first, then remove the plugin:

```sh
~/.config/omarchy/plugins/rogertobler.ballroom/uninstall.sh
omarchy plugin remove rogertobler.ballroom
```

The uninstaller disables the plugin, which gives the bar its built-in audio widget back, stops the equalizer and
the stage, and removes the units, the command and the widget. A plugin folder that was added with
`omarchy plugin add` is a git checkout and is removed with `omarchy plugin remove rogertobler.ballroom`. Before the
equalizer stops, it is switched off, which brings the output down by its preamp, so the sound is not louder
without it.

## What it does not do

- Pair or connect Bluetooth devices. That stays with Omarchy's Bluetooth panel.
- Process the microphone: no noise suppression, no echo cancellation, no input equalizer.
- Network speakers, AirPlay, Chromecast or other machines.
- A patchbay. Ballroom sends streams to devices; it does not wire ports by hand.
- Several outputs at once, or a priority list of outputs. Zones are not part of this release.
- Features of a headphone maker's own app, such as noise cancelling modes.

## Command reference

```
ballroom                                  what plays where, how loud, who is listening
ballroom json                             everything the widget shows, as JSON
ballroom out [DEVICE|next]  | in [DEVICE]
ballroom vol [TARGET] [LEVEL]             TARGET: out, in, a device or an application; LEVEL 0 to 150, +5, -5
ballroom mute [TARGET] [on|off|toggle]
ballroom route [APP DEVICE|APP follow]
ballroom device list|alias|hide|show|kind|cap|classcap|reset ...
ballroom apply                            bring the graph in line with routes and caps
ballroom bt [list] | bt codec [DEVICE] [CODEC] | bt mode [DEVICE] music|call | bt auto [on|off]
ballroom eq [show|on|off|stop|restart|sync]
ballroom eq preset list|use NAME [DEVICE]|save NAME|rm NAME | eq import FILE [NAME]
ballroom eq band N FREQ GAIN [Q] [TYPE] | eq preamp DB|auto | eq balance -1..1 | eq mono|swap on|off | eq stereo reset
ballroom stage [status|start|quit|refresh|clear]
ballroom play [URL|N|*N|NAME] | pause | next | prev | stop | toggle | seek SECONDS|+N|-N
ballroom radio search QUERY [--more] | radio play N
ballroom sc search QUERY | sc play N | sc list [likes|playlists|uploads|reposts] [NAME] | sc open id:N
ballroom sc name [NAME|-] | sc whoami | sc browsers | sc cookies [auto|BROWSER|-]
ballroom di search QUERY | di play CHANNEL | di channels [NETWORK] | di key [set|-]
ballroom fav [list|add [N]|rm N|play N]
ballroom scene [list|save NAME|use NAME|show NAME|rm NAME]
ballroom doctor
ballroom spectrum [--bars N] [--fps N] [--source auto|SERIAL]
ballroom help | --version
```

`ballroom help` says the same with a line on each. A device is named by its name, its number in the listing, or a
unique part of its description; anything ambiguous is refused with the candidates, never guessed.

Every verb except `spectrum`, `help` and `--version` takes `--json` and then prints one JSON object, with `ok`, any `warnings`, and on failure `error` and
`code`. The exit codes are part of the interface:

| Code | Means |
|---|---|
| 0 | done |
| 1 | failed |
| 2 | wrong use: an unknown verb, a missing or invalid argument |
| 3 | not found: no such device, stream, preset, scene or channel |
| 4 | a tool or a server did not answer in time |

## Status

Version 0.1.0. Built against PipeWire 1.6 and WirePlumber 0.5 on Omarchy 4.5.

## License

[MIT](LICENSE)
