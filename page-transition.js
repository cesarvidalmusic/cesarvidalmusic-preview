/*
 * César Vidal — page transition v8
 * Prueba limitada a Bio <-> Gonzalez Reeds.
 * Wash oscuro idéntico en ambos sentidos, sin capturas ni iframes.
 */

(function () {
  "use strict";

  const STORAGE_KEY = "cv-soft-page-transition-v8";

  const ALLOWED_PAGES = new Set([
    "bio.html",
    "gonzalez-reeds.html"
  ]);

  const OUT_DURATION = 800;
  const IN_DURATION = 1080;
  const MAX_ASSET_WAIT = 420;
  const MAX_INTENT_AGE = 12000;

  let isNavigating = false;
  let outgoingOverlay = null;

  function pageName(url) {
    const pathname = new URL(url, location.href).pathname;
    return pathname.split("/").pop() || "index.html";
  }

  function transitionAllowed(link) {
    if (!link || !link.href || link.hasAttribute("download")) {
      return false;
    }

    if (link.target && link.target !== "_self") {
      return false;
    }

    if (link.closest(".cv-nav-soon")) {
      return false;
    }

    const destination = new URL(link.href, location.href);

    if (destination.origin !== location.origin) {
      return false;
    }

    if (destination.href === location.href) {
      return false;
    }

    if (destination.pathname === location.pathname) {
      return false;
    }

    return (
      ALLOWED_PAGES.has(pageName(location.href)) &&
      ALLOWED_PAGES.has(pageName(destination.href))
    );
  }

  function addOutgoingStyles() {
    if (document.getElementById("cv-transition-v8-style")) {
      return;
    }

    const style = document.createElement("style");

    style.id = "cv-transition-v8-style";

    style.textContent = `
      .cv-transition-v8-curtain {
        position: fixed;
        inset: 0;
        z-index: 2147483600;
        opacity: 0;
        pointer-events: none;

        background:
          radial-gradient(
            ellipse at 57% 63%,
            rgba(44,85,68,0.18),
            transparent 75%
          ),
          #242017;

        transition:
          opacity ${OUT_DURATION}ms cubic-bezier(0.40, 0, 0.22, 1);
      }

      .cv-transition-v8-curtain.is-covered {
        opacity: 1;
        pointer-events: auto;
      }

      html.cv-transition-v8-leaving .cv-page {
        filter: blur(7px) brightness(0.90);
        transform: scale(1.008);

        transition:
          filter ${OUT_DURATION}ms cubic-bezier(0.40, 0, 0.22, 1),
          transform ${OUT_DURATION}ms cubic-bezier(0.40, 0, 0.22, 1);
      }

      @media (prefers-reduced-motion: reduce) {
        .cv-transition-v8-curtain,
        html.cv-transition-v8-leaving .cv-page {
          transition-duration: 80ms;
        }
      }
    `;

    document.head.appendChild(style);
  }

  function saveIntent(destination) {
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          target: new URL(destination, location.href).pathname,
          time: Date.now()
        })
      );

      return true;

    } catch (error) {
      return false;
    }
  }

  function clearIntent() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (error) {
      // Ignorar errores de almacenamiento.
    }
  }

  function navigate(destination) {
    if (isNavigating) {
      return;
    }

    isNavigating = true;

    addOutgoingStyles();

    outgoingOverlay = document.createElement("div");
    outgoingOverlay.className = "cv-transition-v8-curtain";
    outgoingOverlay.setAttribute("aria-hidden", "true");

    document.body.appendChild(outgoingOverlay);

    // Asegura que el navegador registre el estado inicial
    // antes de comenzar la animación.

    void outgoingOverlay.offsetWidth;

    document.documentElement.classList.add(
      "cv-transition-v8-leaving"
    );

    requestAnimationFrame(() => {
      outgoingOverlay.classList.add("is-covered");
    });

    const duration = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches
      ? 90
      : OUT_DURATION + 40;

    window.setTimeout(() => {
      saveIntent(destination);
      location.assign(destination);
    }, duration);
  }

  function waitForImagesBriefly() {
    const incomplete = Array.from(document.images).filter(
      (img) => !img.complete
    );

    if (incomplete.length === 0) {
      return Promise.resolve();
    }

    const imagesReady = Promise.all(
      incomplete.map(
        (img) => new Promise((resolve) => {
          img.addEventListener("load", resolve, { once: true });
          img.addEventListener("error", resolve, { once: true });
        })
      )
    );

    const timeout = new Promise((resolve) => {
      setTimeout(resolve, MAX_ASSET_WAIT);
    });

    return Promise.race([imagesReady, timeout]);
  }

  async function revealIncomingPage() {

    // El estado inicial se aplica desde el <head>
    // antes de que aparezca visualmente la página.

    if (
      !document.documentElement.classList.contains(
        "cv-transition-v8-incoming"
      )
    ) {
      return;
    }

    let validIntent = false;

    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      const data = raw ? JSON.parse(raw) : null;

      validIntent = Boolean(
        data &&
        data.target === location.pathname &&
        Date.now() - Number(data.time) >= 0 &&
        Date.now() - Number(data.time) < MAX_INTENT_AGE
      );

    } catch (error) {
      // Continuar sin transición si falla el almacenamiento.
    }

    clearIntent();

    if (!validIntent) {
      document.documentElement.classList.remove(
        "cv-transition-v8-incoming"
      );

      return;
    }

    // Esperar brevemente las imágenes.
    // No se bloquea la página indefinidamente.

    await waitForImagesBriefly();

    await new Promise((resolve) => {
      requestAnimationFrame(() => {
        requestAnimationFrame(resolve);
      });
    });

    document.documentElement.classList.add(
      "cv-transition-v8-reveal"
    );

    const duration = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches
      ? 100
      : IN_DURATION + 100;

    window.setTimeout(() => {
      document.documentElement.classList.remove(
        "cv-transition-v8-incoming",
        "cv-transition-v8-reveal"
      );
    }, duration);
  }

  document.addEventListener("click", (event) => {

    const link = event.target.closest("a");

    if (!transitionAllowed(link)) {
      return;
    }

    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }

    event.preventDefault();

    navigate(link.href);
  });

  // Limpia la transición si el navegador restaura
  // una página mediante el historial.

  window.addEventListener("pageshow", (event) => {

    if (!event.persisted) {
      return;
    }

    isNavigating = false;

    document.documentElement.classList.remove(
      "cv-transition-v8-leaving"
    );

    if (outgoingOverlay) {
      outgoingOverlay.remove();
    }

    outgoingOverlay = null;
  });

  if (document.readyState === "loading") {

    document.addEventListener(
      "DOMContentLoaded",
      revealIncomingPage,
      { once: true }
    );

  } else {

    revealIncomingPage();

  }

})();
