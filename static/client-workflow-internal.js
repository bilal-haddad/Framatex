'use strict';
// Actions métier supplémentaires dans les composants internes existants.
const CLIENT_ORDER_LABELS={draft:'Brouillon',submitted:'Envoyée',under_review:'En cours d’étude',accepted:'Acceptée',rejected:'Refusée'};
const CLIENT_DOCUMENT_LABELS={requested:'Demandé',uploaded:'Déposé',under_review:'En vérification',accepted:'Accepté',correction_required:'À corriger'};
const CLIENT_INTERNAL_TRANSITIONS={submitted:['under_review','accepted','rejected'],under_review:['accepted','rejected']};
function clientWorkflowDocument(item){
 const versions=item.document?.versions||[];const latest=versions.at(-1);
 const decisions=['uploaded','under_review'].includes(item.status)?['under_review','accepted','correction_required'].filter(status=>status!==item.status):[];
 return `<article class="ops-panel"><div class="ops-panel-head"><h3>${e(item.title)}</h3><span class="ops-pill ${item.status==='accepted'?'ok':'warn'}">${e(CLIENT_DOCUMENT_LABELS[item.status])}</span></div><p>${e(item.description)}</p><p class="ops-muted">${e(item.request_number)} · ${e(item.requested_by)} · ${niceDate(item.requested_at)}</p>
 ${versions.map(v=>`<p><a class="link" href="/api/admin/client-document-requests/${encodeURIComponent(item.id)}/versions/${v.number}/download">${e(v.original_name)} · V${v.number}</a><code class="ops-hash">SHA-256 : ${e(v.sha256)}</code></p>`).join('')||opsEmpty('Aucun dépôt reçu.')}
 <div class="ops-tabs">${decisions.map(status=>`<button class="secondary tiny" type="button" data-client-doc-decision="${e(item.id)}" data-version="${e(latest.id)}" data-status="${status}">${status==='correction_required'?'Demander correction':status==='under_review'?'Mettre en vérification':'Accepter'}</button>`).join('')}</div>
 <details><summary>Historique documentaire</summary>${item.history.map(event=>`<div class="ops-comment"><strong>${e(CLIENT_DOCUMENT_LABELS[event.status])}${event.version?' · V'+event.version:''}</strong><small> · ${e(event.actor)} · ${niceDate(event.occurred_at)}</small><p>${e(event.message)}</p></div>`).join('')}</details></article>`;
}
function clientWorkflowShares(items){return items.map(item=>`<article class="ops-comment"><strong>${e(item.title)} · V${item.version}</strong><small>${e(item.status==='revoked'?'Retiré':item.effective?'Partagé':'Publication non effective')} · ${niceDate(item.published_at)}</small><code class="ops-hash">SHA-256 : ${e(item.sha256)}</code>${item.status==='published'?`<button class="secondary tiny" type="button" data-client-share-revoke="${e(item.id)}">Retirer du partage client</button>`:''}</article>`).join('')||opsEmpty('Aucun document partagé avec ce compte Client.')}
function clientWorkflowBind(root,refresh){
 root.querySelectorAll('[data-client-doc-decision]').forEach(button=>button.onclick=()=>{
   modal('Vérification du document client',`<form id="cw-review-form"><p>${e(CLIENT_DOCUMENT_LABELS[button.dataset.status])}</p><div class="field"><label for="cw-message">Message au client${button.dataset.status==='correction_required'?' · correction attendue':''}</label><textarea id="cw-message" maxlength="2000" ${button.dataset.status==='correction_required'?'required minlength="3"':''}></textarea></div><p class="ops-muted">Ce message apparaît dans l’historique documentaire du client. Les commentaires internes restent distincts.</p><button class="primary" type="submit">Enregistrer la décision sur cette version</button></form>`);
   overlay.querySelector('#cw-review-form').onsubmit=async event=>{event.preventDefault();try{await api(`/api/admin/client-document-requests/${button.dataset.clientDocDecision}/status`,{method:'PATCH',body:JSON.stringify({status:button.dataset.status,version_id:button.dataset.version,message:val('cw-message')})});await refresh()}catch(error){showErr(error)}};
 });
 root.querySelectorAll('[data-client-share-revoke]').forEach(button=>button.onclick=()=>{
   modal('Retirer du partage client',`<form id="cw-revoke-form"><p>Le retrait conserve le document interne et l’historique du partage.</p><div class="field"><label for="cw-revoke-reason">Motif du retrait</label><textarea id="cw-revoke-reason" required minlength="12" maxlength="1200"></textarea></div><button class="primary" type="submit">Retirer du partage</button></form>`);
   overlay.querySelector('#cw-revoke-form').onsubmit=async event=>{event.preventDefault();try{await api(`/api/admin/client-shared-documents/${button.dataset.clientShareRevoke}/revoke`,{method:'POST',body:JSON.stringify({reason:val('cw-revoke-reason')})});await refresh()}catch(error){showErr(error)}};
 });
}
function clientWorkflowAsk(orderId,refresh){
 modal('Demander un document au client',`<form id="cw-ask-form"><div class="field"><label for="cw-title">Document demandé</label><input id="cw-title" minlength="2" maxlength="200" required placeholder="Dossier technique"></div><div class="field"><label for="cw-description">Précisions destinées au client</label><textarea id="cw-description" maxlength="2000"></textarea></div><button class="primary" type="submit">Demander le document</button></form>`);
 overlay.querySelector('#cw-ask-form').onsubmit=async event=>{event.preventDefault();try{await api(`/api/admin/client-order-requests/${orderId}/document-requests`,{method:'POST',body:JSON.stringify({title:val('cw-title'),description:val('cw-description')})});await refresh()}catch(error){showErr(error)}};
}
async function clientWorkflowShare(clientId=null,orderId=null,versionId=null,refresh=()=>operationsClients()){
 const [candidates,clients]=await Promise.all([api('/api/admin/client-share-candidates'),clientId?Promise.resolve([]):api('/api/admin/clients')]);
 const versions=versionId?candidates.filter(item=>item.version_id===versionId):candidates;
 if(!versions.length){toast('Aucune version admissible et approuvée pour ce partage.');return}
 modal('Partager explicitement avec le client',`<form id="cw-share-form">${!clientId?`<div class="field"><label for="cw-client">Compte Client destinataire</label><select id="cw-client" required><option value="">Choisir le compte</option>${clients.map(client=>`<option value="${e(client.id)}">${e(client.raison_sociale)} · ${e(client.client_code)} · ${e(client.email)}</option>`).join('')}</select></div>`:''}<div class="field"><label for="cw-version">Version interne approuvée</label><select id="cw-version" required>${versions.map(item=>`<option value="${e(item.version_id)}">${e(item.title)} · V${item.version} · ${e(item.launch_name)}</option>`).join('')}</select></div><div class="field"><label for="cw-share-reason">Motif de l’autorisation de partage</label><textarea id="cw-share-reason" required minlength="12" maxlength="1200"></textarea></div><p class="ops-muted">Seule cette version devient téléchargeable par le compte sélectionné. Aucun commentaire, audit ou autre document interne n’est partagé.</p><button class="primary" type="submit">Partager avec le client</button></form>`,true);
 overlay.querySelector('#cw-share-form').onsubmit=async event=>{event.preventDefault();try{await api(`/api/admin/clients/${clientId||val('cw-client')}/shared-documents`,{method:'POST',body:JSON.stringify({document_version_id:val('cw-version'),order_request_id:orderId,reason:val('cw-share-reason')})});closeModal();toast('Version partagée avec le compte Client sélectionné.');await refresh()}catch(error){showErr(error)}};
}
async function clientWorkflowAccount(clientId){
 const [requests,shared]=await Promise.all([api(`/api/admin/clients/${clientId}/document-requests`),api(`/api/admin/clients/${clientId}/shared-documents`)]);
 modal('Documents du compte Client',`<h3>Documents demandés / reçus</h3>${requests.map(clientWorkflowDocument).join('')||opsEmpty('Aucune pièce demandée.')}<div class="ops-panel-head"><h3>Documents partagés</h3><button class="secondary tiny" id="cw-account-share">Partager un document</button></div>${clientWorkflowShares(shared)}`,true);
 clientWorkflowBind(overlay,()=>clientWorkflowAccount(clientId));overlay.querySelector('#cw-account-share').onclick=()=>clientWorkflowShare(clientId,null,null,()=>clientWorkflowAccount(clientId)).catch(showErr);
}
const clientWorkflowOriginalClients=operationsClients;
operationsClients=async function(){
 await clientWorkflowOriginalClients();
 app.querySelectorAll('[data-ops-client]').forEach(button=>{const action=document.createElement('button');action.className='secondary tiny';action.type='button';action.dataset.clientWorkflowAccount=button.dataset.opsClient;action.textContent='Documents demandés / partagés';action.onclick=()=>clientWorkflowAccount(button.dataset.opsClient).catch(showErr);button.parentElement.appendChild(action)});
 app.querySelectorAll('[data-ops-request] .ops-pill').forEach(label=>{label.textContent=CLIENT_ORDER_LABELS[label.textContent]||label.textContent});
};
const clientWorkflowOriginalRequest=operationsClientRequest;
operationsClientRequest=async function(orderId){
 await clientWorkflowOriginalRequest(orderId);
 const order=await api(`/api/admin/client-order-requests/${orderId}`);
 const [requested,shared]=await Promise.all([api(`/api/admin/clients/${order.client.id}/document-requests?order_request_id=${encodeURIComponent(orderId)}`),api(`/api/admin/clients/${order.client.id}/shared-documents`)]);
 const statuses=CLIENT_INTERNAL_TRANSITIONS[order.status]||[];
 overlay.querySelector('.modal-body').insertAdjacentHTML('beforeend',`<section class="ops-panel"><h3>Statut de la demande : ${e(CLIENT_ORDER_LABELS[order.status])}</h3>${statuses.length?`<form id="cw-order-status-form"><div class="field"><label for="cw-order-status">Décision FRAMATEX</label><select id="cw-order-status">${statuses.map(status=>`<option value="${status}">${e(CLIENT_ORDER_LABELS[status])}</option>`).join('')}</select></div><button class="secondary" type="submit">Changer le statut de la demande</button></form>`:'<p class="ops-muted">Aucune transition interne disponible pour ce statut.</p>'}${order.launch?`<div class="ops-panel-head"><p class="ops-muted">Dossier Jaune ouvert : <strong>${e(order.launch.name)}</strong> · ${e(order.launch.order_ref||'')}</p><button class="secondary tiny" type="button" id="cw-open-launch">Ouvrir le Dossier Jaune</button></div>`:['submitted','under_review','accepted'].includes(order.status)?`<div class="ops-panel-head"><p class="ops-muted">Ouvre le Dossier Jaune avec ses quatre sous-dossiers, l’article, la quantité et le lien permanent vers cette demande.</p><button class="primary tiny" type="button" id="cw-create-launch">${order.status==='accepted'?'Créer le Dossier Jaune':'Accepter et créer le Dossier Jaune'}</button></div>`:''}</section><div class="ops-panel-head"><h3>Documents demandés / reçus</h3><button class="primary tiny" id="cw-ask-document">Demander un document</button></div>${requested.map(clientWorkflowDocument).join('')||opsEmpty('Aucune pièce demandée.')}<div class="ops-panel-head"><h3>Documents partagés avec ce client</h3><button class="secondary tiny" id="cw-share-document">Partager un document</button></div>${clientWorkflowShares(shared)}`);
 const refresh=()=>operationsClientRequest(orderId);
 overlay.querySelector('#cw-open-launch')?.addEventListener('click',()=>{closeModal();openLaunch(order.launch.id,'jaune')});
 overlay.querySelector('#cw-create-launch')?.addEventListener('click',async event=>{const button=event.currentTarget;button.disabled=true;button.setAttribute('aria-busy','true');try{const result=await api(`/api/admin/client-order-requests/${orderId}/launch`,{method:'POST'});closeModal();toast(result.created?'Dossier Jaune créé avec ses quatre sous-dossiers':'Ce Dossier Jaune existait déjà');await openLaunch(result.launch.id,'jaune')}catch(error){button.disabled=false;button.removeAttribute('aria-busy');showErr(error)}});
 overlay.querySelector('#cw-order-status-form')?.addEventListener('submit',async event=>{event.preventDefault();try{await api(`/api/admin/client-order-requests/${orderId}/status`,{method:'PATCH',body:JSON.stringify({status:val('cw-order-status')})});await refresh()}catch(error){showErr(error)}});
 overlay.querySelector('#cw-ask-document').onclick=()=>clientWorkflowAsk(orderId,refresh);
 overlay.querySelector('#cw-share-document').onclick=()=>clientWorkflowShare(order.client.id,orderId,null,refresh).catch(showErr);
 clientWorkflowBind(overlay,refresh);
};
const clientWorkflowOriginalDocument=operationsDocument;
operationsDocument=async function(id,versionId=null){
 await clientWorkflowOriginalDocument(id,versionId);
 if(!state.me.admin)return;const doc=findDoc(id);if(!doc)return;
 const version=doc.versions.find(item=>item.id===versionId)||doc.latest;
 const actions=overlay.querySelector('.ops-tabs');if(!actions)return;
 const button=document.createElement('button');button.type='button';button.className='secondary tiny';button.textContent='Partager avec le client';button.dataset.clientWorkflowShareVersion=version.id;button.onclick=()=>clientWorkflowShare(null,null,version.id,()=>operationsDocument(id,version.id)).catch(showErr);actions.appendChild(button);
};
