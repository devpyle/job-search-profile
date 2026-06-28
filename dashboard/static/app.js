// Shared utilities — page-specific logic lives in each template's {% block scripts %}

function showToast(msg, isError = false) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.className = "toast" + (isError ? " toast-error" : "");
  setTimeout(() => t.classList.add("hidden"), 3500);
}

// Quick-close a card to an end state (Passed / Rejected) without dragging it
// down to the collapsed "closed" section. Opens a small menu by the ✕ button.
function closeJob(evt, jobId) {
  evt.stopPropagation();
  evt.preventDefault();
  document.querySelectorAll(".close-menu").forEach(m => m.remove());

  const rect = evt.currentTarget.getBoundingClientRect();
  const menu = document.createElement("div");
  menu.className = "close-menu";
  menu.style.top  = (rect.bottom + 4) + "px";
  menu.style.left = Math.max(8, rect.right - 130) + "px";

  [["Passed", "Passed — not pursuing"], ["Rejected", "Rejected by them"]].forEach(([status, label]) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.onclick = (e) => { e.stopPropagation(); doCloseJob(jobId, status, menu); };
    menu.appendChild(b);
  });

  document.body.appendChild(menu);
  setTimeout(() => {
    document.addEventListener("click", function onDoc(e) {
      if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener("click", onDoc); }
    });
  }, 0);
}

function doCloseJob(jobId, status, menu) {
  fetch(`/jobs/${jobId}/move`, {
    method:  "POST",
    headers: {"Content-Type": "application/json"},
    body:    JSON.stringify({ status }),
  })
  .then(r => r.json())
  .then(d => {
    if (menu) menu.remove();
    if (d.ok) {
      const card = document.querySelector(`[data-job-id="${jobId}"]`);
      if (card) card.remove();
      if (typeof updateBadges === "function") updateBadges();
      showToast(`Moved to ${status}`);
    } else {
      showToast("Move failed: " + (d.error || ""), true);
    }
  })
  .catch(() => { if (menu) menu.remove(); showToast("Move failed", true); });
}
