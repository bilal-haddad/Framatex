'use strict';

const DOCUMENT_METHODS = {
  pdf_text: 'Texte du PDF', pdf_ocr: 'OCR du PDF', image_ocr: 'OCR de l’image',
  docx_text: 'Texte Word', xlsx_values: 'Cellules Excel', plain_text: 'Texte du fichier',
  email_text: 'Texte du courriel',
};

function stageDocument(url, folder, file, onProgress, onAnalysis) {
  const request = new XMLHttpRequest();
  const promise = new Promise((resolve, reject) => {
    let timer;
    let timedOut = false;
    const armTimeout = milliseconds => {
      clearTimeout(timer);
      timer = setTimeout(() => { timedOut = true; request.abort(); }, milliseconds);
    };
    request.open('POST', url);
    request.responseType = 'json';
    request.setRequestHeader('X-Framatex-Request', '1');
    request.upload.onprogress = event => {
      armTimeout(60000);
      if (event.lengthComputable) onProgress(event.loaded, event.total);
    };
    request.upload.onload = () => { armTimeout(150000); onAnalysis(); };
    request.onload = () => {
      if (request.status === 201 && request.response?.id) resolve(request.response);
      else reject(new Error(request.response?.detail || `Transfert refusé (HTTP ${request.status}).`));
    };
    request.onerror = () => reject(new Error('Transfert interrompu. Vérifiez la connexion puis réessayez.'));
    request.onabort = () => reject(new Error(timedOut ? 'Transfert interrompu après expiration du délai.' : 'Transfert annulé.'));
    request.onloadend = () => clearTimeout(timer);
    const data = new FormData();
    data.append('folder', folder);
    data.append('file', file);
    armTimeout(60000);
    request.send(data);
  });
  return {promise, abort: () => request.abort()};
}

async function documentUploadDialog(options) {
  const launch = state.detail;
  // Case de documents complémentaires : sous-dossier et type fixés, titre libre, plusieurs fichiers possibles.
  const optionalCase = options.optionalCase || null;
  const folders = launch.folders.filter(item => item.can_read && item.can_write && (!optionalCase || item.slug === optionalCase.folder));
  const start = folders.find(item => item.slug === (options.folder || state.folder)) || folders[0];
  if (!start) { toast('Vous ne pouvez pas déposer dans cette commande.'); return; }
  const [{mib}, catalog] = await Promise.all([api('/api/workspace/upload-limits'), api('/api/workspace/document-types')]);
  if (state.detail?.id !== launch.id) return;
  const rules = state.completeness?.rows || [];
  const base = `/api/launches/${encodeURIComponent(launch.id)}/document-uploads`;
  const fixed = Boolean(options.ruleId || options.document);
  const initialType = optionalCase ? 'Document complémentaire' : options.document?.doc_type || options.type || '';
  const initialTitle = optionalCase ? '' : options.document?.title || options.title || '';
  modal(options.document ? 'Déposer une nouvelle version' : optionalCase ? `Déposer · ${optionalCase.title}` : 'Déposer des documents', `
    <form id="ops-upload-form" class="dj-upload" novalidate>
      <p class="du-context">${e(launch.order_ref || launch.name)} · ${djFolderTitle(start.slug)}${fixed ? ` · ${e(initialTitle || initialType)}` : ''}${optionalCase ? ` · Documents complémentaires facultatifs · ${e(optionalCase.title)}` : ''}</p>
      <div class="du-drop" id="ops-upload-drop">
        ${icon('upload')}<strong>Glissez vos fichiers ici</strong>
        <input id="ops-file" type="file" hidden accept="${Object.keys(mib).join(',')}" ${options.document ? '' : 'multiple'}>
        <button type="button" class="secondary" id="du-browse">Parcourir les fichiers</button>
        <small>PDF ${mib['.pdf']} Mo · Excel ${mib['.xlsx']} Mo · Word ${mib['.docx']} Mo · Images ${mib['.png']} Mo · Autres ${mib['.txt']} Mo</small>
      </div>
      <ol id="du-files" class="du-files" aria-label="Fichiers sélectionnés"></ol>
      <p id="du-status" role="status" aria-live="polite"></p>
      <div id="du-transfer" hidden><label for="du-progress">Progression du transfert</label><progress id="du-progress" max="100"></progress></div>
      <div id="ops-analysis" aria-live="polite"></div>
      <div id="du-metadata" ${fixed ? 'hidden' : ''}>
        <div class="two-fields"><div class="field"><label for="ops-folder">Sous-dossier</label><select id="ops-folder">${folders.map(item => `<option value="${item.slug}">${djFolderTitle(item.slug)} · ${e(DJ_FOLDERS[item.slug].name)}</option>`).join('')}</select></div>
        <div class="field"><label for="ops-type">Type documentaire</label><input id="ops-type" list="ops-types" maxlength="100" autocomplete="off"${optionalCase ? ' readonly' : ''}><datalist id="ops-types"></datalist></div></div>
        <div class="field"><label for="ops-title">Titre affiché</label><input id="ops-title" maxlength="220"></div>
      </div>
      <details class="du-optional-note"><summary>+ Ajouter une note facultative</summary><div class="field"><label for="ops-upload-comment">Note liée à cette version</label><textarea id="ops-upload-comment" maxlength="2000" rows="2" placeholder="Préciser la raison du dépôt ou une modification importante…"></textarea></div></details>
      <div id="dj-version-note"></div>
      <div class="field" id="du-justification-field" hidden><label for="du-justification">Justification après vérification (facultative)</label><textarea id="du-justification" maxlength="1800" rows="2"></textarea></div>
      <p id="du-error" class="du-error" role="alert" hidden></p>
      <div class="modal-actions"><button type="button" class="secondary" id="cancel-modal">Fermer</button>
        <button type="button" class="secondary" id="du-cancel-file" hidden>Annuler ce fichier</button>
        <button type="button" class="secondary" id="du-retry" hidden>Réessayer</button>
        <button type="submit" class="primary" disabled>Confirmer le dépôt</button></div>
    </form>`, true);
  const form = overlay.querySelector('#ops-upload-form');
  const get = selector => form.querySelector(selector);
  const setText = (selector, value) => { get(selector).textContent = value; };
  const folder = get('#ops-folder');
  const type = get('#ops-type');
  const title = get('#ops-title');
  const submit = get('[type=submit]');
  const progress = get('#du-progress');
  const drop = get('#ops-upload-drop');
  let queue = [], active = null, transfer = null, staged = null, accepted = null, saving = false, closed = false;
  let relationshipChoice = '';
  let targetFolder = start.slug;
  const writable = launch.folders.flatMap(item => item.can_write ? item.documents || [] : []);

  function status(message) { setText('#du-status', message); }
  function error(message = '') { setText('#du-error', message); get('#du-error').hidden = !message; }
  function drawFiles() {
    get('#du-files').innerHTML = queue.map(item => `<li><span class="du-format">${e(item.extension.slice(1).toUpperCase() || 'Fichier')}</span>
      <span><strong>${e(item.file.name)}</strong><small>${sizeText(item.file.size)} · ${e(item.status)}</small></span></li>`).join('');
  }
  function setDestination(slug, kind, label) {
    folder.value = slug;
    type.value = kind;
    title.value = label;
    updateDestination();
  }
  function existingDocument() {
    if (relationshipChoice === 'new_version' && staged?.analysis?.relationships?.[0]) {
      const candidate = staged.analysis.relationships[0].candidate_document_id;
      return writable.find(item => item.id === candidate) || null;
    }
    return options.document || null;
  }
  function updateDestination() {
    const choices = [...new Set([...rules.filter(rule => rule.folder === folder.value).map(rule => rule.document_type),
      ...(catalog[folder.value]?.types || ['Autre'])])];
    get('#ops-types').innerHTML = choices.map(value => `<option value="${e(value)}"></option>`).join('');
    const existing = existingDocument();
    get('#dj-version-note').innerHTML = existing ? `<p>Ajout à « ${e(existing.title)} » · prochaine version V${existing.latest.number + 1}</p>
      ${options.document ? '' : '<label class="checkbox-line"><input type="checkbox" id="dj-separate"> Créer un document distinct</label>'}` : '';
    if (staged) drawAnalysis();
  }
  function defaultDestination() {
    setDestination(start.slug, initialType, initialTitle);
    get('#du-justification').value = '';
    get('#ops-upload-comment').value = '';
  }
  function drawAnalysis() {
    const data = staged.analysis;
    const classification = data.classification;
    const proposal = classification.suggestions[0];
    const selectedType = type.value.trim();
    // Case complémentaire : le choix de la case vaut classement (hors checklist standard).
    const conflict = !optionalCase && classification.decisive && selectedType && (proposal.canonical_type !== selectedType || proposal.folder !== folder.value);
    const matches = Boolean(optionalCase) || (classification.decisive && !conflict && Boolean(selectedType));
    const unavailable = !optionalCase && !classification.decisive;
    get('#du-justification-field').hidden = matches;
    const detectedOrder = data.fields.find(field => field.key === 'reference_commande' && field.status !== 'ambiguous');
    const message = optionalCase ? `Document complémentaire facultatif « ${optionalCase.title} » : il ne remplace aucune pièce de la checklist standard.`
      : conflict ? `Le document déposé semble être un ${proposal.doc_type}, alors que la pièce attendue est « ${selectedType} ».`
      : unavailable ? 'Type à vérifier. Les indices disponibles ne permettent pas de confirmer le classement.'
      : matches ? 'Le type détecté correspond au classement sélectionné.' : 'Confirmez le classement proposé ou choisissez un type.';
    const reason = data.warnings.join(' · ');
    const canMove = !optionalCase && proposal && classification.decisive && !options.document && !matches;
    const relationships = data.relationships || [];
    const related = options.document
      ? relationships.find(item => item.candidate_document_id === options.document.id) || relationships[0]
      : relationships[0];
    if (options.document && related?.candidate_document_id === options.document.id && !relationshipChoice) relationshipChoice = 'new_version';
    const relationLabel = {exact_duplicate: 'Doublon exact', potential_duplicate: 'Doublon potentiel', new_version: 'Nouvelle version probable'};
    const selectedRelation = value => relationshipChoice === value ? ' selected' : '';
    const relationChoices = related ? [
      (related.kind === 'new_version' || options.document?.id === related.candidate_document_id) && related.can_add_version ? `<option value="new_version"${selectedRelation('new_version')}>Ajouter comme nouvelle version du document proposé</option>` : '',
      options.document && related.candidate_document_id !== options.document.id
        ? `<option value="new_document"${selectedRelation('new_document')}>Ajouter comme nouvelle version de « ${e(options.document.title)} », sans rattachement</option>`
        : `<option value="new_document"${selectedRelation('new_document')}>Conserver comme nouveau document indépendant</option>`,
      `<option value="keep_duplicate"${selectedRelation('keep_duplicate')}>${options.document && related.candidate_document_id !== options.document.id ? `Ajouter à « ${e(options.document.title)} » en conservant le rapprochement signalé` : 'Conserver malgré le rapprochement signalé'}</option>`,
    ].filter(Boolean).join('') : '';
    get('#ops-analysis').innerHTML = `<section class="du-analysis ${conflict ? 'is-conflict' : ''}">
      <strong>${e(message)}</strong>
      ${DOCUMENT_METHODS[data.method] ? `<p>${e(DOCUMENT_METHODS[data.method])}</p>` : ''}
      ${reason ? `<p>${e(reason)}</p>` : ''}
      ${classification.suggestions.length ? `<ul>${classification.suggestions.map(candidate => `<li><b>${e(candidate.doc_type)}</b> · ${djFolderTitle(candidate.folder)}<small>${e(candidate.reason)}</small></li>`).join('')}</ul>` : ''}
      ${detectedOrder ? `<p>Référence repérée · <strong>${e(detectedOrder.value)}</strong></p>` : ''}
      ${data.text_excerpt ? `<details><summary>Voir l’extrait analysé</summary><p>${e(data.text_excerpt)}</p></details>` : ''}
      ${data.fields.length ? `<details><summary>Voir les valeurs à confirmer</summary>${renderCandidates(data.fields)}</details>` : ''}
      ${related ? `<div class="du-relationship"><strong>${e(relationLabel[related.kind])} · ${e(related.title)} · V${related.candidate_version}</strong>
        <ul>${related.evidence.map(item => `<li>${e(item)}</li>`).join('')}</ul>
        <div class="field"><label for="du-relationship-action">Décision du collaborateur</label><select id="du-relationship-action"><option value="">Choisir une action…</option>${relationChoices}</select></div>
        <div class="field" id="du-relationship-reason" ${relationshipChoice === 'keep_duplicate' ? '' : 'hidden'}><label for="du-relationship-note">Justification de conservation</label><textarea id="du-relationship-note" minlength="12" maxlength="1800" rows="2"></textarea></div>
        <small>Vous pouvez aussi annuler ce fichier. Aucun rapprochement n’est appliqué automatiquement.</small></div>` : ''}
      ${canMove ? `<button type="button" class="secondary tiny" id="du-correct">Classer dans ${djFolderTitle(proposal.folder)} · ${e(proposal.canonical_type)}</button>` : ''}
      ${!matches && selectedType ? '<label class="checkbox-line"><input type="checkbox" id="du-confirm-type"> Je confirme le type documentaire sélectionné.</label><p>Sans confirmation, le fichier est conservé avec un type à vérifier et ne compte pas dans la complétude.</p>' : ''}
    </section>`;
    get('#du-correct')?.addEventListener('click', () => {
      const rule = rules.find(item => item.folder === proposal.folder && item.document_type === proposal.canonical_type);
      setDestination(proposal.folder, proposal.canonical_type, rule?.title || proposal.canonical_type);
    });
    get('#du-relationship-action')?.addEventListener('change', event => {
      relationshipChoice = event.target.value;
      const note = get('#du-relationship-reason');
      note.hidden = relationshipChoice !== 'keep_duplicate';
      if (relationshipChoice === 'new_version') {
        setDestination(related.folder, related.doc_type, related.title);
      }
    });
    submit.textContent = conflict ? 'Conserver avec le classement sélectionné' : 'Confirmer le dépôt';
  }
  async function removeStage(item) {
    if (item) await api(`${base}/${encodeURIComponent(item.id)}`, {method: 'DELETE'}).catch(() => {});
  }
  async function finishDialog() {
    if (saving || closed) return;
    closed = true;
    transfer?.abort();
    closeModal();
    await removeStage(staged);
    if (accepted && state.detail?.id === launch.id) await refreshDocuments();
  }
  async function refreshDocuments() {
    const rule = rules.find(item => item.folder === targetFolder && item.document_type === accepted.doc_type);
    await openLaunch(launch.id, targetFolder, rule ? {rule_id: rule.id} : {row_document: accepted.id, folder: targetFolder});
  }
  async function processNext() {
    const next = queue.find(item => item.status === 'En attente');
    if (!next) return;
    active = next;
    staged = null;
    relationshipChoice = '';
    submit.disabled = true;
    get('#du-retry').hidden = true;
    get('#du-cancel-file').hidden = false;
    get('#du-justification-field').hidden = true;
    get('#ops-analysis').replaceChildren();
    get('#du-transfer').hidden = false;
    progress.removeAttribute('value');
    error();
    active.status = 'Transfert en cours';
    drawFiles();
    status(`Transfert de ${active.file.name}…`);
    const current = active;
    transfer = stageDocument(base, start.slug, active.file, (loaded, total) => {
      progress.value = 100 * loaded / total;
      status(`Transfert · ${sizeText(loaded)} / ${sizeText(total)}`);
    }, () => {
      active.status = 'Analyse en cours';
      drawFiles();
      status('Transfert terminé. Analyse documentaire en cours…');
    });
    try {
      const data = await transfer.promise;
      if (closed || active !== current) { await removeStage(data); return; }
      staged = data;
      active.status = 'Prêt à vérifier';
      if (!title.value.trim()) title.value = (optionalCase ? '' : type.value.trim()) || active.file.name.replace(/\.[^.]+$/, '').slice(0, 220);
      drawFiles();
      drawAnalysis();
      submit.disabled = false;
      status(`Vérifiez le classement de ${active.file.name}.`);
    } catch (failure) {
      if (closed || active !== current) return;
      active.status = 'Échec';
      drawFiles();
      error(failure.message);
      get('#du-retry').hidden = false;
      status('');
    } finally { if (active === current) transfer = null; }
  }
  function choose(files) {
    if (closed || saving) return;
    const selection = options.document ? Array.from(files).slice(0, 1) : Array.from(files);
    for (const file of selection) {
      const extension = '.' + (file.name.split('.').pop() || '').toLowerCase();
      const issue = !mib[extension] ? 'Format non autorisé' : !file.size ? 'Fichier vide'
        : file.size > mib[extension] * 1024 * 1024 ? `Limite de ${mib[extension]} Mo dépassée` : '';
      queue.push({file, extension, status: issue || 'En attente'});
    }
    drawFiles();
    if (!active) processNext();
  }
  async function cancelFile() {
    if (saving || !active) return;
    active.status = 'Annulé';
    active = null;
    transfer?.abort();
    const pending = staged;
    staged = null;
    submit.disabled = true;
    get('#du-cancel-file').hidden = get('#du-retry').hidden = get('#du-transfer').hidden = true;
    get('#du-justification-field').hidden = true;
    get('#ops-analysis').replaceChildren();
    error();
    status('Fichier annulé.');
    drawFiles();
    await removeStage(pending);
    defaultDestination();
    processNext();
  }
  form.onsubmit = async event => {
    event.preventDefault();
    if (!staged || saving || closed) return;
    const selectedType = type.value.trim();
    const selectedFolder = folder.value;
    if (!selectedType || !title.value.trim()) { error('Renseignez le type et le titre du document.'); return; }
    const related = staged.analysis.relationships?.[0];
    if (related && !relationshipChoice) { error('Choisissez comment traiter le rapprochement documentaire proposé.'); return; }
    const relationshipReason = get('#du-relationship-note')?.value.trim() || '';
    if (relationshipChoice === 'keep_duplicate' && relationshipReason.length < 12) { error('Justifiez la conservation du doublon en au moins 12 caractères.'); return; }
    const input = get('#du-justification');
    const justification = input.closest('[hidden]') ? '' : input.value.trim();
    const rule = rules.find(item => item.folder === selectedFolder && item.document_type === selectedType);
    const existing = relationshipChoice === 'new_version'
      ? writable.find(item => item.id === related?.candidate_document_id)
      : get('#dj-separate')?.checked ? null : existingDocument();
    saving = true;
    submit.disabled = true;
    get('#cancel-modal').disabled = true;
    error();
    status('Enregistrement du classement…');
    try {
      accepted = await api(`${base}/${encodeURIComponent(staged.id)}/publish`, {method: 'POST', body: JSON.stringify({
        folder: selectedFolder, doc_type: selectedType, title: title.value.trim(), rule_id: rule?.id,
        document_id: existing?.id, comment: get('#ops-upload-comment').value, justification,
        confirm_type: Boolean(get('#du-confirm-type')?.checked),
        relationship_action: relationshipChoice || null,
        relationship_candidate_version_id: related?.candidate_version_id || null,
        relationship_reason: relationshipReason, optional_case_id: optionalCase?.id || null,
      })});
      if (existing) existing.latest = accepted.latest;
      else writable.push(accepted);
      targetFolder = selectedFolder;
      active.status = `Déposé · V${accepted.latest.number}${['to_verify', 'incompatible'].includes(accepted.identification) ? ' · type à vérifier' : ''}`;
      active = staged = null;
      relationshipChoice = '';
      get('#du-cancel-file').hidden = get('#du-justification-field').hidden = get('#du-transfer').hidden = true;
      get('#ops-analysis').replaceChildren();
      drawFiles();
      status('Document déposé.');
      defaultDestination();
      if (queue.length === 1) {
        saving = false;
        const intent = fxIntent;
        await finishDialog();
        toast(`Document déposé · V${accepted.latest.number}`);
        // Réouverture de la fiche sur la nouvelle version, sauf si l'utilisateur a entre-temps
        // ouvert autre chose : une suite plus ancienne n'écrase pas son action.
        if (options.document && fxIntent === intent && !overlay.querySelector('.modal')) await operationsDocument(accepted.id, accepted.latest.id);
      } else {
        await refreshDocuments();
        processNext();
      }
    } catch (failure) { error(failure.message); status(''); }
    finally { saving = false; submit.disabled = !staged; get('#cancel-modal').disabled = false; }
  };
  get('#du-browse').onclick = () => get('#ops-file').click();
  get('#ops-file').onchange = event => { choose(event.target.files); event.target.value = ''; };
  for (const eventName of ['dragenter', 'dragover']) drop.addEventListener(eventName, event => { event.preventDefault(); drop.classList.add('is-dragging'); });
  drop.ondragleave = event => { if (!drop.contains(event.relatedTarget)) drop.classList.remove('is-dragging'); };
  drop.ondrop = event => { event.preventDefault(); drop.classList.remove('is-dragging'); choose(event.dataTransfer.files); };
  get('#cancel-modal').onclick = () => finishDialog().catch(showErr);
  form.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.stopPropagation(); get('#cancel-modal').click(); }
  });
  overlay.querySelector('#close-modal').onclick = get('#cancel-modal').onclick;
  overlay.querySelector('.modal-scrim').addEventListener('click', event => {
    if (event.target.classList.contains('modal-scrim')) { event.stopImmediatePropagation(); get('#cancel-modal').click(); }
  }, true);
  get('#du-cancel-file').onclick = () => cancelFile().catch(showErr);
  get('#du-retry').onclick = () => { if (active) active.status = 'En attente'; processNext(); };
  folder.onchange = updateDestination;
  if (optionalCase) folder.disabled = true;
  type.oninput = updateDestination;
  defaultDestination();
  get('#du-browse').focus();
  if (options.file) choose([options.file]);
}
