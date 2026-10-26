"""Visual QA for the supervision intake at phone width. Synthetic vault only.

Walks the flow in a real Chromium at 390x844 (and once at 1280 desktop),
screenshots each distinct page, and fails on horizontal scroll or console errors.
"""
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright  # noqa: E402

from laylaw.app.server import LaylawApp, launch_url, make_server  # noqa: E402
from laylaw.secure.secrets_store import MemorySecretStore  # noqa: E402
from laylaw.secure.vault import init_vault  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
PASS = "fictional passphrase 42"
root = Path(tempfile.mkdtemp()) / "vault"
ss = MemorySecretStore()
v, _ = init_vault(root, PASS, secret_store=ss, mode="synthetic", kdf_n=2 ** 12)
v.lock()
app = LaylawApp(root, ss)
server = make_server(app)
threading.Thread(target=server.serve_forever, daemon=True).start()

problems, shots = [], []
ANS = {
    "danger_now": "no", "about_adult": "yes", "filled_by": "helper", "matter_type": "both", "held_now": "no",
    "deadline_date": "2026-11-03", "deadline_what": "enroll", "deadline_source": "paper",
    "deadline_consequence": "nothing was said", "rehab_said": "yes", "rehab_who": "probation",
    "rehab_form": "written_condition",
    "rehab_doc_words": "FICTIONAL: shall enroll in and complete a treatment program as directed",
    "rehab_recollection": "FICTIONAL: the officer said it has to be live-in", "rehab_level": "generic",
    "hoping_for": "FICTIONAL: whether outpatient could be considered", "stage_gate": "now",
    "charge_text": "FICTIONAL CHARGE", "court_county": "Fictional County", "case_ref": "FICT-0000",
    "arrest_date": "2026-09-01", "next_appearance": "2026-11-10", "release_status": "conditions",
    "counsel": "public_defender", "supervision_on_paper": "not_sure", "led_to": "a new assessment",
    "assessment": "yes", "assessment_words": "FICTIONAL: intensive outpatient", "nonres_approval": "mentioned",
    "hold": "no", "unresolved": "FICTIONAL: none",
}
MULTI = {"supervision_kinds": ["probation", "prcs"], "nonres_discussed": ["outpatient", "iop"],
         "supports": ["transport", "work"]}


def check(page, name, width):
    sw = page.evaluate("document.documentElement.scrollWidth")
    if sw > width:
        problems.append(f"{name}: horizontal scroll ({sw}px > {width}px)")
    path = OUT / f"{len(shots):02d}-{name}-{width}.png"
    page.screenshot(path=str(path), full_page=True)
    shots.append(path)


with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    page.goto(launch_url(app))
    for width, height in ((390, 844), (1280, 900)):
        page.set_viewport_size({"width": width, "height": height})
        if page.locator("input[name=passphrase]").count():
            page.fill("input[name=passphrase]", PASS)
            page.click("button")
        page.goto(f"http://127.0.0.1:{app.port}/")
        forms = page.locator("form[action='/intake/new']")
        sup = forms.filter(has=page.locator("input[name=flow][value=supervision]"))
        sup.locator("input[name=nickname]").fill("fictional QA")
        sup.locator("input[name=adult]").check()
        sup.locator("button").click()
        seen = set()
        for _ in range(60):
            step = page.locator("input[name=step]")
            if step.count() == 0 or "Everything has been asked" in page.content():
                break
            sid = step.first.get_attribute("value")
            if width == 390 and sid in ("danger_now", "matter_type", "rehab_form", "rehab_doc_words", "first_files",
                                        "supervision_kinds", "nonres_discussed") and sid not in seen:
                check(page, sid, width)
            seen.add(sid)
            if sid in MULTI:
                for v in MULTI[sid]:
                    page.check(f"input[name=multi][value={v}]")
                page.click("button[name=action][value=answer]")
            elif sid == "first_files":
                page.set_input_files("input[name=file]", {"name": "fictional-conditions.pdf",
                                                          "mimeType": "application/pdf",
                                                          "buffer": b"FICTIONAL-PDF"})
                page.select_option("select[name=category]", "conditions")
                page.click("text=Add this file")
                page.click("button[name=action][value=done]")
            else:
                v = ANS.get(sid)
                radio = page.locator(f"input[type=radio][value='{v}']")
                if radio.count():
                    radio.check()
                elif page.locator("input[type=date]").count():
                    page.fill("input[type=date]", v)
                elif page.locator("textarea[name=value]").count():
                    page.fill("textarea[name=value]", v)
                else:
                    page.fill("input[name=value]", v, timeout=5000)
                page.click("button[name=action][value=answer]")
        base = page.url.split("/review")[0].rstrip("/")
        page.goto(base + "/review")
        check(page, "review", width)
        page.goto(base + "/packet")
        check(page, "packet", width)
        text = page.inner_text("body")
        for needle in ("RAPID SITUATION SUMMARY", "REQUIREMENT SOURCE MAP", "NONRESIDENTIAL OPTIONS COMPARISON",
                       "DOCUMENT STATES (as typed in)", "all unchanged"):
            if needle not in text:
                problems.append(f"packet missing: {needle}")
    ctx.close()
    browser.close()
server.shutdown()
print("screenshots:", len(shots))
print("PROBLEMS:" if problems else "no problems", *problems, sep="\n")
