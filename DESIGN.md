# Ballroom: why it is built this way

Sound is the one part of a desktop where a mistake is heard at once, and where the worst mistake is not a crash
but a jump: headphones at the level the speakers had, a microphone that opens without being asked, a player that
stops in the middle of a song because a device went away under it. Every decision below follows from that. Where
PipeWire or WirePlumber behave differently from what their documentation suggests, Ballroom goes by the behaviour.

"Closed" means something specific here. A failure ends quiet and muted: the output lower rather than higher, the
microphone shut rather than open. Nothing that goes wrong may end louder than it started.

## One command, one widget

Everything that has a rule behind it goes through the `ballroom` command: the default device and its cap, routes,
mutes per device, the equalizer, the stage. The widget reads `ballroom json` and acts through the same verbs a
terminal or a key binding uses, so a cap or a guard applies the same way wherever the change comes from. The two
main sliders in the panel act on PipeWire directly, as the built-in widget does, because a slider has to follow the
hand.

The lists in the panel come from `ballroom json` and not from Quickshell's live PipeWire model. Rebuilding a list
while a node is being removed has brought that model down; a reading from a separate process cannot take the shell
with it. The live model is read only where a reading would be too slow: the two main sliders, the number of nodes
(to notice that something came or went) and the level meters of the inputs while the panel is open.

## The rules every verb follows

The head of the `ballroom` command lists nine rules. Each of them answers something PipeWire or WirePlumber
actually does.

1. **Measure, then report.** After every write the graph is read again, and the answer comes from that reading,
   not from what was sent. `wpctl` exits 0 even for a profile that does not exist, and WirePlumber applies a new
   default or a new target asynchronously. So a write is followed by a short wait for the graph to say the same,
   and a verb that did not take says so. A filter that sleeps because nothing plays takes new values only when
   sound comes back; that is reported as pending, not as done.

2. **Volumes are cubic.** PipeWire keeps linear channel volumes; `wpctl`, `pactl` and Quickshell all show the cube
   root. 50 % on any slider is 0.125 inside PipeWire. Ballroom uses the same scale everywhere, so a cap of 50 %
   means the same thing as 50 % on the slider, and two tools never disagree about a level.

3. **No object id outlives one reading.** PipeWire hands ids out again after a restart or a hotplug, so an id from
   a minute ago may name another object now. Devices are named by `node.name`, streams by `object.serial`, and the
   id is looked up again right before each write. Nothing is recognised by `application.name` either: it carries
   whatever the application chose to call itself.

4. **Every call to a tool has a time limit.** A hung `wpctl` must not hang the bar. The command gives each tool
   three seconds by default and longer only where the work is known to take longer, such as asking `yt-dlp` about
   a playlist. The widget runs every verb under `/usr/bin/timeout` and stops a process that prints more than it
   could reasonably mean.

5. **WirePlumber is never restarted.** With a Bluetooth headset a restart costs about twelve seconds without
   sound. Ballroom also ships no WirePlumber or PipeWire configuration fragment: everything it changes, it changes
   at run time through metadata, `wpctl` and its own processes. What WirePlumber remembers by itself stays after
   Ballroom is removed, as it would after any mixer: the default output last set, where a stream was last sent, and
   the Bluetooth call mode setting (`ballroom bt auto`), which is saved with `wpctl settings`.

6. **A device that vanishes never plays through another one.** Switching a Bluetooth headset between music and
   call mode, or to another codec, makes its node go away and come back. In between, WirePlumber would move the
   sound to the next output, and a call meant for the headset would play on the speakers. So every other output is
   muted around the switch, and afterwards exactly those mutes are taken back: an output the user had muted stays
   muted. If the headset does not come back, the mutes stay and a warning says how to lift them: silence is the
   safe way for this to fail.

7. **No error text of a PipeWire tool is compared**, only exit codes and structured output. The words of a tool
   change with its version and its language; an exit code and a JSON field do not.

8. **The microphone is never opened on the side.** What Ballroom reads from inputs, the spectrum of the default
   input and a level per listed input, runs only while the panel is open and stops with it, never reads a muted
   input, and carries a name that says what it is. Switching to another input keeps it muted when the previous one
   was muted, and a scene may close a microphone but never opens one.

9. **A secret is never a process argument and never printed.** Every local user can read the arguments of every
   process in `/proc`. The DI.FM listen key comes in over stdin or a hidden prompt, goes to `mpv` over its socket,
   and is masked in every text Ballroom prints and in the stream title in the graph. What Ballroom remembers of a
   DI.FM stream is the channel, never the address.

## One writer at a time

The widget runs `apply` whenever something in the graph comes or goes, a click in the panel runs a verb beside it,
and a terminal or a key binding may run a third. Two of them changing a settings file, or restarting the
equalizer, at the same moment would lose one change or restart twice. So every verb that writes a settings file or
touches the equalizer takes a lock: a file in the runtime directory holding the writer's process id. A lock whose
process is gone is taken over; a lock that stays busy for five seconds is reported, not broken. Reading verbs never
take it, so the bar keeps reading while a writer works. Changing a level or a mute (`vol`, `mute`, `in`) writes no
file and takes no lock: it is one call to `wpctl`, read back like every other write.

Settings files are written whole, to a temporary file that is renamed into place, so a reader that comes every
second never sees half of one. A file that cannot be read is moved aside and replaced by defaults, never silently
overwritten.

## Caps, and `outputs-seen.json`

A cap is the level an output may arrive at, and it is for an output that arrives, not for one that is already
there. `apply` runs on every node that appears, including a stream that starts and the panel's own spectrum, and
capping then would pull a headset the user turned up to 70 % down to 50 % in the middle of a song.

So `apply` writes down which plugged in outputs it has seen, in `outputs-seen.json` in the runtime directory, and
caps only the ones that were not there last time. The file lives in the runtime directory on purpose: after a
login it is gone, and every output counts as arriving. An output that was there but unplugged counts as arriving
when it is plugged in again, since a headphone jack or a monitor port stays a node while nothing is in it.

The order is always the same: first down to the cap, then made the default. Never the other way round, not even
for the few milliseconds in between.

The kind of a device decides its cap. A Bluetooth headset says it is a headset in `device.form-factor` on its card,
never on its sink node, so the card's properties are read beneath the node's.

## Routes per setup, and unplugged ports

WirePlumber remembers a target per application by device name. That memory does not know where the machine is: an
application sent to the monitor at the desk is sent there again at another table, where that monitor is gone.
Ballroom keeps its rules per setup, the sorted names of the outputs that are plugged in, and `apply` decides per
stream: with a rule here, to its output; without one, on an output that a rule of another setup names, it is let go
to follow the default, because it sits there by WirePlumber's memory and not by choice. A stream on any other
output was put there by hand and stays.

A port with nothing plugged in stays a node, and WirePlumber keeps a stream on it. Such a stream is let go to the
default and comes back with its rule when the port is plugged in again. On some machines the display driver says
a monitor is gone while the sound card keeps reporting its port as available, and WirePlumber leaves the default on
a monitor that is not there. Ballroom therefore asks `/sys/class/drm`: with no external display connected, every
display port counts as unplugged, and Ballroom moves the default itself, capped first, and remembers the output that
was chosen in `undocked.json`. That note sits beside the settings and not in the runtime directory, because
WirePlumber keeps the default Ballroom set across a login, and the way back has to survive the login as well. The
default goes back only if it still stands where Ballroom put it.

## The equalizer is a PipeWire process of its own

The equalizer is a filter chain run by `ballroom-eq.service` as `pipewire -c ~/.config/ballroom/eq.conf`, a client
of the session's PipeWire. WirePlumber places it in front of the default output as a smart filter, by itself and
for whichever output is the default. Nothing in WirePlumber's configuration changes for it, which is how rule 5
holds.

**It is never stopped to switch it off.** When a node vanishes under a playing stream, many players pause, and a
rebuild plays the stream straight on the device for a moment without the preamp, which is the jump to loud this
design exists to prevent. So once the process runs, every change is a change of values, and "off" sets every
filter to neutral and leaves the process running. Only `eq restart` and `eq stop` end it, and the installer
restarts it after an update. Off, stop and the uninstaller all bring the output down by the preamp first and only
then take the preamp away, so none of them is louder for a moment.

**The filter graph has one fixed shape**: per channel, a 2 by 2 mixer for balance, mono and swap, a preamp, then 16
peaking filters, 4 low shelves and 4 high shelves. A filter at 0 dB passes the sound unchanged, so every preset
fits into the same graph, and switching presets is a change of values, never a restart. The configuration file
carries its shape (`fixed:16p4l4h`); when a later version changes the shape, the process is rebuilt once. A preset
that needs more filters of one kind than the shape holds is refused rather than cut.

The preamp is a high shelf at 0 Hz, which is a plain gain. PipeWire's filters follow the RBJ cookbook for peaks and
shelves alike, so the curve Ballroom computes and shows is the curve that is heard, and the automatic preamp is
that curve's highest point taken off, down to at most minus 24 dB.

**Every real change of a band clicks once.** A change of a builtin biquad resets it. So all changed values go to
the filter in one call, a value that did not change is not sent, a filter at 0 dB keeps its frequency and Q, and
the panel sends a band when the slider is let go, never while it is dragged. One change, one click.

**The preamp never goes without the output following it.** A running equalizer holds the sound down by its
preamp. When the preamp goes away, because the user switches the equalizer off or its process dies, the output is
brought down by the same amount so the loudness stays, and the level set is written down next to the level it came
from. When the preamp is back, the output is raised only if it still stands exactly where it was put, and never
above the level it came from or above its cap. A start that failed is not retried on every change in the graph,
and the configuration that last worked is kept until a new one has loaded.

## The stage over mpv's socket

The stage is `mpv` without a window and without a configuration of its own (`--no-config`, so a user's `mpv.conf`
cannot change what the stage does), run by `ballroom-stage.service` and driven over its JSON IPC socket in the
runtime directory. Every address goes over the socket, never as a process argument, because a DI.FM address
carries the listen key. Its sound is an ordinary stream named Ballroom, recognised by its `node.name`; mpv's own
volume is never touched, or two volumes would stack.

`mpv` runs with `--ytdl=no`. With it on, mpv hands every address to `yt-dlp` first, and a radio stream never plays.
Turning it on for one file only is a race: mpv loads its `yt-dlp` hook while the file already opens, and under load
the page is opened before the hook exists. So a SoundCloud page is resolved by `ballroom` with `yt-dlp -g`, and mpv
only ever gets a direct address. `mpv-mpris` is not loaded, because without a session bus it stalls mpv.

A live stream is not paused but stopped and remembered. mpv would keep buffering, and the sound after the pause
would lag behind the station by the length of the pause. Playing it again tunes in live. A track pauses in place.

Talking to the radio directory and to DI.FM happens inside the command, not through a separate tool: only https,
no redirects (a redirect could carry the key elsewhere), and an answer larger than a limit is refused, not cut,
because a cut list is a different list.

## SoundCloud and the browser session

SoundCloud has no sign in for third party players, so Ballroom uses the session of a browser that is already
signed in, the way `yt-dlp` can. To find that browser, the cookie stores are opened read only and only their host
column is read, never a value. A Chromium store is locked with a key from the desktop keyring, and `yt-dlp` needs
to be told which keyring; without it, it decrypts nothing and quietly returns only public tracks. So the keyrings
are tried, without network, and only a run that opened every cookie counts.

`yt-dlp` cannot export one site's cookies. To learn the profile name, it writes the whole jar to a file, which
Ballroom creates first itself (exclusive, no links followed, readable by the user only, with the one header line
`yt-dlp` needs to accept it), reads, and deletes before Ballroom sends its own request with the session. A signal deletes it too, and one left
behind by a kill is swept on the next run. The request carries only the rows a browser would send to that address
(`jarHeader`): domain exactly `soundcloud.com`, a path covering `/you`, not expired, nothing that could break the
header.

A browser session is read only after the user chose that browser (`soundcloudCookies` names it). An empty setting
and `none`, which `sc cookies -` stores, read no browser: no `yt-dlp` call and no profile request carries one. There
is no automatic choice behind an empty value, so a setting that was cleared stays off across updates. The panel
says "public only" only while the saved setting names no browser, not because a click asked for it.

## The widget around the command

Every process the widget starts gets a cleared environment with a short list of variables, a fixed `PATH`, a
deadline and a limit on its output. A variable exported in the session must not change what Ballroom reads or
where a key goes, and a file placed in `~/.local/bin` must not replace `wpctl` for every panel call. The command
fixes its own `PATH` for the same reason.

The settings page is built from the schema in `manifest.json`, and the command checks a value against the same
schema before it hands it to the shell. The command keeps the same bounds in its own table, which has to be kept
equal to the manifest by hand; the panel never invents a bound of its own. A secret never goes into the schema, because the shell keeps widget settings in plain text.

Ballroom is a clone of the built-in audio widget rather than a second audio widget beside it. Two widgets that both
set the default output fight over it; one that takes the other's place while it is enabled cannot.
