// Just enough DOM for paintCode: text nodes, spans and a fragment.
export class Node {
  constructor(className) {
    this.className = className;
    this.children = [];
  }
  append(...nodes) {
    for (const node of nodes) this.children.push(...(node.fragment ? node.children : [node]));
  }
  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }
  get childElementCount() {
    return this.children.filter(child => child instanceof Node).length;
  }
  get textContent() {
    return this.children.map(child => (child instanceof Node ? child.textContent : child.text)).join("");
  }
  set textContent(text) {
    this.children = text ? [{text}] : [];
  }
  classes() {
    return this.children.flatMap(child => (child instanceof Node ? [child.className, ...child.classes()] : []));
  }
}
globalThis.document = {
  createDocumentFragment: () => Object.assign(new Node(), {fragment: true}),
  createElement: () => new Node(""),
  createTextNode: text => ({text}),
};
export const settle = () => new Promise(resolve => setTimeout(resolve, 100));
