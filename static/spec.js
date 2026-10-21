'use strict';
// MVP 0.7 : aucune extraction ni conformité n'est décidée automatiquement.
function renderSpec(){
 const data=state.specReport||{requirements:[],ambiguities:[],coverage:{visible_total:0,verified:0,uncovered:0,to_verify:0,recheck:0},open_ambiguities:0};
 const docs=(state.detail?.folders||[]).filter(f=>f.can_read).flatMap(f=>f.documents);
 const canEdit=(state.detail?.folders||[]).some(f=>f.can_write);
 const status={verified:'Vérifiée par responsable',uncovered:'Sans justificatif',to_verify:'Preuve à vérifier',source_changed:'Source remplacée',evidence_changed:'Preuve remplacée',open:'À clarifier',resolved:'Clarifiée',dismissed:'Écartée'};
 const p=data.coverage;
 const reqRows=data.requirements.map(r=>`<article class="spec-item"><div class="spec-item-title"><strong>${e(r.title)}</strong><span class="tag ${r.state==='verified'?'green':r.state==='uncovered'?'orange':''}">${e(status[r.state]||r.state)}</span></div><div class="workflow-meta">${e(r.category)} · ${e(r.source_document)} v${r.source_version}</div><p>${e(r.description)}</p>${r.evidence_document?`<div class="spec-evidence">Justificatif : ${e(r.evidence_document)} v${r.evidence_version}</div>`:''}${r.review_note?`<div class="spec-evidence">Décision : ${e(r.review_note)}</div>`:''}<div class="spec-actions">${can('document.write',r.source_folder)?`<button class="link" data-spec-evidence="${e(r.id)}">Associer une preuve</button>`:''}${r.state==='source_changed'&&can('document.write',r.source_folder)?`<button class="link" data-spec-refresh-req="${e(r.id)}">Actualiser la source</button>`:''}${r.can_review&&r.evidence_version_id&&r.state!=='verified'?`<button class="link" data-spec-verify="${e(r.id)}">Vérifier</button>`:''}</div></article>`).join('');
 const ambRows=data.ambiguities.map(a=>`<article class="spec-item"><div class="spec-item-title"><strong>${e(a.kind)}</strong><span class="tag ${a.status==='resolved'?'green':'orange'}">${e(status[a.status]||a.status)}</span></div><blockquote>${e(a.excerpt)}</blockquote><p>${e(a.question)}</p><div class="workflow-meta">${e(a.source_document)} v${a.source_version}</div>${a.resolution?`<div class="spec-evidence">${e(a.resolution)}</div>`:''}${a.status==='source_changed'&&can('document.write',a.source_folder)?`<button class="link" data-spec-refresh-amb="${e(a.id)}">Réexaminer la version</button>`:''}${a.can_review&&a.status==='open'?`<button class="link" data-spec-resolve="${e(a.id)}">Documenter la décision</button>`:''}</article>`).join('');
 return `<section class="spec-section" aria-label="Exigences client et ambiguïtés"><div class="section-heading workflow-head"><div><h2>Exigences client et ambiguïtés</h2><small>Spécifications vérifiables · source, preuve et décision humaines</small></div></div>
 <div class="spec-summary"><div><strong>${p.visible_total}</strong><span>Exigences visibles</span></div><div><strong>${p.verified}</strong><span>Vérifiées</span></div><div><strong>${p.uncovered}</strong><span>Sans preuve</span></div><div><strong>${data.open_ambiguities}</strong><span>Points à clarifier</span></div></div>
 <div class="spec-toolbar panel"><p>Analyse limitée aux passages lisibles du document. L'absence d'alerte ne garantit ni la conformité ni l'exhaustivité. Les chiffres ne concernent que les rubriques accessibles.</p><div class="spec-buttons">${canEdit?`<button class="primary tiny" id="spec-scan">Analyser un document</button><button class="secondary tiny" id="spec-add-manual">Saisir une exigence</button>`:'<span class="tag">Consultation uniquement</span>'}</div></div>
 <div class="spec-grid"><div><div class="section-heading"><h3>Couverture des exigences</h3><small>${p.to_verify} à vérifier · ${p.recheck} à réexaminer</small></div><div class="panel spec-list">${reqRows||'<div class="workflow-empty">Aucune exigence confirmée pour ce lancement.</div>'}</div></div>
 <div><div class="section-heading"><h3>Points de clarification</h3><small>${data.open_ambiguities} ouverts ou à réexaminer</small></div><div class="panel spec-list">${ambRows||'<div class="workflow-empty">Aucune ambiguïté enregistrée.</div>'}</div></div></div></section>`;
}
function bindSpec(){
 app.querySelectorAll('[data-spec-refresh-req]').forEach(b=>b.addEventListener('click',()=>specRefreshReq(b.dataset.specRefreshReq)));
 app.querySelectorAll('[data-spec-refresh-amb]').forEach(b=>b.addEventListener('click',()=>specRefreshAmb(b.dataset.specRefreshAmb)));
 app.querySelector('#spec-scan')?.addEventListener('click',specPickScan);
 app.querySelector('#spec-add-manual')?.addEventListener('click',()=>specCreateReq());
 app.querySelectorAll('[data-spec-evidence]').forEach(b=>b.addEventListener('click',()=>specEvidence(b.dataset.specEvidence)));
 app.querySelectorAll('[data-spec-verify]').forEach(b=>b.addEventListener('click',()=>specVerify(b.dataset.specVerify)));
 app.querySelectorAll('[data-spec-resolve]').forEach(b=>b.addEventListener('click',()=>specResolve(b.dataset.specResolve)));
}
function specDocs(write=false){return (state.detail?.folders||[]).filter(f=>f.can_read&&(!write||f.can_write)).flatMap(f=>f.documents.map(d=>({doc:d,folder:f.slug})));}
function specVersionOptions(docs,selected=''){return docs.map(({doc,folder})=>`<option value="${e(doc.latest.id)}" ${doc.latest.id===selected?'selected':''}>${e(doc.title)} · v${doc.latest.number} · ${e(folder)}</option>`).join('');}
function specPickScan(){
 const docs=specDocs(true);
 if(!docs.length){toast('Déposez un dossier technique dans une rubrique autorisée');return;}
 modal('Analyser les spécifications',`<p class="modal-desc">Repérage lexical local sur la version courante ; les propositions ne sont ni exhaustives ni enregistrées tant que vous ne les confirmez pas.</p><div class="field"><label>Document source</label><select id="spec-doc-choice">${specVersionOptions(docs)}</select></div><div class="modal-actions"><button class="secondary" id="spec-cancel">Annuler</button><button class="primary" id="spec-analyze">Lire les passages</button></div><div id="spec-results"></div>`,true);
 overlay.querySelector('#spec-cancel').onclick=closeModal;
 overlay.querySelector('#spec-analyze').onclick=async()=>{
  const versionId=val('spec-doc-choice'),region=overlay.querySelector('#spec-results');region.innerHTML='<p class="workflow-help">Lecture en cours…</p>';
  try{const x=await api(`/api/document-versions/${encodeURIComponent(versionId)}/spec-suggestions`);
   region.innerHTML=`<div class="spec-detected"><p class="workflow-help">Méthode : ${e(x.method)} · ${e(x.warnings.join(' · '))}</p><p class="permission-lock">${e(x.limits)}</p><h3>Exigences candidates (${x.requirements.length})</h3>${x.requirements.map((r,i)=>`<article class="spec-suggestion"><strong>${e(r.category)}</strong><p>${e(r.description)}</p><button class="secondary tiny" data-spec-accept-req="${i}">Revoir et enregistrer</button></article>`).join('')||'<p class="workflow-help">Aucune proposition : saisir manuellement si nécessaire.</p>'}<h3>Ambiguïtés potentielles (${x.ambiguities.length})</h3>${x.ambiguities.map((a,i)=>`<article class="spec-suggestion"><strong>${e(a.kind)}</strong><p>${e(a.excerpt)}</p><p>${e(a.question)}</p><button class="secondary tiny" data-spec-accept-amb="${i}">Revoir et enregistrer</button></article>`).join('')||'<p class="workflow-help">Aucun passage repéré sur la zone analysée.</p>'}</div>`;
   region.querySelectorAll('[data-spec-accept-req]').forEach(b=>b.onclick=()=>specCreateReq(versionId,x.requirements[+b.dataset.specAcceptReq]));
   region.querySelectorAll('[data-spec-accept-amb]').forEach(b=>b.onclick=()=>specCreateAmb(versionId,x.ambiguities[+b.dataset.specAcceptAmb]));
  }catch(err){region.textContent='';showErr(err)}
 };
}
function specCreateReq(versionId='',candidate=null){
 const docs=specDocs(true);
 if(!docs.length){toast('Aucun document modifiable');return;}
 modal('Confirmer une exigence client',`<form id="spec-req-form"><div class="field"><label>Document source *</label><select id="spec-req-version" required>${specVersionOptions(docs,versionId)}</select></div><div class="field"><label>Intitulé *</label><input id="spec-req-title" minlength="5" maxlength="180" required value="${e(candidate?.title||'')}"></div><div class="field"><label>Catégorie</label><select id="spec-req-category">${['Autre','Matière','Dimensions','Accessoires','Couleur','Conditionnement','Confection'].map(x=>`<option ${candidate?.category===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Exigence à vérifier *</label><textarea id="spec-req-description" minlength="8" maxlength="1200" required>${e(candidate?.description||'')}</textarea></div><div class="field"><label>Extrait exact / justification du repérage</label><textarea id="spec-req-excerpt" maxlength="500">${e(candidate?.source_excerpt||'')}</textarea></div><p class="permission-lock">L'enregistrement confirme uniquement que l'exigence a été identifiée. Sa conformité nécessite une preuve et une vérification distincte.</p><div class="modal-actions"><button class="secondary" type="button" id="spec-cancel">Annuler</button><button class="primary" type="submit">Enregistrer cette exigence</button></div></form>`,true);
 overlay.querySelector('#spec-cancel').onclick=closeModal;
 overlay.querySelector('#spec-req-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${state.detail.id}/requirements`,{method:'POST',body:JSON.stringify({source_version_id:val('spec-req-version'),title:val('spec-req-title'),category:val('spec-req-category'),description:val('spec-req-description'),source_excerpt:val('spec-req-excerpt')})});closeModal();toast('Exigence identifiée — justificatif encore à associer');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
}
function specCreateAmb(versionId,candidate){
 const docs=specDocs(true);
 modal('Confirmer un point à clarifier',`<form id="spec-amb-form"><div class="field"><label>Document source</label><select id="spec-amb-version">${specVersionOptions(docs,versionId)}</select></div><div class="field"><label>Passage concerné</label><textarea id="spec-amb-excerpt" minlength="8" maxlength="500" required>${e(candidate.excerpt)}</textarea></div><div class="field"><label>Question à poser</label><textarea id="spec-amb-question" minlength="8" maxlength="500" required>${e(candidate.question)}</textarea></div><p class="permission-lock">Ce point reste une demande de clarification, pas une non-conformité prouvée.</p><div class="modal-actions"><button type="button" class="secondary" id="spec-cancel">Annuler</button><button type="submit" class="primary">Enregistrer le point</button></div></form>`,true);
 overlay.querySelector('#spec-cancel').onclick=closeModal;
 overlay.querySelector('#spec-amb-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${state.detail.id}/ambiguities`,{method:'POST',body:JSON.stringify({source_version_id:val('spec-amb-version'),excerpt:val('spec-amb-excerpt'),kind:candidate.kind,question:val('spec-amb-question')})});closeModal();toast('Ambiguïté enregistrée');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
}
function specEvidence(id){
 const req=state.specReport.requirements.find(r=>r.id===id),docs=specDocs();if(!req)return;
 if(!docs.length){toast('Aucun document de preuve accessible');return;}
 modal('Associer un justificatif',`<p class="modal-desc">${e(req.title)}. L'association d'un fichier ne valide pas sa conformité.</p><form id="spec-proof-form"><div class="field"><label>Version du document de preuve</label><select id="spec-proof-version">${specVersionOptions(docs,req.evidence_version_id||'')}</select></div><div class="modal-actions"><button type="button" class="secondary" id="spec-cancel">Annuler</button><button class="primary" type="submit">Associer</button></div></form>`);
 overlay.querySelector('#spec-cancel').onclick=closeModal;
 overlay.querySelector('#spec-proof-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${state.detail.id}/requirements/${id}/evidence`,{method:'POST',body:JSON.stringify({evidence_version_id:val('spec-proof-version')})});closeModal();toast('Preuve associée ; vérification encore requise');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
}
function specVerify(id){
 const req=state.specReport.requirements.find(r=>r.id===id);if(!req)return;
 modal('Vérification humaine de l’exigence',`<p class="modal-desc">Exigence : ${e(req.title)}<br>Preuve : ${e(req.evidence_document)} v${req.evidence_version}. Examinez la pièce avant de confirmer.</p><form id="spec-check-form"><div class="field"><label>Justification de la vérification *</label><textarea id="spec-review-note" minlength="12" maxlength="2000" required placeholder="Précisez le résultat du contrôle et la preuve examinée."></textarea></div><div class="modal-actions"><button type="button" id="spec-cancel" class="secondary">Annuler</button><button class="primary" type="submit">Confirmer l'examen</button></div></form>`);
 overlay.querySelector('#spec-cancel').onclick=closeModal;
 overlay.querySelector('#spec-check-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${state.detail.id}/requirements/${id}/verify`,{method:'POST',body:JSON.stringify({note:val('spec-review-note')})});closeModal();toast('Vérification enregistrée avec versions sources');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
}
function specResolve(id){
 const item=state.specReport.ambiguities.find(a=>a.id===id);if(!item)return;
 const docs=specDocs();
 modal('Traiter un point de clarification',`<p class="modal-desc">${e(item.excerpt)}</p><form id="spec-close-form"><div class="field"><label>Décision</label><select id="spec-close-status"><option value="resolved">Clarifié après examen</option><option value="dismissed">Écarté avec justification</option></select></div><div class="field"><label>Réponse reçue / justification *</label><textarea id="spec-close-note" minlength="12" maxlength="2000" required></textarea></div><div class="field"><label>Document de clarification (facultatif)</label><select id="spec-close-version"><option value="">Aucun document associé</option>${specVersionOptions(docs)}</select></div><div class="modal-actions"><button type="button" id="spec-cancel" class="secondary">Annuler</button><button type="submit" class="primary">Documenter la décision</button></div></form>`);
 overlay.querySelector('#spec-cancel').onclick=closeModal;
 overlay.querySelector('#spec-close-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${state.detail.id}/ambiguities/${id}/resolve`,{method:'POST',body:JSON.stringify({decision:val('spec-close-status'),note:val('spec-close-note'),clarification_version_id:val('spec-close-version')||null})});closeModal();toast('Décision de clarification documentée');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
}

function specRefreshReq(id){
 const row=state.specReport.requirements.find(x=>x.id===id);
 const doc=specDocs(true).find(x=>x.doc.id===row?.source_document_id)?.doc;
 if(!row||!doc){toast('Nouvelle version source inaccessible');return;}
 modal('Actualiser la source de l’exigence',`<p class="modal-desc">Passage de v${row.source_version} à v${doc.latest.number}. Relisez le document avant de confirmer : aucune conformité antérieure n'est conservée automatiquement.</p><form id="spec-refresh-req-form"><div class="field"><label>Intitulé réexaminé</label><input id="spec-refresh-title" minlength="5" maxlength="180" required value="${e(row.title)}"></div><div class="field"><label>Exigence réexaminée</label><textarea id="spec-refresh-description" minlength="8" maxlength="1200" required>${e(row.description)}</textarea></div><div class="field"><label>Passage justificatif de la nouvelle version</label><textarea id="spec-refresh-excerpt" maxlength="500">${e(row.source_excerpt)}</textarea></div><div class="modal-actions"><button class="secondary" id="spec-cancel" type="button">Annuler</button><button class="primary" type="submit">Confirmer la nouvelle version</button></div></form>`,true);
 overlay.querySelector('#spec-cancel').onclick=closeModal;
 overlay.querySelector('#spec-refresh-req-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${state.detail.id}/requirements/${id}/refresh-source`,{method:'POST',body:JSON.stringify({new_source_version_id:doc.latest.id,title:val('spec-refresh-title'),description:val('spec-refresh-description'),source_excerpt:val('spec-refresh-excerpt')})});closeModal();toast('Nouvelle source enregistrée ; revérification requise');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
}
function specRefreshAmb(id){
 const row=state.specReport.ambiguities.find(x=>x.id===id);
 const doc=specDocs(true).find(x=>x.doc.id===row?.source_document_id)?.doc;
 if(!row||!doc){toast('Nouvelle version source inaccessible');return;}
 modal('Réexaminer une ambiguïté',`<p class="modal-desc">Source remplacée. Vérifiez si le passage reste ambigu dans la version ${doc.latest.number}.</p><form id="spec-refresh-amb-form"><div class="field"><label>Passage de la nouvelle version</label><textarea id="spec-refresh-amb-excerpt" minlength="8" maxlength="500" required>${e(row.excerpt)}</textarea></div><div class="field"><label>Question maintenue ou modifiée</label><textarea id="spec-refresh-amb-question" minlength="8" maxlength="500" required>${e(row.question)}</textarea></div><div class="modal-actions"><button type="button" class="secondary" id="spec-cancel">Annuler</button><button type="submit" class="primary">Rouvrir sur la nouvelle version</button></div></form>`,true);
 overlay.querySelector('#spec-cancel').onclick=closeModal;
 overlay.querySelector('#spec-refresh-amb-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${state.detail.id}/ambiguities/${id}/refresh-source`,{method:'POST',body:JSON.stringify({new_source_version_id:doc.latest.id,excerpt:val('spec-refresh-amb-excerpt'),question:val('spec-refresh-amb-question')})});closeModal();toast('Point réexaminé et rouvert');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
}
