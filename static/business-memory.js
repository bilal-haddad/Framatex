'use strict';
// Navigation de la mémoire interne : toutes les données viennent des routes /api/workspace.
const BM_CATEGORY={incident:'Incident',retard:'Retard de livraison',qualite:'Non-conformité qualité',documentaire:'Problème documentaire',modification:'Modification de commande',communication:'Problème de communication',retour:'Retour positif',recommandation:'Recommandation',autre:'Autre'};
const BM_IMPORTANCE={information:'Information',surveiller:'À surveiller',important:'Important',critique:'Critique'};
const BM_STATUS={open:'Ouvert',resolved:'Résolu'};
const BM_TYPE={client:'Client',fournisseur:'Fournisseur',atelier:'Atelier'};
const BM_FOLDER={jaune:'Sous-dossier jaune',rose:'Sous-dossier rose',bleu:'Sous-dossier bleu',vert:'Sous-dossier vert'};
const bmDay=value=>value?opsDay(value):'—';
const bmOptions=(items,empty)=>`<option value="">${empty}</option>${items.map(([key,label])=>`<option value="${e(key)}">${e(label)}</option>`).join('')}`;

function bmBindSearch(root,{type,selection,showCreate=true,scope=()=>({})}){
 const input=root.querySelector('[data-bm-search]'),results=root.querySelector('[data-bm-results]');
 let timer=0,token=0;
 const lookup=async()=>{
  const t=++token,query=input.value.trim();
  selection(null);
  if(query.length<2){results.innerHTML='';return}
  const rows=await api('/api/workspace/partners?'+new URLSearchParams({q:query,party_type:type(),...scope()}));
  if(t!==token||!results.isConnected)return;
  results.innerHTML=rows.map(row=>`<button class="bm-choice" type="button" data-bm-id="${e(row.id)}"><strong>${e(row.name)}</strong><small>${e(BM_TYPE[row.party_type])} · ${row.match==='exact'?'Correspondance exacte':'Vérifier la correspondance'}</small></button>`).join('')
   +(showCreate?`<button class="bm-choice bm-new" type="button" data-bm-new>+ Créer « ${e(query)} » après vérification</button>`:'');
  results.querySelectorAll('[data-bm-id]').forEach(button=>button.onclick=()=>{const row=rows.find(item=>item.id===button.dataset.bmId);input.value=row.name;results.innerHTML='';selection(row)});
  results.querySelector('[data-bm-new]')?.addEventListener('click',async()=>{
   if(rows.some(row=>row.match==='exact')){toast('Sélectionnez la fiche existante.');return}
   if(rows.length&&!window.confirm('Des noms proches existent. Confirmez qu’il s’agit d’une entreprise distincte.'))return;
   try{const row=await api('/api/workspace/partners',{method:'POST',body:JSON.stringify({name:query,party_type:type()})});input.value=row.name;results.innerHTML='';selection(row);toast('Partenaire référencé')}catch(error){showErr(error)}
  });
 };
 input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>lookup().catch(showErr),250)});
}

function bmNoteCard(row,actions=false){
 return `<article class="bm-note"><div class="bm-note-head"><strong>${e(BM_CATEGORY[row.category]||row.category)}</strong><span class="ops-pill ${row.status==='resolved'?'ok':'warn'}">${e(BM_STATUS[row.status]||row.status)}</span><span class="ops-pill">${e(BM_IMPORTANCE[row.importance]||row.importance)}</span></div>
 <p>${e(row.body)}</p>${row.recommendation?`<p class="bm-recommend"><strong>Action recommandée :</strong> ${e(row.recommendation)}</p>`:''}
 <small>${bmDay(row.event_date||row.created_at)} · ${e(row.author)}${row.launch_id?` · ${e(row.order_ref||'Commande associée')}${row.folder_slug?` · ${e(BM_FOLDER[row.folder_slug]||row.folder_slug)}`:''}`:' · Note générale'}</small>
 <div class="bm-links">${row.launch_id?`<button class="link" data-bm-order="${e(row.launch_id)}">Ouvrir la commande</button>`:''}
 ${row.evidence_version_id?`<button class="link" data-bm-proof="${e(row.evidence_version_id)}">Voir le justificatif</button>`:''}
 ${actions?`<button class="link" data-bm-edit="${e(row.id)}">Corriger / clôturer</button>`:''}</div></article>`;
}
function bmBindNotes(root,refresh){
 root.querySelectorAll('[data-bm-order]').forEach(b=>b.onclick=()=>{closeModal();openLaunch(b.dataset.bmOrder).catch(showErr)});
 root.querySelectorAll('[data-bm-proof]').forEach(b=>b.onclick=()=>paperPassport(b.dataset.bmProof));
 root.querySelectorAll('[data-bm-edit]').forEach(b=>b.onclick=()=>bmEditNote(b.dataset.bmEdit,refresh).catch(showErr));
}
async function bmEditNote(id,refresh){
 const note=await api(`/api/workspace/business-memory/${id}`);
 modal('Corriger ou clôturer un retour',`<form id="bm-edit">
 ${state.me.admin&&note.launch_id?`<div class="field"><label for="bm-edit-folder">Sous-dossier concerné</label><select id="bm-edit-folder">${Object.entries(BM_FOLDER).map(([k,v])=>`<option value="${k}" ${k===note.folder_slug?'selected':''}>${v}</option>`).join('')}</select><small>Le reclassement est réservé au chef et conservé dans l’historique.</small></div>`:''}
 <div class="field"><label for="bm-edit-category">Catégorie</label><select id="bm-edit-category">${Object.entries(BM_CATEGORY).map(([k,v])=>`<option value="${k}" ${k===note.category?'selected':''}>${v}</option>`).join('')}</select></div>
 <div class="field"><label for="bm-edit-date">Date de l’événement</label><input type="date" id="bm-edit-date" value="${e(note.event_date||note.created_at.slice(0,10))}"></div>
 <div class="field"><label for="bm-edit-body">Description factuelle</label><textarea id="bm-edit-body" minlength="12" maxlength="2000" required>${e(note.body)}</textarea></div>
 <div class="field"><label for="bm-edit-recommendation">Action recommandée</label><textarea id="bm-edit-recommendation" maxlength="2000">${e(note.recommendation||'')}</textarea></div>
 <div class="field"><label for="bm-edit-importance">Importance</label><select id="bm-edit-importance">${Object.entries(BM_IMPORTANCE).map(([k,v])=>`<option value="${k}" ${k===note.importance?'selected':''}>${v}</option>`).join('')}</select></div>
 <div class="field"><label for="bm-edit-status">Statut</label><select id="bm-edit-status">${Object.entries(BM_STATUS).map(([k,v])=>`<option value="${k}" ${k===note.status?'selected':''}>${v}</option>`).join('')}</select></div>
 <div class="field"><label for="bm-edit-reason">Justification de la modification</label><textarea id="bm-edit-reason" minlength="12" maxlength="1000" required></textarea></div><button class="primary" type="submit">Enregistrer la décision</button></form>`,true);
 overlay.querySelector('#bm-edit').onsubmit=async event=>{event.preventDefault();try{await api(`/api/workspace/business-memory/${id}`,{method:'PATCH',body:JSON.stringify({category:val('bm-edit-category'),event_date:val('bm-edit-date'),body:val('bm-edit-body'),recommendation:val('bm-edit-recommendation')||null,importance:val('bm-edit-importance'),status:val('bm-edit-status'),folder_slug:overlay.querySelector('#bm-edit-folder')?.value,reason:val('bm-edit-reason')})});closeModal();await refresh()}catch(error){showErr(error)}};
}
async function bmPartnerSheet(id){
 const row=await api(`/api/workspace/partners/${encodeURIComponent(id)}`);
 modal(`Fiche partenaire · ${row.name}`,`<div class="bm-sheet"><p>${e(BM_TYPE[row.party_type])} · ${e(row.business_reference||'Sans référence métier')} · ${row.order_count} commande(s) accessible(s)</p>
 <div class="bm-metrics">${[['incident','Incidents'],['retard','Retards'],['qualite','Qualité'],['documentaire','Documents'],['retour','Positifs'],['open_vigilance','Vigilances ouvertes']].map(([key,label])=>`<div><strong>${row.counts[key]||0}</strong><span>${label}</span></div>`).join('')}</div>
 <h3>Chronologie des expériences</h3>${row.notes.map(n=>bmNoteCard(n,true)).join('')||opsEmpty('Aucun retour pour ce partenaire.')}</div>`,true);
 bmBindNotes(overlay,()=>bmPartnerSheet(id));
}
async function bmContext(partnerId){
 const data=await api(`/api/workspace/partners/${encodeURIComponent(partnerId)}/vigilance`);
 const c=data.counts;
 return `<section class="bm-context ops-panel"><div class="ops-panel-head"><h3>Historique du ${e(BM_TYPE[data.partner.party_type].toLowerCase())} — ${e(data.partner.name)}</h3><button class="link" data-bm-partner="${e(partnerId)}">Consulter la fiche partenaire</button></div>
 <p>${c.retard} retard(s) · ${c.documentaire} problème(s) documentaire(s) · ${c.retour} retour(s) positif(s) · ${c.open_vigilance} vigilance(s) ouverte(s)</p>
 ${data.items.slice(0,4).map(n=>`<div class="bm-vigilance ${n.status==='resolved'?'is-resolved':''}"><strong>${e(BM_CATEGORY[n.category]||n.category)} · ${e(BM_STATUS[n.status])}</strong><p>${e(n.recommendation||n.body)}</p><small>Source : ${bmDay(n.event_date||n.created_at)}${n.launch_id?` · ${e(n.order_ref||'commande liée')}`:''}</small>${n.launch_id?`<button class="link" data-bm-order="${e(n.launch_id)}">Voir la source</button>`:''}</div>`).join('')||'<p class="ops-muted">Aucun point de vigilance significatif enregistré.</p>'}</section>`;
}
function bmBindContext(root){root.querySelectorAll('[data-bm-partner]').forEach(b=>b.onclick=()=>bmPartnerSheet(b.dataset.bmPartner).catch(showErr));bmBindNotes(root,()=>Promise.resolve())}

operationsExperience=async function(){
 state.view='experience';
 const access=await api('/api/workspace/business-memory/options');
 const launchOptions=access.launches.map(l=>`<option value="${e(l.id)}">${e(l.order_ref||l.name)}</option>`).join('');
 mount(`${opsHeading('Mémoire métier','Retours d’expérience internes et fiches partenaires, selon vos habilitations.',access.can_create?'<button class="primary" id="bm-add">+ Ajouter un retour</button>':'')}
 <section class="bm-metrics" id="bm-stats" aria-label="Indicateurs réels"></section>
 <form class="ops-filters bm-filters" id="bm-filters">${opsField('q','Rechercher')}
 <div class="field"><label for="launch_id">Commande</label><select id="launch_id" name="launch_id"><option value="">Toutes les commandes</option>${launchOptions}</select></div>
 <div class="field"><label for="folder_slug">Sous-dossier</label><select id="folder_slug" name="folder_slug"><option value="">Tous les sous-dossiers</option>${Object.entries(BM_FOLDER).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></div>
 <div class="field"><label for="party_type">Partenaire</label><select id="party_type" name="party_type">${bmOptions(Object.entries(BM_TYPE),'Tous')}</select></div>
 <div class="field"><label for="category">Catégorie</label><select id="category" name="category">${bmOptions(Object.entries(BM_CATEGORY),'Toutes')}</select></div>
 <div class="field"><label for="importance">Importance</label><select id="importance" name="importance">${bmOptions(Object.entries(BM_IMPORTANCE),'Toutes')}</select></div>
 <div class="field"><label for="status">Statut</label><select id="status" name="status">${bmOptions(Object.entries(BM_STATUS),'Tous')}</select></div>
 ${opsField('date_from','Depuis','date')}${opsField('date_to','Jusqu’au','date')}
 <div class="field"><label for="sort">Trier</label><select id="sort" name="sort"><option value="date">Date récente</option><option value="importance">Importance</option></select></div></form>
 <section class="ops-panel"><h2>Partenaires référencés</h2><div id="bm-partners" class="bm-partners"></div></section>
 <section class="ops-panel"><h2>Retours enregistrés</h2><div id="bm-results"></div></section>`,'Mémoire métier');
 const form=app.querySelector('#bm-filters');let timer,seq=0;
 const draw=async()=>{const mine=++seq,params=opsParams(form);const [report,partners]=await Promise.all([api('/api/workspace/business-memory?'+params),api('/api/workspace/partners?'+new URLSearchParams({q:params.get('q')||'',party_type:params.get('party_type')||''}))]);if(mine!==seq||state.view!=='experience')return;
  const s=report.stats;app.querySelector('#bm-stats').innerHTML=[['partners','Partenaires'],['returns','Retours'],['incident','Incidents'],['retard','Retards'],['qualite','Qualité'],['retour','Positifs'],['open_vigilance','Vigilances ouvertes']].map(([k,l])=>`<div><strong>${s[k]||0}</strong><span>${l}</span></div>`).join('');
  app.querySelector('#bm-partners').innerHTML=partners.map(p=>`<button class="bm-partner" data-bm-partner="${e(p.id)}"><strong>${e(p.name)}</strong><small>${e(BM_TYPE[p.party_type])}${p.match==='possible'?' · correspondance à vérifier':''}</small></button>`).join('')||opsEmpty('Aucun partenaire correspondant.');
  app.querySelector('#bm-results').innerHTML=report.items.map(n=>bmNoteCard(n,true)).join('')||opsEmpty('Aucun retour correspondant.');bmBindContext(app);bmBindNotes(app,draw);
 };
 form.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>draw().catch(showErr),250)});
 app.querySelector('#bm-add')?.addEventListener('click',()=>operationsAddNote());await draw();
};

operationsAddNote=async function(launchId=null,folderSlug=null){
 const access=await api('/api/workspace/business-memory/options');
 const launches=launchId?access.launches.filter(l=>l.id===launchId):access.launches;
 if(!access.can_create||!launches.length){toast('Aucun sous-dossier accessible pour enregistrer un retour.');return}
 modal('Ajouter un retour métier',`<form id="bm-note-form" class="bm-form">
 <div class="two-fields"><div class="field"><label for="bm-type">Type de partenaire</label><select id="bm-type">${Object.entries(BM_TYPE).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></div><div class="field"><label for="bm-partner-search">Partenaire</label><input id="bm-partner-search" data-bm-search autocomplete="off" required placeholder="Rechercher ou créer"><div class="bm-suggestions" data-bm-results></div></div></div>
 <div class="two-fields"><div class="field"><label for="bm-launch">Commande concernée</label><select id="bm-launch" required>${access.can_general?'<option value="">Retour général · chef uniquement</option>':''}${launches.map(l=>`<option value="${e(l.id)}" ${l.id===launchId?'selected':''}>${e(l.order_ref||l.name)}</option>`).join('')}</select></div><div class="field"><label for="bm-folder">Sous-dossier concerné</label><select id="bm-folder" required></select></div></div>
 <div class="two-fields"><div class="field"><label for="bm-category">Catégorie</label><select id="bm-category">${Object.entries(BM_CATEGORY).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></div><div class="field"><label for="bm-event-date">Date de l’événement</label><input id="bm-event-date" type="date" required value="${new Date().toISOString().slice(0,10)}"></div></div>
 <div class="field"><label for="bm-body">Description factuelle</label><textarea id="bm-body" minlength="12" maxlength="2000" required placeholder="Décrivez les faits observés et leur contexte."></textarea></div>
 <div class="two-fields"><div class="field"><label for="bm-importance">Importance</label><select id="bm-importance">${Object.entries(BM_IMPORTANCE).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></div><div class="field"><label for="bm-status">Statut</label><select id="bm-status">${Object.entries(BM_STATUS).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></div></div>
 <div class="field"><label for="bm-recommendation">Action recommandée · facultative</label><textarea id="bm-recommendation" maxlength="2000"></textarea></div>
 <div class="field"><label for="bm-evidence">Document justificatif existant · facultatif</label><select id="bm-evidence"><option value="">Aucun</option></select></div>
 <button class="primary" type="submit">Enregistrer le retour</button></form>`,true);
 let selected=null;const type=overlay.querySelector('#bm-type');const name=overlay.querySelector('#bm-partner-search');
 bmBindSearch(overlay,{type:()=>type.value,selection:row=>{selected=row},scope:()=>({launch_id:overlay.querySelector('#bm-launch').value,folder_slug:overlay.querySelector('#bm-folder').value})});
 type.onchange=()=>{selected=null;name.value='';overlay.querySelector('[data-bm-results]').innerHTML=''};
 const order=overlay.querySelector('#bm-launch'),folder=overlay.querySelector('#bm-folder'),evidence=overlay.querySelector('#bm-evidence');
 const loadFolders=()=>{const launch=access.launches.find(l=>l.id===order.value);const folders=launch?.folders||[];folder.innerHTML=folders.map(slug=>`<option value="${slug}" ${slug===folderSlug?'selected':''}>${e(BM_FOLDER[slug])}</option>`).join('');folder.disabled=!folders.length};
 const loadEvidence=async()=>{evidence.innerHTML='<option value="">Aucun</option>';if(!order.value||!folder.value)return;try{const detail=await api(`/api/launches/${order.value}`);evidence.insertAdjacentHTML('beforeend',detail.folders.filter(f=>f.slug===folder.value&&f.can_read).flatMap(f=>f.documents.flatMap(d=>d.versions.map(v=>`<option value="${e(v.id)}">${e(d.title)} · V${v.number}</option>`))).join(''))}catch(error){showErr(error)}};
 order.onchange=async()=>{loadFolders();await loadEvidence()};folder.onchange=loadEvidence;loadFolders();await loadEvidence();
 overlay.querySelector('#bm-note-form').onsubmit=async event=>{event.preventDefault();if(!selected){toast('Sélectionnez ou créez la fiche partenaire.');return}try{
  await api('/api/workspace/business-memory',{method:'POST',body:JSON.stringify({partner_id:selected.id,launch_id:order.value||null,folder_slug:folder.value||null,category:val('bm-category'),event_date:val('bm-event-date'),body:val('bm-body'),importance:val('bm-importance'),status:val('bm-status'),recommendation:val('bm-recommendation')||null,evidence_version_id:evidence.value||null})});
  closeModal();toast('Retour enregistré dans la mémoire métier');if(launchId)await openLaunch(launchId,state.folder);else await operationsExperience();
 }catch(error){showErr(error)}};
};

// Raccordement discret dans le parcours commande, y compris les demandes Client.
const bmOriginalLoadExtras=djLoadExtras;
djLoadExtras=async function(id){
 const extras=await bmOriginalLoadExtras(id);
 const links=await api(`/api/launches/${encodeURIComponent(id)}/partners`).catch(()=>[]);
 const contexts=await Promise.all(links.map(p=>bmContext(p.id).catch(()=>'')));
 return {...extras,bmLaunchPartners:links,bmContexts:contexts};
};
const bmOriginalHeader=djHeader;
djHeader=function(){
 const header=bmOriginalHeader();
 const qr='<button class="secondary" id="bm-qr" type="button" aria-label="QR du dossier">▦ QR du dossier</button>';
 const contexts=(state.bmContexts||[]).join('');
 const associate=can('document.write','jaune')?'<button class="link" id="bm-link-partner">Associer un fournisseur ou un atelier</button>':'';
 return header.replace('<div class="dj-head-actions">',`<div class="dj-head-actions">${qr}`)
   +`<div class="bm-order-context">${contexts}${associate}</div>`;
};
const bmOriginalBind=djBind;
djBind=function(){
 bmOriginalBind();app.querySelector('#bm-qr')?.addEventListener('click',paperQR);
 bmBindContext(app);
 app.querySelector('#bm-link-partner')?.addEventListener('click',()=>bmLinkPartner(state.detail.id));
 app.querySelectorAll('[data-bm-passport]').forEach(b=>b.onclick=()=>paperPassport(b.dataset.bmPassport));
 // Le bouton est décidé par l'API sur la commande et le sous-dossier ouverts,
 // jamais par le droit de dépôt Jaune ou une permission d'une autre commande.
 api('/api/workspace/business-memory/options').then(access=>{
  const launch=access.launches.find(item=>item.id===state.detail?.id);
  if(!launch||!launch.folders.includes(state.folder)||app.querySelector('#bm-add-folder-note'))return;
  const host=app.querySelector('.dj-head-actions');if(!host)return;
  const button=document.createElement('button');button.id='bm-add-folder-note';button.type='button';button.className='secondary';button.textContent='+ Ajouter un retour';
  button.onclick=()=>operationsAddNote(state.detail.id,state.folder).catch(showErr);host.prepend(button);
 }).catch(()=>{});
};
async function bmLinkPartner(launchId){
 modal('Associer un partenaire à la commande',`<form id="bm-link-form"><div class="field"><label for="bm-link-type">Type</label><select id="bm-link-type"><option value="fournisseur">Fournisseur</option><option value="atelier">Atelier</option><option value="client">Client</option></select></div>
 <div class="field"><label for="bm-link-search">Partenaire</label><input id="bm-link-search" data-bm-search required autocomplete="off"><div class="bm-suggestions" data-bm-results></div></div><button class="primary" type="submit">Associer à cette commande</button></form>`);
 let selected=null;const type=overlay.querySelector('#bm-link-type'),search=overlay.querySelector('#bm-link-search');
 bmBindSearch(overlay,{type:()=>type.value,selection:p=>selected=p});type.onchange=()=>{search.value='';selected=null};
 overlay.querySelector('#bm-link-form').onsubmit=async event=>{event.preventDefault();if(!selected){toast('Sélectionnez une fiche partenaire.');return}try{
  await api(`/api/launches/${encodeURIComponent(launchId)}/partners`,{method:'POST',body:JSON.stringify({partner_id:selected.id})});closeModal();await openLaunch(launchId,state.folder);
 }catch(error){showErr(error)}};
}
const bmOriginalNewLaunch=openNewLaunch;
openNewLaunch=function(){
 bmOriginalNewLaunch();
 const form=overlay.querySelector('#new-launch-form');if(!form)return;
 form.querySelector('.modal-actions').insertAdjacentHTML('beforebegin',`<div class="field"><label for="bm-launch-supplier">Fournisseur ou atelier associé · facultatif</label><select id="bm-launch-kind"><option value="fournisseur">Fournisseur</option><option value="atelier">Atelier</option></select><input id="bm-launch-supplier" data-bm-search autocomplete="off" placeholder="Rechercher un partenaire existant"><div class="bm-suggestions" data-bm-results></div></div><p class="ops-muted">Sélectionnez une fiche pour voir immédiatement ses expériences sur la nouvelle commande.</p>`);
 let selected=null;bmBindSearch(form,{type:()=>form.querySelector('#bm-launch-kind').value,selection:p=>selected=p,showCreate:false});
 const original=form.onsubmit;
 form.onsubmit=async event=>{
  if(!selected){return original(event)}
  event.preventDefault();try{
   // Fiche commande complète lorsqu'elle est disponible (order-sheet.js), sinon création historique.
   const created=typeof sheetCreateValues==='function'?await api('/api/order-sheets',{method:'POST',body:JSON.stringify(sheetCreateValues()),headers:{'Idempotency-Key':overlay.querySelector('#new-launch-form')?.dataset.idempotencyKey||''}}):await api('/api/launches',{method:'POST',body:JSON.stringify({name:val('l-name'),client_name:val('l-client')||null,order_ref:val('l-order')||null,orli_ref:val('l-orli')||null})});
   await api(`/api/launches/${created.id}/partners`,{method:'POST',body:JSON.stringify({partner_id:selected.id})});closeModal();toast('Dossier créé et partenaire associé');await openLaunch(created.id,'jaune');
  }catch(error){showErr(error)}
 };
};
const bmOriginalEditLaunch=openEditLaunch;
openEditLaunch=function(){bmOriginalEditLaunch();const form=overlay.querySelector('#edit-launch-form');if(!form)return;
 form.querySelector('.modal-actions').insertAdjacentHTML('beforebegin',`<p class="ops-muted">Les partenaires associés et leurs vigilances sont visibles dans l’en-tête de cette commande.</p><button type="button" class="secondary tiny" id="bm-associate-from-edit">Associer un partenaire</button>`);
 form.querySelector('#bm-associate-from-edit').onclick=()=>bmLinkPartner(state.detail.id);
};
const bmOriginalRequest=operationsClientRequest;
operationsClientRequest=async function(id){
 await bmOriginalRequest(id);
 const request=await api(`/api/admin/client-order-requests/${encodeURIComponent(id)}`);
 const matches=await api('/api/workspace/partners?'+new URLSearchParams({q:request.client.raison_sociale,party_type:'client'}));
 const partner=matches.find(p=>p.client_account_id===request.client.id);
 if(partner&&overlay.querySelector('.modal-body')){
  overlay.querySelector('.modal-body').insertAdjacentHTML('afterbegin',await bmContext(partner.id));bmBindContext(overlay);
 }else if(matches.length&&overlay.querySelector('.modal-body')){
  overlay.querySelector('.modal-body').insertAdjacentHTML('afterbegin',`<section class="ops-panel bm-context"><h3>Fiche Client à confirmer</h3><p>Une fiche porte ce nom. Vérifiez son identité avant de rattacher le compte.</p>${matches.map(p=>`<button class="secondary tiny" data-bm-client-link="${e(p.id)}">Rattacher ${e(p.name)}</button>`).join('')}</section>`);
  overlay.querySelectorAll('[data-bm-client-link]').forEach(button=>button.onclick=async()=>{try{
   await api(`/api/workspace/partners/${button.dataset.bmClientLink}/client-account`,{method:'POST',body:JSON.stringify({client_account_id:request.client.id})});await operationsClientRequest(id);
  }catch(error){showErr(error)}});
 }
};
