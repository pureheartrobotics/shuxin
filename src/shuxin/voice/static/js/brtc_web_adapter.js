/**
 * Baidu Pure RTC web media adapter.
 * Implements MediaPeer.join/leave; AppKey never enters the browser.
 *
 * Uses global BRTC_* APIs when baidu.rtc.sdk.js is loaded; otherwise stub
 * mode (L1 signaling validation without cloud media).
 */
(function (global) {
  "use strict";

  function logFn(msg) {
    if (typeof global.shuxinCallLog === "function") {
      global.shuxinCallLog(msg);
    } else {
      console.log("[BrtcWebAdapter]", msg);
    }
  }

  function BrtcWebAdapter() {
    this._active = false;
    this._rtc = null;
    this._stub = false;
  }

  BrtcWebAdapter.prototype.isActive = function () {
    return this._active;
  };

  /**
   * @param {{app_id:string, server_url:string, room_name:string, user_id:string, token:string}} rtc
   * @returns {Promise<void>}
   */
  BrtcWebAdapter.prototype.join = function (rtc) {
    var self = this;
    return new Promise(function (resolve, reject) {
      if (!rtc || !rtc.room_name || !rtc.user_id || !rtc.token) {
        reject(new Error("missing rtc params"));
        return;
      }
      self.leave();
      self._rtc = rtc;

      var hasSdk =
        typeof global.BRTC_Start === "function" ||
        (global.baidu && global.baidu.rtc && typeof global.baidu.rtc.BRTC_Start === "function");
      var startFn = global.BRTC_Start || (global.baidu && global.baidu.rtc && global.baidu.rtc.BRTC_Start);

      if (!hasSdk || typeof startFn !== "function") {
        self._stub = true;
        self._active = true;
        logFn(
          "!!! BRTC SDK NOT LOADED — stub join (NO AUDIO) room=" +
            rtc.room_name +
            " user=" +
            rtc.user_id +
            " — hard-refresh Ctrl+Shift+R; check Console for CDN/local SDK errors"
        );
        resolve();
        return;
      }

      try {
        var localView = document.getElementById("brtc-local");
        var remoteView = document.getElementById("brtc-remote");
        startFn({
          server: rtc.server_url || "wss://rtc.exp.bcelive.com/janus",
          appid: rtc.app_id,
          token: rtc.token,
          roomname: rtc.room_name,
          userid: rtc.user_id,
          displayname: rtc.user_id,
          localvideoviewid: localView ? "brtc-local" : "",
          remotevideoviewid: remoteView ? "brtc-remote" : "",
          usingvideo: false,
          usingaudio: true,
          aspublisher: true,
          autosubscribe: true,
          autopublish: true,
          showvideobps: false,
          shownovideo: false,
          showspinner: false,
          success: function () {
            self._stub = false;
            self._active = true;
            logFn("BRTC joined room=" + rtc.room_name + " as " + rtc.user_id);
            if (remoteView && typeof remoteView.play === "function") {
              remoteView.play().catch(function () {});
            }
            resolve();
          },
          error: function (err) {
            self._active = false;
            logFn("BRTC join failed: " + (err && (err.message || err)));
            reject(err || new Error("BRTC_Start failed"));
          },
        });
      } catch (err) {
        self._active = false;
        reject(err);
      }
    });
  };

  BrtcWebAdapter.prototype.leave = function () {
    if (!this._active && !this._rtc) {
      return;
    }
    try {
      var stopFn =
        global.BRTC_Stop ||
        (global.baidu && global.baidu.rtc && global.baidu.rtc.BRTC_Stop);
      if (!this._stub && typeof stopFn === "function") {
        stopFn();
      }
    } catch (err) {
      logFn("BRTC leave error: " + (err && err.message));
    }
    this._active = false;
    this._stub = false;
    this._rtc = null;
    logFn("BRTC left room");
  };

  global.BrtcWebAdapter = BrtcWebAdapter;
})(window);
