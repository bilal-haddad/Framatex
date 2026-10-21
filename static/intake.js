'use strict';
// 0.5 — deux innovations complémentaires. Chaque suggestion reste révocable et vérifiée.
function renderIntake(){
 const docs=(state.detail?.folders||[]).filter(f=>f.can_read).flatMap(f=>f.documents);
 const editable=(state.detail?.folders||[]).some(f=>f.can_write);
 return `<section class="intake-section" aria-label="Lecture et classement assistés"><div class="section-heading workflow-head"><div><h2>Lecture et classement assistés</h2><small>OCR et extraction structurée · suggestions documentaires à confirmer</small></div></div><div class="panel intake-panel"><div><h3>Importer sans ressaisie inutile</h3><p>Analyse locale du fichier : propositions de classement, références, quantités, dates et montants. Aucun classement ni aucune valeur n'est enregistré sans confirmation.</p>${editable?`<button class="primary tiny" id="intake-open">Analyser un document</button>`:'<span class="tag">Dépôt non autorisé</span>'}</div><div><h3>Documents déjà enregistrés</h3>${docs.length?`<div class="intake-docs">${docs.slice(0,20).map(d=>`<button class="secondary tiny" data-intake-version="${e(d.latest.id)}">${e(d.title)} · v${d.latest.number}</button>`).join('')}</div>`:'<p>Aucune pièce accessible.</p>'}<p class="workflow-help">Les résultats de l’analyse n’équivalent pas à une validation métier. L’original reste la référence.</p></div></div></section>`;
}
function bindIntake(){
 app.querySelector('#intake-open')?.addEventListener('click',intakeOpen);
 app.querySelectorAll('[data-intake-version]').forEach(x=>x.addEventListener('click',()=>intakeExisting(x.dataset.intakeVersion)));
}
function renderCandidates(items){
 if(!items?.length)return `<p class="workflow-help">Aucun champ structuré détecté.</p>`;
 return `<div class="intake-candidates">${items.map((x,i)=>`<div class="intake-candidate"><strong>${e(x.key.replaceAll('_',' '))}</strong><span>${e(x.value)} ${e(x.unit||'')}</span><small>${e(x.source_excerpt||'')}</small></div>`).join('')}</div>`;
}
function intakeOpen(){
 const d=state.detail;
 modal('Analyser avant le dépôt',`<p class="modal-desc">Le fichier est lu localement. Confirmez le sous-dossier et le type proposés avant l'enregistrement.</p><form id="intake-file-form"><div class="field"><label>Document à analyser *</label><input id="intake-file" type="file" accept=".pdf,.docx,.xlsx,.png,.jpg,.jpeg,.txt,.eml" required /></div><div class="modal-actions"><button type="button" class="secondary" id="intake-cancel">Annuler</button><button class="primary" type="submit">Analyser</button></div></form><div id="intake-result"></div>`,true);
 overlay.querySelector('#intake-cancel').onclick=closeModal;
 overlay.querySelector('#intake-file-form').onsubmit=async ev=>{
  ev.preventDefault();const file=overlay.querySelector('#intake-file').files[0];if(!file)return;
  const fd=new FormData();fd.append('file',file);
  const zone=overlay.querySelector('#intake-result');zone.textContent='Analyse en cours…';
  try{
   const result=await api('/api/launches/'+d.id+'/intake/preview',{method:'POST',body:fd});
   const folders=d.folders.filter(x=>x.can_write);const top=result.classification.suggestions[0];const recommended=folders.some(f=>f.slug===top?.folder)?top?.folder:folders[0]?.slug;
   const types=['Autre',...new Set([...result.classification.suggestions.map(x=>x.doc_type),'Fiche d’emploi','Dossier technique','Bon de livraison','Facture'])];
   zone.innerHTML=`<div class="intake-analysis"><h3>Propositions à vérifier</h3><p class="workflow-help">Méthode : ${e(result.method)}. ${e(result.warnings.join(' · '))}</p><p class="workflow-help">${e(result.classification.suggestions.map(x=>x.doc_type+' : '+x.reason).join(' · ')||'Classement incertain : choisissez vous-même.')}</p><form id="intake-confirm-form"><div class="two-fields"><div class="field"><label>Sous-dossier confirmé *</label><select id="intake-folder">${folders.map(f=>`<option value="${e(f.slug)}" ${recommended===f.slug?'selected':''}>${e(f.label)}</option>`).join('')}</select></div><div class="field"><label>Type confirmé *</label><select id="intake-type">${types.map(t=>`<option value="${e(t)}" ${top?.doc_type===t?'selected':''}>${e(t)}</option>`).join('')}</select></div></div><div class="field"><label>Titre du document *</label><input id="intake-title" maxlength="220" required value="${e(file.name.replace(/\.[^.]+$/,''))}"></div><h3>Champs proposés (non encore validés)</h3>${renderCandidates(result.fields)}<div class="field"><label>Extrait détecté</label><textarea rows="4" readonly>${e(result.text_excerpt||'Aucun texte détecté')}</textarea></div><div class="modal-actions"><button type="button" class="secondary" id="intake-stop">Ne pas enregistrer</button><button type="submit" class="primary">Confirmer le classement et déposer</button></div></form></div>`;
   zone.querySelector('#intake-stop').onclick=closeModal;
   zone.querySelector('#intake-confirm-form').onsubmit=async event=>{event.preventDefault();try{const up=new FormData();up.append('folder',zone.querySelector('#intake-folder').value);up.append('doc_type',zone.querySelector('#intake-type').value);up.append('title',zone.querySelector('#intake-title').value.trim());up.append('file',file);const doc=await api('/api/launches/'+d.id+'/documents',{method:'POST',body:up});closeModal();toast('Dépôt confirmé · vous pouvez vérifier les champs extraits depuis le document');await openLaunch(d.id,doc.folder)}catch(err){showErr(err)}};
  }catch(err){zone.textContent='';showErr(err)}
 };
}
async function intakeExisting(versionId){
 try{
 const data=await api('/api/document-versions/'+encodeURIComponent(versionId)+'/intake');
 const pending=(data.fields||[]).filter(x=>!(data.confirmed||[]).some(y=>y.key===x.key));
 modal('Extraire et confirmer les champs',`<p class="modal-desc">Lecture ${e(data.method)}. Les champs extraits sont des propositions et ne modifient ni ORLI ni les valeurs métier déjà enregistrées.</p>${data.warnings?.length?`<p class="permission-lock">${e(data.warnings.join(' · '))}</p>`:''}<div class="field"><label>Extrait du document</label><textarea readonly rows="4">${e(data.text_excerpt)}</textarea></div><h3>Champs non encore confirmés</h3>${pending.length?pending.map(x=>`<div class="intake-field-row"><div class="workflow-meta">${e(x.key)} · ${e(x.source_excerpt)}</div><input aria-label="Valeur corrigée pour ${e(x.key)}" id="if-${e(x.key)}" value="${e(x.value)}" maxlength="140"/><button class="secondary tiny" data-intake-confirm="${e(x.key)}">Valider la valeur</button></div>`).join(''):'<p>Aucun nouveau champ proposé.</p>'}<h3>Champs confirmés</h3>${(data.confirmed||[]).map(x=>`<p class="workflow-meta">${e(x.key)} : ${e(x.value)} ${e(x.unit||'')}</p>`).join('')||'<p class="workflow-help">Aucun.</p>'}`,true);
 overlay.querySelectorAll('[data-intake-confirm]').forEach(el=>el.addEventListener('click',async()=>{
  const key=el.dataset.intakeConfirm;const candidate=pending.find(x=>x.key===key);if(!candidate)return;
  const value=overlay.querySelector('#if-'+key).value.trim();
  if(!value){toast('Saisir une valeur à confirmer');return}
  try{await api('/api/document-versions/'+encodeURIComponent(versionId)+'/intake/confirm',{method:'POST',body:JSON.stringify({field_key:key,value,unit:candidate.unit||'',source_excerpt:candidate.source_excerpt||''})});toast('Champ confirmé sur la version documentaire');await intakeExisting(versionId)}catch(err){showErr(err)}
 }));
 }catch(err){showErr(err)}
}
