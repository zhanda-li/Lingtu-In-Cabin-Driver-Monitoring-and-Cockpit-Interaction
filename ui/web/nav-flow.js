/* Request ordering and route comparisons shared by the existing navigation page. */
(function (root) {
  'use strict';
  class LatestRequest {
    constructor() { this.seq = 0; this.active = null; }
    invalidate() {
      ++this.seq;
      if (this.active) this.active.controller.abort();
      this.active = null;
    }
    begin() {
      this.invalidate();
      const request = { seq: this.seq, controller: new AbortController() };
      this.active = request;
      return request;
    }
    current(request) { return this.active === request && request.seq === this.seq; }
    finish(request) { if (this.current(request)) this.active = null; }
    get busy() { return !!this.active; }
  }
  function validPoint(p) {
    return !!p && Number.isFinite(p.lat) && Number.isFinite(p.lng)
      && Math.abs(p.lat) <= 90 && Math.abs(p.lng) <= 180;
  }
  function binding(origin, dest) {
    return validPoint(origin) && validPoint(dest)
      ? [origin.lat, origin.lng, dest.lat, dest.lng].join('|') : '';
  }
  function comparison(route, routes) {
    const times = routes.map(r => r.drive_s).filter(v => Number.isFinite(v) && v > 0);
    if (!Number.isFinite(route.drive_s) || route.drive_s <= 0 || !times.length) return '';
    const extra = Math.round((route.drive_s - Math.min(...times)) / 60);
    return extra > 0 ? '比最快多 ' + extra + ' 分钟' : '最快方案';
  }
  const api = { LatestRequest, validPoint, binding, comparison };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.NavFlow = api;
})(typeof window !== 'undefined' ? window : globalThis);
