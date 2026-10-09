"""HTML for the Rapid Incident Intake. No JavaScript; every value is escaped.

Mobile first: one question per page, large tap targets, nothing wider than the
screen (tables scroll inside their card rather than pushing the page sideways).
"""
from __future__ import annotations

from ..intake.chronology import BASIS_LABELS, chronology, evidence_inventory, open_questions
from ..intake.model import EVIDENCE_CATEGORIES, AnswerStatus, IncidentIntake
from ..intake.packet import build_packet
from ..intake.steps import SAFETY_MESSAGE, STEP_BY_ID, Step
from .pages import csrf_field, e, nav_bar, page

STYLE = """
<style>
.progress{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin:6px 0 2px}
.progress>span{display:block;height:100%;background:var(--accent)}
.choices label{display:flex;gap:10px;align-items:flex-start;font-weight:400;border:1px solid var(--line);
 border-radius:10px;padding:12px 14px;margin:8px 0;cursor:pointer;min-height:48px}
.choices input{margin-top:4px;transform:scale(1.3)}
.why{background:var(--bg);border-left:4px solid var(--accent);padding:8px 12px;margin:10px 0;font-size:.92rem}
.safety{background:var(--warnbg);color:var(--warn);border:1px solid var(--warn);border-radius:8px;padding:10px 12px;
 margin:12px 0;font-weight:600}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.example{white-space:pre-wrap}
.row-actions{display:flex;flex-wrap:wrap;gap:0 8px}
dl.review{margin:0}dl.review dt{font-weight:600;margin-top:12px}dl.review dd{margin:2px 0 0 0;white-space:pre-wrap}
input[type=date]{width:100%;padding:10px;font:inherit;border:1px solid var(--line);border-radius:8px;
 background:var(--bg);color:var(--fg)}
input[type=file]{max-width:100%}
button{min-height:44px}
pre,dd,td{overflow-wrap:anywhere}
</style>
"""


def _base(cid: str, mid: str) -> str:
    return f"/n/{e(cid)}/{e(mid)}"


def _progress_text(m: dict) -> str:
    return "Done" if m["finished"] else f"{e(m['done'])} of about {e(m['total'])}"


def home_section(csrf: str, matters: list[dict]) -> str:
    rows = "".join(
        f"<tr><td><a href='/n/{e(m['client_id'])}/{e(m['matter_id'])}'>{e(m['nickname'] or 'Incident intake')}</a>"
        f"</td><td>{_progress_text(m)}"
        f"</td><td>{e(m['files'])}</td><td class=muted>{e(str(m['updated'])[:16].replace('T', ' '))}</td></tr>"
        for m in matters)
    table = (f"<div class=scroll><table><tr><th>Intake</th><th>Progress</th><th>Files</th><th>Updated (UTC)</th>"
             f"</tr>{rows}</table></div>") if rows else "<p class=muted>No incident intakes yet.</p>"
    return (f"<h2>Incident intakes</h2><div class=card>{table}</div>"
            f"<div class=card><form method=post action='/intake/new'>{csrf_field(csrf)}"
            f"<p><strong>Start an incident intake</strong></p>"
            f"<p class=muted>For writing down one incident while it's fresh. It's kept separate from every "
            f"other interview and client.</p>"
            f"<label for=nick>A short name you'll recognise (optional)</label>"
            f"<input type=text id=nick name=nickname maxlength=80 placeholder='for example: maintenance entry'>"
            f"<p class=muted>Don't put names or addresses here.</p>"
            f"<label><input type=checkbox name=adult value=yes required> I'm an adult filling this out</label>"
            f"<button>Start</button></form></div>")


def _header(intake: IncidentIntake, step: Step | None) -> str:
    done, total = intake.progress()
    pct = int(100 * done / total) if total else 100
    section = e(step.section) if step else "Review"
    stage = "The essentials" if step is not None and step.stage == 1 else "More detail"
    label = (stage if section == stage else f"{stage} · {section}") if step else "Review"
    title = e(intake.nickname or "Incident intake")
    return (f"<h1>{title}</h1><p class=muted>{label} · {done} of about {total} answered</p>"
            f"<div class=progress aria-hidden=true><span style='width:{pct}%'></span></div>")


def _safety(intake: IncidentIntake, *, full: bool = False) -> str:
    """The full message right after the person says yes (and on the review page); a short line after that."""
    if intake.plain_answers().get("danger_now") != "yes":
        return ""
    if full or intake.current == "summary":
        return f"<div class=safety role=alert>{e(SAFETY_MESSAGE)}</div>"
    return "<p class=muted><strong>If anyone is in danger right now, call 911.</strong></p>"


def _upload_form(csrf: str, cid: str, mid: str, back: str) -> str:
    opts = "".join(f"<option value='{e(k)}'>{e(v)}</option>" for k, v in EVIDENCE_CATEGORIES)
    return (f"<form method=post action='{_base(cid, mid)}/evidence' enctype='multipart/form-data'>{csrf_field(csrf)}"
            f"<input type=hidden name=back value='{e(back)}'>"
            f"<label for=f>Choose a file</label><input type=file id=f name=file required>"
            f"<label for=cat>What is it?</label><select id=cat name=category>{opts}</select>"
            f"<details><summary>Add details (optional)</summary>"
            f"<label for=src>Where it came from</label><input type=text id=src name=source maxlength=120 "
            f"placeholder='for example: my phone'>"
            f"<label for=dt>Its date or time, if you know it</label><input type=text id=dt name=date_text "
            f"maxlength=40 placeholder='for example: 2026-10-01 10:20'>"
            f"<label for=nt>Notes</label><input type=text id=nt name=notes maxlength=500></details>"
            f"<p class=muted>The file is stored encrypted and kept exactly as it is. Notes are saved beside it, "
            f"never inside it.</p><button>Add this file</button></form>")


def _files_list(intake: IncidentIntake) -> str:
    if not intake.evidence:
        return "<p class=muted>No files yet.</p>"
    return "<ul>" + "".join(
        f"<li>{e(i['file'])} <span class=muted>({e(i['kind'])}, {e(i['original']).lower()})</span></li>"
        for i in evidence_inventory(intake)) + "</ul>"


def step_page(csrf: str, intake: IncidentIntake, step: Step, *, editing: bool, banner: str, messages) -> str:
    cid, mid = intake.client_id, intake.matter_id
    base = _base(cid, mid)
    help_ = f"<p class=muted>{e(step.help)}</p>" if step.help else ""
    example = f"<p class='muted example'>{e(step.example)}</p>" if step.example else ""
    why = f"<div class=why><strong>Why we ask:</strong> {e(step.why)}</div>" if step.why else ""
    current = intake.answers.get(step.id)
    prior = current.value if current and current.status == AnswerStatus.ANSWERED else ""
    hidden = f"{csrf_field(csrf)}<input type=hidden name=step value='{e(step.id)}'>"

    if step.kind == "choice":
        field = "<div class=choices role=radiogroup>" + "".join(
            f"<label><input type=radio name=value value='{e(k)}'{' checked' if prior == k else ''} required>"
            f"<span>{e(v)}</span></label>" for k, v in step.choices) + "</div>"
    elif step.kind == "long":
        field = f"<label for=v class=muted>Your answer</label><textarea id=v name=value maxlength={step.max_len}>" \
                f"{e(prior)}</textarea>"
    elif step.kind == "date":
        field = f"<label for=v class=muted>Date</label><input type=date id=v name=value value='{e(prior)}'>"
    elif step.kind == "upload":
        field = ""
    else:
        field = (f"<label for=v class=muted>Your answer</label><input type=text id=v name=value "
                 f"maxlength={step.max_len} value='{e(prior)}' autocomplete=off>")

    has_unsure = step.kind == "choice" and any(k == "not_sure" for k, _ in step.choices)
    buttons = "<div class=row-actions>"
    if step.kind == "upload":
        buttons += "<button name=action value=done formnovalidate>Continue</button>"
    else:
        buttons += "<button name=action value=answer>Continue</button>"
        if not has_unsure and step.id != "stage_gate":
            buttons += "<button class=plain name=action value=not_sure formnovalidate>I'm not sure</button>"
    if step.id != "stage_gate":
        buttons += "<button class=plain name=action value=skip formnovalidate>Skip</button>"
    if editing:
        buttons += "<button class=plain name=action value=cancel_edit formnovalidate>Cancel change</button>"
    else:
        buttons += "<button class=plain name=action value=back formnovalidate>Back</button>"
        buttons += "<button class=plain name=action value=later formnovalidate>Save and finish later</button>"
    buttons += "</div>"

    question = f"<p class=q><label for=v style='font-weight:400;margin:0'>{e(step.prompt)}</label></p>"
    if step.kind == "upload":
        # Files first, then Continue, so nobody moves on before adding what they meant to add.
        body = (STYLE + _header(intake, step) + _safety(intake) + f"<div class=card>{question}{help_}"
                f"{_upload_form(csrf, cid, mid, 'step')}<h2>Files added</h2>{_files_list(intake)}"
                f"<form method=post action='{base}/answer'>{hidden}{buttons}</form></div>")
    else:
        body = (STYLE + _header(intake, step) + _safety(intake)
                + f"<div class=card><form method=post action='{base}/answer'>{hidden}{question}"
                f"{help_}{why}{field}{example}{buttons}</form></div>")
    body += f"<p class=muted><a href='{base}/review'>See everything so far</a></p>"
    return page("Incident intake", body, banner=banner, nav=nav_bar(csrf), messages=messages)


def review_page(csrf: str, intake: IncidentIntake, *, banner: str, messages) -> str:
    cid, mid = intake.client_id, intake.matter_id
    base = _base(cid, mid)
    items = []
    for step in intake.applicable_steps():
        if step.kind == "upload" or step.id == "stage_gate":
            continue
        a = intake.answers.get(step.id)
        if a is None:
            shown = "<span class=muted>Not answered yet</span>"
        elif a.status == AnswerStatus.NOT_SURE:
            shown = "<span class=muted>Not sure</span>"
        elif a.status == AnswerStatus.SKIPPED:
            shown = "<span class=muted>Skipped</span>"
        else:
            shown = e(dict(step.choices).get(a.value, a.value) if step.kind == "choice" else a.value)
        change = (f"<form method=post action='{base}/edit' class=inline>{csrf_field(csrf)}"
                  f"<input type=hidden name=step value='{e(step.id)}'><button class=plain>Change</button></form>"
                  if a is not None else "")
        items.append(f"<dt>{e(step.prompt)}</dt><dd>{shown} {change}</dd>")
    status = ("<p>Everything has been asked. Look it over, change anything that's not right, then open the "
              "referral packet.</p>") if intake.finished else \
        (f"<p>Some questions are still to come. <a href='{base}'>Continue where you left off</a>.</p>")

    rows = "".join(f"<tr><td>{e(r.when)}</td><td>{e(r.what)}</td><td>{e(BASIS_LABELS[r.basis])}"
                   + (f"<br><span class=muted>time: {e(BASIS_LABELS[r.when_basis].lower())}</span>"
                      if r.when_basis != r.basis else "") + "</td></tr>" for r in chronology(intake))
    inv = "".join(f"<tr><td>{e(i['file'])}</td><td>{e(i['kind'])}</td><td>{e(i['source'])}</td>"
                  f"<td>{e(i['date'])}</td><td>{e(i['original'])}</td><td>{e(i['notes'])}</td></tr>"
                  for i in evidence_inventory(intake))
    inv_table = (f"<div class=scroll><table><tr><th>File</th><th>Kind</th><th>From</th><th>Date</th>"
                 f"<th>Original</th><th>Notes</th></tr>{inv}</table></div>") if inv else \
        "<p class=muted>No files yet.</p>"
    questions = "".join(f"<li>{e(q)}</li>" for q in open_questions(intake))
    child = ""
    if intake.child_statement:
        child = (f"<h2>The child's own words</h2><div class=card><p>“{e(intake.child_statement['words'])}"
                 f"”</p><p class=muted>Recorded once, exactly as entered, and not changed afterwards.</p></div>")
    body = (STYLE + _header(intake, None) + _safety(intake, full=True) + f"<div class=card>{status}</div>"
            f"<h2>Your answers</h2><div class=card><dl class=review>{''.join(items)}</dl></div>{child}"
            f"<h2>What happened, in order</h2><div class=card><div class=scroll><table><tr><th>When</th>"
            f"<th>What</th><th>Based on</th></tr>{rows}</table></div></div>"
            f"<h2>Files</h2><div class=card>{inv_table}{_upload_form(csrf, cid, mid, 'review')}</div>"
            f"<h2>Still open</h2><div class=card>"
            + (f"<ul>{questions}</ul>" if questions else "<p class=muted>Nothing open.</p>") + "</div>"
            f"<p><a href='{base}/packet'><strong>Open the referral packet</strong></a> · "
            f"<a href='{base}/delete'>Delete this intake</a></p>")
    return page("Review", body, banner=banner, nav=nav_bar(csrf), messages=messages)


def packet_page(csrf: str, intake: IncidentIntake, *, integrity: dict[str, bool], banner: str, messages) -> str:
    packet = build_packet(intake)
    base = _base(intake.client_id, intake.matter_id)
    bad = [i for i in intake.evidence if not integrity.get(i.id, False)]
    check = ("<p class=muted>Every file was checked just now against the fingerprint taken when it was added: "
             "all unchanged.</p>") if intake.evidence and not bad else \
        (f"<div class='msg err'>{len(bad)} file(s) did not match their original fingerprint.</div>" if bad else "")
    body = (STYLE + f"<h1>Referral packet</h1><p class=muted><a href='{base}/review'>Back to the review</a></p>"
            f"<p class=muted>Shown on screen only. Export is turned off for encrypted data; printing or saving "
            f"this page creates an unencrypted copy.</p>{check}"
            f"<div class=card><pre>{e(packet['text'])}</pre></div>")
    return page("Referral packet", body, banner=banner, nav=nav_bar(csrf), messages=messages)


def delete_page(csrf: str, intake: IncidentIntake, *, banner: str) -> str:
    base = _base(intake.client_id, intake.matter_id)
    body = (f"<h1>Delete this intake?</h1><div class=card><p>This permanently removes this incident intake and "
            f"its {len(intake.evidence)} file(s) from Laylaw on this computer. It can't be undone.</p>"
            f"<form method=post action='{base}/delete'>{csrf_field(csrf)}"
            f"<label for=c>Type DELETE to confirm</label><input type=text id=c name=confirm required>"
            f"<button class=danger>Delete permanently</button></form><p><a href='{base}/review'>Cancel</a></p></div>")
    return page("Delete", body, banner=banner, nav=nav_bar(csrf))
