const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:950}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(pathToFileURL(path.join(__dirname,'index.html')).href+'#jobs');
 async function route(name){
  if(await page.locator('#menu-toggle').isVisible()){
   await page.locator('#menu-toggle').click();await page.locator(`#mobile-menu [data-career="${name}"]`).click();
  }else await page.locator(`.sidebar [data-career="${name}"]`).click();
  await page.waitForFunction(name=>document.body.dataset.page===name&&document.querySelector('#menu-toggle').getAttribute('aria-expanded')==='false',name);
 }
 async function focused(selector){await page.waitForFunction(s=>document.querySelector(s)===document.activeElement,selector);}
 async function screenshot(name){await page.evaluate(()=>document.querySelector('#toast').classList.remove('visible'));await page.screenshot({path:path.join(__dirname,'screenshots',name+'.png'),fullPage:false,animations:'disabled'});}
 assert.equal(await page.locator('.job.selected').getAttribute('data-id'),'1');
 await page.locator('.save').click();
 await route('profile');await page.locator('#edit-criteria').click();
 const initial=await page.locator('#criterion-direction').inputValue();
 await page.locator('#criterion-direction').fill('Другие задачи');await page.locator('#cancel-criteria').click();
 assert.equal(await page.evaluate(()=>criteriaChanged()),false);
 await page.locator('#edit-criteria').click();await page.locator('#criteria-form [type=submit]').click();
 assert.equal(await page.evaluate(()=>criteriaChanged()),false);
 await page.locator('#edit-criteria').click();await page.locator('#criterion-direction').fill('Другие задачи');await page.locator('#criteria-form [type=submit]').click();
 for(const name of ['assistant','jobs','saved']){
  await route(name);assert.equal(await page.locator('.freshness-note:visible').count(),name==='assistant'?1:2);
  if(name!=='assistant'){assert.equal(await page.locator('#detail .freshness-note').textContent(),'Критерии изменены. Этот разбор ещё не обновлён');assert.equal(await page.locator('#detail .badge').textContent(),'Подходит');}
 }
 await route('profile');await page.locator('#edit-criteria').click();await page.locator('#criterion-direction').fill(initial);await page.locator('#criteria-form [type=submit]').click();
 for(const name of ['assistant','jobs','saved']){await route(name);assert.equal(await page.locator('.freshness-note:visible').count(),0);}
 await route('assistant');
 const bottoms=await page.locator('.rec-actions').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().bottom));assert(Math.abs(bottoms[0]-bottoms[1])<2);
 // Arrange a larger saved set, then exercise removal through actual controls.
 await page.evaluate(()=>{saved.add(2);saved.add(3);});await route('saved');await page.locator('[data-id="2"]').click();await page.locator('.save').click();assert.equal(await page.locator('.job.selected').getAttribute('data-id'),'3');
 await page.setViewportSize({width:390,height:850});await route('assistant');
 assert.equal(await page.locator('#title').textContent(),'Помощник по поиску работы');
 assert.equal(await page.locator('#assistant-criteria').getAttribute('open'),null);
 await page.locator('#assistant-criteria summary').click();assert.equal(await page.locator('#edit-assistant-criteria').isVisible(),true);
 await page.setViewportSize({width:1440,height:950});await page.waitForFunction(()=>document.querySelector('#assistant-criteria').open);
 assert.equal(await page.evaluate(()=>criteria.direction),initial);
 await page.setViewportSize({width:390,height:850});await route('saved');
 assert.equal(await page.locator('#filter-panel').isVisible(),false);
 await page.locator('#filter-toggle').click();await page.locator('#query').fill('линия');
 assert.equal(await page.locator('#filter-panel').isVisible(),true);await page.locator('#filter-toggle').click();
 assert((await page.locator('#filter-toggle').textContent()).includes('Есть условия'));
 assert.equal(await page.locator('#clear-conditions').isVisible(),true);await page.locator('#clear-conditions').click();
 await page.locator('[data-id="1"]').click();await page.locator('.save').click();assert.equal(await page.locator('#list').isVisible(),true);await focused('[data-id="3"]');
 await page.locator('[data-id="3"]').click();await page.locator('.save').click();assert.equal(await page.locator('#saved-empty').isVisible(),true);
 await page.locator('#toast button').click();assert.equal(await page.locator('#saved-empty').isVisible(),false);
 await route('jobs');assert.equal(await page.locator('#list').isVisible(),true);
 await page.locator('[data-filter="review"]').click();await page.locator('#query').fill('контур');
 await page.locator('[data-id="5"]').scrollIntoViewIfNeeded();const scroll=await page.evaluate(()=>scrollY);
 await page.locator('[data-id="5"]').click();await screenshot('detail-390');await page.locator('.back-list').click();
 await focused('[data-id="5"]');assert.equal(await page.locator('#query').inputValue(),'контур');assert.equal(await page.locator('[data-filter="review"]').getAttribute('aria-pressed'),'true');assert(Math.abs(await page.evaluate(()=>scrollY)-scroll)<5);
 assert.equal(await page.locator('.job.selected').count(),0);
 await page.evaluate(()=>{statuses[1]='Откликнулся';});await route('applications');
 assert.equal(await page.locator('[data-group]').first().getAttribute('data-group'),'Откликнулся');
 assert.equal(await page.locator('.group-collapsed').count(),1);
 const order=await page.locator('[data-group]').evaluateAll(nodes=>nodes.map(n=>n.dataset.group));
 await page.locator('#application-1').selectOption('Интересно');await focused('#application-1');
 assert.deepEqual(await page.locator('[data-group]').evaluateAll(nodes=>nodes.map(n=>n.dataset.group)),order);
 await page.setViewportSize({width:1440,height:950});await page.waitForFunction(()=>document.querySelector('[data-group]').dataset.group==='Интересно');
 await page.setViewportSize({width:390,height:850});await route('jobs');
 await page.locator('#query').fill('');await page.locator('[data-filter="all"]').click();
 await page.locator('#menu-toggle').click();assert.equal(await page.locator('#mobile-menu .nav-note').isVisible(),true);
 await screenshot('menu-390');assert(await page.locator('#mobile-menu').evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}));
 for(let i=0;i<12;i++){await page.keyboard.press('Tab');assert(await page.evaluate(()=>document.querySelector('#mobile-menu').contains(document.activeElement)));}
 const under=await page.evaluate(()=>scrollY);await page.mouse.move(5,800);await page.mouse.wheel(0,600);await page.waitForTimeout(100);assert.equal(await page.evaluate(()=>scrollY),under);
 await page.keyboard.press('Escape');await focused('#menu-toggle');
 await page.locator('#menu-toggle').click();await page.locator('#menu-close').click();await focused('#menu-toggle');
 await route('profile');await focused('#title');await page.locator('#confirm-preference').click();assert.equal(await page.locator('.proposal').count(),0);assert.equal(await page.locator('.confirmed').textContent(),'Ограничение добавлено');
 await page.locator('#edit-criteria').click();await screenshot('edit-profile-390');
 // Reduced viewport approximates the space remaining above a software keyboard.
 await page.setViewportSize({width:390,height:420});await page.locator('#criterion-calls').fill('x'.repeat(201));await page.locator('#criteria-form [type=submit]').click();assert((await page.locator('#criteria-error').textContent()).includes('200'));
 await page.locator('#criterion-calls').fill('Без постоянных звонков');await page.locator('#criteria-form [type=submit]').click();await focused('#edit-criteria');
 await page.setViewportSize({width:1440,height:650});await route('jobs');await page.locator('[data-id="1"]').click();await page.locator('.copy').scrollIntoViewIfNeeded();assert(await page.locator('.copy').isVisible());
 assert(await page.locator('.copy').evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}));
 const phone=await browser.newPage({viewport:{width:390,height:850},isMobile:true,hasTouch:true});
 phone.on('pageerror',e=>errors.push(e.message));
 await phone.goto(pathToFileURL(path.join(__dirname,'index.html')).href+'#jobs');
 assert.equal(await phone.locator('#list').isVisible(),true);assert.equal(await phone.locator('#detail').isVisible(),false);
 await phone.evaluate(()=>{jobs[0].title='Координатор международных проектов и внедрения информационных систем '.repeat(5);jobs[0].salary=null;render();});
 await phone.locator('[data-id="1"]').click();assert.equal(await phone.locator('.detail-salary').textContent(),'Зарплата не указана');assert.equal(await phone.locator('a.vacancy').count(),0);
 for(const width of [360,390]){await phone.setViewportSize({width,height:850});assert(await phone.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 await phone.evaluate(()=>{saved.add(1);saved.add(2);saved.add(3);saved.add(4);openCareer('saved');});assert.equal(await phone.locator('#filter-panel').isVisible(),true);
 await phone.close();
 assert.deepEqual(errors,[]);console.log('PASS: freshness across routes, reset criteria, responsive criteria, favorite filters/removal, groups, modal focus/scroll, short viewport, reachable detail actions, touch viewport and long titles.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
