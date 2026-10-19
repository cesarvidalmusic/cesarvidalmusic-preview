"""Check gallery reordering, readable layouts, motion and tab-session persistence."""
import argparse
import asyncio
import functools
import json
from pathlib import Path
import subprocess
import threading

from playwright.async_api import async_playwright
from test_page_transitions import ROOT, GALLERY_COLORS, QuietHandler, TestServer, new_page, direct, check_entry
from test_gallery_motion import CLOCK, snapshot


async def loaded(page):
    await page.evaluate('window.cvPageReady')
    await page.evaluate('document.fonts.ready')
    await page.wait_for_function("getComputedStyle(document.querySelector('.cv-mp-view-controls')).visibility === 'visible'")
    await page.evaluate("Promise.all(Array.from(document.querySelectorAll('.cv-mp-cover'), image => image.decode()))")


async def settled(page, mode):
    await page.wait_for_function("mode => document.querySelector('#stage').dataset.view === mode && !document.querySelector('.cv-mp-morph-layer')", arg=mode)
    assert await page.get_by_role('button', name='All projects', exact=True).get_attribute('aria-pressed') == str(mode == 'overview').lower()
    assert not await page.locator('#stage').get_attribute('aria-busy')


async def toggle(page, mode):
    await page.get_by_role('button', name='All projects' if mode == 'overview' else 'Moving columns', exact=True).click()
    await settled(page, mode)


async def layout(page, width):
    result = await page.evaluate("""() => {
      const stage=document.querySelector('#stage').getBoundingClientRect();
      const cards=Array.from(document.querySelector('.cv-mp-overview').children, card=>{
        const box=card.getBoundingClientRect();
        const photo=card.querySelector('img');
        const last=card.querySelector('.cv-mp-card-more, .cv-mp-coming-soon').getBoundingClientRect();
        return {project:card.dataset.project, x:box.x,y:box.y,right:box.right,bottom:box.bottom,
          readable:last.bottom<=box.bottom-3, photo:photo.complete&&photo.naturalWidth>0,
          disabled:card.getAttribute('aria-disabled'),href:card.getAttribute('href')};
      });
      return {cards,stage:{top:stage.top,bottom:stage.bottom,left:stage.left,right:stage.right},
        hiddenColumns:Array.from(document.querySelectorAll('.cv-mp-col'), c=>getComputedStyle(c).display==='none')};
    }""")
    cards=result['cards']
    assert len(cards)==len({card['project'] for card in cards})==8, result
    assert all(card['photo'] and card['readable'] for card in cards), result
    assert all(result['hiddenColumns']), result
    solo=next(card for card in cards if card['project']=='Solo Project')
    assert solo['disabled']=='true' and solo['href'] is None, solo
    if width>700:
        assert len({round(card['x'],1) for card in cards})==2, result
        assert len({round(card['y'],1) for card in cards})==4, result
        assert all(card['y']>=result['stage']['top']-0.1 and card['bottom']<=result['stage']['bottom']+0.1 for card in cards),result
    else:
        assert len({round(card['x'],1) for card in cards})==1,result
        assert await page.locator('#stage').evaluate('el=>el.scrollHeight>el.clientHeight'),result
    return result


async def alignment(page, width):
    result=await page.evaluate("""() => {
      const button=document.querySelector('.cv-mp-view-button');
      const box=button.getBoundingClientRect();
      const home=document.querySelector('nav a[href="index.html"]').getBoundingClientRect();
      const range=document.createRange();range.selectNodeContents(document.querySelector('h1'));
      return {x:box.x,home:home.x,width:box.width,height:box.height,titleEnd:range.getBoundingClientRect().right,
        end:document.querySelector('.cv-mp-view-controls').getBoundingClientRect().right,
        color:getComputedStyle(button).color};
    }""")
    assert result['width']==result['height']==28,result
    assert result['color']=='rgb(200, 64, 10)',result
    assert result['titleEnd']<=result['x']-12,result
    assert result['end']<width,result
    if width>700: assert abs(result['x']-result['home'])<0.5,result
    return result


async def motion_and_hover(browser, base, out):
    context,page=await new_page(browser,base,init=CLOCK)
    await direct(page,base,'bio.html')
    await page.locator('nav a[href="music-projects.html"]').click()
    await check_entry(page,'music-projects.html')
    await loaded(page)
    await alignment(page,1440)
    await page.evaluate('stepGallery(0); stepGallery(17000)')
    before=await snapshot(page)
    originals=await page.locator('.cv-mp-track .cv-mp-card').evaluate_all("cards=>cards.map(card=>({project:card.dataset.project,box:card.getBoundingClientRect().toJSON()}))")
    transforms=await page.locator('.cv-mp-track').evaluate_all('els=>els.map(el=>el.style.transform)')
    await page.get_by_role('button',name='All projects',exact=True).click()
    animation=await page.evaluate("""() => {
      window.viewAnimations=document.querySelector('.cv-mp-morph-layer').getAnimations({subtree:true});
      viewAnimations.forEach(animation=>{animation.pause();animation.currentTime=0});
      const cards=Array.from(document.querySelectorAll('.cv-mp-morph-card'),card=>({project:card.dataset.project,box:card.getBoundingClientRect().toJSON()}));
      const timing=viewAnimations[0].effect.getTiming();
      const progress=[];
      for(const fraction of [0.2,0.8,1]) {
        viewAnimations.forEach(a=>a.currentTime=timing.duration*fraction);
        progress.push(viewAnimations[0].effect.getComputedTiming().progress);
      }
      viewAnimations.forEach(a=>a.currentTime=timing.duration*0.45);
      return {cards,duration:timing.duration,easing:timing.easing,progress};
    }""")
    assert animation['duration']==850,animation
    assert animation['progress'][0]>0.5 and 1-animation['progress'][1]<0.05,animation
    for column in before['columns']:
        for card in column:
            if min(card['bottom'],before['bottom'])-max(card['top'],before['top'])<=1:continue
            old=next(item for item in originals if item['project']==card['project'] and abs(item['box']['y']-card['top'])<0.1)
            proxy=next(item for item in animation['cards'] if item['project']==card['project'])
            assert all(abs(old['box'][key]-proxy['box'][key])<0.2 for key in ('x','y','width','height')),(old,proxy)
    if out:await page.screenshot(path=str(out/'reordering.png'))
    await page.evaluate('viewAnimations.forEach(animation=>animation.finish())')
    await settled(page,'overview')
    await layout(page,1440)
    await page.evaluate('stepGallery(30000)')
    assert transforms==await page.locator('.cv-mp-track').evaluate_all('els=>els.map(el=>el.style.transform)')
    card=page.locator('.cv-mp-overview .cv-mp-card').first
    box=await card.bounding_box();await card.hover();await page.wait_for_timeout(400)
    grown=await card.bounding_box()
    assert abs(grown['width']/box['width']-1.05)<0.002
    assert await card.evaluate("el=>getComputedStyle(el,'::after').opacity")=='0'
    assert await card.evaluate("el=>getComputedStyle(el).backgroundColor") in ['rgb(36, 32, 23)','rgb(44, 85, 68)','rgb(237, 101, 81)','rgb(239, 208, 111)']
    await page.mouse.move(10,10);await page.wait_for_timeout(400)
    if out:await page.screenshot(path=str(out/'overview.png'))
    await toggle(page,'moving')
    await page.evaluate('stepGallery(0); stepGallery(200)')
    after=await snapshot(page)
    assert [[card['id'] for card in column] for column in before['columns']]==[[card['id'] for card in column] for column in after['columns']]
    assert not page.errors,page.errors
    await context.close()
    return {'duration_ms':animation['duration'],'ease_progress':animation['progress'],'restored_nodes':True,'hover':True}


async def persistence(browser,base):
    context,page=await new_page(browser,base)
    await direct(page,base,'music-projects.html');await loaded(page)
    await toggle(page,'overview')
    for destination in GALLERY_COLORS:
        await page.locator(f'.cv-mp-overview a[href="{destination}"]').click()
        await check_entry(page,destination)
        await page.locator('nav a[href="music-projects.html"]').click()
        await check_entry(page,'music-projects.html')
        await settled(page,'overview');await layout(page,1440)
    for destination in ['bio.html','contact.html','gonzalez-reeds.html','index.html','music-projects.html']:
        await page.locator(f'nav a[href="{destination}"]').click();await check_entry(page,destination)
    await settled(page,'overview')
    await page.reload(wait_until='domcontentloaded');await loaded(page);await settled(page,'overview')
    await page.go_back(wait_until='domcontentloaded');await page.go_forward(wait_until='domcontentloaded')
    await loaded(page);await settled(page,'overview')
    fresh=await context.new_page();await fresh.goto(base+'music-projects.html',wait_until='domcontentloaded');await loaded(fresh);await settled(fresh,'moving')
    await fresh.close()
    await toggle(page,'moving')
    await page.locator('nav a[href="bio.html"]').click();await check_entry(page,'bio.html')
    await page.locator('nav a[href="music-projects.html"]').click();await check_entry(page,'music-projects.html');await settled(page,'moving')
    assert not page.errors,page.errors
    await context.close()
    return {'project_roundtrips':7,'menu_pages':5,'reload':True,'history':True,'fresh_tab_defaults_to_moving':True}


async def layouts(browser,base,out):
    results=[]
    for width,height in [(1512,770),(1280,900),(1920,1080),(390,844)]:
        context,page=await new_page(browser,base)
        await page.set_viewport_size({'width':width,'height':height})
        await direct(page,base,'music-projects.html');await loaded(page)
        aligned=await alignment(page,width)
        await toggle(page,'overview');await layout(page,width)
        if out:await page.screenshot(path=str(out/f'overview-{width}.png'))
        await page.set_viewport_size({'width':1440,'height':900});await page.wait_for_timeout(80)
        await layout(page,1440);await alignment(page,1440)
        await toggle(page,'moving')
        assert not page.errors,page.errors
        results.append({'viewport':[width,height],'aligned':aligned})
        await context.close()
    return results


async def resilience(browser,base):
    for options in [{'reduced':True},{'init':'Element.prototype.animate=undefined;'},
                    {'init':"Storage.prototype.setItem=()=>{throw new DOMException('Blocked','SecurityError')}"}]:
        context,page=await new_page(browser,base,**options)
        await direct(page,base,'music-projects.html');await loaded(page)
        await toggle(page,'overview');await layout(page,1440);await toggle(page,'moving')
        assert not page.errors,page.errors
        await context.close()
    context,page=await new_page(browser,base)
    await direct(page,base,'music-projects.html');await loaded(page)
    for mode in ['overview','moving','overview','moving']:
        await page.get_by_role('button',name='All projects' if mode=='overview' else 'Moving columns',exact=True).click()
        await page.wait_for_timeout(50)
    await settled(page,'moving')
    assert await page.evaluate("sessionStorage.getItem('cv-mp-view')")=='moving'
    assert not page.errors,page.errors
    await context.close()
    context,page=await new_page(browser,base)
    await direct(page,base,'music-projects.html');await loaded(page)
    await page.get_by_role('button',name='All projects',exact=True).evaluate('button=>button.click()')
    await page.locator('nav a[href="bio.html"]').evaluate('link=>link.click()')
    await check_entry(page,'bio.html')
    await page.locator('nav a[href="music-projects.html"]').click();await check_entry(page,'music-projects.html')
    await settled(page,'overview')
    assert not page.errors,page.errors
    await context.close()
    for pattern in ['**/music-projects-views.js?*','**/css/music-projects-views.css?*']:
        context,page=await new_page(browser,base)
        await page.route(pattern,lambda route:route.abort())
        await direct(page,base,'music-projects.html')
        assert await page.locator('.cv-mp-view-controls').is_hidden()
        assert not page.errors,page.errors
        await context.close()
    return {'reduced_motion':True,'no_web_animations':True,'blocked_storage':True,
            'rapid_toggles':True,'leave_during_reordering':True,'missing_assets':True}


async def run(base,out):
    subprocess.run(['node','--check',str(ROOT/'music-projects-views.js')],check=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path='/usr/bin/chromium',headless=True)
        results={}
        for name,check in [('motion',motion_and_hover),('persistence',persistence),('layouts',layouts),('resilience',resilience)]:
            results[name]=await check(browser,base,out) if name in ('motion','layouts') else await check(browser,base)
            print(json.dumps({name:results[name]}),flush=True)
        await browser.close()
    return {'status':'passed',**results}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path)
    args=parser.parse_args()
    out=args.results.parent if args.results else None
    server=TestServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=str(ROOT)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        result=asyncio.run(run(f'http://127.0.0.1:{server.server_port}/',out))
        if args.results:args.results.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result),flush=True)
    finally:server.shutdown();server.server_close()
