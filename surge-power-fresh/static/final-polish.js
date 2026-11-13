document.addEventListener('DOMContentLoaded',()=>{
 const main=document.querySelector('main');
 if(main){if(!main.id)main.id='main-content';const skip=document.createElement('a');skip.className='skip-link';skip.href='#'+main.id;skip.textContent='Skip to main content';document.body.prepend(skip);}
 document.querySelectorAll('input[type=email]').forEach(el=>{el.autocomplete='email';});
 document.querySelectorAll('form[method=post]').forEach(form=>{
  form.addEventListener('submit',()=>{if(!form.checkValidity())return;form.setAttribute('aria-busy','true');const button=form.querySelector('button[type=submit],button:not([type])');if(button){setTimeout(()=>{button.disabled=true;},0);}});
 });
 window.addEventListener('pageshow',()=>{document.querySelectorAll('form[aria-busy=true]').forEach(form=>{form.removeAttribute('aria-busy');form.querySelectorAll('button').forEach(button=>button.disabled=false);});});
});
