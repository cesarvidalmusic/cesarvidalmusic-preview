/* Reorganize the existing gallery cards; remember the view for this tab. */
(function () {
  "use strict";

  const STORAGE_KEY = "cv-mp-view";
  const DURATION = 1200;
  const EASING = "cubic-bezier(0.16, 1, 0.3, 1)";
  const PARTS = {
    photo: ".cv-mp-cover",
    title: ".cv-mp-card-title",
    preview: ".cv-mp-card-preview",
    more: ".cv-mp-card-more",
    soon: ".cv-mp-coming-soon"
  };

  window.cvInitProjectViews = function ({ stage, tracks, projects, createCard, pause, resume, prepareMotion, followMotion, resize, resetHover }) {
    if (getComputedStyle(stage).getPropertyValue("--cv-mp-views-ready").trim() !== "1") return;
    const hero = document.querySelector(".cv-page-hero");
    const title = hero.querySelector("h1");
    const home = document.querySelector('nav a[href="index.html"]');
    const controls = hero.querySelector(".cv-mp-view-controls");
    const buttons = Array.from(controls.querySelectorAll("button[data-view]"));
    const overview = document.createElement("div");
    overview.className = "cv-mp-overview";
    stage.appendChild(overview);

    let view = "moving";
    let savedTracks = null;
    let switching = false;
    let queuedView = null;
    let morphLayer = null;
    let animations = [];
    let stopFollowing = null;
    let releaseMotion = null;
    let generation = 0;

    function readView() {
      try {
        return sessionStorage.getItem(STORAGE_KEY) === "overview" ? "overview" : "moving";
      } catch (error) {
        return "moving";
      }
    }

    function rememberView(next) {
      try { sessionStorage.setItem(STORAGE_KEY, next); } catch (error) {
        // Both views remain usable if the browser blocks storage.
      }
    }

    function updateButtons() {
      stage.dataset.view = view;
      buttons.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
    }

    function positionControls() {
      title.style.removeProperty("font-size");
      const heroBox = hero.getBoundingClientRect();
      const titleBox = title.getBoundingClientRect();
      const homeBox = home.getBoundingClientRect();
      const scaleX = heroBox.width / hero.offsetWidth;
      const scaleY = heroBox.height / hero.offsetHeight;
      const titleLeft = (titleBox.left - heroBox.left) / scaleX;
      const homeLeft = (homeBox.left - heroBox.left) / scaleX;
      const style = getComputedStyle(hero);
      const right = hero.clientWidth - parseFloat(style.paddingRight);
      const range = document.createRange();
      range.selectNodeContents(title);
      const text = range.getBoundingClientRect();
      const groupWidth = controls.offsetWidth;
      // On compact menus Home can be off-screen; keep both controls reachable.
      const left = homeLeft > titleLeft + 120
        ? Math.min(homeLeft, right - groupWidth)
        : right - groupWidth;
      const available = Math.max(120, left - titleLeft - 16);
      if (text.width / scaleX > available) {
        title.style.fontSize = (parseFloat(getComputedStyle(title).fontSize) * available / (text.width / scaleX)) + "px";
      }
      controls.style.left = left + "px";
      controls.style.top = ((titleBox.top - heroBox.top) / scaleY + (titleBox.height / scaleY - 28) / 2) + "px";
    }

    function snapshots(preferred) {
      const frame = stage.getBoundingClientRect();
      const scaleX = frame.width / stage.offsetWidth;
      const scaleY = frame.height / stage.offsetHeight;
      const rect = element => {
        const box = element.getBoundingClientRect();
        return { x: (box.left - frame.left) / scaleX, y: (box.top - frame.top) / scaleY,
          width: box.width / scaleX, height: box.height / scaleY };
      };
      const cards = view === "overview" ? Array.from(overview.children) : tracks.flatMap(track => Array.from(track.children));
      const result = new Map();
      cards.forEach(card => {
        const box = rect(card);
        const visible = Math.max(0, Math.min(box.y + box.height, stage.clientHeight) - Math.max(box.y, 0));
        const distance = visible ? -visible : Math.max(-box.y - box.height, box.y - stage.clientHeight, 0);
        const previous = result.get(card.dataset.project);
        const priority = Boolean(preferred?.has(card));
        if (previous && (previous.priority > priority ||
          (previous.priority === priority && previous.distance <= distance))) return;
        const blocks = {};
        Object.entries(PARTS).forEach(([name, selector]) => {
          const element = card.querySelector(selector);
          if (!element) return;
          const part = rect(element);
          const css = getComputedStyle(element);
          blocks[name] = { left: part.x - box.x, top: part.y - box.y, width: part.width,
            height: part.height, fontSize: css.fontSize, lineHeight: css.lineHeight,
            letterSpacing: css.letterSpacing, color: css.color };
        });
        result.set(card.dataset.project, { element: card, box, blocks, distance, priority,
          column: tracks.indexOf(card.parentElement),
          background: getComputedStyle(card).backgroundColor });
      });
      return result;
    }

    function applyView(next, before) {
      stage.scrollTop = 0;
      if (next === "overview") {
        savedTracks = tracks.map(track => Array.from(track.children));
        overview.replaceChildren(...projects.map(project => before.get(project.title)?.element || createCard(project)));
        stage.classList.add("cv-mp-stage--overview");
      } else {
        stage.classList.remove("cv-mp-stage--overview");
        tracks.forEach((track, index) => track.replaceChildren(...savedTracks[index]));
        overview.replaceChildren();
        savedTracks = null;
        resize();
      }
      view = next;
      updateButtons();
    }

    function outside(reference, index) {
      return { ...reference, element: null, column: -1, box: { ...reference.box,
        y: index % 2 ? -reference.box.height - 4 : stage.clientHeight + 4 } };
    }

    function cardFrame(snapshot, clampBuffer = true) {
      const box = snapshot.box;
      // Keep unseen buffers just outside the crop instead of flying from many screens away.
      const y = clampBuffer ? Math.max(-box.height - 4, Math.min(stage.clientHeight + 4, box.y)) : box.y;
      return { transform: `translate3d(${box.x}px, ${y}px, 0)`,
        width: box.width + "px", height: box.height + "px", backgroundColor: snapshot.background };
    }

    function partFrame(part, photo) {
      const frame = { left: part.left + "px", top: part.top + "px",
        width: part.width + "px", height: part.height + "px" };
      if (!photo) Object.assign(frame, { fontSize: part.fontSize, lineHeight: part.lineHeight,
        letterSpacing: part.letterSpacing, color: part.color });
      return frame;
    }

    function finishSwitch(flushQueue = true) {
      generation++;
      if (stopFollowing) stopFollowing();
      stopFollowing = null;
      if (releaseMotion) releaseMotion();
      releaseMotion = null;
      animations.forEach(animation => animation.cancel());
      animations = [];
      if (morphLayer) morphLayer.remove();
      morphLayer = null;
      switching = false;
      stage.classList.remove("cv-mp-is-switching");
      stage.removeAttribute("aria-busy");
      if (view === "moving") resume();
      const next = queuedView;
      queuedView = null;
      if (flushQueue && next && next !== view) setView(next);
    }

    function morph(before) {
      switching = true;
      stage.classList.add("cv-mp-is-switching");
      stage.setAttribute("aria-busy", "true");
      morphLayer = document.createElement("div");
      morphLayer.className = "cv-mp-morph-layer";
      morphLayer.setAttribute("aria-hidden", "true");
      stage.appendChild(morphLayer);
      const duration = matchMedia("(prefers-reduced-motion: reduce)").matches ? 80 : DURATION;
      const preparation = view === "moving" ? prepareMotion(duration / 1000) : null;
      releaseMotion = preparation?.release || null;
      const after = snapshots(preparation?.preferred);
      const timing = { duration, easing: EASING, fill: "both" };
      const firstBefore = before.values().next().value;
      const firstAfter = after.values().next().value;
      const carriers = [];
      projects.forEach((project, index) => {
        const from = before.get(project.title) || outside(firstBefore, index);
        const to = after.get(project.title) || outside(firstAfter, index);
        const clone = (to.element || from.element).cloneNode(true);
        clone.querySelectorAll("img").forEach(image => { image.decoding = "sync"; });
        clone.classList.add("cv-mp-morph-card");
        clone.removeAttribute("href");
        clone.tabIndex = -1;
        const carrier = document.createElement("div");
        carrier.className = "cv-mp-morph-motion";
        carrier.appendChild(clone);
        morphLayer.appendChild(carrier);
        carriers.push({ element: carrier, column: to.column });
        animations.push(clone.animate([cardFrame(from), cardFrame(to, view !== "moving")], timing));
        Object.entries(PARTS).forEach(([name, selector]) => {
          const element = clone.querySelector(selector);
          if (!element) return;
          const start = from.blocks[name] || from.blocks.more || from.blocks.soon;
          const end = to.blocks[name] || to.blocks.more || to.blocks.soon;
          animations.push(element.animate([partFrame(start, name === "photo"), partFrame(end, name === "photo")], timing));
        });
      });
      if (view === "moving") {
        // Follow the actual column travel on a separate wrapper. Reordering
        // eases to a moving destination, so revealing the originals never
        // stops their vertical motion or adds a second positional jump.
        const travel = tracks.map(() => 0);
        stopFollowing = followMotion(movement => {
          movement.forEach((distance, column) => { travel[column] += distance; });
          carriers.forEach(carrier => {
            if (carrier.column < 0) return;
            carrier.element.style.transform = `translate3d(0, ${travel[carrier.column]}px, 0)`;
          });
        });
        resume();
      }
      const current = ++generation;
      Promise.all(animations.map(animation => animation.finished)).then(() => {
        if (generation === current) finishSwitch();
      }, () => { /* Page departure or resize can finish the reordering early. */ });
    }

    function setView(next, animate = true) {
      if (next !== "moving" && next !== "overview") return;
      rememberView(next);
      if (switching) {
        queuedView = next;
        return;
      }
      if (view === next) {
        updateButtons();
        return;
      }
      pause();
      tracks.forEach(track => Array.from(track.children).forEach(resetHover));
      Array.from(overview.children).forEach(resetHover);
      const before = snapshots();
      applyView(next, before);
      if (animate && typeof stage.animate === "function") morph(before);
      else if (view === "moving") resume();
    }

    buttons.forEach(button => button.addEventListener("click", () => setView(button.dataset.view)));
    window.addEventListener("resize", () => {
      if (switching) finishSwitch();
      positionControls();
    });
    window.addEventListener("pagehide", () => {
      finishSwitch(false);
      pause();
    });
    window.addEventListener("pageshow", event => {
      if (!event.persisted) return;
      setView(readView(), false);
      if (view === "moving") resume();
    });
    controls.hidden = false;
    controls.style.visibility = "hidden";
    const ready = document.fonts ? document.fonts.ready : Promise.resolve();
    ready.then(() => {
      positionControls();
      controls.style.removeProperty("visibility");
    });
    updateButtons();
    setView(readView(), false);
  };
})();
