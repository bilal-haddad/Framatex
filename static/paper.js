'use strict';
// 0.6 — Un QR est un raccourci de navigation, jamais une preuve d'habilitation.
function renderPaper(){
 const d=state.detail;
 const docs=d.folders.filter(f=>f.can_read).flatMap(f=>f.documents);
 return `<section class="paper-section" aria-label="Papier et passeports numériques">
 <div class="section-heading workflow-head"><div><h2>Passerelle papier et passeports numériques</h2>
 <small>Étiquette QR du lancement · empreintes et provenance des versions</small></div></div>
 <div class="panel paper-panel"><div><h3>Retrouver ce dossier depuis le papier</h3>
 <p>Imprimez une étiquette QR pour ce lancement. Après le scan, chaque personne doit se connecter et dispose uniquement de ses propres habilitations.</p>
 <button class="primary tiny" id="paper-qr">Voir l'étiquette QR</button></div><div><h3>Vérifier une version archivée</h3>
 <p>Un passeport montre l'auteur, la version, l'empreinte SHA-256, les décisions et l'état réel d'intégrité du fichier au moment de la vérification.</p>
 ${docs.length?`<div class="intake-docs">${docs.slice(0,20).map(doc=>`<button class="secondary tiny" data-paper-version="${e(doc.latest.id)}">${e(doc.title)} · v${doc.latest.number}</button>`).join('')}</div>`:'<span class="tag">Aucun document accessible</span>'}
 </div></div></section>`;
}
function bindPaper(){
 app.querySelector('#paper-qr')?.addEventListener('click',paperQR);
 app.querySelectorAll('[data-paper-version]').forEach(b=>b.addEventListener('click',()=>paperPassport(b.dataset.paperVersion)));
}
async function paperQR(){
 try{
  const d=state.detail;
  const result=await api(`/api/launches/${encodeURIComponent(d.id)}/paper-link`);
  modal('Étiquette QR du lancement',`<div class="paper-qr-content"><p class="modal-desc">${e(result.notice)}</p>
  <img class="paper-qr-image" src="/api/launches/${encodeURIComponent(d.id)}/paper-qr.png" alt="QR code du dossier">
  <p><strong>${e(result.launch_name)}</strong></p><code>${e(result.launch_id)}</code>
  <p class="workflow-help">Adresse encodée : ${e(result.url)}</p>
  <p class="permission-lock">Sur téléphone, l'adresse doit être accessible sur le réseau autorisé. L'adresse 127.0.0.1 ne fonctionne que sur l'ordinateur qui héberge le serveur.</p>
  <div class="modal-actions"><button class="secondary" id="paper-close">Fermer</button><button class="primary" id="paper-print">Ouvrir l'étiquette à imprimer</button></div></div>`,true);
  overlay.querySelector('#paper-close').onclick=closeModal;
  overlay.querySelector('#paper-print').onclick=()=>window.open(`/api/launches/${encodeURIComponent(d.id)}/paper-label`,'_blank','noopener');
 }catch(err){showErr(err)}
}
async function paperPassport(id){
 try{
  const p=await api(`/api/document-versions/${encodeURIComponent(id)}/passport`);
  const verified=p.integrity.status==='intact';
  const stateLabel={intact:'Empreinte et taille conformes',mismatch:'Incohérence détectée',missing:'Fichier absent du stockage',unavailable:'Lecture du stockage impossible'}[p.integrity.status]||'État inconnu';
  const rows=(p.reviews||[]).map(r=>`<div class="version-row"><div><strong>${e(r.decision)}</strong><div class="version-meta">${e(r.reviewer_name)} · ${niceDate(r.reviewed_at)}</div><p>${e(r.comment||'Sans commentaire')}</p></div></div>`).join('');
  modal(`Passeport · ${p.title}`,`<div class="paper-passport"><p class="modal-desc">Version ${p.version} ${p.is_current?'(courante)':'(archivée)'} · ${e(p.folder)} · ${e(p.document_type)}</p>
  <p><span class="tag ${verified?'green':'orange'}">${e(stateLabel)}</span></p>
  <div class="info-pair"><label>Fichier original</label><span>${e(p.original_filename)}</span></div>
  <div class="info-pair"><label>Auteur du dépôt</label><span>${e(p.uploader.name)} · ${niceDate(p.uploaded_at)}</span></div>
  <div class="info-pair"><label>Taille enregistrée</label><span>${sizeText(p.size)}</span></div>
  <div class="info-pair"><label>Empreinte SHA-256 enregistrée</label><code class="paper-digest">${e(p.sha256_registered)}</code></div>
  ${p.integrity.actual_sha256?`<div class="info-pair"><label>Empreinte recalculée</label><code class="paper-digest">${e(p.integrity.actual_sha256)}</code></div>`:''}
  ${p.previous_version?`<div class="info-pair"><label>Version précédente</label><span>v${p.previous_version.number} · ${e(p.previous_version.sha256_registered.slice(0,16))}…</span></div>`:''}
  <h3>Décisions liées à cette version</h3>${rows||'<p class="workflow-help">Aucune décision de validation enregistrée.</p>'}
  <p class="permission-lock">${e(p.notice)}</p><div class="modal-actions"><button class="secondary" id="paper-back">Fermer</button><button class="primary" id="paper-refresh">Recalculer l’empreinte</button></div></div>`,true);
  overlay.querySelector('#paper-back').onclick=closeModal;
  overlay.querySelector('#paper-refresh').onclick=()=>paperPassport(id);
 }catch(err){showErr(err)}
}
// La route du QR ne contient qu'un UUID ; ne jamais utiliser cet UUID comme permission.
function paperTargetFromHash(hash){
 const match=/^#\/launch\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.exec(hash||'');
 return match ? match[1] : null;
}
async function paperOpenDeepLink(){
 const id=paperTargetFromHash(window.location.hash);
 if(!id)return false;
 try{await openLaunch(id,'jaune');return true}catch(err){showErr(err);return false}
}
