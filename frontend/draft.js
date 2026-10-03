/* Drafts are private to the signed-in user and survive navigation/reloads. */
window.SigamizDraft=(()=>{
 let key=null,restorePhotos=null,timer=null,fieldsFailed=false,photosFailed=false,pendingPhotos=0;
 const form=document.getElementById('listingForm');
 const fields=()=>[...form.querySelectorAll('input:not([type=file]),select,textarea')];
 const database=new Promise((resolve,reject)=>{const request=indexedDB.open('sigamiz-drafts',1);request.onupgradeneeded=()=>request.result.createObjectStore('photos');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
 database.catch(()=>{});
 async function photos(operation,value,capturedKey=key){if(!capturedKey)return;const db=await database;return new Promise((resolve,reject)=>{const transaction=db.transaction('photos',operation==='get'?'readonly':'readwrite');const store=transaction.objectStore('photos');const request=operation==='get'?store.get(capturedKey):operation==='put'?store.put(value,capturedKey):store.delete(capturedKey);transaction.oncomplete=()=>resolve(request.result);transaction.onerror=()=>reject(transaction.error||request.error);transaction.onabort=()=>reject(transaction.error||Error('Draft save aborted'));});}
 function save(){if(!key)return;const values={};fields().forEach(field=>values[field.id]=field.type==='checkbox'?field.checked:field.value);try{localStorage.setItem(key,JSON.stringify(values));fieldsFailed=false;}catch{fieldsFailed=true;document.getElementById('locationStatus').textContent='Brauzerda joy yetmadi: qoralama saqlanmadi.';}}
 form.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(save,250);});form.addEventListener('change',save);
 window.addEventListener('pagehide',save);window.addEventListener('beforeunload',event=>{save();if(key&&(fieldsFailed||photosFailed||pendingPhotos)){event.preventDefault();event.returnValue='';}});
 async function bind(userId,restore){const next=userId?'sigamiz-draft:'+userId:null;if(next===key)return;key=next;restorePhotos=restore;if(!key)return;const captured=key;try{const stored=JSON.parse(localStorage.getItem(key)||'{}');fields().forEach(field=>{if(field.id in stored){if(field.type==='checkbox')field.checked=Boolean(stored[field.id]);else field.value=stored[field.id];}});if(stored.lat&&stored.lng)document.getElementById('locationStatus').textContent='Qoralamadagi lokatsiya tiklandi.';const saved=await photos('get',null,captured);if(key===captured&&saved)restorePhotos(saved);}catch{/* Form remains usable when browser storage is disabled. */}}
 async function clear(){clearTimeout(timer);fieldsFailed=false;photosFailed=false;if(key){localStorage.removeItem(key);await photos('delete').catch(()=>{});}}
 async function savePhotos(value){pendingPhotos++;try{await photos('put',value);photosFailed=false;}catch{photosFailed=true;document.getElementById('locationStatus').textContent='Rasmlar qoralamada saqlanmadi; qolgan maydonlar saqlangan.';}finally{pendingPhotos--;}}
 return {bind,clear,savePhotos,save};
})();
