"""Generates the Settings and per-Job settings mockups: python docs/mockups/tools/gen_settings.py"""
import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]


def ico(name, cls="i"):
    return f'<svg class="{cls}" aria-hidden="true"><use href="assets/icons.svg#{name}"/></svg>'


HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&family=Archivo+Narrow:wght@600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="assets/ama.css"><link rel="stylesheet" href="assets/ama-app.css"><script src="assets/theme.js"></script>
</head>
<body>
"""

TOGGLE = "const m=document.getElementById('menu');m.hidden=!m.hidden;this.setAttribute('aria-expanded',String(!m.hidden))"


def header(current=None, review=2, used=102, menu_open=False, paused=False, on_settings=True, review_href="review-movie.html"):
    def nav(href, text, key):
        cur = ' aria-current="page"' if current == key else ""
        return f'<a href="{href}"{cur}>{text}</a>'
    count = f'<span class="count" aria-label="{review} waiting">{review}</span>' if review else ""
    mark = (f'<span class="paused" title="New Discs are ignored until you resume">{ico("pause")}Paused</span>' if paused else "")
    pct = round(used / 256 * 100, 1)
    acc, pau = ("false", "true") if paused else ("true", "false")
    setcur = ' aria-current="page"' if on_settings else ""
    return f"""<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <a class="brand" href="now.html">Automatic Media Archive</a>
  <nav class="nav" aria-label="Main">{nav("now.html", "Now", "now")}{nav(review_href, "Review" + count, "review")}{nav("history.html", "History", "history")}</nav>
  {mark}<a class="scratch" href="scratch-full.html" title="Local scratch space"><span class="lbl">Scratch</span><span class="meter" role="meter" aria-valuenow="{used}" aria-valuemin="0" aria-valuemax="256" aria-label="Scratch used"><i style="width:{pct}%"></i></span><b>{used} / 256 GB</b></a>
  <div class="menu"><button class="mbtn" type="button" aria-label="Menu" aria-expanded="{"true" if menu_open else "false"}" aria-controls="menu" onclick="{TOGGLE}">{ico("menu")}</button>
    <div class="mpanel" id="menu"{"" if menu_open else " hidden"}>
      <div class="mg"><div class="ml" id="m-drive">New Discs</div><div class="segs" role="group" aria-labelledby="m-drive"><button type="button" aria-pressed="{acc}">Accepting</button><button type="button" aria-pressed="{pau}">Paused</button></div></div>
      <div class="mg"><div class="ml" id="m-theme">Theme</div><div class="segs" role="group" aria-labelledby="m-theme"><button type="button" aria-pressed="true">System</button><button type="button" aria-pressed="false">Light</button><button type="button" aria-pressed="false">Dark</button></div></div>
      <a class="mi" href="settings-general.html"{setcur}>{ico("settings")}Settings</a>
      <a class="mi" href="logs.html">{ico("log")}Logs</a>
      <a class="mi" href="login.html">{ico("logout")}Log out</a>
    </div></div>
</header>
"""


TABS = [("general", "General", "settings-general.html"),
        ("ripping", "Ripping", "settings-ripping.html"),
        ("archive", "Archive", "settings-encode.html"),
        ("alerts", "Alerts", "settings-notifications.html"),
        ("logs", "Logs", "settings-logs.html")]

SUBS = [("encode", "Encode", "settings-encode.html"),
        ("libraries", "Libraries", "settings-libraries.html"),
        ("nas", "NAS", "settings-nas.html"),
        ("identification", "Identification", "settings-identification.html")]


CUR = ' aria-current="page"'
EXP = ' aria-expanded="true"'


def tabs(cur):
    return '<nav class="files" aria-label="Settings sections">' + "".join(
        f'<a class="tab" href="{h}"{CUR if k == cur else ""}>{t}</a>' for k, t, h in TABS) + "</nav>"


def subnav(cur):
    return '<nav class="subnav" aria-label="Archive settings">' + "".join(
        f'<a href="{h}"{CUR if k == cur else ""}>{t}</a>' for k, t, h in SUBS) + "</nav>"


RESTART_NOTE = f'<span class="ts rnote">{ico("redo")}Used after a restart</span>'


def grp(title, note=""):
    return f'<div class="grp-h"><h2>{title}</h2>{note}</div>'


def sf(fid, label, ctl, hint=None, tech=None, tag=None, secret=False, extra=""):
    """One field row. ctl may contain {db} for the aria-describedby attribute."""
    ids = []
    hn = ""
    if hint or tech:
        ids.append(f"{fid}-h")
        t = f'<span class="tech">{tech}</span>' if tech else ""
        hn = f'<div class="hn" id="{fid}-h">{hint or ""}{t}</div>'
    db = f' aria-describedby="{" ".join(ids)}"' if ids else ""
    tg = ""
    if tag == "restart":
        tg = f'<span class="rs" title="Saved now, used after AMA restarts">{ico("redo")}Restart</span>'
    elif tag == "pending":
        tg = f'<span class="rs pending">{ico("redo")}Waiting for restart</span>'
    if secret:
        lab = f'<span id="{fid}-l">{label}</span>'
    elif fid and "{nolabel}" not in ctl:
        lab = f'<label for="{fid}">{label}</label>'
    else:
        lab = f'<span id="{fid}-l">{label}</span>'
    ctl = ctl.replace("{nolabel}", "").replace("{db}", db)
    return f'<div class="sf"><div><div class="lb">{lab}{tg}</div>{hn}</div><div class="ctl">{ctl}{extra}</div></div>'


def inp(fid, value="", placeholder="", typ="text", unit=None, cls="input", extra_attr=""):
    v = f' value="{value}"' if value != "" else ""
    p = f' placeholder="{placeholder}"' if placeholder else ""
    i = f'<input class="{cls}" id="{fid}" type="{typ}" name="{fid}"{v}{p}{{db}} spellcheck="false"{extra_attr}>'
    return f'<div class="unit">{i}<span>{unit}</span></div>' if unit else i


def secret_set(fid, what):
    return (f'<div class="secret" role="group" aria-labelledby="{fid}-l"{{db}}><span class="state">{ico("check")}Set</span>'
            f'<button class="btn quiet" type="button" aria-label="Replace {what}">Replace</button>'
            f'<button class="btn quiet" type="button" aria-label="Remove {what}">Remove</button></div>')


def foot(name, state="clean"):
    if state == "clean":
        return f'<div class="setfoot"><span class="st">No unsaved changes</span><button class="btn pri" type="submit" disabled>Save {name}</button></div>'
    if state == "saved":
        return f'<div class="setfoot"><span class="st"><span class="ok" role="status">{ico("check")}Saved at 21:14</span></span><button class="btn pri" type="submit" disabled>Save {name}</button></div>'
    if state == "dirty":
        return f'<div class="setfoot"><span class="st dirty">Unsaved changes</span><button class="btn quiet" type="reset">Undo changes</button><button class="btn pri" type="submit">Save {name}</button></div>'
    if state == "error":
        return f'<div class="setfoot"><span class="st dirty">Not saved: fix the fields marked above</span><button class="btn quiet" type="reset">Undo changes</button><button class="btn pri" type="submit">Save {name}</button></div>'


def adv(did, title, rows, note="", is_open=False, advanced=True, lead=None):
    tag = '<span class="advtag">Advanced</span>' if advanced else ""
    lead = lead if lead is not None else ("You probably don't need to change this." if advanced else "")
    sub = f'<span class="advsub">{lead}</span>' if lead else ""
    nt = f'<span class="advnote">{note}</span>' if note else ""
    return (f'<details class="adv" id="{did}"{" open" if is_open else ""}><summary>'
            f'<span class="advh">{tag}<span class="advt">{title}</span>{ico("chevron", "i chev")}</span>{sub}{nt}</summary>'
            f'{"".join(rows)}</details>')


SETNOTE = '<p class="ts setnote">Saved to <code>ama.toml</code>. Editing the file by hand does the same thing; this page shows what\'s in it now.</p>'


def page(fname, section, tab, body, banner="", menu_open=False, paused=False, sub=None, note=SETNOTE, script=""):
    title = f"{section} · Settings · Automatic Media Archive"
    if sub:
        title = f"{sub} · {section} · Settings · Automatic Media Archive"
    html = (HEAD.format(title=title) + header(menu_open=menu_open, paused=paused) +
            f'<main class="settings" id="main">\n  <h1>Settings</h1>\n  {banner}{tabs(tab)}\n  {body}\n  {note}\n</main>\n'
            "<script>document.querySelector('.files [aria-current]').scrollIntoView({inline:'center',block:'nearest'})</script>\n"
            f'{script}<script src="assets/menu.js"></script>\n</body>\n</html>\n')
    (OUT / fname).write_text(html, encoding="utf-8", newline="\n")


def form(label, inner):
    return f'<form class="box setbox" aria-label="{label}" novalidate>\n      ' + "\n      ".join(inner) + "\n  </form>"


# ---------- General ----------

def general(fname, *, port="8080", host="0.0.0.0", port_tag=None, foot_state="clean", paused=False,
            menu_open=False, banner="", host_warn=False, leave=False):
    host_extra = ""
    if host_warn:
        host_extra = (f'<div class="fwarn" id="web-host-w">{ico("alert")}<span><b>Phones and other computers lose access.</b> '
                      'With 127.0.0.1 only this PC can open AMA after the restart, so this phone or laptop will lose AMA too if it isn\'t that PC.</span></div>')
    host_ctl = inp("web-host", host)
    if host_warn:
        host_ctl = host_ctl.replace("{db}", ' aria-describedby="web-host-h web-host-w"')
    state = "Paused" if paused else "Accepting"
    state_txt = ("AMA ignores Discs you insert until you resume. A Rip already running finishes." if paused
                 else "AMA rips each Disc you insert.")
    rows = []
    if leave:
        rows.append('<div class="leave" role="alertdialog" aria-labelledby="leave-h" aria-describedby="leave-d" tabindex="-1">'
                    '<div><b id="leave-h">Leave General without saving?</b><span id="leave-d">You changed Address. Going to Ripping now throws that change away.</span></div>'
                    '<div class="actions"><button class="btn quiet" type="button">Stay on General</button><button class="btn danger" type="button">Discard and go</button><button class="btn pri" type="button">Save and go</button></div></div>')
    rows += [
        grp("Web UI", RESTART_NOTE),
        sf("web-host", "Address", host_ctl,
           hint="Who can open AMA. 0.0.0.0 lets phones and other computers at home reach it; 127.0.0.1 limits it to this PC.",
           tag="pending" if port_tag == "host" else None, extra=host_extra),
        sf("web-port", "Port", inp("web-port", port, typ="number"),
           hint="The number after the address in the browser bar (:8080). Change it only if another program already uses it.",
           tag="pending" if port_tag == "port" else None),
        sf("web-pass", "Password", secret_set("web-pass", "password"), secret=True,
           hint="Without a password, anyone on your home network can use AMA. Once saved it's never shown again."),
        grp("New Discs", '<span class="ts">Changes at once</span>'),
        sf("drive-state", "Right now",
           f'{{nolabel}}<div class="ro"><b>{state}</b></div>'
           f'<button class="btn quiet" type="button" onclick="document.querySelector(\'.mbtn\').click()">{ico("menu")}Change in the menu</button>',
           hint=f"{state_txt} Pause and resume from the menu at the top right; it isn't saved in <code>ama.toml</code>."),
        grp("Storage", RESTART_NOTE),
        sf("paths-scratch", "Scratch folder", inp("paths-scratch", r"D:\ama-scratch"),
           hint="Rips wait here for Identification, Review and Encode. Needs at least 256 GB free."),
        sf("scratch-need", "Space needed before a Rip",
           '{nolabel}<table class="pertype" aria-labelledby="scratch-need-l"{db}><thead><tr><th scope="col">Disc Type</th><th scope="col">Free space</th></tr></thead><tbody>'
           + "".join(f'<tr><td>{n}</td><td><div class="unit"><input class="input" type="number" value="{v}" aria-label="{n} free space"><span>GB</span></div></td></tr>'
                     for n, v in [("CD", 1), ("DVD", 10), ("Blu-ray", 50), ("UHD Blu-ray", 100)]) + "</tbody></table>",
           hint="With less free, an inserted Disc is ejected unripped and Now shows what's holding scratch."),
        adv("adv-files", "Database and log file", [
            sf("paths-db", "Database", inp("paths-db", "ama.sqlite3"),
               hint="AMA's record of every Job. A plain name is kept next to <code>ama.toml</code>.",
               tech="Key <code>[paths] state_db</code>"),
            sf("paths-log", "Log file", inp("paths-log", r"logs\ama.log"),
               hint="AMA's own diagnostic log. Each Job's step output is in Logs, not here.",
               tech="Key <code>[paths] log_file</code>"),
        ], note=f'{ico("redo")}Used after a restart'),
        foot("General", foot_state),
    ]
    page(fname, "General", "general", form("General settings", rows), banner=banner, menu_open=menu_open, paused=paused)


general("settings-general.html")
general("settings-menu.html", menu_open=True)
general("settings-menu-paused.html", menu_open=True, paused=True)
general("settings-unsaved.html", host="127.0.0.1", foot_state="dirty", host_warn=True, leave=True)


def restart_banner(mode):
    items = "<ul><li>Port (General)</li><li>Drive letter (Ripping)</li></ul>"
    new_addr = '<p class="rmeta">After the restart AMA is at <a href="#">http://ama-pc:8081</a>; this address stops working.</p>'
    busy = ('<p class="rmeta"><b>ARRIVAL</b> is Ripping and 1 Encode is running. Restarting now stops both: the Rip has to start again with the Disc reinserted, and the Encode starts over from the beginning.</p>')
    if mode == "banner":
        return (f'<div class="notice restart" role="status">{ico("redo")}<div class="rbody"><div><b>Restart AMA to use 2 saved changes</b>{items}{busy}{new_addr}</div>'
                '<button class="btn pri" type="button" onclick="location.href=\'settings-restart-confirm.html\'">Restart&hellip;</button></div></div>\n  ')
    if mode == "confirm":
        return (f'<div class="notice restart" role="status">{ico("redo")}<div class="rbody"><div><b>Restart AMA to use 2 saved changes</b>{items}{new_addr}</div></div>'
                '<div class="rconfirm" id="rconfirm" role="alertdialog" aria-labelledby="rc-h" aria-describedby="rc-d" tabindex="-1">'
                '<div><b id="rc-h">A Rip and an Encode are running</b><span id="rc-d">Restart when idle waits for <b>ARRIVAL</b> to finish Ripping and for the Encode to finish (about 25 min), and starts no new Rip meanwhile. Restart now stops both: the Rip has to start again with the Disc reinserted and the Encode starts over.</span></div>'
                '<div class="actions"><button class="btn quiet" type="button" onclick="location.href=\'settings-restart.html\'">Cancel</button><button class="btn danger" type="button">Restart now</button>'
                '<button class="btn pri" type="button" autofocus onclick="location.href=\'settings-restart-idle.html\'">Restart when idle</button></div></div></div>\n  ')
    if mode == "idle":
        return (f'<div class="notice restart" role="status">{ico("redo")}<div class="rbody"><div><b>AMA restarts when nothing is Ripping or Encoding</b>{items}'
                '<p class="rmeta">Waiting for <b>ARRIVAL</b> to finish Ripping and for 1 Encode, about 25 min. No new Rip starts meanwhile.</p>'
                f'{new_addr}</div><button class="btn quiet" type="button" onclick="location.href=\'settings-restart.html\'">Don\'t restart</button></div></div>\n  ')


for f, mode in [("settings-restart.html", "banner"), ("settings-restart-confirm.html", "confirm"), ("settings-restart-idle.html", "idle")]:
    general(f, port="8081", port_tag="port", foot_state="saved", banner=restart_banner(mode))


# ---------- Ripping ----------

def tool(fid, name, hint, stat, ph, tech):
    return sf(fid, name, f'<span class="tstat">{ico("check")}{stat}</span>' + inp(fid, placeholder=ph), hint=hint, tech=tech)


def ripping(fname, open_cd=False, open_tools=False):
    rows = [
        grp("Drive", RESTART_NOTE),
        sf("drive-letter", "Drive letter", inp("drive-letter", placeholder="Automatic (D:)"),
           hint="Leave empty to use the first optical drive Windows finds, now D:."),
        sf("drive-poll", "Check for a Disc every", inp("drive-poll", "3", typ="number", unit="seconds"),
           hint="How soon AMA notices a Disc going in or coming out. 3 seconds suits most drives."),
        adv("adv-cd", "Reading CDs", [
            sf("cd-offset", "Read offset", inp("cd-offset", "667", typ="number", unit="samples"),
               hint="Lines up your drive's reading so each CD Rip can be checked against AccurateRip, a database of other people's Rips. +667 is right for the PIONEER BDR-S11JX.",
               tech="In EAC's convention. Measure it once with cyanrip's offset test, <code>cyanrip -f</code>. Key <code>[cd] offset</code>"),
            sf("cd-retries", "Re-reads", inp("cd-retries", "10", typ="number", unit="per frame"),
               hint="How many times AMA reads a scratched spot again before counting it as an error. More is slower but rescues more.",
               tech="Key <code>[cd] retries</code>"),
        ], note="Used from the next CD Rip", is_open=open_cd),
        adv("adv-tools", "Tools", [
            '<p class="advp">AMA downloads its own checked copies of ffmpeg and cyanrip. Give a full path only to use your own copy instead; it\'s used as-is.</p>',
            tool("tools-ffmpeg", "ffmpeg", "Encodes video.", "Working · 7.1, AMA's copy", "Use AMA's copy", "Key <code>[tools] ffmpeg</code>"),
            tool("tools-ffprobe", "ffprobe", "Reads each Title's length, tracks and picture.", "Working · 7.1, AMA's copy", "Use AMA's copy", "Key <code>[tools] ffprobe</code>"),
            tool("tools-cyanrip", "cyanrip", "Rips CDs.", "Working · 0.9.3, AMA's copy", "Use AMA's copy", "Key <code>[tools] cyanrip</code>"),
            tool("tools-makemkvcon", "MakeMKV", "Rips DVDs and Blu-rays. It's yours to install and register; AMA never does either.", "Working · 1.17.8, registered", "Look in Program Files", "Key <code>[tools] makemkvcon</code>"),
            sf("tools-dir", "Tools folder", inp("tools-dir", placeholder=r"%LOCALAPPDATA%\ama\tools"),
               hint="Where AMA keeps its copies. The first start needs internet and about 0.5 GB.", tech="Key <code>[tools] dir</code>"),
        ], note=f'{ico("redo")}Checked when AMA starts · used after a restart', is_open=open_tools),
        foot("Ripping"),
    ]
    page(fname, "Ripping", "ripping", form("Ripping settings", rows))


ripping("settings-ripping.html")
ripping("settings-cd.html", open_cd=True)
ripping("settings-tools.html", open_tools=True)


# ---------- Archive: Encode ----------

def encoder_choices(broken=False):
    nv = ('<label class="radio broken on"><input type="radio" name="encoder" value="hevc_nvenc" checked><span>HEVC (NVIDIA)<span class="ts">Stopped working at the 20:14 test</span></span></label>' if broken
          else '<label class="radio on"><input type="radio" name="encoder" value="hevc_nvenc" checked><span>HEVC (NVIDIA)<span class="ts">Fast; the default</span></span></label>')
    return ('{nolabel}<div class="choices" role="radiogroup" aria-labelledby="encoder-l"{db}>' + nv +
            '<label class="radio"><input type="radio" name="encoder" value="av1_nvenc"><span>AV1 (NVIDIA)<span class="ts">Smaller files; older Plex apps may have to convert them</span></span></label>'
            '<label class="radio na"><input type="radio" name="encoder" value="hevc_qsv" disabled><span>HEVC (Intel Quick Sync)<span class="ts">Not available on this PC</span></span></label>'
            '<label class="radio"><input type="radio" name="encoder" value="libx265"><span>HEVC (software)<span class="ts">Works on any PC; very slow for UHD</span></span></label></div>'
            + ('<button class="btn quiet" type="button">Test encoders again</button>' if broken else ""))


def radios(fid, name, opts):
    return (f'{{nolabel}}<div class="choices" role="radiogroup" aria-labelledby="{fid}-l"{{db}}>' +
            "".join(f'<label class="radio{" on" if on else ""}"><input type="radio" name="{name}"{" checked" if on else ""}><span>{t}</span></label>' for t, on in opts) + "</div>")


def encode(fname, broken=False):
    rows = [subnav("encode")]
    if broken:
        rows.append(f'<div class="notice setnotice" role="alert">{ico("alert")}<div><b>HEVC (NVIDIA) stopped working</b>The test encode at 20:14 failed, so Encodes will fail until it works again or you pick another encoder. <a href="logs-run-app.html">See the test log</a></div></div>')
    q = ('{nolabel}<table class="pertype" aria-labelledby="enc-q-l"{db}><thead><tr><th scope="col">Disc Type</th><th scope="col">Quality</th><th scope="col">Max resolution</th></tr></thead><tbody>'
         '<tr><td>DVD</td><td><input class="input" type="number" value="20" aria-label="DVD quality"></td><td><select class="select" aria-label="DVD max resolution"><option selected>Keep (576p)</option></select></td></tr>'
         '<tr><td>Blu-ray</td><td><input class="input" type="number" value="22" aria-label="Blu-ray quality"></td><td><select class="select" aria-label="Blu-ray max resolution"><option selected>Keep (1080p)</option><option>720p</option></select></td></tr>'
         '<tr><td>UHD Blu-ray</td><td><input class="input" type="number" value="22" aria-label="UHD Blu-ray quality"></td><td><select class="select" aria-label="UHD Blu-ray max resolution"><option selected>Keep (2160p)</option><option>1080p</option></select></td></tr></tbody></table>')
    rows += [
        grp("Encoder", '<span class="ts">Used for Encodes that haven\'t started</span>'),
        sf("encoder", "Encoder", encoder_choices(broken),
           hint="Only encoders that pass a test encode on this PC can be picked. Every Archive is an MKV file at a steady quality, and UHD Discs keep their HDR picture.",
           tech="HDR10 is kept; Dolby Vision isn't."),
        sf("enc-preset", "Speed", '<select class="select" id="enc-preset"{db}><option>Faster, bigger</option><option>Balanced</option><option selected>Slower, smaller</option><option>Slowest, smallest</option></select>',
           hint="Slower makes smaller files at the same quality. The same four steps on every encoder."),
        adv("adv-enc", "Quality, sound and subtitles", [
            sf("enc-q", "Quality and size", q,
               hint="Lower numbers keep more detail and make bigger files; 18 to 24 suits most Discs. Archives are kept for good, so settle these before you archive a lot.",
               tech="Constant quality (CQ), 0 to 51. Keys <code>[encode.cq] dvd</code>, <code>bd</code>, <code>uhd</code>"),
            sf("enc-audio", "Sound", radios("enc-audio", "audio", [("Copy all tracks", True), ("First track, plus a stereo copy that plays everywhere (AAC)", False), ("Preferred languages only", False)]),
               hint="Copy all keeps every language and commentary."),
            sf("enc-subs", "Subtitles", radios("enc-subs", "subs", [("All", False), ("Preferred languages", True), ("None", False)])),
            sf("enc-langs", "Preferred languages", inp("enc-langs", "English, Japanese"),
               hint="In order of preference. Used by the sound and subtitle choices above."),
        ], advanced=False, lead="Now: quality 20 to 22 · copy all sound · subtitles in English, Japanese"),
        foot("Encode"),
    ]
    page(fname, "Archive", "archive", form("Encode settings", rows), sub="Encode",
         note='<p class="ts setnote">Changes apply to Jobs whose Encode hasn\'t started. A Job can override them from its own settings until then. Saved to <code>ama.toml</code>.</p>')


encode("settings-encode.html")
encode("settings-encode-probe.html", broken=True)


# ---------- Archive: Libraries ----------

LOCK = f'<span class="lockd">{ico("lock")}Default, can\'t be removed</span>'


def librow(name, folder, plex, default=False, kind="Films", cls=""):
    if default:
        act = f'{LOCK}<button class="btn quiet" type="button" aria-label="Edit {name}">Edit</button>'
    else:
        act = (f'<button class="btn quiet" type="button" aria-label="Edit {name}">Edit</button>'
               f'<button class="btn quiet" type="button" aria-label="Make {name} the {kind} default">Make default</button>'
               f'<button class="btn danger" type="button" aria-label="Remove {name}"{EXP if cls == "rm" else ""}>Remove</button>')
    c = " open" if cls else ""
    return (f'<div class="librow{c}" role="listitem"><div class="lc nm">{name}</div><div class="lc"><span class="k">Folder</span><span class="path">{folder}</span></div>'
            f'<div class="lc"><span class="k">Plex library</span>{plex}</div><div class="act">{act}</div></div>')


def libedit(title, name, plex_opts, folder, button, kind_word, plex_off=False, new=False):
    if plex_off:
        plex = ('<select class="select" id="lib-plex" disabled aria-describedby="lib-plex-h"><option>Plex isn\'t reachable</option></select>'
                '<span class="hint" id="lib-plex-h">AMA couldn\'t reach Plex at http://nas:32400. Save without one and Plex finds this folder on its next scheduled scan; pick one here once Plex is back. <a href="#plex-url">Check the Plex connection</a></span>')
    else:
        plex = (f'<select class="select" id="lib-plex" aria-describedby="lib-plex-h">' + "".join(f'<option{" selected" if s else ""}>{o}</option>' for o, s in plex_opts) +
                f'</select><span class="hint" id="lib-plex-h">Plex\'s {kind_word} libraries. Plex scans this folder after each Job is filed here.</span>')
    h = f'<b class="newh">{title}</b>' if new else ""
    return (f'<div class="libpanel{" new" if new else ""}">{h}<div class="libedit" role="group" aria-label="{title}">\n'
            f'  <div class="field"><label for="lib-name">Name</label><input class="input" id="lib-name" value="{name}"></div>\n'
            f'  <div class="field"><label for="lib-plex">Plex library</label>{plex}</div>\n'
            f'  <div class="field full"><label for="lib-path">Folder</label><input class="input" id="lib-path" value="{folder}" aria-describedby="lib-path-h"><span class="hint" id="lib-path-h">On the NAS share. AMA creates it if it\'s missing, so check the spelling.</span></div>\n'
            f'  <div class="actions"><button class="btn quiet" type="button">Cancel</button><button class="btn pri" type="submit">{button}</button></div>\n</div></div>')


def libraries(fname, mode=None):
    plex_off = mode == "plex-off"
    stat = (f'<span class="ts"><span class="tstat off">{ico("alert")}Can\'t reach Plex</span></span>' if plex_off
            else f'<span class="ts"><span class="tstat">{ico("check")}Connected</span></span>')
    fam = (r"\\nas\media\Family Films", "Family Films")
    films = [librow("Movies", r"\\nas\media\Movies", "Movies", default=True)]
    if mode in ("edit", "plex-off"):
        films.append(librow("Family Films", *fam, cls="edit"))
        films.append(libedit("Edit Family Films", "Family Films", [("Movies", 0), ("Family Films", 1), ("Movies 4K", 0)], r"\\nas\media\Family Films", "Save Library", "movie", plex_off=plex_off))
    else:
        films.append(librow("Family Films", *fam))
    if mode == "remove":
        films.append(librow("Movies 4K", r"\\nas\media\Movies 4K", "Movies 4K", cls="rm"))
        films.append('<div class="libpanel"><div class="libconfirm" role="alertdialog" aria-labelledby="rm-h" aria-describedby="rm-d" tabindex="-1"><div><b id="rm-h">Remove Movies 4K?</b><span id="rm-d">Its folder and the Jobs already filed there stay on the NAS and in Plex. Jobs that picked it and aren\'t filed yet go to Movies, the Films default.</span></div><div class="actions"><button class="btn quiet" type="button">Cancel</button><button class="btn danger" type="button">Remove Library</button></div></div></div>')
    else:
        films.append(librow("Movies 4K", r"\\nas\media\Movies 4K", "Movies 4K"))
    tv = [librow("TV", r"\\nas\media\TV", "TV Shows", default=True, kind="TV")]
    if mode == "add":
        tv.append(libedit("New TV Library", "Anime", [("TV Shows", 0), ("Anime", 1)], r"\\nas\media\Anime", "Add TV Library", "TV", new=True))
    plus = ico("plus")
    rows = [
        subnav("libraries"),
        grp("Plex connection", stat),
        sf("plex-url", "Plex server", inp("plex-url", "http://nas:32400"),
           hint="Where Plex runs, with its port. Plex normally uses 32400."),
        sf("plex-token", "Plex sign-in token", secret_set("plex-token", "Plex sign-in token"), secret=True,
           hint="Lets AMA tell Plex to look for new files as soon as a Job is filed. Without it, Plex finds them on its next scheduled scan.",
           tech="Plex calls it the X-Plex-Token."),
        sf("plex-path", "Share path seen by Plex", inp("plex-path", "/volume1/media", placeholder="Same as the NAS share"),
           hint="Only if Plex runs on another machine: where that machine sees the NAS share. Leave empty when Plex sees the same path as AMA."),
        foot("Plex connection").replace('class="setfoot"', 'class="setfoot sub"'),
        grp("Films", '<span class="ts">Default: Movies</span>'),
        '<div class="libs" role="list" aria-label="Films Libraries">' + "".join(films) + "</div>",
        f'<div class="libadd"><button class="btn quiet" type="button">{plus}Add Films Library</button></div>',
        grp("TV", '<span class="ts">Default: TV</span>'),
        '<div class="libs" role="list" aria-label="TV Libraries">' + "".join(tv) + "</div>",
    ]
    if mode != "add":
        rows.append(f'<div class="libadd"><button class="btn quiet" type="button">{plus}Add TV Library</button></div>')
    rows += [
        grp("Music", '<span class="ts">Default: Music</span>'),
        '<div class="libs" role="list" aria-label="Music Libraries">' + librow("Music", r"\\nas\media\Music", "Music", default=True, kind="Music") + "</div>",
        f'<div class="libadd"><button class="btn quiet" type="button">{plus}Add Music Library</button></div>',
    ]
    page(fname, "Archive", "archive", form("Libraries settings", rows), sub="Libraries",
         note='<p class="ts setnote">A Job goes to its kind\'s default unless you pick another Library in its settings before it\'s filed. Each Library saves on its own, to <code>ama.toml</code>.</p>')


libraries("settings-libraries.html")
libraries("settings-libraries-edit.html", "edit")
libraries("settings-libraries-add.html", "add")
libraries("settings-libraries-remove.html", "remove")
libraries("settings-libraries-plex-off.html", "plex-off")


# ---------- Archive: NAS, Identification ----------

rows = [
    subnav("nas"),
    grp("NAS share", f'<span class="ts grpst"><span class="tstat">{ico("check")}Connected</span><span class="rnote">{ico("redo")}Used after a restart</span></span>'),
    sf("nas-unc", "Share", inp("nas-unc", r"\\nas\media"),
       hint=r"The shared folder on your NAS that holds your Libraries, like \\nas\media. AMA connects when it starts and keeps trying while it can't.",
       tech="Connected with Windows' <code>net use</code>."),
    sf("nas-user", "Username", inp("nas-user", placeholder="Logged-on Windows user"),
       hint="Leave empty to connect as the Windows user AMA runs as."),
    sf("nas-pass", "Password", inp("nas-pass", typ="password", placeholder="Not set"),
       hint="Once saved it's never shown again."),
    sf("nas-retry", "Try again every", inp("nas-retry", "60", typ="number", unit="seconds"),
       hint="How often AMA tries again while it can't reach the NAS."),
    foot("NAS"),
]
page("settings-nas.html", "Archive", "archive", form("NAS settings", rows), sub="NAS")

rows = [
    subnav("identification"),
    grp("TMDB", '<span class="ts">Used from the next Identification</span>'),
    sf("tmdb-key", "TMDB API key", secret_set("tmdb-key", "TMDB API key"), secret=True,
       hint="Lets AMA recognise films and TV series using The Movie Database. Without it every video Job goes to Review with no suggestions.",
       tech='The v3 "API Key" from your TMDB account settings.'),
    foot("Identification"),
]
page("settings-identification.html", "Archive", "archive", form("Identification settings", rows), sub="Identification")


# ---------- Alerts ----------

def alerts(fname, error=False):
    rows = []
    if error:
        rows.append(f'<div class="notice setnotice" role="alert" tabindex="-1" id="errsum">{ico("alert")}<div><b>Alerts weren\'t saved</b><code>ama.toml</code> hasn\'t changed. Fix these 2 fields:'
                    '<ul class="errlist"><li><a href="#discord-url">Discord webhook URL: paste the whole URL</a></li><li><a href="#ntfy-url">ntfy server: use a full address</a></li></ul></div></div>')
        discord = sf("discord-url", "Webhook URL",
                     '<input class="input bad" id="discord-url" type="password" name="discord-url" value="api/webhooks/1234" aria-describedby="discord-url-h discord-url-e" aria-invalid="true" spellcheck="false">'
                     f'<div class="ferr" id="discord-url-e">{ico("alert")}<span>Paste the whole webhook URL, starting with https://discord.com/api/webhooks/</span></div>'
                     '<button class="btn quiet" type="button">Keep the saved one</button>',
                     hint="Posts to a Discord channel when a Disc needs Review, is done or failed. Empty turns Discord off.")
        ntfy = sf("ntfy-url", "Server",
                  '<input class="input bad" id="ntfy-url" type="text" name="ntfy-url" value="ntfy.sh" aria-describedby="ntfy-url-h ntfy-url-e" aria-invalid="true" spellcheck="false">'
                  f'<div class="ferr" id="ntfy-url-e">{ico("alert")}<span>Enter a full address starting with https:// or http://</span></div>',
                  hint="The ntfy server your phone's ntfy app listens to. https://ntfy.sh is the free public one.")
    else:
        discord = sf("discord-url", "Webhook URL", secret_set("discord-url", "Discord webhook URL"), secret=True,
                     hint="Posts to a Discord channel when a Disc needs Review, is done or failed. Empty turns Discord off.")
        ntfy = sf("ntfy-url", "Server", inp("ntfy-url", "https://ntfy.sh"),
                  hint="The ntfy server your phone's ntfy app listens to. https://ntfy.sh is the free public one.")
    rows += [
        grp("Discord", '<span class="ts">Used from the next alert</span>'),
        discord,
        grp("ntfy", '<span class="ts">Used from the next alert</span>'),
        ntfy,
        sf("ntfy-topic", "Topic", secret_set("ntfy-topic", "ntfy topic"), secret=True,
           hint="Anyone who knows the topic can read your alerts, so it's kept like a password. Empty turns ntfy off."),
        foot("Alerts", "error" if error else "clean"),
    ]
    page(fname, "Alerts", "alerts", form("Alerts settings", rows),
         note='<p class="ts setnote">Alerts go out when a Disc needs Review, is filed (“insert the next one”) or failed. Plex scans are set under <a href="settings-libraries.html">Archive › Libraries</a>. Saved to <code>ama.toml</code>.</p>')


alerts("settings-notifications.html")
alerts("settings-notifications-error.html", error=True)


# ---------- Logs ----------

rows = [
    grp("Step output", '<span class="ts">Takes effect at once</span>'),
    sf("logs-keep", "Keep step output for", inp("logs-keep", "0", typ="number", unit="days"),
       hint="0 keeps it forever. Older output is removed at startup and once a day; Jobs, History and each run's summary are always kept."),
    foot("Logs"),
]
page("settings-logs.html", "Logs", "logs", form("Logs settings", rows))


# ---------- Per-Job settings: v2 nav and wording ----------

for f in ["job-settings-job-cd.html", "job-settings-job-video.html", "job-settings-rip-cd.html", "job-settings-rip-video.html"]:
    p = OUT / f
    s = p.read_text(encoding="utf-8")
    old = re.search(r'(<a class="skip"[^\n]*\n)?<header class="top">.*?</header>\n', s, re.S).group(0)
    cur = re.search(r'<a href="([a-z-]+)\.html" aria-current="page">', old)
    cur = {"now": "now", "history": "history"}.get(cur.group(1) if cur else "", None)
    rc = re.search(r'aria-label="(\d+) waiting"', old)
    used = int(re.search(r'aria-valuenow="(\d+)"', old).group(1))
    rhref = re.search(r'<a href="(review-[a-z]+\.html)"', old).group(1)
    s = s.replace(old, header(current=cur, review=int(rc.group(1)) if rc else 0, used=used, on_settings=False, review_href=rhref))
    s = s.replace("<main>", '<main id="main">')
    s = s.replace("<option>Work it out</option>", "<option>Decide automatically</option>")
    s = s.replace("<b>CQ 20</b>", "<b>Quality 20</b>")
    s = re.sub(r"<option( selected)?>CQ (\d+)</option>", r"<option\1>\2</option>", s)
    s = s.replace('<span class="note" id="e-q-n">Blu-ray default CQ 22', '<span class="note" id="e-q-n">Lower keeps more detail · Blu-ray default 22')
    s = s.replace("Blu-ray default CQ 22", "Blu-ray default 22")
    s = s.replace(">CQ 20<", ">20<")
    s = s.replace("First track + AAC stereo", "First track, plus a stereo copy")
    if "assets/menu.js" not in s:
        s = s.replace("</body>", '<script src="assets/menu.js"></script>\n</body>', 1)
    p.write_text(s, encoding="utf-8", newline="\n")
print("ok")
