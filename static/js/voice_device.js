/**
 * WzVoiceDevice — provider-agnostic in-browser softphone wrapper.
 *
 * Supports:
 *   twilio  → Twilio.Device  (twilio/voice-sdk CDN)
 *   telnyx  → TelnyxRTC     (@telnyx/webrtc CDN)
 *   other   → fallback banner; calls placed via server API only
 *
 * Usage:
 *   const dev = new WzVoiceDevice(apiFetchFn);
 *   await dev.init(connectorId);
 *   await dev.dial(conferenceRoom);   // join a named conference
 *   dev.hangup();
 *   dev.mute(true/false);
 *   dev.on('state', handler);         // 'idle'|'ringing'|'connected'|'error'
 */
class WzVoiceDevice {
    constructor(apiFetch) {
        this._api        = apiFetch;
        this._provider   = null;
        this._supported  = false;
        this._device     = null;    // Twilio.Device | TelnyxRTC
        this._call       = null;    // active call object
        this._state      = 'idle';  // idle | initialising | ready | ringing | connected | error
        this._handlers   = {};
        this._credentials = null;
        this._sdkReady   = false;
    }

    // ── Public API ──────────────────────────────────────────────────────────

    /** Fetch credentials from the server and load the provider SDK. */
    async init(connectorId) {
        this._setState('initialising');
        try {
            const r = await this._api(`/api/v1/voice/agent-credentials?connector_id=${connectorId}`);
            if (!r.ok) throw new Error(`credentials fetch failed: ${r.status}`);
            const data = await r.json();
            this._provider   = data.provider;
            this._supported  = data.webrtc_supported;
            this._credentials = data.credentials;

            if (!this._supported) {
                this._setState('unsupported', data.message);
                return;
            }
            if (data.sdk_url) await this._loadScript(data.sdk_url);

            if (this._provider === 'twilio')  await this._initTwilio();
            if (this._provider === 'telnyx')  await this._initTelnyx();
        } catch (err) {
            console.error('[WzVoiceDevice] init error:', err);
            this._setState('error', err.message);
        }
    }

    /** Join a named conference room (outbound campaign dialler). */
    async dial(conferenceRoom) {
        if (!this._supported || this._state !== 'ready') {
            console.warn('[WzVoiceDevice] dial() called when not ready, state=', this._state);
            return false;
        }
        this._setState('ringing');
        try {
            if (this._provider === 'twilio')  return await this._dialTwilio(conferenceRoom);
            if (this._provider === 'telnyx')  return await this._dialTelnyx(conferenceRoom);
        } catch (err) {
            console.error('[WzVoiceDevice] dial error:', err);
            this._setState('error', err.message);
            return false;
        }
    }

    /** Hang up the current call. */
    hangup() {
        if (!this._call) return;
        try {
            if (this._provider === 'twilio') this._call.disconnect();
            if (this._provider === 'telnyx') this._call.hangup();
        } catch (_) { /* ignore */ }
        this._call = null;
        this._setState('ready');
    }

    /** Mute or unmute the microphone. */
    mute(on) {
        if (!this._call) return;
        if (this._provider === 'twilio') this._call.mute(on);
        if (this._provider === 'telnyx') on ? this._call.muteAudio() : this._call.unmuteAudio();
    }

    get provider()   { return this._provider; }
    get supported()  { return this._supported; }
    get state()      { return this._state; }
    get activeCall() { return !!this._call; }

    /** Register an event handler. Events: 'state', 'error'. */
    on(event, handler) { this._handlers[event] = handler; }

    // ── Twilio implementation ───────────────────────────────────────────────

    async _initTwilio() {
        const { token } = this._credentials;
        const device = new Twilio.Device(token, {
            codecPreferences: ['opus', 'pcmu'],
            edge: 'johannesburg',
            logLevel: 'warn',
        });

        device.on('ready',       () => this._setState('ready'));
        device.on('error',       (e) => this._setState('error', e.message));
        device.on('registering', () => this._setState('initialising'));
        device.on('registered',  () => this._setState('ready'));
        device.on('unregistered',() => this._setState('idle'));

        device.register();
        this._device = device;
    }

    async _dialTwilio(conferenceRoom) {
        const call = await this._device.connect({
            params: { To: conferenceRoom, ConferenceName: conferenceRoom },
        });
        this._call = call;
        call.on('accept',     () => this._setState('connected'));
        call.on('disconnect', () => { this._call = null; this._setState('ready'); });
        call.on('error',      (e) => this._setState('error', e.message));
        return true;
    }

    // ── Telnyx implementation ───────────────────────────────────────────────

    async _initTelnyx() {
        const { login, password } = this._credentials;
        const client = new window.TelnyxRTC({ login, password });

        client.on('telnyx.ready',       () => this._setState('ready'));
        client.on('telnyx.error',       (e) => this._setState('error', e.message));
        client.on('telnyx.socket.error',() => this._setState('error', 'WebSocket error'));

        await client.connect();
        this._device = client;
    }

    async _dialTelnyx(conferenceRoom) {
        const call = this._device.newCall({
            destinationNumber: conferenceRoom,
            callerName: 'WizzardChat',
        });
        this._call = call;
        call.on('telnyx.notification', (n) => {
            if (n.type === 'callUpdate') {
                const st = n.call?.state;
                if (st === 'active')  this._setState('connected');
                if (st === 'destroy') { this._call = null; this._setState('ready'); }
            }
        });
        return true;
    }

    // ── Helpers ─────────────────────────────────────────────────────────────

    _setState(state, detail) {
        this._state = state;
        if (this._handlers['state']) this._handlers['state'](state, detail);
    }

    _loadScript(url) {
        return new Promise((resolve, reject) => {
            if (document.querySelector(`script[src="${url}"]`)) { resolve(); return; }
            const s = document.createElement('script');
            s.src = url;
            s.onload  = resolve;
            s.onerror = () => reject(new Error(`Failed to load SDK: ${url}`));
            document.head.appendChild(s);
        });
    }
}
