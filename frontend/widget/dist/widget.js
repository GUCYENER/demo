(()=>{(function(){"use strict";let t=document.currentScript||document.querySelector("script[data-key]"),n={apiKey:(t==null?void 0:t.getAttribute("data-key"))||"",baseUrl:(()=>{let i=(t==null?void 0:t.getAttribute("src"))||"";try{return new URL(i,window.location.href).origin}catch(e){return window.location.origin}})(),title:(t==null?void 0:t.getAttribute("data-title"))||"NGSSAI Asistan",subtitle:(t==null?void 0:t.getAttribute("data-subtitle"))||"Size nas\u0131l yard\u0131mc\u0131 olabilirim?",placeholder:(t==null?void 0:t.getAttribute("data-placeholder"))||"Mesaj\u0131n\u0131z\u0131 yaz\u0131n...",position:(t==null?void 0:t.getAttribute("data-position"))||"right",theme:(t==null?void 0:t.getAttribute("data-theme"))||"dark",accentColor:(t==null?void 0:t.getAttribute("data-accent"))||"#7c6bff"};if(!n.apiKey){console.warn("[NGSSAI Widget] data-key attribute eksik. Widget y\xFCklenemedi.");return}let a={token:null,orgCode:null,dialogId:null,messages:[],isOpen:!1,isStreaming:!1,isConnecting:!1},g=`ngssai_widget_${n.apiKey.slice(-8)}`;function p(){try{let i=sessionStorage.getItem(g);if(i){let e=JSON.parse(i);a.token=e.token||null,a.dialogId=e.dialogId||null,a.orgCode=e.orgCode||null}}catch(i){}}function d(){try{sessionStorage.setItem(g,JSON.stringify({token:a.token,dialogId:a.dialogId,orgCode:a.orgCode}))}catch(i){}}let h=`
    :host { all: initial; }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    /* De\u011Fi\u015Fkenler */
    .ngssai-root {
      --acc:   ${n.accentColor};
      --acc2:  color-mix(in srgb, ${n.accentColor} 70%, #000);
      --bg1:   #0d0f14;
      --bg2:   #13161e;
      --bg3:   #1a1d27;
      --bg4:   #22263a;
      --bdr:   #2a2f45;
      --t1:    #e8eaf0;
      --t2:    #9da4ba;
      --t3:    #5a6080;
      --white: #ffffff;
      --green: #22c55e;
      --rad:   16px;
      --rad-sm:10px;
      --shadow: 0 24px 64px rgba(0,0,0,.55), 0 4px 16px rgba(0,0,0,.4);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
      color: var(--t1);
    }

    /* Floating Buton */
    .ngssai-fab {
      position: fixed;
      ${n.position==="left"?"left: 24px;":"right: 24px;"}
      bottom: 24px;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: linear-gradient(135deg, var(--acc), var(--acc2));
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 20px color-mix(in srgb, var(--acc) 40%, transparent);
      transition: transform .2s, box-shadow .2s;
      z-index: 2147483646;
    }
    .ngssai-fab:hover { transform: scale(1.08); box-shadow: 0 6px 28px color-mix(in srgb, var(--acc) 55%, transparent); }
    .ngssai-fab svg { width: 26px; height: 26px; fill: #fff; }
    .ngssai-fab .ngssai-fab-close { display: none; }
    .ngssai-fab.open .ngssai-fab-chat { display: none; }
    .ngssai-fab.open .ngssai-fab-close { display: block; }

    /* Bildirim rozeti */
    .ngssai-badge {
      position: absolute;
      top: -4px;
      right: -4px;
      width: 18px;
      height: 18px;
      background: #ef4444;
      border-radius: 50%;
      border: 2px solid #0d0f14;
      display: none;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      font-weight: 700;
      color: #fff;
    }
    .ngssai-badge.show { display: flex; }

    /* Chat Panel */
    .ngssai-panel {
      position: fixed;
      ${n.position==="left"?"left: 24px;":"right: 24px;"}
      bottom: 92px;
      width: 370px;
      max-width: calc(100vw - 32px);
      height: 560px;
      max-height: calc(100vh - 120px);
      background: var(--bg1);
      border: 1px solid var(--bdr);
      border-radius: var(--rad);
      box-shadow: var(--shadow);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      z-index: 2147483645;
      transition: opacity .2s, transform .2s;
      opacity: 0;
      transform: translateY(12px) scale(.97);
      pointer-events: none;
    }
    .ngssai-panel.open {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: all;
    }

    /* Panel Header */
    .ngssai-header {
      background: linear-gradient(135deg, var(--bg3), var(--bg2));
      border-bottom: 1px solid var(--bdr);
      padding: 14px 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }
    .ngssai-header-icon {
      width: 36px;
      height: 36px;
      border-radius: 10px;
      background: linear-gradient(135deg, var(--acc), var(--acc2));
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
    }
    .ngssai-header-icon svg { width: 18px; height: 18px; fill: #fff; }
    .ngssai-header-text { flex: 1; overflow: hidden; }
    .ngssai-header-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--t1);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .ngssai-header-status {
      font-size: 11px;
      color: var(--t3);
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .ngssai-status-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--green);
    }
    .ngssai-header-close {
      width: 28px;
      height: 28px;
      border-radius: 8px;
      background: none;
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--t3);
      transition: background .15s, color .15s;
    }
    .ngssai-header-close:hover { background: var(--bg4); color: var(--t1); }
    .ngssai-header-close svg { width: 16px; height: 16px; fill: currentColor; }

    /* Mesaj Alan\u0131 */
    .ngssai-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      scroll-behavior: smooth;
    }
    .ngssai-messages::-webkit-scrollbar { width: 4px; }
    .ngssai-messages::-webkit-scrollbar-track { background: transparent; }
    .ngssai-messages::-webkit-scrollbar-thumb { background: var(--bg4); border-radius: 2px; }

    /* Kar\u015F\u0131lama Mesaj\u0131 */
    .ngssai-welcome {
      text-align: center;
      padding: 24px 16px;
    }
    .ngssai-welcome-icon {
      width: 52px;
      height: 52px;
      border-radius: 14px;
      background: linear-gradient(135deg, var(--acc), var(--acc2));
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 12px;
    }
    .ngssai-welcome-icon svg { width: 26px; height: 26px; fill: #fff; }
    .ngssai-welcome h3 { font-size: 15px; font-weight: 600; color: var(--t1); margin-bottom: 6px; }
    .ngssai-welcome p { font-size: 12.5px; color: var(--t2); line-height: 1.5; }

    /* Mesaj Balonu */
    .ngssai-msg { display: flex; gap: 8px; align-items: flex-end; }
    .ngssai-msg.user { flex-direction: row-reverse; }

    .ngssai-msg-avatar {
      width: 26px;
      height: 26px;
      border-radius: 8px;
      flex-shrink: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 700;
      color: #fff;
    }
    .ngssai-msg.bot .ngssai-msg-avatar {
      background: linear-gradient(135deg, var(--acc), var(--acc2));
    }
    .ngssai-msg.user .ngssai-msg-avatar {
      background: var(--bg4);
    }

    .ngssai-msg-bubble {
      max-width: 78%;
      padding: 10px 13px;
      border-radius: 14px;
      font-size: 13.5px;
      line-height: 1.55;
    }
    .ngssai-msg.bot .ngssai-msg-bubble {
      background: var(--bg3);
      border: 1px solid var(--bdr);
      border-bottom-left-radius: 4px;
      color: var(--t1);
    }
    .ngssai-msg.user .ngssai-msg-bubble {
      background: linear-gradient(135deg, var(--acc), var(--acc2));
      border-bottom-right-radius: 4px;
      color: #fff;
    }
    .ngssai-msg-bubble p { margin: 0 0 6px; }
    .ngssai-msg-bubble p:last-child { margin-bottom: 0; }
    .ngssai-msg-bubble ul, .ngssai-msg-bubble ol { padding-left: 16px; margin: 4px 0; }
    .ngssai-msg-bubble li { margin-bottom: 2px; }
    .ngssai-msg-bubble strong { font-weight: 600; }
    .ngssai-msg-bubble code {
      background: rgba(0,0,0,.25);
      padding: 1px 5px;
      border-radius: 4px;
      font-family: monospace;
      font-size: 12px;
    }

    /* Yaz\u0131yor g\xF6stergesi */
    .ngssai-typing-dots {
      display: flex;
      gap: 4px;
      padding: 10px 14px;
    }
    .ngssai-typing-dots span {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--t3);
      animation: ngssaiDot 1.2s infinite;
    }
    .ngssai-typing-dots span:nth-child(2) { animation-delay: .2s; }
    .ngssai-typing-dots span:nth-child(3) { animation-delay: .4s; }
    @keyframes ngssaiDot {
      0%, 60%, 100% { transform: translateY(0); opacity: .4; }
      30% { transform: translateY(-5px); opacity: 1; }
    }

    /* Input Alan\u0131 */
    .ngssai-input-area {
      border-top: 1px solid var(--bdr);
      background: var(--bg2);
      padding: 12px;
      flex-shrink: 0;
    }
    .ngssai-input-row {
      display: flex;
      gap: 8px;
      align-items: flex-end;
    }
    .ngssai-input {
      flex: 1;
      background: var(--bg3);
      border: 1px solid var(--bdr);
      border-radius: var(--rad-sm);
      color: var(--t1);
      padding: 10px 12px;
      font-size: 13.5px;
      resize: none;
      outline: none;
      max-height: 120px;
      min-height: 40px;
      line-height: 1.45;
      transition: border-color .15s;
      font-family: inherit;
    }
    .ngssai-input::placeholder { color: var(--t3); }
    .ngssai-input:focus { border-color: var(--acc); }

    .ngssai-send {
      width: 40px;
      height: 40px;
      border-radius: 10px;
      background: linear-gradient(135deg, var(--acc), var(--acc2));
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: opacity .15s, transform .1s;
    }
    .ngssai-send:hover:not(:disabled) { opacity: .9; transform: scale(1.05); }
    .ngssai-send:disabled { opacity: .4; cursor: not-allowed; }
    .ngssai-send svg { width: 18px; height: 18px; fill: #fff; }

    .ngssai-footer {
      text-align: center;
      font-size: 10.5px;
      color: var(--t3);
      margin-top: 6px;
    }
    .ngssai-footer a { color: var(--acc); text-decoration: none; }

    /* Ba\u011Flan\u0131yor overlay */
    .ngssai-connecting {
      position: absolute;
      inset: 0;
      background: var(--bg1);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 14px;
      z-index: 10;
    }
    .ngssai-spinner {
      width: 36px;
      height: 36px;
      border: 3px solid var(--bg4);
      border-top-color: var(--acc);
      border-radius: 50%;
      animation: ngssaiSpin .7s linear infinite;
    }
    @keyframes ngssaiSpin { to { transform: rotate(360deg); } }
    .ngssai-connecting-text { font-size: 13px; color: var(--t2); }

    /* Hata */
    .ngssai-error-banner {
      background: rgba(239,68,68,.12);
      border: 1px solid rgba(239,68,68,.3);
      border-radius: var(--rad-sm);
      padding: 10px 12px;
      font-size: 12.5px;
      color: #fca5a5;
      display: flex;
      gap: 8px;
      align-items: flex-start;
      margin: 8px 16px 0;
    }
    .ngssai-new-chat {
      margin-top: 8px;
      background: none;
      border: 1px solid var(--bdr);
      border-radius: 8px;
      padding: 6px 12px;
      color: var(--t2);
      font-size: 12px;
      cursor: pointer;
      width: 100%;
      transition: background .15s;
    }
    .ngssai-new-chat:hover { background: var(--bg3); }
  `;function b(){return`
      <div class="ngssai-root">
        <!-- Floating Button -->
        <button class="ngssai-fab" id="ngssai-fab" aria-label="Destek sohbeti a\xE7">
          <svg class="ngssai-fab-chat" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <svg class="ngssai-fab-close" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg>
          <span class="ngssai-badge" id="ngssai-badge"></span>
        </button>

        <!-- Chat Panel -->
        <div class="ngssai-panel" id="ngssai-panel" role="dialog" aria-label="${n.title}">
          <!-- Header -->
          <div class="ngssai-header">
            <div class="ngssai-header-icon">
              <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            </div>
            <div class="ngssai-header-text">
              <div class="ngssai-header-title">${n.title}</div>
              <div class="ngssai-header-status">
                <span class="ngssai-status-dot"></span>
                <span id="ngssai-status-text">\xC7evrimi\xE7i</span>
              </div>
            </div>
            <button class="ngssai-header-close" id="ngssai-close" aria-label="Kapat">
              <svg viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Ba\u011Flan\u0131yor -->
          <div class="ngssai-connecting" id="ngssai-connecting">
            <div class="ngssai-spinner"></div>
            <div class="ngssai-connecting-text">Ba\u011Flan\u0131yor...</div>
          </div>

          <!-- Mesajlar -->
          <div class="ngssai-messages" id="ngssai-messages">
            <div class="ngssai-welcome">
              <div class="ngssai-welcome-icon">
                <svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </div>
              <h3>${n.title}</h3>
              <p>${n.subtitle}</p>
            </div>
          </div>

          <!-- Input -->
          <div class="ngssai-input-area">
            <div class="ngssai-input-row">
              <textarea
                class="ngssai-input"
                id="ngssai-input"
                placeholder="${n.placeholder}"
                rows="1"
                aria-label="Mesaj yaz"
              ></textarea>
              <button class="ngssai-send" id="ngssai-send" disabled aria-label="G\xF6nder">
                <svg viewBox="0 0 24 24"><path d="M22 2L11 13"/><path d="M22 2L15 22 11 13 2 9l20-7z"/></svg>
              </button>
            </div>
            <div class="ngssai-footer">
              Powered by <a href="#" target="_blank">NGSSAI</a>
            </div>
          </div>
        </div>
      </div>
    `}function u(i){return i?i.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>").replace(/`([^`]+)`/g,"<code>$1</code>").replace(/^### (.+)$/gm,"<strong>$1</strong>").replace(/^## (.+)$/gm,"<strong>$1</strong>").replace(/^# (.+)$/gm,"<strong>$1</strong>").replace(/^[-*] (.+)$/gm,"<li>$1</li>").replace(/(<li>.*<\/li>\n?)+/g,e=>`<ul>${e}</ul>`).replace(/\n/g,"<br>"):""}class m{constructor(){this.host=null,this.shadow=null,this.els={},this._streamController=null}mount(){this.host=document.createElement("ngssai-widget"),this.host.style.cssText="position:fixed;z-index:2147483647;pointer-events:none;top:0;left:0;",document.body.appendChild(this.host),this.shadow=this.host.attachShadow({mode:"open"});let e=document.createElement("style");e.textContent=h,this.shadow.appendChild(e);let s=document.createElement("div");s.innerHTML=b(),this.shadow.appendChild(s.firstElementChild),this.host.style.pointerEvents="none",this.shadow.querySelector(".ngssai-root").style.pointerEvents="all",this.els={fab:this.shadow.getElementById("ngssai-fab"),badge:this.shadow.getElementById("ngssai-badge"),panel:this.shadow.getElementById("ngssai-panel"),close:this.shadow.getElementById("ngssai-close"),messages:this.shadow.getElementById("ngssai-messages"),connecting:this.shadow.getElementById("ngssai-connecting"),input:this.shadow.getElementById("ngssai-input"),send:this.shadow.getElementById("ngssai-send"),status:this.shadow.getElementById("ngssai-status-text")},this._bindEvents()}_bindEvents(){this.els.fab.addEventListener("click",()=>this.toggle()),this.els.close.addEventListener("click",()=>this.close()),this.els.input.addEventListener("keydown",e=>{e.key==="Enter"&&!e.shiftKey&&(e.preventDefault(),this.sendMessage())}),this.els.input.addEventListener("input",()=>{let e=this.els.input;e.style.height="auto",e.style.height=Math.min(e.scrollHeight,120)+"px"}),this.els.send.addEventListener("click",()=>this.sendMessage())}toggle(){a.isOpen?this.close():this.open()}open(){a.isOpen=!0,this.els.fab.classList.add("open"),this.els.panel.classList.add("open"),this.els.badge.classList.remove("show"),a.token?(this._hideConnecting(),this.els.send.disabled=!1,this.els.input.focus()):this._connect()}close(){a.isOpen=!1,this.els.fab.classList.remove("open"),this.els.panel.classList.remove("open")}async _connect(){a.isConnecting=!0,this._showConnecting(),this.els.status.textContent="Ba\u011Flan\u0131yor...";try{let e=await fetch(`${n.baseUrl}/api/widget/token`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({api_key:n.apiKey})});if(!e.ok){let o=await e.json().catch(()=>({}));throw new Error(o.detail||"Token al\u0131namad\u0131")}let s=await e.json();a.token=s.access_token,a.orgCode=s.org_code,d(),await this._createDialog(),this._hideConnecting(),this.els.status.textContent="\xC7evrimi\xE7i",this.els.send.disabled=!1,a.isConnecting=!1,this.els.input.focus()}catch(e){a.isConnecting=!1,this._hideConnecting(),this._showError(`Ba\u011Flant\u0131 hatas\u0131: ${e.message}`),this.els.status.textContent="Ba\u011Flanamad\u0131"}}async _createDialog(){let e=await fetch(`${n.baseUrl}/api/dialogs`,{method:"POST",headers:{Authorization:`Bearer ${a.token}`,"Content-Type":"application/json"},body:JSON.stringify({title:"Widget Sohbeti",source_type:"widget"})});if(!e.ok)throw new Error("Dialog olu\u015Fturulamad\u0131");let s=await e.json();a.dialogId=s.id||s.dialog_id,d()}async sendMessage(){var o;let e=this.els.input.value.trim();if(!e||a.isStreaming||!a.token)return;this.els.input.value="",this.els.input.style.height="auto",this.els.send.disabled=!0,this._appendMessage("user",e),this._scrollToBottom();let s=this._showTyping();a.isStreaming=!0;try{a.dialogId||await this._createDialog();let l=await fetch(`${n.baseUrl}/api/dialogs/${a.dialogId}/messages`,{method:"POST",headers:{Authorization:`Bearer ${a.token}`,"Content-Type":"application/json"},body:JSON.stringify({content:e})});if(this._removeTyping(s),l.ok){let r=await l.json(),f=((o=r.assistant_message)==null?void 0:o.content)||r.content||r.response||r.message||"Yan\u0131t al\u0131namad\u0131.";this._appendBotMessage(f)}else{let r=await l.json().catch(()=>({}));if(l.status===401)a.token=null,a.dialogId=null,d(),this._appendBotMessage("Oturumunuz sona erdi. L\xFCtfen tekrar deneyin.");else throw new Error(r.detail||"Yan\u0131t al\u0131namad\u0131")}}catch(l){this._removeTyping(s),this._appendBotMessage(`Hata: ${l.message}`)}finally{a.isStreaming=!1,this.els.send.disabled=!1,this._scrollToBottom(),this.els.input.focus()}}_appendMessage(e,s){let o=e==="bot",l=o?"AI":"S",r=document.createElement("div");return r.className=`ngssai-msg ${o?"bot":"user"}`,r.innerHTML=`
        <div class="ngssai-msg-avatar">${l}</div>
        <div class="ngssai-msg-bubble">${o?u(s):this._escapeHtml(s)}</div>
      `,this.els.messages.appendChild(r),r}_appendBotMessage(e){return this._appendMessage("bot",e)}_escapeHtml(e){return e.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}_showTyping(){let e="typing_"+Date.now(),s=document.createElement("div");return s.className="ngssai-msg bot",s.id=e,s.innerHTML=`
        <div class="ngssai-msg-avatar">AI</div>
        <div class="ngssai-msg-bubble">
          <div class="ngssai-typing-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      `,this.els.messages.appendChild(s),this._scrollToBottom(),e}_removeTyping(e){var s;(s=this.shadow.getElementById(e))==null||s.remove()}_scrollToBottom(){this.els.messages.scrollTop=this.els.messages.scrollHeight}_showConnecting(){this.els.connecting.style.display="flex"}_hideConnecting(){this.els.connecting.style.display="none"}_showError(e){let s=document.createElement("div");s.className="ngssai-error-banner",s.innerHTML=`<span>\u26A0\uFE0F ${this._escapeHtml(e)}</span>`;let o=document.createElement("button");o.className="ngssai-new-chat",o.textContent="Yeniden Dene",o.addEventListener("click",()=>{s.remove(),this._connect()}),this.els.messages.appendChild(s),this.els.messages.appendChild(o)}}function c(){p();let i=new m;i.mount(),window.__ngssaiWidget=i}document.readyState==="loading"?document.addEventListener("DOMContentLoaded",c):c()})();})();
//# sourceMappingURL=widget.js.map
