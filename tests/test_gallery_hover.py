"""Exercise hover handoffs at card edges, including Retina and zoom-like layouts."""
import argparse
import asyncio
import functools
import json
from pathlib import Path
import threading

from playwright.async_api import async_playwright
from test_page_transitions import ROOT, QuietHandler, TestServer
from test_gallery_views import loaded, toggle


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
            const previous=cards[first].querySelector('.cv-mp-card-visual');
            samples.push({hovered:cards.flatMap((card,i)=>card.matches(':hover')?[i]:[]),
              color:getComputedStyle(previous).backgroundColor,
              previousLayer:Number(getComputedStyle(cards[first]).zIndex)});
          }
          return samples;
        }""", first)
        assert all(sample['hovered'] == [second] for sample in samples), (first, second, samples)
        colors = [[int(channel) for channel in sample['color'][4:-1].split(',')] for sample in samples]
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
    assert await cards.locator('.cv-mp-card-visual').evaluate_all(
        "els=>els.every(el=>getComputedStyle(el).backgroundColor==='rgb(255, 255, 255)')")
    if out:
        await page.screenshot(path=str(out / f'overview-{width}-{height}-{scale}.png'))

    # Pointer events pass through the growing visual to the real project link.
    photo = await cards.nth(0).locator('img').bounding_box()
    await page.mouse.click(photo['x'] + photo['width'] / 2, photo['y'] + photo['height'] / 2)
    await page.wait_for_url('**/des-visages.html', wait_until='domcontentloaded')
    assert not errors, errors
    await context.close()
    return {'viewport': [width, height], 'pixel_ratio': scale, 'edge_handoffs': 6,
            'rapid_handoffs': 14, 'fixed_targets': True, 'smooth_exit': True, 'photo_link': True}


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
