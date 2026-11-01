/* No OAuth values are read, stored or sent by this page. */
const closeButton=document.getElementById('close-window');
if(closeButton)closeButton.onclick=()=>window.close();
// Script-opened sign-in windows can close themselves; normal tabs keep the return instructions.
if(document.body.hasAttribute('data-google-connected'))setTimeout(()=>window.close(),1800);
