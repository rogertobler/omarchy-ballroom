import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Services.Pipewire
import Quickshell.Services.Mpris
import qs.Ui
import qs.Commons
import "Model.js" as Model

// Ballroom: the sound of the machine in the bar, and a panel behind it.
//
//   left = panel · right = mute the output · middle = mute the microphone · wheel = output volume
//   and while something plays that can be paused, a button after the icon: left = pause or play · right = stop
//
// Ballroom is a clone of omarchy.audio and keeps its module and IPC names, so the shell hands every call and
// keybinding for the audio widget to it while it is enabled, and gives the built-in back when it is disabled.
// The two main sliders act on PipeWire directly, as the built-in does. Everything with a rule behind it (the
// default device and its cap, routes, mutes per device, the lists) goes through `ballroom`, see Service.qml.
Panel {
  id: root
  moduleName: "omarchy.audio"
  ipcTarget: "omarchy.audio"

  implicitWidth: face.implicitWidth
  implicitHeight: button.implicitHeight

  Service { id: svc; settings: root.settings; opened: root.opened; inputMuted: root.inputMuted }

  readonly property var info: svc.info
  readonly property var sink: Pipewire.defaultAudioSink
  readonly property var source: Pipewire.defaultAudioSource
  readonly property var outputDevice: Model.defaultOutput(info)
  readonly property var snd: Model.sound(info)
  // Whether a section is shown is the sections list's business, and nothing else's: two switches for one thing
  // are two chances to disagree. The equalizer keeps working when its section is hidden; the section is only
  // what the eye sees.
  function sectionOn(id) {
    for (var i = 0; i < sectionPlan.length; i++) if (sectionPlan[i].id === id) return sectionPlan[i].on
    return true
  }
  readonly property bool showSound: !!snd && sectionOn("sound")
  readonly property var stg: Model.stage(info)
  // The library is a section; the transport is a row in PLAYING and belongs to the stream, not to a setting.
  readonly property bool showStage: !!stg && sectionOn("library")
  readonly property string resultsQuery: stg && stg.results ? String(stg.results.kind) + ":" + String(stg.results.query) : ""
  // What stands in the search field narrows what is shown, as long as it is not exactly the words the held
  // results were fetched with. Typing on DI.FM therefore sifts the channels at once, without Enter.
  property string searchText: ""
  // What the field should hold when it is built: after a fresh start of the shell the tab follows what was
  // searched last, and the field has to say the same thing.
  property string restoreText: ""
  // No Enter needed: what is held narrows while the words appear, and the source is asked once the hand rests.
  // The wait is as long as the source is slow, measured: DI.FM answers from its own cache in 69 ms, the radio
  // directory in 225 ms, SoundCloud in 1.3 s. Enter is still there and skips the wait.
  readonly property int searchDelay: stageSource === "di" ? 250 : stageSource === "soundcloud" ? 700 : 450
  onSearchTextChanged: liveSearch.restart()
  function searchNow(immediate) {
    liveSearch.stop()
    var q = searchText.trim()
    if (q.length < 2 || stageSource === "fav") return
    if (stageSource === "soundcloud" && scView !== "search") return
    if (!Model.sourceUsable(stg, stageSource, svc.soundcloudUser, svc.soundcloudCookies)) return
    // What is already held for exactly these words needs no second errand.
    if (!immediate && stg && stg.results && String(stg.results.kind) === stageSource
        && String(stg.results.query).trim().toLowerCase() === q.toLowerCase()) return
    svc.stageSearch(stageSource, q)
  }
  Timer { id: liveSearch; interval: root.searchDelay; onTriggered: root.searchNow(false) }
  // The chosen tab and the field keep themselves while the shell runs, so a panel that opens again opens where
  // it was left. After a fresh start of the shell they do not, and held results would sit on a tab nobody is
  // looking at: once, when the first reading arrives, the tab follows what was searched last.
  property bool searchRestored: false
  onStgChanged: {
    if (searchRestored || !stg) return
    searchRestored = true
    var r = stg.results
    if (r && (r.items instanceof Array) && r.items.length > 0) {
      if (["radio", "soundcloud", "di"].indexOf(String(r.kind)) >= 0) stageSource = String(r.kind)
      searchText = String(r.query || "")
      restoreText = searchText
      return
    }
    // Nothing was searched, but something is kept: that is what gets chosen, so the library opens on it. Only
    // when the user has not said otherwise in the settings, and only this once.
    if (stg.favorites instanceof Array && stg.favorites.length > 0) stageSource = "fav"
  }
  // Which sections are folded shut. The panel writes it when a line is clicked, so the panel opens again the
  // way it was left; what the user does in this run wins at once, because the way back from the shell takes a
  // moment and a fold has to answer under the finger.
  readonly property var foldStored: Model.foldState(svc.setting("folded", ""))
  property var foldNow: ({})
  function foldOpen(id) {
    if (foldNow[id] !== undefined) return foldNow[id] === true
    if (foldStored[id] !== undefined) return foldStored[id] === true
    // Nothing recorded for it: the devices under their level stand open, and the library only where something is
    // kept in it.
    return id !== "library" || (!!stg && stg.favorites instanceof Array && stg.favorites.length > 0)
  }
  // What the output slider shows while it is being dragged, and -1 while nobody drags it. The head of the panel
  // and the section's own line both say the level, and the slider lives inside a section that is loaded on
  // demand: a name inside one of those is out of reach from here, so the section hands the value up.
  property real outputLive: -1
  readonly property real outputShown: outputLive >= 0 ? outputLive : outputVolume

  // The mark on a section's line that says which way it folds. One place for it: six lines carry it.
  function chevron(id) { return (foldOpen(id) ? Model.G_CHEVRON_UP : Model.G_CHEVRON_DOWN) + "  " }
  function toggleFold(id) {
    var v = !foldOpen(id)
    // A new object, never the one it already holds changed in place: a var property that is handed back the
    // same object sends no change signal, and every binding that asks foldOpen keeps the answer it had. That is
    // what made a section impossible to open again: the first click still went through the way back from the
    // shell, because nothing was recorded here yet, and from then on nothing moved at all.
    var m = {}
    for (var k in foldNow) m[k] = foldNow[k]
    m[id] = v
    foldNow = m
    svc.applySetting("folded", Model.foldLine(svc.setting("folded", ""), id, v))
  }

  readonly property string rowFilter: Model.rowFilter(stg, stageSource, scView, searchText)
  readonly property var stageRows: Model.stageRows(stg, stageSource, foldOpen("library"), scView, rowFilter, svc.soundcloudUser, stagePage, svc.soundcloudCookies)
  readonly property var resultRows: stageRows.filter(function (r) { return r.boxed })
  readonly property var libraryRows: stageRows.filter(function (r) { return !r.boxed })
  readonly property var resultsInfo: Model.resultsInfo(stg, stageSource, scView, rowFilter, svc.soundcloudUser, stagePage, svc.soundcloudCookies)
  // Which ten of what is held are on the screen. It goes back to the first whenever what is held changes, so a
  // new search never opens on page four of the one before it.
  property int stagePage: 0
  onResultsQueryChanged: stagePage = 0
  onRowFilterChanged: stagePage = 0
  onScViewChanged: stagePage = 0
  // Forward past the last held page asks the source for more; the rows arrive and the page turns onto them.
  function pageForward() {
    if (resultsInfo.canNext) { stagePage += 1; return }
    if (resultsInfo.canFetchMore && svc.stageSearchMore(stageSource, resultsInfo.query)) stagePage += 1
  }
  function pageBack() { if (resultsInfo.canPrev) stagePage -= 1 }
  property string stageSource: "radio"
  // Under SOUNDCLOUD: the search, or one of the lists the profile holds. Choosing one fetches it.
  property string scView: "search"
  // Switching the source by hand empties the field; the restore above sets it again straight after.
  onStageSourceChanged: { scView = "search"; stagePage = 0; clearSearch() }
  readonly property var inputDevice: Model.defaultInput(info)
  readonly property real outputVolume: sink && sink.audio ? sink.audio.volume : 0
  readonly property bool outputMuted: sink && sink.audio ? sink.audio.muted : false
  readonly property real inputVolume: source && source.audio ? source.audio.volume : 0
  readonly property bool inputMuted: source && source.audio ? source.audio.muted : false

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color dim: Qt.darker(fg, 1.45)
  readonly property color hoverFill: Style.hoverFillFor(fg, Color.accent)
  readonly property color selectedFill: Style.selectedFillFor(fg, Color.accent)

  PwObjectTracker { objects: [root.sink, root.source].filter(function (n) { return !!n }) }

  // A default output set by anything but Ballroom (a keybinding, another panel) still takes its preset along.
  readonly property string sinkName: sink ? String(sink.name || "") : ""
  onSinkNameChanged: if (sinkName !== "") svc.applySoon()

  // The level of the default input, read the way the built-in panel reads it: only while the panel is open,
  // and here only while the input is not muted. Together with the spectrum, this is the whole of what Ballroom
  // takes from a microphone.
  PwNodePeakMonitor {
    id: inputPeak
    node: root.source
    enabled: root.opened && !!root.source && !root.inputMuted
  }

  property real wheelAccumulator: 0

  // The colour of one spectrum band, by the widget's setting: the foreground (grey on most themes), the
  // theme's accent, or a rainbow from red on the lowest band to violet on the highest.
  function bandColor(index, count, dimmed) {
    if (dimmed) return dim
    if (svc.spectrumColor === "Accent") return Color.accent
    if (svc.spectrumColor === "Rainbow") return Qt.hsla(0.8 * index / Math.max(1, count - 1), 0.85, 0.6, 1)
    return fg
  }

  function setOutputVolume(v) {
    if (!sink || !sink.audio) return outputVolume
    var next = Math.max(0, Math.min(1.5, v))
    sink.audio.volume = next
    return next
  }
  function setInputVolume(v) { if (source && source.audio) source.audio.volume = Math.max(0, Math.min(1, v)) }
  function toggleOutputMute() { if (sink && sink.audio) sink.audio.muted = !sink.audio.muted }
  function toggleInputMute() { if (source && source.audio) source.audio.muted = !source.audio.muted }
  function showVolumeOsd(v) {
    if (!bar || !bar.shell) return
    bar.shell.summon("omarchy.osd", JSON.stringify({ icon: Model.outputGlyph(outputDevice, v, outputMuted), value: Math.round(v * 100) }))
  }

  // Lists are snapshots of the last `ballroom json`, rebuilt only when that reading changes.
  property var outputs: []
  property var inputs: []
  property var streams: []
  // While the panel is open, every level meter of the shell is one of Ballroom's own.
  readonly property var listeners: Model.listening(info, opened)
  onInfoChanged: {
    outputs = Model.visibleDevices(info, "outputs")
    inputs = Model.visibleDevices(info, "inputs")
    streams = Model.playing(info)
    settleLocalLevels()
    refreshInputNodes()
    clampCursor()
  }

  // Each input row meters its own device, so the row of the microphone that hears something moves. That needs
  // the live node behind a listed input: looked up by name whenever the reading or the graph changes, and
  // only the name is read from a node this widget has not bound. The list itself stays the snapshot.
  property var inputNodes: ({})
  function refreshInputNodes() {
    var map = {}
    var all = Pipewire.nodes ? Pipewire.nodes.values : []
    for (var i = 0; i < all.length; i++) {
      var n = all[i]
      if (!n || n.isStream || n.isSink || !n.name) continue
      map[n.name] = n
    }
    inputNodes = map
  }
  readonly property int liveNodeCount: svc.nodeCount
  onLiveNodeCountChanged: refreshInputNodes()
  readonly property var meteredNodes: {
    var out = []
    for (var i = 0; i < inputs.length; i++) {
      var n = inputNodes[inputs[i].name]
      if (n) out.push(n)
    }
    return out
  }
  PwObjectTracker { objects: root.meteredNodes }

  // Levels set from a device row, shown at once and kept until a reading of `ballroom json` agrees or three
  // seconds pass. The default device is not kept here: its row moves with the live sliders above.
  property var localLevels: ({})
  function levelOf(device, section) {
    if (!device) return 0
    if (device.isDefault) return section === "input" ? inputVolume : outputVolume
    var l = localLevels[device.name]
    return l && Date.now() - l.at < 3000 ? l.value : Number(device.volume)
  }
  function setDeviceLevel(device, section, value) {
    if (!device) return
    var v = Math.max(0, Math.min(1, Math.round(value * 100) / 100))
    if (device.isDefault) {
      if (section === "input") setInputVolume(v)
      else showVolumeOsd(setOutputVolume(v))
      return
    }
    var next = Object.assign({}, localLevels)
    next[device.name] = { value: v, at: Date.now() }
    localLevels = next
    svc.setDeviceVolume(device.name, v)
  }
  // A level that the command could not set is not shown as if it were.
  Connections { target: svc; function onFailedActionsChanged() { root.localLevels = {} } }
  function settleLocalLevels() {
    var next = {}
    var all = Model.list(info, "outputs").concat(Model.list(info, "inputs"))
    for (var name in localLevels) {
      var l = localLevels[name]
      if (Date.now() - l.at >= 3000) continue
      var d = null
      for (var i = 0; i < all.length; i++) if (all[i].name === name) d = all[i]
      if (d && Math.abs(Number(d.volume) - l.value) < 0.015) continue
      next[name] = l
    }
    localLevels = next
  }

  // ---- keyboard cursor: sections top to bottom, -1 is the section's own control (switch or slider) ----
  property bool cursorActive: false
  property string section: "header"
  property int index: -1
  // The sections the cursor walks, in the order they stand in the panel: the levels and the equalizer first,
  // then the stage and what plays, then the library, and the device lists at the foot. A section with -1 as its
  // floor has a control of its own on that index (a slider, a fold line); the others are rows only.
  // The cursor walks the sections in the order they stand in the panel, and that order is now the owner's: it
  // follows the same plan the sections are built from. A section that is switched off or has nothing to show is
  // not a stop.
  function sectionShows(id) {
    if (id === "output") return true
    if (id === "input") return !!source
    if (id === "sound") return showSound
    if (id === "playing") return streams.length > 0
    if (id === "library") return showStage && !!stg && stg.available
    return false
  }
  readonly property var sections: {
    if (settingsOpen) return ["settings"]
    var list = ["header"]
    for (var i = 0; i < sectionPlan.length; i++)
      if (sectionPlan[i].on && sectionShows(sectionPlan[i].id)) list.push(sectionPlan[i].id)
    return list
  }

  // How many rows a section has under its own line. A folded one has none; its line stays, so it can be opened
  // again from the keyboard. OUTPUT and INPUT keep their master level on 0 even when folded: folding takes the
  // devices under it away, not the level.
  function countOf(s) {
    if (s === "playing") return streams.length
    if (s === "settings") return settingOrder.length
    if (s === "output") return 1 + (foldOpen(s) ? outputs.length : 0)
    if (s === "input") return 1 + (foldOpen(s) ? inputs.length : 0)
    if (!foldOpen(s)) return 0
    return s === "library" ? stageRows.length : s === "sound" ? 1 : 0
  }
  // The device a cursor row under a master level stands for: row 0 is the level itself, the devices follow.
  function deviceAt(s, i) { return i >= 1 ? (s === "input" ? inputs[i - 1] : outputs[i - 1]) : undefined }
  // Every section that folds has its line as its own control on -1, the way the library always had: the arrows
  // reach it, and Enter on it folds. Rows start at 0.
  function floorOf(s) { return s === "playing" || s === "settings" ? 0 : -1 }
  // The library's rows change from the field, the tab, the sub-tab and the fold, not only from a new reading:
  // without this the cursor could stand past the end and the next arrow key would jump out of the section.
  onStageRowsChanged: clampCursor()
  // Folding a list takes its rows away under the cursor; without this the cursor stands past the end and the
  // next arrow key jumps out of the section.
  onFoldNowChanged: clampCursor()
  function clampCursor() {
    if (sections.indexOf(section) < 0) { section = "header"; index = -1 }
    var max = countOf(section) - 1
    if (index > max) index = Math.max(floorOf(section), max)
  }
  function moveCursor(delta) {
    var s = sections.indexOf(section)
    var next = index + delta
    if (next >= floorOf(section) && next < countOf(section)) { index = next; return }
    // The library is ten rows at a time: past the last one comes the next page, not the next section, and back
    // past the first one comes the one before it, at its foot.
    if (section === "library" && delta > 0 && (resultsInfo.canNext || resultsInfo.canFetchMore)) { pageForward(); index = 0; return }
    if (section === "library" && delta < 0 && index === 0 && resultsInfo.canPrev) { pageBack(); index = Math.max(0, countOf(section) - 1); return }
    var ns = s + (delta > 0 ? 1 : -1)
    if (ns < 0 || ns >= sections.length) return
    section = sections[ns]
    index = delta > 0 ? floorOf(section) : countOf(section) - 1
    if (index < floorOf(section)) index = floorOf(section)
  }
  function adjust(delta) {
    if (svc.stale) return
    if (section === "header" || (section === "output" && index === 0)) showVolumeOsd(setOutputVolume(outputVolume + delta))
    else if (section === "input" && index === 0) setInputVolume(inputVolume + delta)
    else if (section === "output" && deviceAt(section, index)) setDeviceLevel(deviceAt(section, index), "output", levelOf(deviceAt(section, index), "output") + delta)
    else if (section === "input" && deviceAt(section, index)) setDeviceLevel(deviceAt(section, index), "input", levelOf(deviceAt(section, index), "input") + delta)
    else if (section === "sound" && index === 0) svc.usePreset(Model.presetStep(snd, delta))
    else if (section === "playing" && streams[index] && !(streams[index].stage === true && stg && stg.title !== "" && !stg.live && Number(stg.duration) > 0))
      svc.setStreamVolume(streams[index].serial, Number(streams[index].volume) + delta)
    // On our own row the arrows seek, where there is a position to seek to; on every other row they turn it down.
    else if (section === "playing" && streams[index] && streams[index].stage === true && stg && stg.title !== "" && !stg.live && Number(stg.duration) > 0)
      svc.stageCtl(["seek", delta > 0 ? "+5" : "-5"])
  }
  function activate() {
    if (svc.stale) return
    if (section === "settings") { var it = settingItems[String((settingOrder[index] || {}).key)]; if (it) it.activate(); return }
    if (section === "sound") { if (index < 0) toggleFold("sound"); else svc.usePreset(Model.presetStep(snd, 1)); return }
    if (section === "library") {
      // The fold line is the section's own control; a row plays, and a playlist opens.
      if (index < 0) { root.toggleFold("library"); return }
      var e = stageRows[index]
      if (e) svc.stageRun(e.openable ? ["sc", "open", e.play] : ["play", e.play])
      return
    }
    // Enter on our own row starts and stops what plays; m still mutes it, like every other row.
    if (section === "playing" && streams[index] && streams[index].stage === true) { stageToggle(); return }
    if (section === "playing" && streams[index]) { svc.toggleStreamMute(streams[index].serial); return }
    // Under a master level: Enter on the level mutes it, on a device makes that device the default.
    if (section === "output") { if (index < 0) toggleFold("output"); else if (index === 0) toggleOutputMute(); else if (deviceAt(section, index)) svc.makeDefaultOutput(deviceAt(section, index).name); return }
    if (section === "input") { if (index < 0) toggleFold("input"); else if (index === 0) toggleInputMute(); else if (deviceAt(section, index)) svc.makeDefaultInput(deviceAt(section, index).name); return }
    if (section === "header") toggleOutputMute()
  }
  // The star on a stage row: what is kept is dropped, anything else is kept. An entry has the same id in every
  // list, so a result and the favorite made from it are the same entry.
  function toggleFavorite(entry) {
    if (!entry || svc.stale) return
    // Keeping a playlist would leave the question what it should play; opening it answers that first.
    if (entry.openable && !entry.favorite) return
    svc.stageCtl(["fav", entry.favorite ? "rm" : "add", "id:" + String(entry.id)])
  }
  // m: whatever the cursor is on. A device row mutes that device, a slider its default, the header the output.
  function muteUnderCursor() {
    if (svc.stale) return
    // A row in the library is not a device: m there must not reach past it to the speakers.
    if (section === "library" || section === "sound" || section === "settings") return
    // Nor is the line a section folds by: m on it mutes nothing, instead of reaching past it to the default
    // output. Only the panel's own head sits on -1 and means the output.
    if (index < 0 && section !== "header") return
    if (section === "playing") { if (streams[index]) svc.toggleStreamMute(streams[index].serial); return }
    if (deviceAt(section, index)) { svc.toggleDeviceMute(deviceAt(section, index).name); return }
    if (section === "input") toggleInputMute()
    else toggleOutputMute()
  }
  function hovered(s, i) { cursorActive = true; section = s; index = i }
  // True while one of the panel's fields has the focus; see the key catcher, which stands aside then. Counted,
  // not bound to the fields by name: they live inside sections that are loaded and dropped as the order and the
  // switches say, and a name inside one of those is out of reach here. Counting also survives a move straight
  // from one field to the next, where the loser reports before the winner.
  property int editingCount: 0
  readonly property bool editing: editingCount > 0
  // Never below zero. The count is reset when the panel opens or closes, and a field that still had the focus
  // then reports leaving it afterwards: that used to take the count to -1, and the next field being typed in
  // brought it back to 0, which reads as "nobody is typing". The key catcher would have stood in front of the
  // field and swallowed the letters.
  function noteEditing(on) { editingCount = Math.max(0, editingCount + (on ? 1 : -1)) }
  // A field that goes away while it has the focus never reports leaving it, so the count is reset whenever the
  // panel opens or closes. The shell gives the panel its focus back at every opening anyway.
  // One handler only: QML rejects a second one for the same signal on the same object. Opening or closing the
  // panel folds everything back in and clears the count of fields being typed in.
  // One handler only: QML rejects a second one for the same signal on the same object. A panel that opens also
  // drops the order it was holding from a drag, and starts from what the shell holds.
  onOpenedChanged: { editingCount = 0; eqSettingsOpen = false; deviceOpen = ""; cursorActive = false; orderNow = null; dragCancel(); nameByHand = false }
  onSettingsOpenChanged: editingCount = 0
  // The account behind the browser session is asked for once per run of the shell, not once per panel opening.
  property bool accountAsked: false
  // Set when the user chose to type the name instead of naming a browser. Not a setting: the moment a name or a
  // browser is there, the question is over, and a panel that opens again asks it afresh. Otherwise a choice made
  // once would still stand after the name was thrown away, and the browsers would never be offered again.
  property bool nameByHand: false
  // The settings page takes the place of the panel's body. Its cursor is a row number: the rows are the schema,
  // and the schema does not move while the page is open.
  property bool settingsOpen: false
  // The name a device was given here, as opposed to the one it came with: the field shows the given one and
  // offers the other as its placeholder, so it is clear which is which.
  function aliasOf(device) {
    if (!device) return ""
    var own = String(device.label || "")
    return own === String(device.description || "") ? "" : own
  }
  // The limits a device can be given, as words a dropdown can hold.
  readonly property var capChoices: {
    var out = ["no limit"]
    for (var v = 20; v <= 100; v += 10) out.push(v + " %")
    return out
  }
  // Whether the equalizer's own settings are folded out under its curve.
  property bool eqSettingsOpen: false
  // The name of the device whose own settings are folded out, or empty. One at a time.
  property string deviceOpen: ""
  readonly property var settingGroups: Model.settingGroups(svc.settingsSchema)
  readonly property var settingOrder: Model.settingOrder(settingGroups)
  // The rows register themselves by key, so Enter can reach the one under the cursor across the groups.
  property var settingItems: ({})
  // Going to the page and back moves the cursor, it does not switch it on: the shell wants one mark on screen at
  // a time and wants it where the mouse or a key put it. Parking it on the first row lit that row grey with
  // nobody having gone there.
  function toggleSettings() {
    settingsOpen = !settingsOpen
    cursorActive = false
    index = -1
    section = settingsOpen ? "settings" : "header"
  }
  // After a tab is chosen: the search field takes the keys where there is one, the panel keeps them where the
  // field is hidden. The field is inside a section that is loaded on demand, so it is asked, not reached for.
  signal focusSearchRequested()
  signal clearSearchRequested()
  // Clearing the search is not the field's business alone. The field only reports a change, and a field that is
  // already empty reports nothing: what was searched for stayed in searchText, and the panel went on saying
  // "nothing found for" a word that stood nowhere. So the words are dropped here, and the field is told after.
  function clearSearch() { searchText = ""; restoreText = ""; clearSearchRequested() }
  function focusSearch() { focusSearchRequested() }


  // ---- the bar ----
  // The icon and the spectrum beside it are one target: either opens the panel, mutes, or turns the volume, and
  // the shell's mark under an open panel spans both.
  function barPressed(b) {
    if (b === Qt.RightButton) toggleOutputMute()
    else if (b === Qt.MiddleButton) toggleInputMute()
    else toggle()
  }
  function barWheel(delta) {
    var wheel = Util.wheelSteps(wheelAccumulator, delta)
    wheelAccumulator = wheel.remainder
    if (wheel.steps === 0) return
    showVolumeOsd(setOutputVolume(outputVolume + wheel.steps * 0.05))
  }
  readonly property real openPanelIndicatorWidth: Math.round(face.width * (barSpectrum.visible ? 0.8 : 0.55))
  // Pausing answers within milliseconds. Playing again may have to tune a stream in anew, since a live stream is
  // stopped for a pause, and that takes seconds: it goes through the process that waits for the stage, so it
  // never runs into the deadline of the quick one.
  function stageToggle() {
    if (Model.stagePlaying(stg)) svc.stageCtl(["toggle"])
    else svc.stageRun(["toggle"])
  }
  // The players that report over MPRIS, read here so the binding follows each of them, and handed to the model as
  // plain rows. They report every change themselves, so the button follows a click at once; the stage is read.
  readonly property var mprisList: Mpris.players ? Mpris.players.values : []
  readonly property var mprisRows: {
    var out = []
    for (var i = 0; i < mprisList.length; i++) {
      var p = mprisList[i]
      if (!p) continue
      out.push({ dbusName: p.dbusName, desktopEntry: p.desktopEntry, identity: p.identity, trackTitle: p.trackTitle,
                 trackArtist: p.trackArtist, isPlaying: p.isPlaying, canPause: p.canPause, canPlay: p.canPlay, canTogglePlaying: p.canTogglePlaying })
    }
    return out
  }
  // One story for the whole widget; each part adds what its own clicks do.
  readonly property var barPlaying: Model.nowPlaying(stg, mprisRows)
  function barTip(hint) { return Model.tooltip(info, root.opened, barPlaying, barMedia ? barMedia.paused : [], hint) }
  // The players the button paused, by their bus name: the next click plays these again and nothing else.
  property var mediaHeld: []
  readonly property var barMedia: svc.setting("stageButton", true) === true ? Model.barMedia(stg, mprisRows, mediaHeld) : null
  function mprisPlayer(key) {
    for (var i = 0; i < mprisList.length; i++) if (mprisList[i] && String(mprisList[i].dbusName) === key) return mprisList[i]
    return null
  }
  function mediaPress(b) {
    var m = barMedia
    if (!m) return
    if (b === Qt.RightButton) {
      // Stop: the stage stops, a player that plays is paused, and the button forgets them all and goes.
      if (m.stage) svc.stageCtl(["stop"])
      if (m.pausing) mediaPause(m.keys)
      mediaHeld = []
      return
    }
    if (m.pausing) {
      if (m.stage) svc.stageCtl(["pause"])
      mediaPause(m.keys)
      mediaHeld = m.keys
    } else {
      if (m.stage) stageToggle()
      for (var i = 0; i < m.keys.length; i++) {
        var p = mprisPlayer(m.keys[i])
        if (p && p.canPlay) p.play()
        else if (p && p.canTogglePlaying && !p.isPlaying) p.togglePlaying()
      }
      mediaHeld = []
    }
  }
  function mediaPause(keys) {
    for (var i = 0; i < keys.length; i++) {
      var p = mprisPlayer(keys[i])
      if (p && p.canPause) p.pause()
      else if (p && p.canTogglePlaying && p.isPlaying) p.togglePlaying()
    }
  }

  Row {
    id: face
    height: parent.height
    spacing: 0

    BarIconButton {
      id: button
      bar: root.bar
      height: parent.height
      text: Model.outputGlyph(root.outputDevice, root.outputVolume, root.outputMuted)
      tooltipText: root.barTip(Model.HINT_OUTPUT)
      onPressed: function (b) { root.barPressed(b) }
      onWheelMoved: function (delta) { root.barWheel(delta) }
    }

    // Pause and play for whatever plays: the stage, the browser, a music player. It stands between the icon and
    // the spectrum, so the icon keeps its place at the start of the widget. Right-click stops, and the button goes.
    BarIconButton {
      id: mediaButton
      bar: root.bar
      height: parent.height
      text: root.barMedia ? root.barMedia.glyph : ""
      tooltipText: root.barMedia ? root.barTip(root.barMedia.hint) : ""
      dimmed: svc.stageBusy
      onPressed: function (b) {
        if (b === Qt.MiddleButton) root.toggleInputMute()
        else root.mediaPress(b)
      }
      onWheelMoved: function (delta) { root.barWheel(delta) }
    }

    // A small spectrum beside the icon while something plays. The bars take the loudest band they cover.
    WidgetButton {
      id: barSpectrum
      bar: root.bar
      readonly property int count: svc.spectrumBars
      readonly property var levels: Model.barBands(svc.bands, count)
      labelVisible: false
      hasVisualContent: svc.spectrumWanted && !(root.bar && root.bar.vertical) && !Model.quiet(svc.bands)
      fixedWidth: count * Style.space(3) + Style.space(6)
      height: parent.height
      tooltipText: root.barTip(Model.HINT_OUTPUT)
      onPressed: function (b) { root.barPressed(b) }
      onWheelMoved: function (delta) { root.barWheel(delta) }

      Row {
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: parent.right
        anchors.rightMargin: Style.space(4)
        spacing: Style.space(1)
        Repeater {
          model: barSpectrum.count
          Rectangle {
            required property int index
            width: Style.space(2)
            height: Math.max(Style.space(2), Math.round(barSpectrum.height * 0.55 * barSpectrum.levels[index]))
            anchors.bottom: parent ? parent.bottom : undefined
            radius: 1
            color: root.bandColor(index, barSpectrum.count, root.outputMuted)
          }
        }
      }
    }
  }

  // ---- the panel ----
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keys
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(660))

    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      // The catcher takes keys before the item that has the focus (Keys.BeforeItem), so while a field is being
      // typed in it must stand aside: otherwise Enter played the row under the cursor instead of searching, and
      // the letters j, k, l, h and x moved the cursor instead of landing in the field. One counter for the whole
      // panel, page included: two ways of saying "somebody is typing" are two ways of disagreeing about it.
      blocked: root.editing
      onMoveRequested: function (dx, dy) {
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.moveCursor(dy)
        else if (dx !== 0) root.adjust(dx * 0.05)
      }
      onActivateRequested: if (root.cursorActive) root.activate()
      onCloseRequested: { if (root.settingsOpen) root.toggleSettings(); else root.close() }
      onTabRequested: function (direction) { root.switchPanel(direction) }
      onTextKey: function (t) {
        if (t === "s" || t === "S") root.toggleSettings()
        else if (root.settingsOpen) { /* the page has no other letters of its own */ }
        else if (t === "m" || t === "M") root.muteUnderCursor()
        else if ((t === "f" || t === "F") && root.section === "library" && root.index >= 0) root.toggleFavorite(root.stageRows[root.index])
        else if ((t === "e" || t === "E") && root.showSound) svc.setEq(!root.snd.enabled)
      }

      ScrollView {
        id: scroll
        anchors.fill: parent
        // The bar sits at the right edge of the view. The view reaches into the panel's padding, so the bar
        // ends up a little inside the border instead of a whole padding away from it; the column gives that
        // reach back, so nothing else moves.
        readonly property int reach: Math.max(0, panel.padding - Style.space(4))
        anchors.rightMargin: -reach
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        // As the shell's own panels do it: no bar and no dragging while everything fits.
        readonly property bool overflows: column.implicitHeight > height
        ScrollBar.vertical.policy: overflows ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff
        Binding { target: scroll.contentItem; property: "interactive"; value: scroll.overflows }

        Column {
          id: column
          // The bar lies over the content in the shell's style; when it is wider than the reach, the column
          // leaves it the rest, so it never covers a control on the right while the panel scrolls.
          width: scroll.availableWidth - scroll.reach - (scroll.overflows ? Math.max(0, scroll.ScrollBar.vertical.width - scroll.reach) : 0)
          spacing: Style.space(14)

          // ---------- hero: icon · title and mood · switch ----------
          Item {
            width: parent.width
            implicitHeight: Math.max(heroIcon.implicitHeight, heroText.implicitHeight, powerSwitch.implicitHeight)

            Text {
              id: heroIcon
              textFormat: Text.PlainText
              text: Model.outputGlyph(root.outputDevice, root.outputVolume, root.outputMuted)
              color: root.fg
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
              opacity: root.outputMuted ? 0.5 : 1.0
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            // On means the output is audible. The switch owns the output's mute here, mouse and keyboard alike.
            // The way into the settings, and back out of them. It sits beside the switch, where the eye already
            // goes for the one control the hero has.
            PanelActionButton {
              id: gearButton
              iconText: "\u{F0493}"
              tooltipText: root.settingsOpen ? "Back to the panel (Esc)" : "Settings (s)"
              foreground: root.settingsOpen ? Color.accent : root.fg
              fontFamily: root.fontFamily
              anchors.right: powerSwitch.left
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              onClicked: root.toggleSettings()
            }

            ToggleSwitch {
              id: powerSwitch
              checked: !!root.sink && !root.outputMuted
              hasCursor: root.cursorActive && root.section === "header"
              foreground: root.fg
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onHovered: function (on) { if (on) root.hovered("header", -1) }
              onToggled: root.toggleOutputMute()

              PanelToolTip {
                visible: powerSwitch.containsMouse
                text: root.outputMuted ? "Unmute the output" : "Mute the output"
                fontFamily: root.fontFamily
              }
            }

            Column {
              id: heroText
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: parent.right
              anchors.rightMargin: powerSwitch.width + gearButton.width + Style.space(22)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                textFormat: Text.PlainText
                text: svc.title
                color: root.fg
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
                width: parent.width
              }
              Text {
                textFormat: Text.PlainText
                text: svc.stale ? "STATE UNKNOWN" : Model.heroLine(root.info, root.outputShown, root.outputMuted)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
                elide: Text.ElideRight
                width: parent.width
              }
            }
          }

          // Everything but the hero and the foot: the settings page takes its place without moving them.
          Column {
            id: panelBody
            width: parent.width
            spacing: Style.space(14)
            visible: !root.settingsOpen

            // Every section is loaded from the plan: which ones, and in which order, is one setting, so the
            // panel can be laid out as its owner wants it. A Column puts its children in the order they were
            // written, so a section that may move has to be a component that is loaded, not a child in place.
            Repeater {
              model: root.sectionPlan
              Loader {
                required property var modelData
                width: panelBody.width
                height: item ? item.implicitHeight : 0
                active: modelData.on
                visible: active
                sourceComponent: root.sectionComponent(modelData.id)
              }
            }
          }

          // ---------- settings ----------
          // One row per setting, built from the manifest's schema, so the panel and the terminal show the same
          // rows with the same words and the same bounds. A change is saved at once and comes back from the
          // shell; nothing is held here. The DI.FM listen key is not among them: it is a secret, not a widget
          // setting, and it is asked for where it is needed.
          Column {
            width: parent.width
            spacing: Style.space(10)
            visible: root.settingsOpen

            PanelSectionHeader { text: "SETTINGS"; foreground: root.fg; fontFamily: root.fontFamily }

            // The page offers the browsers found here, so it asks for them once when it opens.
            Timer { interval: 200; running: root.settingsOpen && !svc.browsersAsked; onTriggered: svc.findBrowsers() }

            Text {
              visible: root.settingGroups.length === 0
              textFormat: Text.PlainText
              text: "The settings could not be read from the plugin's manifest."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.Wrap
              width: parent.width
              leftPadding: Style.space(6)
            }

            Repeater {
              model: root.settingGroups
              SettingGroup {
                required property var modelData
                width: column.width
                group: modelData
              }
            }

            // The limit a device of this kind is brought down to when it arrives and has none of its own. This
            // is what keeps a freshly plugged headset from taking the level of the speakers, so it is not the
            // same thing as the limit on one device in its own row.
            BorderSurface {
              width: column.width
              implicitHeight: limitsColumn.implicitHeight + Style.space(14)
              radius: Style.cornerRadius
              borderSpec: Border.controlSpec("normal", root.fg, Color.accent)
              color: "transparent"
              Column {
                id: limitsColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: Style.space(8)
                spacing: Style.space(6)
                PanelSectionHeader {
                  width: parent.width - Style.space(16); x: Style.space(8)
                  text: "LIMITS"; foreground: root.fg; fontFamily: root.fontFamily
                }
                Repeater {
                  model: ["headphones", "speakers"]
                  Item {
                    required property var modelData
                    width: limitsColumn.width - Style.space(16)
                    x: Style.space(8)
                    implicitHeight: Math.max(capLabel.implicitHeight, capList.implicitHeight) + Style.space(4)
                    Text {
                      id: capLabel
                      textFormat: Text.PlainText
                      text: modelData === "headphones" ? "New headphones start at" : "New speakers start at"
                      color: root.fg
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      anchors.left: parent.left
                      anchors.right: capList.left
                      anchors.rightMargin: Style.space(10)
                      elide: Text.ElideRight
                      anchors.verticalCenter: parent.verticalCenter
                    }
                    Dropdown {
                      id: capList
                      width: Style.space(120)
                      showLabel: false
                      fontFamily: root.fontFamily
                      foreground: root.fg
                      accent: Color.accent
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      options: root.capChoices
                      value: Model.classCapText(root.info, modelData)
                      onChanged: function (v) {
                        if (v === Model.classCapText(root.info, modelData)) return
                        svc.setClassCap(modelData, v === "no limit" ? "none" : v.replace(" %", ""))
                      }
                      onPopupOpenChanged: root.noteEditing(popupOpen)
                      MouseArea { anchors.fill: parent; enabled: parent.popupOpen; onClicked: parent.close() }
                    }
                  }
                }
                Text {
                  width: parent.width - Style.space(16); x: Style.space(8)
                  textFormat: Text.PlainText
                  text: "An output of this kind is brought down to this before it becomes the default one, and again whenever one arrives. What you turn up afterwards stays. A device given its own limit in its row keeps that one."
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }
              }
            }

            // Bluetooth, as far as it is not about one device: whether WirePlumber may switch a headset to call
            // mode when something opens its microphone. Mode and codec of one device sit in that device's row.
            BorderSurface {
              width: column.width
              implicitHeight: btColumn.implicitHeight + Style.space(14)
              radius: Style.cornerRadius
              borderSpec: Border.controlSpec("normal", root.fg, Color.accent)
              color: "transparent"
              Column {
                id: btColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: Style.space(8)
                spacing: Style.space(6)
                PanelSectionHeader {
                  width: parent.width - Style.space(16); x: Style.space(8)
                  text: "BLUETOOTH"; foreground: root.fg; fontFamily: root.fontFamily
                }
                Item {
                  width: btColumn.width - Style.space(16)
                  x: Style.space(8)
                  implicitHeight: Math.max(btAutoLabel.implicitHeight, btAutoSwitch.implicitHeight)
                  Text {
                    id: btAutoLabel
                    textFormat: Text.PlainText
                    text: "Call mode when an application records"
                    color: root.fg
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    anchors.left: parent.left
                    anchors.right: btAutoSwitch.left
                    anchors.rightMargin: Style.space(10)
                    elide: Text.ElideRight
                    anchors.verticalCenter: parent.verticalCenter
                  }
                  ToggleSwitch {
                    id: btAutoSwitch
                    checked: root.info && root.info.btAuto === true
                    foreground: root.fg
                    accent: Color.accent
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    onToggled: svc.setBtAuto(!(root.info && root.info.btAuto === true))
                  }
                }
                Text {
                  width: parent.width - Style.space(16); x: Style.space(8)
                  textFormat: Text.PlainText
                  text: "When an application opens the microphone of a Bluetooth headset, WirePlumber switches it to call mode: the microphone works, the music sounds like a phone call. Off keeps the music, and the headset's microphone is then not available."
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }
              }
            }

            // The diagnosis. It asks PipeWire, WirePlumber and the units and takes a moment, so it runs only
            // when it is asked for and never as part of the reading that keeps the panel current.
            BorderSurface {
              width: column.width
              implicitHeight: docColumn.implicitHeight + Style.space(14)
              radius: Style.cornerRadius
              borderSpec: Border.controlSpec("normal", root.fg, Color.accent)
              color: "transparent"
              Column {
                id: docColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: Style.space(8)
                spacing: Style.space(6)
                Item {
                  width: docColumn.width - Style.space(16)
                  x: Style.space(8)
                  implicitHeight: docHeader.implicitHeight
                  PanelSectionHeader { id: docHeader; text: "DIAGNOSIS"; foreground: root.fg; fontFamily: root.fontFamily }
                  Text {
                    text: svc.doctorRunning ? "LOOKING\u2026" : (svc.doctorText === "" ? "RUN IT" : "AGAIN")
                    color: root.fg
                    opacity: svc.doctorRunning ? 0.5 : 0.8
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 1.0
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    MouseArea {
                      anchors.fill: parent
                      anchors.margins: -Style.space(4)
                      enabled: !svc.doctorRunning
                      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                      onClicked: svc.runDoctor()
                    }
                  }
                }
                Text {
                  visible: svc.doctorText === "" && !svc.doctorRunning
                  width: parent.width - Style.space(16); x: Style.space(8)
                  textFormat: Text.PlainText
                  text: "Fourteen checks: whether PipeWire answers and how fast, whether WirePlumber holds the defaults, the units, the clock, dropouts, the default output and input, the equalizer and what sits in front of the output, mpv, and what is stored here. The answer to why there is no sound."
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }
                Repeater {
                  model: Model.doctorLines(svc.doctorText)
                  Item {
                    required property var modelData
                    width: docColumn.width - Style.space(16)
                    x: Style.space(8)
                    implicitHeight: docText.implicitHeight + Style.space(3)
                    Text {
                      id: docMark
                      text: modelData.state === "ok" ? "\u2713" : modelData.state === "warn" ? "!" : "\u2717"
                      color: modelData.state === "ok" ? root.fg : Color.urgent
                      opacity: modelData.state === "ok" ? 0.6 : 1.0
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      width: Style.space(14)
                      anchors.left: parent.left
                      anchors.top: parent.top
                    }
                    Text {
                      id: docText
                      textFormat: Text.PlainText
                      text: String(modelData.key) + "  " + String(modelData.text)
                      color: modelData.state === "ok" ? root.dim : root.fg
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      wrapMode: Text.WordWrap
                      anchors.left: docMark.right
                      anchors.right: parent.right
                      anchors.top: parent.top
                    }
                  }
                }
              }
            }

          }

          // ---------- foot ----------
          // What is wrong right now, and nothing else. The panel is the only surface; what the terminal can do
          // beside it is a verb, and `ballroom help` lists them.
          PanelSeparator { foreground: root.fg }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: svc.errorText !== "" ? svc.errorText : (svc.busy ? "working…" : (svc.spectrumError !== "" ? svc.spectrumError : Model.healthLine(root.info)))
            color: svc.errorText !== "" || Model.healthLine(root.info) !== "" ? Color.urgent : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
            visible: text !== ""
          }
        }
      }
    }
  }

  // ---- pieces ----

  // A glyph that is a button, in the stage's row of controls.
  component StageButton: Text {
    id: sb
    property string glyph: ""
    property bool dimmed: false
    signal clicked()
    text: glyph
    color: root.fg
    font.family: root.fontFamily
    font.pixelSize: Style.font.title
    opacity: svc.stageBusy || dimmed ? 0.35 : 1.0
    MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor; onClicked: sb.clicked() }
  }

  // A line that does not fit scrolls through, round and round, instead of being cut: a track title is the one
  // thing in its row worth reading in full. It rests at the start before each round so the beginning can be read,
  // and it only moves while the panel is open, so a closed panel costs nothing.
  //
  // The position comes from a clock kept per text, not from an animation in the row: the rows of PLAYING are
  // built anew on every reading, and an animation would start over each time and never reach the end.
  property var marqueeEpochs: ({})
  function marqueeEpoch(text) {
    var e = marqueeEpochs[text]
    if (e === undefined) {
      if (Object.keys(marqueeEpochs).length > 32) marqueeEpochs = ({})
      e = Date.now()
      marqueeEpochs[text] = e
    }
    return e
  }
  component Marquee: Item {
    id: mq
    property string text: ""
    property color color: root.fg
    property int pixelSize: Style.font.body
    property bool bold: false
    readonly property real gap: Style.space(40)
    readonly property real cycle: mqText.implicitWidth + gap
    readonly property bool overflows: mqText.implicitWidth > width + 1
    readonly property int restMs: 2500
    readonly property real pxPerSec: 40
    implicitHeight: mqText.implicitHeight
    clip: true
    function tick() {
      var period = restMs + cycle / pxPerSec * 1000
      var phase = (Date.now() - root.marqueeEpoch(text)) % period
      mqRow.x = phase < restMs ? 0 : -Math.min(cycle, (phase - restMs) / 1000 * pxPerSec)
    }
    Timer {
      interval: 33
      repeat: true
      running: mq.overflows && root.opened && mq.visible
      triggeredOnStart: true
      onTriggered: mq.tick()
      onRunningChanged: if (!running) mqRow.x = 0
    }
    Row {
      id: mqRow
      spacing: mq.gap
      Text {
        id: mqText
        textFormat: Text.PlainText
        text: mq.text
        color: mq.color
        font.family: root.fontFamily
        font.pixelSize: mq.pixelSize
        font.bold: mq.bold
      }
      // The second copy follows the first, so the end of the title runs straight into its beginning.
      Text {
        visible: mq.overflows
        textFormat: Text.PlainText
        text: mq.text
        color: mq.color
        font.family: root.fontFamily
        font.pixelSize: mq.pixelSize
        font.bold: mq.bold
      }
    }
  }

  Component {
    id: outputSection
    Column {
      width: parent.width
      spacing: Style.space(14)
                // ---------- output ----------
                PanelSeparator { foreground: root.fg }

                Column {
                  width: parent.width
                  spacing: Style.space(6)

                  Item {
                    width: parent.width
                    implicitHeight: outputHeader.implicitHeight + Style.space(4)
                    // The line folds the section. It is declared before everything else on it, so a control on the
                    // same line still gets its own clicks.
                    FoldGrip { sectionId: "output" }
                    HoverHandler { onHoveredChanged: if (hovered) root.hovered("output", -1) }
                    PanelSectionHeader { id: outputHeader; text: root.chevron("output") + "OUTPUT"; foreground: root.fg; fontFamily: root.fontFamily; anchors.verticalCenter: parent.verticalCenter }
                    // Folded, the line says how many devices it hides: folding hides the rows, not that they exist.
                    Text {
                      visible: !root.foldOpen("output")
                      textFormat: Text.PlainText
                      text: Model.foldNote(root.outputs.length, "device")
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      anchors.left: outputHeader.right
                      anchors.leftMargin: Style.space(12)
                      anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                      textFormat: Text.PlainText
                      text: Math.round(root.outputShown * 100) + "%"
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      opacity: root.outputMuted ? 0.5 : 1.0
                      anchors.right: parent.right
                      anchors.rightMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                    }
                  }

                  // The master level stays when the section folds; what folds away are the devices under it.
                  CursorSurface {
                    width: parent.width
                    height: outputSlider.implicitHeight + Style.spacing.controlGap
                    hasCursor: root.cursorActive && root.section === "output" && root.index === 0
                    foreground: root.fg
                    outline: true
                    // The switch for this side, at the left of its slider: a speaker and a microphone that
                    // wear a stroke when they are off. On the line above it would break the flight of the
                    // section titles, which all start at the same place.
                    Text {
                      id: outputMute
                      textFormat: Text.PlainText
                      text: Model.outputGlyph(root.outputDevice, root.outputVolume, root.outputMuted)
                      color: root.fg
                      opacity: root.outputMuted ? 1.0 : 0.45
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.title
                      width: Style.space(22)
                      horizontalAlignment: Text.AlignHCenter
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(4)
                      anchors.verticalCenter: parent.verticalCenter
                      MouseArea {
                        id: outputMuteArea
                        anchors.fill: parent
                        anchors.margins: -Style.space(2)
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.toggleOutputMute()
                        PanelToolTip { visible: outputMuteArea.containsMouse; text: root.outputMuted ? "Sound on (m)" : "Sound off (m)"; fontFamily: root.fontFamily }
                      }
                    }
                    PanelSlider {
                      id: outputSlider
                      bar: root.bar
                      anchors.fill: parent
                      anchors.leftMargin: outputMute.width + Style.space(10)
                      anchors.rightMargin: Style.space(6)
                      minimum: 0
                      maximum: 1
                      step: 0.05
                      value: root.outputVolume
                      opacity: root.outputMuted ? 0.5 : 1.0
                      enabled: !!root.sink
                      onMoved: function (v) { root.setOutputVolume(v) }
                      onRightClicked: root.toggleOutputMute()
                      onDraggingChanged: root.outputLive = dragging ? liveValue : -1
                      onLiveValueChanged: if (dragging) root.outputLive = liveValue
                      WheelGuard {}
                    }
                    HoverHandler { onHoveredChanged: if (hovered) root.hovered("output", 0) }
                  }

                  // What plays, as it plays, whenever the panel is open: silence is the hairline, so an idle room
                  // still reads as a room that is being watched, like the input's ON AIR.
                  // The equalizer draws the same bands behind its curve, where they carry a second meaning (the sound
                  // before the curve acts on it). Two sets of the same bars one above the other say nothing twice, so
                  // this one steps aside while SOUND is there, and comes back when it is switched off.
                  Spectrum {
                    visible: svc.spectrumWanted && !root.showSound && root.foldOpen("output")
                    width: parent.width
                    bands: svc.bands
                    dimmed: root.outputMuted
                    caption: "ON STAGE"
                  }

                  // ---------- output devices ----------
                  // The outputs, as the children of their level: the default one is marked, a click on another makes
                  // it the default, and each row carries its own level, mute and gear. Set in from the edge, so the
                  // master above reads as the parent.
                  DeviceList { sectionName: "output"; devices: root.outputs }
                }
    }
  }
  Component {
    id: inputSection
    Column {
      width: parent.width
      spacing: Style.space(14)
                // ---------- input ----------
                // No line between the two levels: OUTPUT and INPUT are the same kind of thing, a master level with its
                // devices under it, and a rule between them would split what belongs together.
                Column {
                  width: parent.width
                  spacing: Style.space(6)
                  visible: root.inputs.length > 0 || !!root.source

                  Item {
                    width: parent.width
                    implicitHeight: inputHeader.implicitHeight + Style.space(4)
                    FoldGrip { sectionId: "input" }
                    HoverHandler { onHoveredChanged: if (hovered) root.hovered("input", -1) }
                    PanelSectionHeader { id: inputHeader; text: root.chevron("input") + "INPUT"; foreground: root.fg; fontFamily: root.fontFamily; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                      visible: !root.foldOpen("input")
                      textFormat: Text.PlainText
                      text: Model.foldNote(root.inputs.length, "device")
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      anchors.left: inputHeader.right
                      anchors.leftMargin: Style.space(12)
                      anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                      textFormat: Text.PlainText
                      text: Math.round((inputSlider.dragging ? inputSlider.liveValue : root.inputVolume) * 100) + "%"
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      opacity: root.inputMuted ? 0.5 : 1.0
                      anchors.right: parent.right
                      anchors.rightMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                    }
                  }

                  CursorSurface {
                    visible: !!root.source
                    width: parent.width
                    // More room than a box that holds only a slider: the meter is a bare bar with no padding of its
                  // own, so the shell's control gap of 8 left it almost against the lower edge.
                  height: inputControls.implicitHeight + Style.spacing.controlGap + Style.space(8)
                    hasCursor: root.cursorActive && root.section === "input" && root.index === 0
                    foreground: root.fg
                    outline: true
                    // The switch for this side, at the left of its slider: a speaker and a microphone that
                    // wear a stroke when they are off. On the line above it would break the flight of the
                    // section titles, which all start at the same place.
                    Text {
                      id: inputMute
                      textFormat: Text.PlainText
                      text: Model.muteGlyph("input", root.inputMuted)
                      color: root.fg
                      opacity: root.inputMuted ? 1.0 : 0.45
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.title
                      width: Style.space(22)
                      horizontalAlignment: Text.AlignHCenter
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(4)
                      anchors.verticalCenter: parent.verticalCenter
                      MouseArea {
                        id: inputMuteArea
                        anchors.fill: parent
                        anchors.margins: -Style.space(2)
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.toggleInputMute()
                        PanelToolTip { visible: inputMuteArea.containsMouse; text: root.inputMuted ? "Microphone on (m)" : "Microphone off (m)"; fontFamily: root.fontFamily }
                      }
                    }

                    // The slider first, at the same height as the one for the output above it, and what the
                    // microphone hears under it. The meter used to sit on top, where a quiet room left a dark strip
                    // that read as a gap over a box that had slipped down.
                    Column {
                      id: inputControls
                      anchors.left: parent.left
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.leftMargin: inputMute.width + Style.space(10)
                      anchors.rightMargin: Style.space(6)
                      spacing: Style.space(5)

                      PanelSlider {
                        id: inputSlider
                        bar: root.bar
                        width: parent.width
                        minimum: 0
                        maximum: 1
                        step: 0.05
                        value: root.inputVolume
                        opacity: root.inputMuted ? 0.5 : 1.0
                        enabled: !!root.source
                        onMoved: function (v) { root.setInputVolume(v) }
                        onRightClicked: root.toggleInputMute()
                        WheelGuard {}
                      }

                      // How loud the microphone is right now, under the slider that sets how loud it may be.
                      Rectangle {
                        width: parent.width
                        height: Math.max(Style.space(5), Style.spacing.xs)
                        color: Util.alpha(root.fg, 0.18)
                        opacity: root.inputMuted ? 0.35 : 1.0
                        Rectangle {
                          height: parent.height
                          width: parent.width * (inputPeak.enabled ? Math.max(0, Math.min(1, inputPeak.peak)) : 0)
                          color: root.fg
                          Behavior on width { NumberAnimation { duration: 70 } }
                        }
                      }
                    }
                    HoverHandler { onHoveredChanged: if (hovered) root.hovered("input", 0) }
                  }

                  // What the microphone hears, while the panel is open and the microphone is not muted. Ballroom
                  // itself is reading it then, and says so.
                  Spectrum {
                    visible: svc.inputSpectrumRunning && root.foldOpen("input")
                    width: parent.width
                    bands: svc.inputBands
                    caption: "ON AIR"
                  }

                  Text {
                    visible: root.listeners.length > 0
                    textFormat: Text.PlainText
                    text: "Listening: " + root.listeners.join(", ")
                    color: Color.urgent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    elide: Text.ElideRight
                    width: parent.width
                    leftPadding: Style.space(6)
                    rightPadding: Style.space(6)
                  }

                  // ---------- input devices ----------
                  DeviceList { sectionName: "input"; devices: root.inputs }
                }
    }
  }
  Component {
    id: soundSectionComponent
    Column {
      width: parent.width
      spacing: Style.space(14)
                // ---------- sound ----------
                PanelSeparator { visible: root.showSound; foreground: root.fg }

                Column {
                  width: parent.width
                  spacing: Style.space(6)
                  visible: root.showSound

                  Item {
                    width: parent.width
                    implicitHeight: Math.max(soundHeader.implicitHeight, eqSwitch.implicitHeight)
                    FoldGrip { sectionId: "sound" }
                    HoverHandler { onHoveredChanged: if (hovered) root.hovered("sound", -1) }
                    PanelSectionHeader { id: soundHeader; text: root.chevron("sound") + "SOUND"; foreground: root.fg; fontFamily: root.fontFamily; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                      textFormat: Text.PlainText
                      text: Model.soundLine(root.snd, root.info)
                      color: root.snd && root.snd.enabled && !root.snd.running ? Color.urgent : root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      elide: Text.ElideRight
                      horizontalAlignment: Text.AlignRight
                      anchors.left: soundHeader.right
                      anchors.leftMargin: Style.space(12)
                      anchors.right: eqGear.left
                      anchors.rightMargin: Style.space(10)
                      anchors.verticalCenter: parent.verticalCenter
                    }
                    // The switch is the equalizer's, not the sound's: it says so.
                    Text {
                      id: eqLabel
                      text: "EQ"
                      color: root.snd && root.snd.enabled ? root.fg : root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      font.letterSpacing: 1.2
                      anchors.right: eqSwitch.left
                      anchors.rightMargin: Style.space(4)
                      anchors.verticalCenter: parent.verticalCenter
                    }
                    // The gear folds out what the equalizer can do beyond on, off and stepping a preset: the
                    // preamp, the two sides, and keeping or dropping a preset of one's own.
                    Text {
                      id: eqGear
                      text: "\u{F0493}"
                      color: root.fg
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      opacity: root.eqSettingsOpen ? 0.95 : 0.45
                      anchors.right: eqLabel.left
                      anchors.rightMargin: Style.space(10)
                      anchors.verticalCenter: parent.verticalCenter
                      MouseArea {
                        anchors.fill: parent
                        anchors.margins: -Style.space(5)
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.eqSettingsOpen = !root.eqSettingsOpen
                      }
                    }

                    ToggleSwitch {
                      id: eqSwitch
                      trackHeight: Math.max(16, Math.round(Style.spacing.controlHeight * 0.4))
                      checked: !!root.snd && root.snd.enabled
                      busy: svc.busy
                      foreground: root.fg
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                      onToggled: svc.setEq(!(root.snd && root.snd.enabled))
                      PanelToolTip { visible: eqSwitch.containsMouse; text: root.snd && root.snd.enabled ? "Equalizer off: the sound plays unchanged (e)" : "Equalizer on (e)"; fontFamily: root.fontFamily }
                    }
                  }

                  // The curve over what plays: the spectrum behind is the sound before the equalizer, the line is what
                  // the equalizer does to it.
                  Item {
                    id: curveBox
                    visible: root.foldOpen("sound")
                    width: parent.width
                    height: Style.space(72)
                    readonly property real range: Model.curveRange(root.snd)
                    readonly property var levels: Model.barBands(svc.bands, svc.spectrumBars * 2)

                    Row {
                      anchors.fill: parent
                      anchors.leftMargin: Style.space(6)
                      anchors.rightMargin: Style.space(6)
                      spacing: Style.space(2)
                      visible: svc.spectrumWanted
                      Repeater {
                        model: svc.spectrumBars * 2
                        Item {
                          required property int index
                          width: Math.max(1, (curveBox.width - Style.space(12) - (svc.spectrumBars * 2 - 1) * Style.space(2)) / (svc.spectrumBars * 2))
                          height: parent.height
                          Rectangle {
                            anchors.bottom: parent.bottom
                            width: parent.width
                            height: parent.height * curveBox.levels[index]
                            radius: 2
                            color: root.bandColor(index, svc.spectrumBars * 2, false)
                            opacity: 0.18
                            Behavior on height { NumberAnimation { duration: 60 } }
                          }
                        }
                      }
                    }
                    Rectangle {
                      anchors.left: parent.left
                      anchors.right: parent.right
                      anchors.leftMargin: Style.space(6)
                      anchors.rightMargin: Style.space(6)
                      y: Math.round(parent.height / 2)
                      height: 1
                      color: Util.alpha(root.fg, 0.22)
                    }
                    Canvas {
                      id: curveCanvas
                      anchors.fill: parent
                      anchors.leftMargin: Style.space(6)
                      anchors.rightMargin: Style.space(6)
                      readonly property var points: Model.curvePoints(root.snd, width, height, curveBox.range)
                      readonly property color stroke: root.snd && root.snd.enabled ? (svc.spectrumColor === "Mono" ? root.fg : Color.accent) : root.dim
                      onPointsChanged: requestPaint()
                      onStrokeChanged: requestPaint()
                      onPaint: {
                        var ctx = getContext("2d")
                        ctx.reset()
                        if (!points.length) return
                        ctx.lineWidth = Math.max(2, Style.space(2))
                        ctx.lineJoin = "round"
                        ctx.strokeStyle = stroke
                        ctx.beginPath()
                        ctx.moveTo(points[0].x, points[0].y)
                        for (var i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y)
                        ctx.stroke()
                      }
                    }
                    Text {
                      textFormat: Text.PlainText
                      text: "+" + curveBox.range + " dB"
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      anchors.right: parent.right
                      anchors.rightMargin: Style.space(6)
                      anchors.top: parent.top
                    }
                  }

                  // The preset of the default output, stepped with the arrows or a click on its name. It stands under
                  // the curve, because the curve is what it changes: the name reads as the caption of the picture.
                  CursorSurface {
                    visible: root.foldOpen("sound")
                    width: parent.width
                    height: presetRow.implicitHeight + Style.spacing.controlGap
                    hasCursor: root.cursorActive && root.section === "sound" && root.index === 0
                    foreground: root.fg
                    outline: true
                    HoverHandler { onHoveredChanged: if (hovered) root.hovered("sound", 0) }
                    Item {
                      id: presetRow
                      anchors.fill: parent
                      anchors.leftMargin: Style.space(6)
                      anchors.rightMargin: Style.space(6)
                      implicitHeight: presetName.implicitHeight + Style.space(4)
                      Text {
                        id: prevPreset
                        text: "\u{F0141}"
                        color: root.fg
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.title
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor; onClicked: svc.usePreset(Model.presetStep(root.snd, -1)) }
                      }
                      Text {
                        id: presetName
                        textFormat: Text.PlainText
                        text: root.snd ? String(root.snd.preset) : ""
                        color: root.fg
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        font.bold: true
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignHCenter
                        anchors.left: prevPreset.right
                        anchors.right: nextPreset.left
                        anchors.leftMargin: Style.space(8)
                        anchors.rightMargin: Style.space(8)
                        anchors.verticalCenter: parent.verticalCenter
                        opacity: root.snd && root.snd.enabled ? 1.0 : 0.5
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: svc.usePreset(Model.presetStep(root.snd, 1)) }
                      }
                      Text {
                        id: nextPreset
                        text: "\u{F0142}"
                        color: root.fg
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.title
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor; onClicked: svc.usePreset(Model.presetStep(root.snd, 1)) }
                      }
                    }
                  }

                    // What the equalizer can do beyond on, off and the preset: the preamp, the two sides, and a
              // preset of one's own. Each of these is one change, sent once.
              Column {
                visible: root.eqSettingsOpen && root.foldOpen("sound")
                width: parent.width
                spacing: Style.space(6)
                leftPadding: Style.space(6)
                rightPadding: Style.space(6)

                Item {
                  width: parent.width - Style.space(12)
                  implicitHeight: preampLabel.implicitHeight + Style.space(6)
                  Text {
                    id: preampLabel
                    textFormat: Text.PlainText
                    text: "Preamp " + (root.snd ? Number(root.snd.preamp).toFixed(1) : "0.0") + " dB"
                      + (root.snd && root.snd.preampMode === "auto" ? "  ·  AUTO" : "")
                    color: root.fg
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                  }
                  Text {
                    text: root.snd && root.snd.preampMode === "auto" ? "SET BY HAND" : "LET IT CHOOSE"
                    color: root.fg
                    opacity: 0.7
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 1.0
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    MouseArea {
                      anchors.fill: parent
                      anchors.margins: -Style.space(4)
                      cursorShape: Qt.PointingHandCursor
                      onClicked: {
                        if (!root.snd) return
                        if (root.snd.preampMode === "auto") svc.setPreamp(Number(root.snd.preamp).toFixed(1))
                        else svc.setPreampAuto()
                      }
                    }
                  }
                }
                PanelSlider {
                  visible: !!root.snd && root.snd.preampMode !== "auto"
                  bar: root.bar
                  width: parent.width - Style.space(12)
                  minimum: -20
                  maximum: 6
                  step: 0.5
                  value: root.snd ? Number(root.snd.preamp) : 0
                  onReleased: function (v) { svc.setPreamp(v.toFixed(1)) }
                  WheelGuard {}
                }

                // The bands themselves, under the curve they draw. Each is sent once, when the knob is let go:
                // a biquad clicks at every real change, and a moving control would click all the way. Touching
                // a band of a preset that came with Ballroom copies it to one of your own first, so nothing
                // that is built in is ever edited in place.
                Text {
                  visible: root.snd && root.snd.bands instanceof Array && root.snd.bands.length > 0
                  textFormat: Text.PlainText
                  text: "BANDS" + (Model.presetIsOwn(root.snd) ? "" : "  \u00b7  A CHANGE KEEPS A COPY OF ITS OWN")
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  font.letterSpacing: 1.0
                }
                Repeater {
                  model: root.snd && root.snd.bands instanceof Array ? root.snd.bands : []
                  Item {
                    required property var modelData
                    required property int index
                    width: parent.width - Style.space(12)
                    implicitHeight: bandSlider.implicitHeight + Style.space(4)
                    Text {
                      id: bandFreq
                      textFormat: Text.PlainText
                      text: Model.bandLabel(modelData)
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      width: Style.space(62)
                      anchors.left: parent.left
                      anchors.verticalCenter: parent.verticalCenter
                    }
                    PanelSlider {
                      id: bandSlider
                      bar: root.bar
                      anchors.left: bandFreq.right
                      anchors.right: bandGain.left
                      anchors.leftMargin: Style.space(6)
                      anchors.rightMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                      minimum: -12
                      maximum: 12
                      step: 0.5
                      value: Number(modelData.gain)
                      onReleased: function (v) { svc.setBand(index + 1, modelData, v) }
                      WheelGuard {}
                    }
                    Text {
                      id: bandGain
                      textFormat: Text.PlainText
                      text: (bandSlider.dragging ? bandSlider.liveValue : Number(modelData.gain)).toFixed(1) + " dB"
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      width: Style.space(50)
                      horizontalAlignment: Text.AlignRight
                      anchors.right: parent.right
                      anchors.verticalCenter: parent.verticalCenter
                    }
                  }
                }

                Text {
                  textFormat: Text.PlainText
                  text: "Balance " + Model.balanceText(root.snd ? root.snd.balance : 0)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
                PanelSlider {
                  bar: root.bar
                  width: parent.width - Style.space(12)
                  minimum: -1
                  maximum: 1
                  step: 0.02
                  value: root.snd ? Number(root.snd.balance) : 0
                  onReleased: function (v) { svc.setBalance(v) }
                  WheelGuard {}
                }

                Row {
                  width: parent.width - Style.space(12)
                  spacing: Style.space(16)
                  Text {
                    text: "MONO"
                    color: root.snd && root.snd.mono ? root.fg : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 1.0
                    MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor
                      onClicked: svc.setStereo("mono", !(root.snd && root.snd.mono)) }
                  }
                  Text {
                    text: "SWAP SIDES"
                    color: root.snd && root.snd.swap ? root.fg : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 1.0
                    MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor
                      onClicked: svc.setStereo("swap", !(root.snd && root.snd.swap)) }
                  }
                }

                // Where a turn of a band goes. Nobody can see this from the controls, and it is the first thing
                // anyone asks after making a preset of their own.
                Text {
                  textFormat: Text.PlainText
                  text: Model.presetIsOwn(root.snd)
                    ? "What you change goes into " + (root.snd ? root.snd.preset : "") + ", as you change it. The field below keeps a copy under another name."
                    : "The presets that come with Ballroom are never changed: the first turn of a band copies this one and works on the copy."
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.Wrap
                  width: parent.width - Style.space(12)
                  x: Style.space(6)
                }

                // A preset of one's own: keep what the curve is now under a name, or drop the one in use. Only
                // one's own can be dropped; the ones that come with Ballroom stay.
                TextField {
                  id: presetNameField
                  width: parent.width - Style.space(12)
                  foreground: root.fg
                  placeholderText: "Keep this curve under another name"
                  onActiveFocusChanged: root.noteEditing(activeFocus)
                  onAccepted: { if (svc.savePreset(text)) { text = ""; keys.forceActiveFocus() } }
                  Keys.onEscapePressed: { text = ""; keys.forceActiveFocus() }
                }
                Text {
                  visible: Model.presetIsOwn(root.snd)
                  text: "DROP THIS PRESET"
                  color: root.fg
                  opacity: 0.7
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  font.letterSpacing: 1.0
                  MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor
                    onClicked: if (root.snd) svc.removePreset(root.snd.preset) }
                }
                // AutoEQ publishes a file for most headphones; the terminal takes a path, and so does this.
                TextField {
                  id: importField
                  width: parent.width - Style.space(12)
                  foreground: root.fg
                  placeholderText: "Import an AutoEQ ParametricEQ.txt by its path"
                  onActiveFocusChanged: root.noteEditing(activeFocus)
                  onAccepted: { if (svc.importPreset(text)) { text = ""; keys.forceActiveFocus() } }
                  Keys.onEscapePressed: { text = ""; keys.forceActiveFocus() }
                }
              }

            // Balance, mono and swap live behind the equalizer's settings; here the panel only shows one that is set, so a side
                  // that was turned by accident does not stay unnoticed, and a click puts it back.
                  Item {
                    id: stereoNote
                    readonly property var parts: {
                      var out = []
                      if (root.snd && Number(root.snd.balance) !== 0) out.push("BALANCE " + Model.balanceText(root.snd.balance).toUpperCase())
                      if (root.snd && root.snd.mono) out.push("MONO")
                      if (root.snd && root.snd.swap) out.push("SWAPPED")
                      // Balance, mono and swap live in the equalizer's matrix; with it off they do nothing.
                      if (out.length && root.snd && !root.snd.enabled) out.push("(EQ OFF)")
                      return out
                    }
                    visible: parts.length > 0
                    width: parent.width
                    implicitHeight: visible ? stereoText.implicitHeight + Style.space(4) : 0
                    Text {
                      id: stereoText
                      textFormat: Text.PlainText
                      text: stereoNote.parts.join(" · ")
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      font.letterSpacing: 1.0
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                      textFormat: Text.PlainText
                      text: "RESET"
                      color: root.fg
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      font.letterSpacing: 1.0
                      anchors.right: parent.right
                      anchors.rightMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                      MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor; onClicked: svc.resetStereo() }
                    }
                  }

                  Text {
                    visible: !!root.snd && root.snd.foreign instanceof Array && root.snd.foreign.length > 0
                    textFormat: Text.PlainText
                    text: root.snd && root.snd.foreign ? "Another filter is in front of the output: " + root.snd.foreign.join(", ") : ""
                    color: Color.urgent
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.Wrap
                    width: parent.width
                    leftPadding: Style.space(6)
                    rightPadding: Style.space(6)
                  }
                }
    }
  }
  Component {
    id: playingSection
    Column {
      width: parent.width
      spacing: Style.space(14)
                // ---------- playing ----------
                // Everything that makes a sound, the stage among it. It used to have a section of its own above this
                // one, which meant it stood here twice: once with its transport and once as the stream it is. One
                // place, and the row that is ours carries the transport.
                PanelSeparator { visible: root.streams.length > 0; foreground: root.fg }

                Column {
                  width: parent.width
                  spacing: Style.space(8)
                  visible: root.streams.length > 0

                  Item {
                    width: parent.width
                    implicitHeight: playingHeader.implicitHeight
                    PanelSectionHeader { id: playingHeader; text: "PLAYING"; foreground: root.fg; fontFamily: root.fontFamily }
                    // A rule holds whether its application runs or not, so a rule for a program that is closed
                    // has no row among the streams. This shows them, so one can be seen and let go again.
                    Text {
                      visible: root.routeGhosts.length > 0
                      textFormat: Text.PlainText
                      text: root.showQuietRoutes ? "PINNED, NOT PLAYING \u00b7 HIDE"
                        : "PINNED, NOT PLAYING (" + root.routeGhosts.length + ")"
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      font.letterSpacing: 1.0
                      anchors.left: playingHeader.right
                      anchors.leftMargin: Style.space(12)
                      anchors.verticalCenter: parent.verticalCenter
                      MouseArea {
                        anchors.fill: parent
                        anchors.margins: -Style.space(4)
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.showQuietRoutes = !root.showQuietRoutes
                      }
                    }
                    Text {
                      visible: root.showStage && !!root.stg && root.stg.available
                      textFormat: Text.PlainText
                      text: svc.stageBusy ? "tuning in…" : Model.stageLine(root.stg).toUpperCase()
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      font.letterSpacing: 1.2
                      elide: Text.ElideLeft
                      horizontalAlignment: Text.AlignRight
                      anchors.left: playingHeader.right
                      anchors.leftMargin: Style.space(12)
                      anchors.right: parent.right
                      anchors.rightMargin: Style.space(6)
                      anchors.verticalCenter: parent.verticalCenter
                    }
                  }

                  Repeater {
                    model: root.streams
                    StreamRow {
                      required property var modelData
                      required property int index
                      width: column.width
                      stream: modelData
                      rowIndex: index
                    }
                  }

                  Repeater {
                    model: root.showQuietRoutes ? root.routeGhosts : []
                    RouteRow {
                      required property var modelData
                      width: column.width
                      rule: modelData
                    }
                  }
                }
    }
  }
  Component {
    id: librarySection
    Column {
      width: parent.width
      spacing: Style.space(14)
                // ---------- library ----------
                // The only part of the panel that browses instead of controlling, and the only one whose height jumps:
                // it folds open over several hundred pixels. At the foot it can do that without moving a control.
                PanelSeparator { visible: root.showStage; foreground: root.fg }

                Column {
                  width: parent.width
                  spacing: Style.space(6)
                  visible: root.showStage

                  Text {
                    visible: !!root.stg && !root.stg.available
                    textFormat: Text.PlainText
                    text: "Radio, SoundCloud and DI.FM play through mpv: omarchy pkg add mpv"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.Wrap
                    width: parent.width
                    leftPadding: Style.space(6)
                    rightPadding: Style.space(6)
                  }

                  // The library: the sources, the search, its results, the favorites of the chosen source, and for
                  // SoundCloud the likes of the account. Its line opens and closes it, like every other list.
                  FoldHeader {
                    visible: !!root.stg && root.stg.available
                    sectionId: "library"
                    title: "LIBRARY"
                    noteAlways: true
                    note: svc.stageError !== "" ? svc.stageError
                      : svc.searching ? "searching…" : svc.fetchingList ? "asking SoundCloud…" : svc.namingAccount ? "asking your browser…"
                      : Model.libraryLine(root.stg, root.stageSource)
                    noteColor: svc.stageError !== "" ? Color.urgent : root.dim
                  }
                  Column {
                    width: parent.width
                    spacing: Style.space(6)
                    visible: root.foldOpen("library") && !!root.stg && root.stg.available

                    // The search looks up the chosen source: the radio-browser directory, SoundCloud, the DI.FM channels.
                    Row {
                      spacing: Style.space(14)
                      leftPadding: Style.space(6)
                      Repeater {
                        model: Model.sourceTabs(root.stg)
                        Text {
                          required property var modelData
                          textFormat: Text.PlainText
                          text: Model.sourceTab(modelData)
                          color: root.stageSource === modelData ? root.fg : root.dim
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                          font.bold: true
                          font.letterSpacing: 1.0
                          font.underline: root.stageSource === modelData
                          // A tab without a search of its own (FAVORITES, DI.FM before its key) leaves the keys with
                          // the panel: focus in a hidden field would swallow the arrows.
                          MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor
                            onClicked: { root.stageSource = modelData; root.focusSearch() } }
                        }
                      }
                    }
                    // What a SoundCloud profile holds beside the search. One at a time, like the sources above,
                    // and not before there is a profile: the lists of nobody are three words that do nothing.
                    Row {
                      visible: root.stageSource === "soundcloud" && Model.sourceUsable(root.stg, root.stageSource, svc.soundcloudUser, svc.soundcloudCookies)
                      spacing: Style.space(14)
                      leftPadding: Style.space(6)
                      Repeater {
                        model: Model.SC_VIEWS
                        Text {
                          required property var modelData
                          textFormat: Text.PlainText
                          text: String(modelData).toUpperCase()
                          color: root.scView === modelData ? root.fg : root.dim
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                          font.letterSpacing: 1.0
                          font.underline: root.scView === modelData
                          MouseArea {
                            anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor
                            onClicked: { root.scView = modelData; root.focusSearch() }
                          }
                        }
                      }
                    }
                    TextField {
                      id: stageSearchField
                      onActiveFocusChanged: root.noteEditing(activeFocus)
                      onTextChanged: root.searchText = text
                      Component.onCompleted: if (root.restoreText !== "") text = root.restoreText
                      Connections {
                        target: root
                        function onFocusSearchRequested() {
                          if (stageSearchField.visible) stageSearchField.forceActiveFocus()
                          else keys.forceActiveFocus()
                        }
                        function onClearSearchRequested() { stageSearchField.text = "" }
                        // What came back with the held results was put into the panel before this field existed,
                        // so the field would stay empty while the panel searched for something.
                        function onRestoreTextChanged() { if (root.restoreText !== "") stageSearchField.text = root.restoreText }
                      }
                      visible: root.stageSource !== "fav" && Model.sourceUsable(root.stg, root.stageSource, svc.soundcloudUser, svc.soundcloudCookies)
                        && !(root.stageSource === "soundcloud" && root.scView !== "search")
                      width: parent.width
                      foreground: root.fg
                      placeholderText: Model.searchHint(root.stageSource)
                      // The focus stays here after a search, so the next words go into the field and not into the
                      // panel's cursor. Escape leaves it. Enter only skips the short wait; it is never needed.
                      onAccepted: root.searchNow(true)
                      Keys.onEscapePressed: keys.forceActiveFocus()
                    }
                    // SoundCloud wants one of two things, and the choice is the user's: a browser whose session
                    // Ballroom may read, and then the name comes with it, or no browser at all, and then the name
                    // is typed and only what that profile shows publicly appears. Before one is picked, Ballroom
                    // only asks whether a browser holds a SoundCloud cookie at all, never its value; the session
                    // itself is read once, after it has been picked.
                    Column {
                      id: scSetup
                      visible: root.stageSource === "soundcloud" && svc.soundcloudUser === ""
                      width: parent.width
                      spacing: Style.space(6)
                      // One question at a time. Picking a browser is an answer, so the browsers go away and only
                      // what follows from the answer stands there: first the asking, and if that browser says
                      // nothing, the name with one way back to the browsers.
                      readonly property string picked: Model.browserName(svc.soundcloudCookies)
                      readonly property bool anyBrowser: Model.browserOptions(svc.browsers, "").length > 0
                      readonly property bool asking: !svc.browsersAsked
                      readonly property bool waiting: picked !== "" && (svc.namingAccount || !root.accountAsked)
                      readonly property bool failed: picked !== "" && !svc.namingAccount && root.accountAsked
                      readonly property bool choosing: !asking && !waiting && !failed && !root.nameByHand && anyBrowser

                      Text {
                        textFormat: Text.PlainText
                        text: scSetup.asking ? "Looking for a browser…"
                          : scSetup.waiting ? "Asking " + scSetup.picked + " whose account it is…"
                          : scSetup.choosing ? "Pick the browser you are signed in to SoundCloud with. Ballroom reads that session to ask SoundCloud whose it is, and for nothing else."
                          : scSetup.failed ? "That browser did not say whose account it is: it may not be signed in, or its cookie store stayed locked. Type the name, or pick another browser."
                          : root.nameByHand || svc.browsersAnswered === false ? "Type the name of a profile: the part after soundcloud.com/ in its address. Only what that profile shows publicly appears here."
                          : svc.lockedStore ? "A browser is here, but its cookie store could not be opened. Type the name of a profile: the part after soundcloud.com/ in its address."
                          : "No browser here keeps a cookie store Ballroom can read. Type the name of a profile: the part after soundcloud.com/ in its address."
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.Wrap
                        width: parent.width
                        leftPadding: Style.space(6)
                        rightPadding: Style.space(6)
                      }

                      // One button per browser, under each other and bordered, because this is a choice to click
                      // and not a line to read. Button is the kit's own: it paints its own hover and press, so a
                      // row of words does not have to pretend to be a control.
                      Column {
                        width: parent.width - Style.space(12)
                        x: Style.space(6)
                        spacing: Style.space(4)

                        Repeater {
                          model: scSetup.choosing ? Model.browserOptions(svc.browsers, "") : []
                          Button {
                            required property var modelData
                            width: parent.width
                            leftAlign: true
                            bordered: true
                            text: Model.browserLabel(modelData)
                            selected: Model.browserTarget(modelData) === Model.browserName(svc.soundcloudCookies)
                            foreground: root.fg
                            accent: Color.accent
                            fontFamily: root.fontFamily
                            fontSize: Style.font.caption
                            tooltipText: "Read this browser's SoundCloud session"
                            onClicked: {
                              root.accountAsked = false
                              if (svc.setSoundcloudCookies(Model.browserTarget(modelData))) root.nameByHand = false
                            }
                          }
                        }

                        // The way past the browsers, and back again. Without a border: it is the second choice,
                        // not one of the browsers.
                        Button {
                          visible: !scSetup.asking && !scSetup.waiting && (scSetup.choosing || scSetup.failed || scSetup.anyBrowser)
                          width: parent.width
                          leftAlign: true
                          text: scSetup.choosing ? "Without a browser" : scSetup.failed ? "Pick another browser" : "Use a browser instead"
                          foreground: root.fg
                          accent: Color.accent
                          fontFamily: root.fontFamily
                          fontSize: Style.font.caption
                          onClicked: {
                            // Both ways leave no browser session in use: an empty setting would mean "take the
                            // one that is signed in", so going without a browser has to say "none".
                            if (svc.soundcloudCookies !== "none") svc.setSoundcloudCookies("-")
                            if (scSetup.choosing) { root.nameByHand = true; return }
                            root.nameByHand = false
                            root.accountAsked = false
                          }
                        }
                      }

                      TextField {
                        id: soundcloudNameField
                        onActiveFocusChanged: root.noteEditing(activeFocus)
                        visible: !scSetup.asking && !scSetup.choosing && !scSetup.waiting
                        width: parent.width
                        foreground: root.fg
                        placeholderText: "SoundCloud name"
                        onAccepted: { if (svc.setSoundcloudName(text)) { text = ""; keys.forceActiveFocus() } }
                        Keys.onEscapePressed: keys.forceActiveFocus()
                      }
                    }
                    // DI.FM without a key: ask for it here, hidden while typing; it goes to the command over stdin.
                    Column {
                      visible: root.stageSource === "di" && !!root.stg && !root.stg.diKey
                      width: parent.width
                      spacing: Style.space(4)
                      Text {
                        textFormat: Text.PlainText
                        text: "DI.FM and its sister stations play here with a premium listen key; your account page on di.fm shows it. Ballroom checks it with DI.FM, keeps it for your user only and never shows it."
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        wrapMode: Text.Wrap
                        width: parent.width
                        leftPadding: Style.space(6)
                        rightPadding: Style.space(6)
                      }
                      TextField {
                        id: diKeyField
                        onActiveFocusChanged: root.noteEditing(activeFocus)
                        width: parent.width
                        foreground: root.fg
                        password: true
                        placeholderText: "DI.FM listen key"
                        onAccepted: { if (svc.setDiKey(text)) { text = ""; keys.forceActiveFocus() } }
                        Keys.onEscapePressed: keys.forceActiveFocus()
                      }
                    }
                    Text {
                      visible: root.stageRows.length === 0 && Model.sourceUsable(root.stg, root.stageSource, svc.soundcloudUser, svc.soundcloudCookies)
                        && !(root.stageSource === "soundcloud" && svc.soundcloudUser === "")
                      textFormat: Text.PlainText
                      text: root.stageSource === "fav" ? "No favorites yet: the star on a result keeps one here"
                        : root.stageSource === "soundcloud" && root.scView !== "search"
                          ? (svc.fetchingList ? "Asking SoundCloud…" : "Nothing in your " + root.scView)
                        : root.rowFilter !== ""
                          ? (svc.searching ? "Asking " + Model.sourceTab(root.stageSource) + "…" : "Nothing found for «" + root.rowFilter + "»")
                          : "Nothing here yet: type above, and the star on a result keeps it under FAVORITES"
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      wrapMode: Text.Wrap
                      width: parent.width
                      leftPadding: Style.space(6)
                      rightPadding: Style.space(6)
                    }

                    // The results: their caption names the search and clears it; the box holds ten rows and scrolls
                    // inside itself; the button under it loads ten more.
                    Item {
                      visible: root.resultsInfo.held > 0
                      width: parent.width
                      implicitHeight: resultsCaption.implicitHeight + Style.space(8)
                      Text {
                        id: resultsCaption
                        textFormat: Text.PlainText
                        text: (root.resultsInfo.list === "favorites" ? "FAVORITES  "
                          : root.resultsInfo.list !== "" ? root.resultsInfo.list.toUpperCase() + " of " + root.resultsInfo.query + "  "
                          : root.resultsInfo.channels ? (root.resultsInfo.narrowed ? "CHANNELS matching «" + root.rowFilter + "»  " : "ALL CHANNELS  ")
                          : root.resultsInfo.narrowed ? "HELD, matching «" + root.rowFilter + "»  "
                          : "RESULTS for «" + root.resultsInfo.query + "»  ")
                          + root.resultsInfo.from + "-" + root.resultsInfo.to + " of " + root.resultsInfo.held
                          + (root.resultsInfo.list === "" && !root.resultsInfo.channels && !root.resultsInfo.narrowed && root.stg && root.stg.results && root.stg.results.complete === false ? "+" : "")
                        color: Qt.darker(root.fg, 1.4)
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        font.bold: true
                        font.letterSpacing: 1.0
                        elide: Text.ElideRight
                        anchors.left: parent.left
                        anchors.right: resultsClear.left
                        anchors.leftMargin: Style.space(6)
                        anchors.verticalCenter: parent.verticalCenter
                      }
                      Text {
                        id: resultsClear
                        visible: !root.resultsInfo.channels && root.resultsInfo.list === ""
                        text: Model.G_CLOSE
                        color: root.fg
                        opacity: 0.5
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.body
                        anchors.right: parent.right
                        anchors.rightMargin: Style.space(6)
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea { anchors.fill: parent; anchors.margins: -Style.space(4); cursorShape: Qt.PointingHandCursor; onClicked: { root.clearSearch(); svc.stageCtl(["stage", "clear"]) } }
                      }
                    }
                    // The rows stand still: a list that scrolls inside a panel that scrolls catches the wheel on
                    // its way down the panel. Ten at a time, and the row underneath turns the page.
                    Repeater {
                      model: root.resultRows
                      StageRow {
                        required property var modelData
                        required property int index
                        width: column.width
                        entry: modelData
                        rowIndex: index
                      }
                    }
                    Item {
                      visible: root.resultsInfo.canPrev || root.resultsInfo.canNext || root.resultsInfo.canFetchMore
                      width: parent.width
                      implicitHeight: pageText.implicitHeight + Style.space(12)
                      Text {
                        text: Model.G_CHEVRON_LEFT
                        color: root.fg
                        opacity: root.resultsInfo.canPrev ? 0.85 : 0.2
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.title
                        anchors.left: parent.left
                        anchors.leftMargin: Style.space(12)
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea {
                          anchors.fill: parent
                          anchors.margins: -Style.space(6)
                          enabled: root.resultsInfo.canPrev
                          cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                          onClicked: root.pageBack()
                        }
                      }
                      Text {
                        id: pageText
                        textFormat: Text.PlainText
                        text: svc.searching ? "asking the source…"
                          : "PAGE " + (root.resultsInfo.page + 1) + " OF " + root.resultsInfo.pages
                            + (root.resultsInfo.canFetchMore && !root.resultsInfo.canNext ? "  \u00b7  MORE TO FETCH" : "")
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        font.bold: true
                        font.letterSpacing: 1.0
                        anchors.centerIn: parent
                      }
                      Text {
                        text: Model.G_CHEVRON_RIGHT
                        color: root.fg
                        opacity: (root.resultsInfo.canNext || root.resultsInfo.canFetchMore) && !svc.searching ? 0.85 : 0.2
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.title
                        anchors.right: parent.right
                        anchors.rightMargin: Style.space(12)
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea {
                          anchors.fill: parent
                          anchors.margins: -Style.space(6)
                          enabled: (root.resultsInfo.canNext || root.resultsInfo.canFetchMore) && !svc.searching
                          cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                          onClicked: root.pageForward()
                        }
                      }
                    }
                    Repeater {
                      model: root.libraryRows
                      StageRow {
                        required property var modelData
                        required property int index
                        width: column.width
                        entry: modelData
                        rowIndex: root.resultRows.length + index
                      }
                    }
                  }
                  // The channels of DI.FM are fetched when the library opens on DI.FM and the list is not there yet.
                  readonly property bool wantsChannels: root.foldOpen("library") && root.opened && root.showStage && root.stageSource === "di" && !!root.stg && root.stg.available && !root.stg.channels
                  Timer { interval: 300; running: parent.wantsChannels; onTriggered: svc.stageChannels() }
                  // The chosen list is fetched when it is not the one that is held, and again when it is older than ten
                  // minutes. A click on its caption fetches it at once.
                  readonly property bool wantsList: root.foldOpen("library") && root.opened && root.showStage && root.stageSource === "soundcloud"
                    && root.scView !== "search" && svc.soundcloudUser !== "" && !!root.stg && root.stg.available
                    && (!root.stg.sclist || root.stg.sclist.what !== root.scView || String(root.stg.sclist.user) !== svc.soundcloudUser
                        || Date.now() - Number(root.stg.sclist.at) > 600000)
                  Timer { interval: 300; running: parent.wantsList; onTriggered: svc.stageList(root.scView) }
                  // Without a profile name, the browsers are looked for once; if one of them is signed in, the account
                  // name is read from that session. Both only while the library stands on SoundCloud.
                  readonly property bool wantsBrowsers: root.foldOpen("library") && root.opened && root.showStage && root.stageSource === "soundcloud"
                    && svc.soundcloudUser === "" && !svc.browsersAsked
                  Timer { interval: 300; running: parent.wantsBrowsers; onTriggered: svc.findBrowsers() }
                  // Only once a browser has been picked: before that, nothing opens a cookie store.
                  readonly property bool wantsAccount: root.foldOpen("library") && root.opened && root.showStage && root.stageSource === "soundcloud"
                    && svc.soundcloudUser === "" && Model.browserName(svc.soundcloudCookies) !== "" && !root.accountAsked
                  Timer { interval: 300; running: parent.wantsAccount; onTriggered: { root.accountAsked = true; svc.findAccount() } }
                }
    }
  }
  // The devices under a master level, set in from the left edge. Rows only while the section is open; the cursor
  // counts them from 1, because 0 is the level above them.
  component DeviceList: Column {
    id: dlist
    property string sectionName: "output"
    property var devices: []
    x: Style.space(12)
    width: parent.width - Style.space(12)
    spacing: Style.space(4)
    visible: root.foldOpen(sectionName) && devices.length > 0
    Repeater {
      model: root.foldOpen(dlist.sectionName) ? dlist.devices : []
      DeviceRow {
        required property var modelData
        required property int index
        width: dlist.width
        device: modelData
        rowIndex: index + 1
        sectionName: dlist.sectionName
      }
    }
  }

  // Which component builds which section. A name the plan does not know cannot get here: the plan drops what
  // this list has never heard of.
  function sectionComponent(id) {
    if (id === "output") return outputSection
    if (id === "input") return inputSection
    if (id === "sound") return soundSectionComponent
    if (id === "playing") return playingSection
    if (id === "library") return librarySection
    return null
  }
  // Applications that are pinned to a device but are not playing right now. A rule holds whether its program
  // runs or not, so without this there is no row anywhere to let one go again.
  readonly property var routeGhosts: Model.routeGhosts(info)
  property bool showQuietRoutes: false

  // The order of the sections: the stored line, unless one is being dragged, and then the order it has under the
  // finger. A new array every time, never the one it already holds changed in place, or nothing would move.
  readonly property string sectionsStored: String(svc.setting("sections", ""))
  property var orderNow: null
  // Held, not bound: a bound array would be a new array on every reading of the settings, and a Repeater over a
  // new array builds every section again. That is what took the focus out of a field being typed in whenever a
  // setting was written. It changes when the order or the switches really change, and then only.
  property var sectionPlan: Model.sectionPlan("")
  function syncSectionPlan() {
    var next = orderNow !== null ? orderNow : Model.sectionPlan(sectionsStored)
    if (Model.sectionSetting(next) !== Model.sectionSetting(sectionPlan)) sectionPlan = next
  }
  onSectionsStoredChanged: {
    if (orderNow !== null && sectionsStored === Model.sectionSetting(orderNow)) orderNow = null
    syncSectionPlan()
  }
  onOrderNowChanged: syncSectionPlan()
  Component.onCompleted: syncSectionPlan()

  // Dragging a section by its line. The panel scrolls, so the line has to hold on to the press
  // (preventStealing), or the view takes the drag away halfway through. Which section the finger is over is
  // asked of the column itself: the sections are loaded, and their heights are whatever they happen to be.
  // The order itself changes only when the finger lets go. A Repeater over a plain array builds every section
  // again whenever the array changes, and that would take away the very line that holds the mouse: the drag
  // would end at the first section it crossed. So the line it is over says where it will land, and the move
  // happens once, at the end.
  property string dragSection: ""
  property string dragOver: ""
  property real dragFrom: 0
  property bool dragMoved: false
  function dragStart(id, item, y) {
    dragSection = id
    dragOver = ""
    dragMoved = false
    dragFrom = item.mapToItem(panelBody, 0, y).y
  }
  function dragTo(id, item, y) {
    if (dragSection !== id) return
    var at = item.mapToItem(panelBody, 0, y).y
    if (!dragMoved && Math.abs(at - dragFrom) < Style.space(8)) return
    dragMoved = true
    var over = panelBody.childAt(panelBody.width / 2, at)
    dragOver = over && over.modelData ? String(over.modelData.id) : ""
  }
  function dragEnd(id) {
    if (!dragMoved) toggleFold(id)
    else if (dragOver !== "" && dragOver !== id) {
      var plan = Model.sectionDropped(sectionPlan, id, dragOver)
      if (Model.sectionSetting(plan) !== Model.sectionSetting(sectionPlan)) {
        orderNow = plan
        svc.applySetting("sections", Model.sectionSetting(plan))
      }
    }
    dragCancel()
  }
  function dragCancel() { dragSection = ""; dragOver = ""; dragMoved = false }

  // The line of a section, as a handle: a click folds it, a drag moves the section. One piece for all six, so
  // that the two gestures cannot drift apart. It is declared before everything else on its line, so a control
  // that sits on the same line still gets its own clicks.
  component FoldGrip: MouseArea {
    id: grip
    property string sectionId: ""
    anchors.fill: parent
    preventStealing: true
    cursorShape: root.dragSection === grip.sectionId && root.dragMoved ? Qt.ClosedHandCursor : Qt.PointingHandCursor
    onPressed: function (m) { root.dragStart(grip.sectionId, grip, m.y) }
    onPositionChanged: function (m) { root.dragTo(grip.sectionId, grip, m.y) }
    onReleased: root.dragEnd(grip.sectionId)
    onCanceled: root.dragCancel()
    // What is being moved, and where it will land. Behind the words on the line, because the grip stands before
    // them: the one being dragged is filled, the one it would take the place of is outlined.
    readonly property bool dragged: root.dragMoved && root.dragSection === grip.sectionId
    readonly property bool targeted: root.dragMoved && root.dragOver === grip.sectionId && root.dragSection !== grip.sectionId
    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: grip.dragged ? root.hoverFill : "transparent"
      border.width: grip.targeted ? 2 : 0
      border.color: Color.accent
    }
  }

  // The line of a section that folds: the whole line is the handle, and a chevron says which way it goes. The
  // same line for every one of them, so that folding is one thing and not three.
  component FoldHeader: Item {
    id: fhead
    property string sectionId: ""
    property string title: ""
    property string note: ""
    property int rows: 0
    property bool noteAlways: false
    property color noteColor: root.dim
    readonly property bool open: root.foldOpen(fhead.sectionId)
    width: parent.width
    implicitHeight: fheadLabel.implicitHeight + Style.space(8)
    FoldGrip { sectionId: fhead.sectionId }
    HoverHandler { onHoveredChanged: if (hovered) root.hovered(fhead.sectionId, -1) }
    Text {
      id: fheadLabel
      textFormat: Text.PlainText
      text: root.chevron(fhead.sectionId) + fhead.title
      color: Qt.darker(root.fg, 1.4)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: 1.0
      anchors.left: parent.left
      anchors.leftMargin: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
    }
    // What the section says beside its title. A list that is shut says how many rows it holds, so that folding
    // hides the rows and not the fact that they are there; the library says what it is doing, open or shut.
    Text {
      textFormat: Text.PlainText
      visible: fhead.noteAlways || !fhead.open
      text: fhead.note !== "" ? fhead.note : Model.foldNote(fhead.rows, "device")
      color: fhead.noteColor
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      elide: Text.ElideLeft
      horizontalAlignment: Text.AlignRight
      anchors.left: fheadLabel.right
      anchors.leftMargin: Style.space(12)
      anchors.right: parent.right
      anchors.rightMargin: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
    }
  }

  // A group of settings in one container: a title, then its rows with a line between them. One container per
  // group, not one per row: the eye finds a setting by its group first.
  component SettingGroup: BorderSurface {
    id: sgroup
    property var group: ({})
    implicitHeight: groupColumn.implicitHeight + Style.space(14)
    radius: Style.cornerRadius
    borderSpec: Border.controlSpec("normal", root.fg, Color.accent)
    color: "transparent"
    Column {
      id: groupColumn
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.topMargin: Style.space(8)
      spacing: Style.space(2)
      PanelSectionHeader {
        width: parent.width - Style.space(16)
        x: Style.space(8)
        text: sgroup.group && sgroup.group.title ? String(sgroup.group.title).toUpperCase() : ""
        foreground: root.fg
        fontFamily: root.fontFamily
      }
      Repeater {
        model: sgroup.group && sgroup.group.rows instanceof Array ? sgroup.group.rows : []
        Column {
          required property var modelData
          required property int index
          width: groupColumn.width
          spacing: Style.space(2)
          PanelSeparator { visible: index > 0; width: parent.width; foreground: root.fg; opacity: 0.5 }
          SettingRow { width: parent.width; def: modelData }
        }
      }

      // What a group carries beside its schema rows. SoundCloud and DI.FM are the same kind of thing, two
      // sources that want something set up, so they stand in one group; but the DI.FM key is a secret, not a
      // widget setting, and a schema row would write it in clear text into the shell's configuration. It lives
      // in a file of its own, goes to the command over stdin and is checked with DI.FM before it is kept, so
      // this only ever says whether there is one.
      Column {
        visible: sgroup.group && sgroup.group.extra === "dikey"
        width: groupColumn.width
        spacing: Style.space(6)
        PanelSeparator { width: parent.width; foreground: root.fg; opacity: 0.5 }
        Item {
          width: parent.width - Style.space(16)
          x: Style.space(8)
          implicitHeight: diLabel.implicitHeight
          Text {
            id: diLabel
            textFormat: Text.PlainText
            text: "DI.FM listen key"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }
          Text {
            textFormat: Text.PlainText
            text: !!root.stg && root.stg.diKey ? "SET" : "NOT SET"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1.0
            anchors.right: diForget.left
            anchors.rightMargin: Style.space(12)
            anchors.verticalCenter: parent.verticalCenter
          }
          Text {
            id: diForget
            visible: !!root.stg && root.stg.diKey
            text: "FORGET"
            color: root.fg
            opacity: 0.7
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1.0
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
              anchors.fill: parent
              anchors.margins: -Style.space(4)
              cursorShape: Qt.PointingHandCursor
              onClicked: svc.stageCtl(["di", "key", "-"])
            }
          }
        }
        TextField {
          id: diSettingsKey
          width: parent.width - Style.space(16)
          x: Style.space(8)
          foreground: root.fg
          password: true
          placeholderText: !!root.stg && root.stg.diKey ? "replace it" : "DI.FM listen key"
          onActiveFocusChanged: root.noteEditing(activeFocus)
          onAccepted: { if (svc.setDiKey(text)) { text = ""; keys.forceActiveFocus() } }
          Keys.onEscapePressed: { text = ""; keys.forceActiveFocus() }
        }
        Text {
          textFormat: Text.PlainText
          text: "DI.FM and its sister stations play with a premium listen key; your account page on di.fm shows it. Ballroom checks it with DI.FM, keeps it for your user only, never shows it again, and never writes it into the shell's settings."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
          width: parent.width - Style.space(16)
          x: Style.space(8)
        }
      }
    }
  }

  // One setting as a row: its label, the control its type asks for, and the first sentence of what the manifest
  // says about it. The value is read from the widget's settings and written through the command; the row holds
  // none of its own, so what shows is always what the shell has.
  component SettingRow: Rectangle {
    id: srow3
    property var def: ({})
    readonly property string key: def && def.key ? String(def.key) : ""
    readonly property string kind: def && def.type ? String(def.type) : "string"
    readonly property var current: svc.setting(srow3.key, def ? def.defaultValue : undefined)
    readonly property string currentText: String(current === undefined || current === null ? "" : current)
    // A setting whose choices only the machine knows: the browsers found here. The manifest says where to ask,
    // the page asks, and the value still goes through the command like every other one.
    readonly property bool fromBrowsers: !!def && def.optionsFrom === "browsers"
    readonly property bool fromSections: !!def && def.optionsFrom === "sections"
    readonly property bool hasCursor: root.cursorActive && root.section === "settings"
      && root.index >= 0 && String((root.settingOrder[root.index] || {}).key) === srow3.key
    readonly property bool hot: hasCursor || rowHover.hovered
    implicitHeight: srowBody.implicitHeight + Style.space(12)
    radius: Style.cornerRadius
    color: hot ? root.hoverFill : "transparent"
    Behavior on color { ColorAnimation { duration: 100 } }
    // The same rule as the fold: a new object, so that a change is a change. Nothing binds to this one today,
    // and the next thing that does should not have to find that out the hard way.
    Component.onCompleted: { var m = Object.assign({}, root.settingItems); m[srow3.key] = srow3; root.settingItems = m }
    // When the shell tears the panel down, the root may be gone before its rows are: then there is nothing to
    // unregister from.
    Component.onDestruction: { if (!root || !root.settingItems) return; var m = Object.assign({}, root.settingItems); if (m[srow3.key] === srow3) delete m[srow3.key]; root.settingItems = m }

    // Enter on the row: a switch flips, a choice opens, a number or a text takes the keys.
    function activate() {
      if (fromSections) return
      if (kind === "boolean") svc.applySetting(key, !(current === true))
      else if (kind === "enum" || fromBrowsers) choice.toggle()
      else if (kind === "integer") number.field.forceActiveFocus()
      else textEdit.forceActiveFocus()
    }

    HoverHandler { id: rowHover }
    // Stacked, not side by side: a choice or a number squeezed beside the words leaves a strip a few characters
    // wide for either. Only a switch is small enough to stay on the title line.
    Column {
      id: srowBody
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(8)
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(6)

      Item {
        width: parent.width
        implicitHeight: Math.max(srowLabel.implicitHeight, srowSwitch.implicitHeight)
        Text {
          id: srowLabel
          textFormat: Text.PlainText
          text: srow3.def && srow3.def.label ? String(srow3.def.label) : srow3.key
          color: root.fg
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
          anchors.left: parent.left
          anchors.right: srowSwitch.left
          anchors.rightMargin: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
        }
        ToggleSwitch {
          id: srowSwitch
          visible: srow3.kind === "boolean"
          checked: srow3.current === true
          foreground: root.fg
          accent: Color.accent
          hasCursor: srow3.hasCursor
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          onToggled: svc.applySetting(srow3.key, !(srow3.current === true))
        }
      }

      Dropdown {
        id: choice
        visible: (srow3.kind === "enum" || srow3.fromBrowsers) && !srow3.fromSections
        showLabel: false
        width: parent.width
        fontFamily: root.fontFamily
        foreground: root.fg
        accent: Color.accent
        options: srow3.fromBrowsers ? Model.browserOptions(svc.browsers, srow3.currentText)
          : (srow3.def && srow3.def.options instanceof Array ? srow3.def.options : [])
        value: srow3.fromBrowsers ? Model.browserValue(svc.browsers, srow3.currentText) : srow3.currentText
        hasCursor: srow3.hasCursor
        onChanged: function (v) {
          if (srow3.fromBrowsers) {
            var t = Model.browserTarget(v)
            if (t && v !== Model.browserValue(svc.browsers, srow3.currentText)) svc.setSoundcloudCookies(t)
            return
          }
          if (v !== srow3.currentText) svc.applySetting(srow3.key, v)
        }
        onPopupOpenChanged: root.noteEditing(popupOpen)
        // The shell's Dropdown leaves the popup at its default close policy, so a press on the trigger while

        // it is open both closes it (press outside the popup) and opens it again (the trigger's own click):

        // it flickers and stays open. This lies over the trigger while the popup is up, takes that press and

        // closes it once.

        MouseArea {

          anchors.fill: parent

          enabled: parent.popupOpen

          onClicked: parent.close()

        }

      }
      NumberField {
        id: number
        visible: srow3.kind === "integer"
        label: ""
        from: srow3.def && srow3.def.min !== undefined ? Number(srow3.def.min) : 0
        to: srow3.def && srow3.def.max !== undefined ? Number(srow3.def.max) : 9999
        stepSize: srow3.def && srow3.def.step !== undefined ? Number(srow3.def.step) : 1
        value: Number(srow3.current) || 0
        foreground: root.fg
        accent: Color.accent
        fontFamily: root.fontFamily
        hasCursor: srow3.hasCursor
        onModified: function (v) { if (v !== Number(srow3.current)) svc.applySetting(srow3.key, v) }
        Connections { target: number.field; function onActiveFocusChanged() { root.noteEditing(number.field.activeFocus) } }
      }
      // Text takes a field of its own, saved when the field is left or Enter is pressed. What comes back from
      // the shell replaces it, unless it is being typed in right now.
      TextField {
        id: textEdit
        visible: srow3.kind === "string" && !srow3.fromBrowsers && !srow3.fromSections
        width: parent.width
        foreground: root.fg
        placeholderText: srow3.def && srow3.def.placeholder ? String(srow3.def.placeholder) : ""
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        Component.onCompleted: text = srow3.currentText
        onActiveFocusChanged: {
          root.noteEditing(activeFocus)
          if (!activeFocus && text !== srow3.currentText) svc.applySetting(srow3.key, text)
        }
        onAccepted: keys.forceActiveFocus()
        Keys.onEscapePressed: { text = srow3.currentText; keys.forceActiveFocus() }
        Connections {
          target: svc
          function onSettingsChanged() { if (!textEdit.activeFocus) textEdit.text = srow3.currentText }
        }
      }

      // A setting that is a list of the panel's own parts: one row each, a switch to show or hide it and two
      // arrows to move it. It is written back as the one line the setting holds.
      Column {
        visible: srow3.fromSections
        width: parent.width
        spacing: Style.space(2)
        Repeater {
          model: srow3.fromSections ? root.sectionPlan : []
          Item {
            required property var modelData
            required property int index
            width: parent.width
            implicitHeight: Math.max(secName.implicitHeight, secSwitch.implicitHeight) + Style.space(8)
            Text {
              id: secName
              textFormat: Text.PlainText
              text: String(modelData.title)
              color: modelData.on ? root.fg : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              elide: Text.ElideRight
              anchors.left: parent.left
              anchors.right: secUp.left
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              id: secUp
              text: Model.G_CHEVRON_UP
              color: root.fg
              opacity: index > 0 ? 0.8 : 0.2
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              anchors.right: secDown.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              MouseArea {
                anchors.fill: parent; anchors.margins: -Style.space(5)
                enabled: index > 0
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: svc.applySetting(srow3.key, Model.sectionSetting(Model.sectionMoved(root.sectionPlan, modelData.id, -1)))
              }
            }
            Text {
              id: secDown
              text: Model.G_CHEVRON_DOWN
              color: root.fg
              opacity: index < root.sectionPlan.length - 1 ? 0.8 : 0.2
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              anchors.right: secSwitch.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              MouseArea {
                anchors.fill: parent; anchors.margins: -Style.space(5)
                enabled: index < root.sectionPlan.length - 1
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: svc.applySetting(srow3.key, Model.sectionSetting(Model.sectionMoved(root.sectionPlan, modelData.id, 1)))
              }
            }
            ToggleSwitch {
              id: secSwitch
              checked: modelData.on === true
              foreground: root.fg
              accent: Color.accent
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              onToggled: svc.applySetting(srow3.key, Model.sectionSetting(Model.sectionToggled(root.sectionPlan, modelData.id)))
            }
          }
        }
      }

      // Chosen by hand? Then say so, and let it be taken back. Letting Ballroom choose again is not a browser,
      // so it has no place in the list above.
      Text {
        visible: srow3.fromBrowsers && srow3.currentText !== ""
        text: "CHOSEN BY HAND \u00b7 LET BALLROOM CHOOSE"
        color: root.fg
        opacity: 0.7
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.0
        MouseArea {
          anchors.fill: parent
          anchors.margins: -Style.space(4)
          cursorShape: Qt.PointingHandCursor
          onClicked: svc.setSoundcloudCookies("-")
        }
      }

      Text {
        visible: text !== ""
        textFormat: Text.PlainText
        text: Model.settingHelp(srow3.def)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
        width: parent.width
      }
    }
  }

  // A rule whose application is not playing: its name, where it is pinned, and the way to let it go. No level
  // and no mute, because there is no stream to turn down.
  component RouteRow: Item {
    id: rrow
    required property var rule
    implicitHeight: rrowName.implicitHeight + Style.spacing.xl
    Row {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      spacing: Style.space(8)
      Text {
        id: rrowName
        textFormat: Text.PlainText
        text: rrow.rule ? String(rrow.rule.app) : ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
        width: parent.width - rrowTarget.width - rrowRelease.width - Style.space(16)
        anchors.verticalCenter: parent.verticalCenter
      }
      Text {
        id: rrowTarget
        textFormat: Text.PlainText
        text: rrow.rule ? Model.labelOf(root.info, rrow.rule.device) : ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
        width: Math.min(implicitWidth, Style.space(120))
        anchors.verticalCenter: parent.verticalCenter
      }
      Text {
        id: rrowRelease
        text: "RELEASE"
        color: root.fg
        opacity: 0.6
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        font.letterSpacing: 1.0
        anchors.verticalCenter: parent.verticalCenter
        MouseArea {
          anchors.fill: parent
          anchors.margins: -Style.space(4)
          cursorShape: Qt.PointingHandCursor
          onClicked: if (rrow.rule) svc.routeApp(rrow.rule.app, "follow")
        }
      }
    }
  }

  // A search result or a favorite: click plays it. The star on a result says whether it is kept and keeps or
  // drops it on a click (filled means kept); the cross on the FAVORITES tab removes the row.
  component StageRow: CursorSurface {
    id: srow2
    required property var entry
    required property int rowIndex
    readonly property bool captioned: !!entry && entry.first === true && entry.boxed !== true && entry.group !== ""
    // The FAVORITES tab: every source at once, so a row says which one it is instead of showing a glyph for it.
    readonly property bool onFav: root.stageSource === "fav"
    hasCursor: root.cursorActive && root.section === "library" && root.index === rowIndex
    foreground: root.fg
    fill: root.hoverFill
    currentFill: root.selectedFill
    implicitHeight: stageRowInner.implicitHeight + Style.spacing.xl + (captioned ? stageCaption.implicitHeight + Style.space(6) : 0)

    // The caption of a group above its first row.
    Text {
      id: stageCaption
      visible: srow2.captioned
      textFormat: Text.PlainText
      text: srow2.captioned ? String(srow2.entry.group) : ""
      color: Qt.darker(root.fg, 1.4)
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: 1.0
      anchors.left: parent.left
      anchors.leftMargin: Style.space(6)
      anchors.top: parent.top
      anchors.topMargin: Style.space(4)

    }

    MouseArea {
      id: srow2Mouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onContainsMouseChanged: if (containsMouse) root.hovered("library", srow2.rowIndex)
      onClicked: if (srow2.entry) svc.stageRun(srow2.entry.openable ? ["sc", "open", srow2.entry.play] : ["play", srow2.entry.play])
      // A row cuts a long name short, so resting on it says the whole name and whatever the second column lost.
      PanelToolTip {
        visible: srow2Mouse.containsMouse && (srow2Title.truncated || subText.truncated)
        text: !srow2.entry ? "" : String(srow2.entry.title) + (srow2.onFav || String(srow2.entry.subtitle || "") === "" ? "" : "\n" + String(srow2.entry.subtitle))
        fontFamily: root.fontFamily
        width: Math.min(implicitWidth, srow2.width)
      }
    }
    Row {
      id: stageRowInner
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Style.spacing.xl / 2
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      spacing: Style.space(8)
      // On a source tab every row is of that source, so the glyph tells the eye which kind of thing a row is
      // while the words beside it describe the entry. On FAVORITES the sources are mixed and it is the source
      // itself that has to be said, in words: there the glyph goes and the name gets the room it takes.
      Text {
        visible: !srow2.onFav
        text: Model.stageGlyph(srow2.entry ? srow2.entry.kind : "")
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        width: Style.space(22)
        horizontalAlignment: Text.AlignHCenter
        anchors.verticalCenter: parent.verticalCenter
        opacity: 0.8
      }
      Text {
        id: srow2Title
        textFormat: Text.PlainText
        text: srow2.entry ? srow2.entry.title : ""
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        elide: Text.ElideRight
        width: parent.width - (srow2.onFav ? 0 : Style.space(30)) - subText.width - rowAction.width - Style.space(16)
        anchors.verticalCenter: parent.verticalCenter
      }
      Text {
        id: subText
        textFormat: Text.PlainText
        // The source in full on FAVORITES, and never cut: it is two or three words and the name yields the rest.
        text: !srow2.entry ? "" : srow2.onFav ? Model.sourceName(srow2.entry.kind) : String(srow2.entry.subtitle)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
        width: srow2.onFav ? implicitWidth : Math.min(implicitWidth, Style.space(110))
        anchors.verticalCenter: parent.verticalCenter
      }
      Text {
        id: rowAction
        // A playlist has no star: a favorite is something that plays, and a playlist is something that opens. A
        // kept row keeps its cross whatever it is, or it could never be removed again.
        visible: !!srow2.entry && (!srow2.entry.openable || !srow2.entry.result)
        text: !srow2.entry ? "" : !srow2.entry.result ? Model.G_CLOSE : srow2.entry.favorite ? Model.G_STAR : Model.G_STAR_OFF
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        width: Style.space(22)
        horizontalAlignment: Text.AlignHCenter
        anchors.verticalCenter: parent.verticalCenter
        // A result that is kept wears its full star openly; the rest of the column stays quiet until the cursor
        // is on it, and the cross that removes a favorite is never the loudest thing in its row.
        opacity: srow2.hasCursor || (srow2.entry && srow2.entry.result && srow2.entry.favorite) ? 0.9 : 0.35
        MouseArea {
          anchors.fill: parent
          anchors.margins: -Style.space(4)
          cursorShape: Qt.PointingHandCursor
          onClicked: root.toggleFavorite(srow2.entry)
        }
      }
    }
  }


  // The shell's slider turns with the mouse wheel, so scrolling through the panel moved every slider the pointer
  // crossed, and a balance or a band that moves clicks. Sliders here take no wheel: the guard lies over the
  // slider, lets presses through to it, and gives the wheel to the panel's scrolling instead.
  function scrollPanel(delta) {
    var f = scroll.contentItem
    if (!f || f.contentHeight === undefined) return
    f.contentY = Math.max(0, Math.min(Math.max(0, f.contentHeight - f.height), f.contentY - delta))
  }
  component WheelGuard: MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.NoButton
    onWheel: function (wheel) { root.scrollPanel(wheel.angleDelta.y); wheel.accepted = true }
  }



  // Bars over a hairline. Silence is the hairline alone: nothing to draw, so nothing is drawn.
  component Spectrum: Item {
    id: spec
    property var bands: []
    property bool dimmed: false
    property string caption: ""
    readonly property int count: svc.spectrumBars * 2
    readonly property var levels: Model.barBands(bands, count)
    readonly property real barWidth: Math.max(1, (width - Style.space(12) - (count - 1) * Style.space(2)) / count)
    implicitHeight: Style.space(36)

    Rectangle {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.bottom: parent.bottom
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      height: 1
      color: Util.alpha(root.fg, 0.18)
    }

    Row {
      anchors.fill: parent
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      anchors.bottomMargin: 1
      spacing: Style.space(2)
      Repeater {
        model: spec.count
        Item {
          id: slot
          required property int index
          readonly property real level: spec.levels[index]
          width: spec.barWidth
          height: parent.height
          Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: parent.height * slot.level
            radius: 2
            color: root.bandColor(slot.index, spec.count, spec.dimmed)
            opacity: (spec.dimmed ? 0.3 : 0.5) + 0.5 * slot.level
            Behavior on height { NumberAnimation { duration: 60 } }
          }
        }
      }
    }

    Text {
      visible: spec.caption !== ""
      textFormat: Text.PlainText
      text: spec.caption
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: 1.2
      anchors.right: parent.right
      anchors.rightMargin: Style.space(6)
      anchors.top: parent.top
    }
  }

  // A device: click the row to make it the default, click the button at its end to mute it.
  // Visuals come from hasCursor and current, never from containsMouse, like the built-in panel.
  component DeviceRow: CursorSurface {
    id: row
    required property var device
    required property int rowIndex
    // sectionName is the master level the row stands under ("output", "input"), where the keyboard cursor finds
    // it; kind is what the row is.
    property string sectionName: "output"
    readonly property string kind: sectionName === "input" ? "input" : "output"
    readonly property bool muted: !!device && !!device.mute
    readonly property var bt: Model.btOf(root.info, device)
    // The gear at the end of the row folds out what belongs to this one device: what it is called, whether it
    // is shown, and for an output what kind it is and how loud it may become. Open at most one at a time, so
    // the list does not turn into a wall.
    readonly property bool settingsOpen: root.deviceOpen === (device ? String(device.name) : "?")

    // Inputs carry their level: the default one from the meter under the slider, every other one from a
    // meter of its own, open only while the panel is and the input is not muted.
    readonly property bool metered: kind === "input" && svc.inputMeters
    readonly property var liveNode: metered && device ? (root.inputNodes[device.name] || null) : null
    PwNodePeakMonitor {
      id: rowPeak
      node: row.liveNode
      enabled: row.metered && root.opened && !row.muted && !row.current && !!row.liveNode && !(row.liveNode.audio && row.liveNode.audio.muted)
    }
    readonly property real level: !metered ? 0
      : current ? (inputPeak.enabled ? inputPeak.peak : 0)
      : (rowPeak.enabled ? rowPeak.peak : 0)

    readonly property real shownLevel: levelSlider.dragging ? levelSlider.liveValue : root.levelOf(device, row.kind)
    hasCursor: root.cursorActive && root.section === sectionName && root.index === rowIndex
    current: !!device && device.isDefault
    foreground: root.fg
    fill: root.hoverFill
    currentFill: root.selectedFill
    implicitHeight: rowInner.implicitHeight + Style.spacing.xl + (settingsOpen ? deviceSettings.implicitHeight + Style.space(12) : 0)

    // Declared before the row's own controls, so the mute button and the gear lie above it and keep their
    // clicks. It covers the row alone: what folds out underneath has its own fields, and a click there must
    // reach them instead of making this device the default one.
    MouseArea {
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      height: rowInner.implicitHeight + Style.spacing.xl
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onContainsMouseChanged: if (containsMouse) root.hovered(row.sectionName, row.rowIndex)
      onClicked: {
        if (!row.device) return
        if (row.kind === "output") svc.makeDefaultOutput(row.device.name)
        else svc.makeDefaultInput(row.device.name)
      }
    }

    // What belongs to this one device, folded out under its row.
    Column {
      id: deviceSettings
      visible: row.settingsOpen
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: rowInner.bottom
      anchors.topMargin: Style.space(8)
      anchors.leftMargin: Style.space(28)
      anchors.rightMargin: Style.space(8)
      spacing: Style.space(6)

      TextField {
        id: aliasField
        width: parent.width
        foreground: root.fg
        placeholderText: row.device ? String(row.device.description || row.device.label) : ""
        onActiveFocusChanged: {
          root.noteEditing(activeFocus)
          if (!activeFocus && row.device && text !== (root.aliasOf(row.device))) svc.setDeviceAlias(row.device.name, text)
        }
        Component.onCompleted: text = row.device ? root.aliasOf(row.device) : ""
        onAccepted: keys.forceActiveFocus()
        Keys.onEscapePressed: { text = row.device ? root.aliasOf(row.device) : ""; keys.forceActiveFocus() }
      }

      Row {
        width: parent.width
        spacing: Style.space(10)
        visible: row.kind === "output"
        Dropdown {
          id: kindPick
          width: Math.round((parent.width - Style.space(10)) / 2)
          showLabel: false
          fontFamily: root.fontFamily
          foreground: root.fg
          accent: Color.accent
          options: ["Speakers", "Headphones"]
          value: row.device && row.device.kind === "headphones" ? "Headphones" : "Speakers"
          onChanged: function (v) {
            if (!row.device) return
            var want = v === "Headphones" ? "headphones" : "speakers"
            if (want !== String(row.device.kind)) svc.setDeviceKind(row.device.name, want)
          }
          onPopupOpenChanged: root.noteEditing(popupOpen)
          // The shell's Dropdown leaves the popup at its default close policy, so a press on the trigger while
          // it is open both closes it (press outside the popup) and opens it again (the trigger's own click):
          // it flickers and stays open. This lies over the trigger while the popup is up, takes that press and
          // closes it once.
          MouseArea {
            anchors.fill: parent
            enabled: parent.popupOpen
            onClicked: parent.close()
          }
        }
        Dropdown {
          id: capPick
          width: Math.round((parent.width - Style.space(10)) / 2)
          showLabel: false
          fontFamily: root.fontFamily
          foreground: root.fg
          accent: Color.accent
          options: root.capChoices
          value: Model.deviceCapText(row.device)
          onChanged: function (v) {
            if (!row.device || v === Model.deviceCapText(row.device)) return
            svc.setDeviceCap(row.device.name, v === "no limit" ? "none" : v.replace(" %", ""))
          }
          onPopupOpenChanged: root.noteEditing(popupOpen)
          // See the other lists: a press on the trigger while the popup is up must close it, not close and
          // open it again.
          MouseArea {
            anchors.fill: parent
            enabled: parent.popupOpen
            onClicked: parent.close()
          }
        }
      }

      // A Bluetooth device carries two more things: which mode it is in, and which codec it plays. Both make it
      // vanish for a moment while it changes over, so they sit here and not in the row itself.
      Row {
        width: parent.width
        spacing: Style.space(10)
        visible: !!row.bt
        Dropdown {
          id: btMode
          width: Math.round((parent.width - Style.space(10)) / 2)
          showLabel: false
          fontFamily: root.fontFamily
          foreground: root.fg
          accent: Color.accent
          options: ["Music", "Call"]
          value: row.bt && row.bt.mode === "call" ? "Call" : "Music"
          onChanged: function (v) {
            if (!row.bt) return
            var want = v === "Call" ? "call" : "music"
            if (want !== String(row.bt.mode)) svc.setBtMode(row.bt.address, want)
          }
          onPopupOpenChanged: root.noteEditing(popupOpen)
          MouseArea { anchors.fill: parent; enabled: parent.popupOpen; onClicked: parent.close() }
        }
        Dropdown {
          id: btCodec
          width: Math.round((parent.width - Style.space(10)) / 2)
          showLabel: false
          fontFamily: root.fontFamily
          foreground: root.fg
          accent: Color.accent
          options: row.bt && row.bt.codecs instanceof Array ? row.bt.codecs : []
          value: row.bt && row.bt.codec ? String(row.bt.codec) : ""
          onChanged: function (v) { if (row.bt && v && v !== String(row.bt.codec)) svc.setBtCodec(row.bt.address, v) }
          onPopupOpenChanged: root.noteEditing(popupOpen)
          MouseArea { anchors.fill: parent; enabled: parent.popupOpen; onClicked: parent.close() }
        }
      }
      Text {
        visible: !!row.bt && row.bt.mode === "call"
        textFormat: Text.PlainText
        text: "In call mode the microphone works and the music sounds like a phone call."
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
        width: parent.width
      }

      Item {
        width: parent.width
        implicitHeight: hideLabel.implicitHeight + Style.space(6)
        Text {
          id: hideLabel
          textFormat: Text.PlainText
          text: row.device && row.device.hidden ? "HIDDEN FROM THE PANEL" : "SHOWN IN THE PANEL"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          font.letterSpacing: 1.0
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          MouseArea {
            anchors.fill: parent
            anchors.margins: -Style.space(4)
            cursorShape: Qt.PointingHandCursor
            onClicked: if (row.device) svc.setDeviceHidden(row.device.name, !row.device.hidden)
          }
        }
        Text {
          text: "FORGET"
          color: root.fg
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
          font.letterSpacing: 1.0
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          MouseArea {
            anchors.fill: parent
            anchors.margins: -Style.space(4)
            cursorShape: Qt.PointingHandCursor
            onClicked: if (row.device) { svc.forgetDevice(row.device.name); root.deviceOpen = "" }
          }
        }
      }
    }

    Row {
      id: rowInner
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.topMargin: Style.spacing.xl / 2
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      spacing: Style.space(8)

      Text {
        textFormat: Text.PlainText
        text: row.kind === "output" ? Model.deviceGlyph(row.device) : Model.inputGlyph(row.device)
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        width: Style.space(22)
        horizontalAlignment: Text.AlignHCenter
        anchors.verticalCenter: parent.verticalCenter
        opacity: row.muted ? 0.6 : 1.0
      }
      Text {
        textFormat: Text.PlainText
        text: row.device ? String(row.device.label) : ""
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: row.current
        elide: Text.ElideRight
        // Every sibling in this row and the gap after each of them: the gear was added without a place in this
        // sum, so the mute button was pushed past the right edge of the row it belongs to.
        width: parent.width - Style.space(22) - trailing.width - levelBox.width - percentText.width
               - deviceGear.width - muteButton.width - Style.space(48)
        anchors.verticalCenter: parent.verticalCenter
        opacity: row.muted ? 0.6 : 1.0
      }
      Text {
        id: trailing
        textFormat: Text.PlainText
        text: row.device && row.device.codec ? String(row.device.codec).toUpperCase() : ""
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        anchors.verticalCenter: parent.verticalCenter
      }

      // The device's own level: drag it, or use the arrow keys on the row. An input shows above it what comes in.
      Item {
        id: levelBox
        width: Style.space(84)
        height: levelColumn.implicitHeight
        anchors.verticalCenter: parent.verticalCenter

        Column {
          id: levelColumn
          width: parent.width
          spacing: Style.space(2)

          Rectangle {
            id: meter
            visible: row.metered
            width: parent.width
            height: visible ? Math.max(Style.space(4), 3) : 0
            color: Util.alpha(root.fg, 0.18)
            opacity: row.muted ? 0.35 : 1.0
            Rectangle {
              height: parent.height
              width: parent.width * Math.max(0, Math.min(1, row.level))
              color: root.fg
              Behavior on width { NumberAnimation { duration: 70 } }
            }
          }
          PanelSlider {
            id: levelSlider
            bar: root.bar
            width: parent.width
            minimum: 0
            maximum: 1
            step: 0.05
            value: row.shownLevel
            opacity: row.muted ? 0.5 : 1.0
            onMoved: function (v) { if (row.current) root.setDeviceLevel(row.device, row.kind, v) }
            onReleased: function (v) { root.setDeviceLevel(row.device, row.kind, v) }
            onRightClicked: if (row.device) svc.toggleDeviceMute(row.device.name)
            WheelGuard {}
          }
        }

      }
      Text {
        id: percentText
        textFormat: Text.PlainText
        text: Math.round(row.shownLevel * 100) + "%"
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
        width: Style.space(34)
        horizontalAlignment: Text.AlignRight
        anchors.verticalCenter: parent.verticalCenter
        opacity: row.muted ? 0.5 : 1.0
      }
      Text {
        id: deviceGear
        text: "\u{F0493}"
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        width: Style.space(20)
        horizontalAlignment: Text.AlignHCenter
        anchors.verticalCenter: parent.verticalCenter
        opacity: row.settingsOpen ? 0.95 : (row.hasCursor ? 0.7 : 0.3)
        MouseArea {
          anchors.fill: parent
          anchors.margins: -Style.space(4)
          cursorShape: Qt.PointingHandCursor
          onClicked: if (row.device) root.deviceOpen = row.settingsOpen ? "" : String(row.device.name)
        }
      }
      Text {
        id: muteButton
        textFormat: Text.PlainText
        text: Model.muteGlyph(row.kind, row.muted)
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.title
        width: Style.space(22)
        horizontalAlignment: Text.AlignHCenter
        anchors.verticalCenter: parent.verticalCenter
        opacity: row.muted ? 1.0 : (row.hasCursor ? 0.8 : 0.35)
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: if (row.device) svc.toggleDeviceMute(row.device.name)
        }
      }
    }
  }

  // A stream row sends its volume when the slider is let go, and shows the value it is being dragged to meanwhile.
  component StreamRow: CursorSurface {
    id: srow
    required property var stream
    required property int rowIndex
    // Our own player. Its row says what plays and carries the transport; every other row is a volume and a mute.
    readonly property bool isStage: !!stream && stream.stage === true && !!root.stg
    readonly property bool loaded: isStage && root.stg.title !== ""
    readonly property bool hasQueue: isStage && ((root.stg.queue && Number(root.stg.queue.length) > 1) || Number(root.stg.playlist) > 1)
    readonly property bool seekable: loaded && !root.stg.live && Number(root.stg.duration) > 0

    hasCursor: root.cursorActive && root.section === "playing" && root.index === rowIndex
    foreground: root.fg
    fill: root.hoverFill
    currentFill: root.selectedFill
    implicitHeight: scol.implicitHeight + Style.spacing.xl

    Column {
      id: scol
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.leftMargin: Style.space(6)
      anchors.rightMargin: Style.space(6)
      spacing: Style.space(2)

      Row {
        width: parent.width
        spacing: Style.space(8)
        Text {
          id: smute
          textFormat: Text.PlainText
          text: srow.isStage ? (srow.loaded ? Model.stageGlyph(root.stg.kind) : Model.G_NOTE) : Model.streamGlyph(srow.stream)
          color: root.fg
          font.family: root.fontFamily
          font.pixelSize: Style.font.title
          width: Style.space(22)
          horizontalAlignment: Text.AlignHCenter
          anchors.verticalCenter: parent.verticalCenter
          opacity: srow.stream && srow.stream.mute ? 0.5 : 1.0
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: if (srow.stream) svc.toggleStreamMute(srow.stream.serial)
          }
        }
        // The buttons and the level share the first line with the name, so the second line has the row to
        // itself: a track title is long, and it was the thing being cut short.
        Column {
          width: parent.width - smute.width - Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(2)

          Row {
            width: parent.width
            spacing: Style.space(10)
            Marquee {
              text: !srow.isStage ? (srow.stream ? String(srow.stream.app) : "")
                : srow.loaded ? String(root.stg.title) : (root.stg.lastTitle !== "" ? String(root.stg.lastTitle) : "Nothing plays")
              color: root.fg
              opacity: srow.isStage && !srow.loaded ? 0.6 : 1.0
              bold: srow.isStage
              width: parent.width - spct.width - Style.space(10) - (transport.visible ? transport.width + Style.space(10) : 0)
              anchors.verticalCenter: parent.verticalCenter
            }
            Row {
              id: transport
              visible: srow.isStage
              spacing: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              StageButton { glyph: Model.G_PREV; dimmed: !srow.hasQueue; onClicked: svc.stageCtl(["prev"]) }
              StageButton { glyph: srow.isStage && Model.stagePlaying(root.stg) ? Model.G_PAUSE : Model.G_PLAY
                            onClicked: root.stageToggle() }
              StageButton { glyph: Model.G_NEXT; dimmed: !srow.hasQueue; onClicked: svc.stageCtl(["next"]) }
              StageButton { glyph: Model.G_STOP; dimmed: !srow.loaded; onClicked: svc.stageCtl(["stop"]) }
            }
            Text {
              id: spct
              textFormat: Text.PlainText
              text: Math.round((sslider.dragging ? sslider.liveValue : (srow.stream ? Number(srow.stream.volume) : 0)) * 100) + "%"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              width: Style.space(40)
              horizontalAlignment: Text.AlignRight
              anchors.verticalCenter: parent.verticalCenter
            }
          }

          // What the dropdown beside the level cannot say: that the rule's output is unplugged right now, or what
          // the stage is doing.
          Item {
            width: parent.width
            visible: subLine.text !== ""
            implicitHeight: visible ? subLine.implicitHeight : 0
            Text {
              id: subLine
              textFormat: Text.PlainText
              text: !srow.isStage ? Model.streamLine(root.info, srow.stream)
                : srow.loaded ? ((root.stg.ours === false ? "not started here · " : "") + String(root.stg.subtitle))
                : (root.stg.lastTitle !== "" ? "played last · play brings it back" : "open the library below")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
            }
          }
        }
      }

      // The level and where the application is sent, on one line: a row per stream is dear in height, and the
      // panel is long. DEFAULT means the default output of this setup; an output means a rule for this setup,
      // and docking or undocking switches to the rule of the setup one arrives in.
      Row {
        width: parent.width
        spacing: Style.space(8)
        PanelSlider {
          id: sslider
          bar: root.bar
          width: parent.width - sroute.width - Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          minimum: 0
          maximum: 1.5
          step: 0.05
          value: srow.stream ? Number(srow.stream.volume) : 0
          opacity: srow.stream && srow.stream.mute ? 0.5 : 1.0
          onReleased: function (v) { if (srow.stream) svc.setStreamVolume(srow.stream.serial, v) }
          onRightClicked: if (srow.stream) svc.toggleStreamMute(srow.stream.serial)
          WheelGuard {}
        }
        Dropdown {
          id: sroute
          width: Math.min(Style.space(150), Math.round(parent.width * 0.42))
          rowHeight: Style.spacing.controlHeight - Style.space(6)
          showLabel: false
          fontFamily: root.fontFamily
          foreground: root.fg
          accent: Color.accent
          anchors.verticalCenter: parent.verticalCenter
          options: Model.routeOptions(root.info, srow.stream)
          value: Model.routeValue(root.info, srow.stream)
          onChanged: function (v) {
            if (!srow.stream) return
            var t = Model.routeTarget(root.info, v)
            // DEFAULT chosen again still means something when the stream plays elsewhere without a rule here
            // (WirePlumber remembers where it was put): it is let go to the default output.
            var stray = t === "follow" && !srow.stream.routed && srow.stream.device !== root.info.defaultOutput
            if (v === Model.routeValue(root.info, srow.stream) && !stray) return
            if (t) svc.routeApp(srow.stream.app, t)
          }
          // The shell's Dropdown leaves the popup at its default close policy, so a press on the trigger while
          // it is open both closes it (press outside the popup) and opens it again (the trigger's own click):
          // it flickers and stays open. This lies over the trigger while the popup is up, takes that press and
          // closes it once.
          MouseArea {
            anchors.fill: parent
            enabled: parent.popupOpen
            onClicked: parent.close()
          }
        }
      }

      // The position in a track: a live stream has none. Sent once, when the knob is let go.
      Item {
        visible: srow.seekable
        width: parent.width
        implicitHeight: Style.spacing.controlHeight
        PanelSlider {
          id: seekSlider
          bar: root.bar
          anchors.left: parent.left
          anchors.right: seekText.left
          anchors.rightMargin: Style.space(10)
          anchors.verticalCenter: parent.verticalCenter
          minimum: 0
          maximum: 1
          step: 0.01
          value: srow.seekable ? Math.max(0, Math.min(1, Number(root.stg.position) / Number(root.stg.duration))) : 0
          onReleased: function (v) { if (srow.seekable) svc.stageCtl(["seek", String(Math.round(v * Number(root.stg.duration)))]) }
          WheelGuard {}
        }
        Text {
          id: seekText
          textFormat: Text.PlainText
          text: srow.seekable ? Model.mmss(seekSlider.dragging ? seekSlider.liveValue * Number(root.stg.duration) : root.stg.position) + " / " + Model.mmss(root.stg.duration) : ""
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
        }
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.NoButton
      propagateComposedEvents: true
      onContainsMouseChanged: if (containsMouse) root.hovered("playing", srow.rowIndex)
    }
  }
}
