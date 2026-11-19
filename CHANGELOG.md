# Changelog

All notable changes to Ballroom are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version in `manifest.json` is the single source of truth. The `VERSION` constant in the `ballroom` command,
which `ballroom --version` prints, is kept equal to it. Every release is one commit on `main`, tagged `vX.Y.Z`.
Between releases `main` stands still, because the Omarchy marketplace pins a listing to an exact commit.

## [0.1.0] 2026-11-19

The first release.

### Added

- **A clone of the built-in audio widget.** Ballroom takes the place of `omarchy.audio` while it is enabled and
  keeps its module and IPC names; disabling it gives the built-in widget back.
- **Outputs and inputs with their devices.** The level and mute of the default output and input at the top, every
  plugged in device below as its child, with its own level and mute, and a click to make it the default. A live
  level bar in every input row while the panel is open.
- **Volume per application**, with a mute and a route per stream. The dropdown on a stream starts with DEFAULT,
  then the outputs.
- **Routes per setup.** A rule holds for the set of outputs plugged in when it was chosen, so docking and
  undocking switch between rules by themselves, and an application without a rule here follows the default.
- **Caps on arrival.** An output that appears, is plugged in or is made the default is brought down to its cap
  first: 50 % for headphones by default, none for speakers, adjustable per kind and per device. A device you are
  listening to is never pulled down.
- **Undocking.** A stream on an unplugged output follows the default and comes back with its rule. A default left
  on an unplugged output moves to the next plugged in one and back once the chosen output returns.
- **Bluetooth.** The music codec, music or call mode, and whether WirePlumber may switch to call mode by itself,
  with the other outputs held muted while a headset switches.
- **An equalizer per device**, as a PipeWire process of its own in front of the default output: built in and
  own presets, AutoEQ import, up to 16 peaking filters and 4 shelves on each side, an automatic preamp, balance,
  mono and swapped channels. Off keeps it running and neutral and lowers the output by the preamp, so nothing
  that plays is interrupted and nothing gets louder.
- **A spectrum** of the output in the bar and in the panel, and of the microphone while the panel is open, through
  `cava`.
- **The stage**, a player without a window: radio from radio-browser.info, SoundCloud through `yt-dlp` with the
  session of a signed in browser, and DI.FM and its sister stations with a Premium listen key. Search, results,
  favorites, recently played, and a transport on the stage's own row in the panel.
- **A pause button in the bar** for the stage and for MPRIS players such as a browser: one click pauses all of it,
  the next plays exactly that again, a right click stops.
- **Tooltips** that say the level, what plays, what is paused and who is listening, and what each click does.
- **Scenes** that keep and bring back the defaults, levels, equalizer, Bluetooth modes and what the stage plays.
- **`ballroom doctor`**, a diagnosis of services, clock, xruns, defaults, the equalizer, foreign filters and
  configuration fragments, and missing tools.
- **A settings page in the panel**, built from the manifest: name, pause button, spectrum, input meters, the
  sections and their order, SoundCloud, status interval.
- **Foldable and movable sections** in the panel, and the whole panel from the keyboard.
- **The `ballroom` command** with every verb the panel uses, `--json` on each, fixed exit codes, and `--osd` for
  key bindings.

### Security and privacy

- No root, no sudoers file, no system unit, and no WirePlumber or PipeWire configuration fragment.
  WirePlumber is never restarted.
- The DI.FM listen key is never a process argument: it is read from a hidden prompt or stdin, checked with DI.FM
  before it is kept, stored readable by you only, handed to `mpv` over its socket, and masked in every text.
- The microphone is read only while the panel is open, never while it is muted, and a scene never unmutes one.
- The browser's cookie store is opened read only, and only its host column is read. The one file `yt-dlp` writes
  with the whole cookie jar is created by Ballroom, readable by you only, and deleted before any request goes out.
- Settings and runtime directories are readable by you only and refused when they are a link or someone else's.
  There is no fallback to `/tmp`.
- The command runs its tools from a fixed path, and the widget runs it with a cleared environment, a deadline and
  a limit on its output.
- `install.sh` does not replace a command or unit of the same name that belongs to another program, and the
  uninstaller does not remove one.

[0.1.0]: https://github.com/rogertobler/omarchy-ballroom/releases/tag/v0.1.0
