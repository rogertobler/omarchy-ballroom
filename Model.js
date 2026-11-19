.pragma library

// Pure helpers for the Ballroom widget. Nothing here touches the shell: it turns the JSON that `ballroom json`
// prints into the strings and numbers the bar and the panel bind to, which is why the bench can test it with
// bun while the QML around it only runs inside the shell.
//
// Glyphs are the ones Omarchy's own audio panel uses, so they are known to exist in the bar font.
var G_MUTED = "\uEEE8"
var G_HIGH = "\uF028"
var G_MID = "\uF027"
var G_LOW = "\uF026"
var G_HEADPHONES = "\u{F02CB}"
var G_BLUETOOTH = "\u{F00AF}"
var G_HDMI = "\u{F0379}"
var G_SPEAKER = "\u{F04C3}"
var G_MIC = "\u{F036C}"
var G_MIC_OFF = "\u{F036D}"
var G_WEBCAM = "\u{F0100}"
var G_STREAM = "\u{F057E}"
var G_STREAM_OFF = "\u{F075F}"

function parseState(raw) {
  try {
    var d = JSON.parse(String(raw || "").trim())
    return d && typeof d === "object" && !Array.isArray(d) ? d : null
  } catch (e) {
    return null
  }
}

function list(state, key) {
  return state && state[key] instanceof Array ? state[key] : []
}

function defaultOutput(state) {
  var outs = list(state, "outputs")
  for (var i = 0; i < outs.length; i++) if (outs[i].isDefault) return outs[i]
  return null
}

function defaultInput(state) {
  var ins = list(state, "inputs")
  for (var i = 0; i < ins.length; i++) if (ins[i].isDefault) return ins[i]
  return null
}

function percent(v) {
  var n = Number(v)
  return isFinite(n) ? Math.round(n * 100) : 0
}

// The bar icon says what carries the sound and how loud: headphones and Bluetooth by kind, the speaker by level.
function outputGlyph(device, volume, muted) {
  if (!device) return G_MUTED
  if (muted) return G_MUTED
  if (device.kind === "headphones") return G_HEADPHONES
  if (device.api === "bluez5") return G_BLUETOOTH
  var v = volume === undefined ? Number(device.volume) : Number(volume)
  if (v >= 0.67) return G_HIGH
  if (v >= 0.34) return G_MID
  if (v > 0) return G_LOW
  return G_MUTED
}

function deviceGlyph(device) {
  if (!device) return G_SPEAKER
  var text = String(device.label || "") + " " + String(device.description || "")
  if (device.kind === "headphones") return G_HEADPHONES
  if (device.api === "bluez5") return G_BLUETOOTH
  if (/hdmi|displayport/i.test(text)) return G_HDMI
  return G_SPEAKER
}

// What kind of input it is. Whether it is muted is the mute button's business, see muteGlyph.
function inputGlyph(device) {
  if (!device) return G_MIC
  if (device.api === "bluez5") return G_BLUETOOTH
  if (/webcam|camera/i.test(String(device.description || "") + " " + String(device.label || ""))) return G_WEBCAM
  return G_MIC
}

function muteGlyph(section, muted) {
  if (section === "input") return muted ? G_MIC_OFF : G_MIC
  return muted ? G_STREAM_OFF : G_STREAM
}

function streamGlyph(stream) {
  return stream && stream.mute ? G_STREAM_OFF : G_STREAM
}

// What the panel lists: nothing hidden, nothing unplugged unless it is the default, the default first, then by
// name. A port with nothing in it is still a device to PipeWire; it is not a place sound can go.
function visibleDevices(state, key) {
  var out = []
  var all = list(state, key)
  for (var i = 0; i < all.length; i++) {
    var d = all[i]
    if (d.hidden) continue
    if (d.available === false && !d.isDefault) continue
    out.push(d)
  }
  out.sort(function (a, b) {
    if (a.isDefault !== b.isDefault) return a.isDefault ? -1 : 1
    return String(a.label).localeCompare(String(b.label))
  })
  return out
}

// The outputs that are plugged in, as one string. A plug that is pulled or pushed leaves the number of nodes
// alone, so the service compares this between readings to know when apply has to run.
function pluggedKey(state) {
  var names = []
  var all = list(state, "outputs")
  for (var i = 0; i < all.length; i++) if (all[i].available !== false) names.push(String(all[i].name))
  return names.sort().join("\n")
}

function playing(state) {
  var out = []
  var all = list(state, "streams")
  for (var i = 0; i < all.length; i++) if (all[i].direction === "playback") out.push(all[i])
  return out
}

// Who records from a microphone. Recording the monitor of an output (a spectrum, a screen recorder taking the
// desktop sound) is not listening to the room, so it does not count. Ballroom's own spectrum never arrives
// here: `ballroom json` leaves it out. The shell's level meter is Ballroom's own too while the panel runs one
// (ownMeter), and a listener otherwise.
function listening(state, ownMeter) {
  var names = []
  var all = list(state, "streams")
  for (var i = 0; i < all.length; i++) {
    var s = all[i]
    if (s.direction !== "record" || s.fromMonitor) continue
    if (ownMeter && s.meter) continue
    if (names.indexOf(s.app) < 0) names.push(s.app)
  }
  return names
}

function labelOf(state, name) {
  var all = list(state, "outputs").concat(list(state, "inputs"))
  for (var i = 0; i < all.length; i++) if (all[i].name === name) return String(all[i].label)
  return name ? String(name) : "nowhere"
}

// One word for how loud the room is.
function mood(volume, muted) {
  if (muted) return "Muted"
  var p = Math.round(Number(volume) * 100)
  if (!(p > 0)) return "Silence"
  if (p < 15) return "Whisper"
  if (p < 30) return "Murmur"
  if (p < 50) return "Lounge"
  if (p < 70) return "Dance floor"
  if (p < 85) return "Full swing"
  if (p < 100) return "Grand ball"
  return "Gala"
}

// The line under the title: the mood, and the codec when a Bluetooth device carries the sound. Volume and mute
// come from the live slider when the panel has them, from the last reading otherwise.
function heroLine(state, volume, muted) {
  var d = defaultOutput(state)
  if (!d) return "NO OUTPUT"
  var v = volume === undefined ? Number(d.volume) : Number(volume)
  var m = muted === undefined ? !!d.mute : !!muted
  var text = mood(v, m).toUpperCase()
  if (d.codec) text += " · " + String(d.codec).toUpperCase()
  return text
}

// The line under an application's name. The dropdown beside its level says where it is sent (DEFAULT, or the
// output of its rule), so this one only says what the dropdown cannot: that the rule's output is unplugged and the
// application plays on the default until it is back.
function streamLine(state, stream) {
  if (!stream || !stream.device) return ""
  var d = defaultOutput(state)
  // No rule: the dropdown says DEFAULT, and the line says where the sound is measured if that is not the default
  // (a hand move elsewhere, or a memory WirePlumber kept). What the panel shows is the reading, never the intent.
  if (!stream.routed) return d && stream.device !== d.name ? "plays on " + labelOf(state, stream.device) : ""
  if (stream.routed === stream.device) return ""
  var all = list(state, "outputs"), target = null
  for (var i = 0; i < all.length; i++) if (all[i].name === stream.routed) target = all[i]
  // Unplugged is said only when the reading says so; otherwise the stream is simply not there yet, or was moved.
  if (target && target.available === false) return labelOf(state, stream.routed) + " is unplugged, plays on the default"
  return "plays on " + labelOf(state, stream.device)
}

// ownMeter: the panel's own level bars run while it is open, and they are not listeners.
// Every part of the widget in the bar tells the whole story on hover: the output and its level, what plays
// (nowPlaying) and what the pause button holds, who listens. Only the last line differs, the hint: what a click
// does on the part under the pointer.
var HINT_OUTPUT = "Click: panel, right-click: mute, middle-click: microphone, wheel: volume"
function tooltip(state, ownMeter, playing, paused, hint) {
  var d = defaultOutput(state)
  var lines = [d ? String(d.label) + "  " + percent(d.volume) + " %" + (d.mute ? ", muted" : "") : "No output"]
  for (var n = 0; playing && n < playing.length; n++) lines.push("Playing: " + String(playing[n]))
  for (var q = 0; paused && q < paused.length; q++) lines.push("Paused: " + String(paused[q]))
  var who = listening(state, ownMeter)
  if (who.length) lines.push("Listening: " + who.join(", "))
  if (hint) lines.push(String(hint))
  return lines.join("\n")
}

// cava delivers as many bands as it was asked for; the bar may want fewer. Each bar takes the loudest band it
// covers, so a narrow bar never hides a peak.
function barBands(bands, count) {
  var src = bands instanceof Array ? bands : []
  var n = Math.max(1, Math.floor(count))
  var out = []
  if (!src.length) {
    for (var z = 0; z < n; z++) out.push(0)
    return out
  }
  for (var i = 0; i < n; i++) {
    var from = Math.floor(i * src.length / n)
    var to = Math.max(from + 1, Math.floor((i + 1) * src.length / n))
    var peak = 0
    for (var j = from; j < to && j < src.length; j++) peak = Math.max(peak, Number(src[j]) || 0)
    out.push(Math.max(0, Math.min(1, peak)))
  }
  return out
}

function parseBands(line) {
  var d = parseState(line)
  return d && d.bands instanceof Array ? d.bands : null
}

function quiet(bands) {
  if (!(bands instanceof Array)) return true
  for (var i = 0; i < bands.length; i++) if (Number(bands[i]) > 0.02) return false
  return true
}

// ---- sound ----

function sound(state) {
  return state && state.sound && typeof state.sound === "object" ? state.sound : null
}

// The preset after (dir 1) or before (dir -1) the current one, round the list.
function presetStep(snd, dir) {
  if (!snd || !(snd.presets instanceof Array) || !snd.presets.length) return ""
  var i = snd.presets.indexOf(snd.preset)
  var n = snd.presets.length
  return snd.presets[((i < 0 ? 0 : i) + (dir < 0 ? -1 : 1) + n) % n]
}

// Points of the equalizer's curve in a box of width x height, 0 dB in the middle, +-range dB at the edges. The
// curve comes computed from `ballroom json`: 64 frequencies from 20 Hz to 20 kHz, evenly spaced on a log scale.
function curvePoints(snd, width, height, range) {
  var pts = []
  var c = snd && snd.curve instanceof Array ? snd.curve : []
  var r = range > 0 ? range : 12
  for (var i = 0; i < c.length; i++) {
    var db = Math.max(-r, Math.min(r, Number(c[i].db) || 0))
    pts.push({ x: c.length > 1 ? width * i / (c.length - 1) : 0, y: height / 2 - db / r * height / 2 })
  }
  return pts
}

// The range the curve is drawn in: 12 dB, or more when the curve goes further, in steps of 6.
function curveRange(snd) {
  var c = snd && snd.curve instanceof Array ? snd.curve : []
  var m = 0
  for (var i = 0; i < c.length; i++) m = Math.max(m, Math.abs(Number(c[i].db) || 0))
  return Math.max(12, Math.ceil(m / 6) * 6)
}

function balanceText(v) {
  var n = Math.round(Number(v) * 100)
  if (!n) return "Center"
  return n < 0 ? "L " + (-n) + "%" : "R " + n + "%"
}

function soundLine(snd, state) {
  if (!snd) return ""
  if (!snd.enabled) return "Off"
  var where = snd.device ? labelOf(state, snd.device) : "no output"
  return (snd.running ? "" : "not running · ") + snd.preset + " · " + where
}

// The line in the panel foot: the first thing the command warns about (an unplugged default, an equalizer that
// should run but does not, a foreign filter), or nothing.
function healthLine(state) {
  var h = state && state.health instanceof Array ? state.health : []
  return h.length ? String(h[0]) : ""
}

// Whether the preset in use was made here. The state says it of the one in use only, not of the whole list, so
// that is the one the panel may offer to delete.
function presetIsOwn(snd) { return !!snd && snd.builtin === false }

// ---- one device's own settings ----

// What the row under a device offers. An input has no kind and no limit of its own: a limit is what an output is
// brought down to before it is played on, and an input is not played on.
function deviceCapText(device) {
  if (!device) return ""
  if (device.cap === null || device.cap === undefined) return "no limit"
  return percent(device.cap) + " %"
}
// What can be set on a Bluetooth device, found by the node the panel has in hand. The graph alone does not say
// which codecs it offers, so the command puts them in the state.
function btOf(state, device) {
  if (!device) return null
  var all = list(state, "bluetooth")
  for (var i = 0; i < all.length; i++) if (String(all[i].node) === String(device.name)) return all[i]
  return null
}
// A band, named by where it sits: the two at the ends shape everything below or above their frequency, the
// ones between them lift or lower a place in the middle.
function bandLabel(band) {
  if (!band) return ""
  var f = Number(band.freq)
  var hz = f >= 1000 ? (Math.round(f / 100) / 10) + "k" : String(Math.round(f))
  if (band.type === "lowshelf") return "low " + hz
  if (band.type === "highshelf") return "high " + hz
  return hz + " Hz"
}

// The limit a device of a kind starts at, as words the same dropdown can hold as a device's own limit.
function classCapText(state, kind) {
  var caps = state && state.caps ? state.caps : null
  var v = caps ? caps[kind] : undefined
  if (v === null || v === undefined) return "no limit"
  return percent(v) + " %"
}

// A Bluetooth device is known by its address, which is what the bt verbs take; a device that is not one has none.
function btAddress(device) {
  if (!device || device.api !== "bluez5") return ""
  var m = /([0-9A-Fa-f]{2}[:_]){5}[0-9A-Fa-f]{2}/.exec(String(device.name || ""))
  return m ? m[0].replace(/_/g, ":") : ""
}

// ---- the panel's own sections ----

// Every section the panel can show, in the order it is built with. What the user sees is a list of ids kept as
// one setting: the order is the order of that list, and an id with a dash in front is switched off. An id the
// setting does not mention is appended and shown, so a section added later is never invisible; an id nobody
// knows any more is dropped. That way the setting can lag behind the plugin in both directions.
// The outputs and the inputs stand under their master level as its children, one section each: a level and the
// devices it is the level of are one thing. They used to be two lists of their own at the foot of the panel, which
// drew the same rows twice (the master is the default device's row again) and put the choice of device a long
// scroll away from its level. An old setting that still names those lists loses them here, like any unknown id.
var SECTIONS = [
  { id: "output", title: "Output, with its devices" },
  { id: "input", title: "Input, with its devices" },
  { id: "sound", title: "Equalizer" },
  { id: "playing", title: "Playing, with the transport" },
  { id: "library", title: "Library: radio, SoundCloud, DI.FM" },
]
// The sections that fold shut under their own line. The panel remembers which ones the user folded, in the same
// shape as the sections line: an id on its own is open, an id with a dash in front of it is folded. An id the
// line does not mention has never been folded or unfolded, and then the panel's own default holds.
var FOLDABLE = ["output", "input", "sound", "library"]
function foldState(value) {
  var out = {}
  var parts = String(value || "").trim().split(/\s+/)
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i], shut = p.charAt(0) === "-"
    var id = shut ? p.slice(1) : p
    if (FOLDABLE.indexOf(id) >= 0) out[id] = !shut
  }
  return out
}
function foldLine(value, id, open) {
  var st = foldState(value)
  if (FOLDABLE.indexOf(String(id)) >= 0) st[String(id)] = open === true
  var out = []
  for (var i = 0; i < FOLDABLE.length; i++) {
    var k = FOLDABLE[i]
    if (st[k] === undefined) continue
    out.push(st[k] ? k : "-" + k)
  }
  return out.join(" ")
}
// What a folded list says instead of its rows: how many there are, so that folding hides the rows and not the
// fact that they are there.
function foldNote(count, word) {
  var n = Number(count) || 0
  return n === 1 ? "1 " + word : n + " " + word + "s"
}
function sectionTitle(id) {
  for (var i = 0; i < SECTIONS.length; i++) if (SECTIONS[i].id === id) return SECTIONS[i].title
  return String(id || "")
}
function sectionPlan(setting) {
  var known = {}
  for (var i = 0; i < SECTIONS.length; i++) known[SECTIONS[i].id] = true
  var out = [], seen = {}
  var parts = String(setting || "").split(",")
  for (var p = 0; p < parts.length; p++) {
    var t = parts[p].trim()
    if (!t) continue
    var on = t.charAt(0) !== "-"
    var id = on ? t : t.slice(1)
    if (!known[id] || seen[id]) continue
    seen[id] = true
    out.push({ id: id, on: on, title: sectionTitle(id) })
  }
  for (var k = 0; k < SECTIONS.length; k++)
    if (!seen[SECTIONS[k].id]) out.push({ id: SECTIONS[k].id, on: true, title: SECTIONS[k].title })
  return out
}
// The plan back into the one line the setting holds.
// A section dropped on another one: it leaves its place and takes the one it was dropped on. Dropped lower down
// it lands after that section, dropped higher up before it, and both fall out of the same two steps, because
// taking it out first shifts everything below it by one.
function sectionDropped(plan, id, targetId) {
  var list = (plan || []).slice()
  var from = -1, to = -1
  for (var i = 0; i < list.length; i++) {
    if (list[i].id === id) from = i
    if (list[i].id === targetId) to = i
  }
  if (from < 0 || to < 0 || from === to) return list
  var moved = list.splice(from, 1)[0]
  list.splice(to, 0, moved)
  return list
}
function sectionSetting(plan) {
  var out = []
  for (var i = 0; i < (plan || []).length; i++) out.push((plan[i].on ? "" : "-") + plan[i].id)
  return out.join(",")
}
// The plan with one entry moved by a step, for the two arrows beside a row.
function sectionMoved(plan, id, delta) {
  var out = (plan || []).slice()
  for (var i = 0; i < out.length; i++) {
    if (out[i].id !== id) continue
    var j = i + delta
    if (j < 0 || j >= out.length) return out
    var tmp = out[i]; out[i] = out[j]; out[j] = tmp
    return out
  }
  return out
}
function sectionToggled(plan, id) {
  var out = (plan || []).slice()
  for (var i = 0; i < out.length; i++) if (out[i].id === id) out[i] = { id: id, on: !out[i].on, title: out[i].title }
  return out
}

// The diagnosis, as the page prints it: one line per check with its state, and the summary last.
function doctorLines(answer) {
  var d = parseState(answer)
  if (!d || !(d.checks instanceof Array)) return []
  var out = []
  for (var i = 0; i < d.checks.length; i++)
    out.push({ key: String(d.checks[i].key), state: String(d.checks[i].state), text: String(d.checks[i].text) })
  return out
}

// ---- settings ----

// The settings page is the manifest's schema, in groups. A key that the manifest gains and this list has not
// still shows, under "Other": the page can lag behind the manifest but never hide a setting.
var SETTING_GROUPS = [
  { title: "Panel", keys: ["title", "stageButton", "refreshIntervalSec"] },
  { title: "Sections", keys: ["sections"] },
  // The switch first, then what it looks like, then the two that watch the microphone: a row that only means
  // something while the one above it is on belongs under it.
  { title: "Spectrum", keys: ["spectrum", "spectrumBars", "spectrumColor", "inputSpectrum", "inputMeters"] },
  // The two sources that need something set up belong together: a name and a browser for SoundCloud, a listen
  // key for DI.FM. The key is no widget setting (it is a secret), so it rides along as an extra in this group.
  { title: "Library sources", keys: ["soundcloudUser", "soundcloudCookies"], extra: "dikey" },
]
function settingGroups(schema) {
  var byKey = {}, list = schema instanceof Array ? schema : []
  for (var i = 0; i < list.length; i++) if (list[i] && list[i].key) byKey[String(list[i].key)] = list[i]
  var out = [], placed = {}
  for (var g = 0; g < SETTING_GROUPS.length; g++) {
    var rows = []
    for (var k = 0; k < SETTING_GROUPS[g].keys.length; k++) {
      var d = byKey[SETTING_GROUPS[g].keys[k]]
      if (d) { rows.push(d); placed[String(d.key)] = true }
    }
    if (rows.length) out.push({ title: SETTING_GROUPS[g].title, rows: rows, extra: SETTING_GROUPS[g].extra || "" })
  }
  var rest = []
  for (var j = 0; j < list.length; j++) if (list[j] && list[j].key && !placed[String(list[j].key)]) rest.push(list[j])
  if (rest.length) out.push({ title: "Other", rows: rest, extra: "" })
  return out
}
// The rows in the order the arrows walk them, so a cursor number means the same thing as the eye sees.
function settingOrder(groups) {
  var out = []
  for (var g = 0; g < (groups || []).length; g++)
    for (var r = 0; r < groups[g].rows.length; r++) out.push(groups[g].rows[r])
  return out
}
// What the page prints under a row. It used to be the first sentence only, which left "Optional." and "While the
// panel is closed." standing alone under a control nobody could place. The whole description is short enough.
function settingHelp(def) {
  return def && def.description ? String(def.description).trim() : ""
}
// The browsers a dropdown offers. Only browsers: choosing one is the exception, and letting Ballroom choose
// again is not a browser, so it is not in the list. The row says when one was chosen by hand and takes it back.
function browserOptions(browsers, current) {
  var out = []
  var all = browsers instanceof Array ? browsers : []
  for (var i = 0; i < all.length; i++) {
    var b = all[i]
    if (!b || !b.browser) continue
    out.push(String(b.browser) + (b.soundcloud ? " (signed in)" : b.readable === false ? " (store locked)" : ""))
  }
  // A browser named by hand that is not among the ones found here still stands in the list, and says so. The
  // list otherwise would fall back to another name and claim a browser that is not the one in the setting.
  var c = browserName(current)
  if (c) {
    for (var j = 0; j < out.length; j++) if (out[j].split(" ")[0] === c) return out
    out.push(c + " (not found)")
  }
  return out
}
// The browser out of what `ballroom sc cookies` holds: BROWSER[+KEYRING][:PROFILE].
function browserName(spec) {
  var c = String(spec || "").trim()
  // "none" is the setting that reads no browser at all; it names none.
  return c && c !== "none" ? c.split(":")[0].split("+")[0] : ""
}
// What the list stands on: the browser that was named by hand, or, when none was, the one Ballroom takes by
// itself, which is the one that holds a session.
function browserValue(browsers, current) {
  var opts = browserOptions(browsers, current)
  var name = browserName(current)
  if (name) {
    for (var i = 0; i < opts.length; i++) if (opts[i].split(" ")[0] === name) return opts[i]
  }
  var all = browsers instanceof Array ? browsers : []
  for (var j = 0; j < all.length; j++) if (all[j] && all[j].soundcloud) return opts[j]
  return opts.length ? opts[0] : ""
}
// The same choice written for a button: the browser's name reads as a name, the note after it stays as it is.
// Only for the eye; what goes back to the command is the option itself, through browserTarget.
function browserLabel(option) {
  var t = String(option || "")
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : ""
}
// Back to what `ballroom sc cookies` wants: the name of that browser.
function browserTarget(label) { return label ? String(label).split(" ")[0] : "" }

// ---- stage ----

var G_RADIO = "\u{F0439}"
var G_SOUNDCLOUD = "\u{F04C1}"
var G_WAVE = "\u{F147D}"
var G_NOTE = "\u{F075A}"
var G_PLAY = "\u{F040A}"
var G_PAUSE = "\u{F03E4}"
var G_NEXT = "\u{F04AD}"
var G_PREV = "\u{F04AE}"
var G_STOP = "\u{F04DB}"
var G_STAR = "\u{F04CE}"
var G_STAR_OFF = "\u{F04D2}"
var G_CLOSE = "\u{F0156}"
var G_CHEVRON_DOWN = "\u{F0140}"
var G_CHEVRON_LEFT = "\u{F0141}"
var G_CHEVRON_RIGHT = "\u{F0142}"
var G_CHEVRON_UP = "\u{F0143}"

function stage(state) {
  return state && state.stage && typeof state.stage === "object" ? state.stage : null
}

function stageGlyph(kind) {
  if (kind === "radio") return G_RADIO
  if (kind === "soundcloud") return G_SOUNDCLOUD
  if (kind === "di") return G_WAVE
  return G_NOTE
}

var SOURCE_NAMES = { radio: "Radio", soundcloud: "SoundCloud", di: "DI.FM" }
// The library's tabs: the three sources to search, and the favorites of all of them together.
var SOURCE_TABS = { radio: "RADIO", soundcloud: "SOUNDCLOUD", di: "DI.FM", fav: "FAVORITES", recent: "RECENT" }
function sourceTab(source) { return SOURCE_TABS[source] || String(source || "").toUpperCase() }
// The source of an entry, in words. On the FAVORITES tab that is the one thing a row has to say beside its name:
// the tab holds all sources at once, and a glyph for one of them means nothing to anyone who has not learned it.
function sourceName(kind) { return SOURCE_NAMES[kind] || String(kind || "") }

// The outputs a stream can be sent to, as a dropdown takes them. Hidden devices and the equalizer's own node are
// not places to send anything.
// The first entry of the dropdown beside a stream: the application follows the default output, whichever that
// is in this setup. It names the default, so the row says where the sound goes without a second line. It is
// recognised by its first word, not the whole text: the default can change between opening the list and the
// click, and the click must still mean follow.
var ROUTE_DEFAULT = "DEFAULT"
function routeDefault(state) {
  var d = defaultOutput(state)
  return d ? ROUTE_DEFAULT + " · " + String(d.label) : ROUTE_DEFAULT
}
function isRouteDefault(label) { return String(label || "").indexOf(ROUTE_DEFAULT) === 0 }
// The dropdown holds DEFAULT and then the plugged-in outputs. A rule that points at an output the list does not
// show (one the user hid) is listed too, so the dropdown never shows another output than the rule.
function routeOptions(state, stream) {
  var out = [routeDefault(state)]
  var all = visibleDevices(state, "outputs")
  // An unplugged default is shown among the devices, but a rule is chosen among the plugged-in ones only, and
  // the command refuses the rest; so the list does not offer them.
  for (var i = 0; i < all.length; i++) if (all[i].available !== false) out.push(String(all[i].label))
  if (stream && stream.routed) {
    var l = labelOf(state, stream.routed)
    if (out.indexOf(l) < 0) out.push(l)
  }
  return out
}
// What the dropdown stands on: where the application is sent. DEFAULT while no rule holds in this setup, the
// output of its rule otherwise. It used to name the output the stream played on, which looked like a choice
// while it was none, and a choice made there was a rule for good without the dropdown ever saying so.
function routeValue(state, stream) {
  if (!stream) return ""
  return stream.routed ? labelOf(state, stream.routed) : routeDefault(state)
}
// From the chosen entry back to what the command wants: "follow" for DEFAULT, the name of the device otherwise.
function routeTarget(state, label) {
  if (!label) return ""
  // A device first: an output the user named "DEFAULT DAC" is that output, not the first entry.
  var all = visibleDevices(state, "outputs")
  for (var i = 0; i < all.length; i++) if (String(all[i].label) === label) return all[i].name
  if (isRouteDefault(label)) return "follow"
  return ""
}
// The order of the tabs: what was kept comes first as soon as there is something kept, because that is what gets
// chosen most. With nothing kept it stands last, where an empty tab is out of the way.
function sourceTabs(st) {
  var kept = st && st.favorites instanceof Array && st.favorites.length > 0
  var base = kept ? ["fav", "radio", "soundcloud", "di"] : ["radio", "soundcloud", "di", "fav"]
  // What played before is worth a tab of its own: it is the shortest way back to something one heard and did
  // not keep. It stands last, because it fills itself and nobody goes looking for it first.
  if (st && st.recent instanceof Array && st.recent.length > 0) base.push("recent")
  return base
}
// Under SOUNDCLOUD, the four things a profile holds beside the search. One at a time: the command keeps the one
// last asked for, and the panel asks for the one its row is on.
var SC_VIEWS = ["search", "likes", "playlists", "uploads"]
// The held list, but only if it is the one asked for AND belongs to the profile that is set now: after the name
// changes, the old profile's rows would sit under a caption naming it while the setting says someone else.
function scList(st, view, user) {
  var l = st && st.sclist ? st.sclist : null
  if (!l || l.what !== view || !(l.items instanceof Array)) return null
  return !user || String(l.user) === String(user) ? l : null
}
// Whether a tab can show anything yet. DI.FM plays only with a listen key, so without one the tab holds the
// field that asks for it and nothing else: a search, a channel list and a "load more" that end in "needs the
// listen key" are a promise the tab cannot keep.
// Whether a source can be used at all, or wants setting up first. DI.FM plays with a premium listen key and
// with nothing else; SoundCloud wants either a browser session to read or the name of a profile, and until one
// of the two is there the tab holds the question and nothing else: a search field and a row of lists that
// cannot answer are furniture.
function sourceUsable(st, source, scUser, scCookies) {
  if (source === "di") return !!st && !!st.diKey
  if (source === "soundcloud") return String(scUser || "").trim() !== "" || browserName(scCookies) !== ""
  return true
}
// The rules whose application is not making a sound right now: they have no row among the streams, so they are
// invisible unless they are asked for. A rule holds whether its program runs or not.
function routeGhosts(state) {
  var rules = list(state, "routes")
  var live = playing(state)
  var out = []
  for (var i = 0; i < rules.length; i++) {
    var found = false
    for (var j = 0; j < live.length; j++) if (String(live[j].app) === String(rules[i].app)) { found = true; break }
    if (!found) out.push(rules[i])
  }
  return out
}

// The line under STAGE: what state the stage is in, in words. The state is what mpv reports, never what was
// last asked of it.
function stageLine(st) {
  if (!st) return ""
  if (!st.available) return "needs mpv"
  if (!st.running) return "off"
  if (st.state === "playing") return st.buffering ? "buffering" : "on air"
  if (st.state === "loading") return "tuning in"
  return String(st.state || "")
}

// Whether the stage is under way: a pause is what it offers then, a play otherwise.
function stagePlaying(st) {
  return !!st && (st.state === "playing" || st.state === "loading")
}

// The players that report over MPRIS, the browser or a music player, as plain rows. playerctld is left out: it
// mirrors another player, and the one it mirrors would be counted twice. So is a player that can neither pause
// nor play, since the button would promise what it cannot do.
function mediaPlayers(rows) {
  var out = []
  // By length, not instanceof: the rows are built in the widget, and a list from QML need not be this Array.
  var src = rows && typeof rows.length === "number" ? rows : []
  for (var i = 0; i < src.length; i++) {
    var p = src[i]
    if (!p) continue
    var key = String(p.dbusName || "")
    if (!key || key.toLowerCase().indexOf("playerctld") >= 0 || String(p.desktopEntry || "").toLowerCase() === "playerctld") continue
    var canPause = !!(p.canPause || p.canTogglePlaying)
    var canPlay = !!(p.canPlay || p.canTogglePlaying)
    if (!canPause && !canPlay) continue
    var name = String(p.identity || p.desktopEntry || "") || key.replace(/^org\.mpris\.MediaPlayer2\./, "").replace(/\.instance[0-9]+$/, "")
    out.push({ key: key, playing: p.isPlaying === true, canPause: canPause, canPlay: canPlay, name: name,
               title: String(p.trackTitle || ""), artist: String(p.trackArtist || "") })
  }
  return out
}

// A player in one line: who plays, then the track and its artist when the player says them.
function mediaLabel(x) {
  var track = [x.title, x.artist].filter(function (t) { return t !== "" }).join(" · ")
  return track ? x.name + ": " + track : x.name
}
function stageLabel(st) {
  return String(st.title) + (st.subtitle ? " · " + String(st.subtitle) : "")
}

// What plays right now, the stage and every player, one line each: the station and the song it announces, the
// browser and its track. Everything that plays, whether the button can pause it or not.
function nowPlaying(st, players) {
  var out = []
  if (st && st.running && String(st.title || "") !== "" && stagePlaying(st))
    out.push((st.state === "loading" ? "tuning in " : "") + stageLabel(st))
  var list = mediaPlayers(players)
  for (var i = 0; i < list.length; i++) if (list[i].playing) out.push(mediaLabel(list[i]))
  return out
}

// The pause button in the bar. One click hushes everything that plays and can be paused, the stage and every
// player alike; the next plays again exactly what that click paused, and nothing else. So the button never has
// to guess which player is meant. A player the user paused somewhere else is not offered: a browser keeps
// reporting a paused tab, and the button would never go. A paused stage is, as its own row in PLAYING offers it.
// Gone while nothing plays and nothing waits. The glyph is the state the players report, never the last click.
function barMedia(st, players, held) {
  var list = mediaPlayers(players)
  var keep = []
  for (var h = 0; held && h < held.length; h++) keep.push(String(held[h]))
  var loaded = !!st && !!st.running && String(st.title || "") !== ""
  var stageOn = loaded && stagePlaying(st)
  var stageHeld = loaded && st.state === "paused"
  var stageName = loaded ? stageLabel(st) : ""
  var playing = [], waiting = []
  for (var i = 0; i < list.length; i++) {
    var p = list[i]
    if (p.playing && p.canPause) playing.push(p)
    else if (!p.playing && p.canPlay && keep.indexOf(p.key) >= 0) waiting.push(p)
  }
  function keys(xs) { return xs.map(function (x) { return x.key }) }
  // What plays is told by nowPlaying; what waits is the button's own, so it travels with it for the tooltip.
  if (stageOn || playing.length)
    return { glyph: G_PAUSE, pausing: true, stage: stageOn, keys: keys(playing), paused: [], hint: "Click: pause, right-click: stop" }
  if (stageHeld || waiting.length) {
    var then = (stageHeld ? [stageName] : []).concat(waiting.map(mediaLabel))
    return { glyph: G_PLAY, pausing: false, stage: stageHeld, keys: keys(waiting), paused: then, hint: "Click: play, right-click: stop" }
  }
  return null
}

// The rows of the library: what the chosen tab holds. RADIO, SOUNDCLOUD and DI.FM show the last results (for
// DI.FM without a search, every channel) and for SoundCloud the likes of the account; FAVORITES shows what was
// kept, every source together. A row carries the id to send when it is played, starred or removed, whether it
// is already a favorite, its group, and whether it is the first of its group (the panel puts the group caption
// above that one, and an empty group has none).
// Everything that is held becomes a row. There used to be a limit here with a button to raise it, which was a
// button that changed nothing anyone could see: the box is ten rows high and scrolls, so the rows past the
// tenth were already only a scroll away. What is left is asking the source for its next page, a real errand.
// What the field narrows: while its words are not the ones the held results were fetched with, they filter what
// is shown. So typing narrows the DI.FM channels at once, and a search whose results just came back is shown
// whole, tag matches and all, because then the field says exactly what was asked for.
function rowFilter(st, source, scView, text) {
  var t = String(text || "").trim().toLowerCase()
  if (!t) return ""
  // The field stands only where one searches: not over FAVORITES and not over a SoundCloud list. Words that are
  // not to be seen must not thin out a list, or LIKES says nothing matches a search made on another tab.
  if (source === "fav" || (source === "soundcloud" && scView && scView !== "search")) return ""
  var r = st && st.results && st.results.items instanceof Array && (!source || st.results.kind === source) ? st.results : null
  if (r && String(r.query || "").trim().toLowerCase() === t) return ""
  return t
}
function matches(x, words) {
  if (!words.length) return true
  var hay = (String(x.title || "") + " " + String(x.subtitle || "")).toLowerCase()
  for (var i = 0; i < words.length; i++) if (hay.indexOf(words[i]) < 0) return false
  return true
}

// Ten rows at a time, and the page is turned by hand. A list that scrolls inside a panel that scrolls catches
// the wheel: the pointer crosses the list on its way down the panel and the panel stops moving. Ten rows that
// stand still, with a way to the next ten, cost a click and take that trap away.
var PAGE = 10
function stageRows(st, source, libraryOpen, scView, filter, scUser, page, scCookies) {
  var rows = []
  if (!st || libraryOpen === false) return rows
  // An entry has the same id wherever it shows, so a result knows whether it is kept already.
  var kept = {}
  var favs = st.favorites instanceof Array ? st.favorites : []
  for (var k = 0; k < favs.length; k++) kept[String(favs[k].id)] = true
  // boxed: the rows of the search itself, which the panel puts in the box that scrolls and counts. Its caption
  // stands above the box and the "load more" below it, so these rows carry no caption of their own.
  var words = String(filter || "").trim().toLowerCase().split(/\s+/).filter(function (w) { return w !== "" })
  var add = function (list, group, result, prefix, kindOnly, boxed) {
    var first = true
    for (var i = 0; i < list.length; i++) {
      var x = list[i]
      if (kindOnly && x.kind !== kindOnly) continue
      if (boxed && !matches(x, words)) continue
      var id = String(x.id)
      rows.push({ key: prefix + (i + 1), play: "id:" + id, id: id, title: String(x.title), subtitle: String(x.subtitle || ""), kind: x.kind,
                  result: result, favorite: !!kept[id], number: i + 1, group: group, first: first, boxed: boxed === true,
                  // A playlist is opened, not played, and is not kept as a favorite: what would play?
                  openable: x.set === true })
      first = false
    }
  }
  // The favorites fill the same box as everything else: with a hundred of them, a hundred unbounded rows would
  // push the foot of the panel out of reach, and nothing would say how many there are.
  var from = Math.max(0, Math.floor(Number(page) || 0)) * PAGE
  var windowed = function (list) { return list.slice(from, from + PAGE) }
  if (source === "fav") { add(windowed(favs), "", false, "f", "", true); return rows }
  // What played before: a row plays it again, and its star keeps it. It is not a favorite, so it wears the
  // empty star until it is kept.
  if (source === "recent") {
    var rec = st.recent instanceof Array ? st.recent : []
    add(windowed(rec), "", true, "p", "", true)
    return rows
  }
  if (!sourceUsable(st, source, scUser, scCookies)) return rows
  // One of the profile's lists instead of a search: it fills the same box, with its own caption.
  var narrowed = function (list) { return windowed(list.filter(function (x) { return matches(x, words) })) }
  if (source === "soundcloud" && scView && scView !== "search") {
    var l = scList(st, scView, scUser)
    if (l) add(narrowed(l.items), "", true, "s", "", true)
    return rows
  }
  var res = st.results && st.results.items instanceof Array ? st.results.items : []
  if (source && st.results && st.results.kind !== source) res = []
  if (res.length) add(narrowed(res), "RESULTS", true, "r", source, true)
  // DI.FM without a search: every channel, each with a star. They belong in the same box as the results, or the
  // button that loads more of them stands above the list it lengthens.
  else if (source === "di" && st.channels && st.channels.items instanceof Array) add(narrowed(st.channels.items), "CHANNELS", true, "c", source, true)
  return rows
}

// The results of the chosen source: how many are held, how many the panel shows, and whether more can be had,
// either from what is held or by asking the source for its next page.
// held is what the caption counts, and while the field narrows, that is what matches it. canFetchMore is the one
// thing left to press: the source has another page, and nothing is narrowing the view.
function resultsInfo(st, source, scView, filter, scUser, page, scCookies) {
  // The window the arrows under the list move, and what the caption counts.
  var at = Math.max(0, Math.floor(Number(page) || 0))
  var pageOf = function (n, rest) {
    var o = { held: n, page: at, from: n ? at * PAGE + 1 : 0, to: Math.min(n, (at + 1) * PAGE),
              pages: Math.max(1, Math.ceil(n / PAGE)), canPrev: at > 0, canNext: (at + 1) * PAGE < n }
    for (var k in rest) o[k] = rest[k]
    return o
  }
  var words = String(filter || "").trim().toLowerCase().split(/\s+/).filter(function (w) { return w !== "" })
  var kept = function (list) { return list.filter(function (x) { return matches(x, words) }).length }
  if (source === "fav" || source === "recent") {
    var all = st && st[source === "fav" ? "favorites" : "recent"] instanceof Array ? st[source === "fav" ? "favorites" : "recent"] : []
    return pageOf(all.length, { query: "", channels: false, list: source === "fav" ? "favorites" : "recent",
                                narrowed: false, canFetchMore: false })
  }
  if (!sourceUsable(st, source, scUser, scCookies)) return pageOf(0, { query: "", channels: false, list: "", narrowed: false, canFetchMore: false })
  if (source === "soundcloud" && scView && scView !== "search") {
    var l = scList(st, scView, scUser)
    var n = l ? kept(l.items) : 0
    return pageOf(n, { query: l ? String(l.user) : "", channels: false, list: scView, narrowed: words.length > 0, canFetchMore: false })
  }
  var r = st && st.results && st.results.items instanceof Array && (!source || st.results.kind === source) ? st.results : null
  if (!r && source === "di" && st && st.channels && st.channels.items instanceof Array) {
    var n = kept(st.channels.items)
    return pageOf(n, { query: "", channels: true, list: "", narrowed: words.length > 0, canFetchMore: false })
  }
  if (!r) return pageOf(0, { query: "", channels: false, list: "", narrowed: false, canFetchMore: false })
  var fit = kept(r.items)
  return pageOf(fit, { query: String(r.query || ""), channels: false, list: "", narrowed: words.length > 0,
                       canFetchMore: words.length === 0 && r.complete === false })
}

// Seconds as m:ss for the seek row.
function mmss(s) {
  var n = Math.max(0, Math.floor(Number(s) || 0))
  return Math.floor(n / 60) + ":" + (n % 60 < 10 ? "0" : "") + (n % 60)
}

// The words beside LIBRARY: how many favorites the chosen tab counts, all of them on FAVORITES and those of the
// source on the others.
function libraryLine(st, source) {
  if (!st) return ""
  var all = st.favorites instanceof Array ? st.favorites : []
  var fav = source && source !== "fav" ? all.filter(function (f) { return f.kind === source }).length : all.length
  return fav + (fav === 1 ? " favorite" : " favorites")
}

function searchHint(source) {
  return "Search " + (SOURCE_NAMES[source] || source)
}
