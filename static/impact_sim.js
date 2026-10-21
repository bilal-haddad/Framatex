'use strict';
/* MVP 0.10 — graphe explicable et simulateur non destructif.
 * Chaque texte issu de l'API est échappé avant insertion dans le HTML. */
function simNumber(value){
 if(value===null||value===undefined)return 'Non calculable';
 const n=Number(value);
 return Number.isFinite(n)?new Intl.NumberFormat('fr-FR',{maximumFractionDigits:4}).format(n):'Non calculable';
}
function simGraphHtml(graph){
 if(!graph||graph.limited)return `<p class="sim-empty">Le graphe technique est réservé aux utilisateurs habilités à consulter le sous-dossier Jaune.</p>`;
 const inputs=graph.nodes.filter(x=>x.kind==='input');
 const outputs=graph.nodes.filter(x=>x.kind==='derived');
 const processes=graph.nodes.filter(x=>x.kind==='process');
 const node=n=>`<div class="sim-node ${n.available?'available':'incomplete'}"><small>${e(n.kind==='input'?'Valeur de référence':'Résultat calculé')}</small><strong>${e(n.label)}</strong><span>${n.value!==null&&n.value!==undefined?`${e(simNumber(n.value))} ${e(n.unit||'')}`:'À renseigner'}</span>${n.stale_source?'<em>Source à revérifier</em>':''}</div>`;
 return `<div class="sim-graph" role="group" aria-label="Dépendances de calcul"><div class="sim-graph-col">${inputs.map(node).join('')}</div><div class="sim-graph-separator" aria-hidden="true">→</div><div class="sim-graph-col">${outputs.map(node).join('')}</div></div><div class="sim-edges"><strong>Relations de calcul</strong>${graph.edges.filter(x=>x.kind==='formula').map(edge=>`<div>${e(graph.nodes.find(n=>n.id===edge.source)?.label||edge.source)} → ${e(graph.nodes.find(n=>n.id===edge.target)?.label||edge.target)}</div>`).join('')}</div>${processes.length?`<div class="sim-edges"><strong>Circuits de vérification configurés</strong>${graph.edges.filter(x=>x.kind==='rule').map(edge=>`<div>${e(graph.nodes.find(n=>n.id===edge.source)?.label||edge.source)} → ${e(graph.nodes.find(n=>n.id===edge.target)?.label||edge.target)} : ${e(edge.meaning)}</div>`).join('')}</div>`:''}`;
}
function simResultsHtml(result){
 const deltaLabel=x=>x.delta===null?'—':`${Number(x.delta)>0?'+':''}${simNumber(x.delta)} ${e(x.unit)}`;
 return `<div class="sim-results"><div class="section-heading"><h3>Résultat indicatif</h3><span class="tag">Aucune donnée modifiée</span></div><div class="panel table-scroll"><table><thead><tr><th>Indicateur</th><th>Référence</th><th>Scénario</th><th>Écart</th></tr></thead><tbody>${result.outputs.map(x=>`<tr><td><strong>${e(x.label)}</strong></td><td>${simNumber(x.baseline)} ${e(x.baseline===null?'':x.unit)}</td><td>${simNumber(x.scenario)} ${e(x.scenario===null?'':x.unit)}</td><td>${deltaLabel(x)}</td></tr>`).join('')}</tbody></table></div>${result.warnings.map(w=>`<p class="sim-warning">${e(w)}</p>`).join('')}</div>`;
}
function renderImpactSimulation(){
 const graph=state.simGraph;
 if(!graph)return '';
 const accessible=!graph.limited;
 const inputs=(graph.nodes||[]).filter(x=>x.kind==='input');
 const history=state.simHistory||[];
 return `<section class="sim-section" aria-label="Graphe et simulation d'impact"><div class="section-heading"><div><h2>Graphe des dépendances et simulation</h2><small>Calculs expliqués, données sourcées</small></div>${accessible?`<button type="button" id="sim-reload" class="secondary tiny">Actualiser</button>`:''}</div>
 <p class="sim-help">Les liens de calcul sont explicites ; les autres dépendances correspondent aux règles de propagation actives. Le graphe et les calculs ne remplacent ni ORLI ni une validation métier.</p>
 <div class="panel sim-panel">${simGraphHtml(graph)}</div>
 ${accessible?`<div class="sim-two-cols"><div class="panel sim-entry"><h3>Tester une modification</h3><p>Renseignez seulement les valeurs que vous souhaitez faire varier. Les valeurs inchangées sont reprises des données métier enregistrées et leurs unités doivent correspondre.</p><form id="sim-form"><div class="field"><label for="sim-title">Nom du scénario</label><input id="sim-title" required minlength="3" maxlength="160" value="Variation des besoins matière"></div>${inputs.map(x=>`<div class="field"><label for="sim-${e(x.id)}">${e(x.label)} (${e(x.unit)})</label><input type="number" min="0" max="999999999" step="0.0001" id="sim-${e(x.id)}" ${x.available?`placeholder="Référence : ${e(x.value)}"`:'disabled placeholder="Consigner d’abord une valeur source"'} /></div>`).join('')}<div class="sim-actions"><button class="primary tiny" type="submit">Calculer l’impact</button>${can('value.write','jaune')?'<button class="secondary tiny" type="button" id="sim-save">Calculer et conserver</button>':''}</div></form><div id="sim-result" aria-live="polite"></div></div><div class="panel sim-history"><h3>Simulations enregistrées</h3>${history.length?history.map(row=>`<button type="button" class="sim-history-item" data-sim-history="${e(row.id)}"><strong>${e(row.title)}</strong><small>${niceDate(row.created_at)}</small><span>Voir les hypothèses et les écarts</span></button>`).join(''):'<p>Pas encore de scénario conservé. Les aperçus ne sont pas enregistrés automatiquement.</p>'}</div></div>`:''}</section>`;
}
function bindImpactSimulation(){
 app.querySelector('#sim-reload')?.addEventListener('click',()=>openLaunch(state.detail.id,state.folder));
 const form=app.querySelector('#sim-form');
 const send=async(save)=>{
   const changes={};
   for(const x of (state.simGraph?.nodes||[]).filter(n=>n.kind==='input'&&n.available)){
     const v=app.querySelector('#sim-'+x.id)?.value.trim();if(v)changes[x.id]=v;
   }
   if(!Object.keys(changes).length){toast('Indiquez au moins une valeur à faire varier.');return;}
   try{
     const report=await api('/api/launches/'+encodeURIComponent(state.detail.id)+'/impact-simulations',{method:'POST',body:JSON.stringify({title:app.querySelector('#sim-title').value,changes,save})});
     const root=app.querySelector('#sim-result');
     if(root)root.innerHTML=simResultsHtml(report.result);
     if(save){toast('Simulation enregistrée sans modifier les valeurs');state.simHistory=await api('/api/launches/'+encodeURIComponent(state.detail.id)+'/impact-simulations');renderDetail();}
   }catch(err){showErr(err)}
 };
 form?.addEventListener('submit',ev=>{ev.preventDefault();send(false)});
 app.querySelector('#sim-save')?.addEventListener('click',()=>send(true));
 app.querySelectorAll('[data-sim-history]').forEach(btn=>btn.addEventListener('click',()=>{
   const entry=(state.simHistory||[]).find(x=>x.id===btn.dataset.simHistory);if(!entry)return;
   modal('Simulation · '+entry.title,`<p class="modal-desc">Calcul conservé à la date indiquée : il n’est pas mis à jour lorsqu’un document évolue.</p>${simResultsHtml(entry.result)}<div class="modal-actions"><button class="secondary" id="cancel-modal">Fermer</button></div>`,true);
   overlay.querySelector('#cancel-modal').onclick=closeModal;
 }));
}
