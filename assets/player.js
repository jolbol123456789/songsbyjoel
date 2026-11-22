// Spotify players and cookie consent.
// The site sets no cookies of its own. Spotify's players may, so they only load after the visitor says yes
// (GDPR/ePrivacy). The choice is remembered in localStorage and can be changed under "Cookie settings".
// Without a yes, each player is a button that loads just that player when clicked (that click is the consent).
// The banner does not pop up by itself, so it never covers the page; it opens from "Cookie settings".
// Without JavaScript, the button is an ordinary link to Spotify.
(function () {
  var KEY = "spotify-consent";

  function getChoice() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function setChoice(value) {
    try { localStorage.setItem(KEY, value); } catch (e) { /* private mode: ask again next time */ }
  }

  function load(box, focus) {
    var src = box.getAttribute("data-embed");
    if (!src || box.classList.contains("is-loaded")) return;
    var frame = document.createElement("iframe");
    frame.src = src + "?utm_source=generator";
    frame.title = "Spotify player";
    frame.height = box.getAttribute("data-height") || "152";
    frame.allow = "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture";
    frame.loading = "lazy";
    box.classList.add("is-loaded");
    box.replaceChildren(frame);
    if (focus) frame.focus();
  }

  function loadAll() {
    document.querySelectorAll(".player[data-embed]").forEach(function (box) { load(box, false); });
  }

  function init() {
    var banner = document.querySelector(".consent");
    var settings = document.querySelector(".cookie-settings");
    var choice = getChoice();

    if (settings) settings.hidden = false;
    if (choice === "yes") loadAll();

    document.addEventListener("click", function (event) {
      var target = event.target;
      if (!target.closest) return;

      var answer = target.closest("[data-consent]");
      if (answer) {
        var value = answer.getAttribute("data-consent");
        var before = getChoice();
        setChoice(value);
        banner.hidden = true;
        if (value === "yes") loadAll();
        else if (before === "yes") location.reload(); // remove players that are already loaded
        return;
      }

      if (target.closest(".cookie-settings")) {
        banner.hidden = false;
        var first = banner.querySelector("[data-consent]");
        if (first) first.focus();
        return;
      }

      // Clicking a single player's button is consent for that player only.
      var link = target.closest(".player-start");
      if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var box = link.parentElement;
      if (!box.getAttribute("data-embed")) return;
      event.preventDefault();
      load(box, true);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
