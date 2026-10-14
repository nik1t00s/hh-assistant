// Shared demo state, in memory only. No real profile, persistence or network access.
const criteria={direction:'Координация IT-проектов',experience:'Без коммерческого опыта',mode:'Удалённо и гибрид',calls:'Не уточнено'};
const criterionLabels={direction:'Направление и роль',experience:'Опыт',mode:'Формат работы',calls:'Телефонное общение'};
function ruCount(n,one,few,many){return {one,few,many,other:many}[new Intl.PluralRules('ru').select(n)];}
function currentJobs(){return ['loading','error','empty','not-started','unavailable'].includes(listState)?[]:jobs.filter(j=>!newOnly||j.id===4);}
function jobCounts(rows=currentJobs()){return {total:rows.length,match:rows.filter(j=>j.type==='match').length,review:rows.filter(j=>j.type==='review').length};}
function statusOptions(id){return Object.entries(userStatusLabels).map(([key,label])=>`<option value="${esc(key)}" ${(statuses[id]||'Не просмотрено')===key?'selected':''}>${esc(label)}</option>`).join('');}
function updateStatus(id,value){if(!jobs.some(j=>j.id===id)||!Object.hasOwn(userStatusLabels,value))return;statuses[id]=value;toast('Статус обновлён');}
function updateFavorite(id){
 if(!jobs.some(j=>j.id===id))return;const removing=saved.has(id);
 if(removing)saved.delete(id);else saved.add(id);
 toast(removing?'Убрано из избранного':'Сохранено в избранное',removing?()=>{saved.add(id);refreshCurrentPage();toast('Вакансия возвращена в избранное');(document.querySelector(`[data-id="${id}"]`)||$('#title')).focus({preventScroll:true});}:null);
}
function safeOriginalUrl(value){try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)?url.href:null;}catch{return null;}}
function criteriaMarkup(){return Object.entries(criterionLabels).map(([key,label])=>`<div class="profile-line"><span>${label}</span><strong>${esc(criteria[key]||'Не указано')}</strong></div>`).join('');}
function emptyPanel(title,description,action='Посмотреть вакансии'){return `<section class="empty-state"><span class="empty-symbol" aria-hidden="true">${icon(page)}</span><h2>${esc(title)}</h2><p>${esc(description)}</p><button class="primary" data-browse>${esc(action)}</button></section>`;}
function bindBrowse(){document.querySelectorAll('[data-browse]').forEach(b=>b.onclick=()=>{filter='all';$('#query').value='';selected=undefined;openCareer('jobs',true);});}

const evaluatedCriteria={...criteria};
function criteriaChanged(){return Object.keys(criteria).some(key=>criteria[key]!==evaluatedCriteria[key]);}
function criteriaNotice(){return criteriaChanged()?'Критерии изменены. Оценки текущей подборки ещё не обновлены':'Оценки примеров не пересчитываются при изменении критериев.';}
function icon(name){
 const paths={assistant:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/>',jobs:'<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12h18M10 12v3h4v-3"/>',applications:'<path d="m3 11 18-8-8 18-2-8-8-2Zm8 2L21 3"/>',profile:'<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',saved:'<path d="M20 5c-3-3-6-1-8 1-2-2-5-4-8-1-4 4 2 10 8 15 6-5 12-11 8-15Z"/>',history:'<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v5l3 2"/>'};
 return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths[name]||paths.jobs}</svg>`;
}

function freshnessNote(detail=false){return criteriaChanged()?`<p class="freshness-note">${detail?'Критерии изменены. Этот разбор ещё не обновлён':'Оценки по предыдущим критериям'}</p>`:'';}
