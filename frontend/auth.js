/* One login lifecycle for map, publication and saved listings. */
window.SigamizAuth=(()=>{
 let timer=null,busy=false,onSuccess=async()=>{},targets=[];
 function stop(){clearTimeout(timer);timer=null;busy=false;}
 async function start(){
  if(busy)return;busy=true;
  const popup=window.open('about:blank','_blank');
  try{
   const response=await fetch('/api/auth/telegram/start',{method:'POST'});
   if(!response.ok)throw Error('Kirishni boshlashning iloji bo‘lmadi');
   const session=await response.json();
   targets.forEach(target=>{let notice=target.querySelector('.login-code');if(!notice){notice=document.createElement('div');notice.className='login-code';target.append(notice);}notice.replaceChildren(document.createTextNode('Botda kirishni tasdiqlash uchun shu kodni yuboring:'));const code=document.createElement('strong');code.textContent=session.code;notice.append(code);const link=document.createElement('a');link.href=session.bot_url;link.target='_blank';link.rel='noopener';link.textContent='Telegram botini ochish â†’';notice.append(link);});
   if(popup){popup.opener=null;popup.location.href=session.bot_url;}
   const deadline=Date.now()+600000;
   async function poll(){
    try{const res=await fetch('/api/auth/telegram/complete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:session.token})});if(res.status===404||Date.now()>deadline)throw Error('Kod muddati tugadi. Kirishni qayta boshlang.');if(!res.ok)throw Error('Kirish tekshiruvida xatolik. Qayta urinib ko‘ring.');const data=await res.json();if(data.ok){stop();await onSuccess();await mount(targets[0],onSuccess);return;}timer=setTimeout(poll,1800);}catch(error){stop();targets.forEach(t=>{const notice=t.querySelector('.login-code');if(notice)notice.textContent=error.message;});}
   }
   timer=setTimeout(poll,1200);
  }catch(error){stop();popup?.close();targets.forEach(t=>{let message=document.createElement('p');message.setAttribute('role','alert');message.textContent=error.message;t.append(message);});}
 }
 async function mount(target,success){if(!target)return;onSuccess=success;targets=[target];target.replaceChildren();const data=await fetch('/api/me').then(r=>r.json()).catch(()=>({user:null}));if(data.user){const button=document.createElement('button');button.type='button';button.className='ghost account-action';button.textContent='Akkauntdan chiqish';button.onclick=()=>logout().catch(error=>{const message=document.createElement('p');message.setAttribute('role','alert');message.textContent=error.message;target.append(message);});target.append(button);return;}const button=document.createElement('button');button.type='button';button.className='ghost account-action';button.textContent='Telegram orqali kirish';button.onclick=start;target.append(button);}
 async function logout(){const res=await fetch('/api/logout',{method:'POST'});if(!res.ok)throw Error('Chiqib bo‘lmadi');stop();location.reload();}
 window.addEventListener('pagehide',stop);
 return {mount,start,logout};
})();
