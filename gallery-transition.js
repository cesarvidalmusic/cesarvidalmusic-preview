/* Prepare the gallery's actual layout and reuse its shuffle on arrival. */
(function () {
  "use strict";

  const site = new URL('.', document.currentScript.src);
  let cached = null;

  function intersects(a, b) {
    return a.right > b.left && a.left < b.right && a.bottom > b.top && a.top < b.bottom;
  }

  function capture(doc, width, height) {
    const win = doc.defaultView;
    const stage = doc.querySelector('.cv-mp-stage');
    if (!stage) throw new Error('Gallery not ready');
    const clip = stage.getBoundingClientRect();
    const viewport = { left: 0, top: 0, right: width, bottom: height };
    const canvas = doc.createElement('canvas');
    canvas.width = Math.min(800, width);
    canvas.height = Math.round(height * canvas.width / width);
    const context = canvas.getContext('2d');
    context.scale(canvas.width / width, canvas.height / height);
    context.fillStyle = '#fff';
    context.fillRect(0, 0, width, height);

    function clipped(element, draw) {
      context.save();
      if (stage.contains(element)) {
        context.beginPath();
        context.rect(clip.x, clip.y, clip.width, clip.height);
        context.clip();
      }
      draw();
      context.restore();
    }

    for (const image of doc.images) {
      const box = image.getBoundingClientRect();
      if (!image.naturalWidth || !box.width || !box.height || !intersects(box, viewport)) continue;
      if (stage.contains(image) && !intersects(box, clip)) continue;
      clipped(image, () => {
        if (win.getComputedStyle(image).objectFit === 'cover') {
          const scale = Math.max(box.width / image.naturalWidth, box.height / image.naturalHeight);
          const sourceWidth = box.width / scale;
          const sourceHeight = box.height / scale;
          context.drawImage(image, (image.naturalWidth - sourceWidth) / 2,
            (image.naturalHeight - sourceHeight) / 2, sourceWidth, sourceHeight,
            box.x, box.y, box.width, box.height);
        } else {
          context.drawImage(image, box.x, box.y, box.width, box.height);
        }
      });
    }

    // Retain the title and copy's dark areas as well as the cover colors.
    const walker = doc.createTreeWalker(doc.querySelector('[data-page-transition-content]'), NodeFilter.SHOW_TEXT);
    const range = doc.createRange();
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const parent = node.parentElement;
      if (!node.textContent.trim() || parent.closest('script, style, [hidden]')) continue;
      const bounds = parent.getBoundingClientRect();
      if (!bounds.width || !bounds.height || !intersects(bounds, viewport)) continue;
      if (stage.contains(parent) && !intersects(bounds, clip)) continue;
      const style = win.getComputedStyle(parent);
      context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      context.fillStyle = style.color;
      context.letterSpacing = style.letterSpacing === 'normal' ? '0px' : style.letterSpacing;
      const metrics = context.measureText('Hg');
      const ascent = metrics.fontBoundingBoxAscent ?? parseFloat(style.fontSize) * .8;
      const descent = metrics.fontBoundingBoxDescent ?? parseFloat(style.fontSize) * .2;
      clipped(parent, () => {
        for (const match of node.textContent.matchAll(/\S+/g)) {
          range.setStart(node, match.index);
          range.setEnd(node, match.index + match[0].length);
          const box = range.getBoundingClientRect();
          if (box.width && box.height && intersects(box, viewport)) {
            context.fillText(match[0], box.left, box.top + (box.height - ascent - descent) / 2 + ascent);
          }
        }
      });
    }

    const layout = Array.from(stage.querySelectorAll('.cv-mp-cover')).flatMap(image => {
      const box = image.getBoundingClientRect();
      return box.width && intersects(box, clip) && intersects(box, viewport)
        ? [{ project: image.closest('.cv-mp-card').dataset.project,
             x: box.x, y: box.y, width: box.width, height: box.height }] : [];
    });
    return { image: canvas.toDataURL('image/webp', .8), layout };
  }

  function clear() {
    cached?.frame?.remove();
    cached = null;
  }

  function prepare() {
    let view = 'moving';
    try { view = sessionStorage.getItem('cv-mp-view') || view; } catch (_) { /* Default view. */ }
    const width = innerWidth;
    const height = innerHeight;
    const key = `${width}x${height}:${view}`;
    if (cached?.key === key) return cached;
    clear();

    const seed = (Math.random() * 0xffffffff) >>> 0 || 1;
    const frame = document.createElement('iframe');
    frame.setAttribute('aria-hidden', 'true');
    frame.tabIndex = -1;
    frame.dataset.cvGalleryPreview = 'true';
    frame.style.cssText = `position:fixed;inset:0;width:${width}px;height:${height}px;border:0;opacity:0;pointer-events:none;z-index:-1`;
    const url = new URL('music-projects.html', site);
    url.searchParams.set('cv-scene-preview', seed);
    const entry = { key, seed, width, height, frame, image: null, layout: null, ready: null };
    cached = entry;
    let timeout;
    const loaded = new Promise(resolve => {
      frame.addEventListener('load', resolve, { once: true });
      frame.addEventListener('error', resolve, { once: true });
    });
    const render = async () => {
      await loaded;
      if (!frame.isConnected) return;
      const win = frame.contentWindow;
      await Promise.all([win.cvPageReady, win.document.fonts.ready]);
      await Promise.all(Array.from(win.document.images, image => image.decode().catch(() => {})));
      if (!frame.isConnected) return;
      Object.assign(entry, capture(win.document, width, height));
    };
    frame.src = url.href;
    document.body.appendChild(frame);
    entry.ready = Promise.race([
      render(), new Promise(resolve => { timeout = setTimeout(resolve, 3000); })
    ]).catch(() => {}).finally(() => {
      clearTimeout(timeout);
      frame.remove();
      entry.frame = null;
    });
    return entry;
  }

  window.cvGalleryTransition = { prepare, clear };
})();
