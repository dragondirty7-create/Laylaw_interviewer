"""HTML for the local app. No JavaScript anywhere; every value is HTML-escaped."""
from __future__ import annotations

from html import escape

STYLE = """
:root{--bg:#f7f5f0;--fg:#1f2328;--muted:#5b616b;--card:#fff;--line:#d9d4c7;--accent:#2f5d50;--warn:#8a3b12;--warnbg:#fdf0e6}
@media (prefers-color-scheme:dark){:root{--bg:#1a1c1e;--fg:#e8e6e1;--muted:#a3a8b0;--card:#23262a;--line:#3a3e44;--accent:#7fbfa9;--warn:#f0a070;--warnbg:#3a2a20}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.5rem;margin:.2em 0 .6em}h2{font-size:1.15rem;margin:1.6em 0 .5em}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:14px 0}
.q{font-size:1.2rem;white-space:pre-wrap}.muted{color:var(--muted);font-size:.92rem}
.banner{background:var(--warnbg);color:var(--warn);border:1px solid var(--warn);border-radius:8px;padding:8px 12px;font-weight:600;margin-bottom:14px}
.msg{background:var(--card);border-left:4px solid var(--accent);padding:8px 12px;margin:10px 0}
.err{border-left-color:var(--warn)}
label{display:block;margin:10px 0 4px;font-weight:600}input[type=text],input[type=password],textarea,select{width:100%;padding:10px;font:inherit;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
textarea{min-height:140px}button{font:inherit;padding:9px 16px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;margin:10px 8px 0 0}
button.plain{background:transparent;color:var(--accent)}button.danger{border-color:var(--warn);background:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:.92rem}td,th{border-bottom:1px solid var(--line);padding:6px 4px;text-align:left;vertical-align:top}
pre{white-space:pre-wrap;font:inherit;font-size:.95rem}nav{display:flex;justify-content:space-between;align-items:center;gap:8px}
nav form{margin:0}a{color:var(--accent)}.inline{display:inline}
"""


def e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def page(title: str, body: str, *, banner: str = "", nav: str = "", messages: list[tuple[str, str]] = ()) -> str:
    msgs = "".join(f'<div class="msg {e(kind)}">{e(text)}</div>' for kind, text in messages)
    top = f'<div class="banner">{e(banner)}</div>' if banner else ""
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)} · Laylaw</title><style>{STYLE}</style></head>"
            f"<body><main>{top}{nav}{msgs}{body}</main></body></html>")


def csrf_field(token: str) -> str:
    return f'<input type=hidden name=csrf value="{e(token)}">'


def nav_bar(csrf: str) -> str:
    return (f'<nav><a href="/">Laylaw Interviewer</a><span>'
            f'<form method=post action="/lock" class=inline>{csrf_field(csrf)}'
            f'<button class=plain>Lock</button></form>'
            f'<form method=post action="/quit" class=inline>{csrf_field(csrf)}'
            f'<button class=plain>Lock and close</button></form></span></nav>')


def unlock_page(csrf: str, *, banner: str, messages) -> str:
    body = (f"<h1>Laylaw Interviewer</h1><div class=card><form method=post action='/unlock'>"
            f"{csrf_field(csrf)}<label for=pp>Passphrase</label>"
            f"<input type=password id=pp name=passphrase autocomplete=current-password autofocus required>"
            f"<button>Unlock</button></form></div>"
            f"<p class=muted>Your interviews are encrypted on this computer. Laylaw locks itself after "
            f"15 minutes without activity.</p>")
    return page("Unlock", body, banner=banner, messages=messages)


def refused_page(text: str) -> str:
    return page("Not available", f"<h1>Not available</h1><p>{e(text)}</p>")


def home_page(csrf: str, workspaces: list[tuple[str, list[dict]]], *, banner: str, messages) -> str:
    rows = []
    for cid, sessions in workspaces:
        for s in sessions:
            status = {"active": "In progress", "paused": "Saved for later", "paused_for_safety": "Paused for safety",
                      "closed": "Complete"}.get(s.get("status"), s.get("status"))
            rows.append(f"<tr><td><a href='/i/{e(cid)}/{e(s['id'])}'>{e(s.get('interviewee'))}</a></td>"
                        f"<td>{e(s.get('case_id'))}</td><td>{e(cid)}</td>"
                        f"<td>{e(str(s.get('path','')).replace('_', ' '))}</td><td>{e(status)}</td>"
                        f"<td class=muted>{e(str(s.get('updated',''))[:16].replace('T', ' '))}</td></tr>")
    table = ("<table><tr><th>Interviewee</th><th>Case</th><th>Workspace</th><th>Path</th><th>Status</th>"
             "<th>Updated (UTC)</th></tr>" + "".join(rows) + "</table>") if rows else \
        "<p class=muted>No interviews yet.</p>"
    body = (f"<h1>Interviews</h1><div class=card>{table}</div>"
            f"<h2>Start a new interview</h2><div class=card><form method=post action='/new'>{csrf_field(csrf)}"
            f"<label for=cid>Workspace label</label><input type=text id=cid name=client_id required "
            f"pattern='[A-Za-z0-9][A-Za-z0-9_-]{{0,63}}' placeholder='for example: client-a'>"
            f"<p class=muted>Letters, numbers, dashes. One workspace per client keeps their files separate.</p>"
            f"<label for=case>Case reference</label><input type=text id=case name=case_id required maxlength=80>"
            f"<label for=who>Interviewee's name</label><input type=text id=who name=interviewee required maxlength=120>"
            f"<label for=path>Interview type</label><select id=path name=path_name>"
            f"<option value=family_law>Family law</option><option value=criminal_defense>Criminal defense</option>"
            f"</select><label><input type=checkbox name=adult value=yes required> The interviewee is an adult"
            f"</label><button>Start interview</button></form></div>")
    return page("Interviews", body, banner=banner, nav=nav_bar(csrf), messages=messages)


def interview_page(csrf: str, cid: str, sid: str, *, meta: dict, question: str | None, state: str,
                   notice: str | None, records: list[dict], banner: str, messages) -> str:
    base = f"/i/{e(cid)}/{e(sid)}"
    head = (f"<h1>{e(meta['interviewee'])}</h1><p class=muted>Case {e(meta['case_id'])} · "
            f"{e(meta['path'].replace('_', ' '))} · workspace {e(cid)}</p>")
    if notice:
        head += f"<div class='msg err'>{e(notice)}</div>"
    if state == "resume":
        body = (f"<div class=card><p class=q>{e(question)}</p><form method=post action='{base}/resume'>"
                f"{csrf_field(csrf)}<button>Continue</button></form></div>")
    elif state == "wrong_workspace":
        body = ("<div class='card'><p class=q>You said this interview isn't for this person or case, so it has "
                "stopped. Check the details on the home page. If it is the right interview after all, confirm "
                f"below.</p><form method=post action='{base}/confirm'>{csrf_field(csrf)}"
                "<button>Yes, this is the right person and case</button></form></div>")
    elif state == "done":
        body = (f"<div class=card><p class=q>This interview is complete.</p>"
                f"<p><a href='/o/{e(cid)}/{e(sid)}'>View the interview outputs</a></p></div>")
    else:
        safety = ("<p class=muted>Ordinary questions are paused until it's safe to continue. If anyone is in "
                  "danger right now, call 911.</p>") if state == "safety" else ""
        body = (f"<div class=card><p class=q>{e(question)}</p>{safety}"
                f"<form method=post action='{base}/answer'>{csrf_field(csrf)}"
                f"<label for=a>Answer</label><textarea id=a name=answer autofocus></textarea>"
                f"<button name=action value=answer>Answer</button>"
                f"<button class=plain name=action value=skip formnovalidate>Skip</button>"
                f"<button class=plain name=action value=not_sure formnovalidate>Not sure</button>"
                f"<button class=plain name=action value=save_later formnovalidate>Save and finish later</button>"
                f"</form></div>")
    rec_rows = "".join(f"<li>{e(r['label'])} <span class=muted>({e(r['size'])} bytes, stored encrypted)</span></li>"
                       for r in records)
    uploads = (f"<h2>Documents</h2><div class=card>"
               + (f"<ul>{rec_rows}</ul>" if rec_rows else "<p class=muted>No documents yet.</p>")
               + f"<form method=post action='{base}/upload' enctype='multipart/form-data'>{csrf_field(csrf)}"
               f"<label for=f>Add a document</label><input type=file id=f name=file required>"
               f"<label for=lb>Short description (optional)</label><input type=text id=lb name=label maxlength=120>"
               f"<button>Upload</button></form></div>")
    tail = (f"<p><a href='/o/{e(cid)}/{e(sid)}'>Outputs so far</a> · <a href='/d/{e(cid)}/{e(sid)}'>Delete this "
            f"interview</a></p>")
    return page(meta["interviewee"], head + body + uploads + tail, banner=banner, nav=nav_bar(csrf),
                messages=messages)


def _table(rows: list[dict]) -> str:
    if not rows:
        return "<p class=muted>None.</p>"
    cols = list(rows[0].keys())
    head = "".join(f"<th>{e(c.replace('_', ' '))}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{e(r.get(c))}</td>" for c in cols) + "</tr>" for r in rows)
    return f"<table><tr>{head}</tr>{body}</table>"


def _list(items: list) -> str:
    return "<ul>" + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>" if items else "<p class=muted>None.</p>"


def outputs_page(csrf: str, cid: str, sid: str, meta: dict, out: dict, *, banner: str, messages) -> str:
    body = (f"<h1>Interview outputs</h1><p class=muted>{e(meta['interviewee'])} · case {e(meta['case_id'])}. "
            f"<a href='/i/{e(cid)}/{e(sid)}'>Back to the interview</a></p>"
            f"<p class=muted>These are shown on screen only. Export is turned off for encrypted data; printing or "
            f"saving this page creates an unencrypted copy.</p>"
            f"<h2>Handoff summary</h2><div class=card><pre>{e(out['handoff_summary'])}</pre></div>"
            f"<h2>Fact table</h2><div class=card>{_table(out['fact_table'])}</div>"
            f"<h2>Timeline</h2><div class=card>{_table(out['timeline'])}</div>"
            f"<h2>Evidence follow-up</h2><div class=card>{_list(out['evidence_followup'])}</div>"
            f"<h2>Open questions</h2><div class=card>{_list(out['open_questions'])}</div>"
            f"<h2>Requested outcomes</h2><div class=card>{_table(out['requested_outcomes'])}</div>"
            f"<h2>Interview record</h2><div class=card><pre>{e(out['interview_record'])}</pre></div>")
    return page("Outputs", body, banner=banner, nav=nav_bar(csrf), messages=messages)


def delete_page(csrf: str, cid: str, sid: str, meta: dict, *, banner: str) -> str:
    body = (f"<h1>Delete this interview?</h1><div class=card><p>This permanently removes the interview with "
            f"{e(meta['interviewee'])} (case {e(meta['case_id'])}) and its documents from Laylaw on this "
            f"computer. It can't be undone. Backups made outside Laylaw are not affected.</p>"
            f"<form method=post action='/d/{e(cid)}/{e(sid)}'>{csrf_field(csrf)}"
            f"<label for=c>Type DELETE to confirm</label><input type=text id=c name=confirm required>"
            f"<button class=danger>Delete permanently</button></form>"
            f"<p><a href='/i/{e(cid)}/{e(sid)}'>Cancel</a></p></div>")
    return page("Delete", body, banner=banner, nav=nav_bar(csrf))


def closed_page() -> str:
    return page("Closed", "<h1>Laylaw is locked and closed.</h1><p>You can close this browser tab.</p>")
