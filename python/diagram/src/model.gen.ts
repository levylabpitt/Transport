// GENERATED from python/src/expconfig/diagramtypes.py: do not edit.
// Regenerate: uv run python -m expconfig.diagramtypes

export type MinusKind = "ao" | "gnd" | "nc" | "pad" | "unused" | "none";

export interface Issue {
  code: number;
  message: string;
  error: boolean;
}

export interface Cell {
  edit: boolean;   // can be changed on this row
  why: string;   // differs from the standard channel, and why
  issue: Issue | null;
}

export interface Row {
  ai: number;
  type: string;   // U (sourced), V (measured), n.c., Ground
  mode: string;   // I or gate (U), V or dV (V)
  direct: boolean;   // a U row with no Krohn-Hite: the AO drives the pad, the AI is unused
  name: string;   // the automatic label: U1, V2, V26-27
  electrode: string;
  minus: string;
  minusKind: MinusKind;
  kh: string | null;   // "A1", or null: no Krohn-Hite
  khInput: string;   // the KH input: DIFF, SE+, OFF
  khGain: string;
  couple: string;
  filter: string;
  shunt: string | null;   // only on U rows with a KH
  extGain: number;
  lockinGain: number;
  ao: number | null;   // the AO this row's cable uses
  aoSlot: number | null;   // the AO standard for this row, used or not
  aoName: string;
  outGain: number;
  outOffset: number;
  aiUsed: boolean;
  aiChannel: string;   // physical channel from the lock-in once read, "PXI1Slot2/ai0"
  aoChannel: string;
  cells: Record<string, Cell>;
  mismatch: string;
  idle: boolean;   // not connected: drawn thin, still a place to drop a pad
}

export interface CardAo {
  ao: number;
  channel: string;
  name: string;
  gain: number;
  offset: number;
  usedBy: number | null;   // the AI row whose cable uses this AO
}

/** A physical lock-in card (a DAQ device): its AIs and AOs, in front-panel order. */
export interface Card {
  device: string;   // "PXI1Slot2"; "lock-in AI n" (one per AI) until the channels are read
  read: boolean;
  type: string;   // "PXI-4461", from getDevices or the DAQ Type; "" when the lock-in does not say
  serial: string;   // DAQ serial number from getDevices (lock-in 3.10.4+); "" if unknown
  simulated: boolean;   // an NI-DAQmx simulated device
  slot: string;   // "chassis 1, slot 2" for a PXI card; "" otherwise
  ais: number[];
  aos: CardAo[];
}

export interface Pad {
  name: string;
  used: boolean;
}

export interface Model {
  pads: Pad[];   // the chip carrier's pins
  rows: Row[];   // one per lock-in AI
  cards: Card[];
  idle: number[];
  titles: Record<string, string>;   // the table's column titles, by key
  selected: [number, string | null] | null;
}
