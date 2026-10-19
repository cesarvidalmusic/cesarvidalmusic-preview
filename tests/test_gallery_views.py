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
    assert animation['duration']==1200,animation
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
    visual=card.locator('.cv-mp-card-visual')
    box=await visual.bounding_box();await card.hover();await page.wait_for_timeout(400)
    grown=await visual.bounding_box()
    assert abs(grown['width']/box['width']-1.05)<0.002
    assert await visual.evaluate("el=>getComputedStyle(el,'::after').opacity")=='0'
    assert await visual.evaluate("el=>getComputedStyle(el).backgroundColor") in ['rgb(36, 32, 23)','rgb(44, 85, 68)','rgb(237, 101, 81)','rgb(239, 208, 111)']
    await page.mouse.move(10,10);await page.wait_for_timeout(400)
    if out:await page.screenshot(path=str(out/'overview.png'))
    await toggle(page,'moving')
    await page.evaluate('stepGallery(0); stepGallery(200)')
    after=await snapshot(page)
    assert [[card['id'] for card in column] for column in before['columns']]==[[card['id'] for card in column] for column in after['columns']]
    assert not page.errors,page.errors
    await context.close()
    return {'duration_ms':animation['duration'],'ease_progress':animation['progress'],'restored_nodes':True,'hover':True}


async def continuous_return(browser,base):
    context,page=await new_page(browser,base,init=CLOCK)
    await direct(page,base,'music-projects.html');await loaded(page)
    await page.evaluate('stepGallery(0);stepGallery(17000)')
    await toggle(page,'overview')
    await page.get_by_role('button',name='Moving columns',exact=True).click()
    await page.evaluate("""() => {
      window.returnAnimations=document.querySelector('.cv-mp-morph-layer').getAnimations({subtree:true});
      returnAnimations.forEach(a=>{a.pause();a.currentTime=0});
      window.returnStart=Array.from(document.querySelectorAll('.cv-mp-track'),el=>new DOMMatrix(el.style.transform).m42);
      stepGallery(0);
    }""")
    for total in [400,800,1200]:
        state=await page.evaluate("""elapsed => {
          stepGallery(elapsed);
          returnAnimations.forEach(a=>a.currentTime=Number(a.currentTime)+elapsed);
          return {active:!!document.querySelector('.cv-mp-morph-layer'),
            travel:Array.from(document.querySelectorAll('.cv-mp-track'),(el,i)=>new DOMMatrix(el.style.transform).m42-returnStart[i]),
            carriers:Array.from(document.querySelectorAll('.cv-mp-morph-motion'),el=>new DOMMatrix(getComputedStyle(el).transform).m42)};
        }""",400)
        assert state['active'],state
        assert all(abs(actual-speed*total/1000)<0.1 for actual,speed in zip(state['travel'],[-22,30,-18,26])),state
        assert any(abs(y)>1 for y in state['carriers']),state
    # Check the final proxy position against the actual moving target before
    # removing the proxy, including both upward and downward columns.
    handoff=await page.evaluate("""() => {
      const stage=document.querySelector('#stage').getBoundingClientRect();
      window.handoffCards=Array.from(document.querySelectorAll('.cv-mp-track .cv-mp-card'))
        .filter(card=>{const b=card.getBoundingClientRect();return b.top<stage.bottom&&b.bottom>stage.top});
      return handoffCards.map(card=>{
        const proxy=Array.from(document.querySelectorAll('.cv-mp-morph-card')).find(p=>p.dataset.project===card.dataset.project);
        return {project:card.dataset.project,actual:card.getBoundingClientRect().toJSON(),proxy:proxy?.getBoundingClientRect().toJSON()};
      });
    }""")
    for card in handoff:
        assert card['proxy'],card
        assert all(abs(card['actual'][key]-card['proxy'][key])<0.2 for key in ['x','y','width','height']),card
    await page.evaluate('returnAnimations.forEach(a=>a.finish())')
    await settled(page,'moving')
    travel=await page.evaluate("""() => {
      const before=handoffCards.map(card=>card.getBoundingClientRect().y);
      stepGallery(100);
      return handoffCards.map((card,i)=>({column:Array.from(document.querySelectorAll('.cv-mp-track')).indexOf(card.parentElement),dy:card.getBoundingClientRect().y-before[i]}));
    }""")
    for card in travel:
        assert abs(card['dy']-[-2.2,3,-1.8,2.6][card['column']])<0.1,card
    await snapshot(page)
    assert not page.errors,page.errors
    await context.close()
    return {'moving_during_reordering':True,'handoff_without_jump':True,'continues_without_restart':True}


async def hover_stability(browser,base):
    context,page=await new_page(browser,base)
    await page.set_viewport_size({'width':1512,'height':770})
    await direct(page,base,'music-projects.html');await loaded(page);await toggle(page,'overview')
    await page.evaluate('Math.random=()=>0')
    first=page.locator('.cv-mp-overview .cv-mp-card').nth(0)
    second=page.locator('.cv-mp-overview .cv-mp-card').nth(2)
    await first.hover();await page.wait_for_timeout(400)
    color=await first.evaluate("el=>el.style.getPropertyValue('--hover-color')")
    await page.evaluate("""() => {
      Math.random=()=>0.99;
      window.exitSamples=[];window.sampleExit=true;
      const card=document.querySelector('.cv-mp-overview .cv-mp-card-visual');
      function sample(){if(!sampleExit)return;exitSamples.push(getComputedStyle(card).backgroundColor);requestAnimationFrame(sample)}sample();
    }""")
    await second.hover();await page.wait_for_timeout(80)
    await page.locator('.cv-mp-overview .cv-mp-card').nth(4).hover();await page.wait_for_timeout(80)
    await page.locator('.cv-mp-overview .cv-mp-card').nth(6).hover();await page.wait_for_timeout(400)
    samples=await page.evaluate('sampleExit=false;exitSamples')
    # A departing card must fade monotonically to white, never pick up the
    # next card's random color or flash its older hover color again.
    channels=[[int(value.strip()) for value in sample[4:-1].split(',')] for sample in samples]
    assert all(all(b>=a for a,b in zip(old,new)) for old,new in zip(channels,channels[1:])),samples
    assert channels[-1]==[255,255,255],samples
    assert await first.evaluate("el=>el.style.getPropertyValue('--hover-color')")==color
    await first.hover();await page.wait_for_timeout(400)
    next_color=await first.evaluate("el=>el.style.getPropertyValue('--hover-color')")
    assert next_color!=color
    # Re-enter during the shrink animation, as happens at a shared hit edge.
    box=await first.bounding_box()
    await page.mouse.move(10,10)
    await page.evaluate('Math.random=()=>0')
    await page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
    assert await first.evaluate("el=>el.style.getPropertyValue('--hover-color')")==next_color
    await page.wait_for_timeout(400)
    assert await first.locator('.cv-mp-card-visual').evaluate("el=>getComputedStyle(el).backgroundColor")=='rgb(239, 208, 111)'
    assert not page.errors,page.errors
    await context.close()
    return {'same_column_exit_fades_to_white':True,'rapid_reentry_keeps_color':True}


async def return_boundaries(browser,base):
    # Include incoming covers and the instant a downward column recycles.
    phases=[0,200,600,1000,1500,1800,2000,2700,17000,28500,29000,29300,29600]
    for phase in phases:
        context,page=await new_page(browser,base,init=CLOCK)
        await direct(page,base,'music-projects.html');await loaded(page)
        await page.evaluate('ms=>{stepGallery(0);stepGallery(ms)}',phase)
        await page.get_by_role('button',name='All projects',exact=True).evaluate('button=>button.click()')
        await page.evaluate("document.querySelector('.cv-mp-morph-layer').getAnimations({subtree:true}).forEach(a=>a.finish())")
        await settled(page,'overview')
        await page.get_by_role('button',name='Moving columns',exact=True).evaluate('button=>button.click()')
        handoff=await page.evaluate("""() => {
          window.returnAnimations=document.querySelector('.cv-mp-morph-layer').getAnimations({subtree:true});
          returnAnimations.forEach(a=>{a.pause();a.currentTime=0});stepGallery(0);
          for(let i=0;i<12;i++)stepGallery(100);
          returnAnimations.forEach(a=>a.currentTime=1200);
          const stage=document.querySelector('#stage').getBoundingClientRect();
          const visible=selector=>Array.from(document.querySelectorAll(selector))
            .filter(card=>{const box=card.getBoundingClientRect();return box.top<stage.bottom-0.1&&box.bottom>stage.top+0.1});
          const actual=visible('.cv-mp-track .cv-mp-card');
          const proxies=visible('.cv-mp-morph-card');
          return {actual:actual.map(card=>card.dataset.project),proxies:proxies.map(card=>card.dataset.project),
            errors:actual.map(card=>{
              const proxy=proxies.find(p=>p.dataset.project===card.dataset.project);
              const a=card.getBoundingClientRect(),b=proxy?.getBoundingClientRect();
              return b?Math.max(...['x','y','width','height'].map(key=>Math.abs(a[key]-b[key]))):null;
            })};
        }""")
        assert set(handoff['actual'])==set(handoff['proxies']),(phase,handoff)
        assert all(error is not None and error<0.2 for error in handoff['errors']),(phase,handoff)
        await page.evaluate('returnAnimations.forEach(a=>a.finish())')
        await settled(page,'moving');await snapshot(page)
        for _ in range(20):
            await page.evaluate('stepGallery(200)');await snapshot(page)
        assert not page.errors,page.errors
        await context.close()
    return {'entry_and_recycling_phases':len(phases),'visible_proxies_match_live_cards':True}


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
        for name,check in [('motion',motion_and_hover),('continuous_return',continuous_return),('hover_stability',hover_stability),('return_boundaries',return_boundaries),('persistence',persistence),('layouts',layouts),('resilience',resilience)]:
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
