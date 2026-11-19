# Changelog

All notable changes to Ballroom are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The version in `manifest.json` is the single source of truth. The `VERSION` constant in the `ballroom` command,
which `ballroom --version` prints, is kept equal to it. Every release is one commit on `main`, tagged `vX.Y.Z`.
Between releases `main` stands still, because the Omarchy marketplace pins a listing to an exact commit.

## [0.1.2] 2026-11-19

### Changed

- A browser session for SoundCloud is read only after you chose the browser, in the panel or with
  `ballroom sc cookies auto|BROWSER`. An empty setting no longer means "take the browser that is signed in", so a
  setting cleared to turn the session off in 0.1.0 stays off after the update. The automatic choice and its memo
  `sc-cookies.json` are gone.

### Fixed

- "Without a browser" in the panel shows the public profile field only while the saved setting really names no
  browser. Before, it switched on the click, even when saving the setting failed.

## [0.1.1] 2026-11-19

### Fixed

- Turning the browser session off now turns it off. `ballroom sc cookies -` and "Without a browser" in the panel
  stored an empty setting, and an empty setting means "take the browser that is signed in", so SoundCloud lists
  could still use a signed-in browser. The setting is now `none`, and no `yt-dlp` call and no profile request
  reads a browser then.
- The profile request to `soundcloud.com/you` carries only the cookies a browser itself would send there: domain
  exactly `soundcloud.com`, a path that covers `/you`, not expired. Before, every row whose domain ended in
  `soundcloud.com` went along, whatever its path. HttpOnly rows are now read like the others.
- The search field filters only the search. Words left in it no longer thin out LIKES, PLAYLISTS, UPLOADS or
  FAVORITES, where the field is not shown, so a list no longer claims that nothing in it matches.

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

[0.1.2]: https://github.com/rogertobler/omarchy-ballroom/releases/tag/v0.1.2
[0.1.1]: https://github.com/rogertobler/omarchy-ballroom/releases/tag/v0.1.1
[0.1.0]: https://github.com/rogertobler/omarchy-ballroom/releases/tag/v0.1.0
