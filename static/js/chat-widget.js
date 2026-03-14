/**
 * WizzardChat Embeddable Widget
 * Include via: <script> window.WizzardChat = { apiKey: 'xxx', serverUrl: 'https://...' }; </script>
 * <script src=".../static/js/chat-widget.js"></script>
 */
(function () {
  'use strict';

  var cfg = window.WizzardChat || {};
  if (!cfg.apiKey || !cfg.serverUrl) {
    console.warn('[WizzardChat] Missing apiKey or serverUrl');
    return;
  }

  // Guard against double-instantiation (e.g. script loaded twice via cache)
  if (window._WizzardChatLoaded === cfg.apiKey) return;
  window._WizzardChatLoaded = cfg.apiKey;

  // \u2500\u2500 Session ID (persisted per browser session) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  var SESSION_KEY = 'wc_session_' + cfg.apiKey;
  var sessionId = sessionStorage.getItem(SESSION_KEY);
  if (!sessionId) {
    sessionId = 'vs_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    sessionStorage.setItem(SESSION_KEY, sessionId);
  }

  // \u2500\u2500 SSE + HTTP POST \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  var es = null;           // EventSource
  var initSent = false;    // prevent double-init across reconnects
  var wasConnected = false; // has this session ever reached OPEN state?
  var serverBase = cfg.serverUrl.replace(/\/$/, '');
  var sseUrl   = serverBase + '/sse/chat/' + cfg.apiKey + '/' + sessionId;
  var postBase = serverBase + '/chat/' + cfg.apiKey + '/' + sessionId;

  // \u2500\u2500 Widget config (overridden by server on connect) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  var style = {
    primary_color: cfg.primary_color || '#0d6efd',
    bg_color: cfg.bg_color || '#ffffff',
    text_color: cfg.text_color || '#212529',
    title: cfg.title || 'Chat with us',
    subtitle: cfg.subtitle || 'We typically reply within minutes',
    logo_url: cfg.logo_url || '',
    position: cfg.position || 'bottom-right',
    width: cfg.width || '370px',
    height: cfg.height || '520px',
    border_radius: cfg.border_radius || '12px',
  };

  // \u2500\u2500 State \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  var isOpen = false;
  var menuPending = null;  // current menu options waiting for selection
  var agentName = null;

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // CSS injection
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function injectStyles() {
    var css = [
      '#wc-launcher{position:fixed;bottom:20px;z-index:999999;cursor:pointer;width:54px;height:54px;border-radius:50%;',
      'display:flex;align-items:center;justify-content:center;box-shadow:0 4px 16px rgba(0,0,0,.28);',
      'background:' + style.primary_color + ';transition:transform .2s;}',
      '#wc-launcher:hover{transform:scale(1.08);}',
      '#wc-launcher svg{width:26px;height:26px;fill:#fff;}',
      '#wc-launcher .wc-unread{position:absolute;top:0;right:0;background:#dc3545;color:#fff;',
      'border-radius:50%;width:18px;height:18px;font-size:11px;font-weight:700;',
      'display:flex;align-items:center;justify-content:center;display:none;}',
      '#wc-panel{position:fixed;bottom:84px;z-index:999998;',
      'width:' + style.width + ';max-width:calc(100vw - 16px);height:' + style.height + ';',
      'max-height:calc(100vh - 100px);',
      'border-radius:' + style.border_radius + ';overflow:hidden;',
      'box-shadow:0 8px 32px rgba(0,0,0,.22);display:none;flex-direction:column;',
      'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:14px;',
      'background:' + style.bg_color + ';color:' + style.text_color + ';}',
      '#wc-panel.wc-open{display:flex;}',
      '.wc-right{right:20px;}',
      '.wc-left{left:20px;}',
      '#wc-header{background:' + style.primary_color + ';color:#fff;padding:12px 14px;',
      'display:flex;align-items:center;gap:10px;flex-shrink:0;}',
      '#wc-header .wc-logo{width:34px;height:34px;border-radius:50%;object-fit:cover;}',
      '#wc-header .wc-hinfo{flex:1;min-width:0;}',
      '#wc-header .wc-htitle{font-weight:700;font-size:15px;margin:0;line-height:1.2;}',
      '#wc-header .wc-hsub{font-size:11px;opacity:.82;margin:0;}',
      '#wc-header .wc-restart{cursor:pointer;opacity:.7;margin-left:2px;line-height:1;font-size:15px;',
      'background:rgba(255,255,255,.18);border:none;color:#fff;border-radius:50%;width:26px;height:26px;',
      'display:flex;align-items:center;justify-content:center;padding:0;}',
      '#wc-header .wc-restart:hover{opacity:1;background:rgba(255,255,255,.3);}',
      '#wc-header .wc-close{cursor:pointer;opacity:.8;margin-left:4px;line-height:1;font-size:20px;}',
      '#wc-header .wc-close:hover{opacity:1;}',
      '#wc-end-row{display:flex;justify-content:center;padding:6px 10px 2px;border-top:1px solid #f0f0f0;}',
      '#wc-end-btn{font-size:11.5px;color:#dc3545;background:none;border:none;cursor:pointer;',
      'opacity:.75;padding:2px 8px;border-radius:4px;display:flex;align-items:center;gap:4px;transition:opacity .15s,background .15s;}',
      '#wc-end-btn:hover{opacity:1;background:rgba(220,53,69,.08);}',
      '#wc-end-btn.wc-hidden{display:none;}',
      '#wc-end-btn svg{width:12px;height:12px;fill:#dc3545;}',
      '.wc-ended-banner{text-align:center;padding:10px 14px;font-size:12.5px;color:#6c757d;',
      'border-top:1px solid #f0f0f0;background:#f8f9fa;display:none;}',
      '.wc-ended-banner.wc-show{display:block;}',
      '.wc-ended-banner a{color:inherit;text-decoration:underline;cursor:pointer;}',
      '#wc-msgs{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;',
      'background:' + style.bg_color + ';}',
      '.wc-bubble{max-width:82%;padding:9px 12px;border-radius:16px;line-height:1.45;',
      'word-break:break-word;font-size:13.5px;}',
      '.wc-bubble.wc-bot{background:#f0f2f5;color:#212529;border-bottom-left-radius:4px;align-self:flex-start;}',
      '.wc-bubble.wc-agent{background:#e8f0fe;color:#1a237e;border-bottom-left-radius:4px;align-self:flex-start;}',
      '.wc-bubble.wc-visitor{align-self:flex-end;border-bottom-right-radius:4px;color:#fff;}',
      '.wc-menu-options{display:flex;flex-direction:column;gap:6px;align-self:flex-start;max-width:82%;}',
      '.wc-menu-option{padding:7px 14px;border-radius:20px;border:1.5px solid ' + style.primary_color + ';',
      'cursor:pointer;font-size:13px;color:' + style.primary_color + ';background:#fff;transition:all .15s;}',
      '.wc-menu-option:hover,.wc-menu-option.wc-sel{background:' + style.primary_color + ';color:#fff;}',
      '.wc-menu-option.wc-sel{pointer-events:none;}',
      '.wc-label-agent{font-size:11px;color:' + style.primary_color + ';font-weight:600;margin-bottom:2px;align-self:flex-start;}',
      '.wc-label-bot{font-size:11px;color:#888;margin-bottom:2px;align-self:flex-start;}',
      '.wc-system{font-size:12px;color:#888;align-self:center;padding:4px 10px;',
      'background:#f8f9fa;border-radius:12px;text-align:center;}',
      '.wc-typing{align-self:flex-start;color:#888;font-size:12px;font-style:italic;display:none;}',
      '#wc-footer{padding:8px 10px;border-top:1px solid #e9ecef;flex-shrink:0;',
      'background:' + style.bg_color + ';}',
      '#wc-input-row{display:flex;gap:6px;align-items:flex-end;}',
      '#wc-input{flex:1;border:1.5px solid #dee2e6;border-radius:20px;padding:7px 14px;',
      'font-size:13.5px;outline:none;resize:none;max-height:80px;overflow-y:auto;',
      'font-family:inherit;}',
      '#wc-input:focus{border-color:' + style.primary_color + ';}',
      '#wc-send{width:36px;height:36px;border-radius:50%;border:none;cursor:pointer;',
      'display:flex;align-items:center;justify-content:center;flex-shrink:0;',
      'background:' + style.primary_color + ';}',
      '#wc-send:disabled{opacity:.4;cursor:default;}',
      '#wc-send svg{width:16px;height:16px;fill:#fff;}',
      '.wc-status{font-size:11px;color:#888;margin-top:4px;padding-left:4px;min-height:16px;}',
      // Emoji & attachment extras
      '#wc-emoji-btn,#wc-attach-btn{background:none;border:none;cursor:pointer;',
      'width:30px;height:30px;border-radius:50%;display:flex;align-items:center;',
      'justify-content:center;flex-shrink:0;opacity:.65;font-size:17px;transition:opacity .15s,background .15s;}',
      '#wc-emoji-btn:hover,#wc-attach-btn:hover{opacity:1;background:rgba(0,0,0,.07);}',
      '#wc-input-wrap{position:relative;}',
      '#wc-emoji-picker{position:absolute;bottom:calc(100% + 6px);left:0;',
      'background:#fff;border:1px solid #dee2e6;border-radius:10px;padding:6px;',
      'display:none;flex-wrap:wrap;gap:1px;',
      'width:272px;max-height:192px;overflow-y:auto;',
      'box-shadow:0 4px 16px rgba(0,0,0,.16);z-index:1000001;}',
      '#wc-emoji-picker.wc-ep-open{display:flex;}',
      '#wc-emoji-picker button{background:none;border:none;font-size:19px;',
      'width:30px;height:30px;cursor:pointer;border-radius:4px;',
      'display:inline-flex;align-items:center;justify-content:center;padding:0;transition:background .1s;}',
      '#wc-emoji-picker button:hover{background:#f0f2f5;}',
      '.wc-attach-bubble{display:flex;flex-direction:column;gap:4px;max-width:82%;align-self:flex-start;}',
      '.wc-attach-bubble.wc-visitor{align-self:flex-end;}',
      '.wc-attach-img{max-width:220px;max-height:160px;border-radius:10px;display:block;cursor:pointer;}',
      '.wc-attach-file{display:flex;align-items:center;gap:6px;padding:8px 12px;',
      'border:1.5px solid #dee2e6;border-radius:12px;background:#f8f9fa;',
      'font-size:12.5px;color:#0d6efd;text-decoration:none;word-break:break-all;}',
      '.wc-attach-file:hover{background:#e8f0fe;}',
      '.wc-attach-file .wc-attach-icon{font-size:18px;}',
      // Nudge (proactive teaser bubble)
      '#wc-nudge{position:fixed;z-index:999997;display:none;background:#fff;',
      'border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.2);padding:10px 30px 10px 12px;',
      'max-width:240px;cursor:pointer;animation:wc-nudge-in .3s ease;bottom:84px;}',
      '#wc-nudge.wc-right{right:16px;}#wc-nudge.wc-left{left:16px;}',
      '#wc-nudge-close{position:absolute;top:4px;right:6px;background:none;border:none;',
      'font-size:14px;cursor:pointer;color:#aaa;padding:0;line-height:1;}',
      '#wc-nudge-close:hover{color:#555;}',
      '#wc-nudge-msg{margin:0;color:#212529;font-size:13.5px;line-height:1.45;',
      'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;}',
      '@keyframes wc-nudge-in{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:translateY(0);}}',
    ].join('');

    var pos = style.position === 'bottom-left' ? 'wc-left' : 'wc-right';
    var el = document.createElement('style');
    el.id = 'wc-styles';
    el.textContent = css;
    document.head.appendChild(el);
    return pos;
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // DOM build
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function buildDOM(posClass) {
    // Launcher button
    var launcher = document.createElement('div');
    launcher.id = 'wc-launcher';
    launcher.className = posClass;
    launcher.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg><span class="wc-unread" id="wc-badge">0</span>';

    // Chat panel
    var panel = document.createElement('div');
    panel.id = 'wc-panel';
    panel.className = posClass;

    var logoHtml = style.logo_url
      ? '<img src="' + style.logo_url + '" class="wc-logo" alt="logo">'
      : '<div class="wc-logo" style="background:rgba(255,255,255,.25);display:flex;align-items:center;justify-content:center;font-size:18px;">\uD83D\uDCAC</div>';

    panel.innerHTML = [
      '<div id="wc-header">',
      logoHtml,
      '<div class="wc-hinfo"><p class="wc-htitle">' + esc(style.title) + '</p>',
      '<p class="wc-hsub">' + esc(style.subtitle) + '</p></div>',
      '<button class="wc-restart" id="wc-restart-btn" title="New conversation">&#8635;</button>',
      '<span class="wc-close" id="wc-close-btn" title="Close">\u2715</span>',
      '</div>',
      '<div id="wc-msgs"></div>',
      '<div id="wc-footer">',
      '<div id="wc-input-wrap">',
      '<div id="wc-emoji-picker"></div>',
      '<div id="wc-input-row">',
      '<button id="wc-emoji-btn" title="Emoji">\uD83D\uDE0A</button>',
      '<button id="wc-attach-btn" title="Attach file">\uD83D\uDCCE</button>',
      '<input type="file" id="wc-file-input" style="display:none" accept="image/*,.pdf,.doc,.docx,.txt,.zip,.csv">',
      '<textarea id="wc-input" rows="1" placeholder="Type a message\u2026"></textarea>',
      '<button id="wc-send"><svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg></button>',
      '</div>',
      '</div>',
      '<div class="wc-status" id="wc-status"></div>',
      '<div id="wc-end-row">',
      '<button id="wc-end-btn" title="End this conversation">',
      '<svg viewBox="0 0 24 24"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/></svg>',
      'End chat</button>',
      '</div>',
      '<div class="wc-ended-banner" id="wc-ended-banner">',
      'Chat ended. <a onclick="restartChat()">Start a new conversation?</a>',
      '</div>',
      '</div>',
    ].join('');

    document.body.appendChild(launcher);
    document.body.appendChild(panel);

    // Nudge bubble (proactive teaser)
    var posStr = posClass === 'wc-left' ? 'wc-left' : 'wc-right';
    var nudge = document.createElement('div');
    nudge.id = 'wc-nudge';
    nudge.className = posStr;
    nudge.innerHTML = '<button id="wc-nudge-close" title="Dismiss">\u2715</button><p id="wc-nudge-msg"></p>';
    nudge.addEventListener('click', function (ev) {
      if (ev.target.id === 'wc-nudge-close') { dismissNudge(); return; }
      dismissNudge();
      openPanel();
    });
    document.body.appendChild(nudge);

    return { launcher: launcher, panel: panel };
  }

  function esc(s) {
    return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // Emoji picker
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  var WC_EMOJIS = [
    '\uD83D\uDE00','\uD83D\uDE03','\uD83D\uDE04','\uD83D\uDE01','\uD83D\uDE06','\uD83D\uDE05','\uD83E\uDD23','\uD83D\uDE02','\uD83D\uDE42','\uD83D\uDE09','\uD83D\uDE0A','\uD83D\uDE07',
    '\uD83E\uDD70','\uD83D\uDE0D','\uD83D\uDE18','\uD83D\uDE1B','\uD83D\uDE1C','\uD83D\uDE1D','\uD83E\uDD11','\uD83E\uDD17','\uD83E\uDD14','\uD83D\uDE10','\uD83D\uDE11','\uD83D\uDE36',
    '\uD83D\uDE0F','\uD83D\uDE12','\uD83D\uDE44','\uD83D\uDE2C','\uD83D\uDE0C','\uD83D\uDE14','\uD83D\uDE2A','\uD83D\uDE34','\uD83D\uDE37','\uD83E\uDD22','\uD83E\uDD27','\uD83D\uDE35',
    '\uD83D\uDE0E','\uD83D\uDE15','\uD83D\uDE1F','\uD83D\uDE41','\u2639\uFE0F','\uD83D\uDE2E','\uD83D\uDE32','\uD83D\uDE33','\uD83E\uDD7A','\uD83D\uDE26','\uD83D\uDE27','\uD83D\uDE28',
    '\uD83D\uDE30','\uD83D\uDE25','\uD83D\uDE22','\uD83D\uDE2D','\uD83D\uDE31','\uD83D\uDE16','\uD83D\uDE23','\uD83D\uDE1E','\uD83D\uDE29','\uD83D\uDE2B','\uD83D\uDE24','\uD83D\uDE21',
    '\uD83D\uDE20','\uD83E\uDD2C','\uD83D\uDE08','\uD83D\uDC7F','\uD83D\uDC80','\uD83D\uDCA9','\uD83E\uDD21','\uD83D\uDC7B','\uD83D\uDC7D',
    '\uD83D\uDC4D','\uD83D\uDC4E','\uD83D\uDC4F','\uD83D\uDE4C','\uD83E\uDD1D','\uD83D\uDE4F','\uD83D\uDCAA','\uD83D\uDC4B','\u270C\uFE0F','\uD83E\uDD1E','\uD83E\uDD19',
    '\uD83D\uDC48','\uD83D\uDC49','\uD83D\uDC46','\uD83D\uDC47','\u261D\uFE0F','\u270A','\uD83D\uDC4A',
    '\u2764\uFE0F','\uD83E\uDDE1','\uD83D\uDC9B','\uD83D\uDC9A','\uD83D\uDC99','\uD83D\uDC9C','\uD83D\uDD96','\uD83D\uDC94','\uD83D\uDC95','\uD83D\uDC9E','\uD83D\uDC93','\uD83D\uDC97','\uD83D\uDC96','\uD83D\uDC98',
    '\uD83D\uDD25','\u2B50','\uD83C\uDF1F','\u2728','\u26A1','\uD83C\uDF89','\uD83C\uDF8A','\uD83C\uDF88','\uD83C\uDF81','\uD83C\uDFC6','\uD83D\uDC51','\uD83D\uDC8E',
    '\u2705','\u274C','\u26A0\uFE0F','\uD83D\uDCA1','\uD83D\uDD14','\uD83C\uDFB5','\uD83C\uDFB6','\uD83D\uDCF1','\uD83D\uDCBB','\uD83D\uDD11','\uD83D\uDCDD','\uD83D\uDCCC','\uD83D\uDCCE','\uD83D\uDD0D','\uD83D\uDCAC',
    '\uD83C\uDF4E','\uD83C\uDF4A','\uD83C\uDF4B','\uD83C\uDF47','\uD83C\uDF53','\uD83C\uDF52','\uD83C\uDF51','\uD83C\uDF54','\uD83C\uDF5F','\uD83C\uDF55','\uD83C\uDF2E','\u2615','\uD83C\uDF7A','\uD83C\uDF77','\uD83E\uDD73',
    '\uD83D\uDC36','\uD83D\uDC31','\uD83D\uDC2D','\uD83D\uDC30','\uD83E\uDD8A','\uD83D\uDC3B','\uD83D\uDC3C','\uD83E\uDD81','\uD83D\uDC38','\uD83D\uDC35','\uD83D\uDE48','\uD83D\uDE49','\uD83D\uDE4A','\uD83D\uDC14',
    '\uD83C\uDF3A','\uD83C\uDF38','\uD83C\uDF3C','\uD83C\uDF3B','\uD83C\uDF39','\uD83C\uDF40','\uD83C\uDF3F','\uD83C\uDF31','\uD83C\uDF0D','\uD83C\uDF19','\uD83C\uDF1E','\u26C5','\uD83C\uDF08','\u2744\uFE0F',
    '\uD83D\uDE97','\u2708\uFE0F','\uD83D\uDE80','\uD83C\uDFE0','\u26BD','\uD83C\uDFC0','\uD83C\uDFAE','\uD83C\uDFAF','\uD83C\uDFB2','\u265F'
  ];
  var emojiPickerOpen = false;

  function buildEmojiPicker() {
    var picker = document.getElementById('wc-emoji-picker');
    if (!picker || picker.childNodes.length) return;
    WC_EMOJIS.forEach(function(em) {
      var btn = document.createElement('button');
      btn.textContent = em;
      btn.type = 'button';
      btn.title = em;
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        var inp = document.getElementById('wc-input');
        if (inp && !inp.disabled) {
          var pos = inp.selectionStart || inp.value.length;
          inp.value = inp.value.slice(0, pos) + em + inp.value.slice(pos);
          inp.focus();
          // trigger resize
          inp.style.height = 'auto';
          inp.style.height = Math.min(inp.scrollHeight, 80) + 'px';
        }
        closeEmojiPicker();
      });
      picker.appendChild(btn);
    });
  }

  function toggleEmojiPicker(e) {
    if (e) e.stopPropagation();
    var picker = document.getElementById('wc-emoji-picker');
    if (!picker) return;
    emojiPickerOpen = !emojiPickerOpen;
    picker.classList.toggle('wc-ep-open', emojiPickerOpen);
  }

  function closeEmojiPicker() {
    emojiPickerOpen = false;
    var picker = document.getElementById('wc-emoji-picker');
    if (picker) picker.classList.remove('wc-ep-open');
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // Attachment bubble
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function addAttachmentBubble(url, filename, role) {
    var msgs = document.getElementById('wc-msgs');
    if (!msgs) return;
    var isImage = /\.(jpe?g|png|gif|webp|bmp|svg)(\?|$)/i.test(url) || url.startsWith('blob:');
    // Label
    if (role === 'agent' && agentName) {
      var lbl = document.createElement('div');
      lbl.className = 'wc-label-agent'; lbl.textContent = agentName;
      msgs.appendChild(lbl);
    } else if (role === 'bot') {
      var lbl2 = document.createElement('div');
      lbl2.className = 'wc-label-bot'; lbl2.textContent = style.title;
      msgs.appendChild(lbl2);
    }
    var wrap = document.createElement('div');
    wrap.className = 'wc-attach-bubble' + (role === 'visitor' ? ' wc-visitor' : '');
    if (isImage) {
      var img = document.createElement('img');
      img.src = url; img.className = 'wc-attach-img'; img.alt = filename || 'Image';
      img.addEventListener('click', function() { window.open(url, '_blank'); });
      wrap.appendChild(img);
    } else {
      var a = document.createElement('a');
      a.href = url; a.target = '_blank'; a.className = 'wc-attach-file';
      a.innerHTML = '<span class="wc-attach-icon">\uD83D\uDCCE</span>' + esc(filename || 'File');
      wrap.appendChild(a);
    }
    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
    if (!isOpen && role !== 'visitor') {
      unreadCount++;
      var badge = document.getElementById('wc-badge');
      if (badge) { badge.textContent = unreadCount; badge.style.display = 'flex'; }
    }
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // File upload
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function doUpload(file) {
    if (!file) return;
    // Show optimistic local bubble
    var isImg = /\.(jpe?g|png|gif|webp|bmp|svg)$/i.test(file.name);
    if (isImg) {
      addAttachmentBubble(URL.createObjectURL(file), file.name, 'visitor');
    } else {
      addBubble('\uD83D\uDCCE ' + file.name, 'visitor');
    }
    var formData = new FormData();
    formData.append('file', file);
    setStatus('Uploading\u2026');
    fetch(postBase + '/upload', { method: 'POST', body: formData })
      .then(function() { setStatus(''); })
      .catch(function() { setStatus('Upload failed.'); });
    // reset file input
    var fi = document.getElementById('wc-file-input');
    if (fi) fi.value = '';
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // UI helpers
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  var unreadCount = 0;

  function addBubble(text, role) {
    // role: 'bot' | 'agent' | 'visitor' | 'system'
    var msgs = document.getElementById('wc-msgs');
    if (!msgs) return;

    if (role === 'system') {
      var sys = document.createElement('div');
      sys.className = 'wc-system';
      sys.textContent = text;
      msgs.appendChild(sys);
    } else {
      if (role === 'agent' && agentName) {
        var lbl = document.createElement('div');
        lbl.className = 'wc-label-agent';
        lbl.textContent = agentName;
        msgs.appendChild(lbl);
      } else if (role === 'bot') {
        var lbl2 = document.createElement('div');
        lbl2.className = 'wc-label-bot';
        lbl2.textContent = style.title;
        msgs.appendChild(lbl2);
      }
      var b = document.createElement('div');
      b.className = 'wc-bubble wc-' + role;
      if (role === 'visitor') {
        b.style.background = style.primary_color;
      }
      b.textContent = text;
      msgs.appendChild(b);
    }

    msgs.scrollTop = msgs.scrollHeight;

    if (!isOpen && role !== 'visitor') {
      unreadCount++;
      var badge = document.getElementById('wc-badge');
      if (badge) { badge.textContent = unreadCount; badge.style.display = 'flex'; }
    }
  }

  function showMenu(text, options) {
    var msgs = document.getElementById('wc-msgs');
    if (!msgs) return;
    if (text) addBubble(text, 'bot');

    menuPending = options;  // Save so we can disable after selection

    var wrap = document.createElement('div');
    wrap.className = 'wc-menu-options';
    wrap.dataset.menu = '1';

    options.forEach(function (opt) {
      var btn = document.createElement('button');
      btn.className = 'wc-menu-option';
      btn.textContent = opt.text || opt.key;
      btn.dataset.key = opt.key;
      btn.addEventListener('click', function () {
        var label = btn.textContent;
        // Mark selected
        wrap.querySelectorAll('.wc-menu-option').forEach(function (b) { b.classList.add('wc-sel'); });
        // Add visitor bubble
        addBubble(label, 'visitor');
        // Send selection
        sendMessage(String(opt.key));
        menuPending = null;
      });
      wrap.appendChild(btn);
    });

    msgs.appendChild(wrap);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function setStatus(text) {
    var el = document.getElementById('wc-status');
    if (el) el.textContent = text || '';
  }

  function setTyping(from) {
    var el = document.getElementById('wc-status');
    if (el) {
      el.textContent = (from === 'agent' ? 'Agent' : 'Support') + ' is typing\u2026';
      clearTimeout(el._typingTimer);
      el._typingTimer = setTimeout(function () { el.textContent = ''; }, 3000);
    }
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // SSE (server \u2192 client) + HTTP POST (client \u2192 server)
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function connect() {
    // Already open or actively connecting \u2014 do nothing
    if (es && es.readyState !== 2 /* EventSource.CLOSED */) return;

    // Fresh EventSource \u2014 reset init flag so flow re-triggers if session was reset
    initSent = false;
    if (es) { try { es.close(); } catch (_) {} }
    es = new EventSource(sseUrl);
    if (!wasConnected) setStatus('Connecting\u2026');

    es.onopen = function () {
      wasConnected = true;
      setStatus('');
    };

    es.onmessage = function (e) {
      var msg;
      try { msg = JSON.parse(e.data); } catch (err) { return; }

      // 'connected' = brand new (or reset) session \u2192 POST init to trigger the flow
      if (msg.type === 'connected' && !initSent) {
        initSent = true;
        var meta = Object.assign({
          page_url: window.location.href,
          page_title: document.title,
          referrer: document.referrer,
          user_agent: navigator.userAgent,
          trigger_type: _triggerData ? _triggerData.trigger_type : null,
          trigger_value: _triggerData ? _triggerData.trigger_value : null,
        }, cfg.metadata || {});
        fetch(postBase + '/init', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ metadata: meta }),
        }).catch(function () { setStatus('Failed to start session.'); });
      }
      // 'resumed' = returning visitor \u2014 flow already running, no re-init needed

      handleServerMessage(msg);
    };

    es.onerror = function () {
      // readyState 0 = CONNECTING (auto-retry in progress)
      // readyState 2 = CLOSED (gave up or we explicitly closed)
      if (!es || es.readyState === 2) {
        setStatus('Unable to connect. Please refresh the page.');
      } else if (wasConnected) {
        // Was working before \u2014 show reconnecting
        setStatus('Connection lost. Reconnecting\u2026');
      }
      // Else: first-time connect attempt in progress \u2014 stay silent ("Connecting\u2026" already set)
    };
  }

  function sendMessage(text) {
    fetch(postBase + '/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text }),
    }).catch(function () { setStatus('Failed to send. Please try again.'); });
  }

  function sendTypingNotification() {
    fetch(postBase + '/typing', { method: 'POST' }).catch(function () {});
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // End chat (visitor explicitly ends the session)
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function endChat() {
    if (!confirm('End this conversation?\n\nThis will close the chat.')) return;

    // Tell server session is closed
    fetch(postBase + '/close', { method: 'POST' }).catch(function () {});

    // Close SSE
    if (es) { try { es.close(); } catch (_) {} es = null; }

    // Show goodbye system message
    addBubble('You have ended this conversation. Thank you for chatting with us!', 'system');

    // Disable input + send
    var inp = document.getElementById('wc-input');
    var snd = document.getElementById('wc-send');
    if (inp) inp.disabled = true;
    if (snd) snd.disabled = true;

    // Hide end button, show ended banner
    var endBtn = document.getElementById('wc-end-btn');
    if (endBtn) endBtn.classList.add('wc-hidden');
    var banner = document.getElementById('wc-ended-banner');
    if (banner) banner.classList.add('wc-show');

    setStatus('Chat ended');

    // Collapse the panel after a short pause so customer sees the goodbye message
    setTimeout(function () { closePanel(); }, 2500);
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // Restart chat (close session + start fresh)
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function restartChat() {
    if (!confirm('Start a new conversation? This will end the current chat.')) return;

    // Close existing SSE and server session
    if (es) { try { es.close(); } catch (_) {} es = null; }
    fetch(postBase + '/close', { method: 'POST' }).catch(function () {});

    // Generate a new session ID
    sessionId = 'vs_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    sessionStorage.setItem(SESSION_KEY, sessionId);
    sseUrl   = serverBase + '/sse/chat/' + cfg.apiKey + '/' + sessionId;
    postBase = serverBase + '/chat/' + cfg.apiKey + '/' + sessionId;

    // Reset state
    initSent = false;
    wasConnected = false;
    menuPending = null;

    // Reset end-chat UI
    var endBtn = document.getElementById('wc-end-btn');
    if (endBtn) endBtn.classList.remove('wc-hidden');
    var banner = document.getElementById('wc-ended-banner');
    if (banner) banner.classList.remove('wc-show');
    agentName = null;
    unreadCount = 0;

    // Clear messages + status
    var msgs = document.getElementById('wc-msgs');
    if (msgs) msgs.innerHTML = '';
    setStatus('');

    // Re-enable input (in case session had ended)
    var inp = document.getElementById('wc-input');
    var snd = document.getElementById('wc-send');
    if (inp) inp.disabled = false;
    if (snd) snd.disabled = false;

    // Reconnect
    connect();
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // Server message handler
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function handleServerMessage(msg) {
    setStatus('');

    switch (msg.type) {
      case 'connected':
      case 'resumed':
        if (msg.config) applyServerConfig(msg.config);
        break;

      case 'message':
        if (msg.subtype === 'attachment') {
          addAttachmentBubble(msg.text || '', msg.filename || '', msg.from === 'agent' ? 'agent' : 'bot');
        } else {
          addBubble(msg.text || '', msg.from === 'agent' ? 'agent' : 'bot');
        }
        break;

      case 'menu':
        showMenu(msg.text || '', msg.options || []);
        break;

      case 'queue':
        addBubble(msg.message || 'Waiting for an agent\u2026', 'system');
        setStatus('Waiting for agent\u2026');
        break;

      case 'agent_join':
        agentName = msg.agent_name || 'Agent';
        addBubble(agentName + ' has joined the conversation.', 'system');
        setStatus('');
        break;

      case 'typing':
        setTyping(msg.from);
        break;

      case 'end':
        addBubble(msg.message || 'Session ended. Thank you!', 'system');
        setStatus('Session ended');
        // Disable input
        var inp = document.getElementById('wc-input');
        var snd = document.getElementById('wc-send');
        if (inp) inp.disabled = true;
        if (snd) snd.disabled = true;
        break;

      case 'error':
        addBubble('Error: ' + (msg.message || 'Unknown error'), 'system');
        break;
    }
  }

  function applyServerConfig(serverStyle) {
    if (serverStyle.title) {
      style.title = serverStyle.title;
      var el = document.querySelector('#wc-header .wc-htitle');
      if (el) el.textContent = serverStyle.title;
    }
    if (serverStyle.subtitle) {
      style.subtitle = serverStyle.subtitle;
      var el2 = document.querySelector('#wc-header .wc-hsub');
      if (el2) el2.textContent = serverStyle.subtitle;
    }
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // Proactive triggers
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  var _triggerData = null;

  function _fireProactive(type, value) {
    var pt = cfg.proactive || {};
    var nudgeCfg = pt.nudge || {};
    _triggerData = { trigger_type: type, trigger_value: value };
    var delaySec = nudgeCfg.delay_seconds || 0;
    setTimeout(function () {
      if (nudgeCfg.auto_open) {
        openPanel();
      } else if (nudgeCfg.enabled !== false) {
        showNudge(nudgeCfg.message || '\uD83D\uDC4B Need help?');
      } else {
        openPanel();
      }
    }, delaySec * 1000);
  }

  function showNudge(message) {
    var nudge = document.getElementById('wc-nudge');
    var msgEl = document.getElementById('wc-nudge-msg');
    if (!nudge || !msgEl || isOpen) return;  // don\u2019t nudge if panel already open
    msgEl.textContent = message;
    nudge.style.display = 'block';
    clearTimeout(nudge._dt);
    nudge._dt = setTimeout(dismissNudge, 10000);  // auto-dismiss after 10 s
  }

  function dismissNudge() {
    var nudge = document.getElementById('wc-nudge');
    if (!nudge) return;
    nudge.style.display = 'none';
    clearTimeout(nudge._dt);
  }

  function initProactiveTriggers() {
    var pt = cfg.proactive;
    if (!pt || !pt.enabled || !Array.isArray(pt.triggers) || !pt.triggers.length) return;
    var fired = sessionStorage.getItem('wc_pt_' + cfg.apiKey);
    if (fired) return;  // already fired this session

    pt.triggers.forEach(function (rule) {
      switch (rule.type) {

        case 'time_on_page':
          setTimeout(function () {
            if (!rule.repeat) sessionStorage.setItem('wc_pt_' + cfg.apiKey, '1');
            _fireProactive('time_on_page', rule.value);
          }, (rule.value || 30) * 1000);
          break;

        case 'scroll_depth':
          var spct = rule.value || 50;
          var _sHandler = function () {
            var maxScroll = document.documentElement.scrollHeight - window.innerHeight;
            if (maxScroll <= 0) return;
            var pct = (window.scrollY / maxScroll) * 100;
            if (pct >= spct) {
              window.removeEventListener('scroll', _sHandler);
              if (!rule.repeat) sessionStorage.setItem('wc_pt_' + cfg.apiKey, '1');
              _fireProactive('scroll_depth', spct);
            }
          };
          window.addEventListener('scroll', _sHandler, { passive: true });
          break;

        case 'exit_intent':
          var _eHandler = function (ev) {
            if (ev.clientY <= 5) {
              document.removeEventListener('mouseleave', _eHandler);
              if (!rule.repeat) sessionStorage.setItem('wc_pt_' + cfg.apiKey, '1');
              _fireProactive('exit_intent', null);
            }
          };
          document.addEventListener('mouseleave', _eHandler);
          break;

        case 'element_in_view':
          if (!rule.selector) break;
          var _tgt = document.querySelector(rule.selector);
          if (!_tgt) break;
          var _obs = new IntersectionObserver(function (entries, observer) {
            entries.forEach(function (entry) {
              if (entry.isIntersecting) {
                observer.disconnect();
                if (!rule.repeat) sessionStorage.setItem('wc_pt_' + cfg.apiKey, '1');
                _fireProactive('element_in_view', rule.selector);
              }
            });
          }, { threshold: 0.3 });
          _obs.observe(_tgt);
          break;
      }
    });
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // Open / Close panel
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function openPanel() {
    var panel = document.getElementById('wc-panel');
    if (panel) panel.classList.add('wc-open');
    isOpen = true;
    // Reset unread
    unreadCount = 0;
    var badge = document.getElementById('wc-badge');
    if (badge) badge.style.display = 'none';
    // Open SSE stream if not already open
    connect();
    // Focus input
    setTimeout(function () {
      var inp = document.getElementById('wc-input');
      if (inp) inp.focus();
    }, 100);
  }

  function closePanel() {
    var panel = document.getElementById('wc-panel');
    if (panel) panel.classList.remove('wc-open');
    isOpen = false;
  }

  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  // Init
  // \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  function init() {
    var posClass = injectStyles();
    var dom = buildDOM(posClass);

    // Launcher click
    dom.launcher.addEventListener('click', function () {
      isOpen ? closePanel() : openPanel();
    });

    // Close button
    document.getElementById('wc-close-btn').addEventListener('click', function (e) {
      e.stopPropagation();
      closePanel();
    });

    // Restart button
    document.getElementById('wc-restart-btn').addEventListener('click', function (e) {
      e.stopPropagation();
      restartChat();
    });

    // End chat button
    document.getElementById('wc-end-btn').addEventListener('click', function (e) {
      e.stopPropagation();
      endChat();
    });

    // Emoji picker
    buildEmojiPicker();
    document.getElementById('wc-emoji-btn').addEventListener('click', toggleEmojiPicker);
    document.addEventListener('click', function(e) {
      var picker = document.getElementById('wc-emoji-picker');
      var btn = document.getElementById('wc-emoji-btn');
      if (emojiPickerOpen && picker && !picker.contains(e.target) && e.target !== btn) {
        closeEmojiPicker();
      }
    });

    // Attachment
    document.getElementById('wc-attach-btn').addEventListener('click', function() {
      var fi = document.getElementById('wc-file-input');
      if (fi) fi.click();
    });
    document.getElementById('wc-file-input').addEventListener('change', function() {
      if (this.files && this.files[0]) doUpload(this.files[0]);
    });

    // Send button
    document.getElementById('wc-send').addEventListener('click', function () {
      doSend();
    });

    // Enter key (Shift+Enter = newline)
    document.getElementById('wc-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        doSend();
      }
    });

    // Auto-resize textarea + typing notification
    document.getElementById('wc-input').addEventListener('input', function () {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 80) + 'px';
      sendTypingNotification();
    });

    // Dismiss nudge when user opens panel manually
    var origOpen = openPanel;
    openPanel = function () { dismissNudge(); origOpen(); };

    // Initialise proactive trigger rules
    initProactiveTriggers();
  }

  function doSend() {
    var inp = document.getElementById('wc-input');
    if (!inp) return;
    var text = inp.value.trim();
    if (!text) return;
    inp.value = '';
    inp.style.height = 'auto';
    addBubble(text, 'visitor');
    sendMessage(text);
  }

  // Run after DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
