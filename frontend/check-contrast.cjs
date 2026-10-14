const {chromium}=require('playwright');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto(pathToFileURL(path.join(__dirname,'index.html')).href);
 async function measure(label){return page.evaluate(label=>{
  const rgba=v=>{const a=v.match(/[\d.]+/g)?.map(Number)||[0,0,0,0];return [a[0],a[1],a[2],a[3]??1];};
  const over=(f,b)=>[0,1,2].map(i=>f[i]*f[3]+b[i]*(1-f[3]));
  const background=e=>{const stack=[];for(let n=e;n;n=n.parentElement)stack.unshift(rgba(getComputedStyle(n).backgroundColor));return stack.reduce((b,f)=>over(f,b),[255,255,255]);};
  const luminance=c=>c.map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;}).reduce((v,x,i)=>v+x*[.2126,.7152,.0722][i],0);
  const results=[];
  for(const e of document.querySelectorAll('body *')){
   if(!e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})||e.closest('script,style')||e.disabled)continue;
   const text=[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent.trim()).join('').trim();
   if(!text||!/[\p{L}\p{N}]/u.test(text))continue;
   const css=getComputedStyle(e),bg=background(e),fg=over(rgba(css.color),bg),l1=luminance(fg),l2=luminance(bg);
   const ratio=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05),large=parseFloat(css.fontSize)>=24||(parseFloat(css.fontSize)>=18.66&&parseInt(css.fontWeight)>=700);
   results.push({page:label,text:text.slice(0,70),ratio:Number(ratio.toFixed(2)),required:large?3:4.5,pass:ratio>=(large?3:4.5),selector:e.tagName+'.'+e.className});
  }
  return results;
 },label);}
 let rows=[];
 for(const name of ['assistant','jobs','applications','profile','saved','history']){
  await page.locator(`.sidebar [data-career="${name}"]`).click();
  if(name==='jobs')await page.locator('[data-id="1"]').click();
  if(name==='profile')await page.locator('#edit-criteria').click();
  rows.push(...await measure(name));
  if(name==='profile')await page.keyboard.press('Escape');
 }
 await page.locator('.sidebar [data-career="jobs"]').click();
 for(const id of [3,6]){await page.locator(`[data-id="${id}"]`).click();rows.push(...await measure('assessment-'+id));}
 await page.locator('.save').hover();rows.push(...await measure('hover'));
 const failed=rows.filter(r=>!r.pass);
 fs.writeFileSync(path.join(__dirname,'contrast-report.json'),JSON.stringify({checked:rows.length,minimum:Math.min(...rows.map(r=>r.ratio)),failed},null,2));
 console.log(JSON.stringify({checked:rows.length,minimum:Math.min(...rows.map(r=>r.ratio)),failed},null,2));
 await browser.close();if(failed.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exit(1)});
