(() => {
  /* ===== CONFIG: ajuste estes valores antes de publicar ===== */
  const CONFIG = {
    appUrl: "https://app.zunfy.com.br",       // destino do botão Login
  };

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  /* Links do portal */
  $$("[data-app]").forEach(a => { a.href = CONFIG.appUrl; });

  /* Sombra do topo ao rolar */
  const topo = $(".topo");
  const aoRolar = () => topo.classList.toggle("rolou", window.scrollY > 8);
  aoRolar();
  window.addEventListener("scroll", aoRolar, { passive: true });

  /* Menu no celular */
  const hamb = $(".hamb");
  const menu = $("#menu");
  const fecharMenu = () => {
    menu.classList.remove("aberto");
    hamb.setAttribute("aria-expanded", "false");
    hamb.setAttribute("aria-label", "Abrir menu");
  };
  hamb.addEventListener("click", () => {
    const abrir = !menu.classList.contains("aberto");
    menu.classList.toggle("aberto", abrir);
    hamb.setAttribute("aria-expanded", String(abrir));
    hamb.setAttribute("aria-label", abrir ? "Fechar menu" : "Abrir menu");
    if (abrir) menu.querySelector("a").focus();
  });
  menu.addEventListener("click", e => { if (e.target.closest("a")) fecharMenu(); });
  matchMedia("(min-width: 1101px)").addEventListener("change", e => { if (e.matches) fecharMenu(); });

  /* Painel de ajuda */
  const fabChat = $(".fab-chat");
  const painel = $("#painel-ajuda");
  const fecharPainel = () => { painel.hidden = true; fabChat.setAttribute("aria-expanded", "false"); };
  fabChat.addEventListener("click", () => {
    const abrir = painel.hidden;
    painel.hidden = !abrir;
    fabChat.setAttribute("aria-expanded", String(abrir));
    if (abrir) painel.querySelector(".painel-op").focus();
  });
  painel.addEventListener("click", e => { if (e.target.closest("a")) fecharPainel(); });
  $(".painel-fechar").addEventListener("click", () => { fecharPainel(); fabChat.focus(); });

  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    if (menu.classList.contains("aberto")) { fecharMenu(); hamb.focus(); }
    if (!painel.hidden) { fecharPainel(); fabChat.focus(); }
  });
  document.addEventListener("click", e => {
    if (!painel.hidden && !e.target.closest(".flutuantes")) fecharPainel();
    if (menu.classList.contains("aberto") && !e.target.closest(".barra")) fecharMenu();
  });

  $("#ano").textContent = new Date().getFullYear();
})();
