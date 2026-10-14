const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const url=pathToFileURL(path.join(__dirname,'index.html')).href;
 const screenshots=path.join(__dirname,'screenshots');fs.mkdirSync(screenshots,{recursive:true});
 async function route(name){
  if(await page.locator('#menu-toggle').isVisible()){
   await page.locator('#menu-toggle').click();await page.locator(`#mobile-menu [data-career="${name}"]`).click();
  }else await page.locator(`.sidebar [data-career="${name}"]`).click();
  await page.waitForFunction(name=>document.body.dataset.page===name&&document.querySelector('#menu-toggle').getAttribute('aria-expanded')==='false',name);
 }
 async function assertNoOverflow(label){assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Overflow: '+label);}
 await page.goto(url+'#assistant');
 assert.equal(await page.locator('.recommendation').count(),2);
 assert.equal(await page.locator('#explore').textContent(),'Посмотреть 3 вакансии');
 assert((await page.locator('.assistant-hero').textContent()).includes('По 2 вакансиям'));
 assert.deepEqual(await page.evaluate(()=>[0,1,2,5,11,21].map(n=>ruCount(n,'вакансию','вакансии','вакансий'))),['вакансий','вакансию','вакансии','вакансий','вакансий','вакансию']);
 await route('jobs');assert.equal(await page.locator('.job.selected').getAttribute('data-id'),'1');
 await page.locator('[data-id="3"]').click();assert.equal(await page.locator('[data-id="3"]').evaluate(e=>e===document.activeElement),true);
 await route('assistant');await route('jobs');assert.equal(await page.locator('.job.selected').getAttribute('data-id'),'3');
 await page.locator('[data-filter="match"]').click();assert.equal(await page.locator('.job.selected').getAttribute('data-id'),'1');
 assert.equal(await page.evaluate(()=>{const e=new KeyboardEvent('keydown',{key:'f',ctrlKey:true,bubbles:true,cancelable:true});document.dispatchEvent(e);return e.defaultPrevented;}),false);
 await route('profile');await page.locator('#edit-criteria').click();await page.locator('#criteria-form [type=submit]').click();assert.equal(await page.evaluate(()=>criteriaChanged()),false);
 await page.locator('#edit-criteria').click();await page.locator('#criterion-direction').fill('Отмена');await page.locator('#cancel-criteria').click();assert.equal(await page.evaluate(()=>criteriaChanged()),false);
 for(const state of ['error','loading']){
  await page.evaluate(state=>{listState=state;},state);await route('assistant');assert.equal(await page.locator('.recommendation').count(),0);
  await page.locator('#explore').click();assert.equal(await page.evaluate(()=>listState),state);assert.equal(await page.locator('#detail-heading').count(),0);
 }
 await page.evaluate(()=>{listState='empty';});await route('assistant');assert.equal(await page.locator('#explore').textContent(),'Посмотреть все вакансии');
 await page.evaluate(()=>{listState='ready';filter='all';});await route('assistant');

 await page.locator('[data-pick="2"]').click();assert((await page.locator('#detail-heading').textContent()).includes('Ассистент'));
 assert.equal(await page.locator('.vacancy').count(),0);
 assert.equal(await page.locator('.detail-salary').textContent(),'55 000 – 75 000 ₽');
 await page.locator('[data-filter="review"]').click();await page.locator('#query').fill('орбита');assert.equal(await page.locator('.job').count(),1);
 await page.locator('[data-id="3"]').click();assert.equal(await page.locator('.detail-salary').textContent(),'Зарплата не указана');
 await page.locator('#query').fill('no such company');assert.equal(await page.locator('.job').count(),0);assert.equal(await page.locator('#detail-heading').count(),0);
 await page.locator('#reset-filters').click();await page.locator('[data-id="1"]').click();
 await page.locator('.save').click();await page.locator('.state-select').selectOption('Интересно');
 await route('saved');assert.equal(await page.locator('.job').count(),1);await page.locator('[data-id="1"]').click();assert.equal(await page.locator('.state-select').inputValue(),'Интересно');
 await page.locator('.save').click();assert.equal(await page.locator('#saved-empty').isVisible(),true);assert.equal(await page.locator('.filters').isVisible(),false);assert.equal(await page.locator('.subtitle').textContent(),'Твои сохранённые предложения');
 await page.locator('#toast button').click();assert.equal(await page.locator('.job').count(),1);
 await route('assistant');assert.equal(await page.locator('[data-save="1"]').getAttribute('aria-pressed'),'true');
 await route('applications');assert.equal(await page.locator('.application-card').count(),1);await page.locator('#application-1').selectOption('Откликнулся');await page.locator('[data-application="1"]').click();assert.equal(await page.locator('.state-select').inputValue(),'Откликнулся');
 await route('profile');await page.locator('#edit-criteria').click();const original=await page.locator('#criterion-direction').inputValue();
 await page.locator('#criterion-direction').fill('Draft');await page.locator('#cancel-criteria').click();assert.equal(await page.locator('#edit-criteria').evaluate(e=>e===document.activeElement),true);
 await page.locator('#edit-criteria').click();assert.equal(await page.locator('#criterion-direction').inputValue(),original);
 await page.locator('#criterion-direction').fill('x'.repeat(201));await page.locator('#criteria-form [type=submit]').click();assert((await page.locator('#criteria-error').textContent()).includes('200'));
 await page.locator('#criterion-direction').fill('Координация и поддержка');await page.locator('#criteria-form [type=submit]').click();
 await route('assistant');assert((await page.locator('.profile-summary').textContent()).includes('Координация и поддержка'));assert((await page.locator('.analysis-note').textContent()).includes('Критерии изменены'));assert.equal(await page.evaluate(()=>criteriaChanged()),true);
 await route('profile');assert.equal(await page.locator('#confirm-preference').getAttribute('class'),'secondary');await page.locator('#confirm-preference').click();assert.equal(await page.locator('.confirmed').count(),1);
 await route('assistant');assert((await page.locator('.profile-summary').textContent()).includes('Без постоянных звонков'));
 await route('history');assert((await page.locator('#extra').textContent()).includes('пока недоступна'));assert.equal(await page.locator('[data-browse]:visible').count(),1);
 await route('jobs');await page.locator('#search-demo summary').click();
 for(const state of ['loading','error','empty','unavailable','not-started','processing','complete','paused']){
  await page.locator('#demo-state').selectOption(state);assert.equal(await page.locator('.job').count(),['loading','error','empty','unavailable','not-started'].includes(state)?0:6);
 }
 await page.locator('#demo-state').selectOption('error');await page.locator('#retry').click();assert.equal(await page.locator('.job').count(),6);
 await page.locator('#resume').selectOption({index:1});await page.locator('#demo-resume').click();assert.equal(await page.locator('.job').count(),1);
 await route('assistant');assert((await page.locator('#all-jobs').textContent()).includes('1'));
 await route('jobs');await page.locator('#resume').selectOption({index:0});await page.locator('#demo-resume').click();await page.locator('#demo-state').selectOption('ready');
 await page.locator('#batch').click();assert.equal(await page.locator('#dialog').isVisible(),true);await page.keyboard.press('Escape');assert.equal(await page.locator('#batch').evaluate(e=>e===document.activeElement),true);
 await page.locator('#search-demo summary').click();
 await page.evaluate(()=>{jobs.push({id:99,title:'<img src=x onerror=alert(1)>',company:'Test'});filter='unrated';render();});
 await page.locator('[data-id="99"]').click();assert.equal(await page.locator('.analysis-empty').count(),1);assert.equal(await page.locator('#detail img').count(),0);assert.equal(await page.locator('.copy').count(),0);
 await page.evaluate(()=>{jobs.pop();filter='all';render();});
 await page.locator('[data-id="1"]').click();
 await page.evaluate(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw Error('denied')}}});});
 await page.locator('.copy').click();assert.equal(await page.locator('.copy-fallback').isVisible(),true);assert((await page.locator('.copy-fallback').inputValue()).length>10);
 await page.evaluate(()=>{navigator.clipboard.writeText=async text=>{window.copied=text};});await page.locator('.copy').click();assert.equal(await page.locator('#toast').textContent(),'Вопросы скопированы');
 const pages=['assistant','jobs','applications','profile','saved','history'];
 for(const width of [360,390,768,1024,1440,1920]){
  await page.setViewportSize({width,height:1100});
  for(const name of pages){await route(name);await assertNoOverflow(`${name} ${width}`);
   const geometry=await page.evaluate(()=>{
    const left=s=>document.querySelector(s).getBoundingClientRect().left;
    const area=['jobs','saved'].includes(document.body.dataset.page)?'#workspace':'#extra';
    return {zoom:visualViewport.scale,dpr:devicePixelRatio,gap:left('#title')-document.querySelector('.sidebar').getBoundingClientRect().right,title:left('#title'),subtitle:left('.subtitle'),block:left(area),mainWidth:document.querySelector('main').getBoundingClientRect().width};
   });
   assert.equal(geometry.zoom,1,'Browser zoom must be 100%');assert.equal(geometry.dpr,1);
   assert.equal(geometry.title,geometry.subtitle);assert.equal(geometry.title,geometry.block);
   if(width>=1440){assert.equal(geometry.gap,32,`${name} ${width}: sidebar gap`);assert(geometry.mainWidth<=1440);}
   const active=page.locator(`${width<=800?'#mobile-menu':'.sidebar'} [aria-current=page]`);assert.equal(await active.count(),1);
   if(width===1440&&['jobs','saved'].includes(name))await page.locator('.job').first().click();
   if(width===390||width===1440||width===1920){await page.evaluate(()=>{document.querySelector('#toast').classList.remove('visible')});await page.screenshot({path:path.join(screenshots,`${name}-${width}.png`),fullPage:true,animations:'disabled'});}
  }
 }
 await page.setViewportSize({width:390,height:850});await route('jobs');
 assert.equal(await page.locator('#list').isVisible(),true);await page.locator('[data-id="5"]').scrollIntoViewIfNeeded();const before=await page.evaluate(()=>scrollY);
 await page.locator('[data-id="5"]').focus();await page.keyboard.press('Enter');assert.equal(await page.locator('#list').isVisible(),false);
 await page.locator('.back-list').click();assert(Math.abs(await page.evaluate(()=>scrollY)-before)<5,'List scroll not restored');
 await page.locator('#menu-toggle').focus();await page.keyboard.press('Enter');assert.equal(await page.locator('#mobile-menu').isVisible(),true);await page.keyboard.press('Escape');assert.equal(await page.locator('#menu-toggle').evaluate(e=>e===document.activeElement),true);
 await route('profile');await page.locator('#edit-criteria').click();await page.keyboard.press('Escape');assert.equal(await page.locator('#edit-criteria').evaluate(e=>e===document.activeElement),true);
 await page.reload();assert.equal(await page.evaluate(()=>saved.size),0);assert.deepEqual(await page.evaluate(()=>statuses),{});assert.equal(await page.evaluate(()=>criteria.direction),original);
 await route('applications');assert.equal(await page.locator('.ignored-group').count(),0);await page.evaluate(()=>{statuses[1]='Не подходит';renderApplications();});assert.equal(await page.locator('.ignored-group').count(),1);await page.locator('.ignored-group summary').click();await page.locator('#application-1').selectOption('Не просмотрено');assert.equal(await page.locator('.ignored-group').count(),0);assert.equal(await page.locator('.pipeline-column').count(),0);assert.equal(await page.locator('[data-browse]:visible').count(),1);
 await route('saved');assert.equal(await page.locator('#saved-empty').isVisible(),true);
 assert.deepEqual(errors,[]);console.log('PASS: 12 user scenarios; 6 pages × 6 widths; desktop/mobile screenshots; no page errors.');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
