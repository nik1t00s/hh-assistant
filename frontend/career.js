// Existing six routes; all decisions share the same in-memory state.
const careerNames={assistant:'Мой помощник',jobs:'Мои вакансии',applications:'Мои отклики',profile:'Мой профиль',saved:'Избранное',history:'История поиска'};
let proposalSkipped=false,profileOpener=null,mobileCriteriaOpen=false,menuDestination=null,applicationOrder=null;
const mobileLayout=matchMedia('(max-width:800px)');
function updateNavigation(){
 for(const container of document.querySelectorAll('[data-navigation]')){
  container.innerHTML=Object.entries(careerNames).map(([id,name],i)=>`<button class="nav" data-career="${id}"><span class="nav-icon" aria-hidden="true">${icon(id)}</span><span>${name}</span>${id==='jobs'?`<b>${currentJobs().length}</b>`:id==='history'?'<small class=nav-note>Недоступно</small>':''}</button>`).join('');
  container.querySelectorAll('[data-career]').forEach(b=>{b.classList.toggle('active',b.dataset.career===page);if(b.dataset.career===page)b.setAttribute('aria-current','page');b.onclick=()=>{if($('#mobile-menu').open){menuDestination=b.dataset.career;$('#mobile-menu').close();}else openCareer(b.dataset.career,true);};});
 }
}
function openCareer(target,focus=false){
 if(!Object.hasOwn(careerNames,target))target='jobs';const previous=page;page=target;if(target==='applications'&&previous!==target)applicationOrder=null;
 if(location.hash!==`#${target}`)location.hash=target;document.body.dataset.page=target;
 const isList=['jobs','saved'].includes(target);$('#workspace').hidden=!isList;$('#extra').hidden=isList;$('#search-demo').hidden=target!=='jobs';
 $('#title').textContent=target==='assistant'?(mobileLayout.matches?'Помощник по поиску работы':'Твой помощник в поиске работы'):careerNames[target];
 $('.subtitle').textContent={assistant:'WORKAholic помогает понять, какие вакансии подходят тебе и что уточнить перед откликом',jobs:'',saved:'Твои сохранённые предложения',applications:'Сохраняй планы и отмечай, куда уже откликнулся',profile:'Критерии, по которым WORKAholic оценивает вакансии',history:'Результаты предыдущих поисков в одном месте'}[target];
 updateNavigation();
 if(isList){if(previous!==target)selected=matchMedia('(max-width:900px)').matches?undefined:rememberedSelection[target];render();}else refreshCurrentPage();
 if(focus){$('#title').focus({preventScroll:true});window.scrollTo(0,0);}
}
function refreshCurrentPage(){
 updateNavigation();if(['jobs','saved'].includes(page))render();else if(page==='assistant')renderAssistant();else if(page==='profile')renderProfile();else if(page==='applications')renderApplications();
 else if(page==='history'){$('#extra').innerHTML=emptyPanel('История поиска пока недоступна','Здесь будут результаты предыдущих поисков, когда функция будет подключена','К вакансиям');bindBrowse();}
}
function openJob(id){filter='all';newOnly=false;$('#query').value='';openCareer('jobs');selectVacancy(id,true);}
function renderAssistant(){
 const counts=jobCounts(),blocked=['loading','error'].includes(listState),recommendations=currentJobs().filter(j=>j.type==='match').slice(0,2);
 $('#extra').innerHTML=`<div class="home-grid"><div><section class="assistant-hero"><span class="example-label">Сводка подборки</span><h2>${blocked?(listState==='error'?'Не удалось загрузить подборку':'Подборка загружается'):counts.match?`${mobileLayout.matches?'В подборке':'Текущая подборка:'} ${counts.match} ${ruCount(counts.match,'подходящая вакансия','подходящие вакансии','подходящих вакансий')}`:'Подходящих вакансий пока нет'}</h2><p>${blocked?'Рекомендации появятся после загрузки списка.':`По ${counts.review} ${ruCount(counts.review,'вакансии','вакансиям','вакансиям')} нужно уточнить условия.`}</p><div class="hero-buttons"><button class="primary" id="explore">${blocked?'Открыть состояние подборки':counts.match?`Посмотреть ${counts.match} ${ruCount(counts.match,'вакансию','вакансии','вакансий')}`:'Посмотреть все вакансии'}</button><button class="secondary" id="adjust">Изменить критерии</button></div><p class="analysis-note">${criteriaChanged()?'Критерии изменены. Эти оценки относятся к предыдущим условиям':criteriaNotice()}</p></section><div class="home-section-title"><h2>Рекомендованные вакансии</h2><button id="all-jobs">Все вакансии · ${counts.total} →</button></div>${freshnessNote()}<div class="recommendations">${recommendations.map(j=>`<article class="recommendation"><div class="company">${esc(j.company)}</div><h3>${esc(j.title)}</h3><strong>${esc(j.salary||'Зарплата не указана')}</strong><p class="rec-mode">${esc(j.mode||'Формат не указан')}</p><p>${esc((j.why||[])[0]||'Объяснение оценки отсутствует')}</p><div class="rec-actions"><button class="link-button" data-pick="${j.id}">Посмотреть разбор →</button><button class="secondary" data-save="${j.id}" aria-pressed="${saved.has(j.id)}" aria-label="${saved.has(j.id)?'Убрать из избранного':'Сохранить'}: ${esc(j.title)}">${saved.has(j.id)?'Убрать из избранного':'Сохранить'}</button></div></article>`).join('')||`<p>${blocked?'Список рекомендаций недоступен до загрузки подборки.':'Подходящих предложений пока нет. Посмотри всю подборку или уточни критерии.'}</p>`}</div><p class="unavailable-chat">Диалог с помощником пока недоступен.</p></div><aside class="home-side"><details class="profile-summary" id="assistant-criteria" ${!mobileLayout.matches||mobileCriteriaOpen?'open':''}><summary tabindex="${mobileLayout.matches?0:-1}">Критерии поиска</summary>${criteriaMarkup()}<button id="edit-assistant-criteria" class="secondary">Изменить критерии</button></details></aside></div>`;
 $('#explore').onclick=()=>{filter=counts.match?'match':'all';$('#query').value='';selected=undefined;openCareer('jobs',true);};$('#all-jobs').onclick=()=>{filter='all';$('#query').value='';openCareer('jobs',true);};
 $('#adjust').onclick=$('#edit-assistant-criteria').onclick=()=>openCareer('profile',true);
 $('#assistant-criteria').ontoggle=e=>{if(mobileLayout.matches)mobileCriteriaOpen=e.target.open;};
 $('#assistant-criteria summary').onclick=e=>{if(!mobileLayout.matches)e.preventDefault();};
 document.querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>openJob(Number(b.dataset.pick)));
 document.querySelectorAll('[data-save]').forEach(b=>b.onclick=()=>{const id=Number(b.dataset.save);updateFavorite(id);renderAssistant();document.querySelector(`[data-save="${id}"]`).focus();});
}
function renderProfile(){
 $('#extra').innerHTML=`<div class="profile-layout"><section class="panel"><div class="panel-heading"><h2>Какую работу ищем</h2><button id="edit-criteria" class="primary">Редактировать критерии</button></div>${criteriaMarkup()}<p class="analysis-note">${criteriaNotice()}</p></section>${proposalSkipped?'':criteria.calls==='Без постоянных звонков'?'<p class="confirmed proposal-confirmation" role="status">Ограничение добавлено</p>':`<section class="panel proposal"><span class="example-label">Демонстрационное предложение</span><h2>Предложение помощника</h2><p>Исключать вакансии с постоянными телефонными звонками.</p><div class="hero-buttons"><button class="secondary" id="confirm-preference">Добавить ограничение</button><button class="secondary" id="defer-preference">Пока пропустить</button></div></section>`}</div>`;
 $('#edit-criteria').onclick=showCriteriaEditor;
 if($('#confirm-preference'))$('#confirm-preference').onclick=()=>{criteria.calls='Без постоянных звонков';renderProfile();$('#edit-criteria').focus();toast('Ограничение добавлено');};
 if($('#defer-preference'))$('#defer-preference').onclick=()=>{proposalSkipped=true;renderProfile();$('#edit-criteria').focus();toast('Критерии не изменены');};
}
function showCriteriaEditor(){
 profileOpener=document.activeElement;const dialog=$('#criteria-dialog');
 dialog.innerHTML=`<form id="criteria-form" novalidate><h2 id="criteria-title">Редактировать критерии</h2><p>Изменения сохранятся до обновления страницы.</p>${Object.entries(criterionLabels).map(([key,label])=>`<label class="form-field" for="criterion-${key}">${label}<input id="criterion-${key}" name="${key}" value="${esc(criteria[key])}" aria-describedby="criteria-error" autocomplete="off"></label>`).join('')}<p id="criteria-error" role="alert"></p><div class="dialog-actions"><button type="button" id="cancel-criteria" class="secondary">Отмена</button><button class="primary" type="submit">Сохранить</button></div></form>`;
 $('#cancel-criteria').onclick=()=>dialog.close();
 $('#criteria-form').onsubmit=e=>{e.preventDefault();const draft=Object.fromEntries(new FormData(e.target));
  for(const [key,value] of Object.entries(draft)){const field=$('#criterion-'+key);field.removeAttribute('aria-invalid');if(value.trim().length>200){$('#criteria-error').textContent='Сократи поле «'+criterionLabels[key]+'» до 200 символов.';field.setAttribute('aria-invalid','true');field.focus();return;}}
  Object.assign(criteria,Object.fromEntries(Object.entries(draft).map(([k,v])=>[k,v.trim()])));dialog.close();renderProfile();$('#edit-criteria').focus();toast('Критерии сохранены. Подборка не пересчитывалась.');
 };dialog.showModal();$('#criterion-direction').focus();
}
$('#criteria-dialog').addEventListener('close',()=>profileOpener?.isConnected&&profileOpener.focus());
function applicationCard(j){return `<article class="application-card"><span class="company">${esc(j.company)}</span><h3>${esc(j.title)}</h3><p>${esc(j.salary||'Зарплата не указана')}</p><label for="application-${j.id}">Мой статус</label><select id="application-${j.id}" data-application-status="${j.id}">${statusOptions(j.id)}</select><button class="link-button" data-application="${j.id}">Открыть разбор →</button></article>`;}
function renderApplications(){
 const active=jobs.filter(j=>['Интересно','Откликнулся'].includes(statuses[j.id])),ignored=jobs.filter(j=>statuses[j.id]==='Не подходит');
 const count=status=>active.filter(j=>statuses[j.id]===status).length;
 if(!applicationOrder)applicationOrder=['Интересно','Откликнулся'].sort((a,b)=>Number(count(b)>0)-Number(count(a)>0));
 const order=mobileLayout.matches?applicationOrder:['Интересно','Откликнулся'];
 $('#extra').innerHTML=(active.length?`<div class="pipeline">${order.map(status=>{
  const rows=active.filter(j=>statuses[j.id]===status),title=`${userStatusLabels[status]} <span>${rows.length}</span>`;
  return mobileLayout.matches&&!rows.length?`<details class="pipeline-column group-collapsed" data-group="${status}"><summary>${title}</summary><p class="group-empty">Пока нет вакансий с этим статусом.</p></details>`:`<section class="pipeline-column" data-group="${status}"><h2>${title}</h2>${rows.map(applicationCard).join('')||'<p class="group-empty">Пока нет вакансий с этим статусом.</p>'}</section>`;
 }).join('')}</div>`:emptyPanel('Пока нет запланированных откликов','В карточке вакансии отметь, планируешь ли откликнуться или уже отправил отклик'))+(ignored.length?`<details class="ignored-group"><summary>Не интересует · ${ignored.length}</summary>${ignored.map(applicationCard).join('')}</details>`:'')+`<p class="page-note">Статусы ты отмечаешь самостоятельно. WORKAholic не отправляет отклики.</p>`;
 bindBrowse();document.querySelectorAll('[data-application]').forEach(b=>b.onclick=()=>openJob(Number(b.dataset.application)));
 document.querySelectorAll('[data-application-status]').forEach(select=>select.onchange=()=>{
  const id=Number(select.dataset.applicationStatus),top=select.getBoundingClientRect().top;
  updateStatus(id,select.value);renderApplications();const next=$('#application-'+id);
  if(next){const details=next.closest('details');if(details)details.open=true;next.focus({preventScroll:true});window.scrollBy(0,next.getBoundingClientRect().top-top);}else $('#title').focus();
 });
}
$('#menu-toggle').onclick=()=>{$('#mobile-menu').showModal();$('#menu-toggle').setAttribute('aria-expanded','true');};
$('#menu-close').onclick=()=>$('#mobile-menu').close();
$('#mobile-menu').addEventListener('close',()=>{$('#menu-toggle').setAttribute('aria-expanded','false');if(menuDestination){const target=menuDestination;menuDestination=null;openCareer(target,true);}else $('#menu-toggle').focus();});
if(matchMedia('(max-width:900px)').matches)selected=undefined;
openCareer(location.hash.slice(1)||'jobs');
window.addEventListener('hashchange',()=>{const target=location.hash.slice(1)||'jobs';if(target!==page)openCareer(target,true);});

// Keep Tab in the modal, including when the browser would otherwise focus its chrome.
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('keydown',event=>{
 if(event.key!=='Tab')return;
 const controls=[...dialog.querySelectorAll('button,input,select,textarea,a[href],summary,[tabindex]')].filter(el=>!el.disabled&&el.tabIndex>=0&&el.getClientRects().length);
 const first=controls[0],last=controls.at(-1);
 if(!first){event.preventDefault();return;}
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
}));

// Responsive presentation only: criteria and vacancy decisions remain shared.
mobileLayout.addEventListener('change',()=>{
 if(page==='assistant'){$('#title').textContent=mobileLayout.matches?'Помощник по поиску работы':'Твой помощник в поиске работы';renderAssistant();}
 else if(page==='applications')renderApplications();
 if(['jobs','saved'].includes(page))syncFilterPanel();
});
matchMedia('(max-width:900px)').addEventListener('change',e=>{
 if(['jobs','saved'].includes(page)){selected=e.matches?undefined:rememberedSelection[page];render();}
});
