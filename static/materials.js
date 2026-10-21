'use strict';
/* MVP 0.12 — rapprochement matière : quantités déclarées et preuves documentaires.
   Pas d'écriture ORLI ; tous les textes issus des dossiers sont échappés. */
function materialNumber(x){
 const n=Number(x);
 return Number.isFinite(n)?new Intl.NumberFormat('fr-FR',{maximumFractionDigits:3}).format(n):'—';
}
function materialSourceOptions(folder){
 const documents=state.detail?.folders.find(f=>f.slug===folder)?.documents||[];
 return documents.flatMap(d=>d.versions.map(v=>({id:v.id,label:`${d.title} · v${v.number} · ${v.original_name}`})));
}
function materialEvidenceSelect(slug){
 const sources=materialSourceOptions(slug);
 return `<div class="field"><label for="mat-source">Version du justificatif (${e(slug==='jaune'?'Technique · Jaune':'Réception · Rose')})</label><select id="mat-source" required><option value="">Sélectionner une version</option>${sources.map(v=>`<option value="${e(v.id)}">${e(v.label)}</option>`).join('')}</select>${sources.length?'':'<small>Déposez d’abord une pièce dans le sous-dossier concerné.</small>'}</div>`;
}
function materialSourceCell(source){
 if(!source||!source.available)return '<span class="tag orange">Source indisponible</span>';
 return `<button class="link" type="button" data-material-document="${e(source.document_id)}" data-material-version="${e(source.version_number)}" title="Télécharger cette version">${e(source.document_title)} · v${e(source.version_number)}</button>${source.stale?'<span class="tag orange">Version remplacée · à revérifier</span>':''}`;
}
function materialFlags(flags){
 const labels={'commande_supérieure_au_prévu':'Commandé au-delà du prévu','réception_supérieure_aux_commandes':'Réception supérieure aux commandes enregistrées','réception_sans_commande_enregistrée':'Réception sans commande enregistrée','commande_partielle_ou_non_saisie':'Commande partielle ou non saisie','réception_partielle_ou_non_saisie':'Réception partielle ou non saisie'};
 return flags.map(f=>`<span class="tag orange">${e(labels[f]||f)}</span>`).join('');
}
function renderMaterialReport(){
 const report=state.materials;
 if(!report)return '';
 const editPlan=can('launch.update')&&can('document.write','jaune');
 const order=editPlan;const receive=can('launch.update')&&can('document.write','rose');
 return `<section class="material-section" aria-label="Suivi et rapprochement des matières"><div class="section-heading"><div><h2>Traçabilité et rapprochement des matières</h2><small>Prévu / commandé / réceptionné · saisies justifiées</small></div>${editPlan?'<button type="button" class="primary tiny" id="material-create">Ajouter une matière</button>':''}</div>
 <p class="material-help">Les données affichées proviennent de déclarations associées à des documents du dossier. Il ne s’agit ni du stock ORLI ni d’une preuve automatique de conformité. Les écarts signalent des points à examiner, notamment en cas de livraisons partielles.</p>
 ${report.lines.length?report.lines.map(line=>`<article class="panel material-card"><div class="material-title"><div><h3>${e(line.label)} <small>${e(line.reference)}</small></h3><p>Unité commune : ${e(line.unit)}</p></div>${editPlan||receive?`<div class="material-actions">${editPlan?`<button class="secondary tiny" data-material-plan="${e(line.id)}">Réviser le prévu</button><button class="secondary tiny" data-material-entry="${e(line.id)}" data-kind="ordered">Enregistrer une commande</button>`:''}${receive?`<button class="secondary tiny" data-material-entry="${e(line.id)}" data-kind="received">Enregistrer une réception</button>`:''}</div>`:''}</div>
 <div class="material-metrics"><div><span>Prévu</span><strong>${materialNumber(line.planned)} ${e(line.unit)}</strong></div><div><span>Commandé</span><strong>${materialNumber(line.ordered)} ${e(line.unit)}</strong></div><div><span>Réceptionné</span><strong>${materialNumber(line.received)} ${e(line.unit)}</strong></div><div><span>Reste à recevoir*</span><strong>${materialNumber(line.to_receive)} ${e(line.unit)}</strong></div></div>
 <div class="material-flags">${materialFlags(line.flags)||'<span class="tag green">Aucun écart signalé</span>'}</div>
 <details><summary>Historique et justificatifs (${line.plan_history.length} prévision(s), ${line.movements.length} mouvement(s))</summary><div class="table-scroll"><table><thead><tr><th>Type</th><th>Quantité</th><th>Source</th><th>Commentaire</th><th>Date</th><th></th></tr></thead><tbody>
 ${line.plan_history.map(p=>`<tr><td>Prévision</td><td>${materialNumber(p.quantity)} ${e(line.unit)}</td><td>${materialSourceCell(p.source)}</td><td>${e(p.note)}</td><td>${niceDate(p.recorded_at)}</td><td>—</td></tr>`).join('')}
 ${line.movements.map(m=>`<tr><td>${m.kind==='ordered'?'Commande':'Réception'} ${m.cancelled_at?'<span class="tag orange">Annulé</span>':''}</td><td>${materialNumber(m.quantity)} ${e(line.unit)}</td><td>${materialSourceCell(m.source)}</td><td>${e(m.note)}${m.reference?` · ${e(m.reference)}`:''}${m.cancellation_reason?` · Annulation : ${e(m.cancellation_reason)}`:''}</td><td>${niceDate(m.recorded_at)}</td><td>${(m.kind==='ordered'?order:receive)&&!m.cancelled_at?`<button class="link" data-material-cancel="${e(m.id)}" data-line-id="${e(line.id)}">Annuler</button>`:'—'}</td></tr>`).join('')}</tbody></table></div></details></article>`).join(''):
 '<div class="panel material-empty">Aucune matière suivie pour ce lancement. Ajoutez une ligne à partir d’une fiche technique justifiant la quantité prévue.</div>'}
 <small class="material-help">* Reste à recevoir = commandé − réceptionné, d’après les mouvements non annulés. Les valeurs négatives méritent une vérification ; aucune quantité n’est corrigée automatiquement.</small></section>`;
}
function materialFormBase(slug,quantity=''){
 return `<div class="field"><label for="mat-quantity">Quantité (maximum 3 décimales)</label><input id="mat-quantity" required type="number" min="0" max="999999999999" step="0.001" value="${e(quantity)}"></div>${materialEvidenceSelect(slug)}<div class="field"><label for="mat-note">Justification (12 caractères minimum)</label><textarea id="mat-note" required minlength="12" maxlength="1500" rows="3" placeholder="Précisez la valeur retenue, la source et les vérifications réalisées."></textarea></div>`;
}
function bindMaterialForm(formId,url,method,extra){
 overlay.querySelector('#material-cancel-form').onclick=closeModal;
 overlay.querySelector('#'+formId).onsubmit=async ev=>{
   ev.preventDefault();
   const quantity=overlay.querySelector('#mat-quantity').value.trim();
   const payload={quantity,source_version_id:overlay.querySelector('#mat-source').value,note:overlay.querySelector('#mat-note').value,...extra()};
   try{await api(url,{method,body:JSON.stringify(payload)});closeModal();toast('Mouvement matière enregistré avec son justificatif');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}
 };
}
function materialCreate(){
 modal('Ajouter une matière',`<p class="modal-desc">Une matière est suivie par lancement. Le prévu initial doit être associé à une version présente dans le Jaune.</p><form id="material-create-form"><div class="two-fields"><div class="field"><label for="mat-ref">Référence matière</label><input id="mat-ref" required maxlength="100"></div><div class="field"><label for="mat-unit">Unité</label><select id="mat-unit">${['m','m²','kg','g','pcs','L'].map(x=>`<option>${e(x)}</option>`).join('')}</select></div></div><div class="field"><label for="mat-label">Désignation</label><input id="mat-label" required minlength="2" maxlength="180"></div>${materialFormBase('jaune')}<div class="modal-actions"><button class="secondary" type="button" id="material-cancel-form">Annuler</button><button class="primary" type="submit">Créer la matière</button></div></form>`,true);
 bindMaterialForm('material-create-form',`/api/launches/${state.detail.id}/materials`,'POST',()=>({reference:overlay.querySelector('#mat-ref').value,label:overlay.querySelector('#mat-label').value,unit:overlay.querySelector('#mat-unit').value}));
}
function materialRevision(lineId){
 const line=state.materials?.lines.find(x=>x.id===lineId);if(!line)return;
 modal('Réviser le prévu · '+line.label,`<p class="modal-desc">La valeur précédente reste dans l’historique. Un nouveau justificatif technique est requis.</p><form id="material-plan-form">${materialFormBase('jaune',line.planned)}<div class="modal-actions"><button class="secondary" type="button" id="material-cancel-form">Annuler</button><button class="primary" type="submit">Enregistrer la révision</button></div></form>`,true);
 bindMaterialForm('material-plan-form',`/api/launches/${state.detail.id}/materials/${line.id}/plans`,'POST',()=>({}));
}
function materialMovement(lineId,kind){
 const line=state.materials?.lines.find(x=>x.id===lineId);if(!line)return;
 const receipt=kind==='received',slug=receipt?'rose':'jaune';
 modal((receipt?'Réception':'Commande')+' · '+line.label,`<p class="modal-desc">Saisie contrôlée en ${e(line.unit)}. La pièce justificative doit être déposée dans le sous-dossier ${receipt?'Rose':'Jaune'}. Aucun mouvement de stock ORLI n’est créé.</p><form id="material-movement-form">${materialFormBase(slug)}<div class="two-fields"><div class="field"><label for="mat-counterparty">Fournisseur / interlocuteur</label><input id="mat-counterparty" maxlength="140"></div><div class="field"><label for="mat-movement-ref">Référence bon / commande</label><input id="mat-movement-ref" maxlength="100"></div></div><div class="modal-actions"><button type="button" class="secondary" id="material-cancel-form">Annuler</button><button class="primary" type="submit">Enregistrer</button></div></form>`,true);
 bindMaterialForm('material-movement-form',`/api/launches/${state.detail.id}/materials/${line.id}/movements`,'POST',()=>({kind,counterparty:overlay.querySelector('#mat-counterparty').value,reference:overlay.querySelector('#mat-movement-ref').value}));
 if(!receipt)overlay.querySelector('#mat-quantity').min='0.001';else overlay.querySelector('#mat-quantity').min='0.001';
}
function materialCancel(lineId,movementId){
 modal('Annuler une saisie de matière',`<p class="modal-desc">La saisie d’origine et son justificatif restent conservés. Elle sera exclue des totaux après cette annulation motivée.</p><form id="material-void-form"><div class="field"><label for="material-reason">Motif</label><textarea id="material-reason" minlength="12" maxlength="1500" required rows="3"></textarea></div><div class="modal-actions"><button type="button" id="material-void-close" class="secondary">Fermer</button><button type="submit" class="primary">Confirmer l’annulation</button></div></form>`,true);
 overlay.querySelector('#material-void-close').onclick=closeModal;
 overlay.querySelector('#material-void-form').onsubmit=async ev=>{ev.preventDefault();try{await api(`/api/launches/${state.detail.id}/materials/${lineId}/movements/${movementId}/cancel`,{method:'POST',body:JSON.stringify({reason:overlay.querySelector('#material-reason').value})});closeModal();toast('Annulation tracée');await openLaunch(state.detail.id,state.folder)}catch(err){showErr(err)}};
}
function bindMaterialReport(){
 app.querySelector('#material-create')?.addEventListener('click',materialCreate);
 app.querySelectorAll('[data-material-document]').forEach(btn=>btn.addEventListener('click',()=>download(btn.dataset.materialDocument,Number(btn.dataset.materialVersion))));
 app.querySelectorAll('[data-material-plan]').forEach(b=>b.addEventListener('click',()=>materialRevision(b.dataset.materialPlan)));
 app.querySelectorAll('[data-material-entry]').forEach(b=>b.addEventListener('click',()=>materialMovement(b.dataset.materialEntry,b.dataset.kind)));
 app.querySelectorAll('[data-material-cancel]').forEach(b=>b.addEventListener('click',()=>materialCancel(b.dataset.lineId,b.dataset.materialCancel)));
}
