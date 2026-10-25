/* Keep the home wordmark aligned with the menu's first and last items. */
(function () {
  "use strict";

  const menu = document.querySelector('.cv-home-main-nav ul');
  const content = document.querySelector('.cv-hero-content');
  const title = document.querySelector('.cv-title-berlin--home');
  if (!menu || !content || !title) return;

  function fitTitle() {
    const first = menu.firstElementChild.getBoundingClientRect();
    const last = menu.lastElementChild.getBoundingClientRect();
    const box = content.getBoundingClientRect();
    const scale = box.width / content.offsetWidth;
    const style = getComputedStyle(content);
    const innerLeft = box.left + parseFloat(style.paddingLeft) * scale;
    const innerRight = box.right - parseFloat(style.paddingRight) * scale;
    // Compact menus can extend beyond the viewport. Keep the title readable.
    const left = Math.max(innerLeft, first.left);
    const right = Math.min(innerRight, last.right);
    title.style.setProperty('--cv-home-title-width', Math.max(0, right - left) / scale + 'px');
    title.style.setProperty('--cv-home-title-right', Math.max(0, innerRight - right) / scale + 'px');
  }

  fitTitle();
  document.fonts.ready.then(fitTitle);
  window.addEventListener('resize', fitTitle, { passive: true });
  if (typeof ResizeObserver === 'function') new ResizeObserver(fitTitle).observe(menu);
})();
