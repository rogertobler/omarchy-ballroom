# Ballroom command, its code. One program for the bar widget (JSON) and the terminal. The file `ballroom` beside
# it is what runs: it finds this module and calls entry(); `python3 -I ballroom_cmd.py` runs it as well.
#
# Every verb follows these rules. They are not style: each one was measured on PipeWire 1.6.8 and
# WirePlumber 0.5.17, and DESIGN.md says how.
#
#   1. Measure, then report. After every write the graph is read back, and the answer comes from that reading.
#      wpctl exits 0 even for a profile that does not exist.
#   2. Volumes use the cubic scale that wpctl, pactl and Quickshell share: 50 % is 0.125 inside PipeWire.
#   3. No object id is kept beyond one reading. PipeWire hands ids out again after a restart or a hotplug.
#      Devices are named by node.name, streams by object.serial.
#   4. Every call to a tool has a time limit. A hung wpctl must not hang the bar.
#   5. WirePlumber is never restarted. With a Bluetooth headset a restart takes about twelve seconds.
#   6. A change that makes a device vanish never plays through another device: fallback outputs are muted
#      around it, and exactly those mutes are taken back afterwards.
#   7. No error text of a PipeWire tool is compared, only exit codes and structured output.
#   8. The microphone is never opened on the side. What Ballroom reads from inputs (the spectrum of the default
#      input, a level per listed input) runs only while the panel is open and stops with it; the spectrum
#      carries the name ballroom.spectrum.input, and none of it is listed as a listener.
#   9. A secret is never a process argument and never printed. The DI.FM listen key comes in over stdin or a
#      hidden prompt, goes to mpv over its socket, and is masked in every text and every title in the graph.
#
# Python 3.11 or newer, standard library only: Omarchy ships Python (yt-dlp is a Python program), so the plugin
# needs nothing that has to be installed by hand. The output is the same, byte for byte, as the bar widget reads
# it: JSON is written the way a JavaScript runtime writes it, because Model.js and Service.qml parse it.
import sys
import os

# The launcher names the interpreter by its path and runs it isolated (-I): a Python that a version manager or a
# virtual environment puts first on PATH is not used, and PYTHON* variables, the user's site directory and the
# directory of this file do not reach the module search path. The line below repeats the last point for a start
# as `python3 ballroom_cmd.py`. Only sys and os are loaded before it, and both are built in.
if sys.path and os.path.realpath(sys.path[0] or ".") == os.path.dirname(os.path.realpath(__file__)):
    del sys.path[0]

import json
import math
import re
import shutil
import stat as _stat
import copy as _copy
import signal
import fcntl
import secrets
import socket
import select
import subprocess
import time
import codecs
from fractions import Fraction
import posixpath
import functools
import unicodedata

VERSION = "0.2.0"


# ---------------------------------------------------------------- javascript values
# The widget parses what this program prints, and the files it keeps are read by earlier and later versions.
# These helpers give numbers, strings and JSON the shape a JavaScript runtime gives them: 1 and not 1.0,
# 1e-7 and not 1e-07, rounding half up, and a string length counted in UTF-16 units.
class _Undefined:
    __slots__ = ()

    def __repr__(self):
        return "undefined"

    def __bool__(self):
        return False


UNDEF = _Undefined()
NAN = float("nan")


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return is_num(v) and math.isfinite(v) and float(v).is_integer()


def nn(v, d):
    """The value, or d when it is null or undefined (the ?? operator)."""
    return d if v is None or v is UNDEF else v


def truthy(v):
    if v is None or v is UNDEF or v is False:
        return False
    if v is True:
        return True
    if is_num(v):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


def jsnum(x):
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if x != x:
        return "NaN"
    if x in (math.inf, -math.inf):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    r = repr(abs(x))
    if "e" in r:
        mant, exp = r.split("e")
        exp = int(exp)
    else:
        mant, exp = r, 0
    if "." in mant:
        ip, fp = mant.split(".")
    else:
        ip, fp = mant, ""
    if fp == "0":
        fp = ""
    digits = ip + fp
    n = len(ip) + exp
    stripped = digits.lstrip("0")
    n -= len(digits) - len(stripped)
    digits = stripped.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    e = n - 1
    es = ("+" if e >= 0 else "-") + str(abs(e))
    if k == 1:
        return sign + digits + "e" + es
    return sign + digits[0] + "." + digits[1:] + "e" + es


def S(v):
    """String(v)."""
    if isinstance(v, str):
        return v
    if v is None:
        return "null"
    if v is UNDEF:
        return "undefined"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if is_num(v):
        return jsnum(v)
    if isinstance(v, (list, tuple)):
        return ",".join("" if x is None or x is UNDEF else S(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


_JS_WS = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def js_trim(s):
    return s.strip(_JS_WS)


_NUM_RE = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def js_number(v):
    """Number(v). Undefined and null both arrive here as None and give NaN, as undefined does."""
    if v is None or v is UNDEF:
        return NAN
    if isinstance(v, bool):
        return 1 if v else 0
    if is_num(v):
        return v
    if isinstance(v, (list, tuple)):
        return js_number(S(v))
    if isinstance(v, dict):
        return NAN
    s = js_trim(str(v))
    if s == "":
        return 0
    if s in ("Infinity", "+Infinity"):
        return math.inf
    if s == "-Infinity":
        return -math.inf
    m = re.fullmatch(r"0[xX]([0-9a-fA-F]+)|0[oO]([0-7]+)|0[bB]([01]+)", s)
    if m:
        if m.group(1):
            return int(m.group(1), 16)
        if m.group(2):
            return int(m.group(2), 8)
        return int(m.group(3), 2)
    if not _NUM_RE.fullmatch(s):
        return NAN
    f = float(s)
    if f.is_integer() and abs(f) <= 2 ** 53 and not (f == 0 and s.lstrip().startswith("-")):
        return int(f)
    return f


def js_round(x):
    """Math.round: halves go up, towards positive infinity."""
    if not is_num(x) or x != x or x in (math.inf, -math.inf):
        return x
    r = math.floor(x)
    if x - r >= 0.5:
        r += 1
    return int(r)


def js_floor(x):
    if x != x or x in (math.inf, -math.inf):
        return x
    return int(math.floor(x))


def js_ceil(x):
    if x != x or x in (math.inf, -math.inf):
        return x
    return int(math.ceil(x))


def js_max(*xs):
    out = -math.inf
    for x in xs:
        if x != x:
            return NAN
        if x > out:
            out = x
    return out


def js_min(*xs):
    out = math.inf
    for x in xs:
        if x != x:
            return NAN
        if x < out:
            out = x
    return out


# Math.cbrt in the JavaScript runtime the widget was measured with returns the correctly rounded cube root, and the
# C library here does not (one unit in the last place, now and then). A volume is printed with all its digits, so the
# root is taken from the C library and then moved to the double whose cube is nearest, by exact arithmetic.
def cbrt(x):
    if x != x or x == 0 or x in (math.inf, -math.inf):
        return x + x if x != 0 else x
    if x < 0:
        return -cbrt(-x)
    y = math.cbrt(x)
    fx = Fraction(x)
    while True:
        lo, hi = math.nextafter(y, 0), math.nextafter(y, math.inf)
        if fx < ((Fraction(lo) + Fraction(y)) / 2) ** 3:
            y = lo
        elif fx > ((Fraction(y) + Fraction(hi)) / 2) ** 3:
            y = hi
        else:
            return y


def to_fixed(x, digits):
    """Number.prototype.toFixed: the exact binary value, rounded half up."""
    from decimal import Decimal, ROUND_HALF_UP
    if x != x:
        return "NaN"
    if x in (math.inf, -math.inf):
        return "Infinity" if x > 0 else "-Infinity"
    if abs(x) >= 1e21:
        return jsnum(x)
    if x == 0:
        x = 0
    q = Decimal(1).scaleb(-digits)
    neg = x < 0
    s = format(Decimal(abs(x)).quantize(q, rounding=ROUND_HALF_UP), "f")
    return ("-" if neg else "") + s


def u16len(s):
    return len(s) + sum(1 for ch in s if ord(ch) > 0xFFFF)


def cut(s, n):
    """s.slice(0, n), counted in UTF-16 units as JavaScript counts them."""
    if u16len(s) <= n:
        return s
    return s.encode("utf-16-le", "surrogatepass")[: 2 * n].decode("utf-16-le", "surrogatepass")


def pad_start(s, n, fill=" "):
    return fill * max(0, n - u16len(s)) + s


def pad_end(s, n, fill=" "):
    return s + fill * max(0, n - u16len(s))


def at(lst, i):
    """lst[i] as JavaScript reads it: undefined for anything but a whole index inside the list."""
    if not isinstance(lst, list) or not is_int(i) or i < 0 or i >= len(lst):
        return None
    return lst[int(i)]


def js_sorted(strings):
    """Array.prototype.sort without a comparator: by UTF-16 code units."""
    return sorted(strings, key=lambda s: s.encode("utf-16-be", "surrogatepass"))


# String.prototype.localeCompare as an ICU collator orders text (the root order: punctuation before digits before
# letters, letters without regard to case first, lower case before upper case at the last level).
_COLLATE_ASCII = " _-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$0123456789aAbBcCdDeEfFgGhHiIjJkKlLmMnNoOpPqQrRsStTuUvVwWxXyYzZ"


def _collation_key(s):
    prim, sec, ter = [], [], []
    for ch in s:
        base, accent = ch, 0
        if ord(ch) > 127:
            d = unicodedata.normalize("NFD", ch)
            if d and ord(d[0]) < 128 and d[0].isalpha():
                base, accent = d[0], sum(ord(c) for c in d[1:])
        if ord(base) < 128 and base in _COLLATE_ASCII:
            i = _COLLATE_ASCII.index(base.lower() if base.isalpha() else base)
            prim.append(i)
            ter.append(1 if base.isupper() else 0)
        elif ord(base) < 128:
            prim.append(-1)
            ter.append(0)
        else:
            # Not ASCII and no ASCII letter underneath: after the punctuation, before the digits.
            prim.append(_COLLATE_ASCII.index("$") + ord(base) / 0x110000)
            ter.append(0)
        sec.append(accent)
    return (prim, sec, ter, s)


def locale_compare(a, b):
    ka, kb = _collation_key(a), _collation_key(b)
    return -1 if ka < kb else 1 if ka > kb else 0


def gp(obj, *keys):
    """obj?.a?.b: None where the path ends."""
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        elif isinstance(obj, list) and isinstance(k, int):
            obj = obj[k] if 0 <= k < len(obj) else None
        else:
            return None
        if obj is None:
            return None
    return obj


def strict_eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if is_num(a) and is_num(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if a is None or b is None:
        return a is b
    return a is b


def _bad_constant(name):
    raise ValueError(f"not JSON: {name}")


def _parse_int(s):
    i = int(s)
    return i if -(2 ** 53) <= i <= 2 ** 53 else float(s)


def jparse(text):
    """JSON.parse. NaN and Infinity are not JSON, and a number past 2^53 is a double, as in JavaScript."""
    return json.loads(text, parse_constant=_bad_constant, parse_int=_parse_int)


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _jstr(s):
    out = json.dumps(s, ensure_ascii=False)
    return _LONE_SURROGATE.sub(lambda m: "\\u%04x" % ord(m.group(0)), out)


def jdump(v, indent=None, _level=0):
    """JSON.stringify(v) or JSON.stringify(v, null, indent). Keys that hold undefined are left out."""
    if v is None or v is UNDEF:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return jsnum(v) if math.isfinite(v) else "null"
    if isinstance(v, str):
        return _jstr(v)
    nl = "\n" + " " * (indent * (_level + 1)) if indent else ""
    end = "\n" + " " * (indent * _level) if indent else ""
    if isinstance(v, (list, tuple)):
        if not v:
            return "[]"
        return "[" + nl + ("," + nl).join(jdump(x, indent, _level + 1) for x in v) + end + "]"
    if isinstance(v, dict):
        items = [(k, x) for k, x in v.items() if x is not UNDEF]
        if not items:
            return "{}"
        sep = ": " if indent else ":"
        return "{" + nl + ("," + nl).join(_jstr(str(k)) + sep + jdump(x, indent, _level + 1) for k, x in items) + end + "}"
    return "null"


def _printable(s):
    return _LONE_SURROGATE.sub("\ufffd", s)


class _StdoutGone(Exception):
    """The reader of stdout went away (`ballroom di channels | head`): the end of the conversation, not a fault."""


# A stream nobody can write to (a reader that went away, a closed descriptor, a full disk) is the end of that
# conversation, not a fault: as with console.log, the verb carries on, its exit code stands, and nothing about the
# stream is said anywhere. The stream is pointed at /dev/null from then on, so that neither a later write nor the
# flush at exit tries again.
_DEAD_STREAM_ERRORS = (OSError, ValueError, AttributeError)


def _bury(name):
    fd = 1 if name == "stdout" else 2
    try:
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, fd)
        os.close(null)
    except OSError:
        pass
    try:
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    except OSError:
        pass


def _say(name, text):
    stream = getattr(sys, name)
    try:
        stream.write(_printable(text) + "\n")
        stream.flush()
    except _DEAD_STREAM_ERRORS:
        _bury(name)


def say_out(text):
    _say("stdout", text)


def say_err(text):
    _say("stderr", text)


def pjoin(*parts):
    """path.join: the parts joined with a slash and normalized."""
    s = "/".join(p for p in parts if p)
    if not s:
        return "."
    n = posixpath.normpath(s)
    if n.startswith("//"):
        n = "/" + n.lstrip("/")
    if s.endswith("/") and n != "/":
        n += "/"
    return n


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        return f.read()


def _write_fd(fd, text):
    data = text.encode("utf-8", "surrogatepass") if isinstance(text, str) else text
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def write_new(path, text, mode=0o600):
    """A file that must not be there yet: created fresh, never through a link, never over anything."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    try:
        _write_fd(fd, text)
        os.fchmod(fd, mode)
    finally:
        os.close(fd)


def write_atomic(path, text, mode=0o600, before=None):
    """A file written whole and then put in place: a temporary file beside it with a name nobody can guess,
    created fresh (never through a link, never over a file that is there), renamed over the old one. A reader sees
    the old file or the new one, never half of it, and a link planted under any name is never written through.
    before, when given, runs right before the rename and may refuse it by raising."""
    temp = f"{path}.tmp.{secrets.token_hex(8)}"
    try:
        write_new(temp, text, mode)
        if before is not None:
            before()
        os.rename(temp, path)
    finally:
        try:
            os.remove(temp)
        except FileNotFoundError:
            pass


def rm_force(path):
    """rmSync with force: a file that is not there is fine, anything else is an error."""
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def now_ms():
    return int(time.time() * 1000)


def sleep_ms(ms):
    time.sleep(ms / 1000)


def pid_gone(pid):
    """process.kill(pid, 0) failed with ESRCH."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except (OSError, OverflowError, ValueError):
        return False
    return False


def wyhash(data, seed=0):
    """Bun.hash: wyhash as the Zig standard library computes it. Ids and the address hash of the stage are kept
    in files and read by the panel, so the hash stays the one the earlier version wrote."""
    m64 = (1 << 64) - 1
    sec = (0xa0761d6478bd642f, 0xe7037ed1a0b428db, 0x8ebc6af09c88c6e3, 0x589965cc75374cc3)

    def mum(a, b):
        x = a * b
        return x & m64, (x >> 64) & m64

    def mix(a, b):
        a, b = mum(a, b)
        return a ^ b

    def rd(b, i, n):
        return int.from_bytes(b[i:i + n], "little")

    s0 = seed ^ mix(seed ^ sec[0], sec[1])
    st = [s0, s0, s0]
    n = len(data)
    if n <= 16:
        if n >= 4:
            end = n - 4
            q = (n >> 3) << 2
            a = (rd(data, 0, 4) << 32) | rd(data, q, 4)
            b = (rd(data, end, 4) << 32) | rd(data, end - q, 4)
        elif n > 0:
            a = (data[0] << 16) | (data[n >> 1] << 8) | data[n - 1]
            b = 0
        else:
            a = b = 0
    else:
        i = 0
        if n >= 48:
            while i + 48 < n:
                for k in range(3):
                    st[k] = mix(rd(data, i + 16 * k, 8) ^ sec[k + 1], rd(data, i + 16 * k + 8, 8) ^ st[k])
                i += 48
            st[0] ^= st[1] ^ st[2]
        rest = data[i:]
        j = 0
        while j + 16 < len(rest):
            st[0] = mix(rd(rest, j, 8) ^ sec[1], rd(rest, j + 8, 8) ^ st[0])
            j += 16
        a = rd(data, n - 16, 8)
        b = rd(data, n - 8, 8)
    a ^= sec[1]
    b ^= st[0]
    a, b = mum(a, b)
    return mix(a ^ sec[0] ^ n, b ^ sec[1])


def bun_hash(text):
    return str(wyhash(text.encode("utf-8", "surrogatepass")))


# ---------------------------------------------------------------- places
# The bench sets BALLROOM_BENCH=1 and may then hand in a recorded graph, fake servers and a short time limit.
# Outside the bench none of those switches exists: a variable exported in a session must not change what the
# widget reads or where a key goes. The tools come from a fixed path for the same reason: ~/.local/bin is
# first on PATH here, and a file placed there must not replace wpctl or systemctl for every panel call.
ENV = os.environ
BENCH = ENV.get("BALLROOM_BENCH") == "1"
if not BENCH:
    ENV["PATH"] = "/usr/bin:/usr/local/bin:/usr/share/omarchy/bin"
HOME = nn(ENV.get("HOME"), "/tmp")
CONFIG = pjoin(nn(ENV.get("XDG_CONFIG_HOME"), pjoin(HOME, ".config")), "ballroom")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
# The runtime directory is the session's own, on tmpfs and 0700. There is no fallback to /tmp: another local
# user could plant that directory first and fill it with links.
if not ENV.get("XDG_RUNTIME_DIR"):
    say_err("ballroom: XDG_RUNTIME_DIR is not set; run it inside your session")
    sys.exit(1)
RUNTIME = pjoin(ENV["XDG_RUNTIME_DIR"], "ballroom")
TIMEOUT_MS = js_number((ENV.get("BALLROOM_TIMEOUT_MS") if BENCH else None) or 3000)


# ---------------------------------------------------------------- failures
# Exit codes are part of the interface: the panel and scripts branch on them.
class EXIT:
    ok = 0
    failed = 1
    usage = 2
    notFound = 3
    timeout = 4


class Fail(Exception):
    def __init__(self, message, code=EXIT.failed):
        super().__init__(message)
        self.message = message
        self.code = code


def fail_text(e, otherwise):
    return e.message if isinstance(e, Fail) else otherwise


def _mkdirs(path, mode):
    """mkdirSync with recursive: every directory it creates gets the mode, not only the last one."""
    if os.path.isdir(path):
        return
    parent = os.path.dirname(path.rstrip("/"))
    if parent and parent != path and not os.path.exists(parent):
        _mkdirs(parent, mode)
    try:
        os.mkdir(path, mode)
    except FileExistsError:
        if not os.path.isdir(path):
            raise


# Ballroom's own directories are created 0700 and checked every time: never a link, never another user's,
# never open to others. A directory that fails this is refused, not used.
def ensureDir(d):
    if not os.path.exists(d):
        _mkdirs(d, 0o700)
    st = os.lstat(d)
    if _stat.S_ISLNK(st.st_mode) or not _stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise Fail(f"{d} is not a directory of this user; refusing to use it")
    if (st.st_mode & 0o077) != 0:
        # The runtime directory is shared ground and is refused when open; a directory in the home is Ballroom's own
        # and is closed instead.
        if d == RUNTIME:
            raise Fail(f"{d} is open to other users; refusing to use it")
        os.chmod(d, 0o700)
    if d == RUNTIME:
        sweepJars()
    if d in (RUNTIME, CONFIG) or d == _cache_dir():
        sweepTemps(d, r".+\.tmp\.[0-9a-f]{16}")


def _cache_dir():
    return pjoin(nn(ENV.get("XDG_CACHE_HOME"), pjoin(HOME, ".cache")), "ballroom")


def isBallroomProcess(pid):
    """A process of this user that runs a ballroom command, as its command line says. Unreadable counts as no."""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            argv = f.read(4096).split(b"\0")
    except (OSError, ValueError):
        return False
    return any(os.path.basename(a) == b"ballroom" for a in argv[:3])


# A cookie jar that whoami exported holds the whole browser jar in clear text. Its owner removes it at once, and
# a signal removes it too; one left by SIGKILL is removed by the next ballroom that touches the runtime
# directory, whatever it is there for. A jar is left alone while its process lives and is a ballroom: that one is
# bounded by its own deadlines (yt-dlp 30 s, the request 15 s) and removes the jar itself. A jar whose process is
# gone goes at once; one whose number now belongs to some other program goes once it is older than a minute.
# Only files of this user that carry the name. One listing of a small directory, once per run.
_jars_swept = False


def sweepJars():
    global _jars_swept
    if _jars_swept:
        return
    _jars_swept = True
    try:
        names = os.listdir(RUNTIME)
    except OSError:
        return
    for f in names:
        if not re.fullmatch(r"sc-jar\.[0-9]+", f):
            continue
        path = pjoin(RUNTIME, f)
        try:
            st = os.lstat(path)
            if st.st_uid != os.getuid() or not _stat.S_ISREG(st.st_mode):
                continue
            pid = int(f[7:])
            if pid_gone(pid) or (not isBallroomProcess(pid) and time.time() - st.st_mtime > 60):
                rm_force(path)
        except (OSError, ValueError):
            pass  # gone meanwhile, or not ours to judge


# A temporary file of write_atomic that a killed writer left behind: the name it gives (NAME.tmp. and sixteen hex
# digits), a regular file of this user, older than ten minutes (a writer takes milliseconds). Swept in Ballroom's
# own directories, once per directory and run; in ~/.config/systemd/user only under the names of our two units.
_temps_swept = set()


def sweepTemps(d, pattern):
    if d in _temps_swept:
        return
    _temps_swept.add(d)
    try:
        names = os.listdir(d)
    except OSError:
        return
    for f in names:
        if not re.fullmatch(pattern, f):
            continue
        path = pjoin(d, f)
        try:
            st = os.lstat(path)
            if st.st_uid == os.getuid() and _stat.S_ISREG(st.st_mode) and time.time() - st.st_mtime > 600:
                rm_force(path)
        except OSError:
            pass  # gone meanwhile


# A runtime file is written whole: a reader that comes every second (the widget) must never see half of it.
def writeRuntime(name, text):
    ensureDir(RUNTIME)
    write_atomic(pjoin(RUNTIME, name), text, 0o600)


# One writer at a time. The widget runs apply on every change in the graph, an action beside it, and the
# terminal on top: two of them changing a settings file or restarting the equalizer at once would lose one change
# or restart twice. The lock is flock on a file in the runtime directory that stays there. The kernel lets one
# holder in and drops the lock when the holder ends, however it ends, so there is no stale lock to judge and none
# to take over. The file names the holder's pid for whoever looks. Reading verbs never take it.
_lock_depth = 0
_lock_fd = None


def lockAcquire():
    global _lock_depth, _lock_fd
    _lock_depth += 1
    if _lock_depth > 1:
        return
    fd = None
    try:
        ensureDir(RUNTIME)
        fd = os.open(pjoin(RUNTIME, "lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        until = now_ms() + 5000
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                pass
            if now_ms() > until:
                raise Fail("another ballroom is busy changing settings; try again", EXIT.failed)
            sleep_ms(20)
        os.ftruncate(fd, 0)
        os.pwrite(fd, str(os.getpid()).encode(), 0)
        _lock_fd, fd = fd, None
    except BaseException:
        _lock_depth -= 1
        raise
    finally:
        if fd is not None:
            os.close(fd)


def lockRelease():
    global _lock_depth, _lock_fd
    _lock_depth -= 1
    if _lock_depth > 0:
        return
    fd, _lock_fd = _lock_fd, None
    if fd is not None:
        os.close(fd)


def withLock(f):
    lockAcquire()
    try:
        return f()
    finally:
        lockRelease()


# ---------------------------------------------------------------- running tools
class RunResult:
    __slots__ = ("rc", "out", "err", "timedOut", "overflow")

    def __init__(self, rc, out, err, timedOut, overflow=False):
        self.rc, self.out, self.err, self.timedOut, self.overflow = rc, out, err, timedOut, overflow


# Every tool runs in a process group of its own, so that a timeout, an overflow, an exception or a signal ends
# everything it started, not just the first process: a child that forked keeps the pipes and would run on. The
# groups that are alive are kept here for the signal handlers.
_groups = set()


def killGroups():
    for g in list(_groups):
        try:
            os.killpg(g, signal.SIGKILL)
        except OSError:
            pass  # already gone


# How much of a tool's answer is kept. pw-dump of a full graph is a few MiB and yt-dlp's list of 200 entries less;
# a tool that sends more than this is not answering, it is flooding. It is killed, and its answer counts as none:
# a cut answer is a different answer.
OUT_CAP = 32 * 1024 * 1024
ERR_CAP = 1024 * 1024


def run(cmd, timeout=None):
    """A tool with a time limit. Past the limit it is killed (SIGKILL), and the answer does not wait for anything
    it started and left holding the pipes."""
    if timeout is None:
        timeout = TIMEOUT_MS
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except (OSError, ValueError):
        # The tool is not installed. That is a state to report, not a crash.
        return RunResult(127, "", "", False)
    limit = timeout / 1000 if is_num(timeout) and timeout == timeout else 0
    deadline = time.monotonic() + limit
    bufs = {p.stdout.fileno(): bytearray(), p.stderr.fileno(): bytearray()}
    caps = {p.stdout.fileno(): OUT_CAP, p.stderr.fileno(): ERR_CAP}
    names = {p.stdout.fileno(): "stdout", p.stderr.fileno(): "stderr"}
    open_fds = set(bufs)
    timed_out = overflow = False
    _groups.add(p.pid)
    try:
        while open_fds and not overflow:
            left = deadline - time.monotonic()
            if left <= 0:
                timed_out = True
                break
            ready, _, _ = select.select(list(open_fds), [], [], left)
            for fd in ready:
                chunk = os.read(fd, 65536)
                if chunk:
                    bufs[fd] += chunk
                    if len(bufs[fd]) > caps[fd]:
                        overflow = names[fd]
                else:
                    open_fds.discard(fd)
        if not timed_out and not overflow:
            left = deadline - time.monotonic()
            try:
                p.wait(timeout=max(0, left))
            except subprocess.TimeoutExpired:
                timed_out = True
    finally:
        # Past the limit, past the cap, or on the way out with an exception: the whole group goes. A tool that
        # ended by itself is reaped, and whatever it left running still holds nothing of ours past this point.
        if timed_out or overflow or p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
        _groups.discard(p.pid)
        p.stdout.close()
        p.stderr.close()
    out = bytes(bufs[next(iter(bufs))]).decode("utf-8", "replace")
    err = bytes(list(bufs.values())[1]).decode("utf-8", "replace")
    rc = p.returncode
    if rc is None:
        rc = 1
    elif rc < 0:
        rc = 128 - rc
    if overflow:
        return RunResult(rc if rc != 0 else 1, "", "", False, overflow)
    return RunResult(rc, out, err, timed_out)


def must(r, what):
    if r.timedOut:
        raise Fail(f"{what} did not answer within {S(TIMEOUT_MS)} ms", EXIT.timeout)
    if r.overflow:
        raise Fail(f"{what} sent more than {(OUT_CAP if r.overflow == 'stdout' else ERR_CAP) // (1024 * 1024)} MiB on {r.overflow}; refused")
    if r.rc == 127:
        raise Fail(f"{what} is not installed")
    if r.rc != 0:
        raise Fail(f"{what} failed with exit {r.rc}")
    return r


def which(name):
    return shutil.which(name) is not None


# ---------------------------------------------------------------- stored settings
# Two small files, each with a schema version. A file that cannot be read is moved aside and replaced by
# defaults, never silently overwritten: the user may want to see what was in it.
#
# Routes are kept per setup: the sorted names of the outputs that are plugged in right now (see setupKey). An
# application sent to the monitor while docked is not sent there at the kitchen table, where a rule for the
# speakers may hold instead; where no rule is written for the setup at hand, the application follows the default.
DEFAULT_DEVICES = {"schemaVersion": 1, "caps": {"headphones": 0.5, "speakers": None}, "devices": {}}
DEFAULT_RULES = {"schemaVersion": 2, "routes": {}}
warnings = []


def isObject(v):
    return isinstance(v, dict)


def loadJson(name, fallback, valid):
    f = pjoin(CONFIG, name)
    if not os.path.exists(f):
        return _copy.deepcopy(fallback)
    try:
        parsed = jparse(read_text(f))
    except Exception:
        parsed = None
    if isinstance(parsed, dict) and strict_eq(parsed.get("schemaVersion"), fallback["schemaVersion"]) and valid(parsed):
        return parsed
    aside = pjoin(CONFIG, re.sub(r"\.json\Z", f".invalid.{now_ms()}.json", name, count=1))
    try:
        os.rename(f, aside)
    except OSError:
        pass  # reported below either way
    warnings.append(f"{name} could not be read and was moved aside; defaults apply")
    return _copy.deepcopy(fallback)


def saveJson(name, value):
    ensureDir(CONFIG)
    write_atomic(pjoin(CONFIG, name), jdump(value, 2) + "\n", 0o600)


def loadDevices():
    # A cap is what stands between a headset and the level of the speakers: one outside 5 to 100 % in the file is
    # no cap, so the whole file is moved aside and the defaults, which cap headphones, hold instead.
    def capOk(c):
        return c is None or c is UNDEF or (is_num(c) and 0.05 <= c <= 1)

    def valid(v):
        return (isObject(v.get("devices")) and isObject(v.get("caps"))
                and all(capOk(c) for c in v["caps"].values())
                and all(isObject(e) and capOk(e.get("cap", UNDEF)) for e in v["devices"].values()))
    d = loadJson("devices.json", DEFAULT_DEVICES, valid)
    caps = dict(DEFAULT_DEVICES["caps"])
    caps.update(d["caps"])
    d["caps"] = caps
    return d


# Read once per process: readGraph asks for the rules, and waitFor reads the graph every few milliseconds, so
# without this the file would be parsed dozens of times per verb and a warning about it pushed as often.
_rules_cache = None


def loadRules():
    global _rules_cache
    if _rules_cache is None:
        _rules_cache = readRules()
    return _copy.deepcopy(_rules_cache)


# Writers hold the lock; a file from before routes were kept per setup is moved aside here, not while reading:
# a reading verb runs beside the writer, and its rename could take the file the writer just wrote.
def saveRules(rules):
    global _rules_cache
    if oldRules():
        try:
            os.rename(pjoin(CONFIG, "rules.json"), pjoin(CONFIG, "rules.v1.json"))
        except OSError:
            pass  # the new file replaces it anyway
    saveJson("rules.json", rules)
    _rules_cache = None


# A file from before routes were kept per setup holds one device per application (schema 1).
def oldRules():
    try:
        old = jparse(read_text(pjoin(CONFIG, "rules.json")))
        return isinstance(old, dict) and strict_eq(old.get("schemaVersion"), 1) and isObject(old.get("routes"))
    except Exception:
        return False


def readRules():
    # An old file is not read as one setup: a rule chosen at the desk would otherwise bind at the kitchen table. It
    # is left in place for the next writer to move aside, and said so once per process.
    if oldRules():
        warnings.append("rules.json came from an older Ballroom; routes are kept per setup now, choose them again (the next route moves it aside as rules.v1.json)")
        return _copy.deepcopy(DEFAULT_RULES)
    return loadJson("rules.json", DEFAULT_RULES, lambda v: isObject(v.get("routes"))
                    and all(isObject(m) and all(isinstance(d, str) for d in m.values()) for m in v["routes"].values()))


# The setup: which outputs are plugged in, as one key. The filter is plumbing and not part of it.
def setupKey(outputs):
    return "|".join(js_sorted([d["name"] for d in outputs if d["available"] and not d["filter"]]))


# The routes that hold in the setup at hand.
def routesIn(rules, setup):
    r = rules["routes"].get(setup)
    return r if r is not None else {}


# Every output an application is sent to in any setup. WirePlumber remembers the last target per application,
# so a stream found on one of these without a rule here is that memory at work, not a choice made by hand.
# The rule for an application, by its name as the stream gives it. A rule typed while the application was closed
# carries the spelling that was typed, so a name that differs only in case is the same application.
def ruleOf(routes, app):
    if app in routes:
        return routes[app]
    low = app.lower()
    for k, v in routes.items():
        if k.lower() == low:
            return v
    return None


def ruleTargets(rules, app):
    out = set()
    for m in rules["routes"].values():
        d = ruleOf(m, app)
        if truthy(d):
            out.add(d)
    return out


# ---------------------------------------------------------------- reading the graph
# A device: name, serial, id, description, nick, label, available, cls ("sink" or "source"), api, kind
# ("headphones" or "speakers"), volume, mute, isDefault, hidden, favorite, cap, codec, profile, filter, btAddress,
# deviceId. A stream: serial, id, name, app, media, direction ("playback" or "record"), volume, mute, target,
# device, fromMonitor, routed, internal, meter. Both are dicts, in this order, because `device list` and `out`
# print them as they are.

# The cubic scale: PipeWire keeps linear channel volumes, everyone who shows a slider shows the cube root.
def visualVolume(props):
    v = gp(props, "channelVolumes")
    if not isinstance(v, list) or not v:
        return 1
    total = 0
    for x in v:
        total += cbrt(js_max(0, js_number(x)))
    return total / len(v)


# p is the node's properties over the card's: a Bluetooth headset says "headset" in device.form-factor and
# device.icon-name on the card only, never on its sink node (measured on PipeWire 1.6.8).
def inferKind(p, stored=None):
    k = gp(stored, "kind")
    if k == "headphones" or k == "speakers":
        return k
    form = S(nn(p.get("device.form-factor"), ""))
    if re.search(r"headphone|headset|hands-?free|earbud", form, re.I):
        return "headphones"
    if re.search(r"speaker|internal|hifi|tv|computer", form, re.I):
        return "speakers"
    text = f'{S(nn(p.get("node.description"), ""))} {S(nn(p.get("node.nick"), ""))} {S(nn(p.get("api.alsa.pcm.id"), ""))} {S(nn(p.get("device.icon-name"), ""))}'
    return "headphones" if re.search(r"headphone|headset", text, re.I) else "speakers"


# The short name a device shows. PipeWire's nick is what the card calls the port ("Speaker", the monitor
# behind an HDMI port); the description names the whole card, and on one card every port shares it. A stored
# alias beats both. Two devices that would end up with the same name fall back to their descriptions.
def friendlyLabel(text):
    s = js_trim(S(nn(text, "")))
    s = re.sub(r"^sof-soundwire\s+", "", s, count=1, flags=re.I)
    s = re.sub(r"^built-?in audio\s+", "", s, count=1, flags=re.I)
    s = re.sub(r"\s+Output\Z", "", s, count=1, flags=re.I)
    s = re.sub(r"\s+Input\Z", "", s, count=1, flags=re.I)
    return re.sub(r"\bMicrophones\b", "Microphone", s, flags=re.ASCII)


def metadataDefault(objects, key):
    md = next((o for o in objects if gp(o, "type") == "PipeWire:Interface:Metadata" and gp(o, "props", "metadata.name") == "default"), None)
    entries = gp(md, "metadata")
    entry = next((e for e in (entries if isinstance(entries, list) else []) if gp(e, "key") == key and strict_eq(gp(e, "subject"), 0)), None)
    return gp(entry, "value", "name")


# A monitor port learns its plug from the display driver, and on some machines that message never comes when a
# dock is pulled: the jack stays on, the route says available, and WirePlumber keeps the default on a monitor
# that is gone. The display side knows better. So while no external display is connected, a display port counts
# as unplugged. With one connected the jack is trusted, since a port cannot be matched to its connector
# reliably. None when there is nothing to ask; the bench hands in its own connectors and never reads the host.
# A connector that answers "unknown" (while a display settles, or with no probe at all) is not asked; only
# "connected" and "disconnected" count, and with nothing that answers the route is trusted. Read once per
# process: a verb is done within seconds, and readGraph asks for it on every read.
_display_cache = UNDEF


def externalDisplay():
    global _display_cache
    if _display_cache is UNDEF:
        _display_cache = readExternalDisplay()
    return _display_cache


def readExternalDisplay():
    d = ENV.get("BALLROOM_DRM") if BENCH else "/sys/class/drm"
    if not d:
        return None
    try:
        names = os.listdir(d)
    except OSError:
        return None
    asked = False
    for n in names:
        m = re.match(r"card[0-9]+-(.+)\Z", n, re.S)
        if not m:
            continue
        try:
            status = js_trim(read_text(pjoin(d, n, "status")))
        except OSError:
            continue
        if re.match(r"(eDP|LVDS|DSI)-", m.group(1)):
            continue
        if status == "connected":
            return True
        if status == "disconnected":
            asked = True
    return False if asked else None


# A route's info is a count followed by key and value pairs.
def displayRoute(r):
    info = gp(r, "info")
    info = info[1:] if isinstance(info, list) else []
    i = 0
    while i + 1 < len(info):
        if info[i] == "port.type":
            return re.fullmatch(r"hdmi|displayport|dp", S(info[i + 1]), re.I) is not None
        i += 2
    return re.search(r"hdmi|displayport", S(nn(gp(r, "name"), "")), re.I) is not None


def _props(o):
    p = gp(o, "info", "props")
    return p if isinstance(p, dict) else {}


def readGraph():
    # The bench hands in a recorded graph to test what null sinks cannot show, such as an unplugged port.
    recorded = ENV.get("BALLROOM_DUMP") if BENCH else None
    # Null sinks have no ports to pull, so the bench names the outputs it calls unplugged. Only Ballroom's reading
    # changes: the node stays in the graph and WirePlumber keeps what is linked to it, as with a real monitor.
    unplugged = set(x for x in S(nn(ENV.get("BALLROOM_UNPLUGGED"), "")).split(",") if x) if BENCH else set()
    raw = read_text(recorded) if recorded else must(run(["pw-dump"]), "pw-dump").out
    try:
        objects = jparse(raw)
    except Exception:
        raise Fail("pw-dump returned no readable JSON")
    if not isinstance(objects, list):
        raise TypeError("pw-dump returned no list")
    devices = loadDevices()
    rules = loadRules()
    nodes = [o for o in objects if gp(o, "type") == "PipeWire:Interface:Node"]
    byId = {}
    for n in nodes:
        byId[n.get("id")] = n
    defaultSink = metadataDefault(objects, "default.audio.sink")
    defaultSource = metadataDefault(objects, "default.audio.source")

    # A port with nothing plugged in is still a node. The card knows: among its routes, the ones carrying the
    # node's profile device say available yes, no or unknown. Only a plain no counts as unplugged, except for a
    # display port while no external display is connected (see externalDisplay).
    cards = [o for o in objects if gp(o, "type") == "PipeWire:Interface:Device"]
    display = externalDisplay()

    def card_of(p):
        want = js_number(p.get("device.id"))
        return next((o for o in cards if is_num(o.get("id")) and o.get("id") == want), None)

    def plugged(p, cls):
        if p.get("device.id") is None or p.get("card.profile.device") is None:
            return True
        card = card_of(p)
        direction = "Output" if cls == "sink" else "Input"
        dev = js_number(p.get("card.profile.device"))
        routes = gp(card, "info", "params", "EnumRoute")
        mine = [r for r in (routes if isinstance(routes, list) else [])
                if gp(r, "direction") == direction and isinstance(gp(r, "devices"), list)
                and any(is_num(x) and (x == dev or (x != x and dev != dev)) for x in r["devices"])]
        if not mine:
            return True
        if display is False and all(displayRoute(r) for r in mine):
            return False
        return any(gp(r, "available") != "no" for r in mine)

    # Muted is muted wherever it is set. On a card with routes, wpctl and the shell set the mute on the active route,
    # and on some devices (a USB webcam was the case) the node's own Props never follow: the node says open while
    # the route, and the sound, is muted. Either one muted means no sound gets through, so either one counts.
    def routeMuted(p, cls):
        if p.get("device.id") is None or p.get("card.profile.device") is None:
            return False
        card = card_of(p)
        direction = "Output" if cls == "sink" else "Input"
        routes = gp(card, "info", "params", "Route")
        route = next((r for r in (routes if isinstance(routes, list) else [])
                      if gp(r, "direction") == direction and js_number(gp(r, "device")) == js_number(p.get("card.profile.device"))), None)
        return gp(route, "props", "mute") is True

    def device(n, cls):
        p = _props(n)
        name = S(nn(p.get("node.name"), ""))
        stored = devices["devices"].get(name) or {}
        card = card_of(p) if p.get("device.id") is not None else None
        merged = dict(_props(card))
        merged.update(p)
        kind = inferKind(merged, stored)
        description = S(nn(p.get("node.description"), nn(p.get("node.nick"), name)))
        nick = friendlyLabel(p.get("node.nick"))
        if "cap" in stored:
            cap = stored["cap"]
        else:
            cap = nn(devices["caps"].get(kind), None) if cls == "sink" else None
        props0 = gp(n, "info", "params", "Props", 0)
        label = stored.get("alias") if truthy(stored.get("alias")) else nick or friendlyLabel(description) or name
        return {
            "name": name, "serial": js_number(p.get("object.serial")), "id": n.get("id"), "description": description, "nick": nick,
            "label": label, "available": plugged(p, cls) and name not in unplugged, "cls": cls,
            "api": S(nn(p.get("device.api"), "virtual")), "kind": kind, "volume": visualVolume(props0),
            "mute": truthy(gp(props0, "mute")) or routeMuted(p, cls), "isDefault": name == (defaultSink if cls == "sink" else defaultSource),
            "hidden": truthy(stored.get("hidden")), "favorite": truthy(stored.get("favorite")), "cap": cap,
            "codec": nn(p.get("api.bluez5.codec"), None), "profile": nn(p.get("api.bluez5.profile"), None),
            "filter": p.get("filter.smart") is True or p.get("filter.smart") == "true" or name.startswith("ballroom."),
            "btAddress": nn(p.get("api.bluez5.address"), None), "deviceId": js_number(p.get("device.id")) if p.get("device.id") is not None else None,
        }

    outputs, inputs, streams = [], [], []
    for n in nodes:
        cls = S(nn(gp(n, "info", "props", "media.class"), ""))
        if cls == "Audio/Sink":
            outputs.append(device(n, "sink"))
        elif cls == "Audio/Source" or cls == "Audio/Source/Virtual":
            inputs.append(device(n, "source"))
    setup = setupKey(outputs)
    routes = routesIn(rules, setup)
    for lst in (outputs, inputs):
        seen = {}
        for d in lst:
            seen[d["label"]] = seen.get(d["label"], 0) + 1
        for d in lst:
            if seen.get(d["label"], 0) > 1 and not truthy(gp(devices["devices"].get(d["name"]), "alias")):
                d["label"] = friendlyLabel(d["description"]) or d["name"]

    links = [o for o in objects if gp(o, "type") == "PipeWire:Interface:Link"]

    def peersOut(i):
        return [x for x in (byId.get(gp(l, "info", "input-node-id")) for l in links if strict_eq(gp(l, "info", "output-node-id"), i)) if truthy(x)]

    def peersIn(i):
        return [x for x in (byId.get(gp(l, "info", "output-node-id")) for l in links if strict_eq(gp(l, "info", "input-node-id"), i)) if truthy(x)]

    # A stream that plays into a filter plays, in the end, into the device behind the filter. The filter's
    # output stream shares its link group, so the chain is followed through that.
    def behind(node, depth=0):
        p = _props(node)
        if node is None or depth > 4 or not S(p.get("media.class", UNDEF)).startswith("Audio/Sink"):
            return node
        group = p.get("node.link-group")
        if not truthy(group):
            return node
        partner = next((m for m in nodes if m is not node and strict_eq(gp(m, "info", "props", "node.link-group"), group)), None)
        nxt = (peersOut(partner.get("id")) or [None])[0] if partner is not None else None
        return behind(nxt, depth + 1) if nxt is not None else node

    for n in nodes:
        p = _props(n)
        cls = S(nn(p.get("media.class"), ""))
        direction = "playback" if cls == "Stream/Output/Audio" else "record" if cls == "Stream/Input/Audio" else None
        if not direction:
            continue
        name = S(nn(p.get("node.name"), ""))
        app = S(nn(p.get("application.name"), name))
        peers = peersOut(n.get("id")) if direction == "playback" else peersIn(n.get("id"))
        peer = peers[0] if peers else None
        peerName = nn(gp(peer, "info", "props", "node.name"), None)
        final = behind(peer) if direction == "playback" and peer is not None else peer
        fromMonitor = direction == "record" and S(nn(gp(peer, "info", "props", "media.class"), "")) == "Audio/Sink"
        props0 = gp(n, "info", "params", "Props", 0)
        streams.append({
            "serial": js_number(p.get("object.serial")), "id": n.get("id"), "name": name, "app": app, "media": S(nn(p.get("media.name"), "")), "direction": direction,
            "volume": visualVolume(props0), "mute": truthy(gp(props0, "mute")),
            "target": peerName, "device": nn(gp(final, "info", "props", "node.name"), None), "fromMonitor": fromMonitor,
            "routed": nn(ruleOf(routes, app), None),
            # The filter's own output and anything Ballroom starts itself are plumbing, not a way sound takes.
            "internal": name.startswith("ballroom."),
            # Quickshell's PwNodePeakMonitor names its capture so. The level bar in Ballroom's own panel is one of
            # these, and the panel leaves it out of "who is listening" while that bar runs; the command shows it.
            "meter": app == "Quickshell Peak Detect",
        })
    return {"objects": objects, "outputs": outputs, "inputs": inputs, "streams": streams,
            "defaultSink": defaultSink, "defaultSource": defaultSource, "setup": setup}


# ---------------------------------------------------------------- finding what the user means
# A device is named by node.name, by its alias, by its number in the listing, or by a unique part of its
# description. Anything ambiguous is refused with the candidates, never guessed.
def findDevice(g, cls, query):
    lst = [d for d in (g["outputs"] if cls == "sink" else g["inputs"]) if not d["filter"]]
    q = js_trim(query)
    word = "output" if cls == "sink" else "input"
    if q == "" or q == "default":
        d = next((d for d in lst if d["isDefault"]), None)
        if d is not None:
            return d
        raise Fail(f"there is no default {word}", EXIT.notFound)
    exact = next((d for d in lst if d["name"] == q), None) or next((d for d in lst if d["label"] == q), None)
    if exact is not None:
        return exact
    if re.fullmatch(r"[0-9]+", q):
        d = at(lst, js_number(q) - 1)
        if d is not None:
            return d
    lower = q.lower()
    partial = [d for d in lst if lower in S(d["label"]).lower() or lower in d["description"].lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise Fail(f'"{q}" matches {len(partial)} devices: {", ".join(S(d["label"]) for d in partial)}', EXIT.usage)
    raise Fail(f'no {word} called "{q}"', EXIT.notFound)


def findStreams(g, query):
    q = js_trim(query)
    own = [s for s in g["streams"] if not s["internal"]]
    bySerial = [s for s in own if s["serial"] == js_number(q.replace("#", "", 1))] if re.fullmatch(r"#?[0-9]+", q) else []
    if bySerial:
        return bySerial
    lower = q.lower()
    return [s for s in own if s["app"].lower() == lower or s["name"] == q]


# ---------------------------------------------------------------- writing, always read back
def percent(v):
    return js_round((v if is_num(v) else _tonum(v)) * 100)


# A level in a scene as JavaScript reads it from a file someone may have edited: a missing field is undefined, and
# arithmetic with it gives NaN, which compares false, so the step is skipped instead of the scene failing.
def _lv(lv, key):
    return lv.get(key, UNDEF) if isinstance(lv, dict) else UNDEF


def _tonum(v):
    return 0 if v is None else js_number(v)


def parseLevel(text, current):
    m = re.fullmatch(r"([+-]?)([0-9]+(?:\.[0-9]+)?)%?", js_trim(text))
    if not m:
        raise Fail(f'"{text}" is not a volume; use 0 to 150, +5 or -5', EXIT.usage)
    value = js_number(m.group(2)) / 100
    nxt = current + value if m.group(1) == "+" else current - value if m.group(1) == "-" else value
    return js_max(0, js_min(1.5, nxt))


# The id is looked up again right before each write: an id from an earlier reading may belong to another
# object by now.
def idOf(kind, name):
    g = readGraph()
    n = next((o for o in g["objects"] if gp(o, "type") == "PipeWire:Interface:Node" and gp(o, "info", "props", "node.name") == name), None)
    if n is None:
        raise Fail(f'"{name}" is gone', EXIT.notFound)
    return n.get("id")


def setVolume(nodeName, level):
    must(run(["wpctl", "set-volume", S(idOf("node", nodeName)), to_fixed(level, 4)]), "wpctl set-volume")


def setVolumeOfStream(serial, level):
    g = readGraph()
    s = next((x for x in g["streams"] if x["serial"] == serial), None)
    if s is None:
        raise Fail(f"stream #{S(serial)} is gone", EXIT.notFound)
    must(run(["wpctl", "set-volume", S(s["id"]), to_fixed(level, 4)]), "wpctl set-volume")


def setMute(i, on):
    must(run(["wpctl", "set-mute", S(i), "1" if on else "0"]), "wpctl set-mute")


def setDefault(nodeName):
    must(run(["wpctl", "set-default", S(idOf("node", nodeName))]), "wpctl set-default")


# Reading back takes a moment: WirePlumber applies a default or a route asynchronously.
def waitFor(check, limitMs=2000):
    until = now_ms() + limitMs
    g = readGraph()
    while not check(g) and now_ms() < until:
        sleep_ms(25)
        g = readGraph()
    return g


def find_by_name(lst, name):
    return next((x for x in lst if x["name"] == name), None)


def find_by_serial(lst, serial):
    return next((x for x in lst if x["serial"] == serial), None)


def default_of(lst):
    return next((x for x in lst if x["isDefault"] and not x["filter"]), None)


# ---------------------------------------------------------------- rules
# Rule 6. Everything that could catch the sound while the device is away is muted first, and afterwards only
# what this function muted is unmuted again: a device the user had muted stays muted.
# `isBack` says when the device has returned. It is a predicate, not a name: a Bluetooth sink in call mode can
# carry another node name than in music mode, and only its hardware address stays the same.
# If the device does not come back, the outputs stay muted and a warning says so: the sound would otherwise land
# on whatever WirePlumber picks next, at that output's level. Failing quiet is the safe way to fail here; the
# warning names the way out.
def guarded(keep, isBack, action, limitMs=15000):
    g = readGraph()
    others = [d for d in g["outputs"] if not keep(d) and not d["filter"] and not d["mute"]]
    for d in others:
        setMute(d["id"], True)
    started = now_ms()
    backAfterMs = None
    heldMuted = 0
    try:
        action()
        after = waitFor(isBack, limitMs)
        if isBack(after):
            backAfterMs = now_ms() - started
    finally:
        now = readGraph()
        # Decided on the graph as it is now, not on how the action went: an action that failed before the device ever
        # left leaves it where it was, and then nothing has to stay muted.
        if isBack(now):
            for d in others:
                live = find_by_name(now["outputs"], d["name"])
                if live is not None:
                    setMute(live["id"], False)
        elif others:
            heldMuted = len(others)
            warnings.append(f"the device did not come back, so {len(others)} other output(s) stay muted rather than play in its place; unmute them with ballroom mute OUTPUT off once the sound is where it should be")
    return {"mutedAround": len(others), "backAfterMs": backAfterMs, "heldMuted": heldMuted}


# Hearing protection for a device that is about to carry the sound: above its cap it is brought down first,
# then made the default. Never the other way round.
def capBeforeUse(d):
    if d["cap"] is None or d["volume"] <= d["cap"] + 0.005:
        return False
    setVolume(d["name"], d["cap"])
    return True


# ---------------------------------------------------------------- verbs
# Every verb answers with an Out: {"json": ..., "text": ..., "osd": {icon, percent?, message?}}.
def Out(js, text, osd=None):
    return {"json": js, "text": text, "osd": osd}


def statusLines(g):
    out = next((d for d in g["outputs"] if d["isDefault"]), None)
    inp = next((d for d in g["inputs"] if d["isDefault"]), None)
    playing = [s for s in g["streams"] if not s["internal"] and s["direction"] == "playback"]
    listening = [s for s in g["streams"] if not s["internal"] and s["direction"] == "record" and not s["fromMonitor"]]
    o = (f'{S(out["label"])}  {percent(out["volume"])} %{"  muted" if out["mute"] else ""}{"  " + S(out["codec"]).upper() if truthy(out["codec"]) else ""}'
         if out is not None else "none")
    i = f'{S(inp["label"])}  {percent(inp["volume"])} %{"  muted" if inp["mute"] else ""}' if inp is not None else "none"
    p = ", ".join(f'{s["app"]} {percent(s["volume"])} %{" muted" if s["mute"] else ""}' for s in playing) if playing else "nothing"
    li = ", ".join(s["app"] for s in listening) if listening else "nobody"
    return [f"Output  {o}", f"Input   {i}", f"Playing {p}", f"Listening {li}"]


def verbStatus():
    g = readGraph()
    return Out(stateJson(g), "\n".join(statusLines(g) + [f"warning: {w}" for w in warnings]))


def _try(f, otherwise):
    try:
        return f()
    except Exception:
        return otherwise


def stateJson(g):
    def pick(d):
        return {k: d[k] for k in ("name", "serial", "label", "description", "kind", "api", "volume", "mute", "isDefault",
                                  "hidden", "available", "favorite", "cap", "codec", "profile")}

    def bluetooth():
        out = []
        for b in btDevices(g):
            codecs_ = []
            for x in btOffers(b):
                if x["codec"] not in codecs_:
                    codecs_.append(x["codec"])
            # node names a field the Bluetooth entry does not carry, so it is never written.
            out.append({"address": b["address"], "mode": btModeNow(b), "codec": btCodecNow(b), "codecs": codecs_})
        return out

    return {
        "ok": True, "version": VERSION,
        "defaultOutput": g["defaultSink"], "defaultInput": g["defaultSource"],
        "outputs": [pick(d) for d in g["outputs"] if not d["filter"]],
        "inputs": [pick(d) for d in g["inputs"] if not d["filter"]],
        "sound": _try(lambda: eqReport(soundPlan(g), eqNode(g) is not None, g), None),
        "health": _try(lambda: health(g), []),
        # The rules that send an application to one output. They hold whether that application runs or not, so the
        # panel needs them beside the streams: a rule for a program that is closed has no row of its own otherwise.
        # Only the rules of the setup at hand: the others belong to other places and would show as pinned here.
        "setup": g["setup"],
        "routes": [{"app": cut(clean(app), 120), "device": dev} for app, dev in routesIn(loadRules(), g["setup"]).items()],
        # Every Bluetooth audio device with what can be set on it: the mode it is in, the codec it carries, and the
        # codecs it offers in music mode. The panel cannot work these out from the graph alone.
        "bluetooth": _try(bluetooth, []),
        # The limit a device of each kind starts at when it arrives without one of its own. The panel offers it
        # beside a device's own limit, and the two are not the same thing.
        "caps": loadDevices()["caps"],
        # Whether WirePlumber switches a Bluetooth headset to call mode when an application opens its microphone.
        "btAuto": _try(lambda: smSetting(g, "bluetooth.autoswitch-to-headset-profile") == "true", None),
        "stage": _try(stageState, None),
        # stage marks our own player among the streams, by node.name and never by the application name: the name
        # carries whatever mpv was told to call itself, node.name is what the unit set.
        "streams": [{"serial": s["serial"], "app": cut(clean(s["app"]), 120), "media": cut(maskKey(clean(s["media"])), 160),
                     "direction": s["direction"], "volume": s["volume"], "mute": s["mute"], "device": s["device"],
                     "fromMonitor": s["fromMonitor"], "routed": s["routed"], "meter": s["meter"],
                     "stage": s["name"] == STAGE_NODE} for s in g["streams"] if not s["internal"]],
        "warnings": warnings,
    }


def listDevices(g, cls):
    lst = [d for d in (g["outputs"] if cls == "sink" else g["inputs"]) if not d["filter"]]
    text = "\n".join(
        f'{"*" if d["isDefault"] else " "} {pad_start(str(i + 1), 2)}  {S(d["label"])}  {percent(d["volume"])} %{"  muted" if d["mute"] else ""}'
        f'{"  hidden" if d["hidden"] else ""}{"" if d["available"] else "  unplugged"}  ({d["kind"]})' for i, d in enumerate(lst))
    return Out({"ok": True, "devices": lst}, text or "no devices")


def verbOut(args):
    g = readGraph()
    if not args:
        return listDevices(g, "sink")
    return withLock(lambda: outNow(g, args))


def outNow(g, args):
    d = nextOutput(g) if len(args) == 1 and args[0] == "next" else findDevice(g, "sink", " ".join(args))
    # The cap is for an output that arrives. The one already playing keeps the level it is listened at.
    capped = False if d["isDefault"] else capBeforeUse(d)
    # An output the user chose is theirs: Ballroom no longer moves the default back after an undock.
    rm_force(pjoin(CONFIG, "undocked.json"))
    setDefault(d["name"])
    after = waitFor(lambda x: x["defaultSink"] == d["name"])
    if after["defaultSink"] != d["name"]:
        raise Fail(f'{S(d["label"])} did not become the default output')
    # The new device's preset is set now, while the sound changes device anyway: one change, one click.
    if truthy(loadSound()["enabled"]):
        try:
            eqSync()
        except Exception as e:
            warnings.append(fail_text(e, "the equalizer did not follow"))
    now = find_by_name(after["outputs"], d["name"])
    if now is None:
        raise TypeError("the output is gone")
    brought = f" (brought down to its cap of {percent(d['cap'])} % first)" if capped else ""
    return Out({"ok": True, "output": d["name"], "volume": now["volume"], "capped": capped},
               f'Output {S(now["label"])}, {percent(now["volume"])} %{brought}',
               {"icon": "volume-muted" if now["mute"] else "volume-high", "percent": percent(now["volume"]), "message": now["label"]})


def verbIn(args):
    g = readGraph()
    if not args:
        return listDevices(g, "source")
    d = findDevice(g, "source", " ".join(args))
    # WirePlumber does not make an unplugged input the default; refused before anything is switched on its way.
    if not d["available"]:
        raise Fail(f'{S(d["label"])} is unplugged; choose an input that is plugged in', EXIT.usage)
    # A microphone the user muted stays closed: switching to another one does not open a live microphone.
    previous = next((x for x in g["inputs"] if x["isDefault"]), None)
    keepClosed = previous is not None and previous["mute"] and not d["mute"]
    if keepClosed:
        setMute(d["id"], True)
        # Rule 1 and the microphone: the switch happens only once the new input reads back as muted.
        shut = waitFor(lambda x: gp(find_by_name(x["inputs"], d["name"]), "mute") is True)
        if gp(find_by_name(shut["inputs"], d["name"]), "mute") is not True:
            raise Fail(f'{S(d["label"])} could not be muted, so it did not become the default input')
    setDefault(d["name"])
    after = waitFor(lambda x: x["defaultSource"] == d["name"])
    if after["defaultSource"] != d["name"]:
        raise Fail(f'{S(d["label"])} did not become the default input')
    now = find_by_name(after["inputs"], d["name"])
    if now is None:
        raise TypeError("the input is gone")
    return Out({"ok": True, "input": d["name"], "mute": now["mute"], "keptClosed": keepClosed},
               f'Input {S(now["label"])}{", muted" if now["mute"] else ""}{" (kept muted, the previous input was muted)" if keepClosed else ""}',
               {"icon": "microphone-muted" if now["mute"] else "microphone", "message": now["label"]})


# vol [TARGET] [LEVEL]. TARGET is "out", "in", a device or an application; without it the default output.
def resolveTarget(g, words):
    q = js_trim(" ".join(words))
    if q == "" or q == "out":
        d = findDevice(g, "sink", "")
        return {"devices": [d], "streams": [], "label": d["label"]}
    if q == "in":
        d = findDevice(g, "source", "")
        return {"devices": [d], "streams": [], "label": d["label"]}
    streams = findStreams(g, q)
    for cls in ("sink", "source"):
        try:
            d = findDevice(g, cls, q)
            return {"devices": [d], "streams": [], "label": d["label"]}
        except Fail as e:
            if e.code != EXIT.notFound:
                raise
    if streams:
        return {"devices": [], "streams": streams, "label": streams[0]["app"]}
    raise Fail(f'nothing called "{q}"', EXIT.notFound)


def verbVol(args):
    g = readGraph()
    last = args[-1] if args else None
    hasLevel = last is not None and re.fullmatch(r"[+-]?[0-9]+(\.[0-9]+)?%?", last) is not None
    target = resolveTarget(g, args[:-1] if hasLevel else args)
    if target["devices"]:
        current = target["devices"][0]["volume"]
    elif target["streams"]:
        current = target["streams"][0]["volume"]
    else:
        current = 1
    if not hasLevel:
        return Out({"ok": True, "target": target["label"], "volume": current}, f'{S(target["label"])} {percent(current)} %')
    level = parseLevel(last, current)
    for d in target["devices"]:
        setVolume(d["name"], level)
    for s in target["streams"]:
        setVolumeOfStream(s["serial"], level)
    after = readGraph()
    if target["devices"]:
        now = gp(find_by_name(after["outputs"] + after["inputs"], target["devices"][0]["name"]), "volume")
    else:
        now = gp(find_by_serial(after["streams"], target["streams"][0]["serial"]), "volume")
    osd = {"icon": "microphone" if gp(target["devices"], 0, "cls") == "source" else "volume-high", "percent": percent(nn(now, 0))}
    if not target["devices"]:
        osd["message"] = target["label"]
    return Out({"ok": True, "target": target["label"], "volume": now}, f'{S(target["label"])} {"gone" if now is None else f"{percent(now)} %"}', osd)


def verbMute(args):
    g = readGraph()
    last = args[-1] if args else None
    mode = last if last in ("on", "off", "toggle") else "toggle"
    target = resolveTarget(g, args[:-1] if mode == last else args)
    items = [{"id": d["id"], "mute": d["mute"]} for d in target["devices"]] + [{"id": s["id"], "mute": s["mute"]} for s in target["streams"]]
    nxt = True if mode == "on" else False if mode == "off" else not truthy(gp(items, 0, "mute"))
    for it in items:
        setMute(it["id"], nxt)
    # Rule 1: the answer is what the graph says now, not what was sent.
    after = readGraph()
    if target["devices"]:
        now = gp(find_by_name(after["outputs"] + after["inputs"], target["devices"][0]["name"]), "mute")
    else:
        now = gp(find_by_serial(after["streams"], target["streams"][0]["serial"]), "mute")
    if now is None:
        raise Fail(f'{S(target["label"])} is gone', EXIT.notFound)
    if now != nxt:
        raise Fail(f'{S(target["label"])} did not {"mute" if nxt else "unmute"}')
    src = gp(target["devices"], 0, "cls") == "source"
    icon = ("microphone-muted" if nxt else "microphone") if src else ("volume-muted" if nxt else "volume-high")
    return Out({"ok": True, "target": target["label"], "mute": now}, f'{S(target["label"])} {"muted" if now else "unmuted"}',
               {"icon": icon, "message": f'{S(target["label"])} {"muted" if nxt else "on"}'})


def set_target(stream_id, value):
    must(run(["pw-metadata", "-n", "default", "--", S(stream_id), "target.object", value, "Spa:Id"]), "pw-metadata")


def device_of(g, serial):
    return gp(find_by_serial(g["streams"], serial), "device")


# route APP DEVICE | route APP follow | route. WirePlumber remembers the target per application by device name
# once a stream was moved; the rule file adds what WirePlumber does not do: letting a stream follow the default
# while its device is unplugged, moving it back when the device returns, and keeping the rule for the setup it
# was chosen in, so that docking and undocking switch between rules (see apply). A rule is written for the setup
# at hand and read only there; follow removes it there.
def verbRoute(args):
    return withLock(lambda: routeNow(args)) if args else routeNow(args)


def routeNow(args):
    rules = loadRules()
    if not args:
        # The listing is the file; the graph only says which setup is the one at hand, and without an answer from
        # PipeWire the file is still listed.
        setup = None
        try:
            setup = readGraph()["setup"]
        except Exception:
            warnings.append("PipeWire did not answer, so which setup holds is unknown")
        lines = []
        for key, m in rules["routes"].items():
            lines.append("this setup:" if key == setup else f'setup {", ".join(key.split("|"))}:')
            for app, dev in m.items():
                lines.append(f"  {app} -> {dev}")
        return Out({"ok": True, "setup": setup, "routes": {} if setup is None else routesIn(rules, setup), "setups": rules["routes"]},
                   "\n".join(lines) or "no routes")
    g = readGraph()
    if len(args) < 2:
        raise Fail("usage: ballroom route APP DEVICE|follow", EXIT.usage)
    wanted = " ".join(args[1:])
    streams = [s for s in g["streams"] if not s["internal"] and s["direction"] == "playback" and s["app"].lower() == args[0].lower()]
    here = routesIn(rules, g["setup"])
    app = streams[0]["app"] if streams else next((k for k in here if k.lower() == args[0].lower()), args[0])
    for k in list(here.keys()):
        if k != app and k.lower() == app.lower():
            del here[k]
    if wanted == "follow":
        here.pop(app, None)
        if here:
            rules["routes"][g["setup"]] = here
        else:
            rules["routes"].pop(g["setup"], None)
        saveRules(rules)
        for s in streams:
            set_target(s["id"], "-1")
        # Rule 1: WirePlumber moves a freed stream to the default output; count the ones that arrived there.
        if streams and truthy(g["defaultSink"]):
            back = waitFor(lambda x: all(device_of(x, s["serial"]) == g["defaultSink"] for s in streams))
        else:
            back = g
        moved = len([s for s in streams if device_of(back, s["serial"]) == g["defaultSink"]])
        return Out({"ok": True, "app": app, "route": None, "moved": moved, "running": len(streams)},
                   f'{app} follows the default output in this setup{f" ({moved} of {len(streams)} running streams moved)" if streams else ""}')
    d = findDevice(g, "sink", wanted)
    if not d["available"]:
        raise Fail(f'{S(d["label"])} is unplugged; a rule is chosen among the outputs that are plugged in', EXIT.usage)
    here[app] = d["name"]
    rules["routes"][g["setup"]] = here
    saveRules(rules)
    for s in streams:
        set_target(s["id"], S(d["serial"]))
    after = waitFor(lambda x: all(device_of(x, s["serial"]) == d["name"] for s in streams)) if streams else g
    moved = len([s for s in streams if device_of(after, s["serial"]) == d["name"]])
    return Out({"ok": True, "app": app, "route": d["name"], "moved": moved, "running": len(streams)},
               f'{app} -> {S(d["label"])} in this setup{f" ({moved} of {len(streams)} running streams moved)" if streams else " (applies when it plays)"}')


def verbDevice(args):
    return deviceNow(args) if not args or args[0] == "list" else withLock(lambda: deviceNow(args))


_CAP_RE = r"[0-9]+(\.[0-9]+)?%?"


def deviceNow(args):
    sub = args[0] if args else None
    rest = args[1:]
    g = readGraph()
    if not sub or sub == "list":
        al = [d for d in g["outputs"] + g["inputs"] if not d["filter"]]
        return Out({"ok": True, "devices": al}, "\n".join(
            f'{"out" if d["cls"] == "sink" else "in "} {S(d["label"])}  ({d["kind"]}{", cap " + S(percent(d["cap"])) + " %" if d["cap"] is not None else ""}'
            f'{", hidden" if d["hidden"] else ""}{"" if d["available"] else ", unplugged"})' for d in al))
    devices = loadDevices()

    def findAny(q):
        try:
            return findDevice(g, "sink", q)
        except Fail as e:
            if e.code == EXIT.notFound:
                return findDevice(g, "source", q)
            raise

    def entry(d):
        e = devices["devices"].get(d["name"])
        if e is None:
            e = devices["devices"][d["name"]] = {}
        return e

    if sub == "alias":
        if len(rest) < 2:
            raise Fail("usage: ballroom device alias DEVICE NAME|-", EXIT.usage)
        d = findAny(rest[0])
        text = " ".join(rest[1:])
        if text == "-":
            entry(d).pop("alias", None)
        else:
            entry(d)["alias"] = text
    elif sub in ("hide", "show"):
        d = findAny(" ".join(rest))
        entry(d)["hidden"] = sub == "hide"
    elif sub == "kind":
        if len(rest) < 2 or rest[-1] not in ("headphones", "speakers", "auto"):
            raise Fail("usage: ballroom device kind DEVICE headphones|speakers|auto", EXIT.usage)
        d = findAny(" ".join(rest[:-1]))
        k = rest[-1]
        if k == "auto":
            entry(d).pop("kind", None)
        else:
            entry(d)["kind"] = k
    elif sub == "classcap":
        kind = rest[0] if rest else None
        v = rest[1] if len(rest) > 1 else None
        if kind not in ("headphones", "speakers") or v is None:
            raise Fail("usage: ballroom device classcap headphones|speakers PERCENT|none", EXIT.usage)
        # The same bound as a device's own cap. A cap of 0 would let every headset that arrives arrive silent, and
        # 150 is no cap at all; parseLevel alone takes both. The bound used to sit in the surface that asked for
        # the number, which left the verb open to anything.
        if v == "none":
            devices["caps"][kind] = None
        else:
            if not re.fullmatch(_CAP_RE, v):
                raise Fail("a cap is a percentage from 5 to 100, or none", EXIT.usage)
            cap = parseLevel(v, 0)
            if cap < 0.05 or cap > 1:
                raise Fail("a cap is a percentage from 5 to 100, or none", EXIT.usage)
            devices["caps"][kind] = cap
    elif sub == "reset":
        d = findAny(" ".join(rest))
        devices["devices"].pop(d["name"], None)
    elif sub == "cap":
        if len(rest) < 2:
            raise Fail("usage: ballroom device cap DEVICE PERCENT|-|none", EXIT.usage)
        d = findAny(" ".join(rest[:-1]))
        v = rest[-1]
        # A cap says how loud something may arrive at the ear, so it belongs to an output. On an input it would
        # quietly hold a microphone down, which is not what anyone asks for here.
        if d["cls"] != "sink":
            raise Fail("a cap belongs to an output; an input has none", EXIT.usage)
        if v == "-":
            entry(d).pop("cap", None)
        elif v == "none":
            entry(d)["cap"] = None
        else:
            if not re.fullmatch(_CAP_RE, v):
                raise Fail("a cap is a percentage from 5 to 100, or none", EXIT.usage)
            cap = parseLevel(v, 0)
            if cap < 0.05 or cap > 1:
                raise Fail("a cap is a percentage from 5 to 100, or none", EXIT.usage)
            entry(d)["cap"] = cap
    else:
        raise Fail(f"unknown: device {sub}", EXIT.usage)
    saveJson("devices.json", devices)
    return Out({"ok": True}, "saved")


# apply: brings the current graph in line with the stored rules. It is what the service runs when anything in
# the graph comes or goes, and it changes nothing the second time.
#
# WirePlumber moves the default off an output whose route says unplugged. When the plug is not reported (see
# externalDisplay), it never hears of it and the default stays on a monitor that is gone, taking every new
# stream with it. So apply moves the default to the plugged output WirePlumber ranks highest, capped first like
# one that arrives, and remembers which one the user had chosen. Once that one is plugged in again, the default
# goes back, but only if it still sits where apply put it: a default the user chose meanwhile is theirs. The
# note lives beside the settings, not in the runtime directory: WirePlumber keeps the default that apply set as
# the configured one across logins, so the way back has to survive a login as well.
def followPlug(g, changes):
    f = pjoin(CONFIG, "undocked.json")
    note = None
    try:
        v = jparse(read_text(f))
        if isinstance(gp(v, "chosen"), str) and isinstance(gp(v, "placed"), str):
            note = v
    except Exception:
        pass  # nothing was moved
    df = next((x for x in g["outputs"] if x["isDefault"] and not x["filter"]), None)
    if note is not None:
        # Only a default the user chose ends the note: one that is plugged in, where Ballroom did not put it, while
        # the output Ballroom put it on is still there to be chosen against. No default yet (a login in progress), or
        # a default WirePlumber moved because that output went away, is not a choice, and the note stays.
        placed = next((x for x in g["outputs"] if x["name"] == note["placed"] and x["available"] and not x["filter"]), None)
        if df is not None and df["available"] and df["name"] != note["placed"] and placed is not None:
            rm_force(f)
            note = None
        else:
            chosen = next((x for x in g["outputs"] if x["name"] == note["chosen"] and x["available"] and not x["filter"]), None)
            # The chosen output is still away. If the one the default was placed on is unplugged now as well, the
            # default moves on below and the note keeps naming the output the user had chosen.
            if chosen is not None:
                if gp(df, "name") == chosen["name"]:
                    rm_force(f)
                    return False
                if capBeforeUse(chosen):
                    changes.append(f'{chosen["name"]}: brought down to {percent(chosen["cap"])} %')
                setDefault(chosen["name"])
                # The note goes only once the way back is read back; a switch that did not take is tried again next time.
                if waitFor(lambda x: x["defaultSink"] == chosen["name"])["defaultSink"] == chosen["name"]:
                    rm_force(f)
                    changes.append(f'default output: back to {chosen["name"]}, plugged in again')
                else:
                    warnings.append(f'the default output did not go back to {chosen["name"]}')
                return True
            if df is None or df["available"]:
                return False
    if df is None or df["available"]:
        return False
    chosenName = note["chosen"] if note is not None else df["name"]

    def rank(d):
        n = next((o for o in g["objects"] if gp(o, "type") == "PipeWire:Interface:Node" and gp(o, "info", "props", "node.name") == d["name"]), None)
        r = js_number(nn(gp(n, "info", "props", "priority.session"), 0))
        return r if truthy(r) else 0

    candidates = [x for x in g["outputs"] if x["available"] and not x["filter"] and x["name"] != df["name"]]
    shown = [x for x in candidates if not x["hidden"]]

    def order(a, b):
        r = rank(b) - rank(a)
        return r if truthy(r) else locale_compare(a["name"], b["name"])

    pool = sorted(shown if shown else candidates, key=functools.cmp_to_key(order))
    nxt = pool[0] if pool else None
    if nxt is None:
        return False
    if capBeforeUse(nxt):
        changes.append(f'{nxt["name"]}: brought down to {percent(nxt["cap"])} %')
    # Written before the move: a default that moves late, after the read-back gave up, still finds its way back.
    # If it did not move at all, the default is still on the unplugged output and the next apply tries again.
    saveJson("undocked.json", {"chosen": chosenName, "placed": nxt["name"]})
    setDefault(nxt["name"])
    if waitFor(lambda x: x["defaultSink"] == nxt["name"])["defaultSink"] != nxt["name"]:
        warnings.append(f'{df["name"]} is unplugged and the default output did not move to {nxt["name"]}')
        return True
    changes.append(f'default output: {df["name"]} is unplugged, {nxt["name"]} until {chosenName} is back')
    return True


# The cap is for an output that arrives, not for one that is already there: the service runs apply on every
# node that appears, a stream that starts or the panel's own spectrum included, and capping then would pull a
# headset the user turned up to 70 % down to 50 % in the middle of a song. So apply remembers which outputs it has seen, in the runtime directory, and caps only the ones
# that were not there last time. After a login the file is gone and every output counts as arriving. An output
# that was there but unplugged counts as arriving when it is plugged in: a headphone jack or a monitor port stays
# a node while nothing is in it, so only its plug says that something new now carries the sound.
#
# Unplugging a port leaves its node in the graph, and WirePlumber leaves a stream linked to a node it was sent
# to: a player routed to a monitor plays into a dock that is gone. So apply lets every stream that sits on an
# unplugged output follow the default, and a stream with a rule goes back to its device once that device is
# plugged in again. The default itself goes too when WirePlumber leaves it on an unplugged output (see
# followPlug).
def verbApply():
    return withLock(applyNow)


def applyNow():
    g = readGraph()
    changes = []
    seenFile = pjoin(RUNTIME, "outputs-seen.json")
    seen = None
    try:
        v = jparse(read_text(seenFile))
        if isinstance(v, list):
            seen = [S(x) for x in v]
    except Exception:
        pass  # first apply of this login
    outputs = [x for x in g["outputs"] if not x["filter"] and x["available"]]
    for d in outputs:
        if seen is not None and d["name"] in seen:
            continue
        if capBeforeUse(d):
            changes.append(f'{d["name"]}: brought down to {percent(d["cap"])} %')
    ensureDir(RUNTIME)
    writeRuntime("outputs-seen.json", jdump([d["name"] for d in outputs]) + "\n")
    # Read again when a cap was applied: followPlug caps the output it moves to from the graph it is handed, and
    # a stale level there would have it report the same drop a second time.
    if changes:
        g = readGraph()
    if followPlug(g, changes):
        g = readGraph()
    # The equalizer: make up for a lost preamp, bring it back, and give it the new default device's preset.
    eqGuard(g, changes)
    if truthy(loadSound()["enabled"]) or eqNode(g) is not None:
        try:
            r = eqSync()
            if r["action"] != "none":
                changes.append(f'equalizer: {r["action"]}')
        except Exception as e:
            warnings.append(fail_text(e, "the equalizer could not be brought in line"))
    rules = loadRules()
    # Read again right before the routes: the equalizer may just have been restarted above, and PipeWire hands
    # out ids anew when nodes come and go (rule 3). What was moved is read back afterwards (rule 1).
    g = readGraph()
    routes = routesIn(rules, g["setup"])
    moved, freed, released = [], [], []
    df = next((x for x in g["outputs"] if x["isDefault"] and not x["filter"] and x["available"]), None)
    for s in [x for x in g["streams"] if not x["internal"] and x["direction"] == "playback"]:
        want = ruleOf(routes, s["app"])
        d = find_by_name(g["outputs"], want) if truthy(want) else None
        if d is not None and d["available"]:
            if s["device"] == want:
                continue
            set_target(s["id"], S(d["serial"]))
            moved.append(s)
            continue
        # Freed only toward a default that is plugged in and is another device: anything else changes nothing
        # audible and would move the stream again on every apply.
        on = find_by_name(g["outputs"], s["device"])
        if on is None or df is None or df["name"] == on["name"]:
            continue
        if on["available"]:
            # Plugged in, but not the default, and no rule here. If that output is where a rule of another setup sends
            # this application, the stream is there by that rule or by WirePlumber's memory of it, and it is let go,
            # whether the setup changed in this run or the application started later. Anywhere else it was put by
            # hand, and stays.
            if on["name"] not in ruleTargets(rules, s["app"]):
                continue
            set_target(s["id"], "-1")
            released.append(s)
            continue
        set_target(s["id"], "-1")
        freed.append(s)
    if freed or released:
        al = freed + released
        after = waitFor(lambda x: all(device_of(x, s["serial"]) == df["name"] for s in al))
        for s in freed:
            if device_of(after, s["serial"]) == df["name"]:
                changes.append(f'{s["app"]}: {S(s["device"])} is unplugged, follows the default {df["name"]}')
            else:
                warnings.append(f'{s["app"]} plays into {S(s["device"])}, which is unplugged, and did not follow the default')
        for s in released:
            if device_of(after, s["serial"]) == df["name"]:
                changes.append(f'{s["app"]}: no rule in this setup, follows the default {df["name"]}')
            else:
                warnings.append(f'{s["app"]} has no rule in this setup and did not follow the default')
    if moved:
        after = waitFor(lambda x: all(device_of(x, s["serial"]) == ruleOf(routes, s["app"]) for s in moved))
        for s in moved:
            to = ruleOf(routes, s["app"])
            if device_of(after, s["serial"]) == to:
                changes.append(f'{s["app"]}: back to {S(to)}')
            else:
                warnings.append(f'{s["app"]} did not move to {S(to)}')
    return Out({"ok": True, "changes": changes}, "\n".join(changes) if changes else "nothing to do")


# _guard DEVICE -- COMMAND: runs a command that makes DEVICE vanish and return, with rule 6 around it. The
# Bluetooth verbs use the same function; the bench uses this verb to prove it.
def verbGuard(args):
    sep = args.index("--") if "--" in args else -1
    if sep < 1 or sep == len(args) - 1:
        raise Fail("usage: ballroom _guard DEVICE -- COMMAND", EXIT.usage)
    g = readGraph()
    d = findDevice(g, "sink", " ".join(args[:sep]))
    cmd = args[sep + 1:]

    def action():
        r = run(cmd, 20000)
        if r.rc != 0:
            raise Fail(f"the guarded command exited {r.rc}")
    result = guarded(lambda x: x["name"] == d["name"], lambda x: x["defaultSink"] == d["name"] and any(y["name"] == d["name"] for y in x["outputs"]), action)
    js = {"ok": result["backAfterMs"] is not None}
    js.update(result)
    return Out(js, f'back after {result["backAfterMs"]} ms, {result["mutedAround"]} outputs held muted' if result["backAfterMs"] is not None else "the device did not come back")


# ---------------------------------------------------------------- bluetooth
# Only the sound of a headset: its codec, music or call mode, and whether WirePlumber may switch to call mode by
# itself. Pairing and connecting stay with Omarchy's Bluetooth panel.
# A Bluetooth device: id, address, label, profile, profiles (each index, name, available, codec).
def btDevices(g):
    out = []
    for o in g["objects"]:
        if gp(o, "type") != "PipeWire:Interface:Device" or gp(o, "info", "props", "device.api") != "bluez5":
            continue
        sink = next((d for d in g["outputs"] if d["deviceId"] is not None and strict_eq(d["deviceId"], o.get("id"))), None)
        p = _props(o)
        enum = gp(o, "info", "params", "EnumProfile")
        profiles = []
        for e in (enum if isinstance(enum, list) else []):
            m = re.search(r"codec ([^)]+)\)", S(nn(gp(e, "description"), "")))
            profiles.append({"index": gp(e, "index"), "name": gp(e, "name"), "available": gp(e, "available") != "no",
                             "codec": m.group(1) if m else None})
        out.append({
            "id": o.get("id"), "address": S(nn(p.get("api.bluez5.address"), "")),
            "label": sink["label"] if sink is not None and sink["label"] is not None else S(nn(p.get("device.description"), "Bluetooth device")),
            "profile": nn(gp(o, "info", "params", "Profile", 0, "name"), "off"),
            "profiles": profiles,
        })
    return out


def findBt(g, words):
    al = btDevices(g)
    if not al:
        raise Fail("no Bluetooth audio device is connected", EXIT.notFound)
    q = js_trim(" ".join(words)).lower()
    if not q:
        if len(al) == 1:
            return al[0]
        raise Fail(f'{len(al)} Bluetooth devices are connected; name one: {", ".join(S(d["label"]) for d in al)}', EXIT.usage)
    hits = [d for d in al if q in S(d["label"]).lower()]
    if len(hits) == 1:
        return hits[0]
    raise Fail(f'"{q}" matches {len(hits)} Bluetooth devices' if hits else f'no Bluetooth device called "{q}"', EXIT.usage if hits else EXIT.notFound)


# Switch a headset to a profile with rule 6 around it, then read back what really happened.
def switchProfile(bt, index):
    def sameDevice(d):
        return d["btAddress"] == bt["address"]
    result = guarded(sameDevice, lambda g: any(sameDevice(d) and d["isDefault"] for d in g["outputs"]),
                     lambda: must(run(["wpctl", "set-profile", S(bt["id"]), S(index)]), "wpctl set-profile"))
    after = readGraph()
    now = next((d for d in btDevices(after) if d["address"] == bt["address"]), None)
    sink = next((d for d in after["outputs"] if sameDevice(d)), None)
    return {"profile": now["profile"] if now is not None else "gone", "codec": nn(gp(sink, "codec"), None), "backAfterMs": result["backAfterMs"]}


def btOffers(bt):
    return [p for p in bt["profiles"] if S(p["name"]).startswith("a2dp-sink") and truthy(p["codec"]) and p["available"]]


def normCodec(x):
    return re.sub(r"[^a-z0-9]", "", x.lower())


def btCodecNow(bt):
    return nn(gp(next((p for p in bt["profiles"] if p["name"] == bt["profile"]), None), "codec"), None)


def btModeNow(bt):
    p = S(bt["profile"])
    return "music" if p.startswith("a2dp-sink") else "call" if p.startswith("headset-head-unit") else "off"


def _unique(values):
    out = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def btSetMode(bt, mode):
    exact = "a2dp-sink" if mode == "music" else "headset-head-unit"
    target = next((p for p in bt["profiles"] if p["available"] and p["name"] == exact), None) \
        or next((p for p in bt["profiles"] if p["available"] and S(p["name"]).startswith(exact)), None)
    if target is None:
        raise Fail(f'{S(bt["label"])} has no {mode} mode', EXIT.notFound)
    r = switchProfile(bt, target["index"])
    out = {"ok": S(r["profile"]).startswith(exact)}
    out.update(r)
    return out


def btSetCodec(bt, codec):
    match = next((p for p in btOffers(bt) if normCodec(p["codec"]) == normCodec(codec)), None)
    if match is None:
        raise Fail(f'{S(bt["label"])} does not offer {codec}; it offers {", ".join(S(c) for c in _unique(p["codec"] for p in btOffers(bt)))}', EXIT.notFound)
    r = switchProfile(bt, match["index"])
    out = {"ok": r["codec"] is not None and normCodec(S(r["codec"])) == normCodec(match["codec"])}
    out.update(r)
    return out


def smSetting(g, key):
    md = next((o for o in g["objects"] if gp(o, "type") == "PipeWire:Interface:Metadata" and gp(o, "props", "metadata.name") == "sm-settings"), None)
    entries = gp(md, "metadata")
    for x in (entries if isinstance(entries, list) else []):
        if gp(x, "key") == key:
            return S(x.get("value", UNDEF))
    return None


def verbBt(args):
    sub = args[0] if args else None
    rest = args[1:]
    g = readGraph()
    if sub == "auto":
        want = rest[0] if rest else None
        key = "bluetooth.autoswitch-to-headset-profile"
        if want is None:
            v = smSetting(g, key)
            return Out({"ok": True, "auto": v == "true"}, f'switch to call mode when an app records: {"on" if v == "true" else "off"}')
        if want not in ("on", "off"):
            raise Fail("usage: ballroom bt auto [on|off]", EXIT.usage)
        value = "true" if want == "on" else "false"
        must(run(["wpctl", "settings", "--save", key, value]), "wpctl settings")
        after = waitFor(lambda x: smSetting(x, key) == value)
        v = smSetting(after, key)
        if v != value:
            raise Fail("the setting did not take")
        return Out({"ok": True, "auto": v == "true"}, f"switch to call mode when an app records: {want}")
    if sub is None or sub == "list":
        al = btDevices(g)
        text = "\n".join(f'{S(d["label"])}  {S(d["profile"])}  codecs: {", ".join(S(c) for c in _unique(p["codec"] for p in d["profiles"] if S(p["name"]).startswith("a2dp-sink") and truthy(p["codec"])))}' for d in al)
        return Out({"ok": True, "devices": [{k: v for k, v in d.items() if k not in ("id", "address")} for d in al]}, text or "no Bluetooth audio device")
    if sub == "codec":
        def codecOf(bt, word):
            return next((p for p in btOffers(bt) if normCodec(p["codec"]) == normCodec(word)), None) if word else None
        # The last word is a codec if the device offers it; everything before it names the device.
        last = rest[-1] if rest else None
        bt = findBt(g, rest[:-1] if rest[:-1] else [])
        match = codecOf(bt, last)
        if match is None and len(rest) == 1:
            bt = findBt(g, rest)
            match = None
        if match is None:
            offers = _unique(p["codec"] for p in btOffers(bt))
            if len(rest) > 1:
                raise Fail(f'{S(bt["label"])} does not offer {last}; it offers {", ".join(S(c) for c in offers)}', EXIT.notFound)
            now = btCodecNow(bt)
            return Out({"ok": True, "device": bt["label"], "current": now, "codecs": offers},
                       f'{S(bt["label"])}: {S(now) if now is not None else "not in music mode"}; offers {", ".join(S(c) for c in offers)}')
        r = btSetCodec(bt, match["codec"])
        return Out({"ok": r["ok"], "device": bt["label"], "codec": r["codec"], "profile": r["profile"], "backAfterMs": r["backAfterMs"]},
                   f'{S(bt["label"])}: {S(r["codec"]) if r["codec"] is not None else "no codec"}{", back after " + S(r["backAfterMs"]) + " ms" if r["backAfterMs"] is not None else ", did not come back as the default"}')
    if sub == "mode":
        mode = rest[-1] if rest else None
        if mode != "music" and mode != "call":
            raise Fail("usage: ballroom bt mode [DEVICE] music|call", EXIT.usage)
        bt = findBt(g, rest[:-1])
        r = btSetMode(bt, mode)
        return Out({"ok": r["ok"], "device": bt["label"], "mode": mode, "profile": r["profile"], "codec": r["codec"], "backAfterMs": r["backAfterMs"]},
                   f'{S(bt["label"])}: {mode} mode, {S(r["codec"]) if r["codec"] is not None else "no codec"}')
    raise Fail(f"unknown: bt {S(sub) if sub is not None else 'undefined'}", EXIT.usage)


# ---------------------------------------------------------------- sound
# The equalizer is a PipeWire client of its own (ballroom-eq.service runs `pipewire -c eq.conf`), a filter-chain
# that WirePlumber puts in front of the default output as a smart filter. WirePlumber is never touched.
#
# Once running, the process is never stopped or rebuilt by a change: a sink that vanishes under a playing
# stream makes many players pause, and a rebuild plays the stream straight on the
# device for ~30 ms without the preamp. So the graph has one fixed shape with room for any preset (16 peaks,
# 4 low and 4 high shelves; a filter at 0 dB passes the sound unchanged), every change is a change of values,
# sent once because every real change of a builtin biquad resets it and clicks, and "off" sets all of them
# to neutral. Only `eq restart` (after an update) and `eq stop` end the process.
#
# The graph, per channel after a 2x2 matrix: copy -> mixer (balance, mono, swap) -> preamp -> filters. The
# preamp is a high shelf at 0 Hz, which is a plain gain. PipeWire's biquads follow the RBJ cookbook with Q for
# peaks and shelves alike (measured within 0.02 dB), so the curve computed here is the curve that is heard.
#
# A band: type ("peaking", "lowshelf" or "highshelf"), freq, gain, q. A preset: preamp ("auto" or dB), bands.
EQ_UNIT = "ballroom-eq.service"
EQ_NODE = "ballroom.eq"
# The unit reads %h/.config/ballroom/eq.conf; the path is spelled the same way here, whatever XDG says.
EQ_CONF = pjoin(HOME, ".config", "ballroom", "eq.conf")
SAMPLE_RATE = 48000
MAX_BANDS = 16
SLOT_COUNT = {"peaking": 16, "lowshelf": 4, "highshelf": 4}
SLOT_PREFIX = {"peaking": "p", "lowshelf": "l", "highshelf": "h"}
SHAPE = "fixed:16p4l4h"
LABEL = {"peaking": "bq_peaking", "lowshelf": "bq_lowshelf", "highshelf": "bq_highshelf"}
BAND_TYPES = ("peaking", "lowshelf", "highshelf")

# Ten slots: a low shelf, eight peaks, a high shelf. Built-in presets only move gains, so switching between them
# is a change of values and never a restart.
SLOTS = ([{"type": "lowshelf", "freq": 105, "gain": 0, "q": 0.7}]
         + [{"type": "peaking", "freq": f, "gain": 0, "q": 1.0} for f in (63, 125, 250, 500, 1000, 2000, 4000, 8000)]
         + [{"type": "highshelf", "freq": 12000, "gain": 0, "q": 0.7}])


def withGains(gains):
    return [dict(b, gain=gains.get(i, 0)) for i, b in enumerate(SLOTS)]


BUILTIN_PRESETS = {
    "Flat": {"preamp": "auto", "bands": withGains({})},
    "Bass": {"preamp": "auto", "bands": withGains({0: 6, 1: 2})},
    "Treble": {"preamp": "auto", "bands": withGains({8: 2, 9: 4})},
    "Vocal": {"preamp": "auto", "bands": withGains({0: -2, 5: 1.5, 6: 3, 7: 1.5})},
    "Loudness": {"preamp": "auto", "bands": withGains({0: 5, 1: 2, 8: 1, 9: 3})},
}

DEFAULT_SOUND = {"schemaVersion": 1, "enabled": False, "balance": 0, "mono": False, "swap": False}


def loadSound():
    v = loadJson("sound.json", DEFAULT_SOUND, lambda x: isinstance(x.get("enabled"), bool))
    out = dict(DEFAULT_SOUND)
    out.update(v)
    b = js_number(v.get("balance", UNDEF))
    out["balance"] = js_max(-1, js_min(1, b if truthy(b) else 0))
    return out


def validBand(b):
    return (isObject(b) and b.get("type") in BAND_TYPES
            and all(is_num(b.get(k)) and math.isfinite(b.get(k)) for k in ("freq", "gain", "q")))


def loadPresets():
    return loadJson("presets.json", {"schemaVersion": 1, "presets": {}},
                    lambda v: isObject(v.get("presets")) and all(isObject(p) and isinstance(p.get("bands"), list) and all(validBand(b) for b in p["bands"])
                                                                for p in v["presets"].values()))


def allPresets():
    out = dict(BUILTIN_PRESETS)
    out.update(loadPresets()["presets"])
    return out


def clampBand(b):
    def num(v, fallback):
        return v if is_num(v) and math.isfinite(v) else fallback
    return {"type": b["type"], "freq": js_round(js_max(20, js_min(20000, num(b.get("freq"), 1000)))),
            "gain": js_round(js_max(-24, js_min(24, num(b.get("gain"), 0))) * 10) / 10,
            "q": js_round(js_max(0.1, js_min(10, num(b.get("q"), 1))) * 100) / 100}


def biquad(b):
    A = math.pow(10, b["gain"] / 40)
    w0 = 2 * math.pi * b["freq"] / SAMPLE_RATE
    c = math.cos(w0)
    alpha = math.sin(w0) / (2 * b["q"])
    if b["type"] == "peaking":
        return [1 + alpha * A, -2 * c, 1 - alpha * A, 1 + alpha / A, -2 * c, 1 - alpha / A]
    sq = 2 * math.sqrt(A) * alpha
    if b["type"] == "lowshelf":
        return [A * ((A + 1) - (A - 1) * c + sq), 2 * A * ((A - 1) - (A + 1) * c), A * ((A + 1) - (A - 1) * c - sq),
                (A + 1) + (A - 1) * c + sq, -2 * ((A - 1) + (A + 1) * c), (A + 1) + (A - 1) * c - sq]
    return [A * ((A + 1) + (A - 1) * c + sq), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sq),
            (A + 1) - (A - 1) * c + sq, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sq]


def bandsDb(bands, f):
    w = 2 * math.pi * f / SAMPLE_RATE
    total = 0
    for b in bands:
        if b["gain"] == 0:
            continue
        k = biquad(b)

        def mag(x0, x1, x2):
            return math.hypot(x0 + x1 * math.cos(w) + x2 * math.cos(2 * w), x1 * math.sin(w) + x2 * math.sin(2 * w))
        total += 20 * math.log10(mag(k[0], k[1], k[2]) / mag(k[3], k[4], k[5]))
    return total


CURVE_FREQS = [js_round(20 * math.pow(1000, i / 63) * 10) / 10 for i in range(64)]


# Auto headroom: the curve's highest point, never above 0 dB after the preamp.
def autoPreamp(bands):
    peak = 0
    for i in range(241):
        peak = js_max(peak, bandsDb(bands, 20 * math.pow(1000, i / 240)))
    # Never below -24 dB: a preset can stack bands, and a preamp without a floor would become the jump it is
    # there to prevent when the equalizer goes off.
    v = js_max(-24, -js_ceil(peak * 10) / 10)
    return v if truthy(v) else 0


# A plan: device, presetName, preset, bands, preamp, matrix, bypass.
def soundPlan(g, sound=None):
    if sound is None:
        sound = loadSound()
    df = next((d for d in g["outputs"] if d["isDefault"] and not d["filter"]), None)
    presets = allPresets()
    wanted = gp(loadDevices()["devices"].get(df["name"]), "eq") if df is not None else None
    presetName = wanted if isinstance(wanted, str) and wanted and truthy(presets.get(wanted)) else "Flat"
    preset = presets[presetName]
    bands = [clampBand(b) for b in preset["bands"][:MAX_BANDS]]
    while len(bands) < len(SLOTS):
        bands.append({"type": "peaking", "freq": 1000, "gain": 0, "q": 1})
    pre = preset.get("preamp", UNDEF)
    preamp = autoPreamp(bands) if pre == "auto" else js_max(-24, js_min(6, js_number(pre)))
    # Balance takes from one side only; mono sums at half each; swap crosses. [LL, LR, RL, RR]: out channel, in channel.
    bal = sound["balance"]
    l, r = js_min(1, 1 - bal), js_min(1, 1 + bal)
    base = [0.5, 0.5, 0.5, 0.5] if truthy(sound.get("mono")) else [0, 1, 1, 0] if truthy(sound.get("swap")) else [1, 0, 0, 1]
    matrix = [js_round(x * 1000) / 1000 for x in (base[0] * l, base[1] * l, base[2] * r, base[3] * r)]
    return {"device": df["name"] if df is not None else None, "presetName": presetName, "preset": preset, "bands": bands,
            "preamp": preamp, "matrix": matrix, "bypass": not truthy(sound["enabled"])}


# A preset fits the fixed graph when no kind of filter needs more slots than there are.
def checkFits(bands):
    for t in SLOT_COUNT:
        n = len([b for b in bands if b["type"] == t and b["gain"] != 0])
        if n > SLOT_COUNT[t]:
            raise Fail(f"{n} {t} filters; the equalizer has room for {SLOT_COUNT[t]}", EXIT.usage)


# Every control of the fixed graph. Bands fill the slots of their kind in order; a slot without a band, and
# every slot when the equalizer is off, stands at 0 dB. Off also means preamp 0 and a straight matrix.
def slotBands(plan):
    out = []
    used = {"peaking": [], "lowshelf": [], "highshelf": []}
    if not plan["bypass"]:
        for b in plan["bands"]:
            if b["gain"] != 0 and len(used[b["type"]]) < SLOT_COUNT[b["type"]]:
                used[b["type"]].append(b)
    for t in ("lowshelf", "peaking", "highshelf"):
        for i in range(SLOT_COUNT[t]):
            neutral = {"type": t, "freq": 100 if t == "lowshelf" else 10000 if t == "highshelf" else 1000, "gain": 0, "q": 1 if t == "peaking" else 0.7}
            out.append({"name": f"{SLOT_PREFIX[t]}{i}", "type": t, "band": used[t][i] if i < len(used[t]) else neutral})
    return out


def eqControls(plan):
    m = [1, 0, 0, 1] if plan["bypass"] else plan["matrix"]
    pre = 0 if plan["bypass"] else plan["preamp"]
    c = {"mixL:Gain 1": m[0], "mixL:Gain 2": m[1], "mixR:Gain 1": m[2], "mixR:Gain 2": m[3], "preL:Gain": pre, "preR:Gain": pre}
    # A slot at 0 dB keeps the frequency and Q it has: changing those at 0 dB would reset a filter for nothing.
    for s in slotBands(plan):
        name, band = s["name"], s["band"]
        for side in ("L", "R"):
            c[f"{side}_{name}:Gain"] = band["gain"]
            if band["gain"] != 0:
                c[f"{side}_{name}:Freq"] = band["freq"]
                c[f"{side}_{name}:Q"] = band["q"]
    return c


def num(x):
    return to_fixed(x, 1) if is_int(x) else S(x)


def eqConfText(plan):
    c = eqControls(plan)

    def node(name, label, keys):
        pairs = " ".join('"' + k + '" = ' + num(c[name + ":" + k]) for k in keys)
        control = " control = { " + pairs + " }" if keys else ""
        return f"          {{ type = builtin name = {name} label = {label}{control} }}"
    nodes = [node("inL", "copy", []), node("inR", "copy", []),
             node("mixL", "mixer", ["Gain 1", "Gain 2"]), node("mixR", "mixer", ["Gain 1", "Gain 2"]),
             f'          {{ type = builtin name = preL label = bq_highshelf control = {{ "Freq" = 0.0 "Q" = 1.0 "Gain" = {num(plan["preamp"])} }} }}',
             f'          {{ type = builtin name = preR label = bq_highshelf control = {{ "Freq" = 0.0 "Q" = 1.0 "Gain" = {num(plan["preamp"])} }} }}']
    links = ['{ output = "inL:Out" input = "mixL:In 1" }', '{ output = "inR:Out" input = "mixL:In 2" }',
             '{ output = "inL:Out" input = "mixR:In 1" }', '{ output = "inR:Out" input = "mixR:In 2" }',
             '{ output = "mixL:Out" input = "preL:In" }', '{ output = "mixR:Out" input = "preR:In" }']
    slots = slotBands(plan)
    for side in ("L", "R"):
        for i, s in enumerate(slots):
            name, typ, band = s["name"], s["type"], s["band"]
            nodes.append(f'          {{ type = builtin name = {side}_{name} label = {LABEL[typ]} control = {{ "Freq" = {num(band["freq"])} "Q" = {num(band["q"])} "Gain" = {num(band["gain"])} }} }}')
            src = f"pre{side}" if i == 0 else f'{side}_{slots[i - 1]["name"]}'
            links.append(f'{{ output = "{src}:Out" input = "{side}_{name}:In" }}')
    last = slots[-1]["name"]
    nl = "\n"
    links_text = "\n          ".join(links)
    return f"""# Written by ballroom. Every change here is overwritten; use `ballroom eq`.
# shape: {SHAPE}
context.modules = [
  {{ name = libpipewire-module-rt flags = [ ifexists nofail ] }}
  {{ name = libpipewire-module-protocol-native }}
  {{ name = libpipewire-module-client-node }}
  {{ name = libpipewire-module-adapter }}
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.name = "{EQ_NODE}"
      node.description = "Ballroom EQ"
      filter.graph = {{
        nodes = [
{nl.join(nodes)}
        ]
        links = [
          {links_text}
        ]
        inputs = [ "inL:In" "inR:In" ]
        outputs = [ "L_{last}:Out" "R_{last}:Out" ]
      }}
      audio.channels = 2
      audio.position = [ FL FR ]
      capture.props = {{ node.name = "{EQ_NODE}" media.class = Audio/Sink filter.smart = true filter.smart.name = "{EQ_NODE}" }}
      playback.props = {{ node.name = "{EQ_NODE}.output" node.passive = true media.role = "DSP" }}
    }}
  }}
]
"""


def eqNode(g):
    return next((o for o in g["objects"] if gp(o, "type") == "PipeWire:Interface:Node" and gp(o, "info", "props", "node.name") == EQ_NODE), None)


def eqLiveControls(g):
    n = eqNode(g)
    if n is None:
        return None
    lst = gp(n, "info", "params", "Props")
    props = next((p for p in (lst if isinstance(lst, list) else [])
                  if isinstance(gp(p, "params"), list) and any(isinstance(x, str) and ":" in x for x in p["params"])), None)
    if props is None:
        return {}
    out = {}
    params = props["params"]
    i = 0
    while i + 1 < len(params):
        out[S(params[i])] = js_number(params[i + 1])
        i += 2
    return out


def foreignFilters(g):
    out = []
    for o in g["objects"]:
        if gp(o, "type") != "PipeWire:Interface:Node":
            continue
        p = _props(o)
        if S(p.get("media.class", UNDEF)) == "Audio/Sink" and (p.get("filter.smart") is True or p.get("filter.smart") == "true") and p.get("node.name") != EQ_NODE:
            out.append(S(p.get("node.name", UNDEF)))
    return out


def unit(verb):
    return run(["systemctl", "--user", verb, EQ_UNIT], 5000)


def shapeOfConf():
    try:
        m = re.search("(?:^|(?<=[\r\u2028\u2029]))# shape: ([^\n\r\u2028\u2029]*)(?=[\n\r\u2028\u2029]|\\Z)", read_text(EQ_CONF), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


# The two user services live beside this file, as the plugin ships them, and are put in place by the command
# itself: a plugin added from the store has nobody who copies them. Before a unit is started, the copy in
# ~/.config/systemd/user is made to say exactly what the shipped one says, but only a copy that is Ballroom's:
#   - none there: the shipped one is written;
#   - a link there (masked with systemctl mask, or linked by hand): not ours, left alone, the start is refused;
#   - a file without Description=Ballroom in its first five lines: someone else's unit under our name, left alone,
#     the start is refused;
#   - our own file with other content: replaced whole (a temporary file and a rename, so systemd never reads half
#     of it).
# After a write systemd is told to read it again. A marker in the runtime directory stands until that reload
# succeeded, so a reload that failed is tried again by the next start even though the file already matches.
# With no shipped file beside the command, an installed copy of ours is used as it is; with neither, the start is
# refused and says why.
# All of it, from the first look to the marker's removal, runs under a lock of its own (unit-lock in the runtime
# directory, not the writers' lock: this runs inside writers too, and the stage starts without it). Without it
# two starters interleave: one with the old file clears the marker while the other is between marker and rename,
# and the new file goes in without a reload. Right before the rename the file is looked at again; if it is no
# longer what was judged (a mask or a link put there meanwhile), nothing is replaced. What is left is the
# instant between that look and the rename itself, which no file system call closes.
UNIT_DIR = pjoin(HOME, ".config", "systemd", "user")


def unitIsOurs(data):
    return any(l.strip().startswith("Description=Ballroom") for l in data.decode("utf-8", "replace").split("\n")[:5])


def _unitLock():
    ensureDir(RUNTIME)
    fd = os.open(pjoin(RUNTIME, "unit-lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    # Longer than the writers' wait: the holder may be in a daemon-reload, which is given 10 s.
    until = now_ms() + 15000
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            pass
        except OSError:
            os.close(fd)
            raise
        if now_ms() > until:
            os.close(fd)
            raise Fail("another ballroom is putting the services in place; try again", EXIT.failed)
        sleep_ms(20)


def ensureUnit(name):
    fd = _unitLock()
    try:
        sweepTemps(UNIT_DIR, r"ballroom-(eq|stage)\.service\.tmp\.[0-9a-f]{16}")
        _ensureUnit(name)
    finally:
        os.close(fd)


def _benchPause():
    """Bench only: holds here until the bench lets go, so that a scenario can act in the gap."""
    gate = ENV.get("BALLROOM_BENCH_UNIT_PAUSE") if BENCH else None
    if not gate:
        return
    with open(gate + ".ready", "w"):
        pass
    until = now_ms() + 15000
    while os.path.exists(gate) and now_ms() < until:
        sleep_ms(20)


def _ensureUnit(name):
    shipped = pjoin(os.path.dirname(os.path.realpath(__file__)), name)
    installed = pjoin(UNIT_DIR, name)
    where = f"~/.config/systemd/user/{name}"
    try:
        with open(shipped, "rb") as f:
            want = f.read()
    except OSError:
        want = None
    try:
        st = os.lstat(installed)
    except FileNotFoundError:
        st = None
    except OSError:
        raise Fail(f"{where} cannot be read; Ballroom does not start it")
    have = None
    if st is not None:
        if _stat.S_ISLNK(st.st_mode):
            target = ""
            try:
                target = os.readlink(installed)
            except OSError:
                pass
            if target == "/dev/null":
                raise Fail(f"{name} is masked; Ballroom leaves it so. systemctl --user unmask {name} lets it start")
            raise Fail(f"{where} is a link, not Ballroom's file; Ballroom leaves it alone. Remove the link to let Ballroom put its own in place")
        if not _stat.S_ISREG(st.st_mode):
            raise Fail(f"{where} is not a file; Ballroom leaves it alone")
        try:
            fd = os.open(installed, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                with os.fdopen(fd, "rb") as f:
                    fd = None
                    have = f.read(1024 * 1024)
            finally:
                if fd is not None:
                    os.close(fd)
        except OSError:
            raise Fail(f"{where} cannot be read; Ballroom does not start it")
        if not unitIsOurs(have):
            raise Fail(f"{where} is not Ballroom's (no Description=Ballroom at its top); Ballroom leaves it alone. Move it away to let Ballroom put its own in place")
    if want is None and have is None:
        raise Fail(f"{name} is neither beside the ballroom command nor in ~/.config/systemd/user; reinstall Ballroom")
    marker = pjoin(RUNTIME, f"reload-{name}")
    wrote = False
    if want is not None and have != want:
        ensureDir(RUNTIME)
        seen = None if st is None else (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns)

        def unchanged():
            _benchPause()
            try:
                now = os.lstat(installed)
                now = (now.st_dev, now.st_ino, now.st_mode, now.st_size, now.st_mtime_ns)
            except FileNotFoundError:
                now = None
            if now != seen:
                raise Fail(f"{where} changed while Ballroom was putting its own in place; Ballroom leaves it alone. Start it again to have another look")
        try:
            # The marker first: if anything after it fails, the next start still reloads.
            write_atomic(marker, "", 0o600)
            _mkdirs(UNIT_DIR, 0o755)
            write_atomic(installed, want, 0o644, before=unchanged)
            wrote = True
        except OSError:
            raise Fail(f"{name} could not be written to ~/.config/systemd/user")
    if not wrote and not os.path.exists(marker):
        return
    r = run(["systemctl", "--user", "daemon-reload"], 10000)
    if r.rc == 127:
        return  # without systemctl the start that follows says so itself
    if r.rc != 0:
        reason = "did not answer" if r.timedOut else f"failed with exit {r.rc}"
        raise Fail(f"{name} was put in place, but systemctl --user daemon-reload {reason}; the next start tries again")
    rm_force(marker)


# Brings the equalizer in line with sound.json, presets and the default device. Returns what it did:
# {action: "none" | "started" | "stopped" | "rebuilt" | "live", running, pending, plan}.
# Rule 1: the answer is read from the graph afterwards. A filter that sleeps (nothing plays) takes new values
# when sound comes back and shows them only then (measured); that is reported as pending, not as done.
def eqSync(restart=False, force=False, stop=False):
    g = readGraph()
    sound = loadSound()
    plan = soundPlan(g, sound)
    ensureDir(RUNTIME)
    if stop:
        if eqNode(g) is None and unit("is-active").rc != 0:
            return {"action": "none", "running": False, "pending": False, "plan": plan}
        must(unit("stop"), "systemctl --user stop")
        g = waitFor(lambda x: eqNode(x) is None, 3000)
        rm_force(pjoin(RUNTIME, "eq-live.json"))
        if eqNode(g) is not None:
            raise Fail("the equalizer did not stop")
        return {"action": "stopped", "running": False, "pending": False, "plan": plan}
    running = eqNode(g) is not None
    # Off and not running: nothing to do; an equalizer is only started to be used.
    if not truthy(sound["enabled"]) and not running:
        return {"action": "none", "running": False, "pending": False, "plan": plan}
    if not running or restart or shapeOfConf() != SHAPE:
        # A start that failed is not retried on every change in the graph: apply runs on each of them, and each
        # try waits seconds for a filter that will not come. A verb the user types always tries.
        failedFile = pjoin(RUNTIME, "eq-failed.json")
        if not running and not force:
            try:
                f = jparse(read_text(failedFile))
                since = now_ms() - js_number(gp(f, "at"))
                if since < 30000:
                    raise Fail(f"the equalizer did not start {js_round(since / 1000)} s ago; ballroom eq restart tries again now")
            except Fail:
                raise
            except Exception:
                pass

        def failed(message):
            writeRuntime("eq-failed.json", jdump({"at": now_ms(), "message": message}) + "\n")
            return Fail(message)
        rm_force(failedFile)
        try:
            ensureUnit(EQ_UNIT)
        except Fail as e:
            raise failed(e.message)
        ensureDir(pjoin(HOME, ".config", "ballroom"))
        # The configuration that worked last is kept beside the new one until the new one has loaded; a start that
        # fails puts it back, so there is always a file the user can return to.
        lastGood = f"{EQ_CONF}.last-good"
        if os.path.exists(EQ_CONF):
            with open(EQ_CONF, "rb") as f:
                write_atomic(lastGood, f.read(), 0o600)
        write_atomic(EQ_CONF, eqConfText(plan), 0o600)

        def rollBack():
            if os.path.exists(lastGood):
                os.rename(lastGood, EQ_CONF)
        r = unit("restart")
        if r.rc == 127:
            rollBack()
            raise Fail("systemctl is not installed; the equalizer runs as a user service")
        if r.rc != 0:
            rollBack()
            raise failed(f"{EQ_UNIT} did not start; journalctl --user -u {EQ_UNIT} says why")
        g = waitFor(lambda x: eqNode(x) is not None and eqLiveControls(x) is not None, 4000)
        if eqNode(g) is None:
            rollBack()
            raise failed(f"{EQ_UNIT} started, but its filter did not appear; journalctl --user -u {EQ_UNIT} says why")
        rm_force(lastGood)
        writeRuntime("eq-live.json", jdump({"preamp": 0 if plan["bypass"] else plan["preamp"], "device": plan["device"], "at": now_ms()}) + "\n")
        return {"action": "rebuilt" if running else "started", "running": True, "pending": False, "plan": plan}
    want = eqControls(plan)
    have = nn(eqLiveControls(g), {})
    changed = [(k, v) for k, v in want.items() if k not in have or abs(have[k] - v) > 0.0005]
    writeRuntime("eq-live.json", jdump({"preamp": 0 if plan["bypass"] else plan["preamp"], "device": plan["device"], "at": now_ms()}) + "\n")
    if not changed:
        return {"action": "none", "running": True, "pending": False, "plan": plan}
    # All changed controls in one call: one click, not one per band.
    node = eqNode(g)
    must(run(["pw-cli", "set-param", S(node.get("id")), "Props", f'{{ params = [ {" ".join(f"{chr(34)}{k}{chr(34)} {num(v)}" for k, v in changed)} ] }}']), "pw-cli set-param")
    if gp(node, "info", "state") == "suspended":
        return {"action": "live", "running": True, "pending": True, "plan": plan}

    def took(x):
        c = nn(eqLiveControls(x), {})
        return all(k in c and abs(c[k] - v) < 0.01 for k, v in changed)
    g = waitFor(took, 2000)
    c = nn(eqLiveControls(g), {})
    missed = [(k, v) for k, v in changed if k not in c or abs(c[k] - v) >= 0.01]
    if missed and gp(eqNode(g), "info", "state") == "suspended":
        return {"action": "live", "running": True, "pending": True, "plan": plan}
    if missed:
        detail = (": " + " ".join(f"{k}={S(v)}/{S(c.get(k, UNDEF))}" for k, v in missed)) if ENV.get("BALLROOM_DEBUG") else ""
        raise Fail(f"the equalizer did not take {len(missed)} of {len(changed)} values{detail}")
    return {"action": "live", "running": True, "pending": False, "plan": plan}


# The equalizer's preamp goes with its process. If that process dies, the sound plays on the device without it,
# louder by the preamp; apply takes the device down by that much until the equalizer is back, so a failure never makes it louder.
# The preamp of a running equalizer holds the sound down by that much. When the preamp goes away (the filter
# died, or the user turned the equalizer off), the default output is brought down by the same amount so the
# loudness stays, and the level that was set is written down next to the level it came from. When the preamp
# is back, the output is raised again only if it still stands exactly where it was put: anything the user
# changed meanwhile stays, and the compensation is dropped and named. The raise never goes above the level it
# came from, nor above the device's cap, so the return of the equalizer can never be a jump.
def COMP_FILE():
    return pjoin(RUNTIME, "eq-compensation.json")


def loadCompensation():
    try:
        c = jparse(read_text(COMP_FILE()))
        if isinstance(gp(c, "device"), str) and all(is_num(c.get(k)) for k in ("db", "from", "to")):
            return c
        return None
    except Exception:
        return None


def compensateDown(d, db, changes, why):
    to = js_round(d["volume"] * cbrt(math.pow(10, db / 20)) * 1000) / 1000
    setVolume(d["name"], to)
    after = find_by_name(readGraph()["outputs"], d["name"])
    writeRuntime("eq-compensation.json", jdump({"device": d["name"], "db": db, "from": d["volume"], "to": nn(gp(after, "volume"), to)}) + "\n")
    changes.append(f'{d["name"]}: {S(db)} dB {why}')


def compensateBack(g, changes):
    comp = loadCompensation()
    if comp is None:
        return
    rm_force(COMP_FILE())
    d = find_by_name(g["outputs"], comp["device"])
    if d is None:
        changes.append(f'{comp["device"]}: not present, its level stays where it is')
        return
    if abs(d["volume"] - comp["to"]) > 0.005:
        changes.append(f'{d["name"]}: its level was changed meanwhile and stays at {percent(d["volume"])} %')
        return
    target = js_min(comp["from"], nn(d["cap"], comp["from"]))
    if target <= d["volume"]:
        return
    setVolume(d["name"], target)
    changes.append(f'{d["name"]}: back to {percent(target)} %, the equalizer is back')


def eqGuard(g, changes):
    sound = loadSound()
    live = None
    try:
        live = jparse(read_text(pjoin(RUNTIME, "eq-live.json")))
    except Exception:
        pass  # the equalizer never ran in this login
    present = eqNode(g) is not None
    pre = gp(live, "preamp")
    if truthy(sound["enabled"]) and not present and truthy(live) and is_num(pre) and pre < 0 and loadCompensation() is None:
        d = next((x for x in g["outputs"] if x["isDefault"] and not x["filter"]), None)
        if d is not None:
            compensateDown(d, pre, changes, "while the equalizer is gone")
    if present and truthy(sound["enabled"]):
        compensateBack(g, changes)


# AutoEQ's ParametricEQ.txt: "Preamp: -6.2 dB" and "Filter 1: ON PK Fc 105 Hz Gain -2.1 dB Q 0.70".
def parseAutoEq(text):
    bands = []
    preamp = "auto"
    for line in re.split(r"\r?\n", text):
        pre = re.match(r"\s*Preamp:\s*(-?[0-9.]+)\s*dB", line, re.I)
        if pre:
            preamp = js_number(pre.group(1))
            continue
        m = re.match(r"\s*Filter\s*[0-9]*:\s*(ON|OFF)\s+(PK|PEQ|LSC|LS|LSQ|HSC|HS|HSQ)\s+Fc\s+([0-9.]+)\s*Hz(?:\s+Gain\s+(-?[0-9.]+)\s*dB)?(?:\s+Q\s+([0-9.]+))?", line, re.I)
        if not m:
            continue
        if m.group(1).upper() == "OFF":
            continue
        kind = m.group(2).upper()
        typ = "lowshelf" if kind.startswith("L") else "highshelf" if kind.startswith("H") else "peaking"
        bands.append(clampBand({"type": typ, "freq": js_number(m.group(3)), "gain": js_number(nn(m.group(4), 0)),
                                "q": js_number(nn(m.group(5), 1 if typ == "peaking" else 0.7))}))
    if not bands:
        raise Fail("no filter lines found; expected AutoEQ's ParametricEQ.txt", EXIT.usage)
    if len(bands) > MAX_BANDS:
        raise Fail(f"{len(bands)} filters; Ballroom takes up to {MAX_BANDS}", EXIT.usage)
    checkFits(bands)
    return {"preamp": preamp, "bands": bands}


def eqReport(plan, running, g):
    presets = allPresets()
    sound = loadSound()
    return {
        "enabled": sound["enabled"], "running": running, "device": plan["device"], "preset": plan["presetName"], "maxBands": SLOT_COUNT,
        "builtin": plan["presetName"] in BUILTIN_PRESETS and plan["presetName"] not in loadPresets()["presets"],
        "presets": list(presets.keys()), "preamp": plan["preamp"], "preampMode": "auto" if plan["preset"].get("preamp") == "auto" else "fixed",
        "bands": plan["bands"], "balance": sound["balance"], "mono": sound["mono"], "swap": sound["swap"],
        "foreign": foreignFilters(g),
        "curve": [{"f": f, "db": js_round((bandsDb(plan["bands"], f) + plan["preamp"]) * 100) / 100} for f in CURVE_FREQS],
    }


# The device a preset change is for: the named one, or the default output.
def eqTarget(g, words):
    return findDevice(g, "sink", " ".join(words))


# A built-in preset is never edited in place: the first edit copies it to "Custom" and gives that to the device.
def editablePreset(g, device):
    store = loadPresets()
    al = allPresets()
    current = gp(loadDevices()["devices"].get(device["name"]), "eq")
    name = current if isinstance(current, str) and truthy(al.get(current)) else "Flat"
    if name not in store["presets"]:
        # A built-in preset is never edited in place: it is copied under a free name, and a copy that another
        # device already uses is not overwritten.
        cp = "Custom"
        n = 2
        while cp in store["presets"]:
            cp = f"Custom {n}"
            n += 1
        store["presets"][cp] = jparse(jdump(al[name]))
        name = cp
        devices = loadDevices()
        devices["devices"].setdefault(device["name"], {})["eq"] = name
        saveJson("devices.json", devices)
    return name, store


def verbEq(args):
    reading = not args or args[0] == "show" or (args[0] == "preset" and (args[1] if len(args) > 1 else "list") == "list")
    return eqNow(args) if reading else withLock(lambda: eqNow(args))


def _is_finite_text(x):
    v = js_number(x)
    return v == v and v not in (math.inf, -math.inf)


def eqNow(args):
    sub = args[0] if args else None
    rest = args[1:]

    def say(r, text, extra=None):
        g = readGraph()
        js = {"ok": True, "action": r["action"], "pending": r["pending"]}
        js.update(eqReport(r["plan"], r["running"], g))
        js.update(extra or {})
        return Out(js, text + (" (the filter sleeps while nothing plays and takes it when sound comes)" if r["pending"] else ""),
                   {"icon": "volume-high", "message": f'Equalizer on: {r["plan"]["presetName"]}' if truthy(loadSound()["enabled"]) else "Equalizer off"})

    def saveSound(patch):
        s2 = loadSound()
        s2.update(patch)
        saveJson("sound.json", s2)

    if sub is None or sub == "show":
        g = readGraph()
        plan = soundPlan(g)
        rep = eqReport(plan, eqNode(g) is not None, g)
        state = ("on" if rep["running"] else "on, but not running") if truthy(rep["enabled"]) else "off"
        dev = f', for {S(gp(find_by_name(g["outputs"], plan["device"]), "label") if find_by_name(g["outputs"], plan["device"]) is not None else UNDEF)}' if plan["device"] is not None else ""
        lines = [f'EQ {state}{dev}: {plan["presetName"]}',
                 f'preamp {S(plan["preamp"])} dB ({rep["preampMode"]}){", balance " + S(rep["balance"]) if truthy(rep["balance"]) else ""}{", mono" if truthy(rep["mono"]) else ""}{", swapped" if truthy(rep["swap"]) else ""}']
        for i, b in enumerate(plan["bands"]):
            lines.append(f'  {pad_start(str(i + 1), 2)}  {pad_end(b["type"], 9)} {pad_start(S(b["freq"]), 5)} Hz  {("+" if b["gain"] >= 0 else "") + to_fixed(b["gain"], 1)} dB  Q {to_fixed(b["q"], 2)}')
        lines += [f"warning: another filter sits in front of the output: {f}" for f in rep["foreign"]]
        js = {"ok": True}
        js.update(rep)
        return Out(js, "\n".join(lines))
    if sub == "on":
        saveSound({"enabled": True})
        r = eqSync(force=True)
        # The output was brought down when the equalizer went off; with the preamp back it comes back, if untouched.
        changes = []
        if r["running"]:
            compensateBack(readGraph(), changes)
        return say(r, f'EQ on ({r["action"]}): {r["plan"]["presetName"]}{"; " + "; ".join(changes) if changes else ""}', {"changes": changes})
    if sub == "off":
        before = soundPlan(readGraph())
        wasOn = truthy(loadSound()["enabled"])
        # Without the preamp the output would be louder by that much at once: the device is brought down first,
        # and only then does the filter go neutral, so there is no moment in between that is louder.
        changes = []
        if wasOn and before["preamp"] < 0 and loadCompensation() is None:
            d = default_of(readGraph()["outputs"])
            if d is not None:
                compensateDown(d, before["preamp"], changes, "so the loudness stays the same with the equalizer off")
        saveSound({"enabled": False})
        r = eqSync()
        return say(r, f'EQ off: the filter passes the sound unchanged{" and keeps running, so nothing that plays is interrupted" if r["running"] else ""}{"; " + "; ".join(changes) if changes else ""}', {"changes": changes})
    if sub == "stop":
        # The preamp goes with the process: the device comes down by it first, as when the equalizer goes off, so
        # stopping is never louder. With the equalizer still on, the next apply starts it again and brings it back.
        changes = []
        g0 = readGraph()
        pre = soundPlan(g0)["preamp"]
        if eqNode(g0) is not None and truthy(loadSound()["enabled"]) and pre < 0 and loadCompensation() is None:
            d = default_of(g0["outputs"])
            if d is not None:
                compensateDown(d, pre, changes, "so the loudness stays the same without the equalizer")
        r = eqSync(stop=True)
        return say(r, f'{"EQ process stopped; players on it may pause" if r["action"] == "stopped" else "EQ process was not running"}{"; " + "; ".join(changes) if changes else ""}', {"changes": changes})
    if sub == "restart":
        r = eqSync(restart=True, force=True)
        return say(r, f'EQ {r["action"]}')
    if sub == "sync":
        r = eqSync(force=True)
        return say(r, f'EQ {r["action"]}')
    if sub == "preset":
        op = rest[0] if rest else None
        more = rest[1:]
        if not op or op == "list":
            g = readGraph()
            plan = soundPlan(g)
            store = loadPresets()["presets"]
            names = list(allPresets().keys())
            return Out({"ok": True, "presets": [{"name": n, "builtin": n not in store and n in BUILTIN_PRESETS, "current": n == plan["presetName"]} for n in names]},
                       "\n".join(f'{"*" if n == plan["presetName"] else " "} {n}{"" if n in store else "  (built in)"}' for n in names))
        if op == "use":
            name = more[0] if more else None
            dev = more[1:]
            if not name or name not in allPresets():
                raise Fail(f'no preset called "{nn(name, "")}"; ballroom eq preset list', EXIT.notFound)
            g = readGraph()
            d = eqTarget(g, dev)
            devices = loadDevices()
            devices["devices"].setdefault(d["name"], {})["eq"] = name
            saveJson("devices.json", devices)
            r = eqSync()
            return say(r, f'{S(d["label"])}: {name}{"" if d["isDefault"] else " (applies when it is the default)"}')
        if op == "save":
            name = cut(js_trim(clean(" ".join(more))), 40)
            if not name or name in BUILTIN_PRESETS:
                raise Fail("usage: ballroom eq preset save NAME (not the name of a built-in preset)", EXIT.usage)
            g = readGraph()
            plan = soundPlan(g)
            store = loadPresets()
            store["presets"][name] = {"preamp": plan["preset"].get("preamp", UNDEF), "bands": plan["bands"]}
            saveJson("presets.json", store)
            if plan["device"] is not None and plan["device"] != "":
                devices = loadDevices()
                devices["devices"].setdefault(plan["device"], {})["eq"] = name
                saveJson("devices.json", devices)
            return Out({"ok": True, "saved": name}, f"saved as {name}")
        if op == "rm":
            name = " ".join(more)
            store = loadPresets()
            if name not in store["presets"]:
                raise Fail(f"{name} is built in" if name in BUILTIN_PRESETS else f'no preset called "{name}"', EXIT.notFound)
            del store["presets"][name]
            saveJson("presets.json", store)
            devices = loadDevices()
            for d in devices["devices"].values():
                if d.get("eq") == name:
                    del d["eq"]
            saveJson("devices.json", devices)
            r = eqSync()
            return say(r, f"removed {name}")
        raise Fail("usage: ballroom eq preset list|use NAME [DEVICE]|save NAME|rm NAME", EXIT.usage)
    if sub == "import":
        f = rest[0] if rest else None
        if not f:
            raise Fail("usage: ballroom eq import FILE [NAME]", EXIT.usage)
        try:
            text = read_text(f)
        except OSError:
            raise Fail(f"cannot read {f}", EXIT.notFound)
        preset = parseAutoEq(text)
        base = " ".join(rest[1:]) or re.sub(r" ParametricEQ\Z", "", re.sub(r"\.txt\Z", "", f.split("/")[-1], flags=re.I), flags=re.I)
        name = cut(js_trim(clean(base)), 40)
        if name in BUILTIN_PRESETS:
            raise Fail(f"{name} is the name of a built-in preset", EXIT.usage)
        store = loadPresets()
        store["presets"][name] = preset
        saveJson("presets.json", store)
        return Out({"ok": True, "imported": name, "bands": len(preset["bands"]), "preamp": preset["preamp"]},
                   f'imported {name}: {len(preset["bands"])} filters, preamp {S(preset["preamp"])}')
    if sub == "band":
        n, freq, gain, q, typ = (rest + [None] * 5)[:5]
        i = js_number(n) - 1
        if (not is_int(i) or i < 0 or i >= MAX_BANDS or any(x is None or not _is_finite_text(x) for x in (freq, gain))
                or (q is not None and not (js_number(q) > 0))):
            raise Fail("usage: ballroom eq band N FREQ GAIN [Q] [peaking|lowshelf|highshelf]", EXIT.usage)
        if truthy(typ) and typ not in BAND_TYPES:
            raise Fail("a band is peaking, lowshelf or highshelf", EXIT.usage)
        i = int(i)
        g = readGraph()
        d = eqTarget(g, [])
        name, presets = editablePreset(g, d)
        p = presets["presets"][name]
        while len(p["bands"]) <= i:
            p["bands"].append({"type": "peaking", "freq": 1000, "gain": 0, "q": 1})
        p["bands"][i] = clampBand({"type": typ if typ is not None else p["bands"][i]["type"], "freq": js_number(freq), "gain": js_number(gain),
                                   "q": js_number(q) if q is not None else p["bands"][i]["q"]})
        checkFits(p["bands"])
        saveJson("presets.json", presets)
        if "--later" in rest:
            return Out({"ok": True, "saved": name}, "saved")
        r = eqSync()
        return say(r, f'band {i + 1} of {name}: {r["action"]}')
    if sub == "preamp":
        v = rest[0] if rest else None
        if v is None or (v != "auto" and not _is_finite_text(v)):
            raise Fail("usage: ballroom eq preamp DB|auto", EXIT.usage)
        g = readGraph()
        d = eqTarget(g, [])
        name, presets = editablePreset(g, d)
        presets["presets"][name]["preamp"] = "auto" if v == "auto" else js_max(-24, js_min(6, js_number(v)))
        saveJson("presets.json", presets)
        r = eqSync()
        return say(r, f'preamp of {name}: {S(r["plan"]["preamp"])} dB')
    if sub == "balance":
        v = js_number(rest[0] if rest else None)
        if not rest or not _is_finite_text(rest[0]):
            raise Fail("usage: ballroom eq balance -1..1 (0 is the middle)", EXIT.usage)
        saveSound({"balance": js_max(-1, js_min(1, js_round(v * 100) / 100))})
        r = eqSync()
        return say(r, f'balance {S(loadSound()["balance"])}{"" if truthy(loadSound()["enabled"]) else " (takes effect with the EQ on)"}')
    if sub == "stereo":
        if (rest[0] if rest else None) != "reset":
            raise Fail("usage: ballroom eq stereo reset", EXIT.usage)
        saveSound({"balance": 0, "mono": False, "swap": False})
        r = eqSync()
        return say(r, "balance centered, mono and swap off")
    if sub in ("mono", "swap"):
        v = rest[0] if rest else None
        if nn(v, "") not in ("on", "off"):
            raise Fail(f"usage: ballroom eq {sub} on|off", EXIT.usage)
        saveSound({sub: v == "on"})
        r = eqSync()
        return say(r, f'{sub} {v}{"" if truthy(loadSound()["enabled"]) else " (takes effect with the EQ on)"}')
    raise Fail(f"unknown: eq {S(sub)}", EXIT.usage)


# ---------------------------------------------------------------- stage
# The stage plays radio, SoundCloud and DI.FM without a window of its own. The engine is mpv: headless, idle,
# without a configuration, driven over its JSON IPC socket. ballroom-stage.service runs it, and `play` starts
# the unit when the socket does not answer; pause, stop and next never start it. Its sound is a stream in the
# graph named Ballroom, with Ballroom's level, route and equalizer; mpv's own volume is never touched, or two
# volumes would stack.
#
# Measured on mpv 0.41: the socket answers 150 ms after the start, a local address plays 60 ms after `loadfile`,
# a radio stream in about 1 s, a SoundCloud track about 4 s after yt-dlp resolved its page (2 s); `stop` answers within
# 15 ms while an address that never answers is loading, and a new `loadfile` replaces such an address at once.
# mpv runs with --ytdl=no: with it on, mpv hands every address to yt-dlp first, and a radio stream never plays.
# Turning ytdl on for one file only is a race: mpv loads its ytdl_hook script while the file already opens, and
# under load ffmpeg opens the page before the hook exists. So a SoundCloud page is resolved here with yt-dlp
# (about 2 s) and mpv gets the direct address. mpv-mpris is not loaded: without a session bus it stalls mpv.
#
# A live stream is not paused but stopped and remembered: mpv would keep buffering, and the sound after the
# pause would lag behind the station by the length of the pause (measured: 4 s of pause, 4 s of lag). Playing it
# again tunes in live. A track (SoundCloud) pauses in place.
#
# Every address goes to mpv over the socket, never as a process argument: /proc shows arguments to every local
# user, and a DI.FM address carries the listen key. DI.FM and its sister stations (the AudioAddict network) have
# no free streams any more; with a premium listen key the premium playlist of a channel names its stream, and
# the server checks the key ("Invalid Listen Key"). The key is a secret: it comes in over stdin or a hidden
# prompt, never as an argument (shell history, /proc), it lives in audioaddict.json (0600), every text Ballroom
# prints has it masked, the stream's title in the graph is forced to the channel name so the address never shows
# there, and what Ballroom remembers of a DI.FM stream is the channel, never the address.
#
# An item of the stage: title, kind ("radio", "soundcloud", "di" or "url"), and as it applies url, subtitle,
# network, channel, set.
STAGE_UNIT = "ballroom-stage.service"
# node.name and application.name of mpv's stream, from --audio-client-name in the unit.
STAGE_NODE = "Ballroom"
STAGE_SOCK = pjoin(RUNTIME, "mpv.sock")
STAGE_UA = f"ballroom/{VERSION} (Omarchy plugin)"
AA_API = (ENV.get("BALLROOM_AUDIOADDICT_API") if BENCH else None) or "https://api.audioaddict.com/v1"
# The networks play here only with a premium listen key: their free playlists point at servers that do not
# resolve, and a third-party player gets an announcement stream instead of music (measured).
AA_NETWORKS = {
    "di": {"name": "DI.FM", "host": "listen.di.fm"}, "radiotunes": {"name": "RadioTunes", "host": "listen.radiotunes.com"},
    "jazzradio": {"name": "JazzRadio", "host": "listen.jazzradio.com"}, "classicalradio": {"name": "ClassicalRadio", "host": "listen.classicalradio.com"},
    "rockradio": {"name": "RockRadio", "host": "listen.rockradio.com"}, "zenradio": {"name": "ZenRadio", "host": "listen.zenradio.com"},
}


# The bench serves the API and the playlists itself: {network} in the template is the network's key.
def aaListen(network):
    template = (ENV.get("BALLROOM_AUDIOADDICT_LISTEN") if BENCH else None) or "https://{host}"
    return template.replace("{host}", AA_NETWORKS[network]["host"], 1).replace("{network}", network, 1)


# The community radio directory. all.api picks a mirror by DNS; two named mirrors follow when it does not answer.
RADIO_API = [ENV["BALLROOM_RADIO_API"]] if BENCH and ENV.get("BALLROOM_RADIO_API") else \
    ["https://all.api.radio-browser.info", "https://de1.api.radio-browser.info", "https://de2.api.radio-browser.info"]
CACHE = pjoin(nn(ENV.get("XDG_CACHE_HOME"), pjoin(HOME, ".cache")), "ballroom")
NOW_FILE = pjoin(RUNTIME, "stage-now.json")


def loadStage():
    return loadJson("stage.json", {"schemaVersion": 1, "favorites": [], "recent": []},
                    lambda v: isinstance(v.get("favorites"), list) and isinstance(v.get("recent"), list))


_key_cache = UNDEF


def listenKey():
    global _key_cache
    if _key_cache is UNDEF:
        v = loadJson("audioaddict.json", {"schemaVersion": 1, "listenKey": ""}, lambda x: isinstance(x.get("listenKey"), str))
        _key_cache = v["listenKey"] if v["listenKey"] else None
    return _key_cache


# Everything the stage prints goes through this.
def maskKey(text):
    k = listenKey()
    return "…".join(text.split(k)) if k else text


def _url(url):
    """new URL(url), as far as it is asked here: the scheme, the host with its port, the host name."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url)
        if not u.scheme or not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", u.scheme):
            return None
        hostname = (u.hostname or "").lower()
        port = u.port
    except ValueError:
        return None
    if u.scheme.lower() in ("http", "https", "ws", "wss", "ftp") and not hostname:
        return None
    default = {"http": 80, "https": 443, "ws": 80, "wss": 443, "ftp": 21}.get(u.scheme.lower())
    host = (f"[{hostname}]" if ":" in hostname else hostname) + (f":{port}" if port is not None and port != default else "")
    return {"protocol": u.scheme.lower() + ":", "host": host, "hostname": hostname}


def hostOf(url):
    u = _url(url)
    return u["host"] if u is not None else "the server"


def isSoundcloudPage(url):
    u = _url(url)
    return u is not None and u["protocol"] == "https:" and re.search(r"(^|\.)soundcloud\.com\Z", u["hostname"]) is not None


def soundcloudHttps(url):
    """http://soundcloud.com/... (or a host under it, without a port of its own) as the https page it is. Every other
    address is returned as it came; isSoundcloudPage still decides what gets the browser session."""
    u = _url(url) if isinstance(url, str) else None
    if u is None or u["protocol"] != "http:" or u["host"] != u["hostname"]:
        return url
    if re.search(r"(^|\.)soundcloud\.com\Z", u["hostname"]) is None or not re.match(r"http://", url, re.I):
        return url
    return "https://" + url[7:]


def encodeURIComponent(s):
    from urllib.parse import quote
    return quote(s, safe="!*'()~-_.")


def decodeURIComponent(s):
    """Strict like the JavaScript one: a broken escape is an error, not a guess."""
    parts = []
    i = 0
    while i < len(s):
        if s[i] != "%":
            parts.append(s[i])
            i += 1
            continue
        raw = bytearray()
        while i < len(s) and s[i] == "%":
            if not re.fullmatch(r"[0-9A-Fa-f]{2}", s[i + 1:i + 3]):
                raise ValueError("URI malformed")
            raw.append(int(s[i + 1:i + 3], 16))
            i += 3
        parts.append(raw.decode("utf-8"))
    return "".join(parts)


class _Deadline(Exception):
    pass


class _TooBig(Exception):
    pass


# One request, one deadline for all of it: the name lookup, the connection, TLS, the head and the body, as a
# fetch with an abort signal has. A socket timeout alone resets with every packet, and a server that trickles a
# byte now and then would hold the panel until the widget kills the process. The request runs in a thread the
# answer does not wait for past the deadline. At the deadline the connection is shut down in both directions:
# that wakes a thread blocked in TLS, in the head or in the body, and the server sees the client leave. Closing
# alone would not: the response holds its own reference to the socket, and during the TLS handshake the plain
# socket is already detached. So the thread keeps a duplicate of the connected socket from the moment it
# connects, and the shutdown goes to that; it reaches the same connection whatever http.client holds. The name
# lookup is the one step nothing interrupts; a thread stuck there is left behind and ends with the process.
# Redirects are never followed; a 3xx comes back without its body.
def _fetch(url, headers, timeout_ms, cap):
    import threading
    deadline = time.monotonic() + timeout_ms / 1000
    box = {}

    def left():
        return max(0.001, deadline - time.monotonic())

    def connect(address, timeout=None, source_address=None, *rest, **kw):
        import socket as _socket
        sock = _socket.create_connection(address, left(), source_address)
        box["dup"] = sock.dup()
        if box.get("expired"):
            sock.close()
            raise _Deadline()
        return sock

    def work():
        conn = None
        try:
            import http.client
            from urllib.parse import urlsplit
            u = urlsplit(url)
            target = (u.path or "/") + (f"?{u.query}" if u.query else "")
            if u.scheme == "https":
                import ssl
                conn = http.client.HTTPSConnection(u.hostname, u.port, timeout=left(), context=ssl.create_default_context())
            elif u.scheme == "http":
                conn = http.client.HTTPConnection(u.hostname, u.port, timeout=left())
            else:
                raise ValueError("not http")
            conn._create_connection = connect
            conn.request("GET", target, headers=headers)
            if conn.sock is not None:
                conn.sock.settimeout(left())
            res = conn.getresponse()
            status, head = res.status, res.headers
            body = bytearray()
            if not 300 <= status < 400:
                while True:
                    if conn.sock is not None:
                        conn.sock.settimeout(left())
                    chunk = res.read(65536)
                    if not chunk:
                        break
                    body += chunk
                    if len(body) > cap:
                        raise _TooBig()
            box["result"] = (status, head, bytes(body))
        except BaseException as e:
            box["error"] = e
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            dup = box.get("dup")
            if dup is not None:
                dup.close()
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(max(0, deadline - time.monotonic()))
    if t.is_alive() or ("error" in box and time.monotonic() >= deadline):
        import socket as _socket
        box["expired"] = True
        dup = box.get("dup")
        if dup is not None:
            try:
                dup.shutdown(_socket.SHUT_RDWR)
            except OSError:
                pass  # the thread closed it on its own meanwhile
        raise _Deadline()
    if "error" in box:
        raise box["error"]
    return box["result"]


# In process, so that an address with a key is never a process argument, and so that `ballroom json` starts
# no process for the stage. The address never appears in a message: only its host. Only https, no redirects
# (a redirect could carry the key elsewhere), and at most FETCH_CAP bytes: past that the answer is refused,
# not cut, because a cut list is a different list.
FETCH_CAP = 1024 * 1024


def fetchRaw(url, timeout=12000):
    if not BENCH and not url.startswith("https://"):
        raise Fail(f"only https is spoken to {hostOf(url)}")
    try:
        status, _head, body = _fetch(url, {"User-Agent": STAGE_UA}, timeout, FETCH_CAP)
    except _Deadline:
        raise Fail(f"no answer from {hostOf(url)} within {js_round(timeout / 1000)} s", EXIT.timeout)
    except _TooBig:
        raise Fail(f"{hostOf(url)} sent more than {FETCH_CAP // 1024} KiB; refused")
    except Exception:
        raise Fail(f"no answer from {hostOf(url)}")
    if 300 <= status < 400:
        raise Fail(f"{hostOf(url)} redirects elsewhere; not followed")
    return {"status": status, "text": body.decode("utf-8-sig", "replace")}


def fetchText(url, timeout=12000):
    r = fetchRaw(url, timeout)
    if r["status"] < 200 or r["status"] >= 300:
        raise Fail(f'{hostOf(url)} answered with {r["status"]}')
    return r["text"]


# An AudioAddict channel: network, key, name, description.
def channelItem(c):
    c = c if isinstance(c, dict) else {}
    return {"title": c.get("name"), "kind": "di", "network": c.get("network"), "channel": c.get("key"),
            "subtitle": gp(AA_NETWORKS.get(c.get("network")), "name")}


# The channel list from the cache alone, without a fetch: `json` runs every second and starts no process.
def cachedChannels(network):
    try:
        cached = jparse(read_text(pjoin(CACHE, f"audioaddict-{network}.json")))
        ch = gp(cached, "channels")
        return [channelItem(c) for c in ch] if isinstance(ch, list) else None
    except Exception:
        return None


def aaChannels(network):
    ensureDir(CACHE)
    f = pjoin(CACHE, f"audioaddict-{network}.json")
    try:
        cached = jparse(read_text(f))
        if now_ms() - js_number(gp(cached, "at")) < 24 * 3600 * 1000 and isinstance(gp(cached, "channels"), list):
            return cached["channels"]
    except Exception:
        pass  # first time, or old
    try:
        lst = jparse(fetchText(f"{AA_API}/{network}/channels"))
    except Fail:
        raise
    except Exception:
        raise Fail(f'{AA_NETWORKS[network]["name"]} sent no channel list')
    channels = [{"network": network, "key": S(c["key"]), "name": clean(S(c["name"])), "description": cut(clean(S(nn(c.get("description_short"), ""))), 160)}
                for c in (lst if isinstance(lst, list) else []) if isinstance(c, dict) and truthy(c.get("key")) and truthy(c.get("name"))]
    write_atomic(f, jdump({"at": now_ms(), "channels": channels}) + "\n", 0o600)
    return channels


# The stream of a channel: the premium playlist names it, and says so when the key is not accepted.
def aaStreamUrl(network, channel, key=UNDEF):
    if key is UNDEF:
        key = listenKey()
    name = AA_NETWORKS[network]["name"]
    if not key:
        raise Fail(f"{name} needs a premium listen key: ballroom di key set (your account page on di.fm shows it)", EXIT.usage)
    # The server answers a wrong key with 403 and the words "Invalid Listen Key" (measured over https).
    r = fetchRaw(f"{aaListen(network)}/premium_high/{encodeURIComponent(S(channel))}.pls?listen_key={encodeURIComponent(key)}")
    if r["status"] in (401, 403) or re.search(r"invalid listen key", r["text"], re.I):
        raise Fail(f"{name} does not accept the listen key; is the premium subscription active?")
    if r["status"] < 200 or r["status"] >= 300:
        raise Fail(f'{name} answered with {r["status"]}')
    m = re.search("(?:^|(?<=[\r\u2028\u2029]))File1=([^\n\r\u2028\u2029]+)(?=[\n\r\u2028\u2029]|\\Z)", r["text"], re.M)
    f = js_trim(m.group(1)) if m else None
    if not f or not re.match(r"https?://", f):
        raise Fail(f"{name} sent no stream for {S(channel)}")
    return f


# A key is checked with DI.FM first and written only then; a wrong one never touches the disk.
def diKeySet(v):
    global _key_cache
    if not re.fullmatch(r"[A-Za-z0-9]{8,64}", v):
        raise Fail("a listen key is 8 to 64 letters and digits", EXIT.usage)
    first = gp(aaChannels("di"), 0, "key")
    aaStreamUrl("di", nn(first, "trance"), v)
    withLock(lambda: saveJson("audioaddict.json", {"schemaVersion": 1, "listenKey": v}))
    _key_cache = UNDEF


# A secret from the terminal: a hidden prompt on a TTY, the first line of stdin otherwise (a pipe or a file).
# The shell builtin `read` takes it, so it is never an argument of any process.
def readSecret(prompt):
    # isatty on the descriptor, not sys.stdin: a buffered reader on stdin would read past the first line and wait
    # for the writer to close the pipe.
    if os.isatty(0):
        p = subprocess.run(["sh", "-c", 'printf "%s " "$1" >&2; stty -echo 2>/dev/null; IFS= read -r k; stty echo 2>/dev/null; printf "\\n" >&2; printf "%s" "$k"', "sh", prompt],
                           stdout=subprocess.PIPE)
        return js_trim(p.stdout.decode("utf-8", "replace"))
    # The first line only, read straight from the descriptor: the widget writes the key and keeps the pipe open
    # until the process ends, and waiting for the pipe to close would keep the process waiting with it.
    buf = b""
    while True:
        try:
            chunk = os.read(0, 4096)
        except BlockingIOError:
            sleep_ms(10)
            continue
        if not chunk:
            break
        buf += chunk
        nl = buf.find(b"\n")
        if nl >= 0:
            buf = buf[:nl]
            break
        if len(buf) > 4096:
            break
    return js_trim(buf.decode("utf-8", "replace"))


# ---- mpv over its socket
# One connection, a batch of commands, the answers in the order of the commands (mpv numbers them by request_id).
def mpvIpc(commands, timeout=2500):
    deadline = time.monotonic() + timeout / 1000
    answers = [UNDEF] * len(commands)
    got = 0
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            s.settimeout(timeout / 1000)
            s.connect(STAGE_SOCK)
        except socket.timeout:
            raise Fail("the stage did not answer", EXIT.timeout)
        except OSError:
            raise Fail("the stage is not running", EXIT.notFound)
        try:
            s.sendall(("\n".join(jdump({"command": c, "request_id": i + 1}) for i, c in enumerate(commands)) + "\n").encode("utf-8", "surrogatepass"))
            buf = b""
            while got < len(commands):
                left = deadline - time.monotonic()
                if left <= 0:
                    raise socket.timeout()
                s.settimeout(left)
                chunk = s.recv(65536)
                if not chunk:
                    raise Fail("the stage closed the connection")
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        v = jparse(line.decode("utf-8", "replace"))
                    except Exception:
                        continue
                    i = js_number(gp(v, "request_id")) - 1
                    if is_int(i) and 0 <= i < len(commands) and answers[int(i)] is UNDEF:
                        answers[int(i)] = v
                        got += 1
        except socket.timeout:
            raise Fail("the stage did not answer", EXIT.timeout)
        except Fail:
            raise
        except OSError:
            raise Fail("the stage did not answer")
    finally:
        s.close()
    return answers


def mpvGet(names):
    a = mpvIpc([["get_property", n] for n in names])
    return {n: (a[i].get("data") if isinstance(a[i], dict) and a[i].get("error") == "success" else None) for i, n in enumerate(names)}


def mpvCmd(cmd, timeout=2500):
    a = mpvIpc([cmd], timeout)[0]
    if gp(a, "error") != "success":
        raise Fail(f'mpv refused {S(cmd[0])}: {cut(maskKey(clean(S(nn(gp(a, "error"), "no answer")))), 120)}')
    return a


def stageInstalled():
    return which("mpv")


def stageRunning():
    try:
        mpvGet(["idle-active"])
        return True
    except Exception:
        return False


def ensureStage():
    if not stageInstalled():
        raise Fail("the stage needs mpv: omarchy pkg add mpv", EXIT.notFound)
    if stageRunning():
        return
    ensureDir(RUNTIME)
    ensureUnit(STAGE_UNIT)
    r = run(["systemctl", "--user", "start", STAGE_UNIT], 8000)
    if r.rc != 0:
        raise Fail(f"{STAGE_UNIT} did not start; journalctl --user -u {STAGE_UNIT} says why")
    until = now_ms() + 5000
    while now_ms() < until:
        if stageRunning():
            return
        sleep_ms(100)
    raise Fail("mpv started but does not answer on its socket")


# SoundCloud is only what isSoundcloudPage says: https and the host soundcloud.com or one under it. An address that
# merely carries the words (http://soundcloud.com/..., https://elsewhere.example/soundcloud.com) is a plain address:
# a SoundCloud entry is handed to yt-dlp with the browser session, and that session is for SoundCloud alone.
def kindOfPath(path):
    if isSoundcloudPage(path):
        return "soundcloud"
    if re.search(r"\.(di\.fm|radiotunes\.com|jazzradio\.com|classicalradio\.com|rockradio\.com|zenradio\.com)(:[0-9]+)?/", path, re.I):
        return "di"
    return "url"


def loadNow():
    try:
        return jparse(read_text(NOW_FILE))
    except Exception:
        return None


def saveNow(now):
    writeRuntime("stage-now.json", jdump(now) + "\n")


def _own(obj, key):
    """obj.key as JSON.stringify sees it: a key that is not there is left out, not written as null."""
    return obj.get(key, UNDEF) if isinstance(obj, dict) else UNDEF


def _str_or_empty(v):
    return S(nn(v, ""))


# What the stage shows. Read from mpv in one connection, plus the stored lists and DI.FM's now-playing.
# Nothing here starts a process: the widget asks every second while the panel is open.
def stageState():
    available = stageInstalled()
    store = loadStage()
    now = loadNow()
    m = None
    if available:
        try:
            m = mpvGet(["idle-active", "core-idle", "pause", "path", "media-title", "metadata/by-key/icy-title", "metadata/by-key/icy-name", "duration", "time-pos", "playlist-count", "paused-for-cache"])
        except Exception:
            m = None
    running = m is not None
    loaded = running and m["idle-active"] is False
    path = m["path"] if loaded and isinstance(m["path"], str) else ""
    # What Ballroom started is recognised by a hash of the address mpv plays: a DI.FM address carries the key.
    ours = bool(truthy(now) and path and strict_eq(gp(now, "urlHash"), bun_hash(path)))
    # A live stream that Ballroom stopped for a pause, ready to be tuned in again.
    resting = bool(truthy(now) and truthy(gp(now, "paused")) and running and not loaded)
    if not available:
        state = "missing"
    elif not running:
        state = "off"
    elif loaded:
        state = "paused" if m["pause"] is True else "loading" if m["core-idle"] is True else "playing"
    else:
        state = "paused" if resting else "stopped"
    kind = (_own(now, "kind") if ours else kindOfPath(path)) if loaded else _own(now, "kind") if resting else None
    title = ((_str_or_empty(gp(now, "title")) if ours else _str_or_empty(m["media-title"])) if loaded
             else _str_or_empty(gp(now, "title")) if resting else "")
    icy = js_trim(m["metadata/by-key/icy-title"]) if loaded and isinstance(m["metadata/by-key/icy-title"], str) else ""
    subtitle = icy or (_str_or_empty(gp(now, "subtitle")) if (ours or resting) else "")
    if not icy and (ours or resting) and gp(now, "kind") == "di":
        try:
            np = jparse(read_text(pjoin(RUNTIME, "stage-di-now.json")))
            if now_ms() - js_number(gp(np, "at")) < 120000 and strict_eq(gp(np, "channel"), gp(now, "channel")) and truthy(gp(np, "text")):
                subtitle = np["text"]
        except Exception:
            pass  # not fetched yet
    # A live stream: a station, or anything with ICY headers, or something that plays and has no length. While a
    # file is still loading its length is simply unknown, and that is not live.
    live = kind == "radio" or kind == "di" or (loaded and (isinstance(m["metadata/by-key/icy-name"], str) or (m["core-idle"] is False and m["duration"] is None)))
    results = None
    try:
        results = jparse(read_text(pjoin(RUNTIME, "stage-results.json")))
    except Exception:
        pass  # no search yet
    sclist = loadScList()
    channels = cachedChannels("di")

    # set: a SoundCloud playlist. The panel opens it instead of playing it, so the flag has to travel.
    def show(i):
        return {"id": stageId(i), "title": cut(maskKey(clean(_str_or_empty(gp(i, "title")))), 160), "kind": _own(i, "kind"),
                "subtitle": cut(maskKey(clean(_str_or_empty(gp(i, "subtitle")))), 160), "set": gp(i, "set") is True}

    q = gp(now, "queue")
    queue = q if (ours or resting) and truthy(q) and isinstance(gp(q, "ids"), list) else None
    items = gp(results, "items")
    return {
        "available": available, "running": running, "state": state, "kind": kind, "live": bool(live), "ours": ours,
        "title": cut(maskKey(clean(title)), 160), "subtitle": cut(maskKey(clean(subtitle)), 160),
        # What played last, for the row at the top while nothing is loaded: play resumes it.
        "lastTitle": cut(maskKey(clean(S(gp(now, "title")))), 160) if not loaded and not resting and truthy(gp(now, "title")) else "",
        "queue": {"length": len(queue["ids"]), "pos": queue.get("pos", UNDEF)} if queue is not None else None,
        "position": js_round(m["time-pos"]) if loaded and is_num(m["time-pos"]) else None,
        "duration": js_round(m["duration"]) if loaded and not live and is_num(m["duration"]) else None,
        "playlist": js_number(nn(m["playlist-count"], 0)) if loaded else 0,
        "buffering": bool(loaded and m["paused-for-cache"] is True),
        "favorites": [show(i) for i in store["favorites"]], "recent": [show(i) for i in store["recent"][:8]],
        "results": {"kind": _own(results, "kind"), "query": maskKey(clean(_str_or_empty(gp(results, "query")))),
                    "items": [show(i) for i in (items if isinstance(items, list) else [])], "complete": gp(results, "complete") is not False}
        if truthy(results) else None,
        # The list of a SoundCloud profile the panel last asked for: which one it is, whose, and when.
        "sclist": {"what": sclist["what"], "user": sclist["user"], "at": sclist.get("at", UNDEF), "items": [show(i) for i in sclist["items"]]} if sclist is not None else None,
        # Every channel of DI.FM, once the list was fetched (ballroom di channels): the library lists them under
        # DI.FM when no search is showing, each with a star.
        "channels": {"network": "di", "items": [show(i) for i in channels]} if channels is not None else None,
        "diKey": bool(listenKey()),
    }


# The widget names a row by this, not by its position: a search that finishes or a favorite that goes between
# two readings must not make a click play or remove the wrong entry. The id carries no address.
def stageId(i):
    kind = i.get("kind", UNDEF) if isinstance(i, dict) else UNDEF
    where = nn(gp(i, "url"), nn(gp(i, "channel"), ""))
    return bun_hash(f'{S(kind)}|{S(nn(gp(i, "network"), ""))}|{S(where)}')


# The queue: the list an entry was chosen from (results, favorites, recent or likes), as ids and a position,
# so that next and prev walk that list. Ids carry no address, so the queue is safe to keep.
def stageLists():
    results = None
    try:
        results = jparse(read_text(pjoin(RUNTIME, "stage-results.json")))
    except Exception:
        pass  # no search yet
    store = loadStage()
    items = gp(results, "items")
    sc = loadScList()
    return [{"name": "results", "items": [i for i in (items if isinstance(items, list) else []) if truthy(i) and truthy(gp(i, "kind"))]},
            {"name": "favorites", "items": store["favorites"]}, {"name": "recent", "items": store["recent"]},
            {"name": "sclist", "items": sc["items"] if sc is not None else []}, {"name": "channels", "items": nn(cachedChannels("di"), [])}]


def stageLocate(i):
    for lst in stageLists():
        ids = [stageId(x) for x in lst["items"]]
        if i in ids:
            pos = ids.index(i)
            return {"item": lst["items"][pos], "queue": {"ids": ids, "pos": pos}}
    return None


def stageById(i):
    found = stageLocate(i)
    return found["item"] if found is not None else None


def queueOf(items, pos):
    return {"ids": [stageId(x) for x in items], "pos": pos}


# The browser session yt-dlp may read, so that private likes and tracks come along. Measured on a profile with
# 130 public likes: with the session 133, the three private ones included, in 3.7 s instead of 1.5 s. The value
# is a browser name, a keyring and a profile path, not a secret; the cookies stay in yt-dlp.
# Nothing is read until a browser is chosen: in the panel, or with `ballroom sc cookies auto|BROWSER`. An empty
# setting reads no browser, and so does "none", the value `sc cookies -` stores. A session that belongs to the
# user's browser is used only because the user said so, never because it happens to be there.
# browser, optionally +keyring, optionally :profile. The leading letters keep a value from ever starting with a
# dash, so it cannot be read as an option however it reaches yt-dlp.
def cookieSpecOk(v):
    return re.fullmatch(r"[a-z]+(\+[a-z]+)?(:[^\r\n]{1,240})?", v) is not None


COOKIES_OFF = "none"


def ytdlpCookieArgs():
    v = js_trim(S(nn(widgetValues().get("soundcloudCookies"), "")))
    if not v or v == COOKIES_OFF:
        return []
    if not cookieSpecOk(v):
        warnings.append("the SoundCloud browser cookies setting is not a browser name like brave or brave:/path/to/profile; ignored")
        return []
    # A Chromium store without a keyring in the spec opens nothing and says nothing about it: only the public
    # tracks come back. `sc cookies` tries the keyrings before it keeps a browser, so this is a value from an
    # older setting or one typed by hand; it is used as it is and named, not silently replaced.
    if "+" not in v and not v.startswith("firefox"):
        warnings.append(f'the browser session is set without a keyring; if only public tracks show, set it again: ballroom sc cookies {v.split(":")[0]}')
    return ["--cookies-from-browser", v]


# A Chromium store since version 11 is locked with a key from the desktop keyring, and yt-dlp has to be told
# which one: without it it reads the store, decrypts nothing and quietly returns what the profile shows
# publicly (measured: 0 of 747 cookies decrypted with the bare name, all 747 with +gnomekeyring).
# So the spec is not guessed, it is tried: yt-dlp writes the jar to a file that is never read, which makes it
# say how many it could open, and that needs no network.
KEYRINGS = ["gnomekeyring", "kwallet6", "kwallet5", "basictext"]


# A store holds old cookies that need no keyring beside the ones that do, so "some opened" proves nothing: the
# wrong keyring can open the old ones and leave the session shut, and then only the public tracks come and
# nobody is told why. yt-dlp says when it left some behind (' (N could not be decrypted)', cookies.py:353), and
# only a run that left none behind counts.
def cookieSpecWorks(spec):
    r = run(["yt-dlp", "--cookies-from-browser", spec, "--cookies", "/dev/null"], 20000)
    said = f"{r.out}\n{r.err}"
    if "could not be decrypted" in said:
        return False
    m = re.search(r"Extracted ([0-9]+) cookies", said)
    return m is not None and js_number(m.group(1)) > 0


def resolveCookieSpec(b):
    if b["browser"] == "firefox":
        return b["value"] if cookieSpecWorks(b["value"]) else None
    for k in KEYRINGS:
        spec = f'{b["browser"]}+{k}:{b["profile"]}'
        if cookieSpecWorks(spec):
            return spec
    return b["value"] if cookieSpecWorks(b["value"]) else None


# Which browsers keep a cookie store on this machine, and which of them holds a SoundCloud session. Only the
# host column of the store is read, never a cookie value: the answer is a browser name and the profile that
# holds the session, which is exactly what yt-dlp is given. The store is opened read only, so a browser that is
# running keeps it. yt-dlp looks for a Chromium profile under the browser's usual directory only, and a profile
# that lives anywhere else is found by nobody: that is why the profile goes into the setting as a path.
# readable false means the store is there but could not be opened (locked, being written, a schema we do not
# know). That is not the same as "not signed in", and saying the second when the first is true would send the
# user off to sign in to an account they are already signed in to.
# A store: browser, profile, cookies, label, value, soundcloud, readable.
CHROMIUM_ROOTS = {
    "brave": ["BraveSoftware"],
    "chrome": ["google-chrome", "google-chrome-beta", "google-chrome-unstable"],
    "chromium": ["chromium"],
    "edge": ["microsoft-edge", "microsoft-edge-beta", "microsoft-edge-dev"],
    "opera": ["opera", "opera-beta", "opera-developer"],
    "vivaldi": ["vivaldi", "vivaldi-snapshot"],
}


def listDir(d):
    try:
        return os.listdir(d)
    except OSError:
        return []


# How many cookies of soundcloud.com the store holds, or None when it cannot be read (a store that is being
# written, a format we do not know). The table and the column are ours, not the user's. The store is opened
# read only, through a file: URI with mode=ro, and without waiting for a lock the browser holds. A host counts
# when it is soundcloud.com itself, with the leading dot both Chromium and Firefox write for a domain cookie, or
# a host under it; a host that only ends in the same letters (evilsoundcloud.com) does not.
def soundcloudCookies(f, table, column):
    try:
        import sqlite3
        from urllib.parse import quote
        db = sqlite3.connect(f"file:{quote(f)}?mode=ro", uri=True, timeout=0)
        try:
            row = db.execute(f"select count(*) as n from {table} where {column} = 'soundcloud.com' or {column} = '.soundcloud.com' or {column} like '%.soundcloud.com'").fetchone()
            return js_number(nn(row[0] if row else None, 0))
        finally:
            db.close()
    except Exception:
        return None


def browserStores():
    found = []
    cfg = nn(ENV.get("XDG_CONFIG_HOME"), pjoin(HOME, ".config"))
    for browser, roots in CHROMIUM_ROOTS.items():
        # A browser directory is the one with the Local State beside the profiles: Brave keeps its own one level
        # deeper, under BraveSoftware.
        dirs = []
        for r in roots:
            base = pjoin(cfg, r)
            if not os.path.exists(base):
                continue
            if os.path.exists(pjoin(base, "Local State")):
                dirs.append(base)
            else:
                for d in listDir(base):
                    if os.path.exists(pjoin(base, d, "Local State")):
                        dirs.append(pjoin(base, d))
        for d in dirs:
            for p in listDir(d):
                if p != "Default" and not p.startswith("Profile "):
                    continue
                f = next((x for x in (pjoin(d, p, "Network", "Cookies"), pjoin(d, p, "Cookies")) if os.path.exists(x)), None)
                if f is None:
                    continue
                n = soundcloudCookies(f, "cookies", "host_key")
                found.append({"browser": browser, "profile": pjoin(d, p), "cookies": f, "label": f"{browser} · {p}", "value": f"{browser}:{pjoin(d, p)}",
                              "soundcloud": nn(n, 0) > 0, "readable": n is not None})
    ff = pjoin(HOME, ".mozilla", "firefox")
    for p in listDir(ff):
        f = pjoin(ff, p, "cookies.sqlite")
        if not os.path.exists(f):
            continue
        n = soundcloudCookies(f, "moz_cookies", "host")
        found.append({"browser": "firefox", "profile": pjoin(ff, p), "cookies": f, "label": f'firefox · {re.sub(r"^[A-Za-z0-9_]+[.]", "", p, count=1)}',
                      "value": f"firefox:{pjoin(ff, p)}", "soundcloud": nn(n, 0) > 0, "readable": n is not None})

    # Signed in on SoundCloud first, so the panel and "auto" take one that carries a session.
    def order(a, b):
        r = int(b["soundcloud"]) - int(a["soundcloud"])
        return r if r else locale_compare(a["label"], b["label"])
    return sorted(found, key=functools.cmp_to_key(order))


# What a SoundCloud profile holds, as yt-dlp lists it: a flat playlist of titles and page addresses, no length
# (measured: 1 to 2 s for the first entries). The four lists SoundCloud itself offers on a profile. A playlist
# is not a track: it is opened into the results, not played. One list at a time is kept for the panel in the
# runtime directory; the panel asks again after ten minutes.
SC_LISTS = {"likes": "likes", "playlists": "sets", "uploads": "tracks", "reposts": "reposts"}


# A list: at, user, what, items.
def loadScList():
    try:
        v = jparse(read_text(pjoin(RUNTIME, "stage-sc.json")))
        return v if isinstance(gp(v, "user"), str) and isinstance(gp(v, "what"), str) and isinstance(gp(v, "items"), list) else None
    except Exception:
        return None


# Who the browser session belongs to. SoundCloud addresses every list by profile name, and the session does not
# say the name anywhere yt-dlp would read it; but soundcloud.com/you answers a signed-in request with a 301 to
# the profile, and that is the name. Measured: 301, Location //soundcloud.com/<name>.
#
# Say it plainly, because the code cannot make it smaller: yt-dlp has no way to export one site's cookies, so
# the file it writes here holds the WHOLE browser jar in clear text, every site the browser is signed in to
# (measured: 747 entries). Only the soundcloud.com rows are read out of it, but all of them touched the disk.
# Against that: the file is ours before yt-dlp sees it (created with O_EXCL and O_NOFOLLOW at 0600, so no link
# can send it anywhere else), it is removed the moment it has been read and before any request goes out, a
# signal removes it too, and one left by a kill is swept on the next run. It happens once per user: the name it
# finds is kept, and nothing asks again.
# The Cookie header a browser itself would send with a request to https://HOST PATH, from a Netscape jar: only
# rows whose domain is that host (a row for another host, or for a host that merely ends in the same letters,
# stays out), whose path covers the request path, and that have not expired. HttpOnly rows carry a "#HttpOnly_"
# prefix and are rows like the others. A name or value that could break the header is left out.
def jarHeader(text, host, path, now=None):
    if now is None:
        now = time.time()
    pairs = []
    for line in text.split("\n"):
        if line.endswith("\r"):
            line = line[:-1]
        if line.startswith("#HttpOnly_"):
            line = line[10:]
        elif not line or line.startswith("#"):
            continue
        f = line.split("\t")
        if len(f) < 7:
            continue
        domain, cpath, expires, name, value = f[0], f[2], f[4], f[5], f[6]
        if re.sub(r"^\.", "", domain.lower(), count=1) != host:
            continue
        p = cpath or "/"
        if not (p == "/" or path == p or path.startswith(p if p.endswith("/") else p + "/")):
            continue
        exp = js_number(expires)
        if is_num(exp) and math.isfinite(exp) and exp > 0 and exp < now:
            continue
        if not name or re.search(r"[;,\s=]", name) or re.search(r"[;\r\n]", value):
            continue
        pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def soundcloudWhoami():
    args = ytdlpCookieArgs()
    if not args:
        return None
    ensureDir(RUNTIME)
    try:
        sweepJars()
    except Exception:
        pass  # the sweep is a courtesy to earlier runs
    jar = pjoin(RUNTIME, f"sc-jar.{os.getpid()}")

    def drop():
        rm_force(jar)

    def bail(signum, frame):
        # yt-dlp first: alive, it would write the whole jar again after it was removed.
        try:
            killGroups()
            drop()
        finally:
            os._exit(EXIT.failed)
    header = ""
    previous = {s: signal.signal(s, bail) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        # Ours, not a link, readable by nobody else: O_EXCL fails on anything that is already there, so a link put
        # in the way beforehand cannot be followed.
        # It carries the one line that makes it an empty cookie jar. yt-dlp LOADS the file it is told to write
        # before it writes it, and an empty file is not a jar: it stopped with "does not look like a Netscape
        # format cookies file" and wrote nothing, which left the account nameless with everything else in order.
        try:
            fd = os.open(jar, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, b"# Netscape HTTP Cookie File\n")
            finally:
                os.close(fd)
        except OSError:
            return None
        run(["yt-dlp", "--no-warnings", *args, "--cookies", jar, "--skip-download", "--simulate", "--", "https://soundcloud.com/discover"], 30000)
        try:
            text = read_text(jar)
        except OSError:
            return None
        header = jarHeader(text, "soundcloud.com", "/you")
    finally:
        drop()
        for s, h in previous.items():
            signal.signal(s, h)
    if not header:
        return None
    location = ""
    try:
        target = (ENV.get("BALLROOM_SC_YOU") if BENCH else None) or "https://soundcloud.com/you"
        _status, head, _body = _fetch(target, {"Cookie": header, "User-Agent": STAGE_UA}, 15000, FETCH_CAP)
        location = nn(head.get("location"), "")
    except Exception:
        return None
    # Anchored: only soundcloud.com itself names the profile, not a host that merely carries the words.
    m = re.fullmatch(r"(?:https?:)?//soundcloud\.com/([A-Za-z0-9_.-]{1,64})/?", js_trim(location))
    return m.group(1) if m else None


# One page of a profile, flat. A track keeps its uploader as the subtitle, a playlist how many tracks it holds.
def soundcloudPage(url, what, who=None):
    if not isSoundcloudPage(url):
        raise Fail("that is not a SoundCloud page (https://soundcloud.com/...); the browser session is not handed to it", EXIT.usage)
    if not which("yt-dlp"):
        raise Fail("SoundCloud needs yt-dlp: omarchy pkg add yt-dlp", EXIT.notFound)
    r = run(["yt-dlp", "--no-warnings", "--flat-playlist", "-J", "--playlist-items", "1-200", *ytdlpCookieArgs(), "--", url], 60000)
    if r.timedOut:
        raise Fail("SoundCloud did not answer within 45 s", EXIT.timeout)
    if r.rc != 0:
        raise Fail((f"SoundCloud knows no profile called {who}" if who else "SoundCloud knows no such playlist") if "404" in r.err
                   else f"yt-dlp could not read the {what} (is it up to date? is the profile public?)")
    try:
        v = jparse(r.out)
    except Exception:
        raise Fail("yt-dlp sent no list")
    entries = gp(v, "entries")
    out = []
    for e in (entries if isinstance(entries, list) else []):
        if not truthy(e) or not re.match(r"https://soundcloud\.com/[^/?#]+/", S(nn(gp(e, "url"), ""))):
            continue
        u = S(e.get("url"))
        is_set = re.search(r"/sets/", u) is not None
        item = {"title": cut(js_trim(clean(S(nn(e.get("title"), "")))), 120) or "untitled", "kind": "soundcloud", "url": u}
        if is_set:
            item["set"] = True
            pc = e.get("playlist_count")
            item["subtitle"] = f'playlist{f", {S(pc)} tracks" if is_num(pc) else ""}'
        else:
            seg = u.split("/")
            item["subtitle"] = cut(clean(decodeURIComponent(seg[3] if len(seg) > 3 else "")), 60)
        out.append(item)
    return out


# One of the four lists a profile offers. Likes and reposts hold both tracks and playlists; uploads only tracks;
# playlists only playlists.
def soundcloudList(what, userArg):
    if what not in SC_LISTS:
        raise Fail(f'no such list "{what}"; one of {", ".join(SC_LISTS)}', EXIT.usage)
    user = js_trim(userArg or S(nn(widgetValues().get("soundcloudUser"), "")))
    if not user:
        raise Fail("no SoundCloud name: ballroom sc name NAME, or ballroom sc whoami with a signed-in browser", EXIT.usage)
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", user):
        raise Fail("a SoundCloud name is letters, digits, dots, dashes and underscores", EXIT.usage)
    items = soundcloudPage(f"https://soundcloud.com/{user}/{SC_LISTS[what]}", what, user)
    lst = {"at": now_ms(), "user": user, "what": what, "items": items}
    writeRuntime("stage-sc.json", jdump(lst) + "\n")
    return lst


# A playlist is opened, not played: its tracks become the results, so they scroll, star and walk with next and
# prev like any other search.
def soundcloudOpen(item):
    # Only a SoundCloud playlist. Every list can hold an address from somewhere else (a radio result carries
    # whatever the open directory says), and this call hands the address to yt-dlp with the browser session
    # attached: it must never be pointed anywhere but the site the session belongs to.
    if gp(item, "kind") != "soundcloud" or gp(item, "set") is not True or not re.match(r"https://soundcloud\.com/", S(nn(gp(item, "url"), ""))):
        raise Fail("that is not a SoundCloud playlist", EXIT.usage)
    items = [x for x in soundcloudPage(item["url"], "playlist") if not truthy(x.get("set"))]
    if not items:
        raise Fail("that playlist holds no tracks that can be played", EXIT.notFound)
    writeRuntime("stage-results.json", jdump({"kind": "soundcloud", "query": item.get("title", UNDEF), "items": items, "complete": True}) + "\n")
    return items


def _same_item(a, item):
    return (gp(a, "kind") == item.get("kind") and nn(gp(a, "url"), gp(a, "channel")) == nn(item.get("url"), item.get("channel"))
            and gp(a, "network") == item.get("network"))


def remember(item):
    withLock(lambda: rememberNow(item))


def rememberNow(item):
    store = loadStage()
    store["recent"] = ([item] + [x for x in store["recent"] if not _same_item(x, item)])[:20]
    saveJson("stage.json", store)


def _strip_now(n):
    return {k: v for k, v in n.items() if k not in ("urlHash", "paused")}


# Loads the address over the socket and reports what mpv does with it, up to 15 s: playing, replaced by
# another address meanwhile, or failed. Only what played gets into the recent list.
def stagePlay(item, queue=None):
    ensureStage()
    url = nn(item.get("url"), "")
    if item.get("kind") == "di":
        url = aaStreamUrl(item.get("network"), item.get("channel"))
    if not isinstance(url, str) or not re.match(r"https?://", url):
        raise Fail("the stage plays http and https addresses", EXIT.usage)
    # An address that carries the listen key is only ever the one DI.FM hands out for a channel; anything else
    # with the key in it would end up in the lists and in every answer.
    key = listenKey()
    if item.get("kind") != "di" and key and key in url:
        raise Fail("that address carries the listen key; play the channel with ballroom di play", EXIT.usage)
    if item.get("kind") == "soundcloud":
        url = resolveSoundCloud(soundcloudHttps(url))
    # The title mpv shows, in the graph too: the item's name, never the address.
    options = {"force-media-title": cut(clean(S(item.get("title", UNDEF))), 120) or "Stage"}
    # pause is a global switch in mpv and would carry over from a paused track to the next address.
    a = mpvIpc([["set_property", "pause", False], ["loadfile", url, "replace", -1, options]], 5000)[1]
    if gp(a, "error") != "success":
        raise Fail(f'mpv did not take the address: {cut(maskKey(clean(S(nn(gp(a, "error"), "no answer")))), 120)}')
    entry = js_number(nn(gp(a, "data", "playlist_entry_id"), 0))
    # What is remembered: the channel for DI.FM (never the address with the key), the page for SoundCloud (the
    # direct address expires), the address itself otherwise.
    stored = dict(item)
    if item.get("kind") == "di":
        stored.pop("url", None)
    else:
        stored["url"] = item.get("url") if item.get("kind") == "soundcloud" else url
    now = dict(stored)
    now["urlHash"] = bun_hash(url)
    now["paused"] = False
    if queue is not None and len(queue["ids"]) > 1:
        now["queue"] = queue
    else:
        now.pop("queue", None)
    saveNow(now)
    state = "loading"
    until = now_ms() + 15000
    while now_ms() < until:
        m = mpvGet(["idle-active", "core-idle", "playlist/0/id"])
        if m["idle-active"] is True:
            state = "failed"
            break
        if not (js_number(m["playlist/0/id"]) == entry):
            state = "replaced"
            break
        if m["core-idle"] is False:
            state = "playing"
            break
        sleep_ms(150)
    if state == "playing":
        remember(stored)
    if state == "failed":
        raise Fail(f'{S(item.get("title", UNDEF))}: the stream could not be played (no answer from the server, or not a sound stream)')
    return {"state": state}


# The direct address behind a SoundCloud page. It expires after a while, so it is resolved on every play and
# never kept; the page address is what favorites and the recent list remember.
def resolveSoundCloud(page):
    if not isSoundcloudPage(page):
        raise Fail("that is not a SoundCloud page (https://soundcloud.com/...); the browser session is not handed to it", EXIT.usage)
    if not which("yt-dlp"):
        raise Fail("SoundCloud needs yt-dlp: omarchy pkg add yt-dlp", EXIT.notFound)
    r = run(["yt-dlp", "--no-warnings", "-g", "-f", "bestaudio/best", *ytdlpCookieArgs(), "--", page], 30000)
    if r.timedOut:
        raise Fail("SoundCloud did not answer within 30 s", EXIT.timeout)
    direct = next((l for l in (js_trim(x) for x in r.out.split("\n")) if re.match(r"https?://", l)), None)
    if r.rc != 0 or not direct:
        raise Fail("yt-dlp could not resolve the SoundCloud page (is it up to date? is the track public?)")
    return direct


# What plays right now, as an item that can be kept: what Ballroom started, or what mpv reports otherwise.
def stageNowItem():
    st = stageState()
    now = loadNow()
    if not st["running"]:
        return None
    if st["ours"] and truthy(now):
        return _strip_now(now)
    # A live stream Ballroom stopped for a pause.
    if st["state"] == "paused" and truthy(now) and truthy(gp(now, "paused")):
        return _strip_now(now)
    if st["state"] in ("playing", "loading", "paused"):
        m = mpvGet(["path"])
        path = m["path"] if isinstance(m["path"], str) else ""
        if not path:
            return None
        key = listenKey()
        if kindOfPath(path) == "di" or (key and key in path):
            raise Fail("what plays carries a listen key in its address; play the channel with ballroom di play to keep it", EXIT.usage)
        return {"title": st["title"] or cut(re.sub(r"^https?://", "", path, count=1), 80), "kind": kindOfPath(path), "url": path}
    return None


def mmss(s):
    return f"{js_floor(s / 60)}:{pad_start(S(js_floor(math.fmod(s, 60))), 2, '0')}"


def _search_params(pairs):
    from urllib.parse import quote_plus
    return "&".join(f'{quote_plus(k, safe="*")}={quote_plus(v, safe="*")}'.replace("~", "%7E") for k, v in pairs)


def radioSearch(q, offset=0):
    params = _search_params([("name", q), ("limit", S(PAGE)), ("offset", S(offset)), ("hidebroken", "true"), ("order", "clickcount"), ("reverse", "true")])
    for base in RADIO_API:
        try:
            lst = jparse(fetchText(f"{base}/json/stations/search?{params}", 8000))
            if isinstance(lst, list):
                return lst
        except Exception:
            pass  # the next mirror
    raise Fail("the radio directory (radio-browser.info) did not answer")


# PAGE results at a time (measured: the directory answers forty as fast as fifteen, SoundCloud takes about
# twice as long for forty); `more` fetches the next page of the same search and appends it. The results file
# says whether a further page can come (`complete`): the directory takes an offset, SoundCloud is asked for a
# longer list, DI.FM is complete at once.
PAGE = 40


def stageSearch(kind, query, more=False):
    q = js_trim(clean(query))
    if not q:
        raise Fail("search for what?", EXIT.usage)
    if u16len(q) > 200:
        raise Fail("that search is too long", EXIT.usage)
    previous = []
    if more:
        old = None
        try:
            old = jparse(read_text(pjoin(RUNTIME, "stage-results.json")))
        except Exception:
            pass  # nothing to add to
        if truthy(old) and gp(old, "kind") == kind and gp(old, "query") == q and isinstance(gp(old, "items"), list):
            if truthy(old.get("complete")):
                return old["items"]
            previous = old["items"]
    items = []
    complete = True
    if kind == "di":
        words = re.split(r"\s+", q.lower())
        for network in AA_NETWORKS:
            for c in aaChannels(network):
                if not isinstance(c, dict):
                    continue
                hay = f'{S(c.get("name"))} {S(c.get("key"))} {AA_NETWORKS[network]["name"]}'.lower()
                if all(w in hay for w in words):
                    items.append({"title": c.get("name"), "kind": "di", "network": network, "channel": c.get("key"), "subtitle": AA_NETWORKS[network]["name"]})
        items = items[:60]
    elif kind == "radio":
        page = radioSearch(q, len(previous))
        complete = len(page) < PAGE
        for s in page:
            # An entry that is not an object has no address, as JavaScript reads it: it is left out.
            if not isinstance(s, dict):
                continue
            src = s.get("url_resolved") if truthy(s.get("url_resolved")) else s.get("url") if truthy(s.get("url")) else ""
            if not re.match(r"https?://", S(src)):
                continue
            codec = s.get("codec")
            rate = " " + S(js_number(s.get("bitrate"))) + "k" if truthy(s.get("bitrate")) else ""
            first = clean(S(codec)) + rate if truthy(codec) else ""
            subtitle = " · ".join(x for x in (first, cut(clean(S(nn(s.get("country"), ""))), 40)) if x)
            items.append({"title": cut(js_trim(clean(S(nn(s.get("name"), "")))), 120) or "unnamed station", "kind": "radio", "url": S(src), "subtitle": subtitle})
    else:
        if not which("yt-dlp"):
            raise Fail("SoundCloud needs yt-dlp: omarchy pkg add yt-dlp", EXIT.notFound)
        want = len(previous) + PAGE
        # No session on the search: it costs 2.8 s to unlock the cookie store on every keystroke that comes to rest,
        # and it buys nothing here. Measured: two identical searches return different results either way, so the
        # difference between signed in and not cannot be told apart from that. The lists keep their session, where
        # it demonstrably adds the private entries.
        r = run(["yt-dlp", "--no-warnings", "--flat-playlist", "-J", f"scsearch{want}:{q}"], 60000 + len(previous) * 500)
        if r.timedOut:
            raise Fail("SoundCloud did not answer within 45 s", EXIT.timeout)
        if r.rc != 0:
            raise Fail("yt-dlp could not search SoundCloud (is it up to date?)")
        try:
            v = jparse(r.out)
        except Exception:
            raise Fail("yt-dlp sent no results")
        entries = gp(v, "entries")
        entries = entries if isinstance(entries, list) else []
        complete = len(entries) < want
        # Only SoundCloud's own pages: a result is later handed to yt-dlp with the browser's cookies, and those are
        # for SoundCloud alone.
        for e in entries:
            if not isinstance(e, dict):
                continue
            page_url = e.get("webpage_url") if truthy(e.get("webpage_url")) else e.get("url") if truthy(e.get("url")) else ""
            if not isSoundcloudPage(S(page_url)):
                continue
            dur = e.get("duration")
            subtitle = " · ".join(x for x in (cut(clean(S(nn(e.get("uploader"), ""))), 60), mmss(dur) if is_num(dur) else "") if x)
            items.append({"title": cut(js_trim(clean(S(nn(e.get("title"), "")))), 120) or "untitled", "kind": "soundcloud", "url": S(page_url), "subtitle": subtitle})
    if previous:
        seen = set(stageId(i) for i in previous)
        items = previous + [i for i in items if stageId(i) not in seen]
    writeRuntime("stage-results.json", jdump({"kind": kind, "query": q, "items": items, "complete": complete}) + "\n")
    return items


def stageResult(n):
    try:
        results = jparse(read_text(pjoin(RUNTIME, "stage-results.json")))
    except Exception:
        raise Fail("search first: ballroom radio search …", EXIT.notFound)
    if not isinstance(results, dict):
        raise TypeError("the results file holds no results")
    i = js_number(n) - 1
    items = results.get("items")
    item = at(items, i) if isinstance(items, list) else None
    if not is_int(i) or not truthy(item):
        count = len(items) if isinstance(items, list) else nn(gp(items, "length"), 0)
        raise Fail(f"no result {n}; the last search had {S(count)}", EXIT.notFound)
    return item


def stageDiNow():
    now = loadNow()
    if not truthy(now) or gp(now, "kind") != "di":
        return ""
    try:
        lst = jparse(fetchText(f'{AA_API}/{S(gp(now, "network"))}/currently_playing'))
    except Fail:
        raise
    except Exception:
        raise Fail("no now-playing list")
    entry = next((x for x in (lst if isinstance(lst, list) else []) if strict_eq(gp(x, "channel_key"), gp(now, "channel"))), None)
    t = gp(entry, "track")
    if truthy(t):
        artist, title = gp(t, "display_artist"), gp(t, "display_title")
        text = cut(clean(f'{S(nn(artist, ""))}{" · " if truthy(artist) and truthy(title) else ""}{S(nn(title, ""))}'), 140)
    else:
        text = ""
    writeRuntime("stage-di-now.json", jdump({"at": now_ms(), "channel": gp(now, "channel"), "text": text}) + "\n")
    return text


def stageOut(extra, text):
    state = stageState()
    js = {"ok": True}
    js.update(extra)
    js["stage"] = state
    return Out(js, maskKey(text), {"icon": "volume-high", "message": f'Stage {state["state"]}: {state["title"]}' if state["title"] else f'Stage {state["state"]}'})


# Resume: a paused track continues, a stopped live stream is tuned in again, otherwise the last thing played.
def stageResume():
    st = stageState()
    if st["state"] == "paused" and st["running"] and mpvGet(["idle-active"])["idle-active"] is False:
        mpvCmd(["set_property", "pause", False])
        sleep_ms(200)
        return stageOut({}, f'resumed: {stageState()["state"]}')
    now = loadNow()
    if truthy(now):
        item = _strip_now(now) if isinstance(now, dict) else {}
    else:
        item = at(loadStage()["recent"], 0)
    if not truthy(item):
        raise Fail("nothing to resume; ballroom play URL, or search first", EXIT.notFound)
    r = stagePlay(item)
    return stageOut({"played": item.get("title", UNDEF), "state": r["state"]}, f'{S(item.get("title", UNDEF))}: {r["state"]}')


def stagePause():
    st = stageState()
    if not st["running"]:
        return stageOut({}, "nothing plays: the stage is off")
    if st["state"] in ("playing", "loading"):
        if st["live"]:
            mpvCmd(["stop"])
            now = loadNow()
            if truthy(now) and st["ours"]:
                saveNow(dict(now, paused=True))
        else:
            mpvCmd(["set_property", "pause", True])
        sleep_ms(200)
    return stageOut({}, f'pause: {stageState()["state"]}')


def _nothing_more(step):
    return f'nothing {"after" if step > 0 else "before"} this one'


def _numbered(items):
    def row(i, x):
        tail = "  · " + S(x.get("subtitle")) if truthy(x.get("subtitle")) else ""
        return f'  {pad_start(str(i + 1), 2)}  {S(x.get("title", UNDEF))}{tail}'
    return "\n".join(row(i, x) for i, x in enumerate(items))


def verbStage(verb, args):
    sub = args[0] if args else None
    rest = args[1:]
    if verb == "stage":
        if not sub or sub == "status":
            st = stageState()
            if not st["available"]:
                line = "stage: mpv is not installed (omarchy pkg add mpv)"
            elif not st["running"]:
                line = "stage: off (ballroom play starts it)"
            else:
                tail = (f', {st["title"]}' + (f' · {st["subtitle"]}' if st["subtitle"] else "")) if st["title"] else ""
                line = f'stage: {st["state"]}{tail}'
            favs = [f'  ★{i + 1}  {f["title"]}  ({S(f["kind"])})' for i, f in enumerate(st["favorites"])]
            return Out({"ok": True, "stage": st}, maskKey("\n".join([line] + favs)))
        if sub == "start":
            ensureStage()
            return stageOut({}, "the stage is running")
        if sub == "quit":
            run(["systemctl", "--user", "stop", STAGE_UNIT], 8000)
            until = now_ms() + 3000
            while now_ms() < until and stageRunning():
                sleep_ms(100)
            return stageOut({}, "mpv still answers on the stage socket (not started by the unit?)" if stageRunning() else "the stage is off")
        if sub == "refresh":
            return stageOut({"now": stageDiNow()}, "refreshed")
        if sub == "clear":
            rm_force(pjoin(RUNTIME, "stage-results.json"))
            return stageOut({}, "results cleared")
        raise Fail("usage: ballroom stage [status|start|quit|refresh|clear]", EXIT.usage)
    if verb == "play":
        what = soundcloudHttps(js_trim(" ".join(args)))
        if not what:
            return stageResume()
        queue = None
        if re.match(r"https?://", what):
            item = {"title": cut(re.sub(r"^https?://", "", what, count=1), 80), "kind": kindOfPath(what), "url": what}
        elif re.fullmatch(r"\*[0-9]+", what) or re.fullmatch(r"fav\s+[0-9]+", what):
            i = js_number(re.sub(r"[^0-9]", "", what)) - 1
            favs = loadStage()["favorites"]
            if not truthy(at(favs, i)):
                raise Fail(f"no favorite {S(i + 1)}", EXIT.notFound)
            item = favs[i]
            queue = queueOf(favs, i)
        elif re.fullmatch(r"~[0-9]+", what):
            i = js_number(what[1:]) - 1
            rec = loadStage()["recent"]
            if not truthy(at(rec, i)):
                raise Fail(f"nothing played {S(i + 1)} ago", EXIT.notFound)
            item = rec[i]
            queue = queueOf(rec, i)
        elif re.fullmatch(r"#?[0-9]+", what):
            n = js_number(what.replace("#", "", 1))
            item = stageResult(S(n))
            queue = queueOf(stageLists()[0]["items"], n - 1)
        elif re.fullmatch(r"id:[0-9]+", what):
            found = stageLocate(what[3:])
            if found is None:
                raise Fail("that entry is gone", EXIT.notFound)
            item, queue = found["item"], found["queue"]
        else:
            favs = loadStage()["favorites"]
            i = next((k for k, x in enumerate(favs) if what.lower() in S(gp(x, "title")).lower()), -1)
            if i < 0:
                raise Fail(f'nothing called "{what}" in the favorites; ballroom radio search {what}', EXIT.notFound)
            item = favs[i]
            queue = queueOf(favs, i)
        if not isinstance(item, dict):
            raise TypeError("that entry is not an item")
        if item.get("kind") == "di" and kindOfPath(S(nn(item.get("url"), ""))) == "di":
            raise Fail("a DI.FM address is not played directly (it carries the key): ballroom di play CHANNEL", EXIT.usage)
        r = stagePlay(item, queue)
        return stageOut({"played": item.get("title", UNDEF), "state": r["state"]},
                        f'{S(item.get("title", UNDEF))}: {"playing" if r["state"] == "playing" else r["state"] + " (streams can take a few seconds)"}')
    if verb == "pause":
        return stagePause()
    if verb == "toggle":
        st = stageState()
        return stagePause() if st["state"] in ("playing", "loading") else stageResume()
    if verb == "stop":
        if not stageRunning():
            return stageOut({}, "nothing plays: the stage is off")
        mpvCmd(["stop"])
        now = loadNow()
        if truthy(now) and truthy(gp(now, "paused")):
            saveNow(dict(now, paused=False))
        sleep_ms(200)
        return stageOut({}, f'stop: {stageState()["state"]}')
    if verb in ("next", "prev"):
        if not stageRunning():
            return stageOut({}, "nothing plays: the stage is off")
        step = 1 if verb == "next" else -1
        # A playlist inside mpv comes first; otherwise the queue, the list the entry was chosen from.
        m = mpvGet(["playlist-count"])
        if js_number(nn(m["playlist-count"], 0)) > 1:
            moved = True
            try:
                mpvCmd(["playlist-next" if verb == "next" else "playlist-prev"])
            except Exception:
                moved = False
            sleep_ms(200)
            return stageOut({"moved": moved}, f'{verb}: {stageState()["state"]}' if moved else _nothing_more(step))
        now = loadNow()
        q = gp(now, "queue")
        q = q if truthy(q) and isinstance(gp(q, "ids"), list) else None
        pos = js_number(q.get("pos", UNDEF)) + step if q is not None else -1
        if q is None or pos < 0 or pos >= len(q["ids"]):
            return stageOut({"moved": False}, _nothing_more(step))
        # A list can hold playlists between its tracks; they are opened, not played, so the walk steps over them.
        ids = q["ids"]
        at_ = pos
        found = stageLocate(at(ids, at_))
        while found is not None and found["item"].get("set") is True:
            at_ += step
            if at_ < 0 or at_ >= len(ids):
                return stageOut({"moved": False}, _nothing_more(step))
            found = stageLocate(at(ids, at_))
        if found is None:
            return stageOut({"moved": False}, "the next entry is gone from its list")
        r = stagePlay(found["item"], {"ids": ids, "pos": at_})
        title = found["item"].get("title", UNDEF)
        return stageOut({"moved": True, "played": title, "state": r["state"]}, f'{S(title)}: {r["state"]}')
    if verb == "seek":
        what = js_trim(nn(sub, ""))
        if not re.fullmatch(r"[+-]?[0-9]+", what):
            raise Fail("usage: ballroom seek SECONDS | +N | -N", EXIT.usage)
        st = stageState()
        if not st["running"] or st["state"] not in ("playing", "paused", "loading"):
            return stageOut({}, "nothing plays")
        if st["live"]:
            raise Fail("a live stream has no position to seek to", EXIT.usage)
        if re.match(r"[+-]", what):
            mpvCmd(["seek", what, "relative"])
        else:
            mpvCmd(["set_property", "time-pos", js_number(what)])
        sleep_ms(150)
        after = stageState()
        return stageOut({"position": after["position"], "duration": after["duration"]},
                        f'at {S(nn(after["position"], 0))} s of {S(nn(after["duration"], 0))}')
    if verb in ("radio", "sc", "di"):
        kind = "soundcloud" if verb == "sc" else verb
        if verb == "di" and sub == "key":
            global _key_cache
            v = js_trim("".join(rest))
            if not v:
                return Out({"ok": True, "diKey": bool(listenKey())},
                           "a listen key is set (not shown); ballroom di key set replaces it, and a single dash instead of a key removes it" if listenKey() else "no listen key; ballroom di key set")
            if v == "-":
                withLock(lambda: saveJson("audioaddict.json", {"schemaVersion": 1, "listenKey": ""}))
                _key_cache = UNDEF
                return Out({"ok": True, "diKey": False}, "listen key removed")
            if v != "set":
                raise Fail("the key is not taken as an argument (it would land in the shell history and in the process list): ballroom di key set, then type or pipe it", EXIT.usage)
            k = readSecret("DI.FM listen key:")
            if not k:
                raise Fail("no key given", EXIT.usage)
            diKeySet(k)
            return Out({"ok": True, "diKey": True}, "listen key accepted by DI.FM, and kept (not shown)")
        if verb == "di" and sub in ("channels", "list"):
            nets = [rest[0]] if rest and rest[0] else list(AA_NETWORKS)
            for n in nets:
                if n not in AA_NETWORKS:
                    raise Fail(f'no network {n}; one of {", ".join(AA_NETWORKS)}', EXIT.usage)
            al = []
            for n in nets:
                al += aaChannels(n)
            return Out({"ok": True, "channels": al}, "\n".join(f'{pad_end(AA_NETWORKS[c["network"]]["name"], 15)} {S(c["name"])}' for c in al))
        if verb == "di" and sub == "play":
            q = js_trim(" ".join(rest)).lower()
            al = []
            for n in AA_NETWORKS:
                al += aaChannels(n)
            c = next((x for x in al if x.get("key") == q or S(x.get("name")).lower() == q), None) or next((x for x in al if q in S(x.get("name")).lower()), None)
            if not q or c is None:
                raise Fail(f'no channel "{q}"; ballroom di search {q}', EXIT.notFound)
            item = {"title": c["name"], "kind": "di", "network": c["network"], "channel": c["key"], "subtitle": AA_NETWORKS[c["network"]]["name"]}
            r = stagePlay(item)
            return stageOut({"played": c["name"], "state": r["state"]}, f'{AA_NETWORKS[c["network"]]["name"]} {S(c["name"])}: {r["state"]}')
        if verb == "sc" and sub in ("browsers", "cookies"):
            if sub == "browsers":
                found = browserStores()
                # The path stays here: the panel names a browser and the command knows where that browser keeps it.
                return Out({"ok": True, "browsers": [{"browser": b["browser"], "label": b["label"], "soundcloud": b["soundcloud"], "readable": b["readable"]} for b in found]},
                           "\n".join(f'  {chr(0x2605) if b["soundcloud"] else " "} {b["label"]}{"" if b["readable"] else "  (its store could not be opened)"}' for b in found)
                           if found else "no browser keeps a cookie store here")
            want = js_trim(" ".join(rest))

            def shown():
                v = js_trim(S(nn(widgetValues().get("soundcloudCookies"), "")))
                return v.split(":")[0].split("+")[0] if v and v != COOKIES_OFF else "none"
            if not want:
                return Out({"ok": True, "cookies": shown()}, "no browser session is read; ballroom sc cookies auto or BROWSER chooses one" if shown() == "none" else f"cookies from {shown()}")
            if want == "-" or want == COOKIES_OFF:
                setWidgetValue("soundcloudCookies", COOKIES_OFF)
                return Out({"ok": True, "cookies": "none"}, "no browser session is read any more")
            # auto: the first store that carries a SoundCloud session. A browser named by hand is matched against
            # what was found, so the profile comes along; a name nothing matches is kept as it was typed.
            found = browserStores()
            if want == "auto":
                pick = next((b for b in found if b["soundcloud"]), None)
            else:
                pick = next((b for b in found if b["browser"] == want.lower() and b["soundcloud"]), None) or next((b for b in found if b["browser"] == want.lower()), None)
            if want == "auto" and pick is None:
                raise Fail("no browser here is signed in on SoundCloud; sign in in the browser, or name it: ballroom sc cookies brave", EXIT.notFound)
            if pick is None and not cookieSpecOk(want):
                raise Fail("that is not a browser name like brave, or brave:/path/to/profile", EXIT.usage)
            # The same walk the automatic choice takes: a Chromium store from version 11 on needs the keyring, and
            # the plain browser:profile spec reads none of it (measured: 0 of 747 cookies without it). Keeping the
            # spec without asking stored something that could never work, and the account came back nameless.
            value = pick["value"] if pick is not None else want
            if pick is not None and which("yt-dlp"):
                spec = resolveCookieSpec(pick)
                if not spec:
                    raise Fail(f'the cookie store of {pick["browser"]} could not be unlocked; unlock your keyring, or name the profile: ballroom sc name NAME', EXIT.notFound)
                value = spec
            elif pick is not None:
                warnings.append("yt-dlp is not installed, so the browser session could not be tried; it is kept as it is")
            setWidgetValue("soundcloudCookies", value)
            if pick is not None:
                text = f'cookies from {pick["label"]}{", signed in on SoundCloud" if pick["soundcloud"] else ", no SoundCloud session in it"}'
            else:
                text = f"cookies from {want}"
            return Out({"ok": True, "cookies": pick["browser"] if pick is not None else want, "soundcloud": pick["soundcloud"] if pick is not None else None}, text)
        if verb == "sc" and sub == "whoami":
            who = soundcloudWhoami()
            if not who:
                raise Fail("the browser session does not say who it belongs to; name the profile: ballroom sc name NAME", EXIT.notFound)
            if (rest[0] if rest else None) != "--show":
                setWidgetValue("soundcloudUser", who)
            return Out({"ok": True, "user": who}, who)
        if verb == "sc" and sub == "name":
            want = js_trim(" ".join(rest))
            if not want:
                v = js_trim(S(nn(widgetValues().get("soundcloudUser"), "")))
                return Out({"ok": True, "user": v}, v or "no name; ballroom sc name NAME, or ballroom sc whoami with a signed-in browser")
            if want == "-":
                setWidgetValue("soundcloudUser", "")
                return Out({"ok": True, "user": ""}, "the name is gone")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", want):
                raise Fail("a SoundCloud name is letters, digits, dots, dashes and underscores", EXIT.usage)
            setWidgetValue("soundcloudUser", want)
            return Out({"ok": True, "user": want}, want)
        if verb == "sc" and sub in ("likes", "list"):
            # sc list [WHAT] [NAME]: named, the list has to be one of the four, or a profile name would silently be
            # taken for a list and the wrong page fetched.
            rest = list(rest)
            what = "likes" if sub == "likes" else S(rest.pop(0)) if rest else "likes"
            r = soundcloudList(what, " ".join(rest))
            return stageOut({"what": what, "count": len(r["items"]), "user": r["user"]},
                            _numbered(r["items"]) if r["items"] else f'nothing in the {what} of {r["user"]}')
        if verb == "sc" and sub == "open":
            first = rest[0] if rest else ""
            i = first[3:] if re.fullmatch(r"id:[0-9]+", first) else ""
            item = stageById(i) if i else None
            if not truthy(item):
                raise Fail("name a playlist by its id: ballroom sc open id:N", EXIT.notFound)
            items = soundcloudOpen(item)
            return stageOut({"opened": item.get("title", UNDEF), "tracks": len(items)}, f'{S(item.get("title", UNDEF))}: {len(items)} tracks')
        if sub == "search":
            more = "--more" in rest
            items = stageSearch(kind, " ".join(w for w in rest if w != "--more"), more)
            return stageOut({"results": len(items)}, _numbered(items) if items else "nothing found")
        if sub == "play":
            r0 = stageResult(rest[0] if rest else "")
            r = stagePlay(r0)
            return stageOut({"played": r0.get("title", UNDEF), "state": r["state"]}, f'{S(r0.get("title", UNDEF))}: {r["state"]}')
        extra = (" | di channels [NETWORK] | di play CHANNEL | di key [set|-]" if verb == "di"
                 else " | sc list [likes|playlists|uploads|reposts] [NAME] | sc open id:N | sc browsers | sc cookies [auto|BROWSER|-] | sc name [NAME|-] | sc whoami" if verb == "sc" else "")
        raise Fail(f"usage: ballroom {verb} search QUERY | {verb} play N{extra}", EXIT.usage)
    if verb == "fav":
        return withLock(lambda: favNow(sub, rest))
    raise Fail(f"unknown verb {verb}", EXIT.usage)


def favNow(sub, rest):
    store = loadStage()
    first = rest[0] if rest else None
    if not sub or sub == "list":
        return stageOut({}, "\n".join(f'  ★{i + 1}  {S(gp(f, "title"))}  ({S(gp(f, "kind"))})' for i, f in enumerate(store["favorites"])) or "no favorites; ballroom fav add")
    if sub == "add":
        item = None
        if first and re.fullmatch(r"id:[0-9]+", first):
            item = stageById(first[3:])
            if not truthy(item):
                raise Fail("that entry is gone", EXIT.notFound)
        elif first and re.fullmatch(r"#?[0-9]+", first):
            item = stageResult(first.replace("#", "", 1))
        else:
            item = stageNowItem()
        if not truthy(item):
            raise Fail("nothing to add: play something, or name a search result (ballroom fav add 3)", EXIT.notFound)
        # A favorite is something that plays. A playlist is opened, and a kept playlist would have no answer to
        # the question what it should play.
        if item.get("set") is True:
            raise Fail("a playlist is opened, not kept: ballroom sc open id:N, then keep a track from it", EXIT.usage)
        # A SoundCloud hit is kept by its page address, which is resolved again when it plays.
        if not any(_same_item(a, item) for a in store["favorites"]):
            store["favorites"].append(dict(item))
        saveJson("stage.json", store)
        return stageOut({"added": item.get("title", UNDEF)}, f'★ {S(item.get("title", UNDEF))}')
    if sub == "rm":
        if re.fullmatch(r"id:[0-9]+", nn(first, "")):
            i = next((k for k, f in enumerate(store["favorites"]) if stageId(f) == first[3:]), -1)
        else:
            i = js_number(first) - 1
        if not truthy(at(store["favorites"], i)):
            raise Fail(f'no favorite {nn(first, "")}', EXIT.notFound)
        gone = store["favorites"].pop(int(i))
        saveJson("stage.json", store)
        return stageOut({"removed": gp(gone, "title")}, f'removed {S(gp(gone, "title"))}')
    if sub == "play":
        return verbStage("play", [f'*{nn(first, "")}'])
    raise Fail("usage: ballroom fav [list|add [N]|rm N|play N]", EXIT.usage)


# ---------------------------------------------------------------- desk: scenes, diagnosis, keys
# A scene is what the desk is set to: the default output and input, the level and mute of every device, the
# equalizer and its preset, the mode and codec of Bluetooth devices, and what the stage plays. `scene use`
# brings the graph back to it, in this order: output (with its cap and its preset), levels, input, equalizer,
# Bluetooth, stage. Everything is read back afterwards (rule 1), and what is not there right now is skipped and
# named, not invented. An input is never unmuted by a scene: a scene may close a microphone, never open one.
# A scene: savedAt, defaultOutput, defaultInput, outputs and inputs ({volume, mute} by node.name), eq {enabled,
# preset}, bt ({mode, codec} by address), stage (an item or null).
def loadScenes():
    return loadJson("scenes.json", {"schemaVersion": 1, "scenes": {}}, lambda v: isObject(v.get("scenes")))


# A scene name is a label, not a path: printable, short, no tab (lists key rows by it).
def sceneName(raw):
    name = js_trim(raw)
    if not name:
        raise Fail("a scene needs a name: ballroom scene save NAME", EXIT.usage)
    if re.search(r"[\x00-\x1f\x7f-\x9f]", name):
        raise Fail("a scene name has no control characters", EXIT.usage)
    if u16len(name) > 40:
        raise Fail("a scene name is at most 40 characters", EXIT.usage)
    return name


def sceneLevel(d):
    return {"volume": js_round(d["volume"] * 100) / 100, "mute": d["mute"]}


def _iso_now():
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % (int(t * 1000) % 1000)


def sceneCapture(g):
    outputs, inputs = {}, {}
    for d in g["outputs"]:
        if not d["filter"]:
            outputs[d["name"]] = sceneLevel(d)
    for d in g["inputs"]:
        if not d["filter"]:
            inputs[d["name"]] = sceneLevel(d)
    bt = {}
    for b in btDevices(g):
        bt[b["address"]] = {"mode": btModeNow(b), "codec": btCodecNow(b)}
    try:
        stage = stageNowItem()
    except Exception:
        stage = None
    plan = soundPlan(g)
    return {"savedAt": _iso_now(), "defaultOutput": g["defaultSink"], "defaultInput": g["defaultSource"],
            "outputs": outputs, "inputs": inputs, "eq": {"enabled": loadSound()["enabled"], "preset": plan["presetName"] if truthy(plan["device"]) else None},
            "bt": bt, "stage": stage}


def sceneSummary(g, s):
    def label(name, lst):
        if not truthy(name):
            return "none"
        d = find_by_name(lst, name)
        return S(nn(d["label"], name)) if d is not None else S(name)
    do = s.get("defaultOutput")
    lv = gp(s, "outputs", do) if isinstance(do, str) else None
    eq = s.get("eq") or {}
    level = f' {percent(_lv(lv, "volume"))} %' if truthy(do) and truthy(lv) else ""
    first = label(do, g["outputs"]) + level
    eq_text = js_trim(f'eq {S(nn(gp(eq, "preset"), ""))}') if truthy(gp(eq, "enabled")) else "eq off"
    stage = s.get("stage")
    return " · ".join([first, f'{len(s.get("outputs") or {})} outputs', eq_text, f'stage: {S(gp(stage, "title"))}' if truthy(stage) else "stage off"])


# Applies a scene and reports every step; a device or preset that is not there is skipped by name.
def sceneApply(name):
    s = loadScenes()["scenes"].get(name)
    if not truthy(s):
        raise Fail(f'no scene "{name}"; ballroom scene list', EXIT.notFound)
    applied, skipped, mismatched = [], [], []

    def attempt(what, f):
        try:
            f()
            applied.append(what)
        except Exception as e:
            skipped.append(f"{what}: {fail_text(e, 'failed')}")
    g = readGraph()

    def present(n, lst):
        return next((d for d in lst if d["name"] == n and not d["filter"]), None)
    # 1. The default output, through the verb: cap first, then the equalizer follows with the device's preset.
    if truthy(s.get("defaultOutput")):
        d = present(s["defaultOutput"], g["outputs"])
        if d is None:
            skipped.append(f'output {S(s["defaultOutput"])}: not present')
        elif not d["isDefault"]:
            attempt(f'output {S(d["label"])}', lambda: verbOut([d["name"]]))
    g = readGraph()
    # 2. Levels and mutes of every output the scene knows and the graph has.
    for n, lv in (s.get("outputs") or {}).items():
        d = present(n, g["outputs"])
        if d is None:
            skipped.append(f"output {n}: not present")
            continue
        if abs(d["volume"] - _tonum(_lv(lv, "volume"))) > 0.005:
            attempt(f'{S(d["label"])} {percent(_lv(lv, "volume"))} %', lambda d=d, lv=lv: setVolume(d["name"], _lv(lv, "volume")))
        if not strict_eq(d["mute"], _lv(lv, "mute")):
            attempt(f'{S(d["label"])} {"muted" if truthy(_lv(lv, "mute")) else "unmuted"}', lambda d=d, lv=lv: setMute(d["id"], _lv(lv, "mute")))
    # 3. The default input through its verb (a muted microphone stays muted), then levels; never an unmute.
    if truthy(s.get("defaultInput")):
        d = present(s["defaultInput"], g["inputs"])
        if d is None:
            skipped.append(f'input {S(s["defaultInput"])}: not present')
        elif not d["isDefault"]:
            attempt(f'input {S(d["label"])}', lambda: verbIn([d["name"]]))
    g = readGraph()
    for n, lv in (s.get("inputs") or {}).items():
        d = present(n, g["inputs"])
        if d is None:
            skipped.append(f"input {n}: not present")
            continue
        if abs(d["volume"] - _tonum(_lv(lv, "volume"))) > 0.005:
            attempt(f'{S(d["label"])} {percent(_lv(lv, "volume"))} %', lambda d=d, lv=lv: setVolume(d["name"], _lv(lv, "volume")))
        if truthy(_lv(lv, "mute")) and not d["mute"]:
            attempt(f'{S(d["label"])} muted', lambda d=d: setMute(d["id"], True))
        elif not truthy(_lv(lv, "mute")) and d["mute"]:
            skipped.append(f'{S(d["label"])}: stays muted (a scene never opens a microphone)')
    # 4. The equalizer: the preset of the default output, then on or off, each one change and one click.
    eq = s.get("eq") or {}
    preset = eq.get("preset")
    if truthy(preset) and preset in allPresets():
        if soundPlan(readGraph())["presetName"] != preset:
            attempt(f"equalizer preset {preset}", lambda: verbEq(["preset", "use", preset]))
    elif truthy(preset):
        skipped.append(f"equalizer preset {S(preset)}: no such preset")
    if not strict_eq(loadSound()["enabled"], eq.get("enabled")):
        attempt(f'equalizer {"on" if truthy(eq.get("enabled")) else "off"}', lambda: verbEq(["on" if truthy(eq.get("enabled")) else "off"]))
    # 5. Bluetooth: mode and codec, each a guarded profile switch.
    g = readGraph()
    for address, want in (s.get("bt") or {}).items():
        b = next((x for x in btDevices(g) if x["address"] == address), None)
        if b is None:
            masked = re.sub(r"[0-9A-Fa-f]{2}(?=(:|\Z))", "xx", address)
            skipped.append(f"Bluetooth device {masked}: not connected")
            continue
        if want.get("mode") != "off" and btModeNow(b) != want.get("mode"):
            def switch_mode(b=b, want=want):
                if not btSetMode(b, want["mode"])["ok"]:
                    raise Fail("did not switch")
            attempt(f'{S(b["label"])} {S(want.get("mode"))} mode', switch_mode)
        if truthy(want.get("codec")) and want.get("mode") == "music":
            now = next((x for x in btDevices(readGraph()) if x["address"] == address), None)
            if now is not None and S(nn(btCodecNow(now), "")).lower() != S(want["codec"]).lower():
                def switch_codec(now=now, want=want):
                    if not btSetCodec(now, want["codec"])["ok"]:
                        raise Fail("did not switch")
                attempt(f'{S(b["label"])} codec {S(want["codec"])}', switch_codec)
    # 6. The stage: play what the scene played, or stop what plays when the scene had nothing.
    stage = s.get("stage")
    if truthy(stage):
        if not stageInstalled():
            skipped.append(f'stage: {S(gp(stage, "title"))} (mpv is not installed)')
        else:
            try:
                r = stagePlay(stage)
                applied.append(f'stage: {S(gp(stage, "title"))} ({r["state"]})')
            except Exception as e:
                skipped.append(f'stage: {S(gp(stage, "title"))}: {fail_text(e, "failed")}')
    elif stageRunning():
        st = stageState()
        if st["state"] in ("playing", "loading", "paused"):
            try:
                mpvCmd(["stop"])
                now = loadNow()
                if truthy(gp(now, "paused")):
                    saveNow(dict(now, paused=False))
                applied.append("stage: stopped")
            except Exception:
                skipped.append("stage: could not stop")
    # Rule 1: what the graph says now, against the scene.
    after = readGraph()
    if truthy(s.get("defaultOutput")) and present(s["defaultOutput"], after["outputs"]) is not None and after["defaultSink"] != s["defaultOutput"]:
        mismatched.append(f'default output is {S(nn(after["defaultSink"], "none"))}')
    if truthy(s.get("defaultInput")) and present(s["defaultInput"], after["inputs"]) is not None and after["defaultSource"] != s["defaultInput"]:
        mismatched.append(f'default input is {S(nn(after["defaultSource"], "none"))}')
    for n, lv in (s.get("outputs") or {}).items():
        d = present(n, after["outputs"])
        if d is not None and (abs(d["volume"] - _tonum(_lv(lv, "volume"))) > 0.02 or not strict_eq(d["mute"], _lv(lv, "mute"))):
            mismatched.append(f'{S(d["label"])} is at {percent(d["volume"])} %{" muted" if d["mute"] else ""}')
    return {"applied": applied, "skipped": skipped, "mismatched": mismatched}


def verbScene(args):
    sub = args[0] if args else None
    if sub in ("save", "rm", "use"):
        return withLock(lambda: sceneNow(args))
    return sceneNow(args)


def sceneNow(args):
    sub = args[0] if args else None
    rest = args[1:]
    store = loadScenes()
    g = readGraph()
    if not sub or sub == "list":
        names = js_sorted(list(store["scenes"].keys()))
        return Out({"ok": True, "scenes": [{"name": n, "savedAt": gp(store["scenes"][n], "savedAt"), "summary": sceneSummary(g, store["scenes"][n])} for n in names]},
                   "\n".join(f'  {pad_end(n, 24)} {sceneSummary(g, store["scenes"][n])}' for n in names) if names else "no scenes; ballroom scene save NAME keeps what is set now")
    if sub == "save":
        name = sceneName(" ".join(rest))
        scene = sceneCapture(g)
        store["scenes"][name] = scene
        saveJson("scenes.json", store)
        return Out({"ok": True, "saved": name, "scene": scene}, f"scene {name}: {sceneSummary(g, scene)}")
    if sub == "show":
        name = sceneName(" ".join(rest))
        s = store["scenes"].get(name)
        if not truthy(s):
            raise Fail(f'no scene "{name}"; ballroom scene list', EXIT.notFound)

        def label(n, lst):
            d = find_by_name(lst, n)
            return S(d["label"]) if d is not None else f"{S(n)} (not present)"
        eq = s.get("eq") or {}
        stage = s.get("stage")
        lines = [f'scene {name}, saved {cut(S(s.get("savedAt", UNDEF)), 16).replace("T", " ", 1)}',
                 f'  output  {label(s["defaultOutput"], g["outputs"]) if truthy(s.get("defaultOutput")) else "none"}',
                 f'  input   {label(s["defaultInput"], g["inputs"]) if truthy(s.get("defaultInput")) else "none"}']
        lines += [f'  out {pad_end(label(n, g["outputs"]), 28)} {pad_start(S(percent(_lv(lv, "volume"))), 3)} %{"  muted" if truthy(_lv(lv, "mute")) else ""}' for n, lv in (s.get("outputs") or {}).items()]
        lines += [f'  in  {pad_end(label(n, g["inputs"]), 28)} {pad_start(S(percent(_lv(lv, "volume"))), 3)} %{"  muted" if truthy(_lv(lv, "mute")) else ""}' for n, lv in (s.get("inputs") or {}).items()]
        lines.append(f'  eq      {"on, " + S(nn(eq.get("preset"), "no preset")) if truthy(eq.get("enabled")) else "off"}')
        for a, b in (s.get("bt") or {}).items():
            dev = next((x for x in btDevices(g) if x["address"] == a), None)
            lines.append(f'  bt      {S(dev["label"]) if dev is not None else "a device that is not connected"}: {S(b.get("mode"))}{", " + S(b["codec"]) if truthy(b.get("codec")) else ""}')
        lines.append(f'  stage   {S(gp(stage, "title")) + " (" + S(gp(stage, "kind")) + ")" if truthy(stage) else "nothing"}')
        return Out({"ok": True, "name": name, "scene": s}, maskKey("\n".join(lines)))
    if sub == "rm":
        name = sceneName(" ".join(rest))
        if not truthy(store["scenes"].get(name)):
            raise Fail(f'no scene "{name}"', EXIT.notFound)
        del store["scenes"][name]
        saveJson("scenes.json", store)
        return Out({"ok": True, "removed": name}, f"removed scene {name}")
    if sub == "use":
        name = sceneName(" ".join(rest))
        r = sceneApply(name)
        text = "\n".join([f'scene {name}: {", ".join(r["applied"]) if r["applied"] else "nothing to change"}']
                         + [f"  skipped: {x}" for x in r["skipped"]] + [f"  not as saved: {x}" for x in r["mismatched"]])
        js = {"ok": True, "used": name}
        js.update(r)
        return Out(js, maskKey(text), {"icon": "volume-high", "message": f"Scene {name}"})
    raise Fail("usage: ballroom scene [list|save NAME|use NAME|show NAME|rm NAME]", EXIT.usage)


# ---- diagnosis
# A check: key, state ("ok", "warn" or "bad"), text.
DUMMY_SINK = "auto_null"
CHECK_GLYPH = {"ok": "✓", "warn": "!", "bad": "✗"}


# Where the names of the nodes a node feeds are read: the equalizer's output should feed the default output.
def feeds(g, nodeName):
    byId = {}
    for o in g["objects"]:
        if gp(o, "type") == "PipeWire:Interface:Node":
            byId[o.get("id")] = S(nn(gp(o, "info", "props", "node.name"), ""))
    frm = next((i for i, n in byId.items() if n == nodeName), UNDEF)
    if frm is UNDEF:
        return []
    return _unique(byId.get(gp(o, "info", "input-node-id"), "?") for o in g["objects"]
                   if gp(o, "type") == "PipeWire:Interface:Link" and strict_eq(gp(o, "info", "output-node-id"), frm))


# The fragments a user or another plugin put into PipeWire's and WirePlumber's drop-in directories. One that
# builds a filter is worth knowing about: Ballroom has none, and two filters in front of one output stack.
def filterFragments():
    base = nn(ENV.get("XDG_CONFIG_HOME"), pjoin(HOME, ".config"))
    dirs = [pjoin(base, "wireplumber", "wireplumber.conf.d"), pjoin(base, "pipewire", "pipewire.conf.d"), pjoin(base, "pipewire", "filter-chain.conf.d")]
    found = []
    for d in dirs:
        try:
            names = [f for f in os.listdir(d) if f.endswith(".conf")]
        except OSError:
            continue
        for f in names:
            try:
                text = read_text(pjoin(d, f))
                if re.search(r"filter-chain|filter\.smart", text):
                    found.append(pjoin(d, f).replace(HOME, "~", 1))
            except OSError:
                pass  # unreadable, not ours to judge
    return found


# pw-top's one shot: the ERR column counts xruns per node. Columns are read by the header's positions, because
# the FORMAT column is empty for a node that does not run and would shift a split by whitespace.
def xruns():
    r = run(["pw-top", "-b", "-n", "1"], 4000)
    if r.rc != 0 or r.timedOut:
        return {"total": 0, "nodes": [], "available": False}
    lines = r.out.split("\n")
    header = next((l for l in lines if re.search(r"\bERR\b", l, re.ASCII) and re.search(r"\bNAME\b", l, re.ASCII)), None)
    if header is None:
        return {"total": 0, "nodes": [], "available": False}
    errFrom, errTo, nameAt = header.find("B/Q") + 3, header.find("FORMAT"), header.find("NAME")
    total = 0
    nodes = []
    for l in lines[lines.index(header) + 1:]:
        if len(l) < nameAt:
            continue
        err = js_number(js_trim(l[errFrom:errTo] if errTo >= 0 else l[errFrom:len(l) + errTo]))
        if not (is_num(err) and math.isfinite(err)) or err <= 0:
            continue
        total += err
        nodes.append(f"{clean(js_trim(l[nameAt:] if nameAt >= 0 else l[len(l) + nameAt:]))} ({S(err)})")
    return {"total": total, "nodes": nodes, "available": True}


# Ballroom 0.1.x copied the command to ~/.local/bin. A copy left there keeps running for the terminal and for key
# bindings, with whatever it knew then; only a link to this very file is this Ballroom.
LOCAL_COMMAND = pjoin(HOME, ".local", "bin", "ballroom")


def oldCommand():
    try:
        st = os.lstat(LOCAL_COMMAND)
    except FileNotFoundError:
        return None
    except OSError:
        return "there but cannot be read"
    if not _stat.S_ISLNK(st.st_mode):
        return "a copy of its own"
    try:
        if os.path.realpath(LOCAL_COMMAND) == pjoin(os.path.dirname(os.path.realpath(__file__)), "ballroom"):
            return None
    except OSError:
        pass
    return "a link to another file"


def doctor():
    checks = []

    def add(key, state, text):
        checks.append({"key": key, "state": state, "text": clean(text)})
    t0 = now_ms()
    g = readGraph()
    took = now_ms() - t0
    add("graph", "ok", f'PipeWire answers, {len(g["objects"])} objects in {took} ms')
    wp = (any(gp(o, "type") == "PipeWire:Interface:Client" and gp(o, "info", "props", "application.process.binary") == "wireplumber" for o in g["objects"])
          and any(gp(o, "type") == "PipeWire:Interface:Metadata" and gp(o, "props", "metadata.name") == "default" for o in g["objects"]))
    add("wireplumber", "ok" if wp else "bad", "WirePlumber is connected and holds the defaults" if wp else "WirePlumber is not connected: no defaults, no routing")
    pulse = run(["pactl", "info"], 2000)
    add("pulse", "ok" if pulse.rc == 0 else "warn" if pulse.rc == 127 else "bad",
        "pipewire-pulse answers" if pulse.rc == 0 else "pactl is not installed, pipewire-pulse not checked" if pulse.rc == 127 else "pipewire-pulse does not answer: applications that speak PulseAudio have no sound")
    units = run(["systemctl", "--user", "is-active", "pipewire", "wireplumber", "pipewire-pulse", EQ_UNIT, STAGE_UNIT], 3000)
    if units.rc == 127 or units.timedOut:
        add("units", "warn", "systemd --user is not reachable; the services were not checked")
    else:
        names = ["pipewire", "wireplumber", "pipewire-pulse", EQ_UNIT, STAGE_UNIT]
        states = js_trim(units.out).split("\n")

        def state(i):
            return states[i] if i < len(states) else "?"
        core = [f"{n} {state(i)}" for i, n in enumerate(names[:3])]
        coreOk = all(x == "active" for x in states[:3])
        add("units", "ok" if coreOk else "warn", f'{", ".join(core)}; {EQ_UNIT} {state(3)}, {STAGE_UNIT} {state(4)}')
    md = run(["pw-metadata", "-n", "settings", "0"], 2000).out

    def setting(k):
        m = re.search("key:'" + k.replace(".", "\\.", 1) + "' value:'([^']*)'", md)
        return m.group(1) if m else None
    forced = [v for v in (js_number(nn(setting("clock.force-quantum"), 0)), js_number(nn(setting("clock.force-rate"), 0))) if v > 0]
    add("clock", "warn" if forced else "ok",
        f'{nn(setting("clock.rate"), "?")} Hz, quantum {nn(setting("clock.quantum"), "?")} ({nn(setting("clock.min-quantum"), "?")} to {nn(setting("clock.max-quantum"), "?")}){"; a forced quantum or rate is set by something else" if forced else ""}')
    x = xruns()
    add("xruns", "warn" if not x["available"] else "warn" if x["total"] else "ok",
        "pw-top did not answer; xruns not counted" if not x["available"] else f'{S(x["total"])} xruns since the nodes started: {", ".join(x["nodes"])}' if x["total"] else "no xruns on any node")
    # PipeWire puts a dummy sink (auto_null) in place when no device is left: sound goes nowhere, and that is
    # reported as no output, not as an output called Dummy.
    out = next((d for d in g["outputs"] if d["isDefault"] and not d["filter"] and d["name"] != DUMMY_SINK), None)
    onFilter = out is None and any(d["isDefault"] and d["filter"] for d in g["outputs"])
    if out is None:
        out_text = "the default output is the equalizer's own node with no device behind it: nothing plays anywhere" if onFilter else "no output: PipeWire plays into a dummy sink, nothing is heard"
    else:
        out_text = (f'{S(out["label"])}, {percent(out["volume"])} %{", muted" if out["mute"] else ""}{"" if out["available"] else ", unplugged"}'
                    f'{", " + S(out["codec"]).upper() if truthy(out["codec"]) else ""}')
    add("output", "bad" if out is None else "warn" if not out["available"] else "ok", out_text)
    inp = next((d for d in g["inputs"] if d["isDefault"]), None)
    add("input", "warn" if inp is None else "ok", "no default input" if inp is None else f'{S(inp["label"])}, {percent(inp["volume"])} %{", muted" if inp["mute"] else ""}')
    snd = loadSound()
    node = eqNode(g)
    if truthy(snd["enabled"]) and node is None:
        add("eq", "bad", "the equalizer is on but its process is not running: ballroom eq restart")
    elif truthy(snd["enabled"]) and node is not None:
        fed = feeds(g, f"{EQ_NODE}.output")
        inFront = truthy(g["defaultSink"]) and g["defaultSink"] in fed
        add("eq", "ok" if inFront else "warn",
            f'on, preset {soundPlan(g)["presetName"]}, in front of {S(out["label"]) if out is not None else S(g["defaultSink"])}' if inFront
            else f'on and running, but not in front of the default output (feeds {", ".join(fed) if fed else "nothing"}); ballroom apply')
    else:
        add("eq", "ok", "off; the process idles neutral so that nothing is interrupted" if node is not None else "off")
    ff = foreignFilters(g)
    add("foreign", "warn" if ff else "ok", f'another filter is in front of the output: {", ".join(ff)} (Ballroom does not touch it; two filters stack)' if ff else "no foreign filter in front of the output")
    frags = filterFragments()
    add("fragments", "warn" if frags else "ok", f'a configuration fragment builds a filter: {", ".join(frags)} (not Ballroom\'s; it may fight the equalizer)' if frags else "no fragment builds a filter")
    st = stageState()
    add("stage", "warn" if not st["available"] else "ok",
        "mpv is not installed: no stage (omarchy pkg add mpv)" if not st["available"] else f'mpv present, {st["state"] if st["running"] else "off"}{"" if which("yt-dlp") else "; yt-dlp is not installed, so no SoundCloud"}')
    tools = [(t, why) for t, why in (("cava", "no spectrum"), ("mpv", "nothing plays"), ("yt-dlp", "no SoundCloud")) if not which(t)]
    add("tools", "warn" if tools else "ok", "; ".join(f"{t} is not installed ({why})" for t, why in tools) if tools else "cava, mpv and yt-dlp are installed")
    old = oldCommand()
    add("command", "warn" if old else "ok",
        f"~/.local/bin/ballroom is {old}, not a link to this Ballroom: the terminal and key bindings may run an older one. Run install.sh again, or remove the old copy"
        if old else "the ballroom in ~/.local/bin is this one" if os.path.lexists(LOCAL_COMMAND) else "no other ballroom in ~/.local/bin")
    rules = loadRules()
    here = routesIn(rules, g["setup"])
    stale = [app for app in here if not any(s["app"] == app for s in g["streams"])]
    elsewhere = len([k for k in rules["routes"] if k != g["setup"]])
    settings_text = (f'{len(loadDevices()["devices"])} device entries, {len(here)} routes in this setup'
                     f'{f" ({len(stale)} for applications that do not play right now)" if stale else ""}'
                     f'{f", rules for {elsewhere} other setups" if elsewhere else ""}, {len(loadScenes()["scenes"])} scenes')
    add("settings", "bad" if warnings else "ok", "; ".join(warnings) if warnings else settings_text)
    return checks


def verbDoctor():
    checks = doctor()

    def count(s):
        return len([c for c in checks if c["state"] == s])
    return Out({"ok": True, "checks": checks, "summary": {"ok": count("ok"), "warn": count("warn"), "bad": count("bad")}},
               maskKey("\n".join(f'{CHECK_GLYPH[c["state"]]} {pad_end(c["key"], 12)} {c["text"]}' for c in checks)))


# The cheap version for the widget, from the graph alone: what the panel foot warns about every second.
def health(g):
    out = []
    df = next((d for d in g["outputs"] if d["isDefault"] and not d["filter"] and d["name"] != DUMMY_SINK), None)
    if df is None:
        out.append("no output behind the equalizer" if any(d["isDefault"] and d["filter"] for d in g["outputs"]) else "no output: PipeWire plays into a dummy sink")
    elif not df["available"]:
        out.append(f'{S(df["label"])} is unplugged')
    if truthy(loadSound()["enabled"]) and eqNode(g) is None:
        out.append("the equalizer is on but not running")
    ff = foreignFilters(g)
    if ff:
        out.append(f'another filter is in front of the output: {", ".join(ff)}')
    return out


# ---- keys
# `--osd` after a verb shows the result on Omarchy's on-screen display, the way the media keys do, so that a
# key binding can call `ballroom vol +5 --osd` instead of the stock scripts and keep caps and routes.
def showOsd(osd):
    if not which("omarchy-osd"):
        return
    args = ["omarchy-osd", "-i", osd["icon"]]
    if osd.get("percent") is not None:
        args += ["-p", S(js_max(0, js_min(100, js_round(osd["percent"]))))]
    if truthy(osd.get("message")):
        args += ["-m", cut(clean(S(osd["message"])), 80)]
    run(args, 2000)


# The output after the default one, among those that are plugged in and not hidden, in the order they are listed.
def nextOutput(g):
    lst = [d for d in g["outputs"] if not d["filter"] and not d["hidden"] and d["available"]]
    if not lst:
        raise Fail("no output is plugged in", EXIT.notFound)
    i = next((k for k, d in enumerate(lst) if d["isDefault"]), -1)
    return lst[(i + 1) % len(lst)]


# ---- what the terminal shows, and the widget's own settings
# This is the only surface in the terminal: there is no second one to keep in step with the panel. `ballroom
# help` is where a verb is found, and every verb prints for a person and, with --json, for a program.
# A name from the graph is text from outside; a control character in it could repaint the terminal.
# Bidi controls are in the class as well: a name with one of them would turn the reading direction of a row.
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def clean(x):
    return _UNSAFE.sub("·", S(x))


# The widget's own settings, as manifest.json declares them (the bench compares the two). They live in the
# shell's configuration; the shell writes them, Ballroom only asks it to.
# len is how long a string setting may be. The default of 40 fits a name; a browser profile is a path and needs
# more, and a value cut in the middle of a path sends yt-dlp to a directory that does not exist.
# `own` marks what the panel writes by itself and nobody types: it is not in the manifest's schema, so the
# settings page never offers it, and the shell hands it back with the rest all the same.
WIDGET_ID = "rogertobler.ballroom"
WIDGET_SETTINGS = [
    {"key": "title", "label": "Name", "type": "string", "def": ""},
    {"key": "stageButton", "label": "Pause button in the bar", "type": "boolean", "def": True},
    {"key": "spectrum", "label": "Show the spectrum", "type": "boolean", "def": True},
    {"key": "inputSpectrum", "label": "Spectrum of the microphone", "type": "boolean", "def": True},
    {"key": "inputMeters", "label": "Level bar in every input row", "type": "boolean", "def": True},
    # Which parts the panel shows and in which order, as one line of ids; a dash in front of one switches it off.
    # The panel keeps the meaning of the line, the command only keeps the line. There is no second switch per
    # section beside it: two ways to hide one thing are two chances to disagree.
    {"key": "sections", "label": "Sections and their order", "type": "string", "def": "", "len": 200},
    {"key": "soundcloudUser", "label": "SoundCloud name", "type": "string", "def": ""},
    {"key": "soundcloudCookies", "label": "SoundCloud browser cookies", "type": "string", "def": "", "len": 240},
    {"key": "spectrumBars", "label": "Bars in the spectrum", "type": "integer", "def": 8, "min": 4, "max": 24},
    {"key": "spectrumColor", "label": "Colour of the bars", "type": "enum", "def": "Mono", "options": ["Mono", "Accent", "Rainbow"]},
    {"key": "refreshIntervalSec", "label": "Status interval (seconds)", "type": "integer", "def": 5, "min": 2, "max": 60},
    # Which parts the panel has folded shut, in the shape of the sections line: an id on its own is open, an id
    # with a dash in front of it is folded. The panel writes it when a section's line is clicked, so that the
    # panel opens the next time the way it was left; an empty line means nothing has been folded yet.
    {"key": "folded", "label": "Folded sections", "type": "string", "def": "", "len": 200, "own": True},
]


def widgetValues():
    values = {w["key"]: w["def"] for w in WIDGET_SETTINGS}
    try:
        config = jparse(read_text(pjoin(nn(ENV.get("XDG_CONFIG_HOME"), pjoin(HOME, ".config")), "omarchy", "shell.json")))
        layout = nn(gp(config, "bar", "layout"), {})
        sections = layout.values() if isinstance(layout, dict) else layout if isinstance(layout, list) else list(layout) if isinstance(layout, str) else []
        for section in sections:
            for entry in (section if isinstance(section, list) else []):
                if not isObject(entry) or entry.get("id") != WIDGET_ID:
                    continue
                for w in WIDGET_SETTINGS:
                    if w["key"] in entry:
                        values[w["key"]] = entry[w["key"]]
    except Exception:
        pass  # no shell configuration: the defaults are what the widget uses
    return values


def setWidgetValue(key, value):
    w = next((x for x in WIDGET_SETTINGS if x["key"] == key), None)
    if w is None:
        raise Fail(f"no widget setting {key}", EXIT.usage)
    if w["type"] == "boolean" and not isinstance(value, bool):
        raise Fail(f'{w["label"]} is on or off', EXIT.usage)
    if w["type"] == "integer" and (not is_num(value) or not is_int(value) or value < w["min"] or value > w["max"]):
        raise Fail(f'{w["label"]} is a whole number from {w["min"]} to {w["max"]}', EXIT.usage)
    if w["type"] == "enum" and S(value) not in w["options"]:
        raise Fail(f'{w["label"]} is one of {", ".join(w["options"])}', EXIT.usage)
    if w["type"] == "string":
        value = cut(js_trim(clean(S(value))), w.get("len", 40))
    r = run(["omarchy-shell", "shell", "setBarWidget", WIDGET_ID, key, jdump(value), "{}"])
    if r.rc == 127:
        raise Fail("omarchy-shell is not installed; widget settings live in the shell")
    if r.timedOut or r.rc != 0:
        raise Fail("the shell did not take the setting; is it running?")
    if js_trim(r.out) != "ok":
        raise Fail(f"the shell refused the setting: {cut(clean(js_trim(r.out)), 120)}")
    # Rule 1: the shell says ok, the configuration it wrote says whether it is true.
    deadline = now_ms() + 2000
    while now_ms() < deadline:
        if strict_eq(widgetValues().get(key), value):
            return
        sleep_ms(50)
    raise Fail(f'the shell answered ok, but {w["label"]} did not change in its configuration')


DOCTOR_ADVICE = {
    "graph": "PipeWire itself. If it does not answer, nothing here works: systemctl --user status pipewire.",
    "wireplumber": "The session manager: defaults, routing, Bluetooth. Without it there is no default output.",
    "pulse": "pipewire-pulse speaks PulseAudio for applications that never learned PipeWire.",
    "units": "The user services. ballroom-eq runs the equalizer, ballroom-stage runs mpv for the stage; both are started by ballroom.",
    "clock": "Rate and quantum of the graph. A forced value was set by something else (pw-metadata -n settings).",
    "xruns": "Dropouts counted by pw-top since each node started. A few after a device change are normal; a rising count while playing is not.",
    "output": "The default output. Unplugged means WirePlumber still points at it; ballroom out picks another.",
    "input": "The default input. ballroom in picks another.",
    "eq": "The equalizer is a PipeWire process in front of the default output. Not running while on: ballroom eq restart. Not in front: ballroom apply.",
    "foreign": "Another smart filter in front of the output, from another plugin or a config fragment. Ballroom leaves it alone; two filters stack.",
    "fragments": "Drop-in files in ~/.config/pipewire and ~/.config/wireplumber that build a filter. Ballroom has none.",
    "stage": "mpv plays radio, SoundCloud and DI.FM; yt-dlp resolves SoundCloud. omarchy pkg add mpv yt-dlp.",
    "tools": "cava draws the spectrum, mpv plays the stage, yt-dlp resolves SoundCloud. omarchy pkg add cava mpv yt-dlp.",
    "command": "The ballroom the terminal finds in ~/.local/bin. A copy there from an older version keeps answering for the terminal and for key bindings. Running install.sh again sets it right, or remove the old copy.",
    "settings": "Ballroom's own files in ~/.config/ballroom. A file that could not be read was moved aside and named here.",
}


# _widget-set KEY VALUE: the one thing the panel cannot do through a verb of its own. A widget setting lives in
# the shell's configuration, and only the shell may write it; everything else the panel changes goes through the
# same verbs a person types. The value arrives as text because that is what a command line carries; the type
# comes from the schema, so the panel and the terminal cannot disagree about what a setting is.
def setWidgetSetting(key, value):
    w = next((x for x in WIDGET_SETTINGS if x["key"] == key), None)
    if w is None:
        raise Fail(f"no widget setting {cut(clean(key), 40)}", EXIT.usage)
    v = (value == "on" or value == "true") if w["type"] == "boolean" else js_number(value) if w["type"] == "integer" else value
    setWidgetValue(w["key"], v)
    return "ok"


# ---------------------------------------------------------------- spectrum
# One cava process, raw ASCII frames, one JSON line per frame on stdout. cava ends with this process, and
# this process ends when its reader goes away, so no analyser outlives the bar.
def verbSpectrum(args):
    bars = js_max(2, js_min(64, js_number(nn(optionValue(args, "--bars"), 10))))
    fps = js_max(5, js_min(60, js_number(nn(optionValue(args, "--fps"), 30))))
    source = nn(optionValue(args, "--source"), "auto")
    if not re.fullmatch(r"auto|[0-9]+", source):
        raise Fail("--source is auto or an object serial", EXIT.usage)
    # What the capture is called says what it reads (rule 8). A serial has to belong to a device that exists.
    who = "output"
    if source != "auto":
        g = readGraph()
        inp = next((d for d in g["inputs"] if d["serial"] == js_number(source)), None)
        if inp is not None:
            if inp["mute"]:
                raise Fail(f'{S(inp["label"])} is muted; a muted input is never read', EXIT.notFound)
            who = "input"
        elif not any(d["serial"] == js_number(source) for d in g["outputs"]):
            raise Fail(f"no device has the serial {source}", EXIT.notFound)
    ensureDir(RUNTIME)
    # A spectrum that was killed outright left its file behind: those of processes that are gone are removed.
    for f in os.listdir(RUNTIME):
        if re.fullmatch(r"cava-[0-9]+\.conf", f) and pid_gone(int(f[5:-5])):
            rm_force(pjoin(RUNTIME, f))
    # One file per process: two spectra run at once, and a restarted one must never pick up the other's source.
    conf = pjoin(RUNTIME, f"cava-{os.getpid()}.conf")
    rm_force(conf)
    write_new(conf, "\n".join([
        "[general]", f"bars = {S(bars)}", f"framerate = {S(fps)}", "sleep_timer = 2",
        "[input]", "method = pipewire", f"source = {source}",
        "[output]", "method = raw", "channels = mono", "mono_option = average", "raw_target = /dev/stdout",
        "data_format = ascii", "ascii_max_range = 1000", "bar_delimiter = 59", "frame_delimiter = 10", "",
    ]), 0o600)
    env = dict(ENV)
    env["PIPEWIRE_PROPS"] = f"{{ node.name = ballroom.spectrum.{who} application.name = Ballroom }}"
    try:
        proc = subprocess.Popen(["cava", "-p", conf], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        rm_force(conf)
        raise Fail("cava is not installed")

    def stop(*_):
        try:
            proc.terminate()
        except OSError:
            pass  # already gone
        rm_force(conf)
        try:
            sys.stdout.flush()
        except _DEAD_STREAM_ERRORS:
            pass
        os._exit(0)
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, stop)
    # Orphaned when the parent dies: the kernel hands the process to init, and that is the signal to stop.
    parent = os.getppid()
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buffer = ""
    fd = proc.stdout.fileno()
    out = sys.stdout
    while True:
        ready, _, _ = select.select([fd], [], [], 1.0)
        if os.getppid() != parent:
            stop()
        if not ready:
            continue
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        buffer += decoder.decode(chunk)
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            bands = [js_min(1, js_number(x) / 1000) for x in line.split(";") if x != ""]
            if len(bands) == bars:
                try:
                    out.write(jdump({"bands": bands}) + "\n")
                    out.flush()
                except _DEAD_STREAM_ERRORS:
                    stop()
    rc = proc.wait()
    rm_force(conf)
    code = rc if rc >= 0 else 128 - rc
    raise Fail(f"cava ended with exit {code}")


def optionValue(args, name):
    if name in args:
        i = args.index(name)
        return args[i + 1] if i + 1 < len(args) else None
    return None


# ---------------------------------------------------------------- main
HELP = f"""ballroom {VERSION}: the sound of this machine in one place

  The panel in the bar does all of this with the mouse. These verbs are the same thing for the terminal, for a
  script and for a key binding, and every one of them prints for a person or, with --json, for a program.

  ballroom                     what plays where, how loud, who is listening
  ballroom json                everything the bar widget shows, as JSON
  ballroom out [DEVICE|next]   list outputs, or make DEVICE (or the next plugged-in one) the default, brought to its cap first
  ballroom in [DEVICE]         list inputs, or make DEVICE the default (a muted microphone stays muted)
  ballroom vol [TARGET] [LEVEL]  volume of the default output, "in", a device or an application; 0-150, +5, -5
  ballroom mute [TARGET] [on|off|toggle]
  ballroom route [APP DEVICE|APP follow] send an application to a device, or let it follow the default again;
                               the rule holds for this setup of plugged-in outputs, docking and undocking switch
                               between setups; while the device is unplugged, the application follows the default
  ballroom device list|alias|hide|show|kind|cap|classcap|reset ...
  ballroom apply               bring the graph in line with routes, and outputs that just arrived or were
                               plugged in with their caps; a stream on an unplugged output follows the default,
                               one sent by a rule of another setup follows it too, and a default that is
                               unplugged moves until its output is back
  ballroom bt [list]           Bluetooth headsets: profile and the codecs they offer
  ballroom bt codec [DEVICE] [CODEC]   show or switch the music codec; other outputs stay muted meanwhile,
                                       and stay muted if it does not come back
  ballroom bt mode [DEVICE] music|call
  ballroom bt auto [on|off]    may WirePlumber switch to call mode when an app records
  ballroom eq [show|on|off|stop|restart|sync]   the equalizer in front of the default output; one preset per device. off
                               leaves the filter running and neutral and brings the output down by the preamp so the
                               loudness stays; on brings it back if untouched; stop ends the process
  ballroom eq preset list|use NAME [DEVICE]|save NAME|rm NAME     built-in and own presets
  ballroom eq import FILE [NAME]   an AutoEQ ParametricEQ.txt as a preset
  ballroom eq band N FREQ GAIN [Q] [TYPE]   change one band of the default output's preset (once: every change clicks)
  ballroom eq preamp DB|auto   eq balance -1..1   eq mono on|off   eq swap on|off   eq stereo reset
  ballroom stage [status|start|quit|refresh|clear]   the stage: radio, SoundCloud and DI.FM without a window, played by mpv; clear drops the results
  ballroom play [URL|N|*N|NAME]   play an address, a search result, a favorite; without anything: resume
  ballroom pause | next | prev | stop | toggle   (a live stream pauses by stopping, and tunes in again live; next and
                               prev walk the list the entry came from: results, favorites, recent or likes)
  ballroom seek SECONDS|+N|-N  the position in a track (not a live stream)
  ballroom radio search QUERY [--more] | radio play N     the radio-browser directory, forty at a time; --more adds the next page
  ballroom sc search QUERY | sc play N       SoundCloud through yt-dlp
  ballroom sc list [likes|playlists|uploads|reposts] [NAME]   one of the lists a profile holds
  ballroom sc open id:N        a playlist: its tracks become the results
  ballroom sc name [NAME|-] | sc whoami   the profile the lists belong to; whoami reads it from the browser session
  ballroom sc browsers         which browsers keep a cookie store here, and which is signed in on SoundCloud
  ballroom sc cookies [auto|BROWSER|-]   which browser session yt-dlp may read; auto takes the one signed in; unset or - reads none
  ballroom di search QUERY | di play CHANNEL | di channels [NETWORK]   DI.FM and its sister stations (premium listen key)
  ballroom di key [set|-]      the DI.FM listen key: set reads it from a hidden prompt or stdin, never an argument
  ballroom fav [list|add [N]|rm N|play N]        favorites
  ballroom scene [list|save NAME|use NAME|show NAME|rm NAME]   scenes: outputs, levels, input, equalizer, Bluetooth, stage
  ballroom doctor              diagnosis: services, clock, xruns, defaults, equalizer, foreign filters and fragments, tools
  ballroom spectrum [--bars N] [--fps N] [--source auto|SERIAL]   one JSON line of bands per frame; a
                               SERIAL of an input reads that microphone, so only do it while someone watches

Add --json to any verb for machine readable output. Add --osd to vol, mute, out, in, eq on|off, play, pause, stop, toggle
or scene use to show the result on Omarchy's on-screen display, the way the media keys do (for key bindings)."""


def main():
    # Ctrl-C ends the command at once, as a signal, without a trace of the interpreter on the terminal.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    argv = sys.argv[1:]
    args = [a for a in argv if a != "--json" and a != "--osd"]
    verb = args[0] if args else None
    rest = args[1:]
    # The bar widget reads `ballroom json` and has to get JSON back on a failure too, not text on stderr.
    json_mode = "--json" in argv or verb == "json"
    osdWanted = "--osd" in argv

    def say(o):
        if json_mode:
            js = dict(o["json"])
            js["warnings"] = list(dict.fromkeys(list(nn(js.get("warnings"), [])) + warnings))
            say_out(jdump(js))
        else:
            say_out(S(o["text"]))
        if osdWanted and o.get("osd"):
            showOsd(o["osd"])
    try:
        if verb is None or verb == "status":
            say(verbStatus())
        elif verb == "json":
            say_out(jdump(stateJson(readGraph())))
        elif verb == "out":
            say(verbOut(rest))
        elif verb == "in":
            say(verbIn(rest))
        elif verb in ("vol", "volume"):
            say(verbVol(rest))
        elif verb == "mute":
            say(verbMute(rest))
        elif verb == "route":
            say(verbRoute(rest))
        elif verb == "device":
            say(verbDevice(rest))
        elif verb == "apply":
            say(verbApply())
        elif verb == "_guard":
            say(verbGuard(rest))
        elif verb == "bt":
            say(verbBt(rest))
        elif verb == "eq":
            say(verbEq(rest))
        elif verb in ("stage", "play", "pause", "next", "prev", "stop", "toggle", "seek", "radio", "sc", "di", "fav"):
            say(verbStage(verb, rest))
        elif verb == "scene":
            say(verbScene(rest))
        elif verb == "doctor":
            say(verbDoctor())
        elif verb == "_widget-set":
            say_out(setWidgetSetting(rest[0] if rest else "", " ".join(rest[1:])))
        elif verb == "_widget-schema":
            say_out(jdump([{k: v for k, v in w.items() if k != "own"} for w in WIDGET_SETTINGS if not w.get("own")]))
        elif verb == "spectrum":
            verbSpectrum(rest)
        elif verb in ("help", "-h", "--help"):
            say_out(HELP)
        elif verb == "--version":
            say_out(VERSION)
        else:
            raise Fail(f'unknown verb "{verb}"; ballroom help lists them', EXIT.usage)
    except _StdoutGone:
        _quiet_exit(0)
    except Exception as e:
        code = e.code if isinstance(e, Fail) else EXIT.failed
        message = maskKey(clean(e.message if isinstance(e, Fail) else "unexpected failure"))
        # The trace names values from every frame it passes, an address with the listen key among them: only the
        # bench prints it, and masked even there.
        if BENCH and ENV.get("BALLROOM_DEBUG"):
            import traceback
            say_err(maskKey(traceback.format_exc().rstrip("\n")))
        try:
            if json_mode:
                say_out(jdump({"ok": False, "error": message, "code": code}))
            else:
                say_err(f"ballroom: {message}")
        except _StdoutGone:
            pass
        _quiet_exit(code)
    _quiet_exit(0)


def _quiet_exit(code):
    """Leaves without a word about a stream nobody reads: what is left in its buffer has nowhere to go."""
    for name in ("stdout", "stderr"):
        try:
            getattr(sys, name).flush()
        except _DEAD_STREAM_ERRORS:
            _bury(name)
    sys.exit(code)


def entry():
    # Nothing escapes as a trace outside the bench: whatever main did not turn into a message ends as exit 120
    # (unexpected failure), quietly.
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        if BENCH and ENV.get("BALLROOM_DEBUG"):
            import traceback
            try:
                sys.stderr.write(maskKey(traceback.format_exc()))
            except _DEAD_STREAM_ERRORS:
                pass
        for name in ("stdout", "stderr"):
            _bury(name)
        os._exit(EXIT.failed)


if __name__ == "__main__":
    entry()
