/*
 * César Vidal — page transition v16 (preview)
 * Transición compartida para todas las páginas del sitio.
 * Transiciones adaptadas al fondo de origen y destino en todo el sitio.
 */

(function () {
  "use strict";

  const STORAGE_KEY = "cv-page-transition";
  const PAGE_THEMES = {
    "index.html": "black",
    "bio.html": "white",
    "contact.html": "black",
    "music-projects.html": "white",
    "gonzalez-reeds.html": "white",
    "merch.html": "white",
    "des-visages.html": "des-visages",
    "spam.html": "spam",
    "des-visages-ep.html": "black",
    "nubes.html": "black",
    "flor-de-loto.html": "black",
    "aleas.html": "black",
    "artikulation-band.html": "black"
  };
  const PHOTO_TRANSITIONS = {
    "artikulation-band.html": { theme: "artikulation", image: "img/artikulation-video-1.webp" },
    "des-visages.html": { theme: "des-visages-photo", image: "img/des-visages-transition.webp" }
  };
  const PHOTO_TRANSITION_CLASSES = Object.values(PHOTO_TRANSITIONS).map(
    ({ theme }) => "cv-transition-to-" + theme
  );
  const COLOR_TRANSITION_CLASSES = ["des-visages", "spam", "black", "white", "artikulation", "des-visages-photo"].flatMap(
    (theme) => ["cv-transition-from-" + theme, "cv-transition-to-" + theme]
  );
  const CSS_FALLBACK_CLASS = "cv-transition-css-fallback";

  const SCRIPT_URL = document.currentScript.src;
  const SITE_ROOT = new URL(".", SCRIPT_URL).pathname;
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
    root.classList.remove("cv-transition-incoming", ...COLOR_TRANSITION_CLASSES, CSS_FALLBACK_CLASS);
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
  const photographsReady = new Map();

  function warmPhotoColors(destinationPage) {
    if (photographsReady.has(destinationPage)) return photographsReady.get(destinationPage);
    const image = new Image();
    image.src = new URL(PHOTO_TRANSITIONS[destinationPage].image, SCRIPT_URL).href;
    const photographReady = image.decode().catch(() => {});
    photographsReady.set(destinationPage, photographReady);
    return photographReady;
  }

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
    const incomingBlur = !closing && PHOTO_TRANSITION_CLASSES.some((name) => root.classList.contains(name))
      ? { filter: "blur(" + settings.getPropertyValue("--cv-transition-photo-content-blur").trim() + ") brightness(1)", transform: "scale(1.008)" }
      : blurred;
    const timing = { duration, easing: "cubic-bezier(0.40, 0, 0.22, 1)", fill: "both" };
    const overlayFrames = closing
      ? [{ opacity: 0 }, { opacity: 1 }]
      : [{ opacity: 1 }, { opacity: 0 }];
    const destinationColor = getComputedStyle(root).getPropertyValue("--cv-transition-destination-color").trim();
    if (destinationColor) {
      const sourceColor = getComputedStyle(root).getPropertyValue("--cv-transition-source-color").trim() || "#ffffff";
      overlayFrames[0].backgroundColor = closing ? sourceColor : destinationColor;
      overlayFrames[1].backgroundColor = destinationColor;
    }
    const animations = [
      overlay.animate(overlayFrames, timing),
      content.animate(closing ? [clear, blurred] : [incomingBlur, clear], timing)
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

  function saveIntent(destination, colorTheme) {
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          target: new URL(destination, location.href).pathname,
          time: Date.now(),
          theme: colorTheme
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
    document.removeEventListener("animationend", incomingTransitionEnd);
    incomingTransitionEnd = null;

    document.documentElement.classList.remove(
      "cv-transition-incoming",
      "cv-transition-reveal",
      CSS_FALLBACK_CLASS
    );
    root.style.removeProperty("--cv-transition-css-duration");

    if (incomingAnimation) incomingAnimation.cancel();
    incomingAnimation = null;
    // Keep the opaque destination color until the new page has painted.
    if (!isNavigating) root.classList.remove(...COLOR_TRANSITION_CLASSES);
  }

  async function navigate(destination) {
    if (isNavigating) {
      return;
    }

    const sourcePage = pageName(location.href);
    const destinationPage = pageName(destination);
    const sourceTheme = PAGE_THEMES[sourcePage];
    const colorTheme = PHOTO_TRANSITIONS[destinationPage]?.theme || PAGE_THEMES[destinationPage];

    // Si el navegador bloquea sessionStorage, conservar la navegación normal
    // en lugar de mostrar solamente la mitad de la transición.
    if (!saveIntent(destination, colorTheme)) {
      location.assign(destination);
      return;
    }

    isNavigating = true;
    finishIncomingPage();
    if (PHOTO_TRANSITIONS[destinationPage]) {
      let timeout;
      await Promise.race([
        warmPhotoColors(destinationPage),
        new Promise((resolve) => { timeout = window.setTimeout(resolve, MAX_ASSET_WAIT); })
      ]).finally(() => window.clearTimeout(timeout));
    }
    if (!isNavigating) return;
    root.classList.remove(...COLOR_TRANSITION_CLASSES);
    if (sourceTheme) root.classList.add("cv-transition-from-" + sourceTheme);
    if (colorTheme) root.classList.add("cv-transition-to-" + colorTheme);

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
        if (event.target === incomingOverlay && event.animationName === "cv-transition-overlay-in") {
          finishIncomingPage();
        }
      };
      document.addEventListener("animationend", incomingTransitionEnd);
      root.style.setProperty("--cv-transition-css-duration", duration + "ms");
      root.classList.add(CSS_FALLBACK_CLASS);
    }

    document.documentElement.classList.add(
      "cv-transition-reveal"
    );
  }

  function warmLinkedPhoto(event) {
    const link = event.target instanceof Element ? event.target.closest("a") : null;
    if (transitionAllowed(link) && PHOTO_TRANSITIONS[pageName(link.href)]) warmPhotoColors(pageName(link.href));
  }
  document.addEventListener("pointerover", warmLinkedPhoto, { passive: true });
  document.addEventListener("focusin", warmLinkedPhoto);

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
