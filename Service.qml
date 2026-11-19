import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import "Model.js" as Model

// State and processes for the Ballroom widget. The lists the panel shows come from `ballroom json`, never from
// the live PipeWire model: Quickshell's PipeWire service has crashed when a Repeater was rebuilt while a node was
// being removed. Every change goes through a `ballroom` verb, so caps, routes and the Bluetooth guard apply the
// same way from the panel, the terminal and a keybinding.
//
// Every process runs with a cleared environment and a short list of variables, under a deadline from
// /usr/bin/timeout, and with a cap on what it may say: a variable exported in the session must not change what
// the widget reads or where a key goes, a hung tool must not hold a channel forever, and an endless answer must
// not fill the shell's memory.
Item {
  id: root
  visible: false

  property var settings: ({})
  property bool opened: false
  // The live mute of the default input, from the widget. Muting it stops the input spectrum at once.
  property bool inputMuted: false

  property var info: null
  // The last reading failed or timed out: what the panel shows is old, and nothing may act on it until a
  // reading comes back.
  property bool stale: false
  property var bands: []
  property var inputBands: []
  property string errorText: ""
  property bool busy: false
  // Counts actions that failed; the widget drops levels it showed ahead of the reading when this moves.
  property int failedActions: 0
  // The spectrum could not start twice in a row (cava missing, say): it stays off and this says why.
  property string spectrumError: ""

  readonly property string bin: Quickshell.env("HOME") + "/.local/bin/ballroom"
  // The name the plugin shows for itself, in the panel. The shell's widget list and
  // the store keep the manifest's name; those are not the plugin's to change.
  readonly property string title: {
    var t = String(setting("title", "")).trim()
    return t !== "" ? t : "Ballroom"
  }
  readonly property bool spectrumWanted: setting("spectrum", true) === true
  readonly property bool inputSpectrumWanted: spectrumWanted && setting("inputSpectrum", true) === true
  readonly property bool inputMeters: setting("inputMeters", true) === true
  readonly property string soundcloudUser: String(setting("soundcloudUser", "")).trim()
  // Which browser session yt-dlp may read, as BROWSER[+KEYRING][:PROFILE]. Empty means nobody has chosen one,
  // and then Ballroom uses the first browser that holds a SoundCloud session and whose store it can open.
  readonly property string soundcloudCookies: String(setting("soundcloudCookies", "")).trim()
  readonly property int spectrumBars: Math.max(4, Math.min(24, Number(setting("spectrumBars", 8))))
  // Mono paints the bars in the bar's foreground, Accent in the theme's accent, Rainbow one hue per band.
  readonly property string spectrumColor: String(setting("spectrumColor", "Mono"))

  // The plugin's own manifest, read from the file beside this one: the bar hands a widget its settings, not the
  // manifest. The settings page is built from the schema in it, so the labels, the bounds and the choices live
  // in one place and the page cannot drift from what the command enforces.
  property var manifest: null
  readonly property string manifestPath: decodeURIComponent(String(Qt.resolvedUrl("manifest.json")).replace(/^file:\/\//, ""))
  readonly property var settingsSchema: {
    var m = manifest
    return m && m.barWidget && m.barWidget.schema instanceof Array ? m.barWidget.schema : []
  }
  FileView {
    path: root.manifestPath
    printErrors: false
    onLoaded: root.manifest = Model.parseState(text())
    onLoadFailed: root.manifest = null
  }
  // A value goes through the command, which checks it against the same bounds the terminal uses and hands it to
  // the shell; the shell gives the widget its settings back, and every control follows from there.
  function applySetting(key, value) {
    var v = typeof value === "boolean" ? (value ? "on" : "off") : String(value)
    return stageCtl(["_widget-set", String(key), v])
  }

  function setting(name, fallback) {
    var v = settings ? settings[name] : undefined
    return v === undefined || v === null ? fallback : v
  }

  // The environment every process gets: a fixed PATH, the home, the runtime directory for the sockets and the
  // display and bus for the shell it calls. Nothing else from the session reaches `ballroom`.
  function processEnv(extra) {
    var e = { PATH: "/usr/bin:/usr/local/bin:/usr/share/omarchy/bin", HOME: String(Quickshell.env("HOME") || ""), LANG: String(Quickshell.env("LANG") || "C.UTF-8") }
    // OMARCHY_PATH belongs on this list: omarchy-shell reads it to find the shell it calls, and without it every
    // widget setting written from the panel came back as "the shell did not take the setting".
    var keep = ["XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "OMARCHY_PATH"]
    for (var i = 0; i < keep.length; i++) {
      var v = Quickshell.env(keep[i])
      if (v) e[keep[i]] = String(v)
    }
    for (var k in (extra || {})) e[k] = extra[k]
    return e
  }
  // A command under a deadline: timeout ends it after `seconds`, and kills it five seconds later if it lingers.
  function withDeadline(seconds, args) { return ["/usr/bin/timeout", "-k", "5", String(seconds), bin].concat(args) }

  // collect(buffer, chunk, process): keep up to outputCap characters; past that, stop the process and mark the
  // buffer as overflowed. Output already read when the kill lands still arrives, so the cap holds here.
  readonly property int outputCap: 262144
  property var _overflow: ({})
  property string _stateText: ""
  property string _actionText: ""
  property string _stageText: ""
  property string _searchText: ""
  property string _ctlText: ""
  function collect(name, chunk, proc) {
    if (_overflow[name]) return
    if (root[name].length + chunk.length > outputCap) {
      _overflow[name] = true
      proc.signal(9)
      return
    }
    root[name] += chunk
  }
  function begin(name) { root[name] = ""; _overflow[name] = false }
  // The first line of a failed verb's answer: its error field when it spoke JSON, otherwise a plain sentence.
  function failureOf(name, exitCode, fallback) {
    if (_overflow[name]) return "ballroom said more than " + outputCap + " characters and was stopped"
    var d = Model.parseState(root[name])
    if (d && d.error) return String(d.error)
    return fallback + (exitCode === 124 ? " (timed out)" : " (exit " + exitCode + ")")
  }

  function refresh() { if (!stateProc.running) stateProc.running = true }

  // One action at a time; a click while one runs is dropped rather than queued behind a hung tool. Nothing acts
  // while the reading is stale: the rows would act on a state that is not the machine's.
  function run(args) {
    if (actionProc.running || stale) return false
    busy = true
    errorText = ""
    actionProc.command = withDeadline(20, args.concat(["--json"]))
    actionProc.running = true
    return true
  }
  function makeDefaultOutput(name) { return run(["out", name]) }
  function makeDefaultInput(name) { return run(["in", name]) }
  function toggleDeviceMute(name) { return run(["mute", name, "toggle"]) }
  // What a device is called, where it belongs and how loud it may become. Every one of these goes through the
  // command, so the panel and the terminal set them the same way and the same checks apply.
  function setDeviceAlias(name, text) { return run(["device", "alias", name, String(text || "").trim() === "" ? "-" : String(text)]) }
  function setDeviceHidden(name, hidden) { return run(["device", hidden ? "hide" : "show", name]) }
  function setDeviceKind(name, kind) { return run(["device", "kind", name, String(kind)]) }
  // "-" gives the device back to the limit of its kind, "none" lets it go all the way up.
  function setDeviceCap(name, what) { return run(["device", "cap", name, String(what)]) }
  function forgetDevice(name) { return run(["device", "reset", name]) }
  function setBtMode(address, mode) { return run(["bt", "mode", address, String(mode)]) }
  function setBtCodec(address, codec) { return run(["bt", "codec", address, String(codec)]) }
  function setBtAuto(on) { return run(["bt", "auto", on ? "on" : "off"]) }
  function setClassCap(kind, what) { return run(["device", "classcap", String(kind), String(what)]) }

  // The diagnosis, on demand: it asks PipeWire, WirePlumber and the units and takes a moment, so it is never
  // part of the reading that keeps the panel current. The answer is kept until the panel is closed.
  property string doctorText: ""
  property bool doctorRunning: doctorProc.running
  function runDoctor() {
    if (doctorProc.running || stale) return false
    doctorProc.command = withDeadline(30, ["doctor", "--json"])
    doctorProc.running = true
    return true
  }
  property string _doctorOut: ""
  Process {
    id: doctorProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_doctorOut", chunk, doctorProc) } }
    onStarted: root.begin("_doctorOut")
    onExited: function (exitCode) { root.doctorText = root._doctorOut; root._doctorOut = "" }
  }

  // The level of a device that is not the default. A wheel sends many small steps and an action runs one at a
  // time, so levels wait here per device and only the last one of each is sent, as soon as nothing else runs.
  property var pendingLevels: ({})
  function setDeviceVolume(name, level) {
    var next = Object.assign({}, pendingLevels)
    next[name] = Math.max(0, Math.min(1, level))
    pendingLevels = next
    levelFlush.restart()
  }
  Timer {
    id: levelFlush
    interval: 120
    onTriggered: {
      var names = Object.keys(root.pendingLevels)
      if (!names.length) return
      if (actionProc.running) { levelFlush.restart(); return }
      var next = Object.assign({}, root.pendingLevels)
      var level = next[names[0]]
      delete next[names[0]]
      root.pendingLevels = next
      root.run(["vol", names[0], String(Math.round(level * 100))])
      if (names.length > 1) levelFlush.restart()
    }
  }
  function setStreamVolume(serial, level) { return run(["vol", "#" + serial, String(Math.round(level * 100))]) }
  // An application is sent to one output, or let go again ("follow"). The rule is kept under the application's
  // name for the setup of outputs that is plugged in right now, so it holds the next time that application plays
  // in this setup; another setup has its own rules, and without one the application follows the default.
  function routeApp(app, target) {
    var a = String(app || "").trim()
    if (!a || !target) return false
    return run(["route", a, String(target)])
  }
  function toggleStreamMute(serial) { return run(["mute", "#" + serial, "toggle"]) }
  // The equalizer. Every one of these is one change, sent once (a moving control would click on every step).
  function setEq(on) { return run(["eq", on ? "on" : "off"]) }
  function usePreset(name) { return name ? run(["eq", "preset", "use", name]) : false }
  function setBalance(v) { return run(["eq", "balance", String(Math.round(Math.max(-1, Math.min(1, v)) * 100) / 100)]) }
  function setStereo(what, on) { return run(["eq", what, on ? "on" : "off"]) }
  function resetStereo() { return run(["eq", "stereo", "reset"]) }
  // The rest of the equalizer, which used to live in the terminal only. Every one of these is one change, sent
  // once: a moving control would click on every step (a biquad clicks at each real change of a band).
  // One band, sent once when the knob is let go. Frequency, width and shape come along unchanged: the verb
  // takes all four, and leaving one out would reset it to what it was at the start.
  function setBand(n, band, gain) {
    if (!band) return false
    return run(["eq", "band", String(n), String(band.freq), Number(gain).toFixed(1), String(band.q), String(band.type)])
  }
  function setPreamp(db) { return run(["eq", "preamp", String(db)]) }
  function setPreampAuto() { return run(["eq", "preamp", "auto"]) }
  function savePreset(name) { var n = String(name || "").trim(); return n ? run(["eq", "preset", "save", n]) : false }
  function removePreset(name) { var n = String(name || "").trim(); return n ? run(["eq", "preset", "rm", n]) : false }
  function importPreset(path) { var v = String(path || "").trim(); return v ? run(["eq", "import", v]) : false }
  // The stage. Playing waits until mpv plays (streams take seconds) and may resolve a page first, so it has a
  // process of its own and never holds up a mute or a volume. A search too. Pause, stop, next and the favorites
  // run in a third one: they answer within milliseconds, and a stop must never wait behind a stream that is
  // still loading.
  property string stageError: ""
  property bool stageBusy: stageProc.running
  property bool searching: searchProc.running
  function stageRun(args) {
    if (stageProc.running || stale) return false
    stageError = ""
    stageProc.command = withDeadline(60, args.concat(["--json"]))
    stageProc.running = true
    return true
  }
  function stageCtl(args) {
    if (ctlProc.running || stale) return false
    stageError = ""
    ctlProc.command = withDeadline(10, args.concat(["--json"]))
    ctlProc.running = true
    return true
  }
  // A search supersedes the one before it. The panel asks for one a moment after the typing stops, so a slower
  // answer to an older query must never land on top of a newer one: the running search is ended and the newest
  // starts when it is gone. An ended search is not a failure and says nothing.
  property var pendingSearch: null
  property bool searchSuperseded: false
  function stageSearch(source, query) {
    var q = String(query || "").trim()
    if (!q || stale) return false
    pendingSearch = { source: source, query: q }
    if (searchProc.running) { searchSuperseded = true; searchProc.signal(15); return true }
    return startSearch()
  }
  function startSearch() {
    if (!pendingSearch || searchProc.running) return false
    var p = pendingSearch
    pendingSearch = null
    stageError = ""
    searchProc.command = withDeadline(60, [p.source === "soundcloud" ? "sc" : p.source, "search", p.query, "--json"])
    searchProc.running = true
    return true
  }
  // The next page of the same search, appended to what is held.
  function stageSearchMore(source, query) {
    var q = String(query || "").trim()
    if (!q || searchProc.running || stale) return false
    stageError = ""
    searchProc.command = withDeadline(90, [source === "soundcloud" ? "sc" : source, "search", q, "--more", "--json"])
    searchProc.running = true
    return true
  }
  // The SoundCloud name goes into the widget settings through the command, which hands it to the shell and
  // reads it back; the shell then gives the widget its new settings.
  function setSoundcloudName(name) {
    var n = String(name || "").trim()
    if (!n) return false
    return stageCtl(["_widget-set", "soundcloudUser", n])
  }
  // The browser whose SoundCloud session may be read. Only the name goes over: the command knows where that
  // browser keeps its profile, and a profile anywhere but the usual place is found by nobody otherwise. A single
  // dash lets Ballroom choose again.
  function setSoundcloudCookies(browser) {
    var b = String(browser || "").trim()
    if (!b) return false
    return stageCtl(["sc", "cookies", b])
  }
  // Which browsers keep a cookie store here, and which of them is signed in on SoundCloud. Asked while the
  // library stands on SoundCloud without a profile name; it reads the host of a cookie, never a value. Nothing
  // is set from this: the panel offers the list, and the user picks one. Only then is that session read.
  property var browsers: []
  property bool browsersAsked: false
  // browsersAnswered says the question was actually answered; without it a timeout would read as "no browser".
  property bool browsersAnswered: false
  // A store that is there but could not be opened is not the same as no store: the panel must not send someone
  // off to sign in to an account they are already signed in to.
  readonly property bool lockedStore: {
    for (var i = 0; i < browsers.length; i++) if (browsers[i] && !browsers[i].readable) return true
    return false
  }
  readonly property string signedInBrowser: {
    for (var i = 0; i < browsers.length; i++) if (browsers[i] && browsers[i].soundcloud) return String(browsers[i].browser)
    return ""
  }
  function findBrowsers() {
    if (browsersProc.running || stale) return false
    browsersProc.command = withDeadline(15, ["sc", "browsers", "--json"])
    browsersProc.running = true
    return true
  }
  // Who that session belongs to. Asked once, and the answer is the profile name, kept like any other setting.
  // It takes a few seconds: the cookie store is opened and one request goes out.
  property bool namingAccount: whoamiProc.running
  function findAccount() {
    if (whoamiProc.running || stale) return false
    whoamiProc.command = withDeadline(60, ["sc", "whoami", "--json"])
    whoamiProc.running = true
    return true
  }
  property string _whoamiText: ""
  Process {
    id: whoamiProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_whoamiText", chunk, whoamiProc) } }
    onStarted: root.begin("_whoamiText")
    onExited: function (exitCode) {
      // A session that does not say whose it is leaves the field asking; that is not an error worth a red line.
      root._whoamiText = ""
      root.refresh()
    }
  }
  property string _browsersText: ""
  Process {
    id: browsersProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_browsersText", chunk, browsersProc) } }
    onStarted: root.begin("_browsersText")
    onExited: function (exitCode) {
      // Only what the panel needs: which browser, whether it holds a session, and whether its store could be
      // opened at all. The profile path stays in the command. A failed call is not an answer, so the panel is
      // told nothing rather than "no browser here".
      var d = exitCode === 0 ? Model.parseState(root._browsersText) : null
      var list = d && d.browsers instanceof Array ? d.browsers : []
      var out = []
      for (var i = 0; i < list.length; i++)
        out.push({ browser: String(list[i].browser), soundcloud: list[i].soundcloud === true, readable: list[i].readable !== false })
      root.browsers = out
      root.browsersAnswered = exitCode === 0
      root.browsersAsked = true
      root._browsersText = ""
    }
  }
  // The channel list of DI.FM, fetched once a day into the cache when the library opens on DI.FM.
  function stageChannels() {
    if (searchProc.running || stale) return false
    searchProc.command = withDeadline(30, ["di", "channels", "di", "--json"])
    searchProc.running = true
    return true
  }
  // The DI.FM listen key is written to the command's stdin, never given as an argument; the command checks it
  // with DI.FM before it keeps it, and the panel shows the answer in the stage line.
  property string _pendingKey: ""
  function setDiKey(key) {
    var k = String(key || "").trim()
    if (!k || keyProc.running || stale) return false
    stageError = ""
    _pendingKey = k
    keyProc.command = withDeadline(30, ["di", "key", "set", "--json"])
    keyProc.running = true
    return true
  }
  property string _keyText: ""
  Process {
    id: keyProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdinEnabled: true
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_keyText", chunk, keyProc) } }
    onStarted: { root.begin("_keyText"); keyProc.write(root._pendingKey + "\n"); root._pendingKey = "" }
    onExited: function (exitCode) {
      root._pendingKey = ""
      if (exitCode !== 0) root.stageError = root.failureOf("_keyText", exitCode, "the key was not taken")
      root._keyText = ""
      root.refresh()
    }
  }
  // One of the lists a SoundCloud profile holds: likes, playlists, uploads, reposts. Fetched when the library
  // stands on that list and it is not the one held, or it is older than ten minutes; never blocks a search or a
  // play. Only one list is kept at a time, the one last asked for.
  property bool fetchingList: listProc.running
  function stageList(what) {
    if (listProc.running || stale || soundcloudUser === "") return false
    listProc.command = withDeadline(90, ["sc", "list", String(what), "--json"])
    listProc.running = true
    return true
  }
  property string _listText: ""
  Process {
    id: listProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_listText", chunk, listProc) } }
    onStarted: root.begin("_listText")
    onExited: function (exitCode) {
      if (exitCode !== 0) root.stageError = root.failureOf("_listText", exitCode, "SoundCloud did not send the list")
      root._listText = ""
      root.refresh()
    }
  }
  Process {
    id: stageProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_stageText", chunk, stageProc) } }
    onStarted: root.begin("_stageText")
    onExited: function (exitCode) {
      if (exitCode !== 0) root.stageError = root.failureOf("_stageText", exitCode, "the stage did not answer")
      root._stageText = ""
      root.refresh()
    }
  }
  Process {
    id: searchProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_searchText", chunk, searchProc) } }
    onStarted: root.begin("_searchText")
    onExited: function (exitCode) {
      var mine = !root.searchSuperseded
      root.searchSuperseded = false
      if (mine && exitCode !== 0) root.stageError = root.failureOf("_searchText", exitCode, "the search did not answer")
      root._searchText = ""
      if (!root.startSearch()) root.refresh()
    }
  }
  Process {
    id: ctlProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_ctlText", chunk, ctlProc) } }
    onStarted: root.begin("_ctlText")
    onExited: function (exitCode) {
      if (exitCode !== 0) root.stageError = root.failureOf("_ctlText", exitCode, "the stage did not answer")
      root._ctlText = ""
      root.refresh()
    }
  }
  Timer { interval: 10000; running: root.stageError !== ""; onTriggered: root.stageError = "" }
  // Results used to be dropped whenever the panel closed. They are kept now: a search is work, the panel closes
  // at every click beside it, and the library that opens on what was searched last is the one the user left.
  // They live in the runtime directory, so a logout still ends them; the cross clears them by hand.
  // DI.FM says what plays on a channel; the stage asks every half minute while one plays and the panel is open.
  readonly property var stageInfo: Model.stage(root.info)
  Timer {
    interval: 30000
    repeat: true
    triggeredOnStart: true
    running: root.opened && !!root.stageInfo && root.stageInfo.kind === "di" && root.stageInfo.state === "playing"
    onTriggered: if (!diNowProc.running) diNowProc.running = true
  }
  Process {
    id: diNowProc
    clearEnvironment: true
    environment: root.processEnv({})
    command: root.withDeadline(15, ["stage", "refresh", "--json"])
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { /* the answer is read back with the next refresh */ } }
    onExited: root.refresh()
  }

  // A default output changed outside Ballroom: apply gives the equalizer that device's preset.
  function applySoon() { hotplug.restart() }

  // The reading. A reading that never comes back, or comes back broken, leaves the panel marked stale: it keeps
  // showing what it had, says so, and takes no action until a reading arrives.
  Process {
    id: stateProc
    clearEnvironment: true
    environment: root.processEnv({})
    command: root.withDeadline(10, ["json"])
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_stateText", chunk, stateProc) } }
    onStarted: root.begin("_stateText")
    onExited: function (exitCode) {
      var text = root._stateText
      root._stateText = ""
      if (root._overflow["_stateText"]) { root.stateFailed("ballroom json said more than " + root.outputCap + " characters"); return }
      var d = Model.parseState(text)
      if (!d) { root.stateFailed(exitCode === 124 ? "PipeWire did not answer" : "ballroom json gave no answer (exit " + exitCode + ")"); return }
      if (d.ok === false) { root.stateFailed(String(d.error || "ballroom json failed")); return }
      root.info = d
      root.stale = false
      var plugged = Model.pluggedKey(d)
      if (root._plugged !== null && plugged !== root._plugged) root.applySoon()
      root._plugged = plugged
      if (root.errorText.indexOf("PipeWire did not answer") === 0 || root.errorText.indexOf("ballroom json") === 0) root.errorText = ""
    }
  }
  function stateFailed(why) { stale = true; errorText = why }

  Process {
    id: actionProc
    clearEnvironment: true
    environment: root.processEnv({})
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { root.collect("_actionText", chunk, actionProc) } }
    onStarted: root.begin("_actionText")
    onExited: function (exitCode) {
      root.busy = false
      if (exitCode !== 0) { root.errorText = root.failureOf("_actionText", exitCode, "ballroom failed"); root.failedActions += 1 }
      root._actionText = ""
      settle.restart()
    }
  }

  Timer { id: settle; interval: 250; onTriggered: root.refresh() }

  // Idle it looks every few seconds; with the panel open, every second.
  Timer {
    interval: root.opened ? 1000 : Math.max(2, Number(root.setting("refreshIntervalSec", 5))) * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  // An error fades after a while, unless the reading is stale: that one stays until a reading comes back.
  Timer { interval: 8000; running: root.errorText !== "" && !root.stale; onTriggered: root.errorText = "" }

  // A device came or went: apply caps and routes, then read the graph again. The count is all this reads from
  // the live model, and it is read from the signal, not from node properties.
  //
  // Measured with a Bluetooth headset on PipeWire 1.6.8 and WirePlumber 0.5.17: WirePlumber makes it the default 27 ms
  // after it appears, at the volume it had, and with a pause here the cap came well under a second after that. The
  // pause only has to swallow the burst of nodes a device brings along, so it is short; and a change that
  // arrives while an apply runs is not dropped but runs once more when that one ends.
  // A plug that is pulled or pushed changes no node count: a monitor port stays a node without its monitor. The
  // reading says which outputs are plugged in, and a change there runs apply as well, within one reading.
  property var _plugged: null
  property int nodeCount: Pipewire.nodes ? Pipewire.nodes.values.length : 0
  property bool applyPending: false
  // The key is never forgotten: a node that comes or goes and a plug that changes can land in the same moment,
  // and a reading that took the key afresh would miss the plug for good. A second apply for one event finds
  // nothing to do (apply changes nothing the second time).
  onNodeCountChanged: hotplug.restart()
  Timer {
    id: hotplug
    interval: 120
    onTriggered: {
      if (applyProc.running) root.applyPending = true
      else applyProc.running = true
    }
  }
  Process {
    id: applyProc
    clearEnvironment: true
    environment: root.processEnv({})
    command: root.withDeadline(20, ["apply", "--json"])
    stdout: SplitParser { splitMarker: ""; onRead: function (chunk) { /* apply reports through the next reading */ } }
    onExited: {
      if (root.applyPending) { root.applyPending = false; applyProc.running = true }
      else root.refresh()
    }
  }

  // The output spectrum: `ballroom spectrum` owns cava and ends with this process. It is started only while
  // something plays or the panel is open, and restarted with a pause if it ends on its own. It streams for as
  // long as it runs, so it has no deadline; a line longer than any frame could be is dropped.
  readonly property bool somethingPlays: Model.playing(root.info).length > 0
  readonly property bool spectrumRunning: spectrumWanted && (somethingPlays || opened)
  property int spectrumFailures: 0
  property string _spectrumErr: ""
  onSpectrumRunningChanged: {
    if (spectrumRunning) { root.spectrumFailures = 0; root.spectrumError = ""; spectrumProc.running = true }
    else { spectrumProc.running = false; root.bands = [] }
  }
  Process {
    id: spectrumProc
    clearEnvironment: true
    environment: root.processEnv({})
    command: [root.bin, "spectrum", "--bars", String(root.spectrumBars * 2), "--fps", "30"]
    stdout: SplitParser {
      onRead: function (line) {
        if (line.length > 4096) return
        var b = Model.parseBands(line)
        if (b) root.bands = b
      }
    }
    stderr: SplitParser { onRead: function (line) { if (line.length < 400) root._spectrumErr = line } }
    onStarted: root._spectrumErr = ""
    onExited: function (exitCode) {
      root.bands = []
      if (!root.spectrumRunning) return
      if (exitCode === 0) { respawn.restart(); return }
      root.spectrumFailures += 1
      if (root.spectrumFailures < 2) { respawn.restart(); return }
      var why = root._spectrumErr.replace(/^ballroom: /, "")
      root.spectrumError = why.indexOf("cava is not installed") >= 0 ? "no spectrum: cava is not installed (omarchy pkg add cava)" : "no spectrum: " + (why || "it could not start")
    }
  }
  Timer { id: respawn; interval: 3000; onTriggered: if (root.spectrumRunning && !spectrumProc.running) spectrumProc.running = true }

  // The input spectrum reads the microphone, so it runs only while the panel is open and the input is not
  // muted, and it ends the moment either changes. A new default input restarts it on that input.
  readonly property int inputSerial: {
    var d = Model.defaultInput(root.info)
    return d && d.serial ? Number(d.serial) : 0
  }
  readonly property bool inputSpectrumRunning: inputSpectrumWanted && opened && inputSerial > 0 && !inputMuted
  onInputSpectrumRunningChanged: {
    if (inputSpectrumRunning) inputSpectrumProc.running = true
    else { inputSpectrumProc.running = false; root.inputBands = [] }
  }
  onInputSerialChanged: if (inputSpectrumProc.running) inputSpectrumProc.running = false
  Process {
    id: inputSpectrumProc
    clearEnvironment: true
    environment: root.processEnv({})
    command: [root.bin, "spectrum", "--bars", String(root.spectrumBars * 2), "--fps", "30", "--source", String(root.inputSerial)]
    stdout: SplitParser {
      onRead: function (line) {
        if (line.length > 4096) return
        var b = Model.parseBands(line)
        if (b) root.inputBands = b
      }
    }
    onExited: {
      root.inputBands = []
      if (root.inputSpectrumRunning) inputRespawn.restart()
    }
  }
  Timer { id: inputRespawn; interval: 1000; onTriggered: if (root.inputSpectrumRunning && !inputSpectrumProc.running) inputSpectrumProc.running = true }
}
