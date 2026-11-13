// COFRE - content script: escribe el valor en el campo adecuado.
// Reglas: nunca envia nada a la red, nunca lee valores del DOM para devolverlos,
// y no toca campos ocultos ni deshabilitados.

function visible(el) {
  if (!el || el.disabled || el.readOnly) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 8 || r.height < 8) return false;
  const style = window.getComputedStyle(el);
  return style.visibility !== "hidden" && style.display !== "none" &&
         el.type !== "hidden";
}

function setValue(el, value) {
  el.focus();
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function pickFields() {
  const focus = document.activeElement;
  if (focus && focus.tagName === "INPUT" && visible(focus) &&
      ["password", "text", "email", "tel"].includes(focus.type)) {
    return [focus];
  }
  const all = [...document.querySelectorAll(
    "input[type=password], input[type=email], input[autocomplete*=password], input[type=text]")]
    .filter(visible);
  const pass = all.find((el) => el.type === "password");
  if (!pass) return all.slice(0, 1);
  // usuario + contrasena si estan en el mismo formulario
  const form = pass.form || pass.closest("form") || document;
  const user = [...form.querySelectorAll("input[type=email], input[type=text]")]
    .filter(visible)[0];
  return user ? [user, pass] : [pass];
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type !== "cofre-fill") return false;
  const value = String(msg.value ?? "");
  if (!value) {
    sendResponse({ filled: 0 });
    return true;
  }
  const fields = pickFields();
  if (!fields.length) {
    sendResponse({ filled: 0 });
    return true;
  }
  // si hay dos campos (usuario/contrasena) solo se rellena el de contrasena,
  // porque el secreto puede ser una clave y no un usuario
  let count = 0;
  if (fields.length === 1) {
    setValue(fields[0], value);
    count = 1;
  } else {
    const pass = fields.find((f) => f.type === "password") || fields[fields.length - 1];
    setValue(pass, value);
    count = 1;
  }
  sendResponse({ filled: count });
  return true;
});
