// What Python sends (expconfig/diagrammodel.py) is described once, in Python
// (expconfig/diagramtypes.py), and generated into model.gen.ts. Only the diagram's own
// types are written here.

export type { Card, CardAo, Cell, Issue, MinusKind, Model, Pad, Row } from "./model.gen";

// A cable end, as wiringedit.py names them.
export type Port = [kind: string, id: string | number | null];

export interface Choices {
  options: string[];
  free: boolean;
}
