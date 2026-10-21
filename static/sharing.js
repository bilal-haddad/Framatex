'use strict';
// v0.14 — aucun portail externe : affichage et actions réservés aux sessions internes.
const SHARE_ALLOWED_TYPES=['Fiche technique','Dossier technique client','Rapport de contrôle','Certificat qualité','Bon de livraison','Fiche qualité'];
const SHARE_STATES={published:'Publiée',revoked:'Retirée'};

function renderSharing(){
 const pub=state.clientPublications, suppliers=state.supplierRequests;
 if(!pub || !suppliers)return '';
 const d=state.detail;
 const eligible=d.folders.filter(f=>f.can_read && ['jaune','rose'].includes(f.slug))
   .flatMap(f=>f.documents.filter(doc=>SHARE_ALLOWED_TYPES.includes(doc.doc_type))
     .map(doc=>({doc,folder:f.slug})));
 const canCreateSupplier=d.folders.some(f=>f.can_write && ['jaune','rose'].includes(f.slug));
 return `<section class="sharing-section" id="sharing-workspace">
  <div class="section-heading"><div><h2>Échanges documentaires</h2><small>Partages internes simulés : aucun accès externe n’est ouvert</small></div></div>
  <div class="sharing-grid">
   <article class="panel sharing-card"><div class="sharing-card-head"><div><h3>Publication client</h3><p>Seules les versions autorisées et validées peuvent apparaître dans l’aperçu.</p></div><span class="tag orange">Interne</span></div>
    <div class="sharing-meta"><strong>${pub.items.filter(x=>x.effective).length}</strong> publication(s) effectivement visible(s) dans la simulation${d.client_name?' · '+e(d.client_name):' · client non renseigné'}</div>
    ${pub.items.length?`<div class="sharing-list">${pub.items.map(x=>`<div class="sharing-item"><div><strong>${e(x.document_title)}</strong><small>${e(x.folder)} · v${x.version} · ${e(x.client_name)}</small>${x.stale||x.client_changed||!x.approval_current?`<small class="sharing-warning">Publication non visible : ${x.stale?'version remplacée':x.client_changed?'client modifié':'approbation non valide'}</small>`:''}</div><div class="sharing-actions"><span class="tag ${x.effective?'green':'orange'}">${x.effective?'Visible':x.status==='revoked'?'Retirée':'Suspendue'}</span>${state.me.admin&&x.status==='published'?`<button type="button" class="secondary tiny" data-share-revoke="${e(x.id)}">Retirer</button>`:''}</div></div>`).join('')}</div>`:'<p class="sharing-empty">Aucun document publié pour ce lancement.</p>'}
    <div class="sharing-actions">${state.me.admin?`<button type="button" class="secondary tiny" id="share-preview">${icon('file')} Aperçu client</button><button type="button" class="primary tiny" id="share-publish" ${!eligible.length||!d.client_name?'disabled':''}>${icon('plus')} Publier une version</button>`:''}</div>
   </article>
   <article class="panel sharing-card"><div class="sharing-card-head"><div><h3>Demandes aux fournisseurs</h3><p>Suivre les pièces attendues et rattacher leurs justificatifs après réception.</p></div><span class="tag orange">Interne</span></div>
    <div class="sharing-meta"><strong>${suppliers.items.filter(x=>x.status==='requested').length}</strong> demande(s) en attente</div>
    ${suppliers.items.length?`<div class="sharing-list">${suppliers.items.map(x=>`<div class="sharing-item"><div><strong>${e(x.requested_title)}</strong><small>${e(x.supplier_name)} · ${e(x.folder_slug)} · ${e(x.expected_doc_type)}${x.due_date?' · '+e(x.due_date):''}</small>${x.response_stale?'<small class="sharing-warning">Justificatif remplacé : réexaminer la version</small>':''}</div><div class="sharing-actions"><span class="tag ${x.status==='received'?'green':x.status==='cancelled'?'orange':'blue'}">${x.status==='received'?'Reçue':x.status==='cancelled'?'Annulée':'Demandée'}</span>${x.status==='requested'&&can('document.write',x.folder_slug)?`<button type="button" class="secondary tiny" data-supplier-resolve="${e(x.id)}">Traiter</button>`:''}</div></div>`).join('')}</div>`:'<p class="sharing-empty">Aucune demande fournisseur enregistrée.</p>'}
    ${canCreateSupplier?`<button type="button" class="primary tiny" id="supplier-create">${icon('plus')} Demander une pièce</button>`:''}
   </article>
  </div>
  <p class="sharing-footnote">Ces vues servent à tester les règles métier : elles n’envoient ni fichiers ni messages aux clients ou fournisseurs.</p>
 </section>`;
}

function bindSharing(){
 const id=state.detail?.id;if(!id)return;
 app.querySelector('#share-preview')?.addEventListener('click',async()=>{
   try{const response=await api(`/api/launches/${id}/client-preview`);
     modal('Aperçu client — simulation locale',`<p class="modal-desc">Aucun client ne peut accéder à cette page. Seules les versions encore autorisées sont affichées.</p><div class="sharing-preview">${response.documents.length?response.documents.map(d=>`<div class="sharing-preview-row"><strong>${e(d.title)}</strong><small>${e(d.document_type)} · version ${d.version}</small></div>`).join(''):'<p>Aucun document actuellement publiable.</p>'}</div><div class="modal-actions"><button type="button" class="secondary" id="share-close">Fermer</button></div>`);
     overlay.querySelector('#share-close').onclick=closeModal;
   }catch(err){showErr(err)}
 });
 app.querySelector('#share-publish')?.addEventListener('click',()=>{
   const options=state.detail.folders.filter(f=>f.can_read&&['jaune','rose'].includes(f.slug)).flatMap(f=>f.documents.filter(doc=>SHARE_ALLOWED_TYPES.includes(doc.doc_type)).map(doc=>`<option value="${e(doc.latest.id)}">${e(doc.title)} · ${e(f.slug)} · v${doc.latest.number}</option>`)).join('');
   modal('Publier une version dans la simulation client',`<p class="modal-desc">Un circuit d’approbation achevé (ou une revue approuvée) est obligatoire. Les documents financiers et les anciennes versions restent exclus.</p><form id="share-form"><div class="field"><label>Version documentaire</label><select id="share-version" required>${options}</select></div><div class="field"><label>Motif de publication</label><textarea id="share-reason" minlength="12" maxlength="1200" required rows="3" placeholder="Préciser pourquoi cette pièce est autorisée pour le client"></textarea></div><div class="modal-actions"><button type="button" class="secondary" id="share-cancel">Annuler</button><button class="primary" type="submit">Confirmer la publication</button></div></form>`);
   overlay.querySelector('#share-cancel').onclick=closeModal;
   overlay.querySelector('#share-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${id}/client-publications`,{method:'POST',body:JSON.stringify({document_version_id:val('share-version'),reason:val('share-reason')})});closeModal();toast('Publication simulée enregistrée');await openLaunch(id,state.folder)}catch(err){showErr(err)}};
 });
 app.querySelectorAll('[data-share-revoke]').forEach(b=>b.addEventListener('click',()=>{
   modal('Retirer la publication',`<form id="share-revoke-form"><p class="modal-desc">La publication sera retirée de l’aperçu sans supprimer le document ni l’historique.</p><div class="field"><label>Motif de retrait</label><textarea id="share-revoke-reason" minlength="12" maxlength="1200" required rows="3"></textarea></div><div class="modal-actions"><button type="button" class="secondary" id="share-cancel">Annuler</button><button class="primary" type="submit">Retirer</button></div></form>`);
   overlay.querySelector('#share-cancel').onclick=closeModal;
   overlay.querySelector('#share-revoke-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/client-publications/${b.dataset.shareRevoke}/revoke`,{method:'POST',body:JSON.stringify({reason:val('share-revoke-reason')})});closeModal();toast('Publication retirée');await openLaunch(id,state.folder)}catch(err){showErr(err)}};
 }));
 app.querySelector('#supplier-create')?.addEventListener('click',()=>{
   const folders=state.detail.folders.filter(f=>['jaune','rose'].includes(f.slug)&&f.can_write).map(f=>`<option value="${e(f.slug)}">${e(f.label)}</option>`).join('');
   modal('Créer une demande documentaire fournisseur',`<p class="modal-desc">Cette demande reste interne. Aucun email ou lien d’accès n’est envoyé au fournisseur.</p><form id="supplier-form"><div class="two-fields"><div class="field"><label>Sous-dossier</label><select id="supplier-folder">${folders}</select></div><div class="field"><label>Fournisseur</label><input id="supplier-name" maxlength="150" required minlength="2" /></div></div><div class="field"><label>Pièce attendue</label><input id="supplier-title" maxlength="200" required minlength="3" /></div><div class="two-fields"><div class="field"><label>Type documentaire attendu</label><input id="supplier-type" maxlength="100" required value="Bon de livraison" /></div><div class="field"><label>Date cible (facultative)</label><input id="supplier-date" type="date" /></div></div><div class="field"><label>Précisions</label><textarea id="supplier-note" maxlength="1200" rows="3"></textarea></div><div class="modal-actions"><button type="button" class="secondary" id="supplier-cancel">Annuler</button><button class="primary" type="submit">Enregistrer la demande</button></div></form>`);
   overlay.querySelector('#supplier-cancel').onclick=closeModal;
   overlay.querySelector('#supplier-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${id}/supplier-requests`,{method:'POST',body:JSON.stringify({folder_slug:val('supplier-folder'),supplier_name:val('supplier-name'),requested_title:val('supplier-title'),expected_doc_type:val('supplier-type'),due_date:val('supplier-date')||null,note:val('supplier-note')})});closeModal();toast('Demande fournisseur enregistrée');await openLaunch(id,state.folder)}catch(err){showErr(err)}};
 });
 app.querySelectorAll('[data-supplier-resolve]').forEach(b=>b.addEventListener('click',()=>{
   const request=state.supplierRequests.items.find(x=>x.id===b.dataset.supplierResolve);if(!request)return;
   const folder=state.detail.folders.find(f=>f.slug===request.folder_slug);
   const docs=folder?.documents.filter(x=>x.doc_type===request.expected_doc_type)||[];
   modal('Traiter une demande fournisseur',`<p class="modal-desc">${e(request.requested_title)} · ${e(request.supplier_name)}. La confirmation de réception doit citer une version réellement déposée dans ce lancement.</p><form id="supplier-resolve-form"><div class="field"><label>Décision</label><select id="supplier-decision"><option value="received">Pièce reçue</option><option value="cancelled">Annuler la demande</option></select></div><div class="field"><label>Version justificative</label><select id="supplier-version"><option value="">Choisir une version</option>${docs.map(d=>`<option value="${e(d.latest.id)}">${e(d.title)} · v${d.latest.number}</option>`).join('')}</select></div><div class="field"><label>Commentaire motivé</label><textarea id="supplier-resolution" minlength="12" maxlength="1200" rows="3" required></textarea></div><div class="modal-actions"><button type="button" class="secondary" id="supplier-cancel">Annuler</button><button class="primary" type="submit">Enregistrer</button></div></form>`);
   overlay.querySelector('#supplier-cancel').onclick=closeModal;
   overlay.querySelector('#supplier-resolve-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/supplier-requests/${request.id}/resolve`,{method:'POST',body:JSON.stringify({decision:val('supplier-decision'),document_version_id:val('supplier-decision')==='received'?val('supplier-version')||null:null,note:val('supplier-resolution')})});closeModal();toast('Demande mise à jour');await openLaunch(id,state.folder)}catch(err){showErr(err)}};
 }));
}
