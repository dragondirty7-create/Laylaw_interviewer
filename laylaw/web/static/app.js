// Laylaw client script. Stores nothing in localStorage/sessionStorage/IndexedDB:
// unsent answer text is saved to the server (encrypted), not to the browser.
(function () {
  "use strict";
  var pw = document.getElementById("show-password");
  if (pw) {
    pw.addEventListener("change", function () {
      var input = document.getElementById("current-password");
      if (input) input.type = pw.checked ? "text" : "password";
    });
  }

  var form = document.getElementById("answer-form");
  if (!form) return;
  var box = document.getElementById("answer");
  var status = document.getElementById("draft-status");
  var csrf = form.querySelector('input[name="csrf_token"]').value;
  var url = form.getAttribute("data-draft-url");
  var revision = form.getAttribute("data-draft-rev");
  var timer = null, last = box.value, inflight = false, stale = false;

  function save() {
    timer = null;
    if (stale || inflight || box.value === last) return;
    var text = box.value;
    inflight = true;
    fetch(url, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ text: text, revision: revision })
    }).then(function (r) {
      if (r.status === 401) { status.textContent = "You've been signed out. Copy your text, then sign in again."; return; }
      if (r.status === 409) {
        // Never overwrite a newer question's draft. Keep the text on screen.
        stale = true;
        status.textContent = "This interview changed on another device. Your text was not applied. Copy it, then reload the page.";
        return;
      }
      if (r.ok) { last = text; status.textContent = "Draft saved"; }
      else { status.textContent = "Couldn't save the draft just now."; }
    }).catch(function () {
      status.textContent = "Couldn't reach the server. Your text is still here.";
    }).finally(function () {
      inflight = false;
      if (box.value !== last) schedule();
    });
  }
  function schedule() { if (timer) clearTimeout(timer); timer = setTimeout(save, 1500); }
  box.addEventListener("input", function () { if (!stale) { status.textContent = ""; schedule(); } });
  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      form.querySelector('button[value="answer"]').click();
    }
  });
  window.addEventListener("pagehide", function () { if (box.value !== last) save(); });
})();
