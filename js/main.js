(function () {
  "use strict";

  var config = window.SITE_CONFIG || {};
  var hasValue = function (v) { return typeof v === "string" && v.trim() !== ""; };

  /* ---------- Botones de contacto ---------- */
  var builders = {
    email: function (v) { return "mailto:" + v.trim(); },
    linkedin: function (v) { return v.trim(); },
    whatsapp: function (v) {
      var number = v.replace(/\D/g, "");
      var text = hasValue(config.whatsappMensaje) ? "?text=" + encodeURIComponent(config.whatsappMensaje) : "";
      return number ? "https://wa.me/" + number + text : "";
    },
    cv: function (v) { return v.trim(); }
  };

  var anyPending = false;
  document.querySelectorAll("[data-contact]").forEach(function (btn) {
    var key = btn.getAttribute("data-contact");
    var value = config[key];
    var href = hasValue(value) && builders[key] ? builders[key](value) : "";

    if (href) {
      btn.setAttribute("href", href);
      if (key === "linkedin" || key === "whatsapp") {
        btn.setAttribute("target", "_blank");
        btn.setAttribute("rel", "noopener");
      }
      if (key === "cv") btn.setAttribute("download", "");
    } else {
      // Sin destino: el <a> no tiene href, por lo que no es clickeable ni enfocable.
      anyPending = true;
      btn.classList.add("is-pending");
      btn.setAttribute("aria-disabled", "true");
      btn.setAttribute("title", "Dato pendiente de cargar");
      var badge = document.createElement("span");
      badge.className = "pending-badge";
      badge.textContent = "pendiente";
      btn.appendChild(badge);
    }
  });

  var note = document.querySelector(".contact-pending-note");
  if (note && anyPending) note.hidden = false;

  /* ---------- Foto ---------- */
  var photoSlot = document.querySelector("[data-foto]");
  if (photoSlot && hasValue(config.foto)) {
    var img = new Image();
    img.alt = "Francisco Gauna";
    img.width = 760;
    img.height = 950;
    img.onload = function () { photoSlot.innerHTML = ""; photoSlot.appendChild(img); };
    img.src = config.foto.trim();
  }

  /* ---------- Menú móvil ---------- */
  var toggle = document.querySelector(".nav-toggle");
  var menu = document.getElementById("nav-menu");
  var closeMenu = function () {
    menu.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
  };
  if (toggle && menu) {
    toggle.addEventListener("click", function () {
      var open = menu.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    menu.addEventListener("click", function (e) { if (e.target.closest("a")) closeMenu(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenu(); });
  }

  /* ---------- Header con sombra al hacer scroll ---------- */
  var header = document.querySelector(".site-header");
  var onScroll = function () { header.classList.toggle("is-scrolled", window.scrollY > 8); };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- Enlace activo en la navegación ---------- */
  if ("IntersectionObserver" in window) {
    var links = {};
    document.querySelectorAll(".nav-menu a[href^='#']").forEach(function (a) {
      links[a.getAttribute("href").slice(1)] = a;
    });
    var sectionObserver = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        Object.keys(links).forEach(function (id) { links[id].classList.remove("is-active"); });
        var link = links[entry.target.id];
        if (link) link.classList.add("is-active");
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    document.querySelectorAll("main section[id]").forEach(function (s) { sectionObserver.observe(s); });

    /* ---------- Aparición suave ---------- */
    var revealTargets = document.querySelectorAll(".section-head, .about-body, .project-card, .area, .timeline-item, .work-box");
    var revealObserver = new IntersectionObserver(function (entries, obs) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    revealTargets.forEach(function (el) { el.classList.add("reveal"); revealObserver.observe(el); });
  }

  /* ---------- Año del footer ---------- */
  var year = document.querySelector("[data-year]");
  if (year) year.textContent = new Date().getFullYear();
})();
