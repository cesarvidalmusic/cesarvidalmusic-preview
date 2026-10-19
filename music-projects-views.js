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

  window.cvInitProjectViews = function ({ stage, tracks, projects, createCard, pause, resume, prepareMotion, followMotion, resize, resetHover, hoverStyle }) {
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
    let hoveredCard = null;
    const hoverStates = new Map();

    function animateHover(card, active) {
      const state = hoverStates.get(card);
      const transform = getComputedStyle(state.visual).transform;
      const opacity = Number(getComputedStyle(state.tint).opacity);
      const scale = new DOMMatrixReadOnly(transform).a;
      const targetScale = active ? 1.05 : 1;
      const targetOpacity = active ? 1 : 0;
      const generation = ++state.generation;
      state.animations.forEach(animation => animation.cancel());
      const finish = () => {
        if (state.generation !== generation) return;
        state.visual.style.transform = `scale(${targetScale})`;
        state.tint.style.opacity = String(targetOpacity);
        state.animations.forEach(animation => animation.cancel());
        state.animations = [];
        if (!active) card.classList.remove("cv-mp-card--leaving");
      };
      if (typeof state.visual.animate !== "function") {
        finish();
        return;
      }
      const distance = Math.max(Math.abs(targetOpacity - opacity), Math.abs(targetScale - scale) / 0.05);
      const timing = { duration: Math.max(60, 350 * distance), easing: "ease", fill: "both" };
      // Explicit animations replace the previous pair together, avoiding the
      // browser's independent CSS-transition reversal and stale completion.
      state.animations = [
        state.visual.animate([{ transform }, { transform: `scale(${targetScale})` }], timing),
        state.tint.animate([{ opacity }, { opacity: targetOpacity }], timing)
      ];
      Promise.all(state.animations.map(animation => animation.finished)).then(finish, () => {});
    }

    function hoverCard(next) {
      if (next === hoveredCard) return;
      const previous = hoveredCard;
      hoveredCard = next;
      if (previous) {
        previous.classList.remove("cv-mp-card--active");
        previous.classList.add("cv-mp-card--leaving");
        hoverStyle.clearText(previous);
        animateHover(previous, false);
      }
      if (!next) return;
      const state = hoverStates.get(next);
      // A visible tint belongs to this card until it has completely faded.
      // Selecting another project never changes this layer's color.
      if (!state.color || Number(getComputedStyle(state.tint).opacity) < 0.001) {
        state.color = hoverStyle.colors[Math.floor(Math.random() * hoverStyle.colors.length)];
        state.tint.style.backgroundColor = state.color;
      }
      next.classList.remove("cv-mp-card--leaving");
      next.classList.add("cv-mp-card--active");
      hoverStyle.setText(next, state.color);
      animateHover(next, true);
    }

    function attachHover(card, visual) {
      const tint = document.createElement("span");
      tint.className = "cv-mp-card-tint";
      tint.setAttribute("aria-hidden", "true");
      visual.prepend(tint);
      hoverStates.set(card, { visual, tint, color: null, animations: [], generation: 0 });
    }

    function clearOverviewHover() {
      hoveredCard = null;
      hoverStates.forEach((state, card) => {
        state.generation++;
        state.animations.forEach(animation => animation.cancel());
        state.tint.remove();
        card.classList.remove("cv-mp-card--active", "cv-mp-card--leaving");
        hoverStyle.clearText(card);
      });
      hoverStates.clear();
    }

    function pointerHover(event) {
      if (switching || event.pointerType === "touch") return;
      const card = event.target.closest(".cv-mp-card");
      hoverCard(card?.parentElement === overview ? card : null);
    }
    overview.addEventListener("pointerover", pointerHover);
    overview.addEventListener("pointermove", pointerHover);
    overview.addEventListener("pointerleave", () => hoverCard(null));

    function snapshotBackground(card, visual) {
      const tint = card.querySelector(".cv-mp-card-tint");
      if (!tint) return getComputedStyle(visual).backgroundColor;
      const css = getComputedStyle(tint);
      const channels = css.backgroundColor.match(/[\d.]+/g).map(Number);
      const opacity = Number(css.opacity) * (channels[3] ?? 1);
      return `rgb(${channels.slice(0, 3).map(channel => Math.round(255 + (channel - 255) * opacity)).join(", ")})`;
    }

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
        const visual = card.querySelector(".cv-mp-card-visual") || card;
        const box = rect(visual);
        const visible = Math.max(0, Math.min(box.y + box.height, stage.clientHeight) - Math.max(box.y, 0));
        const distance = visible ? -visible : Math.max(-box.y - box.height, box.y - stage.clientHeight, 0);
        const previous = result.get(card.dataset.project);
        const priority = Boolean(preferred?.has(card));
        if (previous && (previous.priority > priority ||
          (previous.priority === priority && previous.distance <= distance))) return;
        const blocks = {};
        const textElement = card.querySelector(".cv-mp-card-text");
        const textBox = rect(textElement);
        const textStyle = getComputedStyle(textElement);
        const text = { left: textBox.x - box.x, top: textBox.y - box.y,
          scaleX: textBox.width / parseFloat(textStyle.width),
          scaleY: textBox.height / parseFloat(textStyle.height) };
        Object.entries(PARTS).forEach(([name, selector]) => {
          const element = card.querySelector(selector);
          if (!element) return;
          const part = rect(element);
          const css = getComputedStyle(element);
          blocks[name] = { left: part.x - box.x, top: part.y - box.y, width: part.width,
            height: part.height, fontSize: css.fontSize, lineHeight: css.lineHeight,
            letterSpacing: css.letterSpacing, color: css.color,
            layoutWidth: css.width, layoutHeight: css.height, lineClamp: css.webkitLineClamp };
        });
        result.set(card.dataset.project, { element: card, box, text, blocks, distance, priority,
          column: tracks.indexOf(card.parentElement),
          background: snapshotBackground(card, visual) });
      });
      return result;
    }

    function applyView(next, before) {
      stage.scrollTop = 0;
      if (next === "overview") {
        savedTracks = tracks.map(track => Array.from(track.children));
        overview.replaceChildren(...projects.map(project => before.get(project.title)?.element || createCard(project)));
        Array.from(overview.children).forEach(card => {
          // The link stays fixed in the grid. Its visual content can grow
          // without moving the pointer's target or disturbing its neighbors.
          const visual = document.createElement("span");
          visual.className = "cv-mp-card-visual";
          visual.append(...card.childNodes);
          card.appendChild(visual);
          attachHover(card, visual);
        });
        stage.classList.add("cv-mp-stage--overview");
      } else {
        clearOverviewHover();
        stage.classList.remove("cv-mp-stage--overview");
        Array.from(overview.children).forEach(card => {
          const visual = card.querySelector(".cv-mp-card-visual");
          if (visual) card.replaceChildren(...visual.childNodes);
        });
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

    function photoFrame(part) {
      return { left: part.left + "px", top: part.top + "px",
        width: part.width + "px", height: part.height + "px" };
    }

    function textFrame(snapshot) {
      const text = snapshot.text;
      return { transform: `translate3d(${text.left}px, ${text.top}px, 0) scale(${text.scaleX}, ${text.scaleY})` };
    }

    function fixedText(template, snapshot, layout) {
      const layer = document.createElement("span");
      layer.className = "cv-mp-morph-text";
      layer.dataset.layout = layout;
      Object.entries(PARTS).forEach(([name, selector]) => {
        if (name === "photo") return;
        const original = template.querySelector(selector);
        if (!original) return;
        const element = original.cloneNode(true);
        const part = snapshot.blocks[name] || snapshot.blocks.more || snapshot.blocks.soon;
        // Freeze the original typographic box, including its line clamp.
        // Only the containing layer moves; words never rewrap in flight.
        Object.assign(element.style, {
          left: (part.left - snapshot.text.left) / snapshot.text.scaleX + "px",
          top: (part.top - snapshot.text.top) / snapshot.text.scaleY + "px",
          // Computed sizes are rounded strings. Avoid losing a layout pixel
          // fraction when the browser parses those dimensions again.
          width: parseFloat(part.layoutWidth) + 0.0001 + "px",
          height: parseFloat(part.layoutHeight) + 0.0001 + "px",
          fontSize: part.fontSize, lineHeight: part.lineHeight,
          letterSpacing: part.letterSpacing, color: part.color
        });
        if (name === "preview") {
          element.style.display = "-webkit-box";
          element.style.webkitBoxOrient = "vertical";
          element.style.webkitLineClamp = part.lineClamp;
        }
        layer.appendChild(element);
      });
      return layer;
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
      const fadeTiming = { delay: duration * 0.15, duration: Math.min(160, duration * 0.4) / 2,
        easing: "ease-in-out", fill: "both" };
      const firstBefore = before.values().next().value;
      const firstAfter = after.values().next().value;
      const carriers = [];
      projects.forEach((project, index) => {
        const from = before.get(project.title) || outside(firstBefore, index);
        const to = after.get(project.title) || outside(firstAfter, index);
        const clone = (to.element || from.element).cloneNode(true);
        clone.querySelectorAll(".cv-mp-card-tint").forEach(tint => tint.remove());
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
        const photo = clone.querySelector(PARTS.photo);
        animations.push(photo.animate([photoFrame(from.blocks.photo), photoFrame(to.blocks.photo)], timing));
        const template = clone.querySelector(".cv-mp-card-text");
        template.remove();
        [from, to].forEach((snapshot, side) => {
          const text = fixedText(template, snapshot, side ? "to" : "from");
          clone.appendChild(text);
          animations.push(text.animate([textFrame(from), textFrame(to)], timing));
          // Fade through the two fixed compositions without overlapping words.
          animations.push(text.animate([{ opacity: side ? 0 : 1 }, { opacity: side ? 1 : 0 }],
            { ...fadeTiming, delay: fadeTiming.delay + side * fadeTiming.duration }));
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
