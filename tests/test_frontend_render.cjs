// Test de rendu des fragments HTML, sans navigateur ni dépendance npm.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
let source = fs.readFileSync('static/app.js','utf8');
source = source.substring(0, source.lastIndexOf('(async function init(){'));
const ctx = {document:{querySelector:()=>({})},window:{addEventListener:()=>{}},console, setTimeout, clearTimeout};
vm.createContext(ctx);
vm.runInContext(source,ctx);
const output=vm.runInContext(`(()=>{
 state.me={admin:true,name:'Admin',roles:['Administrateur'],permissions:[]};
 state.detail={id:'launch-1',name:'Lancement de test'};
 state.completeness={phase:'preparation',profile_id:'p1',profile_name:'Profil de test',can_change_context:true,
  configured:true,visible_rules:3,partial_visibility:false,due_count:2,
  counts:{present:1,missing:1,pending_validation:0,not_due:1,exception:0},
  rows:[
   {id:'rule1',title:'Fiche d’emploi',folder:'jaune',document_type:'Fiche d’emploi',due_phase:'preparation',requires_validation:true,guidance:'',status:'present',documents:[{title:'Test',version:1}],can_review:true},
   {id:'rule2',title:'Bon de livraison',folder:'rose',document_type:'Bon de livraison',due_phase:'preparation',requires_validation:false,guidance:'Demander au service réception',status:'missing',documents:[],can_review:true},
   {id:'rule3',title:'Facture',folder:'vert',document_type:'Facture',due_phase:'cloture',requires_validation:false,guidance:'',status:'not_due',documents:[],can_review:false}
  ]};
 return renderCompleteness();
})()`,ctx);
for (const value of ['Complétude documentaire','Fiche d’emploi','Pièce manquante','Non applicable','Justifier','Profil de test']) {
 assert(output.includes(value), 'UI missing: '+value);
}
assert(!output.includes('undefined'), 'Le rendu contient undefined');
// Les données de l'utilisateur doivent être échappées dans le HTML.
const escaping = vm.runInContext(`(()=>{state.completeness.rows[1].title='<script>alert(1)</script>';return renderCompleteness()})()`,ctx);
assert(escaping.includes('&lt;script&gt;') && !escaping.includes('<script>'));
console.log('Frontend fragments OK : états, actions, échappement HTML.');
