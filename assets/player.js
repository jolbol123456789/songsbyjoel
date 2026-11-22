// Click-to-load Spotify player. Nothing is loaded from Spotify until the visitor clicks
// "Play on Spotify". Without JavaScript the button is an ordinary link to Spotify.
document.addEventListener("click", function (event) {
  var link = event.target.closest && event.target.closest(".player-start");
  if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  var box = link.parentElement;
  var src = box.getAttribute("data-embed");
  if (!src) return;
  event.preventDefault();
  var frame = document.createElement("iframe");
  frame.src = src + "?utm_source=generator";
  frame.title = "Spotify player";
  frame.height = box.getAttribute("data-height") || "152";
  frame.allow = "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture";
  box.classList.add("is-loaded");
  box.replaceChildren(frame);
  frame.focus();
});
