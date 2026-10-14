/* Presentation only. jobs is the existing demo collection; no backend requests. */
const userStatusLabels = {'Не просмотрено':'Не просмотрена','Интересно':'Планирую откликнуться','Откликнулся':'Откликнулся','Не подходит':'Не интересует'};
let listState = 'ready', listScroll=0, savedFiltersOpen=false;
const rememberedSelection={};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const assessment = job => labels[job.type] ? job.type : 'unrated';
function baseRows(){return page==='saved'?jobs.filter(j=>saved.has(j.id)):currentJobs();}
function visibleRows(){const q=$('#query').value.trim().toLocaleLowerCase('ru');return baseRows().filter(j=>(filter==='all'||assessment(j)===filter)&&`${j.title||''} ${j.company||''}`.toLocaleLowerCase('ru').includes(q));}
function reviewSections(j){
 // Preserve source wording. Ambiguous review facts are not asserted as confirmed matches.
 const notes=Array.isArray(j.why)?j.why.filter(Boolean):[];
 return {matches:j.matches||(assessment(j)==='match'?notes:[]),unknowns:j.unknowns||(assessment(j)==='review'?notes:[]),risks:assessment(j)==='reject'?notes:[],questions:assessment(j)!=='reject'&&j.question?[j.question]:[]};
}
function render(){
 const base=baseRows(),effectiveState=page==='saved'?'ready':listState,rows=effectiveState==='ready'?visibleRows():[];
 const emptySaved=page==='saved'&&!base.length;
 syncFilterPanel();$('#list-freshness').hidden=!criteriaChanged()||!base.length;
 $('#saved-empty').hidden=!emptySaved;$('#list-workspace').hidden=emptySaved;
 if(emptySaved){$('.subtitle').textContent='Твои сохранённые предложения';selected=undefined;$('#list').replaceChildren();$('#detail').replaceChildren();$('.workarea').classList.remove('has-selection');$('#saved-empty').innerHTML=emptyPanel('Здесь будут сохранённые вакансии','Сохраняй интересные предложения, чтобы вернуться к ним позже');bindBrowse();return;}
 $('#list').setAttribute('aria-busy',String(effectiveState==='loading'));
 $('#count').textContent=`Показано ${rows.length} из ${base.length}`;
 document.querySelectorAll('[data-filter]').forEach(b=>{const key=b.dataset.filter;const count=key==='all'?base.length:base.filter(j=>assessment(j)===key).length;b.innerHTML=`${esc({all:'Все',match:'Подходящие',review:'Нужно уточнить',reject:'Не подходят',unrated:'Не оценено'}[key])} <span>${count}</span>`;b.classList.toggle('selected',filter===key);b.setAttribute('aria-pressed',String(filter===key));});
 const totals=[base.length,base.filter(j=>assessment(j)==='match').length,base.filter(j=>assessment(j)==='review').length];
 $('.subtitle').textContent=`${totals[0]} ${ruCount(totals[0],'вакансия','вакансии','вакансий')} · подходят: ${totals[1]} · нужно уточнить: ${totals[2]}`;
 if(!rows.some(j=>j.id===selected)) selected=matchMedia('(min-width:901px)').matches?rows[0]?.id:undefined;
 if(selected!==undefined)rememberedSelection[page]=selected;
 document.querySelector('.workarea').classList.toggle('has-selection',selected!==undefined);
 if(!rows.length){
  const states={loading:['Загружаем список','Демонстрация состояния загрузки.'],error:['Не удалось загрузить вакансии','Список не получен. Сохранённые отметки не изменены.'],empty:['Поиск завершён без результатов','Попробуй изменить критерии поиска.'],unavailable:['Поиск пока недоступен','Подборка появится после подключения поиска.'], 'not-started':['Ты ещё не запускал поиск','Запуск будет доступен после подключения поиска.']};
  const [title,description]=states[effectiveState]||(base.length?['По этим условиям ничего не найдено','Попробуй другой запрос или сбрось фильтры.']:['В избранном пока пусто','Сохрани интересное предложение в карточке вакансии.']);
  $('#list').innerHTML=`<div class="empty" role="status"><h3>${title}</h3><p>${description}</p>${effectiveState==='error'?'<button id="retry" class="secondary">Вернуть демонстрационный список</button>':effectiveState==='ready'&&base.length?'<button id="reset-filters" class="secondary">Сбросить фильтры</button>':''}</div>`;
  if($('#retry'))$('#retry').onclick=()=>{listState='ready';running=false;$('#demo-state').value='paused';$('#status').textContent='На паузе · пример';render();($('#list .job')||$('#title')).focus()};if($('#reset-filters'))$('#reset-filters').onclick=()=>{filter='all';$('#query').value='';render();$('#query').focus()};
 }else $('#list').innerHTML=rows.map(j=>{
   const type=assessment(j);const reason=type==='review'?j.question:(j.why||[])[0];
   return `<button class="job ${j.id===selected?'selected':''}" data-id="${j.id}" aria-pressed="${j.id===selected}" aria-controls="detail"><span class="job-top"><span class="company">${esc(j.company||'Компания не указана')}<small>${esc(j.place||'Локация не указана')}</small></span><span class="badge ${type}">${esc(labels[type]||'Не оценено')}</span></span><span class="job-name">${esc(j.title||'Без названия')}</span><span class="salary">${esc(j.salary||'Зарплата не указана')}</span><span class="tags"><span>${esc(j.mode||'Формат не указан')}</span>${j.experience?`<span>${esc(j.experience)}</span>`:''}</span>${reason?`<span class="card-reason">${esc(reason)}</span>`:''}<span class="job-bottom"><span>${saved.has(j.id)?'В избранном · ':''}${esc(userStatusLabels[statuses[j.id]]||'Не просмотрена')}</span><b>Подробнее →</b></span></button>`;
 }).join('');
 document.querySelectorAll('.job').forEach(b=>b.onclick=()=>selectVacancy(Number(b.dataset.id),true));
 renderDetail();
}
function selectVacancy(id,focus=false){if(focus)listScroll=window.scrollY;selected=id;render();if(focus&&matchMedia('(max-width: 900px)').matches){$('#detail').scrollIntoView({block:'start'});$('#detail-heading')?.focus({preventScroll:true});}else if(focus)document.querySelector(`[data-id="${id}"]`)?.focus({preventScroll:true});}
function renderDetail(){
 const j=visibleRows().find(j=>j.id===selected);
 if(!j||(page!=='saved'&&listState!=='ready')){$('#detail').innerHTML='<div class="empty"><h2>Выбери вакансию</h2><p>Здесь будут условия, объяснение оценки и твои действия.</p></div>';return;}
 const type=assessment(j),analysis=reviewSections(j);
 const sections=[['Что совпадает',analysis.matches,'positive'],['Что стоит уточнить',analysis.unknowns,'uncertain'],['На что обратить внимание',analysis.risks,'risk']].filter(([,values])=>values.length);
 $('#detail').innerHTML=`<button class="back-list secondary">← К списку вакансий</button>${freshnessNote(true)}<div class="detail-top"><span class="analysis-label">Оценка соответствия</span><span class="badge ${type}">${esc(labels[type]||'Не оценено')}</span></div><h2 id="detail-heading" tabindex="-1">${esc(j.title||'Без названия')}</h2><div class="detail-company">${esc(j.company||'Компания не указана')} · ${esc(j.place||'Локация не указана')}</div><strong class="detail-salary">${esc(j.salary||'Зарплата не указана')}</strong><div class="tags"><span>${esc(j.mode||'Формат не указан')}</span><span>${esc(j.experience||'Требования к опыту — в разборе')}</span></div><div class="detail-actions">${safeOriginalUrl(j.url)?`<a class="primary vacancy" href="${esc(safeOriginalUrl(j.url))}" target="_blank" rel="noopener noreferrer">Открыть вакансию ↗</a>`:''}<button class="secondary save" aria-pressed="${saved.has(j.id)}" aria-label="${saved.has(j.id)?'Убрать из избранного':'Сохранить в избранное'}">${saved.has(j.id)?'Сохранено':'Сохранить'}</button></div>${safeOriginalUrl(j.url)?'':'<p class="source-note">Для примера ссылка не добавлена.</p>'}<div class="personal-status"><label for="personal-status">Мой статус <small>Твои действия, не оценка AI</small></label><select id="personal-status" class="state-select">${statusOptions(j.id)}</select></div><section class="analysis"><h3>Разбор соответствия </h3>${sections.length?sections.map(([title,items,kind])=>`<section class="analysis-section ${kind}"><h4>${title}</h4><ul>${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section>`).join(''):'<p class="analysis-empty">Анализ пока отсутствует. Соответствие вакансии не определено.</p>'}</section>${j.duties?`<section class="description-section"><h3>Чем предстоит заниматься</h3><p>${esc(j.duties)}</p></section>`:''}${analysis.questions.length?`<section class="questions-section"><h3>Перед откликом</h3><p>${esc(analysis.questions.join('\n'))}</p><button class="secondary copy">Скопировать вопросы</button><textarea class="copy-fallback" aria-label="Вопросы для ручного копирования" hidden readonly></textarea></section>`:''}`;
 $('.back-list').onclick=()=>{const old=selected;selected=undefined;render();document.querySelector(`[data-id="${old}"]`)?.focus({preventScroll:true});window.scrollTo(0,listScroll);};
 $('.save').onclick=()=>{if(page==='saved'&&saved.has(j.id)&&!matchMedia('(max-width:900px)').matches){const rows=visibleRows(),index=rows.findIndex(row=>row.id===j.id);selected=(rows[index+1]||rows[index-1])?.id;}updateFavorite(j.id);render();if(selected!==undefined)$('.save')?.focus({preventScroll:true});else {($('#list .job')||$('#saved-empty [data-browse]')||$('#title')).focus({preventScroll:true});if(page==='saved')window.scrollTo(0,listScroll);}};
 $('.state-select').onchange=e=>{updateStatus(j.id,e.target.value);render();$('.state-select')?.focus({preventScroll:true});};
 if($('.copy'))$('.copy').onclick=async()=>{try{await navigator.clipboard.writeText(analysis.questions.join('\n'));toast('Вопросы скопированы');}catch{const field=$('.copy-fallback');field.hidden=false;field.value=analysis.questions.join('\n');field.focus();field.select();toast('Не удалось скопировать автоматически. Текст выделен для копирования.');}};
}
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;render();b.focus()});$('#query').oninput=render;
$('#demo-state').onchange=e=>{
 const value=e.target.value;listState=['loading','error','empty','unavailable','not-started'].includes(value)?value:'ready';running=value==='processing';
 $('#status').textContent={ready:'Подборка примеров',unavailable:'Поиск недоступен · пример','not-started':'Поиск не запускался · пример',paused:'На паузе · пример',processing:'Длительная обработка · пример',complete:'Завершено · пример',loading:'Загрузка · пример',error:'Ошибка · пример',empty:'Пустой список · пример'}[value];render();updateNavigation();
};
$('#demo-resume').onclick=()=>{newOnly=$('#resume').selectedIndex===1;listState='ready';running=true;$('#status').textContent='Продолжение · пример';render();updateNavigation();};
$('#batch').onclick=()=>$('#dialog').showModal();document.querySelectorAll('.close,.close-dialog').forEach(b=>b.onclick=()=>$('#dialog').close());

function syncFilterPanel(){
 const compact=page==='saved'&&baseRows().length>0&&baseRows().length<=3&&matchMedia('(max-width:800px)').matches;
 const active=filter!=='all'||Boolean($('#query').value.trim());
 $('#filter-toggle-row').hidden=!compact;
 $('#filter-panel').hidden=compact&&!savedFiltersOpen;
 $('#filter-toggle').textContent='Поиск и фильтры'+(active?' · Есть условия':'');
 $('#filter-toggle').setAttribute('aria-expanded',String(!$('#filter-panel').hidden));
 $('#clear-conditions').hidden=!active;
}
$('#filter-toggle').onclick=()=>{savedFiltersOpen=!savedFiltersOpen;syncFilterPanel();};
$('#clear-conditions').onclick=()=>{filter='all';$('#query').value='';render();$('#filter-toggle').focus();};
