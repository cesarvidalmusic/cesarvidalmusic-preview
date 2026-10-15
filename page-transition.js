/*
 * César Vidal — page transition v9
 * Prueba limitada a Bio <-> Gonzalez Reeds.
 * Wash oscuro idéntico en ambos sentidos, sin capturas ni iframes.
 */

(function () {
  "use strict";

  const STORAGE_KEY = "cv-soft-page-transition-v9";

  const ALLOWED_PAGES = new Set([
    "bio.html",
    "gonzalez-reeds.html"
  ]);

  const OUT_DURATION = 500;
  const IN_DURATION = 650;
  const MAX_ASSET_WAIT = 420;

  let isNavigating = false;
  let outgoingOverlay = null;
  let incomingCleanup = null;
  let incomingTransitionEnd = null;
  let incomingAnimations = [];
  let incomingStyleOverrides = [];

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
    if (document.getElementById("cv-transition-v9-style")) {
      return;
    }

    const style = document.createElement("style");

    style.id = "cv-transition-v9-style";

    style.textContent = `
      .cv-transition-v9-curtain {
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

      .cv-transition-v9-curtain.is-covered {
        opacity: 1;
        pointer-events: auto;
      }

      html.cv-transition-v9-leaving .cv-page {
        filter: blur(7px) brightness(0.90);
        transform: scale(1.008);

        transition:
          filter ${OUT_DURATION}ms cubic-bezier(0.40, 0, 0.22, 1),
          transform ${OUT_DURATION}ms cubic-bezier(0.40, 0, 0.22, 1);
      }

      @media (prefers-reduced-motion: reduce) {
        .cv-transition-v9-curtain,
        html.cv-transition-v9-leaving .cv-page {
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

  function finishIncomingPage() {
    window.clearTimeout(incomingCleanup);
    incomingCleanup = null;
    document.removeEventListener("transitionend", incomingTransitionEnd);
    incomingTransitionEnd = null;

    document.documentElement.classList.remove(
      "cv-transition-v9-incoming",
      "cv-transition-v9-reveal"
    );

    incomingAnimations.forEach((animation) => animation.cancel());
    incomingAnimations = [];
    incomingStyleOverrides.forEach(({ element, value, priority }) => {
      if (value) {
        element.style.setProperty("transition", value, priority);
      } else {
        element.style.removeProperty("transition");
      }
    });
    incomingStyleOverrides = [];
  }

  function navigate(destination) {
    if (isNavigating) {
      return;
    }

    // Si el navegador bloquea sessionStorage, conservar la navegación normal
    // en lugar de mostrar solamente la mitad de la transición.
    if (!saveIntent(destination)) {
      location.assign(destination);
      return;
    }

    isNavigating = true;
    finishIncomingPage();

    addOutgoingStyles();

    outgoingOverlay = document.createElement("div");
    outgoingOverlay.className = "cv-transition-v9-curtain";
    outgoingOverlay.setAttribute("aria-hidden", "true");

    document.body.appendChild(outgoingOverlay);

    // Asegura que el navegador registre el estado inicial
    // antes de comenzar la animación.

    void outgoingOverlay.offsetWidth;

    document.documentElement.classList.add(
      "cv-transition-v9-leaving"
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
        "cv-transition-v9-incoming"
      )
    ) {
      return;
    }

    // El <head> ya validó y consumió la intención de navegación. No volver a
    // caducarla aquí: una carga lenta del script no debe cancelar el fade-in.

    // Esperar brevemente las imágenes.
    // No se bloquea la página indefinidamente.

    await waitForImagesBriefly();

    // Registrar el estado cubierto antes de empezar a retirar la cortina,
    // incluso si todos los recursos proceden de la caché.
    const incomingOverlay = document.querySelector(".cv-transition-v9-entering");
    if (!incomingOverlay) {
      finishIncomingPage();
      return;
    }

    void incomingOverlay.offsetWidth;
    void getComputedStyle(incomingOverlay).opacity;

    await new Promise((resolve) => {
      requestAnimationFrame(() => {
        requestAnimationFrame(resolve);
      });
    });

    if (isNavigating) {
      return;
    }

    const duration = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches
      ? 100
      : IN_DURATION;

    // Limpiar al terminar realmente la animación. El temporizador es solo
    // una salida de seguridad para pestañas ocultas o transiciones canceladas.
    incomingCleanup = window.setTimeout(finishIncomingPage, duration + 1000);

    const incomingPage = document.querySelector(".cv-page");
    if (typeof incomingOverlay.animate === "function" && incomingPage) {
      // Dar al navegador un inicio y un final explícitos. Una transición CSS
      // puede omitirse durante el primer layout, sobre todo en móviles.
      [incomingOverlay, incomingPage].forEach((element) => {
        incomingStyleOverrides.push({
          element,
          value: element.style.getPropertyValue("transition"),
          priority: element.style.getPropertyPriority("transition")
        });
        element.style.setProperty("transition", "none");
      });

      const timing = {
        duration,
        easing: "cubic-bezier(0.40, 0, 0.22, 1)",
        fill: "both"
      };

      incomingAnimations = [
        incomingOverlay.animate([{ opacity: 1 }, { opacity: 0 }], timing),
        incomingPage.animate([
          { filter: "blur(7px) brightness(0.90)", transform: "scale(1.008)" },
          { filter: "blur(0px) brightness(1)", transform: "scale(1)" }
        ], timing)
      ];

      Promise.all(incomingAnimations.map((animation) => animation.finished)).then(
        finishIncomingPage,
        () => { /* La navegación puede cancelar una entrada en curso. */ }
      );
    } else {
      incomingTransitionEnd = (event) => {
        if (event.target === incomingOverlay && event.propertyName === "opacity") {
          finishIncomingPage();
        }
      };
      document.addEventListener("transitionend", incomingTransitionEnd);
    }

    document.documentElement.classList.add(
      "cv-transition-v9-reveal"
    );
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
    finishIncomingPage();

    document.documentElement.classList.remove(
      "cv-transition-v9-leaving"
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
