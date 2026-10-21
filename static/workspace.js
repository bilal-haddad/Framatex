'use strict';
// 0.9 — navigation et priorisation, sans décision automatique.
const PRIORITY_LABELS={urgent:'Échéance dépassée',high:'À examiner',normal:'À suivre'};
const AREA_TARGETS={documents:'.detail-layout',workflow:'.workflow-root',spec:'.spec-section',mail:'.mail-section'};

function priorityCard(item){
 const label=PRIORITY_LABELS[item.priority]||'À suivre';
 return `<button type="button" class="priority-item" data-workspace-launch="${e(item.launch_id)}" data-workspace-area="${e(item.area)}" data-workspace-folder="${e(item.folder||'')}" data-workspace-document="${e(item.document_id||'')}" data-workspace-version="${e(item.version_id||'')}"><span class="priority-dot ${e(item.priority)}"></span><span class="priority-content"><span class="priority-title">${e(item.title)}</span><span class="priority-description">${e(item.launch_name)} · ${e(item.description)}</span>${item.deadline?`<span class="priority-date">Échéance : ${e(item.deadline)}</span>`:''}</span><span class="priority-side"><span class="priority-label ${e(item.priority)}">${e(label)}</span>${icon('arrow')}</span></button>`;
}
function prioritySummary(report){
 if(!report)return '';
 return `<div class="priority-header"><div><div class="page-kicker">POINTS À TRAITER</div><h2>Mes actions</h2><p>Priorités fondées sur les règles et sur les échéances connues, sans score arbitraire.</p></div><button class="secondary tiny" id="workspace-all">Tout consulter ${icon('arrow')}</button></div><div class="priority-kpis"><div><strong>${report.counts.urgent}</strong><span>Échéances dépassées</span></div><div><strong>${report.counts.high}</strong><span>Vérifications</span></div><div><strong>${report.counts.normal}</strong><span>À suivre sous 7 jours</span></div></div><div class="priority-list">${report.items.length?report.items.slice(0,5).map(priorityCard).join(''):'<div class="priority-empty">Aucune action prioritaire visible pour vos habilitations.</div>'}</div>${report.truncated?'<p class="priority-hint">La liste complète est limitée aux 100 premières actions.</p>':''}`;
}
function renderPriorityWidget(){return `<section class="workspace-priorities" aria-label="Actions prioritaires">${prioritySummary(state.priorities)}</section>`}
function bindPriorityWidget(){
 app.querySelector('#workspace-all')?.addEventListener('click',()=>navigate('actions'));
 app.querySelectorAll('[data-workspace-launch]').forEach(button=>button.addEventListener('click',async()=>{
   const launchId=button.dataset.workspaceLaunch;
   const area=button.dataset.workspaceArea;
   try{if(typeof opsOpenTarget==='function')await opsOpenTarget({launch_id:launchId,area,
       folder:button.dataset.workspaceFolder||(area==='mail'?'rose':state.folder),
       document_id:button.dataset.workspaceDocument||null,version_id:button.dataset.workspaceVersion||null});
     else{await openLaunch(launchId,area==='mail'?'rose':state.folder);focusWorkspaceArea(area)}}catch(err){showErr(err)}
 }));
}
function focusWorkspaceArea(area){
 const target=app.querySelector(AREA_TARGETS[area]||'.detail-layout');
 target?.scrollIntoView?.({behavior:'smooth',block:'start'});
}
async function workspaceActions(){
 state.priorities=await api('/api/workspace/priorities');state.view='actions';
 const report=state.priorities;
 mount(`<div class="page-heading"><div><div class="page-kicker">SUIVI DES ACTIONS</div><h1 class="page-title">Mes actions<span style="color:#3e926e">.</span></h1><p class="page-lead">Les actions visibles respectent vos habilitations. Un dossier clôturé n'apparaît pas.</p></div></div><div class="workspace-priorities">${prioritySummary(report)}</div><div class="priority-toolbar"><label for="priority-filter">Afficher</label><select id="priority-filter"><option value="all">Toutes les priorités</option><option value="urgent">Échéances dépassées</option><option value="high">Vérifications à effectuer</option><option value="normal">À suivre</option></select><span>${report.total} action(s) détectée(s)</span></div><div id="workspace-full-list" class="priority-list"></div><p class="priority-hint">${e(report.method)} Les droits sur chaque document sont contrôlés par le serveur. Les alertes ne constituent pas une preuve d'erreur.</p>`,'Mes actions');
 const listing=app.querySelector('#workspace-full-list');
 const select=app.querySelector('#priority-filter');
 const draw=()=>{const data=report.items.filter(row=>select.value==='all'||row.priority===select.value);listing.innerHTML=data.length?data.map(priorityCard).join(''):'<div class="priority-empty">Aucune action dans ce filtre.</div>';bindPriorityWidget()};
 select.addEventListener('change',draw);draw();
 app.querySelector('#workspace-all')?.addEventListener('click',()=>app.querySelector('#priority-filter')?.focus());
}
let guideHistory=[];
function openGuideDrawer(){
 const existing=overlay.querySelector('.assistant-drawer');
 if(existing){closeModal();return;}
 const current=state.detail?.id||null;
 overlay.innerHTML=`<div class="assistant-overlay"><button class="assistant-backdrop" aria-label="Fermer l’assistant"></button><aside class="assistant-drawer" role="dialog" aria-modal="true" aria-labelledby="assistant-title"><header class="assistant-drawer-head"><div class="assistant-drawer-symbol">${icon('layers')}</div><div><span>VOTRE ASSISTANT DOCUMENTAIRE</span><h2 id="assistant-title">Framatex Assist <i class="chat-online"></i></h2></div><button type="button" class="assistant-close" aria-label="Fermer">${icon('x')}</button></header><div class="assistant-conversation" id="assistant-conversation" aria-live="polite"><div class="assistant-day-label">SESSION ACTUELLE</div><div class="assistant-msg assistant-msg-bot"><span class="assistant-msg-avatar">${icon('layers')}</span><div class="assistant-bubble"><strong>Bonjour !</strong><p>Je peux vous guider dans Framatex, retrouver une rubrique ou expliquer une procédure. Que souhaitez-vous faire ?</p></div></div></div><div class="assistant-suggestion-wrap"><span>QUESTIONS FRÉQUENTES</span><div class="assistant-suggestions"><button type="button" data-guide-example="Où déposer une facture ?">Déposer une facture ${icon('arrow')}</button><button type="button" data-guide-example="Voir les priorités">Mes priorités ${icon('arrow')}</button><button type="button" data-guide-example="Comment vérifier une exigence client ?">Exigences client ${icon('arrow')}</button></div></div><form id="guide-form" class="assistant-composer"><label for="guide-question">Votre question</label><div class="assistant-input-line"><input id="guide-question" type="text" maxlength="500" minlength="2" required placeholder="Écrivez votre question…" autocomplete="off"/><button type="submit" aria-label="Envoyer la question">${icon('arrow')}</button></div><small>Réponses basées sur les procédures locales, sans IA générative.</small></form></aside></div>`;
 const wrapper=overlay.querySelector('.assistant-overlay');
 const close=()=>{overlay.innerHTML='';document.removeEventListener('keydown',onKey)};
 const onKey=(event)=>{if(event.key==='Escape')close()};
 document.addEventListener('keydown',onKey);
 wrapper.querySelector('.assistant-close').addEventListener('click',close);
 wrapper.querySelector('.assistant-backdrop').addEventListener('click',close);
 const conversation=wrapper.querySelector('#assistant-conversation');
 const addMessage=(kind,content)=>{
   const row=document.createElement('div');row.className='assistant-msg assistant-msg-'+kind;
   if(kind==='bot'){const avatar=document.createElement('span');avatar.className='assistant-msg-avatar';avatar.innerHTML=icon('layers');row.appendChild(avatar)}
   const bubble=document.createElement('div');bubble.className='assistant-bubble';
   bubble.innerHTML=content;row.appendChild(bubble);conversation.appendChild(row);conversation.scrollTop=conversation.scrollHeight;
   return row;
 };
 const ask=async(question)=>{
   const q=question.trim();if(q.length<2)return;
   addMessage('user',`<p>${e(q)}</p>`);
   const waiting=addMessage('bot','<p>Je recherche la procédure correspondante…</p>');
   const form=wrapper.querySelector('#guide-form');const field=wrapper.querySelector('#guide-question');
   field.disabled=true;form.querySelector('button[type=submit]').disabled=true;
   try{
     const response=await api('/api/assistant/guide',{method:'POST',body:JSON.stringify({question:q,launch_id:current})});
     const bubble=waiting.querySelector('.assistant-bubble');
     bubble.innerHTML=`<strong>${e(response.title)}</strong><p>${e(response.answer)}</p><small>${e(response.source)}</small>${response.destination?`<button class="assistant-followup" type="button">Ouvrir la rubrique ${icon('arrow')}</button>`:''}`;
     bubble.querySelector('.assistant-followup')?.addEventListener('click',async()=>{try{close();if(response.destination==='detail'&&response.launch_id){await openLaunch(response.launch_id,response.folder||state.folder);focusWorkspaceArea(response.area)}else await navigate(response.destination)}catch(err){showErr(err)}});
   }catch(err){waiting.querySelector('.assistant-bubble').innerHTML=`<p class="assistant-error">${e(err.message)}</p>`}
   finally{field.disabled=false;form.querySelector('button[type=submit]').disabled=false;conversation.scrollTop=conversation.scrollHeight;field.focus()}
 };
 wrapper.querySelectorAll('[data-guide-example]').forEach(button=>button.addEventListener('click',()=>ask(button.dataset.guideExample)));
 wrapper.querySelector('#guide-form').addEventListener('submit',event=>{event.preventDefault();const field=wrapper.querySelector('#guide-question');const question=field.value;field.value='';ask(question)});
 wrapper.querySelector('#guide-question').focus();
}
