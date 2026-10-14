const jobs=[
{id:1,company:'Линия',mark:'л',title:'Младший координатор IT-проектов',salary:'от 65 000 ₽',type:'match',mode:'Гибрид',place:'Москва',color:'#ece8f5',why:['Коммерческий опыт не требуется: есть обучение и наставник.','Координация задач и документация — основа роли.','Фиксированный график без ночных дежурств.'],duties:'Помогать команде планировать задачи, вести встречи и поддерживать проектную документацию.',question:'Уточни, сколько дней в неделю нужно быть в офисе.'},
{id:2,company:'Маяк Digital',mark:'м',title:'Ассистент менеджера проектов',salary:'55 000 – 75 000 ₽',type:'match',mode:'Удалённо',place:'Россия',color:'#e9eedc',why:['Рассматривают кандидатов без опыта.','Есть понятные задачи и поддержка руководителя.','Указанная зарплата соответствует условиям поиска.'],duties:'Следить за сроками, собирать статусы команды и готовить короткие отчёты.',question:'Уточни размер фиксированной части зарплаты.'},
{id:3,company:'Орбита',mark:'о',title:'Специалист по внедрению сервисов',salary:'Зарплата не указана',type:'review',mode:'Удалённо',place:'Россия',color:'#e5edf5',why:['Задачи связаны с внедрением и сопровождением.','Нет однозначного требования коммерческого опыта.'],duties:'Настраивать сервис для новых клиентов, проводить вводные встречи и собирать обратную связь.',question:'Нужно уточнить зарплату и обязательность предыдущего опыта.'},
{id:4,company:'Точка роста',mark:'т',title:'Специалист поддержки пользователей',salary:'от 50 000 ₽',type:'match',mode:'Удалённо',place:'Россия',why:['Предусмотрено обучение продукту.','Дневной график и фиксированная оплата.'],duties:'Разбирать обращения пользователей и пополнять базу знаний.',question:'Уточни долю телефонных обращений.'},
{id:5,company:'Контур идей',mark:'к',title:'Администратор проектного офиса',salary:'от 60 000 ₽',type:'review',mode:'Гибрид',place:'Москва',why:['Подходят задачи по организации проектной работы.','Требования к стажу сформулированы неоднозначно.'],duties:'Вести реестр задач и помогать руководителям с подготовкой встреч.',question:'Принимают ли кандидатов без коммерческого опыта?'},
{id:6,company:'Север Studio',mark:'с',title:'Руководитель проектов / Middle PM',salary:'от 150 000 ₽',type:'reject',mode:'Офис',place:'Москва',why:['Обязательно от трёх лет коммерческого опыта.','Самостоятельное управление бюджетом и командой.'],duties:'Вести несколько проектов и отвечать за финансовый результат.',question:'По указанным требованиям это не стартовая позиция.'}
];
const $=s=>document.querySelector(s);const labels={match:'Подходит',review:'Нужно уточнить',reject:'Не подходит'};let filter='all',selected=1,page='jobs',running=false,saved=new Set(),statuses={},newOnly=false;
function toast(text,undo=null){
 const box=$('#toast'); box.replaceChildren();
 const message=document.createElement('span');message.textContent=text;box.append(message);
 if(undo){const button=document.createElement('button');button.textContent='Отменить';button.onclick=undo;box.append(button);}
 box.classList.add('visible');clearTimeout(toast.timer);
 // An actionable notification remains available until used or superseded.
 if(!undo)toast.timer=setTimeout(()=>box.classList.remove('visible'),4500);
}

// Categorize existing example statements, without creating new conclusions.
for (const id of [3, 5]) {
 const example = jobs.find(j => j.id === id);
 example.matches = example.why.slice(0, 1);
 example.unknowns = example.why.slice(1);
}
