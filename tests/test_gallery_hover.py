"""Exercise hover handoffs at card edges, including Retina and zoom-like layouts."""
import argparse
import asyncio
import functools
import io
import json
from pathlib import Path
import threading

from playwright.async_api import async_playwright
from PIL import Image
from test_page_transitions import ROOT, QuietHandler, TestServer
from test_gallery_views import loaded, toggle


async def painted_colors(page, scale):
    # Freeze compositor animations so computed colors and PNG pixels refer to
    # exactly the same frame. This catches painted flashes that style-only
    # assertions cannot see.
    samples = await page.evaluate("""async () => {
      const overview=document.querySelector('.cv-mp-overview');
      window.paintAnimations=overview.getAnimations({subtree:true});
      paintAnimations.forEach(a=>a.pause());
      await Promise.all(paintAnimations.map(a=>a.ready));
      // Chromium can retain the compositor's next frame after pause resolves.
      // Seek after that acknowledgement to synchronize paint and computed style.
      paintAnimations.forEach(a=>{a.currentTime+=.001});
      await new Promise(requestAnimationFrame);
      await new Promise(requestAnimationFrame);
      return Array.from(overview.children,(card,i)=>{
        const box=card.getBoundingClientRect();
        const css=getComputedStyle(card.querySelector('.cv-mp-card-tint'));
        const channels=css.backgroundColor.match(/[\\d.]+/g).map(Number);
        const alpha=Number(css.opacity)*(channels[3]??1);
        return {project:card.dataset.project,x:i%2?box.right-3:box.left+3,y:box.y+3,
          expected:channels.slice(0,3).map(c=>Math.round(255+(c-255)*alpha)),
          tone:css.backgroundColor,alpha:Number(css.opacity),
          active:card.classList.contains('cv-mp-card--active'),layer:Number(getComputedStyle(card).zIndex)};
      });
    }""")
    screenshot = Image.open(io.BytesIO(await page.screenshot())).convert('RGB')
    for sample in samples:
        pixel = screenshot.getpixel((round(sample['x'] * scale), round(sample['y'] * scale)))
        assert all(abs(actual - expected) <= 2 for actual, expected in zip(pixel, sample['expected'])), (sample, pixel)
    assert sum(sample['active'] for sample in samples) <= 1, samples
    await page.evaluate("paintAnimations.forEach(a=>{if(a.playState==='paused')a.play()})")
    return samples


async def paint_handoffs(page, cards, boxes, scale):
    await page.mouse.move(10, 10)
    await page.wait_for_timeout(450)
    await page.evaluate('Math.random=()=>0')
    await cards.nth(0).hover()
    await page.wait_for_timeout(400)
    await painted_colors(page, scale)
    await page.evaluate('Math.random=()=>.99')
    await cards.nth(2).hover()
    await page.wait_for_timeout(45)
    await page.evaluate("""() => {
      window.heldAnimations=document.querySelector('.cv-mp-overview').getAnimations({subtree:true});
      heldAnimations.forEach(a=>a.pause());
    }""")
    await page.wait_for_timeout(450)
    held = await cards.nth(0).evaluate("card=>({layer:getComputedStyle(card).zIndex,alpha:Number(getComputedStyle(card.querySelector('.cv-mp-card-tint')).opacity)})")
    assert held['layer'] == '2' and held['alpha'] > 0, held
    await page.evaluate("heldAnimations.forEach(a=>{if(a.playState==='paused')a.play()})")
    previous = await painted_colors(page, scale)
    assert previous[0]['tone'] == 'rgb(36, 32, 23)', previous
    path = [4, 6, 4, 2, 0, 1, 3, 5, 7, 5, 3, 1]
    for index in path:
        box = boxes[index]
        await page.mouse.move(box['x'] + 50, box['y'] + box['height'] / 2)
        await page.wait_for_timeout(35)
        current = await painted_colors(page, scale)
        assert current[index]['active'], (index, current)
        for peer, (before, after) in enumerate(zip(previous, current)):
            if peer != index:
                assert before['tone'] == after['tone'], (index, peer, before, after)
        previous = current
    await page.mouse.move(10, 10)
    await page.wait_for_timeout(450)
    final = await painted_colors(page, scale)
    assert all(sample['alpha'] == 0 and sample['layer'] == 1 for sample in final), final
    await toggle(page, 'moving')
    assert await page.locator('.cv-mp-card-tint').count() == 0
    await toggle(page, 'overview')
    assert await page.locator('.cv-mp-card-tint').count() == 8
    return {'painted_pixel_checks': 8 * (len(path) + 3), 'paused_exit_keeps_layer': True,
            'peer_colors_unchanged': True, 'no_tint_leaks_between_views': True}


async def check(browser, base, width, height, scale, out):
    context = await browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=scale)
    page = await context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    response = await page.goto(base + 'music-projects.html', wait_until='domcontentloaded')
    assert response.status == 200
    await loaded(page)
    await toggle(page, 'overview')
    boxes = await page.locator('.cv-mp-overview .cv-mp-card').evaluate_all(
        'cards=>cards.map(card=>card.getBoundingClientRect().toJSON())')
    cards = page.locator('.cv-mp-overview .cv-mp-card')

    for first, second in [(0, 2), (2, 0), (2, 4), (4, 2), (1, 3), (3, 1)]:
        box = boxes[first]
        await page.mouse.move(box['x'] + 50, box['y'] + box['height'] / 2)
        await page.wait_for_timeout(400)
        grown = await cards.nth(first).locator('.cv-mp-card-visual').bounding_box()
        fixed = await cards.nth(first).bounding_box()
        assert all(abs(fixed[key] - box[key]) < 0.1 for key in ('x', 'y', 'width', 'height')), (fixed, box)
        assert abs(grown['width'] / box['width'] - 1.05) < 0.002, (grown, box)

        # Move just inside the neighboring link, while the previous card's
        # enlarged visual still covers that edge. It must not steal the hover.
        target = boxes[second]
        y = target['y'] + (1 if second > first else target['height'] - 1)
        await page.mouse.move(target['x'] + 50, y)
        samples = await page.evaluate("""async first => {
          const cards=Array.from(document.querySelector('.cv-mp-overview').children);
          const samples=[];
          for(let frame=0;frame<25;frame++) {
            await new Promise(requestAnimationFrame);
            const tint=cards[first].querySelector('.cv-mp-card-tint');
            const css=getComputedStyle(tint);
            const rgb=css.backgroundColor.match(/[\\d.]+/g).slice(0,3).map(Number);
            samples.push({hovered:cards.flatMap((card,i)=>card.matches(':hover')?[i]:[]),
              color:rgb.map(channel=>Math.round(255+(channel-255)*Number(css.opacity))),
              previousLayer:Number(getComputedStyle(cards[first]).zIndex)});
          }
          return samples;
        }""", first)
        assert all(sample['hovered'] == [second] for sample in samples), (first, second, samples)
        colors = [sample['color'] for sample in samples]
        assert all(all(b >= a for a, b in zip(old, new)) for old, new in zip(colors, colors[1:])), samples
        assert colors[-1] == [255, 255, 255], samples
        assert samples[0]['previousLayer'] == 2, samples
        assert samples[-1]['previousLayer'] == 1, samples

    # Fast backtracking must select only the intended project on every frame.
    for index in [0, 2, 4, 6, 4, 2, 0, 1, 3, 5, 7, 5, 3, 1]:
        target = boxes[index]
        await page.mouse.move(target['x'] + 50, target['y'] + target['height'] / 2)
        hovered = await cards.evaluate_all('cards=>cards.flatMap((card,i)=>card.matches(":hover")?[i]:[])')
        assert hovered == [index], (index, hovered)
        await page.wait_for_timeout(35)
    await page.mouse.move(10, 10)
    await page.wait_for_timeout(450)
    assert await cards.locator('.cv-mp-card-tint').evaluate_all(
        "els=>els.every(el=>getComputedStyle(el).opacity==='0')")
    paint = await paint_handoffs(page, cards, boxes, scale)
    if out:
        await page.screenshot(path=str(out / f'overview-{width}-{height}-{scale}.png'))

    # Pointer events pass through the growing visual to the real project link.
    photo = await cards.nth(0).locator('img').bounding_box()
    await page.mouse.click(photo['x'] + photo['width'] / 2, photo['y'] + photo['height'] / 2)
    await page.wait_for_url('**/des-visages.html', wait_until='domcontentloaded')
    assert not errors, errors
    await context.close()
    return {'viewport': [width, height], 'pixel_ratio': scale, 'edge_handoffs': 6,
            'rapid_handoffs': 14, 'fixed_targets': True, 'smooth_exit': True, 'photo_link': True, **paint}


async def run(base, out):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        results = []
        for width, height, scale in [(1512, 770, 1), (1512, 982, 2), (1440, 1100, 2), (1512, 1800, 1)]:
            results.append(await check(browser, base, width, height, scale, out))
            print(json.dumps(results[-1]), flush=True)
        await browser.close()
    return {'status': 'passed', 'hover': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path)
    args = parser.parse_args()
    out = args.results.parent if args.results else None
    server = TestServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = asyncio.run(run(f'http://127.0.0.1:{server.server_port}/', out))
        if args.results:
            args.results.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)
    finally:
        server.shutdown()
        server.server_close()
