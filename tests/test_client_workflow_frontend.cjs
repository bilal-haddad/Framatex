'use strict';
const assert=require('node:assert/strict'),fs=require('fs'),vm=require('vm');
const source=fs.readFileSync('static/client/api.js','utf8');
const moduleUrl=text=>'data:text/javascript;base64,'+Buffer.from(text).toString('base64');
(async()=>{
 const api=await import(moduleUrl(source));
 const ui=await import(moduleUrl(fs.readFileSync('static/client/components/ui.js','utf8')));
 let responseStatus=200,responseData={},calls=[];
 global.fetch=async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify(responseData),{status:responseStatus,headers:{'Content-Type':'application/json'}})};
 for(const [backend,expected] of [['account_pending','pending'],['account_suspended','suspended']]){
   responseStatus=403;responseData={detail:{code:backend,message:'Texte serveur'}};
   await assert.rejects(api.loginClient({email:'client@example.test',password:'TestPassword2026!'}),err=>err.code===expected);
 }
 responseStatus=401;responseData={detail:'Identifiants incorrects'};
 await assert.rejects(api.loginClient({email:'missing@example.test',password:'TestPassword2026!'}),err=>err.code==='invalid_credentials');
 responseStatus=200;responseData={status:'submitted'};
 await api.submitOrderRequest('owned-request');
 let call=calls.at(-1);assert.equal(call.url,'/api/client/order-requests/owned-request/status');
 assert.equal(call.options.method,'PATCH');assert.deepEqual(JSON.parse(call.options.body),{status:'submitted'});
 assert.equal(call.options.headers['X-Framatex-Request'],'1');
 await api.listDocumentRequests();assert.equal(calls.at(-1).url,'/api/client/document-requests');
 await api.getDocumentRequest('a/b');assert.equal(calls.at(-1).url,'/api/client/document-requests/a%2Fb');
 await api.listSharedDocuments();assert.equal(calls.at(-1).url,'/api/client/shared-documents');
 let sent;
 global.XMLHttpRequest=class{
   constructor(){this.upload={}}open(method,url){this.method=method;this.url=url}setRequestHeader(k,v){this.header=[k,v]}
   send(form){sent={form,url:this.url,credentials:this.withCredentials,header:this.header};this.status=201;this.response={status:'uploaded'};queueMicrotask(()=>this.onload())}
 };
 await api.uploadRequestedDocument('request-1',new File(['version 2'],'corrige.txt'));
 assert.equal(sent.url,'/api/client/document-requests/request-1/upload');assert(sent.credentials);
 assert.equal(sent.form.get('title'),null);assert.equal(sent.form.get('file').name,'corrige.txt');
 assert.deepEqual(sent.header,['X-Framatex-Request','1']);
 for(const [state,label] of Object.entries({draft:'Brouillon',submitted:'Envoyée',under_review:'En cours d’étude',accepted:'Acceptée',rejected:'Refusée'}))assert(ui.statusBadge(state).includes(label));
 assert(ui.documentStatusBadge('correction_required').includes('À corriger'));
 assert(ui.documentStatusBadge('<svg>').includes('&lt;svg&gt;'));
 const ctx={operationsClients:async()=>{},operationsClientRequest:async()=>{},operationsDocument:async()=>{},
   e:ui.esc,niceDate:x=>x,opsEmpty:x=>x};vm.createContext(ctx);
 vm.runInContext(fs.readFileSync('static/client-workflow-internal.js','utf8'),ctx);
 const item={id:'r1',title:'<script>titre</script>',description:'& texte',status:'uploaded',requested_by:'FRAMATEX',
   requested_at:'2026-10-21',request_number:'REQ-1',document:{versions:[{id:'v1',number:1,original_name:'tech.txt',sha256:'a'.repeat(64)}]},
   history:[{status:'uploaded',version:1,actor:'Client <b>A</b>',occurred_at:'2026-10-21',message:'<img src=x>'}]};
 ctx.item=item;const html=vm.runInContext('clientWorkflowDocument(item)',ctx);
 assert(html.includes('&lt;script&gt;')&&!html.includes('<script>'));assert(html.includes('&lt;img src=x&gt;'));
 assert(html.includes('Demander correction')&&html.includes('data-version="v1"'));
 item.status='accepted';assert(!vm.runInContext('clientWorkflowDocument(item)',ctx).includes('data-client-doc-decision'));
 console.log('Workflow Client UI : statuts, erreurs authentifiées, API isolées, dépôt et échappement OK');
})().catch(error=>{console.error(error);process.exitCode=1});
