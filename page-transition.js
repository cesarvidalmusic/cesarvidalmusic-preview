/*
 * César Vidal — page transition v10
 * Transición compartida para todas las páginas del sitio.
 * Wash oscuro idéntico en ambos sentidos, sin capturas ni iframes.
 */

(function () {
  "use strict";

  const STORAGE_KEY = "cv-page-transition";

  const SITE_ROOT = new URL(".", document.currentScript.src).pathname;
  const ALLOWED_PAGES = new Set([
    "aleas.html",
    "artikulation-band.html",
    "bio.html",
    "contact.html",
    "des-visages-ep.html",
    "des-visages.html",
    "flor-de-loto.html",
    "gonzalez-reeds.html",
    "index.html",
    "merch.html",
    "music-projects.html",
    "nubes.html",
    "spam.html",
  ]);

  const root = document.documentElement;
  const settings = getComputedStyle(root);
  if (settings.getPropertyValue("--cv-transition-ready").trim() !== "1") {
    root.classList.remove("cv-transition-incoming");
    return;
  }

  function readDuration(name, fallback) {
    const value = settings.getPropertyValue(name).trim();
    const number = parseFloat(value);
    if (!Number.isFinite(number) || number < 0) return fallback;
    return value.endsWith("ms") ? number : number * 1000;
  }

  const OUT_DURATION = readDuration("--cv-transition-out-duration", 500);
  const IN_DURATION = readDuration("--cv-transition-in-duration", 650);
  const REDUCED_OUT_DURATION = readDuration("--cv-transition-reduced-out-duration", 80);
  const REDUCED_IN_DURATION = readDuration("--cv-transition-reduced-in-duration", 100);
  const MAX_ASSET_WAIT = 420;

  let isNavigating = false;
  let outgoingOverlay = null;
  let outgoingNavigation = null;
  let incomingCleanup = null;
  let incomingTransitionEnd = null;
  let incomingAnimation = null;
  let outgoingAnimation = null;

  function animatePage(overlay, content, closing, duration) {
    if (typeof overlay.animate !== "function" || !content) return null;
    const previousStyles = [overlay, content].map((element) => {
      const previous = {
        element,
        value: element.style.getPropertyValue("transition"),
        priority: element.style.getPropertyPriority("transition")
      };
      element.style.setProperty("transition", "none");
      return previous;
    });
    const clear = { filter: "blur(0px) brightness(1)", transform: "scale(1)" };
    const blurred = { filter: "blur(7px) brightness(0.90)", transform: "scale(1.008)" };
    const timing = { duration, easing: "cubic-bezier(0.40, 0, 0.22, 1)", fill: "both" };
    const animations = [
      overlay.animate(closing ? [{ opacity: 0 }, { opacity: 1 }] : [{ opacity: 1 }, { opacity: 0 }], timing),
      content.animate(closing ? [clear, blurred] : [blurred, clear], timing)
    ];
    return {
      finished: Promise.all(animations.map((animation) => animation.finished)),
      cancel() {
        animations.forEach((animation) => animation.cancel());
        previousStyles.forEach(({ element, value, priority }) => {
          if (value) element.style.setProperty("transition", value, priority);
          else element.style.removeProperty("transition");
        });
      }
    };
  }

  function pageName(url) {
    const pathname = new URL(url, location.href).pathname;
    if (!pathname.startsWith(SITE_ROOT)) return null;
    return pathname.slice(SITE_ROOT.length) || "index.html";
  }

  function transitionAllowed(link) {
    if (!link || !link.href || link.hasAttribute("download")) {
      return false;
    }

    if (link.target && link.target !== "_self") {
      return false;
    }

    if (link.closest('.cv-nav-soon, [aria-disabled="true"]')) {
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
      "cv-transition-incoming",
      "cv-transition-reveal"
    );

    if (incomingAnimation) incomingAnimation.cancel();
    incomingAnimation = null;
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

    outgoingOverlay = document.createElement("div");
    outgoingOverlay.className = "cv-transition-curtain";
    outgoingOverlay.setAttribute("aria-hidden", "true");

    document.body.appendChild(outgoingOverlay);

    // Asegura que el navegador registre el estado inicial
    // antes de comenzar la animación.

    void outgoingOverlay.offsetWidth;

    document.documentElement.classList.add(
      "cv-transition-leaving"
    );

    const duration = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches
      ? REDUCED_OUT_DURATION
      : OUT_DURATION;

    let completed = false;
    const completeNavigation = () => {
      if (completed || !isNavigating) return;
      completed = true;
      window.clearTimeout(outgoingNavigation);
      location.assign(destination);
    };
    outgoingAnimation = animatePage(
      outgoingOverlay, document.querySelector("[data-page-transition-content]"), true, duration
    );
    if (outgoingAnimation) {
      outgoingOverlay.classList.add("is-covered");
      outgoingAnimation.finished.then(completeNavigation, () => {});
    } else {
      requestAnimationFrame(() => {
        if (outgoingOverlay && isNavigating) outgoingOverlay.classList.add("is-covered");
      });
      outgoingOverlay.addEventListener("transitionend", (event) => {
        if (event.target === outgoingOverlay && event.propertyName === "opacity") completeNavigation();
      });
    }
    outgoingNavigation = window.setTimeout(completeNavigation, duration + 1000);
  }

  function waitForPageAssets() {
    const pending = [];
    const waitFor = (element, event) => new Promise((resolve) => {
      element.addEventListener(event, resolve, { once: true });
      element.addEventListener("error", resolve, { once: true });
    });

    Array.from(document.images)
      .filter((image) => image.loading !== "lazy" && !image.complete)
      .forEach((image) => pending.push(waitFor(image, "load")));
    document.querySelectorAll("video[autoplay]").forEach((video) => {
      if (video.readyState < 2) pending.push(waitFor(video, "loadeddata"));
    });
    if (document.fonts && document.fonts.status === "loading") {
      pending.push(document.fonts.ready);
    }

    if (pending.length === 0) return Promise.resolve();
    let timeout;
    return Promise.race([
      Promise.all(pending),
      new Promise((resolve) => { timeout = setTimeout(resolve, MAX_ASSET_WAIT); })
    ]).finally(() => clearTimeout(timeout));
  }

  async function revealIncomingPage() {

    // El estado inicial se aplica desde el <head>
    // antes de que aparezca visualmente la página.

    if (
      !document.documentElement.classList.contains(
        "cv-transition-incoming"
      )
    ) {
      return;
    }

    // El <head> ya validó y consumió la intención de navegación. No volver a
    // caducarla aquí: una carga lenta del script no debe cancelar el fade-in.

    // Esperar brevemente las imágenes, las fuentes y los fondos de vídeo.
    // No se bloquea la página indefinidamente.

    if (window.cvPageReady) {
      await Promise.race([
        Promise.resolve(window.cvPageReady).catch(() => {}),
        new Promise((resolve) => setTimeout(resolve, 2400))
      ]);
    }
    await waitForPageAssets();

    if (isNavigating || !root.classList.contains("cv-transition-incoming")) return;

    // Registrar el estado cubierto antes de empezar a retirar la cortina,
    // incluso si todos los recursos proceden de la caché.
    const incomingOverlay = document.querySelector(".cv-transition-entering");
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

    if (isNavigating || !root.classList.contains("cv-transition-incoming")) {
      return;
    }

    const duration = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches
      ? REDUCED_IN_DURATION
      : IN_DURATION;

    // Limpiar al terminar realmente la animación. El temporizador es solo
    // una salida de seguridad para pestañas ocultas o transiciones canceladas.
    incomingCleanup = window.setTimeout(finishIncomingPage, duration + 1000);

    // Los fotogramas explícitos evitan que el primer layout omita el fundido.
    incomingAnimation = animatePage(
      incomingOverlay, document.querySelector("[data-page-transition-content]"), false, duration
    );
    if (incomingAnimation) {
      incomingAnimation.finished.then(
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
      "cv-transition-reveal"
    );
  }

  document.addEventListener("click", (event) => {

    const link = event.target instanceof Element ? event.target.closest("a") : null;

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
    window.clearTimeout(outgoingNavigation);
    finishIncomingPage();

    document.documentElement.classList.remove(
      "cv-transition-leaving"
    );

    if (outgoingOverlay) {
      outgoingOverlay.remove();
    }
    if (outgoingAnimation) outgoingAnimation.cancel();
    outgoingAnimation = null;

    outgoingOverlay = null;
  });

  window.addEventListener("pagehide", () => {
    window.clearTimeout(outgoingNavigation);
    if (outgoingAnimation) outgoingAnimation.cancel();
    outgoingAnimation = null;
    finishIncomingPage();
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
