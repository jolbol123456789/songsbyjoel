// Visitor statistics: counts page views and clicks on links, through GoatCounter.
// No cookies and nothing stored on the visitor's device (except an opt-out, if the visitor asks for one).
// Only this is sent: the page or click name, the page title, the referring site (without its query string)
// and any ref/utm_source/utm_campaign in our own URL. Nothing about the screen or the device.
// Links with data-click="name" are counted as clicks on "click/name". Without JavaScript nothing is counted.
(function () {
  var script = document.currentScript;
  var endpoint = script && script.getAttribute("data-endpoint");
  var OPTOUT_KEY = "stats-optout";
  if (!endpoint) return;

  function optedOut() {
    try { return localStorage.getItem(OPTOUT_KEY) === "yes"; } catch (e) { return false; }
  }

  function local() {
    var host = location.hostname;
    return location.protocol === "file:" || host === "localhost" || host === "127.0.0.1" || host === "[::1]" ||
      /\.(localhost|test)$/.test(host);
  }

  function referrer() {
    var ref = document.referrer;
    if (!ref) return "";
    try {
      var url = new URL(ref);
      if (url.host === location.host) return "";
      return url.origin + url.pathname;
    } catch (e) { return ""; }
  }

  function campaign() {
    var keep = ["ref", "utm_source", "utm_campaign"];
    var params = new URLSearchParams(location.search);
    var out = new URLSearchParams();
    keep.forEach(function (k) { if (params.get(k)) out.set(k, params.get(k).slice(0, 100)); });
    var text = out.toString();
    return text ? "?" + text : "";
  }

  function send(values) {
    if (optedOut() || local()) return;
    var query = new URLSearchParams(values);
    query.set("rnd", Math.random().toString(36).slice(2, 8));
    var url = endpoint + "?" + query.toString();
    if (navigator.sendBeacon && navigator.sendBeacon(url)) return;
    var img = new Image();
    img.src = url;
  }

  function pageview() {
    send({ p: location.pathname, t: document.title, r: referrer(), q: campaign() });
  }

  function clicked(event) {
    if (event.type === "auxclick" && event.button !== 1) return;
    var link = event.target.closest && event.target.closest("[data-click]");
    if (!link) return;
    send({ p: "click/" + link.getAttribute("data-click"), t: link.getAttribute("data-click-title") || "",
      e: "true" });
  }

  document.addEventListener("click", clicked, true);
  document.addEventListener("auxclick", clicked, true);

  // The privacy page has a button for opting out of (or back in to) being counted.
  function initOptout() {
    var box = document.querySelector("[data-stats-optout]");
    if (!box) return;
    var button = box.querySelector("button");
    var status = box.querySelector("[data-stats-status]");
    function show() {
      var out = optedOut();
      status.textContent = out ? "Your visits are not counted on this device." : "Your visits are counted.";
      button.textContent = out ? "Count my visits again" : "Don’t count my visits";
    }
    button.addEventListener("click", function () {
      try {
        if (optedOut()) localStorage.removeItem(OPTOUT_KEY);
        else localStorage.setItem(OPTOUT_KEY, "yes");
      } catch (e) { status.textContent = "Your browser blocks saving this choice."; return; }
      show();
    });
    box.hidden = false;
    show();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { pageview(); initOptout(); });
  } else { pageview(); initOptout(); }
})();
