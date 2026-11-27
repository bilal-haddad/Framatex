'use strict';
// 0.13 : circuits de validation configurables et boîte de notifications internes.
const APPROVAL_STATUSES={pending:'En attente',approved:'Approuvé',rejected:'Refusé',changes_requested:'Modifications demandées',stale:'Version remplacée'};

function renderApprovals(){
 const report=state.approvalOverview;
 if(!report)return '';
 const items=report.items.filter(x=>x.template||x.run||x.previous.length);
 return `<section class="approval-section" id="approval-workspace"><div class="section-heading"><div><h2>Circuits de validation</h2><small>Décisions par étape et par version · approbations non transférables</small></div></div><div class="approval-grid">${items.length?items.map(x=>`<article class="panel approval-item"><div class="approval-item-head"><div><strong>${e(x.document_title)}</strong><p>${e(x.folder)} · Version ${x.version}${x.template?` · ${e(x.template.name)}`:''}</p></div>${x.run?`<span class="tag ${x.run.status==='approved'?'green':x.run.status==='stale'||x.run.status==='rejected'?'orange':'blue'}">${e(APPROVAL_STATUSES[x.run.status]||x.run.status)}</span>`:''}</div>${x.run?`<div class="approval-steps">${x.run.stages.map(s=>`<div class="approval-step ${s.decision?'complete':s.position===x.run.current_position&&x.run.status==='pending'?'current':''}"><span class="approval-step-number">${s.position}</span><div><strong>${e(s.name)}</strong><small>${e(s.role_name)}${s.decision?' · '+e(APPROVAL_STATUSES[s.decision]||s.decision):''}</small>${s.comment?`<small>${e(s.comment)}</small>`:''}</div></div>`).join('')}</div>${x.run.can_decide?`<button class="primary tiny" data-approval-decide="${e(x.run.id)}">${icon('check')} Décider de l’étape</button>`:''}`:''}${x.can_start?`<button class="secondary tiny" data-approval-start="${e(x.document_id)}">${icon('plus')} Soumettre la version</button>`:''}${x.previous.length?`<p class="approval-history">${x.previous.length} ancien(s) circuit(s) conservé(s), sans validation de la version actuelle.</p>`:''}</article>`).join(''):'<div class="panel approval-empty">Aucun circuit associé aux documents visibles. Un administrateur peut en configurer par rubrique et type documentaire.</div>'}</div></section>`;
}
function bindApprovals(){
 app.querySelectorAll('[data-approval-start]').forEach(b=>b.addEventListener('click',async()=>{
   try{await api(`/api/documents/${b.dataset.approvalStart}/approval-runs`,{method:'POST'});toast('Circuit démarré');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}
 }));
 app.querySelectorAll('[data-approval-decide]').forEach(b=>b.addEventListener('click',()=>{
   const run=state.approvalOverview.items.map(x=>x.run).find(r=>r?.id===b.dataset.approvalDecide);if(!run)return;
   const step=run.stages.find(x=>x.position===run.current_position);
   modal('Décision sur une étape de validation',`<p class="modal-desc">${e(run.document_title)} · version ${run.version}. ${e(step?.name||'Étape')} : le résultat concerne uniquement cette version.</p><form id="approval-decision-form"><div class="field"><label>Décision</label><select id="approval-choice"><option value="approved">Approuver</option><option value="changes_requested">Demander des corrections</option><option value="rejected">Refuser</option></select></div><div class="field"><label>Commentaire motivé pour un refus ou une correction</label><textarea id="approval-comment" maxlength="1800" rows="4"></textarea></div><div class="modal-actions"><button type="button" class="secondary" id="approval-cancel">Annuler</button><button class="primary" type="submit">Enregistrer la décision</button></div></form>`);
   overlay.querySelector('#approval-cancel').onclick=closeModal;
   overlay.querySelector('#approval-decision-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/approval-runs/${run.id}/decisions`,{method:'POST',body:JSON.stringify({decision:val('approval-choice'),comment:val('approval-comment')})});closeModal();toast('Décision enregistrée');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
 }));
}
async function approvalAdminPanel(){
 const [templates,roles]=await Promise.all([api('/api/admin/approval-templates'),api('/api/admin/roles')]);
 state.approvalTemplates=templates;state.approvalRoles=roles;
 return `<div class="section-heading"><h2>Circuits de validation</h2><button class="primary tiny" id="approval-new-template">${icon('plus')} Nouveau circuit</button></div><p class="completion-admin-lead">Définissez les valideurs par rôle et leur ordre. Une approbation n'est jamais reconduite sur une nouvelle version. L’auteur d'un dépôt ne peut pas valider son propre document.</p><div class="approval-admin-list">${templates.length?templates.map(t=>`<div class="panel approval-admin-item"><div><strong>${e(t.name)}</strong><p>${e(t.folder_slug)} · ${e(t.document_type)} · ${t.stages.map(s=>e(s.name)+' ('+e(s.role_name)+')').join(' → ')}</p></div><button class="secondary tiny" data-approval-toggle="${e(t.id)}" data-approval-active="${t.active?'false':'true'}">${t.active?'Désactiver':'Réactiver'}</button></div>`).join(''):'<p class="muted">Aucun circuit créé.</p>'}</div>`;
}
function bindApprovalAdmin(){
 app.querySelector('#approval-new-template')?.addEventListener('click',()=>{
   const roles=state.approvalRoles||[];
   const ropts=roles.map(r=>`<option value="${e(r.id)}">${e(r.name)}</option>`).join('');
   const one=(n)=>`<div class="approval-config-stage"><label>Étape ${n}</label><div class="two-fields"><div class="field"><input class="approval-stage-name" placeholder="Ex. Contrôle technique" minlength="3" maxlength="140" required></div><div class="field"><select class="approval-stage-role">${ropts}</select></div></div></div>`;
   modal('Créer un circuit de validation',`<form id="approval-template-form"><div class="field"><label>Nom du circuit</label><input id="at-name" required minlength="3" maxlength="140" placeholder="Validation d'une fiche d’emploi"></div><div class="two-fields"><div class="field"><label>Sous-dossier</label><select id="at-folder"><option value="jaune">Jaune</option><option value="rose">Rose</option><option value="bleu">Bleu</option><option value="vert">Vert</option></select></div><div class="field"><label>Type documentaire exact</label><input id="at-type" required minlength="2" maxlength="100" placeholder="Fiche d’emploi"></div></div><div id="approval-stages-input">${one(1)}</div><button type="button" class="secondary tiny" id="approval-add-stage">${icon('plus')} Ajouter une étape</button><p class="permission-lock">Les rôles sélectionnés doivent disposer des permissions de lecture et de validation dans le sous-dossier concerné.</p><div class="modal-actions"><button type="button" class="secondary" id="at-cancel">Annuler</button><button class="primary" type="submit">Créer</button></div></form>`,true);
   overlay.querySelector('#at-cancel').onclick=closeModal;
   overlay.querySelector('#approval-add-stage').onclick=()=>{const el=overlay.querySelector('#approval-stages-input');const n=el.children.length+1;if(n>6)return toast('Maximum six étapes');el.insertAdjacentHTML('beforeend',one(n))};
   overlay.querySelector('#approval-template-form').onsubmit=async ev=>{ev.preventDefault();const stages=[...overlay.querySelectorAll('.approval-config-stage')].map(el=>({name:el.querySelector('.approval-stage-name').value.trim(),reviewer_role_id:el.querySelector('.approval-stage-role').value}));try{await api('/api/admin/approval-templates',{method:'POST',body:JSON.stringify({name:val('at-name'),folder_slug:val('at-folder'),document_type:val('at-type'),stages})});closeModal();toast('Circuit enregistré');await admin()}catch(err){showErr(err)}};
 });
 app.querySelectorAll('[data-approval-toggle]').forEach(b=>b.addEventListener('click',async()=>{try{await api(`/api/admin/approval-templates/${b.dataset.approvalToggle}`,{method:'PATCH',body:JSON.stringify({active:b.dataset.approvalActive==='true'})});toast('Circuit mis à jour');await admin()}catch(err){showErr(err)}}));
}
function notificationItem(n){
 const place=[n.order_ref||n.launch_name,n.folder].filter(Boolean).join(' · ');
 return `<article class="notification-item ${n.read_at?'':'unread'}" data-priority="${e(n.priority)}"><div><div class="notification-meta"><span class="tag ${n.priority==='urgent'||n.priority==='high'?'orange':'blue'}">${e(n.priority)}</span>${n.action_required?'<span class="tag orange">Action en attente</span>':n.lifecycle==='resolved'?'<span class="tag green">Résolue</span>':''}</div><strong>${e(n.title)}</strong><p>${e(n.message)}</p><small>${place?e(place)+' · ':''}${niceDate(n.updated_at||n.created_at)} · ${n.read_at?'Lue':'Non lue'}</small></div><div class="notification-actions">${n.action_label||n.target_kind?`<button class="secondary tiny" data-notification-open="${e(n.id)}">${e(n.action_label||'Ouvrir')}</button>`:''}${!n.read_at?`<button class="link" data-notification-read="${e(n.id)}">Marquer comme lue</button>`:''}${!n.action_required&&n.lifecycle!=='archived'?`<button class="link" data-notification-archive="${e(n.id)}">Archiver</button>`:''}</div></article>`
}
async function openNotification(n){
 if(!n.read_at)await api(`/api/notifications/${n.id}/read`,{method:'POST'});
 if(n.target_kind==='client_order_request')return operationsClientRequest(n.target_id);
 if(n.target_kind==='client_document_request'&&n.metadata?.order_request_id)return operationsClientRequest(n.metadata.order_request_id);
 if(n.target_kind==='client_account')return navigate('clients');
 if(n.launch_id)return openLaunch(n.launch_id,n.folder||null);
 return notificationsPage();
}
async function notificationsPage(){
 state.view='notifications';state.notifications=await api('/api/notifications');const d=state.notifications;
 mount(`<div class="page-heading"><div><div class="page-kicker">CENTRE DE NOTIFICATIONS</div><h1 class="page-title">Notifications<span style="color:#3e926e">.</span></h1><p class="page-lead">Lire une notification ne termine pas l’action métier. Les droits sont revérifiés à chaque consultation.</p></div></div><section class="panel notifications-panel"><div class="section-heading"><h2>${d.unread} non lue(s) · ${d.actions} action(s) à traiter</h2><small>${d.visible} active(s) · ${d.total} dans l’historique</small></div>${d.items.length?d.items.map(notificationItem).join(''):'<div class="empty">Aucune notification pour vos habilitations actuelles.</div>'}</section>`,'Notifications');
 app.querySelectorAll('[data-notification-read]').forEach(b=>b.onclick=async()=>{try{await api(`/api/notifications/${b.dataset.notificationRead}/read`,{method:'POST'});await notificationsPage()}catch(err){showErr(err)}});
 app.querySelectorAll('[data-notification-open]').forEach(b=>b.onclick=async()=>{try{await openNotification(d.items.find(n=>n.id===b.dataset.notificationOpen))}catch(err){showErr(err)}});
 app.querySelectorAll('[data-notification-archive]').forEach(b=>b.onclick=async()=>{try{await api(`/api/notifications/${b.dataset.notificationArchive}/archive`,{method:'POST'});await notificationsPage()}catch(err){showErr(err)}});
}
