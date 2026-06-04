/* davidmyers.work — interactions
   - staggered scroll reveals (IntersectionObserver)
   - nav hairline + shrink on scroll
   - current year in footer
   Progressive enhancement: content is fully visible if JS is off
   (the .reveal opacity is restored here, not assumed).            */

(function () {
  "use strict";

  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- current year ---- */
  var yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());

  /* ---- nav state on scroll ---- */
  var nav = document.getElementById("nav");
  if (nav) {
    var onScroll = function () {
      if (window.scrollY > 8) nav.classList.add("scrolled");
      else nav.classList.remove("scrolled");
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  /* ---- scroll reveals ---- */
  var revealEls = Array.prototype.slice.call(document.querySelectorAll(".reveal, .tl-item"));

  if (reduceMotion || !("IntersectionObserver" in window)) {
    revealEls.forEach(function (el) { el.classList.add("is-visible"); });
    return;
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      var el = entry.target;
      // stagger siblings within the same container for a cascade effect
      var siblings = Array.prototype.slice.call(el.parentNode.children)
        .filter(function (c) { return c.classList.contains("reveal") || c.classList.contains("tl-item"); });
      var index = siblings.indexOf(el);
      el.style.transitionDelay = Math.min(index, 5) * 80 + "ms";
      el.classList.add("is-visible");
      io.unobserve(el);
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });

  revealEls.forEach(function (el) { io.observe(el); });
})();
