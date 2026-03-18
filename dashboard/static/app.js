// Shared utilities — page-specific logic lives in each template's {% block scripts %}

function showToast(msg, isError = false) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.className = "toast" + (isError ? " toast-error" : "");
  setTimeout(() => t.classList.add("hidden"), 3500);
}
