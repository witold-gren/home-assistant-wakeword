// The page of the studio: the icons of Home Assistant (<ha-icon icon="mdi:…">) drawn from the paths kept in
// vendor/mdi.js (no CDN - the machine may be offline), the stylesheet, then the editor itself.

import { ICONS } from "./vendor/mdi.js";
import "./app.js";

const FALLBACK = "mdi:help-circle-outline";

class HaIcon extends HTMLElement {
  static observedAttributes = ["icon"];

  get icon() {
    return this.getAttribute("icon");
  }

  set icon(value) {
    this.setAttribute("icon", value);
  }

  connectedCallback() {
    this._draw();
  }

  attributeChangedCallback() {
    this._draw();
  }

  // drawn in its own shadow root: children of its own would shift the nodes of the templates it sits in
  _draw() {
    const root = this.shadowRoot ?? this.attachShadow({ mode: "open" });
    const path = ICONS[this.getAttribute("icon")] || ICONS[FALLBACK];
    root.innerHTML = `<style>:host{display:inline-flex;width:var(--mdc-icon-size,18px);height:var(--mdc-icon-size,18px);flex:none}`
      + `svg{width:100%;height:100%;fill:currentColor}</style>`
      + `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${path}"></path></svg>`;
  }
}

if (!customElements.get("ha-icon")) customElements.define("ha-icon", HaIcon);
