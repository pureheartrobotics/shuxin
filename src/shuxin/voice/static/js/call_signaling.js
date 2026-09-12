/**
 * Call signaling state machine (browser peer) — aligned with firmware CallManager.
 * Uses BrtcWebAdapter for media; AppKey never used here.
 */
(function (global) {
  "use strict";

  var CallState = {
    Idle: "idle",
    OutgoingRing: "outgoing",
    IncomingRing: "incoming",
    InCall: "incall",
  };

  function CallSignaling(options) {
    this._wsSend = options.sendJson;
    this._onUi = options.onUi || function () {};
    this._log = options.log || function () {};
    this._media = options.media || new global.BrtcWebAdapter();
    this.state = CallState.Idle;
    this.callId = "";
    this._pendingRtc = null;
  }

  CallSignaling.prototype.isAiSuspended = function () {
    return this.state !== CallState.Idle;
  };

  CallSignaling.prototype.isActive = function () {
    return this.state === CallState.InCall;
  };

  /**
   * @returns {boolean} true if message consumed
   */
  CallSignaling.prototype.handleMessage = function (msg) {
    if (!msg || typeof msg.type !== "string" || msg.type.indexOf("call/") !== 0) {
      return false;
    }
    var type = msg.type;
    if (type === "call/outgoing") {
      this._onOutgoing(msg);
      return true;
    }
    if (type === "call/ring") {
      this._onRing(msg);
      return true;
    }
    if (type === "call/connected") {
      this._onConnected(msg);
      return true;
    }
    if (type === "call/cancel") {
      this._onCancel(msg);
      return true;
    }
    if (type === "call/end") {
      this._onEnd(msg);
      return true;
    }
    this._log("Unhandled call message: " + type);
    return true;
  };

  CallSignaling.prototype.accept = function () {
    if (this.state !== CallState.IncomingRing || !this.callId) {
      return;
    }
    this._wsSend({ type: "call/accept", call_id: this.callId });
    this._log("Sent call/accept " + this.callId);
  };

  CallSignaling.prototype.reject = function () {
    if (this.state !== CallState.IncomingRing || !this.callId) {
      return;
    }
    this._wsSend({ type: "call/reject", call_id: this.callId });
    this._reset("rejected");
  };

  CallSignaling.prototype.end = function () {
    if (this.state === CallState.Idle || !this.callId) {
      return;
    }
    this._wsSend({ type: "call/end", call_id: this.callId });
    this._media.leave();
    this._reset("ended_local");
  };

  CallSignaling.prototype.onWsClosed = function () {
    this._media.leave();
    this._reset("ws_closed");
  };

  CallSignaling.prototype._onOutgoing = function (msg) {
    this.callId = String(msg.call_id || "");
    this._pendingRtc = msg.rtc || null;
    this.state = CallState.OutgoingRing;
    this._onUi({
      kind: "outgoing",
      callId: this.callId,
      handle: msg.callee_handle || "",
    });
    this._log("Outgoing call " + this.callId);
  };

  CallSignaling.prototype._onRing = function (msg) {
    this.callId = String(msg.call_id || "");
    this._pendingRtc = msg.rtc || null;
    this.state = CallState.IncomingRing;
    this._onUi({
      kind: "incoming",
      callId: this.callId,
      callerHandle: msg.caller_handle || "",
      callerDeviceId: msg.caller_device_id || "",
    });
    this._log("Incoming call " + this.callId + " from " + (msg.caller_handle || "?"));
  };

  CallSignaling.prototype._onConnected = function (msg) {
    var self = this;
    // Prefer peer-specific rtc on connected; fall back to ring/outgoing params.
    if (msg.rtc && msg.rtc.token) {
      this._pendingRtc = msg.rtc;
    }
    if (!this._pendingRtc) {
      this._log("call/connected without rtc params");
      this._reset("missing_rtc");
      return;
    }
    this._media
      .join(this._pendingRtc)
      .then(function () {
        self.state = CallState.InCall;
        self._onUi({
          kind: "connected",
          callId: self.callId,
          peerDeviceId: msg.peer_device_id || "",
          stub: !!(self._media._stub),
        });
        self._log("In call " + self.callId);
      })
      .catch(function (err) {
        self._log("Media join failed: " + (err && err.message));
        self._wsSend({ type: "call/end", call_id: self.callId });
        self._reset("media_failed");
      });
  };

  CallSignaling.prototype._onCancel = function (msg) {
    if (this.state === CallState.IncomingRing) {
      this._reset(msg.reason || "cancel");
    }
  };

  CallSignaling.prototype._onEnd = function (msg) {
    this._media.leave();
    this._reset(msg.reason || "ended");
  };

  CallSignaling.prototype._reset = function (reason) {
    this.state = CallState.Idle;
    this.callId = "";
    this._pendingRtc = null;
    this._onUi({ kind: "idle", reason: reason || "" });
  };

  global.CallSignaling = CallSignaling;
  global.CallState = CallState;
})(window);
