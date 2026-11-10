// The diagram's only way to Python. Two implementations of one interface:
//   QtBridge   inside the Qt app, through QWebChannel (expconfig/wiringweb.py)
//   HttpBridge in a browser, through the web trial's API (expconfig/web/server.py)
// Every edit returns "" or the reason it was refused; Python then sends a new model.

import type { Choices, Model, Port } from "./types";

export interface Bridge {
  model(): Promise<Model>;
  setCell(ai: number, key: string, value: string): Promise<string>;
  cable(a: Port, b: Port): Promise<string>;
  unplug(p: Port): Promise<string>;
  choices(ai: number, key: string): Promise<Choices>;
  select(ai: number, key: string | null): void;
  onModel(cb: (m: Model) => void): void;
  onSelect(cb: (ai: number, key: string | null) => void): void;
}

declare global {
  interface Window {
    qt?: { webChannelTransport: unknown };
    QWebChannel?: new (transport: unknown, init: (channel: { objects: Record<string, QtObject> }) => void) => unknown;
  }
}

// Slots answer through a callback; signals have connect().
type QtObject = Record<string, any>;

class QtBridge implements Bridge {
  private obj: Promise<QtObject>;

  constructor() {
    this.obj = new Promise((resolve) => {
      new window.QWebChannel!(window.qt!.webChannelTransport, (ch) => resolve(ch.objects.expconfig));
    });
  }

  private call<T>(name: string, ...args: unknown[]): Promise<T> {
    return this.obj.then((o) => new Promise<T>((resolve) => o[name](...args, resolve)));
  }

  async model() {
    return JSON.parse(await this.call<string>("model")) as Model;
  }
  setCell(ai: number, key: string, value: string) {
    return this.call<string>("setCell", ai, key, value);
  }
  cable(a: Port, b: Port) {
    return this.call<string>("cable", JSON.stringify(a), JSON.stringify(b));
  }
  unplug(p: Port) {
    return this.call<string>("unplug", JSON.stringify(p));
  }
  async choices(ai: number, key: string) {
    return JSON.parse(await this.call<string>("choices", ai, key)) as Choices;
  }
  select(ai: number, key: string | null) {
    this.obj.then((o) => o.select(ai, key ?? ""));
  }
  onModel(cb: (m: Model) => void) {
    this.obj.then((o) => o.modelChanged.connect((json: string) => cb(JSON.parse(json))));
  }
  onSelect(cb: (ai: number, key: string | null) => void) {
    this.obj.then((o) => o.selectedChanged.connect((ai: number, key: string) => cb(ai, key || null)));
  }
}

class HttpBridge implements Bridge {
  private version = -1;
  private listeners: ((m: Model) => void)[] = [];

  constructor() {
    setInterval(() => this.poll(), 1500);
  }

  private async post(path: string, body: unknown): Promise<string> {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify(body) });
    if (r.ok) {
      this.poll();
      return "";
    }
    const data = await r.json().catch(() => ({}));
    return data.detail || r.statusText;
  }

  private async poll() {
    const { version } = await (await fetch("/api/version")).json();
    if (version !== this.version) {
      this.version = version;
      const m = await this.model();
      this.listeners.forEach((cb) => cb(m));
    }
  }

  async model() {
    return (await (await fetch("/api/model")).json()) as Model;
  }
  setCell(ai: number, key: string, value: string) {
    return this.post("/api/cell", { ai, key, value });
  }
  cable(a: Port, b: Port) {
    return this.post("/api/connect", { a, b });
  }
  unplug(p: Port) {
    return this.post("/api/disconnect", { port: p });
  }
  async choices(ai: number, key: string) {
    return (await (await fetch(`/api/choices?ai=${ai}&key=${encodeURIComponent(key)}`)).json()) as Choices;
  }
  select() {}
  onModel(cb: (m: Model) => void) {
    this.listeners.push(cb);
  }
  onSelect() {}
}

export function makeBridge(): Bridge {
  return window.qt && window.QWebChannel ? new QtBridge() : new HttpBridge();
}
