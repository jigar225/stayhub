/** Navigation keys show a segment indicator; pointer typing keeps a plain field. */
export function installInputModality() {
  const root = document.documentElement;
  root.dataset.inputModality = "keyboard";
  const pointer = () => {
    root.dataset.inputModality = "pointer";
  };
  const keyboard = (event: KeyboardEvent) => {
    if (
      [
        "Escape",
        "Tab",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
      ].includes(event.key)
    )
      root.dataset.inputModality = "keyboard";
  };
  document.addEventListener("pointerdown", pointer, true);
  document.addEventListener("keydown", keyboard, true);
  return () => {
    document.removeEventListener("pointerdown", pointer, true);
    document.removeEventListener("keydown", keyboard, true);
  };
}
